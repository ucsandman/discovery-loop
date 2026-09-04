"""MIPLIB 2017 OPEN instances as a discovery-loop problem: beat a PUBLISHED best-known objective.

An open instance has a known feasible solution but no optimality proof, so the best-known objective on the
MIPLIB site is a live, externally meaningful bar: a verified feasible point strictly below it (for a min
instance; above, for a max instance) is a genuine result that ZIB credits and lists. Unlike miplib_heur,
whose "record" is HiGHS-default on this PC, the record here is the world's best-known primal value, found by
serious solvers over years. Value per target = (obj - best_known)/max(1,|best_known|) in min-sense (max-sense
instances converted), so 0 ties the best-known and NEGATIVE beats it. A verified win is pushed to GitHub and
emailed to miplibsolutions@zib.de (EMAIL_TO) through the approval-gated seam in publish.py (Wes approves on
Telegram before anything leaves). Beating a MIPLIB open best-known in minutes on one PC is a long
shot; the durable deliverable is an honest, independently verified scoreboard.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import records  # noqa: E402
import verify  # noqa: E402

TITLE = "MIPLIB 2017 OPEN instances vs published best-known"
TARGETS = list(records.TARGETS)
DEFAULTS = {"time": 600, "workers": 3}  # justified from a measured seed run in BASELINE.md
MAXIMIZE = False  # value is min-sense (lower is better); the loop maximises total = minus the summed value
FAIL_SCORE = -1.0  # a crash / timeout / infeasible output, in score space (worse than any clipped feasible gap)
GAP_CLIP = 1.0  # one hopeless instance (100% above best-known) cannot dominate the champion total
# A win must clear the best-known by more than the verifier can be wrong. verify enforces every bound/row
# within 1e-6 relative, so a feasible objective is trustworthy to ~1e-6 relative; requiring value < -1e-6
# means the objective beats best-known by more than that verification noise (exploiting the 1e-6 slack could
# move the objective by at most ~1e-6 relative). A real submission is re-checked by ZIB's exact checker too.
WIN_MARGIN = 1e-6


def _desc(name):
    r = records.table().get(name, {})
    parts = [
        f"{r.get('vars', '?')} vars ({r.get('bin', '?')} bin, {r.get('int', '?')} int, {r.get('cont', '?')} cont)",
        f"{r.get('rows', '?')} rows, {r.get('nonz', '?')} nnz",
        f"{r.get('sense', 'min')}, best-known {r.get('best_known')}"
        + (f" (set {r['date']}, {r['age_years']}y ago)" if r.get("date") else ""),
    ]
    if r.get("highs_gap") is not None:
        parts.append(f"HiGHS-default 120s gap {r['highs_gap']:+.4%}")
    if r.get("tags"):
        parts.append("tags: " + ", ".join(r["tags"]))
    return "; ".join(parts)


INFO = {t: _desc(t) for t in TARGETS}


def records_fetch():
    return records.fetch()


def records_load():
    return records.load()


def solver_argv(t, budget, seed, out):
    return ["--target", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def evaluate(path, t):
    """Independent re-verification. Value = relative gap to best-known (min-sense: 0 ties, negative beats)."""
    d = json.load(open(path))
    res = verify.check(d["solution"], t)
    if not res["feasible"]:
        raise ValueError(
            "infeasible: "
            + json.dumps({k: res[k] for k in ("bound_viol", "int_viol", "row_viol", "unknown_vars")})[:300]
        )
    return res["value"], {"obj": res["obj"], "solution": d["solution"]}


def score(v, rec):
    return -min(v, GAP_CLIP)  # lower value is better; beating best-known (v<0) scores positive


def better(a, b):
    return a < b


def beats(v, rec):
    """A win: value below the tie point (0.0) by more than WIN_MARGIN. rec is 0.0 in value space."""
    ref = rec if rec is not None else 0.0
    return v < ref - WIN_MARGIN


def raw_path(t, best):
    return os.path.join(best, "sol", f"{t}.json")


def sub_path(t, best):
    return os.path.join(best, "sol", f"{t}.sol")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    open(sub_path(t, best), "w").write(f"# {author}\n" + verify.to_sol(payload["solution"], payload["obj"]))
    json.dump(
        {
            "target": t,
            "value": value,
            "obj": payload["obj"],
            "best_known": records.best_known(t),
            "solution": payload["solution"],
            "author": author,
        },
        open(raw_path(t, best), "w"),
    )


PROMPT = """You are evolving a Python solver that searches for the best possible feasible solution to MIPLIB 2017 OPEN instances:
mixed-integer programs for which a feasible solution is known but optimality has never been proven, so the published best-known
objective is a live world record found by strong commercial solvers over years, not a proven optimum. The value per target is the
relative gap to that best-known: (objective - best_known)/max(1,|best_known|) for a minimisation instance, (best_known - objective)/
max(1,|best_known|) for a maximisation instance, so it is in minimisation sense (lower is better): 0 ties the best-known and a
NEGATIVE value means you beat it. Beating one is a genuine, externally creditable result and is hard.

INTERFACE CONTRACT (keep exactly):
  python solver.py --target NAME --time SECONDS --seed S --out PATH
  writes JSON {"target": NAME, "obj": float, "solution": {var_name: value, ...}} listing the nonzero variables
  must finish within SECONDS (hard kill at SECONDS+45; returning early is fine); print nothing important to stdout
  save atomically (write tmp, os.replace) on EVERY improvement so a timeout still leaves the best solution on disk
  allowed imports: python stdlib, numpy, scipy, highspy (HiGHS 1.15); use at most 2 HiGHS threads (three solvers run in parallel)
  the instance file: from records import instance_path; instance_path(NAME) -> .mps path (PYTHONPATH already includes
  problems/miplib_open when the loop runs you; keep the champion's import block)
  the solution is re-checked independently: bounds, integrality, every row within 1e-6; set HiGHS tolerances to 1e-7 and
  round integers; read the instance's own objective sense from HiGHS and never assume minimisation
  a timeout, crash, or infeasible output scores as a 100% gap for that target, so reliability beats ambition
  NEVER special-case an instance: keying on an instance's NAME, its size signature, its best-known value, or any per-instance
  constant is forbidden and defeats the purpose. Only general MIP-search techniques count.

INSTANCE NOTES:
""" + "\n".join(f"  {k}: {v}" for k, v in INFO.items())

TASK = """TASK: write a complete replacement solver.py that reaches a smaller gap to best-known on as many targets as possible within
the budget (champion total is minus the sum of gaps over the targets; beating a target counts positive). Make one substantive,
general algorithmic improvement (or a coherent combination): large-neighbourhood search around the incumbent (RINS / relaxation-
induced neighbourhoods, local branching, proximity search), diving with backtracking, feasibility pump when HiGHS finds nothing
early, adaptive sub-MIP time limits and neighbourhood sizes driven by constraint structure, restarts from multiple incumbents,
polishing with objective-cutoff constraints, and tuning HiGHS options that affect primal progress (mip_heuristic_effort, presolve,
symmetry). These instances are open because they are hard, so pour the extra budget into escaping the incumbent HiGHS finds. Do
not repeat an idea that already failed unless you fix its specific failure."""

TOTAL_DESC = "minus the sum of relative gaps to best-known over the targets (gaps clipped at 100%; 0 = ties every best-known; a failure counts as a 100% gap)"
SUBMIT_NOTE = (
    "Candidates: best-miplib_open/sol/NAME.sol (MIPLIB .sol format). Verify: python problems/miplib_open/verify.py "
    "best-miplib_open/sol/NAME.json. A verified improvement on an open instance is emailed to "
    "miplibsolutions@zib.de by publish.py after Wes approves the send on Telegram (ZIB credits it in the next "
    "site update)."
)

# ZIB accepts improved open-instance solutions by email. Home page (2026-09-04): "Contributions of new
# solutions to open instances are always welcome ... Please send your submissions to miplibsolutions@zib.de".
# publish.py re-verifies every candidate, then sends through invoke-capability (DashClaw pending approval,
# Wes approves on Telegram, moltfire@ sends). Enabled 2026-09-04 on Wes's instruction: auto-email verified wins.
EMAIL_TO = "miplibsolutions@zib.de"


def _objective(t, v):
    """Exact objective for the email: from the saved candidate if present, else derived from the gap value."""
    raw = os.path.join(HERE, "..", "..", "best-miplib_open", "sol", f"{t}.json")
    try:
        return float(json.load(open(raw))["obj"])
    except (OSError, KeyError, ValueError):
        r = records.table().get(t, {})
        bk = float(r.get("best_known", 0.0))
        span = max(1.0, abs(bk))
        return bk - v * span if r.get("sense") == "max" else bk + v * span


def email_subject(cands):
    return f"MIPLIB 2017 open instances: improved solutions for {', '.join(t for t, _, _ in cands)}"


def email_body(cands, repo_url):
    rows = []
    for t, v, _ in cands:
        r = records.table().get(t, {})
        rows.append(
            f"  {t:<24} ours {_objective(t, v):.12g}   listed {r.get('best_known')}"
            f"   ({r.get('sense', 'min')}, {v:+.3e} relative)"
        )
    rows = "\n".join(rows)
    return f"""Dear MIPLIB team,

attached are .sol files ("=obj=" line followed by the nonzero variables) for the following OPEN
instances, each with an objective strictly better than the best-known value in the current .solu file:

{rows}

Every solution was re-checked independently of the solver: variable bounds, integrality and every row
within 1e-6, objective recomputed from the column costs. They were found by an LLM-evolved
large-neighbourhood-search matheuristic on top of HiGHS 1.15, running overnight on a desktop machine.

Code, checker and every candidate: {repo_url}
Please credit: Wes Sander, MoltFire (AI agent).

Thank you for maintaining MIPLIB.

Wes Sander
"""
