"""Packomania csqv (pack N variable-radius circles in the unit square, maximise the sum of radii) as a discovery-loop problem."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.circle_packing import records, verify

TITLE = "circle packing (Packomania csqv)"
TARGETS = ["26", "32", "101", "102", "103", "105", "106", "107", "108", "109", "111", "114"]
DEVELOPMENT = TARGETS
VALIDATION = []
RELEASE_HOLDOUT = []
DEFAULTS = {"time": 120, "workers": 3}
PATTERN_TAGS = ["continuous", "fast-verifier", "local-search", "generatable-test-cases"]
MAXIMIZE = True
FAIL_SCORE = 0.0
WIN_MARGIN = 1e-10
RELEASE_WALL_MARGIN = 1e-10
RELEASE_PAIR_SQ_MARGIN = 1e-12
RELEASE_VALIDATION_SUPPORTED = True

# Prize-contract descriptor (prize_contract.validate_prize_plugin). Nothing here changes how the
# plugin runs; it records what this benchmark is measured against for the prize board. This plugin
# withholds no targets: confirmation re-runs the development set under fresh seeds, so the holdout
# benchmark is that same set and measures repeatability, not generalization.
PRIZE = {
    "objective": (
        "Raise the verified sum of radii on the Packomania csqv targets above the frozen incumbent, "
        "with containment and separation checked outside the generated solver."
    ),
    "candidate_artifact": "problems/circle_packing/solver.py written by the loop (CLI: --n --time --seed --out)",
    "baseline": "problems/circle_packing/seed_solver.py",
    "development_benchmark": list(TARGETS),
    "holdout_benchmark": list(TARGETS),
    "independent_verifier": "problems/circle_packing/verify.py",
    "fitness_metrics": ["sum", "min_wall_slack", "min_pair_slack_sq"],
    "real_target": (
        "The Packomania csqv best-known table (N = 101..114). Ten entries from this lab were reviewed and "
        "accepted upstream in September 2026; the remaining entries are unchanged public records."
    ),
    "prize_registry_id": "packomania-csqv-records",
    "promotion_threshold": {"min_effect": 0.0001, "seed_count": 3, "holdout_required": True},
    "estimated_scaling": (
        "Cost grows with N through the local-search neighbourhood, not through a search exponent; there is no "
        "measured scaling law for this plugin and prize_scaling reports it as unsupported."
    ),
    "publication_requirements": (
        "An exact .pck submission, the matched-seed confirmation rows, and the verifier output at the release "
        "margins. Publication goes through the existing dashboard approval bound to file hashes."
    ),
    "submission_requirements": (
        "Nothing is submitted automatically. A verified improvement is drafted under the run's publish/ directory "
        "and sent by hand to the contacts in problems/circle_packing/contacts.json after approval."
    ),
}


def records_fetch():
    return {str(k): v for k, v in records.fetch().items()}


def records_load():
    return {str(k): v for k, v in records.load().items()}


def solver_argv(t, budget, seed, out):
    return ["--n", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def evaluate(path, t):
    d = json.load(open(path))
    res = verify.check(d["circles"], int(t))
    if not res["feasible"]:
        raise ValueError("infeasible: " + json.dumps(res)[:300])
    return res["sum"], d["circles"]


def score(v, rec):
    return v


def better(a, b):
    return a > b


def beats(v, rec):
    return rec is not None and v > rec + WIN_MARGIN


def validate_release(path, t, *, record=None):
    """Recheck a packing with clearance beyond float noise and the published table precision."""
    try:
        d = json.load(open(path))
        result = verify.check(d["circles"], int(t))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "supported": True, "error": f"invalid candidate: {exc}", "metrics": {}}
    metrics = {k: result.get(k) for k in ("sum", "min_wall_slack", "min_pair_slack_sq")}
    if not result.get("feasible"):
        return {"ok": False, "supported": True, "error": result.get("error", "infeasible packing"), "metrics": metrics}
    if result["min_wall_slack"] < RELEASE_WALL_MARGIN:
        return {"ok": False, "supported": True, "error": "packing lacks required wall clearance", "metrics": metrics}
    if result["min_pair_slack_sq"] < RELEASE_PAIR_SQ_MARGIN:
        return {"ok": False, "supported": True, "error": "packing lacks required pair clearance", "metrics": metrics}
    reference = records_load().get(str(t)) if record is None else record
    metrics.update({"record": reference, "win_margin": WIN_MARGIN})
    if not beats(result["sum"], reference):
        return {
            "ok": False,
            "supported": True,
            "error": "objective does not clear the record margin",
            "metrics": metrics,
        }
    return {"ok": True, "supported": True, "error": None, "metrics": metrics}


def raw_path(t, best):
    return os.path.join(best, "pck", f"csqv{t}.json")


def sub_path(t, best):
    return os.path.join(best, "pck", f"csqv{t}.pck")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "pck"), exist_ok=True)
    open(sub_path(t, best), "w").write(verify.to_pck(payload, author))
    json.dump({"n": int(t), "circles": payload}, open(raw_path(t, best), "w"))


PROMPT = """You are evolving a Python solver for the Packomania csqv benchmark:
pack N circles of variable radius in the unit square [0,1]^2, no two overlapping, all fully inside, MAXIMISE the sum of radii.
Best-known records are tight; wins come from better optimisation, not tricks. Every packing is checked with zero tolerance.

INTERFACE CONTRACT (keep exactly):
  python solver.py --n N --time SECONDS --seed S --out PATH
  writes JSON {"n": N, "circles": [[x, y, r], ...]} (corner convention, square is [0,1]^2)
  must finish within SECONDS (hard kill at SECONDS+45; returning early is fine); print nothing important to stdout
  allowed imports: python stdlib, numpy, scipy (torch with an 8GB CUDA GPU is available but optional)
  the result must be STRICTLY feasible in float64 (wall slack >= 0, d^2 >= (ri+rj)^2 for all pairs, r > 0); keep a final shrink step
  a timeout, crash, or infeasible output scores 0 for that N, so reliability beats ambition"""


def prompt_for_targets(targets):
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"unknown target(s): {unknown}")
    return PROMPT


TASK = """TASK: write a complete replacement solver.py that raises the total sum of radii across the target Ns.
Make one substantive algorithmic improvement (or a coherent combination). Candidates: smarter initialisation (hex/square lattices with
defect circles, corner-first large circles, reuse of the N-1 structure), basin hopping / perturb-and-repolish of the incumbent instead of
cold restarts, active-set Newton or SLSQP polish on the contact graph after the penalty phase, alternating LP-radii / centre moves,
swap/relocate moves for the smallest circles into the largest holes, adaptive penalty schedules, using the full time budget on the
best basin rather than many weak restarts. Do not repeat an idea that already failed unless you fix its specific failure."""

TOTAL_DESC = "sum of radii summed over the target Ns"
SUBMIT_NOTE = "Record candidates: best/pck/csqvN.pck (Packomania submission format). Verify: python problems/circle_packing/verify.py best/pck/csqvN.json"

EMAIL_TO = "eckard.specht@ovgu.de"  # Packomania maintainer, mailto on packomania.com


def email_subject(cands):
    return f"csqv: {len(cands)} new candidate packing{'s' if len(cands) > 1 else ''} (N={','.join(t for t, _, _ in cands)})"


def email_body(cands, repo_url):
    rows = "\n".join(f"  N={t:<4} ours {v:.12f}   listed {r:.12f}   +{v - r:.2e}" for t, v, r in cands)
    plural = "s" if len(cands) > 1 else ""
    return f"""Dear Eckard Specht,

attached are {len(cands)} candidate packing{plural} for the csqv table
(circles of variable radii in the unit square, maximising the sum of radii), in the .pck
format from your hints page: square of side 1 centred at the origin, one "x y r" line per
circle sorted by increasing radius, 16 decimals.

{rows}

The packings come from an LLM-evolved optimiser (penalty L-BFGS-B, basin hopping on the
incumbent, contact-graph SLSQP polish) and were checked with an independent zero-tolerance
verifier: every circle strictly inside the square and d^2 >= (ri+rj)^2 for every pair in
float64. Authors: Wes Sander, MoltFire (AI agent).

Code, checker and every candidate: {repo_url}

Thank you for maintaining Packomania.

Wes Sander
"""
