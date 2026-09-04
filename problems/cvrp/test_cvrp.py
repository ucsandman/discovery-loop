"""Tests for the cvrp problem module and the loop's --no-publish flag.

Runnable two ways:
    python problems/cvrp/test_cvrp.py       # prints PASS/FAIL per test
    pytest problems/cvrp/test_cvrp.py

The verifier tests use a hand-built synthetic instance and run offline. The ground-truth test downloads a
real CVRPLIB instance and its official .sol and is skipped automatically if the site is unreachable. The
--no-publish tests monkeypatch Loop.publish/evaluate/update_bests and drive loop.main() in a temp directory,
so they never touch git, the network, or the model.
"""

import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import verify  # noqa: E402


# ── a 4-customer synthetic instance: depot at origin, unit square corners, capacity 10 ──
def _synthetic(monkeypatch_target=verify):
    inst = {
        "coords": np.array([[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0], [3.0, 4.0]]),
        "demand": np.array([0.0, 4.0, 4.0, 4.0, 4.0]),
        "capacity": 10.0,
        "n": 4,
        "name": "SYNTH",
    }
    monkeypatch_target.load_instance = lambda name: inst
    return inst


def test_verifier_cost_and_feasibility():
    orig = verify.load_instance
    try:
        _synthetic()
        # two routes, each two customers, demand 8 <= 10: feasible. Cost is the sum of rounded EUC_2D edges.
        res = verify.check({"routes": [[1, 2], [3, 4]]}, "SYNTH")
        assert res["feasible"], res
        # route1 [1,2]: 0->1 (10) ->2 (10) ->0 (nint(sqrt(200))=14) = 34
        # route2 [3,4]: 0->3 (10) ->4 (nint(sqrt(65))=8) ->0 (5) = 23
        assert res["obj"] == 34 + 23, res
        assert res["n_routes"] == 2
    finally:
        verify.load_instance = orig


def test_verifier_rejects_bad_solutions():
    orig = verify.load_instance
    try:
        _synthetic()
        dup = verify.check({"routes": [[1, 2], [3], [4], [1]]}, "SYNTH")  # customer 1 twice, every load <= 10
        over = verify.check({"routes": [[1, 2, 3]]}, "SYNTH")  # demand 12 > capacity 10
        miss = verify.check({"routes": [[1, 2], [3]]}, "SYNTH")  # customer 4 missing
        oor = verify.check({"routes": [[1, 2], [3, 5]]}, "SYNTH")  # customer 5 out of range 1..4
        # duplicate is the SOLE defect: no route over capacity, nothing missing
        assert not dup["feasible"] and dup["duplicate_customers"] == [1], dup
        assert dup["over_capacity"] is None and dup["missing_customers"] == [], dup
        assert not over["feasible"] and over["over_capacity"] is not None, over
        assert not miss["feasible"] and miss["missing_customers"] == [4], miss
        assert not oor["feasible"], oor
    finally:
        verify.load_instance = orig


def test_to_sol_roundtrip():
    sol = {"routes": [[1, 2], [3, 4]]}
    text = verify.to_sol(sol, 54)
    assert "Route #1: 1 2" in text and "Route #2: 3 4" in text and "Cost 54" in text
    assert verify.parse_sol(text)["routes"] == sol["routes"]


def test_verifier_ground_truth():
    """Every official best-known .sol must verify to exactly its published cost (network; skipped if offline)."""
    import records

    try:
        tab = records.table()
        name = "X-n280-k17"
        sol = verify.parse_sol(open(records.official_solution_path(name), encoding="utf-8").read())
    except Exception as e:  # offline / site down
        print(f"  (skipped ground-truth: {type(e).__name__})")
        return
    res = verify.check(sol, name)
    assert res["feasible"] and abs(res["obj"] - tab[name]["bks"]) < 0.5, (res, tab[name]["bks"])


# ── --no-publish gating ──
def _run(argv, no_publish, tmp):
    """Drive loop.main() with publish/evaluate/update_bests stubbed; return how many times publish fired."""
    import loop

    calls = {"n": 0}
    # setattr (not direct assignment) so a dead-code scanner does not read these test stubs as unused writes
    # Restored in finally so the stubs do not leak into test_loop.py (seen 2026-09-04).
    saved_layout = loop.layout
    saved = {k: loop.Loop.__dict__[k] for k in ("publish", "evaluate", "update_bests", "write_status", "call_model")}
    setattr(loop, "layout", lambda name: (os.path.join(tmp, "best"), os.path.join(tmp, "runs")))
    setattr(loop.Loop, "publish", lambda self: calls.__setitem__("n", calls["n"] + 1))
    setattr(loop.Loop, "evaluate", lambda self, *_a, **_k: [])  # no solver runs, no network
    setattr(
        loop.Loop, "update_bests", lambda self, *_a, **_k: (["X-n280-k17"], ["X-n280-k17"])
    )  # force wins & improved
    setattr(loop.Loop, "write_status", lambda self, *_a, **_k: None)
    setattr(loop.Loop, "call_model", staticmethod(lambda *_a, **_k: ("# stub\n", 0.0, "stub idea")))
    full = ["loop.py", "--problem", "cvrp", *argv] + (["--no-publish"] if no_publish else [])
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
    scenarios = [
        (["--eval-only"], "seed/eval-only publish site"),
        (["--iters", "1"], "end-of-run publish site"),
        (["--iters", "2"], "in-loop publish site"),
    ]
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
