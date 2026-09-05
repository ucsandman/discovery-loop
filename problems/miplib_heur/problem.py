"""Evolve a general-purpose primal heuristic for mixed-integer programs, scored on MIPLIB 2017 benchmark instances
with PROVEN optima at a fixed 60 s budget.

The value per target is the relative primal gap to the proven optimum (0 = optimal), so the checker is exact.
The record to beat is what plain HiGHS (default options, 2 threads) reaches on this machine in the same slot,
measured by baseline.py and stored in baseline.json. A win is a verified feasible point whose gap is smaller
than HiGHS default by at least WIN_MARGIN. Ten holdout instances (holdout.py) catch overfitting to the train
set; instance-name special-casing is forbidden in the prompt. Publication: GitHub push (no maintainer email).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.miplib_heur import records, verify

TITLE = "MIPLIB 2017 primal heuristic vs HiGHS default (60 s)"
_BASE = json.load(open(records.BASELINE)) if os.path.exists(records.BASELINE) else {}
_TABLE = records.benchmark_table() if os.path.exists(records.TABLE) else {}
TARGETS = sorted(k for k, v in _BASE.items() if v.get("set") == "train")
HOLDOUT = sorted(k for k, v in _BASE.items() if v.get("set") == "holdout")
DEVELOPMENT = TARGETS
VALIDATION = HOLDOUT
RELEASE_HOLDOUT = []


def _desc(name):
    s = _TABLE.get(name, {})
    b = _BASE.get(name, {})
    gap = b.get("gap")
    parts = [
        f"{s.get('vars', '?')} vars ({s.get('bin', '?')} bin, {s.get('int', '?')} int, {s.get('cont', '?')} cont)",
        f"{s.get('rows', '?')} rows, {s.get('nonz', '?')} nnz",
        f"{b.get('sense', 'min')}, optimum {b.get('opt')}",
        "HiGHS default gap " + ("none feasible" if gap is None else f"{gap:.4%}"),
    ]
    if s.get("tags"):
        parts.append("tags: " + ", ".join(s["tags"]))
    return "; ".join(parts)


INFO = {t: _desc(t) for t in TARGETS}
DEFAULTS = {"time": 60, "workers": 3}
MAXIMIZE = False
FAIL_SCORE = -1.0  # added to the champion total directly (score space), so a failed target costs a 100% gap
WIN_MARGIN = 1e-4  # gap must improve on HiGHS default by 0.01% of the objective to count (timing noise floor)
RELEASE_FEASIBILITY_TOL = 1e-8
RELEASE_VALIDATION_SUPPORTED = True


def records_fetch():
    return records.fetch()


def records_load():
    return records.load()


def solver_argv(t, budget, seed, out):
    return ["--target", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def evaluate(path, t):
    """Independent re-verification. Value = relative primal gap to the proven optimum (min-sense, lower is better)."""
    d = json.load(open(path))
    res = verify.check(d["solution"], t)
    if not res["feasible"]:
        raise ValueError("infeasible: " + json.dumps(res)[:300])
    return res["gap"], {"obj": res["obj"], "solution": d["solution"]}


def score(v, rec):
    return -min(v, 1.0)  # a 100% gap is as bad as a failure; keeps one hopeless instance from dominating the total


def better(a, b):
    return a < b


def beats(v, rec):
    return v < (rec - WIN_MARGIN if rec is not None else 1e9)


def validate_release(path, t, *, record=None):
    try:
        d = json.load(open(path))
        if d.get("target", t) != t:
            raise ValueError(f"candidate target {d.get('target')!r} does not match {t!r}")
        result = verify.check(d["solution"], t, tol=RELEASE_FEASIBILITY_TOL)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "supported": True, "error": f"invalid candidate: {exc}", "metrics": {}}
    reference = records_load().get(t) if record is None else record
    metrics = {
        "objective": result["obj"],
        "gap": result["gap"],
        "historical_baseline_gap": reference,
        "bound_violation": result["bound_viol"],
        "integrality_violation": result["int_viol"],
        "row_violation": result["row_viol"],
        "feasibility_tolerance": RELEASE_FEASIBILITY_TOL,
        "validation_count": len(VALIDATION),
        "release_holdout_count": 0,
        "claim_scope": "feasible_benchmark_solution",
        "warning": "stored baseline is historical; superiority requires a fresh paired worker baseline",
    }
    if not result["feasible"]:
        return {
            "ok": False,
            "supported": True,
            "error": "candidate fails strict original-MPS verification",
            "metrics": metrics,
        }
    return {"ok": True, "supported": True, "error": None, "metrics": metrics}


def raw_path(t, best):
    return os.path.join(best, "sol", f"{t}.json")


def sub_path(t, best):
    return os.path.join(best, "sol", f"{t}.sol")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    open(sub_path(t, best), "w").write(verify.to_sol(payload["solution"], payload["obj"]))
    json.dump(
        {"target": t, "gap": value, "obj": payload["obj"], "solution": payload["solution"]},
        open(raw_path(t, best), "w"),
    )


PROMPT = """You are evolving a GENERAL-PURPOSE primal heuristic for mixed-integer programs, the kind that ships inside an open-source
solver (HiGHS). It is scored on MIPLIB 2017 benchmark instances whose optimum is PROVEN, at a fixed 60 s budget per instance:
the value per target is the relative primal gap (objective - optimum) / max(1, |optimum|) in minimisation sense, so 0 means
optimal and lower is better. The record to beat per target is the gap plain HiGHS (default options, 2 threads) reaches in the
same 60 s on this machine. A held-out set of other instances is scored separately: anything keyed on an instance's NAME, size
signature or known optimum is cheating and is rejected; only general techniques count.

INTERFACE CONTRACT (keep exactly):
  python solver.py --target NAME --time SECONDS --seed S --out PATH
  writes JSON {"target": NAME, "obj": float, "solution": {var_name: value, ...}} listing the nonzero variables
  must finish within SECONDS (hard kill at SECONDS+45; returning early is fine); print nothing important to stdout
  save atomically (write tmp, os.replace) on EVERY improvement so a timeout still leaves the best solution on disk
  allowed imports: python stdlib, numpy, scipy, highspy (HiGHS 1.15); use at most 2 HiGHS threads (three solvers run in parallel)
  the instance file: from records import instance_path; instance_path(NAME) -> .mps path (PYTHONPATH already includes
  problems/miplib_heur when the loop runs you; keep the champion's import block)
  the solution is re-checked independently: bounds, integrality, every row within 1e-6; set HiGHS tolerances to 1e-7 and
  round integers; respect the instance's own objective sense (read it from HiGHS, never assume minimisation)
  a timeout, crash, or infeasible output scores as a 100% gap for that target, so reliability beats ambition

INSTANCE NOTES (train set):
""" + "\n".join(f"  {k}: {v}" for k, v in INFO.items())


def prompt_for_targets(targets):
    unknown = sorted(set(targets) - set(DEVELOPMENT))
    if unknown:
        raise ValueError(f"generation prompt requested non-development target(s): {unknown}")
    head = PROMPT.split("INSTANCE NOTES (train set):\n", 1)[0] + "INSTANCE NOTES (development set):\n"
    return head + "\n".join(f"  {name}: {INFO[name]}" for name in targets)


TASK = """TASK: write a complete replacement solver.py that reaches a smaller primal gap on as many targets as possible within 60 s
(champion total is minus the sum of gaps over the train set). Make one substantive algorithmic improvement (or a coherent
combination) that would generalise to unseen instances. Candidates: better use of the LP relaxation (RINS / relaxation-guided
fixing, rounding + repair, diving with backtracking), local branching and proximity search, neighbourhood choice driven by
constraint structure (rows with many fixed variables, set-partitioning swap moves, knapsack rounding), adaptive sub-MIP time
limits and neighbourhood sizes, feasibility pump for instances where HiGHS finds nothing early, a smarter split of the 60 s
between HiGHS's own search and the LNS, restarts from multiple incumbents, tuning HiGHS options that affect primal progress
(mip_heuristic_effort, presolve, symmetry, mip_rel_gap for sub-MIPs). Do not repeat an idea that already failed unless you
fix its specific failure."""

TOTAL_DESC = "minus the sum of relative primal gaps over the train set (gaps clipped at 100%; 0 = optimal everywhere; a failure counts as a 100% gap)"
SUBMIT_NOTE = (
    "Candidates: best-miplib_heur/sol/NAME.sol. Verify: python problems/miplib_heur/verify.py best-miplib_heur/sol/NAME.json. "
    "Holdout check: python problems/miplib_heur/holdout.py best-miplib_heur/solver.py"
)

EMAIL_TO = None  # GitHub push is the publication; upstreaming to HiGHS is a human decision
