"""MIPLIB 2017 open instances as a discovery-loop problem.

Targets are open instances (no proven optimum) small enough for a desktop; the listed value is the best known
incumbent from the official .solu file. All targets are minimisation. A win is a verified feasible solution
with a lower objective (or any feasible solution where none is known).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.miplib import records, verify

TITLE = "MIPLIB 2017 open instances"
TARGETS = [
    "assign1-10-4",
    "milo-v13-4-3d-4-0",
    "neos-3009394-lami",
    "dfn-bwin-DBE",
    "liu",
    "supportcase30",
    "neos-1420790",
    "set3-16",
    "ramos3",
    "neos-5045105-creuse",
]
DEVELOPMENT = TARGETS
VALIDATION = []
RELEASE_HOLDOUT = []
INFO = {
    "assign1-10-4": "572 vars / 582 rows, set partitioning + cardinality, mixed binary; assignment structure",
    "milo-v13-4-3d-4-0": "688 vars / 1328 rows, aggregations + variable bounds, mixed binary; HiGHS incumbent is ~3x the best known, big room",
    "neos-3009394-lami": "2757 vars / 2028 rows, set partitioning + general integers; LP bound 1.64 vs incumbent 5.5",
    "dfn-bwin-DBE": "3285 vars / 235 rows, set packing, mixed binary; few rows, many columns",
    "liu": "1156 vars / 2178 rows, precedence constraints, mixed binary (scheduling)",
    "supportcase30": "1024 binaries / 1028 rows, pure feasibility set cover; NO feasible solution is known: any feasible point is a result",
    "neos-1420790": "4926 vars / 2310 rows, decomposable set partitioning, mixed binary",
    "set3-16": "4019 vars / 3747 rows, precedence + variable bounds, mixed binary",
    "ramos3": "2187 binaries / 2187 rows, set covering; incumbent 186",
    "neos-5045105-creuse": "3848 vars / 252 rows, integer knapsacks, general integers",
}
DEFAULTS = {"time": 400, "workers": 3}
MAXIMIZE = False
FAIL_SCORE = -10.0
REL_TOL = 1e-6
RELEASE_FEASIBILITY_TOL = 1e-8
RELEASE_OBJECTIVE_REL_MARGIN = 1e-10
RELEASE_VALIDATION_SUPPORTED = True


def records_fetch():
    return records.fetch()


def records_load():
    return records.load()


def solver_argv(t, budget, seed, out):
    return ["--target", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def evaluate(path, t):
    """Independent re-verification of a solver output file. Returns (objective, payload) or raises."""
    d = json.load(open(path))
    res = verify.check(d["solution"], t)
    if res["sense"] != "min":
        raise ValueError(f"{t} is a maximisation instance; this problem module assumes minimisation")
    if not res["feasible"]:
        raise ValueError("infeasible: " + json.dumps(res)[:300])
    return res["obj"], d["solution"]


def score(v, rec):
    return 0.0 if rec is None else -(v - rec) / max(1.0, abs(rec))


def better(a, b):
    return a < b


def beats(v, rec):
    return rec is None or v < rec - REL_TOL * max(1.0, abs(rec))


def validate_release(path, t, *, record=None):
    try:
        d = json.load(open(path))
        if d.get("target", t) != t:
            raise ValueError(f"candidate target {d.get('target')!r} does not match {t!r}")
        result = verify.check(d["solution"], t, tol=RELEASE_FEASIBILITY_TOL)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "supported": True, "error": f"invalid candidate: {exc}", "metrics": {}}
    official = records.reference(t)
    reference = official["value"]
    uncertainty = official["uncertainty"] or 0.0
    numeric_margin = RELEASE_OBJECTIVE_REL_MARGIN * max(1.0, abs(reference or 0.0))
    metrics = {
        "objective": result["obj"],
        "sense": result["sense"],
        "official_status": official["status"],
        "reference": reference,
        "reference_uncertainty": official["uncertainty"],
        "bound_violation": result["bound_viol"],
        "integrality_violation": result["int_viol"],
        "row_violation": result["row_viol"],
        "feasibility_tolerance": RELEASE_FEASIBILITY_TOL,
        "claim_scope": "official_miplib_result",
    }
    if not result["feasible"]:
        return {
            "ok": False,
            "supported": True,
            "error": "candidate fails strict original-MPS verification",
            "metrics": metrics,
        }
    if reference is None:
        return {"ok": True, "supported": True, "error": None, "metrics": metrics}
    improvement = reference - result["obj"] if result["sense"] == "min" else result["obj"] - reference
    metrics["improvement"] = improvement
    if improvement <= uncertainty + numeric_margin:
        return {
            "ok": False,
            "supported": True,
            "error": "objective does not clear official reference uncertainty",
            "metrics": metrics,
        }
    return {"ok": True, "supported": True, "error": None, "metrics": metrics}


def raw_path(t, best):
    return os.path.join(best, "sol", f"{t}.json")


def sub_path(t, best):
    return os.path.join(best, "sol", f"{t}.sol")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    open(sub_path(t, best), "w").write(verify.to_sol(payload, value))
    json.dump({"target": t, "obj": value, "solution": payload}, open(raw_path(t, best), "w"))


PROMPT = """You are evolving a Python matheuristic for OPEN instances of MIPLIB 2017: real-world mixed-integer programs with no proven
optimum. The listed value is the best known incumbent, usually from long runs of commercial solvers. Every target is minimisation.
A win is a verified feasible solution with a strictly lower objective; for supportcase30 no feasible solution is known at all.

INTERFACE CONTRACT (keep exactly):
  python solver.py --target NAME --time SECONDS --seed S --out PATH
  writes JSON {"target": NAME, "obj": float, "solution": {var_name: value, ...}} listing the nonzero variables
  must finish within SECONDS (hard kill at SECONDS+45; returning early is fine); print nothing important to stdout
  save atomically (write tmp, os.replace) on EVERY improvement so a timeout still leaves the best solution on disk
  allowed imports: python stdlib, numpy, scipy, highspy (HiGHS 1.15; up to 4 threads per run is fine)
  the instance file: from records import instance_path; instance_path(NAME) -> .mps path (PYTHONPATH already includes
  problems/miplib when the loop runs you, so that import just works; keep the champion's import block)
  the solution is re-checked independently: bounds, integrality, every row within 1e-6; set HiGHS tolerances to 1e-7 and round integers
  a timeout, crash, or infeasible output scores -10 for that target, so reliability beats ambition

INSTANCE NOTES:
""" + "\n".join(f"  {k}: {v}" for k, v in INFO.items())


def prompt_for_targets(targets):
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"unknown target(s): {unknown}")
    head = PROMPT.split("INSTANCE NOTES:\n", 1)[0] + "INSTANCE NOTES:\n"
    return head + "\n".join(f"  {name}: {INFO[name]}" for name in targets)


TASK = """TASK: write a complete replacement solver.py that lowers the objective on as many targets as possible (champion total is the
negative relative gap to the best known incumbent, summed over targets). Make one substantive algorithmic improvement (or a coherent
combination). Candidates: smarter LNS neighbourhoods (RINS using the LP relaxation, local branching, row/constraint-based or
objective-guided neighbourhoods, proximity search), adaptive neighbourhood size and sub-MIP time limits, solution polishing,
exploiting structure per instance (set partitioning swap moves, set covering redundancy removal, knapsack rounding), a feasibility
pump or repair heuristic for supportcase30, tuning HiGHS options (mip_heuristic_effort, presolve, symmetry, restarts), multiple
seeds with intensification on the best basin, spending the time budget where the gap is largest. Do not repeat an idea that already
failed unless you fix its specific failure."""

TOTAL_DESC = "negative relative gap to best known, summed over targets (0 = matching every incumbent; failure = -10)"
SUBMIT_NOTE = "Candidates: best-miplib/sol/NAME.sol (MIPLIB .sol format). Verify: python problems/miplib/verify.py best-miplib/sol/NAME.json"

EMAIL_TO = "miplibsolutions@zib.de"


def email_subject(cands):
    return f"MIPLIB 2017: improved solutions for {', '.join(t for t, _, _ in cands)}"


def email_body(cands, repo_url):
    solu = os.path.basename(records.solu_path() or "solu")
    rows = "\n".join(
        f"  {t:<24} ours {v:.12g}   listed {('none known' if r is None else format(r, '.12g'))}" for t, v, r in cands
    )
    return f"""Dear MIPLIB team,

attached are .sol files ("=obj=" line followed by the nonzero variables) for the following open
instances, each with an objective better than the value in {solu}:

{rows}

All solutions were re-checked independently of the solver: variable bounds, integrality and every row
within 1e-6 absolute/relative, objective recomputed from the column costs. They were found by an
LLM-evolved large-neighbourhood-search matheuristic on top of HiGHS 1.15, on a desktop machine.

Code, checker and every candidate: {repo_url}
Please credit: Wes Sander, MoltFire (AI agent).

Thank you for maintaining MIPLIB.

Wes Sander
"""
