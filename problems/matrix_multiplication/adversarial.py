"""Adversarial checking: breaker suite for discovery-loop candidates.

Every candidate decomposition is attacked before promotion. The breaker
tries to kill it: find a counterexample, find a strictly smaller feasible
decomposition via single/pair deletions or local delete-and-repair, or show
it contains redundant triples.

HONESTY NOTE — READ THIS: these are bounded, time-limited attacks, not
proofs. A candidate that "survives" has survived a fixed budget of
adversarial effort. That is evidence, never a proof of optimality or
minimality. The breaker can say "I failed to break it in X seconds"; it
cannot say "it is unbreakable." Do not present a "survived" verdict as a
claim that no better decomposition exists.
"""

from __future__ import annotations

import random
import time


def _mat_mul_naive(A, B):
    n = len(A)
    C = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            for k in range(n):
                C[i][j] += A[i][k] * B[k][j]
    return C


def _eval_decomposition(factors, A, B):
    """Evaluate a bilinear decomposition on specific input matrices."""
    n = len(A)
    C = [[0] * n for _ in range(n)]
    for (U, V, W) in factors:
        # m = (sum U[a][b] A[a][b]) * (sum V[c][d] B[c][d])
        m1 = sum(U[a][b] * A[a][b] for a in range(n) for b in range(n))
        m2 = sum(V[c][d] * B[c][d] for c in range(n) for d in range(n))
        m = m1 * m2
        for e in range(n):
            for f in range(n):
                C[e][f] += m * W[e][f]
    return C


def random_attack(factors, n, num_trials=100, seed=0, verbose=False) -> dict:
    """Try to find input matrices where the decomposition gives wrong answer.

    Returns: {"passed": bool, "counterexample": (A, B, expected, got) or None}
    """
    rng = random.Random(seed)
    for trial in range(num_trials):
        # Random integer matrices with entries in [-3, 3]
        A = [[rng.randint(-3, 3) for _ in range(n)] for _ in range(n)]
        B = [[rng.randint(-3, 3) for _ in range(n)] for _ in range(n)]

        expected = _mat_mul_naive(A, B)
        got = _eval_decomposition(factors, A, B)

        if expected != got:
            if verbose:
                print(f"  Counterexample found on trial {trial}")
            return {
                "passed": False,
                "counterexample": (A, B, expected, got),
                "trial": trial,
            }

    return {"passed": True, "counterexample": None, "trials": num_trials}


def redundancy_attack(factors, n, verify_fn, verbose=False) -> dict:
    """Try to remove each triple and see if the decomposition still works.

    If a triple is redundant, the rank can be reduced by 1 for free.
    Returns: {"redundant": [indices], "minimal": bool}
    """
    redundant = []
    for i in range(len(factors)):
        reduced = factors[:i] + factors[i + 1:]
        res = verify_fn(reduced, n)
        if res.get("feasible"):
            redundant.append(i)
            if verbose:
                print(f"  Triple {i} is redundant!")

    return {
        "redundant": redundant,
        "minimal": len(redundant) == 0,
        "potential_saving": len(redundant),
    }


def sparsity_attack(factors, n, verbose=False) -> dict:
    """Analyze sparsity: are there triples with unnecessarily dense matrices?

    Returns per-triple nonzero counts and identifies the densest triples
    as candidates for sparsification.
    """
    analysis = []
    for i, (U, V, W) in enumerate(factors):
        nnz_u = sum(1 for a in range(n) for b in range(n) if U[a][b] != 0)
        nnz_v = sum(1 for c in range(n) for d in range(n) if V[c][d] != 0)
        nnz_w = sum(1 for e in range(n) for f in range(n) if W[e][f] != 0)
        analysis.append({
            "triple": i,
            "nnz_U": nnz_u, "nnz_V": nnz_v, "nnz_W": nnz_w,
            "max_nnz": max(nnz_u, nnz_v, nnz_w),
            "total_nnz": nnz_u + nnz_v + nnz_w,
        })

    # Sort by max_nnz descending — densest first
    analysis.sort(key=lambda x: x["max_nnz"], reverse=True)

    return {
        "triples": analysis,
        "densest": analysis[0] if analysis else None,
        "avg_max_nnz": sum(t["max_nnz"] for t in analysis) / len(analysis) if analysis else 0,
    }


# ---------------------------------------------------------------------------
# Breaker-suite internals: fast residual arithmetic over {-1, 0, 1} triples
# ---------------------------------------------------------------------------

def _triple_contribution(triple, n):
    """Flat n^6 array: U[a][b]*V[c][d]*W[e][f] for every index tuple.

    The tensor identity for a feasible candidate says the sum of these
    over all triples equals the delta tensor. Working with contributions
    lets repair score candidates with O(n^6) compares instead of a full
    re-verification per candidate.
    """
    U, V, W = triple
    cells = []
    for a in range(n):
        Ua = U[a]
        for b in range(n):
            uab = Ua[b]
            for c in range(n):
                for d in range(n):
                    uv = uab * V[c][d]
                    for e in range(n):
                        We = W[e]
                        for f in range(n):
                            cells.append(uv * We[f])
    return cells


def _residual_violations(added_contribs, removed_sum):
    """Count tensor-identity equations violated by (base - removed + added).

    Only valid when the base candidate is feasible: then the new residual
    is exactly sum(added) - sum(removed), and an equation is violated iff
    that residual is nonzero.
    """
    bad = 0
    for i, r in enumerate(removed_sum):
        s = -r
        for c in added_contribs:
            s += c[i]
        if s != 0:
            bad += 1
    return bad


def _random_triple(rng, n, max_nnz=3):
    """Sample a random sparse triple over {-1, 0, 1}.

    Each matrix gets 1..max_nnz nonzero entries at random positions.
    These are repair candidates, not claimed to be useful on their own.
    """
    def _sparse_mat():
        M = [[0] * n for _ in range(n)]
        cells = [(a, b) for a in range(n) for b in range(n)]
        for (a, b) in rng.sample(cells, rng.randint(1, max_nnz)):
            M[a][b] = rng.choice((-1, 1))
        return M

    return [_sparse_mat(), _sparse_mat(), _sparse_mat()]


def _greedy_repair(rng, n, removed_sum, pool_size, deadline, max_rounds):
    """Greedily add triples that reduce residual violations, up to max_rounds.

    Returns a list of (triple, contribution) pairs. Bounded by the
    deadline; may return an empty list if nothing helps. This is a
    heuristic repair attempt, not an exhaustive search.
    """
    added = []
    added_contribs = []
    for _ in range(max_rounds):
        if time.monotonic() >= deadline:
            break
        base_bad = _residual_violations(added_contribs, removed_sum)
        if base_bad == 0:
            break
        best = None
        best_bad = base_bad
        for _ in range(pool_size):
            if time.monotonic() >= deadline:
                break
            t = _random_triple(rng, n)
            c = _triple_contribution(t, n)
            bad = _residual_violations(added_contribs + [c], removed_sum)
            if bad < best_bad:
                best_bad = bad
                best = (t, c)
        if best is None:
            break
        added.append(best)
        added_contribs.append(best[1])
    return added


def neighborhood_optimality_attack(factors, n, check, k, time_budget_secs, seed) -> dict:
    """Bounded local search: try to find a STRICTLY lower-rank feasible
    decomposition within k-triple edits of the candidate.

    Method: delete d triples (d in 1..k), then greedy delete-and-repair
    over {-1, 0, 1} triples. Phase 1 tries every single deletion
    deterministically; phase 2 does random delete-sets until the budget
    runs out. Final feasibility is always decided by ``check``.

    This is an honest bounded attack, NOT a proof. Failing to find a
    better decomposition in the budget says nothing about whether one
    exists outside the searched neighborhood.

    Returns: {"found_better": bool, "best_rank_seen": int|None, "attempts": int}
    """
    rng = random.Random(seed)
    deadline = time.monotonic() + max(0.0, time_budget_secs)
    base_rank = len(factors)
    pool_size = 30 if n <= 3 else 12

    base_res = check(factors, n)
    if not base_res.get("feasible"):
        return {
            "found_better": False,
            "best_rank_seen": None,
            "attempts": 0,
        }

    contribs = [_triple_contribution(t, n) for t in factors]
    n6 = len(contribs[0])
    found_better = False
    best_rank_seen = base_rank
    attempts = 0

    def _try_delete_set(idxs):
        removed_sum = [0] * n6
        for j in idxs:
            cj = contribs[j]
            for i in range(n6):
                removed_sum[i] += cj[i]
        idxset = set(idxs)
        reduced = [t for j, t in enumerate(factors) if j not in idxset]
        if check(reduced, n).get("feasible") and len(reduced) < base_rank:
            return reduced
        added = _greedy_repair(rng, n, removed_sum, pool_size, deadline,
                               max_rounds=len(idxs))
        added_contribs = [c for _, c in added]
        if _residual_violations(added_contribs, removed_sum) != 0:
            return None
        candidate = reduced + [t for t, _ in added]
        if len(candidate) < base_rank and check(candidate, n).get("feasible"):
            return candidate
        return None

    def _record(hit):
        nonlocal found_better, best_rank_seen
        if hit is not None:
            found_better = True
            best_rank_seen = min(best_rank_seen, len(hit))

    # Phase 1: every single deletion, deterministically.
    for i in range(base_rank):
        if time.monotonic() >= deadline:
            break
        attempts += 1
        _record(_try_delete_set([i]))

    # Phase 2: random delete-sets of size 1..k until the budget is spent.
    max_d = min(k, base_rank - 1)
    while max_d >= 1 and time.monotonic() < deadline:
        d = rng.randint(1, max_d)
        idxs = rng.sample(range(base_rank), d)
        attempts += 1
        _record(_try_delete_set(idxs))

    return {
        "found_better": found_better,
        "best_rank_seen": best_rank_seen,
        "attempts": attempts,
    }


# Curated, factual bounds only. Do NOT invent bounds for other n.
_KNOWN_BEST = {
    2: (7, "Strassen (1969); proven optimal by Winograd (1971)"),
    3: (23, "Laderman (1976); best known — optimality is NOT proven"),
}


def lower_bound_check(n, rank) -> dict:
    """Compare a candidate's rank against curated known results.

    Pure factual lookup: n=2 optimal is 7 (Strassen, proven optimal);
    n=3 best known is 23 (Laderman, not proven optimal). For any other n
    this function reports that it has no bound rather than inventing one.

    Returns: {"known_best": int|None, "gap": int|None,
              "is_optimal_claim_possible": bool, "note": str}
    """
    entry = _KNOWN_BEST.get(n)
    if entry is None:
        return {
            "known_best": None,
            "gap": None,
            "is_optimal_claim_possible": False,
            "note": f"no curated bound for n={n}; refusing to invent one",
        }
    known_best, provenance = entry
    return {
        "known_best": known_best,
        "gap": rank - known_best,
        "is_optimal_claim_possible": (n == 2 and rank == known_best),
        "note": provenance,
    }


def pair_removal_attack(factors, n, check, time_budget_secs=None, seed=0) -> dict:
    """Try removing every PAIR of triples, with quick greedy repair.

    For each pair: remove both; if still feasible, the pair is removable
    outright. Otherwise attempt a repair adding at most ONE replacement
    triple (net rank -1). Final feasibility is always decided by ``check``.

    Bounded: pass time_budget_secs to stop early; pairs_tested reports how
    far it got. A pair that survives removal was not proven necessary —
    only that this bounded repair failed to exploit its absence.

    Returns: {"removable_pairs": [...], "any_found": bool, "pairs_tested": int}
    """
    rng = random.Random(seed)
    deadline = float("inf") if time_budget_secs is None else time.monotonic() + max(0.0, time_budget_secs)
    base_rank = len(factors)
    pool_size = 30 if n <= 3 else 12

    if not check(factors, n).get("feasible"):
        return {"removable_pairs": [], "any_found": False, "pairs_tested": 0}

    contribs = [_triple_contribution(t, n) for t in factors]
    removable = []
    tested = 0

    for i in range(base_rank):
        for j in range(i + 1, base_rank):
            if time.monotonic() >= deadline:
                break
            tested += 1
            ci, cj = contribs[i], contribs[j]
            removed_sum = [a + b for a, b in zip(ci, cj)]
            reduced = [t for m, t in enumerate(factors) if m != i and m != j]
            if check(reduced, n).get("feasible"):
                removable.append({
                    "pair": (i, j),
                    "replacements_needed": 0,
                    "resulting_rank": base_rank - 2,
                })
                continue
            added = _greedy_repair(rng, n, removed_sum, pool_size, deadline,
                                   max_rounds=1)
            if added:
                added_contribs = [added[0][1]]
                if _residual_violations(added_contribs, removed_sum) == 0:
                    candidate = reduced + [added[0][0]]
                    if check(candidate, n).get("feasible"):
                        removable.append({
                            "pair": (i, j),
                            "replacements_needed": 1,
                            "resulting_rank": base_rank - 1,
                        })
        else:
            continue
        break

    return {
        "removable_pairs": removable,
        "any_found": len(removable) > 0,
        "pairs_tested": tested,
    }


def breaker_suite(factors, n, check, seed=0, time_budget_secs=60, verbose=True) -> dict:
    """Run the full breaker suite: every attack, one verdict.

    Verdict is "broken" ONLY if an attack actually produced a
    better/feasible-smaller decomposition (counterexample, redundant
    triple, neighborhood improvement, or removable pair). Otherwise the
    verdict is "survived".

    "survived" means the candidate withstood this bounded budget of
    adversarial effort. It is evidence for promotion, NOT a proof of
    optimality, minimality, or correctness beyond what the attacks checked.

    Returns: {"verdict": "survived"|"broken", "attacks": {name: result},
              "recommendation": str}
    """
    if verbose:
        print(f"Breaker suite: n={n}, rank={len(factors)}, "
              f"budget={time_budget_secs}s")

    attacks = {}
    attacks["random"] = random_attack(factors, n, num_trials=100, seed=seed)
    attacks["redundancy"] = redundancy_attack(factors, n, check)
    attacks["sparsity"] = sparsity_attack(factors, n)
    attacks["lower_bound"] = lower_bound_check(n, len(factors))
    attacks["neighborhood"] = neighborhood_optimality_attack(
        factors, n, check, k=2,
        time_budget_secs=0.6 * time_budget_secs, seed=seed + 1)
    attacks["pair_removal"] = pair_removal_attack(
        factors, n, check,
        time_budget_secs=0.3 * time_budget_secs, seed=seed + 2)

    broken_by = []
    if not attacks["random"]["passed"]:
        broken_by.append("random attack found a counterexample: candidate is wrong")
    red = attacks["redundancy"]["redundant"]
    if red:
        broken_by.append(f"redundancy attack: triples {red} removable "
                         f"(rank can drop by {len(red)})")
    nb = attacks["neighborhood"]
    if nb["found_better"]:
        broken_by.append(f"neighborhood attack: feasible rank-{nb['best_rank_seen']} "
                         f"found within {nb['attempts']} attempts")
    pr = attacks["pair_removal"]
    if pr["any_found"]:
        pairs = [str(p["pair"]) for p in pr["removable_pairs"]]
        broken_by.append(f"pair-removal attack: pairs {', '.join(pairs)} removable")

    verdict = "broken" if broken_by else "survived"
    if verdict == "broken":
        recommendation = ("Do NOT promote. " + " ".join(broken_by))
    else:
        lb = attacks["lower_bound"]
        recommendation = (
            f"Survived all bounded attacks ({nb['attempts']} neighborhood "
            f"attempts, {pr['pairs_tested']} pairs tested). No strictly "
            "smaller feasible decomposition was found. This is bounded "
            "evidence, not an optimality proof. ")
        if lb["known_best"] is not None:
            recommendation += (f"Curated known best for n={n} is "
                               f"{lb['known_best']}; this candidate sits "
                               f"{lb['gap']} above it.")

    if verbose:
        print(f"  Verdict: {verdict.upper()}")

    return {
        "verdict": verdict,
        "attacks": attacks,
        "recommendation": recommendation,
    }


def full_adversarial_suite(factors, n, verify_fn, seed=0, verbose=True) -> dict:
    """Run all adversarial attacks. Returns comprehensive report."""
    if verbose:
        print(f"Adversarial suite: n={n}, rank={len(factors)}")

    results = {}

    # Attack 1: random counterexamples
    if verbose:
        print("  [1/3] Random attack (100 trials)...")
    results["random"] = random_attack(factors, n, num_trials=100, seed=seed, verbose=verbose)
    if verbose:
        print(f"    {'PASSED' if results['random']['passed'] else 'FAILED'}")

    # Attack 2: redundancy
    if verbose:
        print("  [2/3] Redundancy attack...")
    results["redundancy"] = redundancy_attack(factors, n, verify_fn, verbose=verbose)
    if verbose:
        r = results["redundancy"]
        status = "MINIMAL" if r["minimal"] else f"{len(r['redundant'])} REDUNDANT"
        print(f"    {status}")

    # Attack 3: sparsity analysis
    if verbose:
        print("  [3/3] Sparsity analysis...")
    results["sparsity"] = sparsity_attack(factors, n, verbose=verbose)
    if verbose:
        s = results["sparsity"]
        print(f"    Avg max nnz: {s['avg_max_nnz']:.1f}, densest: triple {s['densest']['triple']}")

    # Overall verdict
    results["verdict"] = (
        "SURVIVED" if results["random"]["passed"] else "BROKEN"
    )
    if not results["redundancy"]["minimal"]:
        results["verdict"] += " (but has redundant triples!)"

    if verbose:
        print(f"  Verdict: {results['verdict']}")

    return results
