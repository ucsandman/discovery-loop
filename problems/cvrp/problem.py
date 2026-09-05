"""CVRPLIB X capacitated vehicle routing (Uchoa et al. 2017) as a discovery-loop problem.

Targets are ten X instances (200-500 nodes) whose best known solution is NOT proven optimal, so the listed
value -- the best-known cost from the live CVRPLIB table -- is beatable. Every target is minimisation. A win
is a solution the independent verifier accepts (every customer served once, routes within capacity) whose
total rounded-EUC_2D cost is below the best known. Vehicle routing is fuel, miles and delivery cost for every
fleet, so a better route is money and emissions saved.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.cvrp import records, verify

TITLE = "CVRPLIB X capacitated vehicle routing (open instances)"
TARGETS = list(records.TARGETS)
DEVELOPMENT = TARGETS
VALIDATION = []
RELEASE_HOLDOUT = []
DEFAULTS = {"time": 120, "workers": 3}
MAXIMIZE = False
FAIL_SCORE = -1.0  # a crash / timeout / infeasible output; strictly worse than any feasible run (gap clipped at 0.5)
GAP_CLIP = 0.5
RELEASE_VALIDATION_SUPPORTED = True


def _info():
    t = records.table()
    out = {}
    for name in TARGETS:
        v = t[name]
        out[name] = (
            f"{v['customers']} customers, capacity {v['capacity']}, best known {int(v['bks'])} routes~{v['k']} "
            f"(not proven optimal)"
        )
    return out


INFO = _info()


def records_fetch():
    return records.fetch()


def records_load():
    return records.load()


def solver_argv(t, budget, seed, out):
    return ["--target", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def evaluate(path, t):
    """Independent re-verification of a solver output file. Returns (cost, solution) or raises."""
    d = json.load(open(path))
    res = verify.check(d["solution"], t)
    if not res["feasible"]:
        raise ValueError("infeasible: " + (res.get("reason") or json.dumps(res)[:200]))
    return res["obj"], d["solution"]


def score(v, rec):
    """Negative relative gap to the best known, clipped at -GAP_CLIP; positive when below the best known."""
    return 0.0 if rec is None else -min((v - rec) / max(1.0, abs(rec)), GAP_CLIP)


def better(a, b):
    return a < b


def beats(v, rec):
    """Costs are integers; a real improvement clears the best known by at least half a unit. Never true when
    the record is unknown (every target has a best known, so rec is None only means the table failed to load)."""
    return rec is not None and v < rec - 0.5


def validate_release(path, t, *, record=None):
    """Recompute exact rounded route cost and capacity/coverage against the original instance."""
    try:
        d = json.load(open(path))
        result = verify.check(d["solution"], t)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "supported": True, "error": f"invalid candidate: {exc}", "metrics": {}}
    metrics = {
        k: result.get(k) for k in ("obj", "n_routes", "duplicate_customers", "missing_customers", "over_capacity")
    }
    if not result.get("feasible"):
        return {
            "ok": False,
            "supported": True,
            "error": result.get("reason", "infeasible route set"),
            "metrics": metrics,
        }
    reference = records_load().get(t) if record is None else record
    metrics.update({"record": reference, "required_integer_improvement": 1})
    if not beats(result["obj"], reference):
        return {"ok": False, "supported": True, "error": "cost does not beat the integer record", "metrics": metrics}
    return {"ok": True, "supported": True, "error": None, "metrics": metrics}


def raw_path(t, best):
    return os.path.join(best, "sol", f"{t}.json")


def sub_path(t, best):
    return os.path.join(best, "sol", f"{t}.sol")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    json.dump({"target": t, "obj": value, "solution": payload, "author": author}, open(raw_path(t, best), "w"))
    open(sub_path(t, best), "w", encoding="utf-8").write(f"# {author}\n" + verify.to_sol(payload, value))


PROMPT = """You are evolving a Python solver for the capacitated vehicle routing problem (CVRP) on the CVRPLIB X benchmark
(Uchoa et al., 2017). Each instance is a depot plus customers on the plane; every customer has a demand; a fleet of
identical vehicles of a fixed CAPACITY must each start and end at the depot and together serve every customer exactly
once, minimising total travel distance. Distances are EUC_2D rounded to the nearest integer, nint(x) = floor(x + 0.5),
and the route cost is the sum of those rounded edge costs. The listed value per instance is the best known solution,
which is NOT proven optimal, so a lower feasible cost is a genuine result.

INTERFACE CONTRACT (keep exactly):
  python solver.py --target NAME --time SECONDS --seed S --out PATH
  writes JSON {"target": NAME, "obj": int, "solution": {"routes": [[c, c, ...], ...]}} where each route is a list of
    customer numbers 1..(DIMENSION-1) in visiting order; the depot is implicit at the start and end of every route
  customers are numbered exactly as in the official CVRPLIB .sol: customer c is the (c+1)-th node in
    NODE_COORD_SECTION, the depot is node 1
  must finish within SECONDS (hard kill at SECONDS+45; returning early is fine); print nothing important to stdout
  save atomically (write tmp, os.replace) on EVERY improvement so a timeout still leaves the best solution on disk
  allowed imports: python stdlib and numpy only (NO external solver packages, no scipy required)
  helpers on PYTHONPATH (problems/cvrp is on sys.path when the loop runs you; keep the champion's import block):
    from verify import load_instance, dist_matrix
    load_instance(NAME) -> {"coords": (N,2) float, "demand": (N,) float, "capacity": float, "n": customers}
      indexed 0..N-1 with index 0 = depot and index c = customer c (so demand[c], coords[c] belong to customer c)
    dist_matrix(coords) -> the integer rounded-EUC_2D matrix the checker itself uses; optimise against THIS matrix
  the solution is re-checked independently: every customer served exactly once, no customer repeated or out of range,
    every route's demand within capacity, cost recomputed from dist_matrix; an infeasible output, crash or timeout
    scores as the worst case for that target, so reliability beats ambition. The number of vehicles is unlimited.

INSTANCE NOTES:
""" + "\n".join(f"  {k}: {v}" for k, v in INFO.items())


def prompt_for_targets(targets):
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"unknown target(s): {unknown}")
    head = PROMPT.split("INSTANCE NOTES:\n", 1)[0] + "INSTANCE NOTES:\n"
    return head + "\n".join(f"  {name}: {INFO[name]}" for name in targets)


TASK = """TASK: write a complete replacement solver.py that lowers the verified route cost on as many targets as possible
(champion total is the negative relative gap to the best known, summed over targets; beating a target counts positive).
Make one substantive algorithmic improvement (or a coherent combination). Candidates: a stronger construction
(Clarke-Wright with the lambda/route-shape savings variants, sweep, or a greedy insertion), granular neighbourhoods
restricted to each customer's nearest neighbours so larger instances get many more moves per second, Or-opt (move
chains of 2-3 customers), guided local search or simulated annealing to escape local minima, ruin-and-recreate / large
neighbourhood search (remove a cluster or a whole route and reinsert cheaply), perturb-and-restart within the budget
keeping the best incumbent, and spending more of the time budget on the instances whose gap is largest. Keep every
move capacity-checked and every saved solution feasible. Do not repeat an idea that already failed unless you fix its
specific failure."""

TOTAL_DESC = (
    "negative relative gap to the best known, summed over targets (0 = matching every best known; a failure = -1)"
)
SUBMIT_NOTE = (
    "Candidates: best-cvrp/sol/NAME.sol (official CVRPLIB 'Route #i:' format). Verify: python problems/cvrp/verify.py "
    "best-cvrp/sol/NAME.json. CVRPLIB has no submission address; a verified improvement on an open instance is "
    "reported to the maintainers (vidalt / CVRPLIB) by hand. Nothing is emailed."
)

EMAIL_TO = None  # CVRPLIB takes new best-known solutions by hand; the GitHub push is the publication


def email_subject(cands):
    return f"CVRPLIB X: improved solutions for {', '.join(t for t, _, _ in cands)}"


def email_body(cands, repo_url):
    rows = "\n".join(f"  {t:<14} ours {int(v)}   best known {int(r)}" for t, v, r in cands)
    return f"Verified CVRP solutions below the CVRPLIB best known:\n\n{rows}\n\nCode and checker: {repo_url}\n"
