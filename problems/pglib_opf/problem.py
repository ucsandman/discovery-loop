"""PGLib-OPF AC optimal power flow as a discovery-loop problem.

Targets are the "typical operating conditions" cases of the IEEE PES PGLib-OPF benchmark (v23.07) up to 793 buses.
The listed value is the AC-OPF objective ($/h) that PowerModels.jl + IPOPT reached, from the repo's BASELINE.md,
given to five significant figures. AC-OPF is nonconvex, so that value is a local optimum: a win is a solution the
independent verifier accepts at 1e-8 pu whose cost is below the listed value by more than the table's rounding.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.pglib_opf import records, verify

TITLE = "PGLib-OPF AC optimal power flow (TYP)"
TARGETS = [
    "pglib_opf_case3_lmbd",
    "pglib_opf_case5_pjm",
    "pglib_opf_case14_ieee",
    "pglib_opf_case24_ieee_rts",
    "pglib_opf_case30_as",
    "pglib_opf_case30_ieee",
    "pglib_opf_case39_epri",
    "pglib_opf_case57_ieee",
    "pglib_opf_case60_c",
    "pglib_opf_case73_ieee_rts",
    "pglib_opf_case89_pegase",
    "pglib_opf_case118_ieee",
    "pglib_opf_case162_ieee_dtc",
    "pglib_opf_case179_goc",
    "pglib_opf_case197_snem",
    "pglib_opf_case200_activ",
    "pglib_opf_case240_pserc",
    "pglib_opf_case300_ieee",
    "pglib_opf_case500_goc",
    "pglib_opf_case588_sdet",
    "pglib_opf_case793_goc",
]
DEVELOPMENT = TARGETS
VALIDATION = []
RELEASE_HOLDOUT = []
DEFAULTS = {"time": 90, "workers": 4}
MAXIMIZE = False
FAIL_SCORE = -1.0
WIN_MARGIN = 1e-4  # conservative preliminary screen; release validation uses each row's exact printed uncertainty
RELEASE_FEASIBILITY_TOL = 1e-8
RELEASE_OBJECTIVE_REL_MARGIN = 1e-8
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
    res = verify.check(d["solution"], t, tol=RELEASE_FEASIBILITY_TOL)
    if not res["feasible"]:
        raise ValueError(
            f"infeasible ({res['n_violations']} violations, worst {res['max_violation']:.3g}): {res['worst']}"
        )
    return res["obj"], d["solution"]


def score(v, rec):
    """Negative relative gap to the published objective, clipped at -1; positive when below the baseline."""
    return 0.0 if rec is None else -min((v - rec) / max(1.0, abs(rec)), 1.0)


def better(a, b):
    return a < b


def beats(v, rec):
    return rec is not None and v < rec - max(abs(rec) * WIN_MARGIN, RELEASE_OBJECTIVE_REL_MARGIN)


def validate_release(path, t, *, record=None):
    """Strictly check the original case and corroborate it with an original-problem reference polish."""
    try:
        d = json.load(open(path))
        result = verify.check(d["solution"], t, tol=RELEASE_FEASIBILITY_TOL)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "supported": True, "error": f"invalid candidate: {exc}", "metrics": {}}
    baseline = records_load().get(t) if record is None else record
    uncertainty = records.baseline_uncertainty(t)
    numeric_margin = RELEASE_OBJECTIVE_REL_MARGIN * max(1.0, abs(baseline))
    threshold = baseline - uncertainty - numeric_margin
    metrics = {
        "objective": result["obj"],
        "baseline": baseline,
        "baseline_rounding_uncertainty": uncertainty,
        "release_threshold": threshold,
        "max_violation": result["max_violation"],
        "feasibility_tolerance": RELEASE_FEASIBILITY_TOL,
    }
    if not result["feasible"]:
        return {
            "ok": False,
            "supported": True,
            "error": "candidate violates the original PGLib case at the release tolerance",
            "metrics": metrics,
        }
    if not result["obj"] < threshold:
        return {
            "ok": False,
            "supported": True,
            "error": "objective does not clear baseline uncertainty",
            "metrics": metrics,
        }
    try:
        reference = verify.reference_polish(d["solution"], t, tol=RELEASE_FEASIBILITY_TOL)
    except Exception as exc:
        return {
            "ok": False,
            "supported": True,
            "error": f"original-problem reference polish failed: {exc}",
            "metrics": metrics,
        }
    checked = reference.get("check") or {}
    metrics.update(
        {
            "reference_objective": checked.get("obj"),
            "reference_max_violation": checked.get("max_violation"),
            "reference_success": reference.get("success", False),
        }
    )
    if not reference.get("success") or not checked.get("obj", float("inf")) < threshold:
        return {
            "ok": False,
            "supported": True,
            "error": reference.get("error") or "reference polish did not confirm the improvement",
            "metrics": metrics,
        }
    return {"ok": True, "supported": True, "error": None, "metrics": metrics}


def raw_path(t, best):
    return os.path.join(best, "sol", f"{t}.json")


def sub_path(t, best):
    return os.path.join(best, "sol", f"{t}.txt")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    json.dump({"target": t, "obj": value, "solution": payload, "author": author}, open(raw_path(t, best), "w"))
    open(sub_path(t, best), "w").write(f"# {author}\n" + verify.to_text(payload, value, t))


PROMPT = """You are evolving a Python AC optimal power flow (AC-OPF) solver for the PGLib-OPF benchmark (IEEE PES task force,
v23.07, typical operating conditions). Each case is a MATPOWER network: buses with loads and shunts, generators with
P/Q limits and polynomial cost curves, branches with impedance, line charging, tap/shift transformers, thermal limits
and angle-difference limits. Minimise total generation cost ($/h) subject to the full nonconvex AC power flow
equations. The listed value per case is what PowerModels.jl + IPOPT (interior point, one start) reached; it is a
LOCAL optimum. A win is a verified feasible solution with a lower cost, so the game is finding better local optima
and being feasible to 1e-8 on the original case, every run.

INTERFACE CONTRACT (keep exactly):
  python solver.py --target NAME --time SECONDS --seed S --out PATH
  writes JSON {"target": NAME, "obj": float, "solution": {"vm": [pu per bus], "va": [radians per bus],
               "pg": [pu per generator row], "qg": [pu per generator row]}} in the case file's row order
  must finish within SECONDS (hard kill at SECONDS+45; returning early is fine); print nothing important to stdout
  save atomically (write tmp, os.replace) on EVERY verified improvement so a timeout still leaves a solution on disk
  allowed imports: python stdlib, numpy, scipy, pypower (PIPS interior point: pypower.api.runopf / runpf / ppoption)
  helpers on PYTHONPATH: matpower.load(path) -> dict of numpy arrays with column constants (mp.VM, mp.PG, ...);
    records.case_path(NAME) -> local .m file; verify.check(solution, NAME) -> {"feasible", "obj", "max_violation",
    "worst"} is the SAME checker the loop uses: call it before writing, never write an unverified solution
  the checker enforces, at 1e-8 pu / degrees: voltage bounds, P/Q limits (zero for status-0 gens), nodal P and Q
    balance at every bus, apparent-power limits at BOTH branch ends, angle-difference limits, reference angle 0
  an infeasible output, crash, or timeout scores -1 for that case, so reliability beats ambition

CASES: 3 to 793 buses. PIPS solves every case in under 6 s from a flat start, so the budget buys many restarts."""


def prompt_for_targets(targets):
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"unknown target(s): {unknown}")
    return PROMPT


TASK = """TASK: write a complete replacement solver.py that lowers the verified cost on as many cases as possible (champion total
is the negative relative gap to the published value, summed over cases; beating a case counts positive). Make one
substantive algorithmic improvement (or a coherent combination). Candidates: smarter multi-start (Latin hypercube
over voltage set-points and dispatch, restarts from perturbed incumbents, basin hopping on generator set-points),
continuation from the DC-OPF or a convex relaxation solution, penalty or augmented-Lagrangian reformulations solved
with scipy, different interior-point settings and constraint scalings, exploiting that many cases have binding
thermal or angle limits (relax then tighten), coordinate moves on reactive dispatch and transformer taps, spending
the time budget where the case is largest or the incumbent is weakest. Do not repeat an idea that already failed
unless you fix its specific failure."""

TOTAL_DESC = "negative relative gap to the published IPOPT objective, summed over cases (0 = matching; failure = -1)"
SUBMIT_NOTE = (
    "Candidates: best-pglib_opf/sol/NAME.json (+ .txt dispatch summary). Verify: python problems/pglib_opf/verify.py "
    "best-pglib_opf/sol/NAME.json. Wins are reported to the pglib-opf issue tracker by hand; nothing is emailed."
)

EMAIL_TO = None


def email_subject(cands):
    return f"PGLib-OPF: improved AC-OPF objectives for {', '.join(t for t, _, _ in cands)}"


def email_body(cands, repo_url):
    rows = "\n".join(f"  {t:<28} ours {v:.6f}   listed {r:.6g}" for t, v, r in cands)
    return f"Verified AC-OPF solutions below the BASELINE.md objective:\n\n{rows}\n\nCode and checker: {repo_url}\n"
