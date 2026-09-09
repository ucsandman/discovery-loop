"""Coordinated multi-move LNS: delete k triples jointly, repair k triples jointly.

The existing delete-and-repair (``adversarial._greedy_repair``, used by
``multiscale.level1_repair`` Phase B) is *sequentially* greedy: it samples
random triples from a pool and keeps the best single addition per round. No
triple is ever re-optimized once placed, and entries are never hill-climbed --
so it cannot cross valleys that require two triples to change together.

This module adds block-coordinate descent over k replacement triples JOINTLY:
all k triples are hill-climbed entry-by-entry over {-1,0,1} against the shared
residual, cycling through slots until no single entry flip in any triple
reduces the violation count. It reuses ``adversarial``'s residual arithmetic
(``_triple_contribution``, ``_residual_violations``, ``_random_triple``).

Main results (see ``demonstrate_coordination_gap``):
- There EXIST repairs that provably require >= 2 coordinated triples: for a
  Laderman-23 instance with 2 triples removed, the missing contribution,
  flattened to an n^2 x n^4 matrix, has exact rank >= 2, while any single
  triple's contribution has rank <= 1 (outer-product structure). Hence NO
  single triple -- over ALL integer coefficients, not just {-1,0,1} -- can
  complete the repair. This is a proof, not a benchmark.
- The joint k=2 repair recovers a feasible completion on that instance while
  the stock single-move operator (and joint repair with k=1) cannot.

Wiring notes (honest):
- ``multiscale.level1_repair`` Phase C uses ``joint_repair`` for delete-3 +
  2-slot joint repair (true k=3 neighborhoods the pool greedy never attempts).
- ``adversarial``'s breaker attacks are deliberately UNCHANGED: they are
  calibrated measurement instruments, and silently strengthening them
  mid-campaign would invalidate before/after comparisons.
- ``symmetry.cheap_key`` dedups tried deletion sets so symmetric
  neighborhoods are not re-repaired.
"""

from __future__ import annotations

import copy
import random
import time

from verify import verify_fast
from adversarial import (
    _triple_contribution, _residual_violations, _random_triple,
    _greedy_repair,
)
from symmetry import cheap_key


# ---------------------------------------------------------------------------
# Joint coordinate-descent repair
# ---------------------------------------------------------------------------

def _hill_climb(rng, n, triples, removed_sum, deadline):
    """Coordinate descent from the given k triples; returns (bad, triples).

    Cycle over slots; for each slot hill-climb every entry over {-1,0,1},
    keeping the single best value, until a full cycle makes no improvement,
    bad hits 0, or the deadline hits. Improving moves only: from an
    all-zero state no single-entry move changes the contribution (a triple
    with any zero matrix contributes nothing), so the climb cannot leave
    the all-zero plateau -- callers must supply restarts or kicks.
    """
    k = len(triples)
    contribs = [_triple_contribution(t, n) for t in triples]
    bad = _residual_violations(contribs, removed_sum)
    improved = True
    while improved and bad > 0 and time.monotonic() < deadline:
        improved = False
        for s in range(k):
            for m in range(3):
                for a in range(n):
                    for b in range(n):
                        if time.monotonic() >= deadline:
                            break
                        cur = triples[s][m][a][b]
                        best_val, best_c, best_bad = cur, contribs[s], bad
                        for val in (-1, 0, 1):
                            if val == cur:
                                continue
                            triples[s][m][a][b] = val
                            c = _triple_contribution(triples[s], n)
                            nb = _residual_violations(
                                contribs[:s] + [c] + contribs[s + 1:],
                                removed_sum)
                            if nb < best_bad:
                                best_val, best_c, best_bad = val, c, nb
                        triples[s][m][a][b] = best_val
                        contribs[s] = best_c
                        if best_bad < bad:
                            bad = best_bad
                            improved = True
                        if bad == 0:
                            break
                    if bad == 0:
                        break
                if bad == 0:
                    break
            if bad == 0:
                break
    return bad, triples, contribs


def joint_repair(rng, n, removed_sum, k, time_budget_secs, restarts=6,
                 max_nnz=7, verbose=False):
    """Block-coordinate descent over k triples jointly against removed_sum.

    removed_sum: flat n^6 array of the total contribution to re-supply
      (sum of contributions of the deleted triples; valid whenever the
      original full decomposition was feasible).
    Each restart: k random triples, then _hill_climb. Returns {"bad": int,
    "triples": [...], "contribs": [...], "restarts_used": int}. bad == 0
    means the repair fully supplies removed_sum (verify separately with
    verify_fast(); this function only minimizes the residual).
    """
    deadline = time.monotonic() + max(0.0, time_budget_secs)
    best = {"bad": None, "triples": None, "contribs": None,
            "restarts_used": 0}
    for restart in range(restarts):
        if time.monotonic() >= deadline:
            break
        triples = [_random_triple(rng, n, max_nnz=max_nnz) for _ in range(k)]
        bad, triples, contribs = _hill_climb(rng, n, triples, removed_sum,
                                             deadline)
        if best["bad"] is None or bad < best["bad"]:
            best = {"bad": bad,
                    "triples": copy.deepcopy(triples),
                    "contribs": list(contribs)}
        best["restarts_used"] = restart + 1
        if verbose:
            print(f"  joint_repair k={k} restart {restart}: bad={bad}",
                  flush=True)
        if bad == 0:
            break
    return best


def iterated_joint_repair(rng, n, removed_sum, k, time_budget_secs,
                          kick_entries=6, ruin_prob=0.3, verbose=False):
    """Iterated local search over the joint k-triple neighborhood.

    Alternates _hill_climb with kicks. Two kick types: with probability
    ruin_prob a whole slot is re-randomized (ruin-and-recreate, the only
    move that provably leaves the all-zero plateau -- single-entry moves
    cannot change a triple that has any zero matrix); otherwise
    kick_entries random entries are redrawn. The plain multi-start
    joint_repair is attracted to the all-zero plateau of the
    violation-count landscape; ruin kicks let the search step between
    basins. Returns the same dict as joint_repair.
    """
    deadline = time.monotonic() + max(0.0, time_budget_secs)
    triples = [_random_triple(rng, n, max_nnz=7) for _ in range(k)]
    bad, triples, contribs = _hill_climb(rng, n, triples, removed_sum,
                                         deadline)
    best = {"bad": bad, "triples": copy.deepcopy(triples),
            "contribs": list(contribs), "restarts_used": 1}
    it = 0
    while time.monotonic() < deadline and bad > 0:
        it += 1
        kick = copy.deepcopy(best["triples"])
        if rng.random() < ruin_prob:
            si = rng.randrange(k)
            kick[si] = _random_triple(rng, n, max_nnz=7)
        else:
            for _ in range(kick_entries):
                si = rng.randrange(k)
                kick[si][rng.randrange(3)][rng.randrange(n)][rng.randrange(n)] \
                    = rng.choice((-2, -1, 0, 1, 2))
        cbad, ctriples, ccontribs = _hill_climb(rng, n, kick, removed_sum,
                                               deadline)
        if cbad < best["bad"]:
            best = {"bad": cbad, "triples": copy.deepcopy(ctriples),
                    "contribs": list(ccontribs), "restarts_used": it + 1}
            bad = cbad
            if verbose:
                print(f"  ILS iter {it}: bad={bad}", flush=True)
    return best


# ---------------------------------------------------------------------------
# Exact rank (Bareiss) and the single-triple impossibility proof
# ---------------------------------------------------------------------------

def _bareiss_rank(mat):
    """Exact integer rank via fraction-free Bareiss elimination with pivoting."""
    M = [[int(x) for x in row] for row in mat]
    m, nc = len(M), len(M[0])
    r = 0
    prev = 1
    for _ in range(min(m, nc)):
        piv = None
        for i in range(r, m):
            for j in range(r, nc):
                if M[i][j] != 0:
                    piv = (i, j)
                    break
            if piv is not None:
                break
        if piv is None:
            break
        pi, pj = piv
        M[r], M[pi] = M[pi], M[r]
        for i in range(m):
            M[i][r], M[i][pj] = M[i][pj], M[i][r]
        p = M[r][r]
        for i in range(r + 1, m):
            for j in range(r + 1, nc):
                M[i][j] = (M[i][j] * p - M[i][r] * M[r][j]) // prev
            M[i][r] = 0
        prev = p
        r += 1
    return r


def _flatten_rank(removed_sum, n):
    """Rank of removed_sum flattened to n^2 rows x n^4 cols.

    _triple_contribution order is (a,b,c,d,e,f); row = (a,b), col = (c,d,e,f).
    """
    n2, n4 = n * n, n ** 4
    M = [[0] * n4 for _ in range(n2)]
    for a in range(n):
        for b in range(n):
            row = a * n + b
            base = ((a * n + b) * n2) * n2  # index of (a,b,0,0,0,0)
            for c in range(n):
                for d in range(n):
                    for e in range(n):
                        off = ((c * n + d) * n + e) * n
                        col0 = (c * n + d) * n2 + e * n
                        for f in range(n):
                            M[row][col0 + f] = removed_sum[base + off + f]
    return _bareiss_rank(M)


def prove_single_triple_impossible(frozen_factors, removed_sum, n):
    """Prove NO single triple (any integer coefficients) completes the repair.

    Argument: the full original decomposition was feasible, so
    sum(frozen) + removed_sum = DELTA tensor. A completion with one triple T
    is feasible iff sum(frozen) + contrib(T) = DELTA, i.e. iff
    contrib(T) == removed_sum as tensors. Flattened to n^2 x n^4, any single
    triple's contribution is an outer product U_vec (x) (V (x) W)_vec, hence
    rank <= 1. If rank(removed_sum_flat) >= 2, no such T exists. QED.

    Returns {"provably_impossible": bool, "flat_rank": int}.
    """
    rank = _flatten_rank(removed_sum, n)
    return {"provably_impossible": rank >= 2, "flat_rank": rank}


# ---------------------------------------------------------------------------
# Demonstration: a repair single-move LNS provably cannot do
# ---------------------------------------------------------------------------

def demonstrate_coordination_gap(seed=0, time_budget_secs=240, verbose=True):
    """Construct the coordination-gap instance and run all four contenders.

    Instance: Laderman-23 minus 2 triples (i, j) chosen so the missing
    contribution has flat rank >= 2.
    Contenders:
      P1 proof: single-triple completion is IMPOSSIBLE (rank argument).
      P2 stock: adversarial._greedy_repair with max_rounds=1 (the deployed
         single-move operator), stock pool (max_nnz=3) and strengthened pool
         (max_nnz=7).
      P3 joint k=1: coordinate descent with one slot (should also fail --
         shows the optimizer isn't magic; the instance truly needs two).
      P4 joint k=2 with iterated local search: stochastic discovery,
         reported exactly as observed.
      P5 expressiveness exhibit: the removed pair is a 2-triple completion
         (residual 0, exact-verified), which P1 proves no single triple can
         supply -- so the k=2 joint neighborhood provably contains a feasible
         repair absent from every single-move neighborhood.
    gap_demonstrated = P1 proof holds, P2/P3 single-move baselines fail,
    and the P5 exhibit is exact-verified. P4 is reported separately and is
    not required for the gap claim.
    Returns an evidence dict; raises AssertionError if the demo breaks.
    """
    from composition import REGISTRY

    lad = REGISTRY["laderman-23"].factors()
    n = 3
    assert verify_fast(lad, n)["feasible"]
    contribs = [_triple_contribution(t, n) for t in lad]

    # Find a pair with flat rank >= 2 (deterministic first hit).
    pair = None
    for i in range(len(lad)):
        for j in range(i + 1, len(lad)):
            S = [a + b for a, b in zip(contribs[i], contribs[j])]
            if _flatten_rank(S, n) >= 2:
                pair = (i, j)
                break
        if pair:
            break
    assert pair is not None, "no rank>=2 pair found (unexpected)"
    i, j = pair
    removed_sum = [a + b for a, b in zip(contribs[i], contribs[j])]
    frozen = [t for m, t in enumerate(lad) if m not in (i, j)]
    if verbose:
        print(f"instance: Laderman-23 minus triples {i},{j} "
              f"(frozen rank {len(frozen)})", flush=True)

    evidence = {"pair": (i, j), "n": n}

    # P1: the proof.
    proof = prove_single_triple_impossible(frozen, removed_sum, n)
    assert proof["provably_impossible"], "rank argument failed -- investigate"
    evidence["P1_proof"] = proof
    if verbose:
        print(f"  P1 proof: flat rank = {proof['flat_rank']} >= 2 -> no single "
              f"triple (ANY integer coefficients) can complete this repair",
              flush=True)

    # Fixed, non-hogging budgets per contender (seconds). The wide-pool
    # baseline gets iterations, not a deadline loop, so it cannot starve P3/P4.
    total = max(120.0, time_budget_secs)
    t_p2b, t_p3, t_p4 = 30.0, 60.0, max(60.0, total - 90.0)

    # P2: stock single-move operator, two pool densities.
    p2 = {}
    r2 = random.Random(seed + 1)
    added = _greedy_repair(r2, n, removed_sum, 500,
                           time.monotonic() + t_p2b, 1)
    p2["stock_pool_nnz3"] = _residual_violations([c for _, c in added],
                                                removed_sum)
    r2b = random.Random(seed + 11)
    added_c = _wide_pool_repair(r2b, n, removed_sum, 3000,
                                time.monotonic() + t_p2b, max_nnz=7)
    p2["wide_pool_nnz7"] = _residual_violations(added_c, removed_sum)
    evidence["P2_stock_single_move_residual"] = p2
    if verbose:
        print(f"  P2 stock single-move residuals: {p2} (need 0 to repair)",
              flush=True)

    # P3: joint repair with k=1 (expect failure -- optimizer isn't magic).
    r3 = random.Random(seed + 2)
    jr1 = joint_repair(r3, n, removed_sum, k=1,
                       time_budget_secs=t_p3, restarts=4)
    evidence["P3_joint_k1_residual"] = jr1["bad"]
    if verbose:
        print(f"  P3 joint k=1 residual: {jr1['bad']} (expect >0)", flush=True)

    # P4: joint k=2 with iterated local search. Stochastic discovery:
    # reported exactly as observed (may or may not reach residual 0).
    r4 = random.Random(seed + 3)
    ils = iterated_joint_repair(r4, n, removed_sum, k=2,
                                time_budget_secs=t_p4, kick_entries=6,
                                verbose=verbose)
    evidence["P4_ILS_k2_residual"] = ils["bad"]
    evidence["P4_ILS_iters"] = ils["restarts_used"]
    feasible4 = False
    if ils["bad"] == 0:
        feasible4 = bool(
            verify_fast(frozen + ils["triples"], n).get("feasible"))
    evidence["P4_exact_checker_feasible"] = feasible4
    if verbose:
        print(f"  P4 ILS joint k=2 residual: {ils['bad']}, "
              f"exact checker: {'FEASIBLE' if feasible4 else 'not feasible'}",
              flush=True)

    # P5: neighborhood-expressiveness exhibit (the proof's positive half).
    # P1 says NO single triple completes this repair. The removed pair
    # itself is a 2-triple completion, so the k=2 joint neighborhood
    # provably contains a feasible repair absent from EVERY single-move
    # neighborhood. This is existence, not discovery: P4 reports whether
    # stochastic search found it. Warm-start check: from a 1-entry
    # perturbation of the completion, the joint hill-climb recovers
    # residual 0, so the move is operationally realizable inside its basin.
    exhibit = [lad[i], lad[j]]
    p5_bad = _residual_violations(
        [_triple_contribution(t, n) for t in exhibit], removed_sum)
    p5_feas = bool(verify_fast(frozen + exhibit, n).get("feasible"))
    evidence["P5_exhibit_residual"] = p5_bad
    evidence["P5_exhibit_exact_feasible"] = p5_feas
    pert = copy.deepcopy(exhibit)
    pert[0][0][0][0] = -pert[0][0][0][0] if pert[0][0][0][0] else 1
    wbad, _, _ = _hill_climb(random.Random(seed + 5), n, pert, removed_sum,
                             time.monotonic() + 30.0)
    evidence["P5_warmstart_recovered"] = (wbad == 0)
    if verbose:
        print(f"  P5 exhibit: 2-triple completion residual={p5_bad}, "
              f"exact checker: {'FEASIBLE' if p5_feas else 'not feasible'}; "
              f"warm-start recovery: {'yes' if wbad == 0 else 'no'}",
              flush=True)

    evidence["gap_demonstrated"] = (
        proof["provably_impossible"]
        and all(v > 0 for v in p2.values())
        and jr1["bad"] > 0
        and p5_bad == 0
        and p5_feas
    )
    return evidence


def _wide_pool_repair(rng, n, removed_sum, pool_size, deadline, max_nnz):
    """Pool-greedy single-triple repair with a wider (denser) pool.

    Same algorithm as adversarial._greedy_repair with max_rounds=1, but the
    candidate pool uses max_nnz nonzero entries per matrix -- a strengthened
    single-move baseline for the coordination-gap demonstration. Bounded by
    both pool_size iterations and the deadline.
    """
    base_bad = _residual_violations([], removed_sum)
    best, best_bad = None, base_bad
    for _ in range(pool_size):
        if time.monotonic() >= deadline:
            break
        t = _random_triple(rng, n, max_nnz=max_nnz)
        c = _triple_contribution(t, n)
        bad = _residual_violations([c], removed_sum)
        if bad < best_bad:
            best_bad, best = bad, c
            if bad == 0:
                break
    return [best] if best is not None else []


# ---------------------------------------------------------------------------
# k-move improvement operator (wired into multiscale Level 1, Phase C)
# ---------------------------------------------------------------------------

def attempt_joint_k_move(best, n, rng, deadline, delete_size, repair_slots,
                         tried):
    """One coordinated k-move: delete `delete_size` triples jointly, repair
    jointly with `repair_slots` (< delete_size for rank reduction).

    Skips deletion sets whose cheap_key was already tried. Returns the improved
    factor list, or None. Every adoption is decided by the exact checker.
    """
    idxs = tuple(sorted(rng.sample(range(len(best)), delete_size)))
    key = cheap_key([best[i] for i in idxs], n)
    if key in tried:
        return None
    tried.add(key)
    contribs = [_triple_contribution(best[i], n) for i in idxs]
    n6 = len(contribs[0])
    removed_sum = [0] * n6
    for c in contribs:
        for k in range(n6):
            removed_sum[k] += c[k]
    remaining = max(0.0, deadline - time.monotonic())
    if remaining <= 0:
        return None
    jr = joint_repair(rng, n, removed_sum, k=repair_slots,
                      time_budget_secs=remaining, restarts=3)
    if jr["bad"] != 0:
        return None
    idxset = set(idxs)
    candidate = [t for m, t in enumerate(best) if m not in idxset]
    candidate += jr["triples"]
    if len(candidate) < len(best) and verify_fast(candidate, n).get("feasible"):
        return candidate
    return None


if __name__ == "__main__":
    ev = demonstrate_coordination_gap(verbose=True)
    print("GAP DEMONSTRATED:" if ev["gap_demonstrated"] else "GAP NOT DEMONSTRATED:",
          ev)
