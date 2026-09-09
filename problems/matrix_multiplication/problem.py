"""Exact rank of small matrix-multiplication tensors as a discovery-loop problem.

For n x n matrices, a bilinear algorithm of rank R is R triples (U_r, V_r, W_r)
of n x n integer matrices with: C = A*B computed as
    m_r = (sum_{a,b} U_r[a,b] A[a,b]) * (sum_{c,d} V_r[c,d] B[c,d])
    C[e,f] = sum_r m_r * W_r[e,f]
using exactly R scalar multiplications. The rank is the minimum feasible R.

Targets are the exact ranks for n = 2, 3, 4 against best-known upper bounds:
  n=2: 7  (Strassen 1969; proven optimal by Winograd 1971 -- calibration target)
  n=3: 23 (Laderman 1976; lower bound 19 -- genuine open target)
  n=4: 48 (Dumas-Pernet-Sedoglavic 2025, rational coeffs; beatable in principle)

Correctness is the exact tensor identity
    sum_r U_r[a,b] V_r[c,d] W_r[e,f] == d(a,e) d(b,c) d(d,f)
for all index tuples, checked in exact integer arithmetic: no tolerances, no
false positives. A rank below the best known for n=3 or n=4 is a publishable
result (first improvement on 3x3 since 1976).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.matrix_multiplication import records, verify

TITLE = "Exact rank of small matrix-multiplication tensors"
TARGETS = ["2", "3", "4"]
DEVELOPMENT = TARGETS
VALIDATION = []
RELEASE_HOLDOUT = []
DEFAULTS = {"time": 300, "workers": 1}
MAXIMIZE = False
FAIL_SCORE = -1.0  # crash / timeout / infeasible output; worse than any feasible run
GAP_CLIP = 0.5
RELEASE_VALIDATION_SUPPORTED = True


def _info():
    t = records.table()
    out = {}
    for name in TARGETS:
        v = t[name]
        out[name] = f"{v['n']}x{v['n']} tensor, best known rank {v['best_known_rank']}: {v['note']}"
    return out


INFO = _info()


def records_fetch():
    return records.fetch()


def records_load():
    return records.load()


def solver_argv(t, budget, seed, out):
    return ["--target", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def evaluate(path, t):
    """Independent re-verification of a solver output file. Returns (rank, factors) or raises."""
    n = int(t)
    d = json.load(open(path))
    factors = d["factors"]
    res = verify.check(factors, n)
    if not res["feasible"]:
        raise ValueError("infeasible: " + (res.get("reason") or "unknown"))
    return res["rank"], factors


def score(v, rec):
    """Negative relative gap to the best known rank, clipped at -GAP_CLIP; positive when below it."""
    return 0.0 if rec is None else -min((v - rec) / max(1.0, abs(rec)), GAP_CLIP)


def better(a, b):
    return a < b


def beats(v, rec):
    """Ranks are integers; a real improvement clears the best known by at least 1."""
    return rec is not None and v <= rec - 1


def validate_release(path, t, *, record=None):
    """Re-verify the exact tensor identity and confirm the rank beats the record."""
    n = int(t)
    try:
        d = json.load(open(path))
        result = verify.check(d["factors"], n)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "supported": True, "error": f"invalid candidate: {exc}", "metrics": {}}
    metrics = {"rank": result.get("rank"), "n": n}
    if not result.get("feasible"):
        return {
            "ok": False,
            "supported": True,
            "error": result.get("reason", "tensor identity fails"),
            "metrics": metrics,
        }
    reference = records_load().get(t) if record is None else record
    metrics.update({"record": reference, "required_improvement": 1})
    if not beats(result["rank"], reference):
        return {"ok": False, "supported": True, "error": "rank does not beat the record", "metrics": metrics}
    return {"ok": True, "supported": True, "error": None, "metrics": metrics}


def raw_path(t, best):
    return os.path.join(best, "sol", f"n{t}.json")


def sub_path(t, best):
    return os.path.join(best, "sol", f"n{t}.txt")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    json.dump(
        {"target": t, "rank": value, "factors": payload, "author": author},
        open(raw_path(t, best), "w"),
    )
    open(sub_path(t, best), "w", encoding="utf-8").write(
        f"# {author}: {t}x{t} multiplication in rank {value}\n"
    )


PROMPT = """You are evolving a Python solver that searches for low-rank bilinear algorithms for n x n matrix
multiplication. A rank-R algorithm is R triples (U_r, V_r, W_r) of n x n INTEGER matrices such that for every
(a,b,c,d,e,f): sum_r U_r[a,b] * V_r[c,d] * W_r[e,f] == 1 if (a==e and b==c and d==f) else 0.
Using it: m_r = (sum U_r[a,b] A[a,b]) * (sum V_r[c,d] B[c,d]); C[e,f] = sum_r m_r * W_r[e,f]. R multiplications total.

TARGETS (minimise rank; integers; lower is better):
  n=2: best known 7 (Strassen 1969, PROVEN OPTIMAL -- reach 7 to prove your search works; it cannot be beaten)
  n=3: best known 23 (Laderman 1976; lower bound 19 -- beating 23 is a genuine publishable breakthrough)
  n=4: best known 48 (Dumas-Pernet-Sedoglavic 2025, rational coeffs; beatable in principle)

INTERFACE CONTRACT (keep exactly):
  python solver.py --target N --time SECONDS --seed S --out PATH
  writes JSON {"target": "N", "rank": R, "factors": [[[U],[V],[W]], ...]} where each of U,V,W is an n x n list of
    lists of ints; R = len(factors) must equal "rank"
  must finish within SECONDS (hard kill at SECONDS+45); save atomically (write tmp, os.replace) on EVERY improvement
  allowed imports: python stdlib and numpy only
  helpers on PYTHONPATH (problems/matrix_multiplication is on sys.path when the loop runs you):
    from verify import check, apply, naive_product
    check(factors, n) -> {"feasible": bool, "rank": int, "reason": str|None}: the EXACT tensor identity, the same
      checker used for scoring -- optimise against THIS, there is no tolerance to exploit
  the output is re-checked independently by that exact checker; an infeasible output, crash or timeout scores as the
  worst case for that target, so a verified feasible decomposition always beats a clever crash.

SEARCH STRATEGY NOTES (the identity is a system of n^6 polynomial equations over the integers):
  Start every run from a feasible point: the naive rank-n^3 decomposition and, for n=2, Strassen's rank-7
    decomposition are in seed_solver.py -- copy their structure, never start from random infeasible triples.
  The most productive formulation is ENERGY MINIMISATION: energy = number of index tuples where the identity fails
    (or sum of squared violations); drive it to zero with simulated annealing / tabu search over small integer
    entries (try {-1,0,1} first, then {-2..2}). Zero energy at rank R is a valid algorithm.
  RANK REDUCTION: take a feasible rank-R decomposition, delete one triple, and re-optimise the remaining R-1
    triples to restore zero energy. Repeat. This is how 27 -> 26 -> ... -> 23 would go for n=3.
  Exploit structure: the multiplication tensor has cyclic symmetry (permute the three factors); Laderman-type
    solutions are sparse with small entries. Bias the search toward sparse, symmetric, small-entry solutions.
  For n=4, a strong opening is Strassen applied recursively (rank 49) followed by rank-reduction passes.
  For n=2, just reproduce rank 7 -- if your search cannot reach 7, fix the search before touching n=3.
  Keep every saved candidate feasible: check with verify.check inside the solver before writing.

HONEST FRAMING: n=2 is calibration (7 is optimal, unbreakable). n=3 at rank 22 or below has not been achieved by
anyone since Laderman's 23 in 1976 -- treat a claim of 22 with extreme suspicion and re-verify it three ways
(tensor identity, random integer-matrix evaluation vs naive, and rational reconstruction) before believing it.
"""


def prompt_for_targets(targets):
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"unknown target(s): {unknown}")
    head = PROMPT.split("TARGETS (minimise rank")[0] + "TARGETS (minimise rank"
    return head + ":\n" + "\n".join(f"  n={name}: {INFO[name]}" for name in targets)


TASK = """TASK: write a complete replacement solver.py that lowers the verified rank on as many targets as possible
(champion total is the negative relative gap to the best known rank, summed over targets; beating a target counts
positive). Make one substantive algorithmic improvement (or a coherent combination). Candidates: a better energy
function for the identity-violation search (tuple-count vs squared violation vs weighted), smarter neighbourhoods
(single-entry flips vs triple swaps vs block moves), rank-reduction passes that delete one triple and re-optimise,
cyclic-symmetry-constrained search spaces, multi-start portfolios across seeds, and spending more of the time budget
on n=3 where the open record lives. For n=2, reaching rank 7 is the acceptance test for the whole search pipeline.
Keep every saved candidate exactly feasible -- the checker has no tolerance. Do not repeat an idea that already
failed unless you fix its specific failure."""

TOTAL_DESC = (
    "negative relative gap to the best known rank, summed over targets "
    "(0 = matching every best known; a failure = -1)"
)
SUBMIT_NOTE = (
    "A verified rank below the best known for n=3 or n=4 is reported as a mathematical result: "
    "exact integer factors, tensor-identity certificate, and random cross-checks, reviewed by hand. "
    "Nothing is auto-published."
)

EMAIL_TO = None  # mathematical results are reported by hand after human review


def email_subject(cands):
    return f"matrix multiplication: rank {cands[0][1]} for {cands[0][0]}x{cands[0][0]}"


def email_body(cands, repo_url):
    rows = "\n".join(f"  n={t}: rank {int(v)}   best known {int(r)}" for t, v, r in cands)
    return f"Verified matrix-multiplication ranks below the best known:\n\n{rows}\n\nCode and checker: {repo_url}\n"
