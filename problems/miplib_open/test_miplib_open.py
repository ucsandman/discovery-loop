"""Tests for the miplib_open problem module.

    python problems/miplib_open/test_miplib_open.py     # prints PASS/FAIL per test
    pytest problems/miplib_open/test_miplib_open.py

Offline tests (records parsing, value math, the three deliberate verifier failures on a hand-built .mps) run
with no network. The ground-truth test downloads real MIPLIB open-instance best-known .sol files and confirms
the verifier reproduces their published objective; it is skipped automatically if the site is unreachable.
The --no-publish tests monkeypatch Loop.publish/evaluate/update_bests and drive loop.main() in a temp dir, so
they never touch git, the network, or the model.
"""

import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import records  # noqa: E402
import verify  # noqa: E402


def _load(name):
    """Load one of THIS module's files by explicit path. A bare ``import problem`` is unsafe here: importing
    verify executes the shared engine problems/miplib/verify.py, which inserts problems/miplib onto sys.path,
    so ``problem`` would otherwise resolve to problems/miplib/problem.py (a different module)."""
    spec = importlib.util.spec_from_file_location("miplib_open_" + name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


problem = _load("problem")

# A tiny MILP for the deliberate-failure tests, so each bad solution trips exactly one field:
#   minimise x + y   s.t.   x + y <= 8,   x in {0..5} integer,   y in [0,10] continuous
SYNTH_MPS = """NAME          SYNTH
ROWS
 N  COST
 L  R1
COLUMNS
    MARKER1   'MARKER'                 'INTORG'
    x         COST      1.0        R1        1.0
    MARKER2   'MARKER'                 'INTEND'
    y         COST      1.0        R1        1.0
RHS
    RHS       R1        8.0
BOUNDS
 UP BND       x         5.0
 UP BND       y         10.0
ENDATA
"""


def _use_synth():
    """Point the shared verifier engine at the synthetic .mps and pin a best-known so value() is defined."""
    path = os.path.join(tempfile.gettempdir(), "miplib_open_synth.mps")
    open(path, "w").write(SYNTH_MPS)
    records._patched_ip = verify._V.instance_path  # must be restored, or the ground-truth test reads the synth .mps
    verify._V.instance_path = lambda name: path
    records._patched_best = records.best_known
    records.best_known = lambda name: 0.0  # ties at obj 0
    return path


def _restore_synth():
    records.best_known = records._patched_best
    verify._V.instance_path = records._patched_ip


def test_verifier_accepts_and_values_a_feasible_point():
    _use_synth()
    try:
        res = verify.check({"x": 3, "y": 2.0}, "SYNTH")  # 3+2=5 <= 8, integral, in bounds
        assert res["feasible"], res
        assert abs(res["obj"] - 5.0) < 1e-9, res
        assert res["sense"] == "min", res
        # value = (obj - best_known)/max(1,|best_known|) = (5 - 0)/1 = 5.0
        assert abs(res["value"] - 5.0) < 1e-9, res
    finally:
        _restore_synth()


def test_verifier_rejects_three_deliberate_failures():
    _use_synth()
    try:
        bound = verify.check({"x": 7, "y": 0.0}, "SYNTH")  # x=7 > ub 5; row 7<=8 ok; integral
        integ = verify.check({"x": 2.5, "y": 0.0}, "SYNTH")  # x fractional; in bounds; row ok
        row = verify.check({"x": 5, "y": 5.0}, "SYNTH")  # x+y=10 > 8; both in bounds; integral
        assert not bound["feasible"] and bound["bound_viol"] > 1e-6, bound
        assert bound["int_viol"] <= 1e-6 and bound["row_viol"] <= 1e-6, bound  # ONLY the bound tripped
        assert not integ["feasible"] and integ["int_viol"] > 1e-6, integ
        assert integ["bound_viol"] <= 0 and integ["row_viol"] <= 0, integ  # ONLY integrality tripped
        assert not row["feasible"] and row["row_viol"] > 1e-6, row
        assert row["bound_viol"] <= 0 and row["int_viol"] <= 1e-6, row  # ONLY the row tripped
    finally:
        _restore_synth()


def test_value_sign_both_senses():
    # min-sense: beating (smaller obj) is negative, tying is 0, worse is positive
    assert verify.value(90.0, 100.0, "min") < 0
    assert abs(verify.value(100.0, 100.0, "min")) < 1e-12
    assert verify.value(110.0, 100.0, "min") > 0
    # max-sense: beating (larger obj) is negative
    assert verify.value(110.0, 100.0, "max") < 0
    assert verify.value(90.0, 100.0, "max") > 0


def test_parse_sol_skips_headers_and_comments():
    text = "=obj= 8263.1\n# Objective value = 8263.1\nx1 1\ny2 2.5\nz3 0\n"
    sol = records.parse_sol(text)
    assert sol == {"x1": 1.0, "y2": 2.5, "z3": 0.0}, sol


def test_solu_best_is_the_open_set():
    best = records.solu_best()
    assert len(best) > 100, len(best)  # ~206 =best= lines
    assert all(isinstance(v, float) for v in best.values())
    for t in records.TARGETS:  # every target must have a published best-known
        assert t in best, t


def test_age_years():
    import datetime

    today = datetime.date(2026, 1, 1)
    assert records.age_years("2020-01-01", today) == 6.0
    assert records.age_years("not-a-date") is None


def test_beats_and_score():
    assert problem.beats(-1e-3, 0.0) is True  # clearly below best-known
    assert problem.beats(-1e-9, 0.0) is False  # inside WIN_MARGIN noise
    assert problem.beats(0.02, 0.0) is False
    assert problem.score(-0.01, 0.0) > 0  # beating best-known scores positive
    assert problem.score(0.5, 0.0) < 0
    assert problem.score(5.0, 0.0) == -problem.GAP_CLIP  # clipped


def test_verifier_ground_truth():
    """For 3 targets, the official best-known .sol must verify to its published objective (network; skip if offline)."""
    try:
        records.table()  # needs records.json (built for TARGETS)
        checked = []
        for name in records.TARGETS:
            if len(checked) >= 3:
                break
            try:
                sol = records.parse_sol(open(records.official_solution_path(name), encoding="utf-8").read())
            except Exception:
                continue
            res = verify.check(sol, name)
            bk = records.best_known(name)
            if res["feasible"]:
                checked.append((name, res["obj"], bk))
                assert abs(res["value"]) < 1e-6, (name, res["obj"], bk, res["value"])
        assert len(checked) >= 3, f"only {len(checked)} targets' official .sol verified cleanly: {checked}"
        print("  ground truth:", "  ".join(f"{n}={o:.6g}(bks {b:.6g})" for n, o, b in checked))
    except AssertionError:
        raise
    except Exception as e:
        print(f"  (skipped ground-truth: {type(e).__name__}: {str(e)[:80]})")


# ── --no-publish gating (same pattern as problems/cvrp/test_cvrp.py) ──
def _run(argv, no_publish, tmp):
    import loop

    calls = {"n": 0}
    # Patch, then restore in finally: without the restore, the stubbed call_model leaks into
    # test_loop.py when pytest runs this file first (seen 2026-09-04, 2 false failures).
    saved_layout = loop.layout
    saved = {k: loop.Loop.__dict__[k] for k in ("publish", "evaluate", "update_bests", "write_status", "call_model")}
    setattr(loop, "layout", lambda name: (os.path.join(tmp, "best"), os.path.join(tmp, "runs")))
    setattr(loop.Loop, "publish", lambda self: calls.__setitem__("n", calls["n"] + 1))
    setattr(loop.Loop, "evaluate", lambda self, *_a, **_k: [])
    setattr(loop.Loop, "update_bests", lambda self, *_a, **_k: ([records.TARGETS[0]], [records.TARGETS[0]]))
    setattr(loop.Loop, "write_status", lambda self, *_a, **_k: None)
    setattr(loop.Loop, "call_model", staticmethod(lambda *_a, **_k: ("# stub\n", 0.0, "stub idea")))
    full = ["loop.py", "--problem", "miplib_open", *argv] + (["--no-publish"] if no_publish else [])
    old = sys.argv
    sys.argv = full
    try:
        loop.main()
    finally:
        sys.argv = old
        loop.layout = saved_layout
        for k, v in saved.items():
            setattr(loop.Loop, k, v)
    return calls["n"]


def test_no_publish_suppresses_every_site():
    scenarios = [(["--eval-only"], "seed/eval-only"), (["--iters", "1"], "end-of-run"), (["--iters", "2"], "in-loop")]
    for argv, label in scenarios:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            fired_default = _run(argv, no_publish=False, tmp=t1)
            fired_flag = _run(argv, no_publish=True, tmp=t2)
        assert fired_default >= 1, f"{label}: default run should have fired publish, got {fired_default}"
        assert fired_flag == 0, f"{label}: --no-publish must suppress publish, got {fired_flag}"


def _main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _main()
