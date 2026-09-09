"""Multi-scale search for matrix-multiplication discovery.

Three levels, top-down. Each level hands its best verified result to the
next, and the final answer is the best decomposition verified at ANY level.

- Level 3 (strategic): enumerate technique compositions over the registry
  via composition.search_compositions — tensor products, block embeddings,
  naive fills. Tiny search space, big structural wins.
- Level 2 (tactical): enumerate partitions of the index set {0..n-1} into
  diagonal blocks; assign a registry decomposition to each block; cover
  cross-block terms with rank-1 outer products and the rest with naive
  fill. Every candidate is verified with the exact tensor-identity
  checker, and candidates are pruned by a cheap rank estimate before any
  factors are built.
- Level 1 (operational): delete-k + greedy repair over {-1,0,1}, seeded
  from the best Level 2 output and bounded by the remaining time budget.
  Every repair is verified with the exact checker before adoption.

run_multiscale(n, time_budget_secs, seed) orchestrates 3 -> 2 -> 1 and
returns (best_rank, best_decomposition, level_report). A level that finds
nothing better simply passes the incumbent down; nothing at any level is
trusted without exact verification.
"""

from __future__ import annotations

import itertools
import random
import time

from verify import check
from composition import (
    Decomposition, REGISTRY, block_embed, direct_sum, naive_fill,
    search_compositions,
)
from adversarial import (
    _triple_contribution, _residual_violations, _greedy_repair,
)

# Budget split across levels: L3 gets the most because structural wins
# dominate; L1 gets the least because it is a bounded local polish.
_LEVEL_FRACTIONS = (0.40, 0.35, 0.25)


def _E(n, i, j, s=1):
    m = [[0] * n for _ in range(n)]
    m[i][j] = s
    return m


def _set_partitions(indices):
    """Yield all set partitions of the index list (Bell-number many)."""
    if not indices:
        yield []
        return
    first, rest = indices[0], indices[1:]
    for part in _set_partitions(rest):
        # Put `first` in its own new block.
        yield [[first]] + [list(b) for b in part]
        # Or add `first` to each existing block, one at a time.
        for i, block in enumerate(part):
            new_part = [list(b) for b in part]
            new_part[i] = [first] + list(block)
            yield new_part


def _cross_terms_for_block(n, block):
    """Rank-1 triples for A[block x K]·B[K x block], K = complement of block."""
    K = [k for k in range(n) if k not in block]
    triples = []
    for r in block:
        for c in block:
            for k in K:
                triples.append([_E(n, r, k), _E(n, k, c), _E(n, r, c)])
    return triples


def _level2_estimate(n, assignment):
    """Cheap rank estimate for a block assignment, before building factors.

    assignment: list of (block, decomposition). Returns the exact rank the
    construction would have, computed arithmetically (no factor building).
    """
    total = 0
    covered = 0
    for block, decomp in assignment:
        m = len(block)
        total += decomp.rank + m * m * (n - m)  # block + cross terms
        covered += m * m
    total += (n * n - covered) * n  # naive fill for the rest
    return total


def _build_level2(n, assignment, seed):
    """Build a Decomposition for a block assignment and verify it exactly.

    Returns (rank, decomposition) if feasible, else None.
    """
    parts = []
    covered = set()
    for block, decomp in assignment:
        block = sorted(block)
        parts.append(block_embed(decomp, n, block, block))
        cross = _cross_terms_for_block(n, block)
        cross_decomp = Decomposition(
            f"cross({block})", n=n, rank=len(cross),
            factors_fn=lambda c=cross: c,
            description=f"Cross-block rank-1 terms for block {block}",
            construction={
                "op": "border_terms", "n": n, "rank": len(cross),
                "name": f"cross({block})",
                "note": f"cross-block A[block x K]·B[K x block] terms for {block}",
            },
        )
        parts.append(cross_decomp)
        covered.update((r, c) for r in block for c in block)
    parts.append(naive_fill(n, covered))

    names = "+".join(f"{d.name}@{sorted(b)}" for b, d in assignment)
    decomp = direct_sum(*parts)
    decomp.name = f"level2({names})"
    decomp.description = (
        "Level 2 block partition: "
        + ", ".join(f"{d.name} on block {sorted(b)}" for b, d in assignment)
    )
    decomp.construction = {
        "op": "level2_partition", "n": n, "rank": decomp.rank,
        "name": decomp.name,
        "note": decomp.description,
        "blocks": [
            {"block": sorted(b), "decomposition": d.construction}
            for b, d in assignment
        ],
    }
    res = check(decomp.factors(), n)
    if res.get("feasible"):
        return decomp.rank, decomp
    return None


def level2_block_search(n, rank_cap, time_budget_secs, seed=0, verbose=True):
    """Enumerate block partitions, keeping verified decompositions under rank_cap.

    Returns a list of (rank, decomposition) sorted by rank. Only
    candidates whose estimated rank is strictly below rank_cap are built
    and verified; the time budget bounds the whole enumeration.
    """
    deadline = time.monotonic() + time_budget_secs
    rng = random.Random(seed)
    found = []
    seen = set()

    partitions = list(_set_partitions(list(range(n))))
    rng.shuffle(partitions)

    for part in partitions:
        if time.monotonic() >= deadline:
            break
        # Every block needs a registry decomposition of matching size.
        options = []
        valid = True
        for block in part:
            choices = [d for d in REGISTRY.values() if d.n == len(block)]
            if not choices:
                valid = False
                break
            options.append([(block, d) for d in choices])
        if not valid:
            continue
        assignments = list(itertools.product(*options))
        rng.shuffle(assignments)
        for assignment in assignments:
            if time.monotonic() >= deadline:
                break
            assignment = list(assignment)
            est = _level2_estimate(n, assignment)
            if est >= rank_cap:
                continue
            key = (est, tuple(sorted((tuple(sorted(b)), d.name) for b, d in assignment)))
            if key in seen:
                continue
            seen.add(key)
            hit = _build_level2(n, assignment, seed)
            if hit is not None:
                rank, decomp = hit
                if rank < rank_cap:
                    found.append((rank, decomp))
                    if verbose:
                        print(f"  Level 2: {decomp.name[:60]}... → rank {rank} ✓")

    found.sort(key=lambda t: (t[0], t[1].name))
    return found


def level1_repair(factors, n, time_budget_secs, seed=0, verbose=True):
    """Delete-k + greedy repair over {-1,0,1}, seeded from a feasible decomposition.

    Phase A: every single deletion, deterministically — adopt any deletion
    that stays feasible (rank drops by 1 each time).
    Phase B: random delete-2 + bounded greedy repair; adopt if the repair
    restores feasibility at strictly lower rank.
    Every adoption is decided by the exact checker, never by the heuristic.

    Returns (best_factors, improvements_made). The input factors must be
    feasible; the returned factors are feasible too (or identical to input).
    """
    deadline = time.monotonic() + time_budget_secs
    rng = random.Random(seed)
    pool_size = 30 if n <= 3 else 12

    if not check(factors, n).get("feasible"):
        return factors, 0

    best = list(factors)
    improvements = 0

    def _attempt_delete(idxs):
        idxset = set(idxs)
        reduced = [t for j, t in enumerate(best) if j not in idxset]
        if check(reduced, n).get("feasible"):
            return reduced
        return None

    # Phase A: deterministic delete-1, repeat while anything improves.
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        for i in range(len(best)):
            if time.monotonic() >= deadline:
                break
            hit = _attempt_delete([i])
            if hit is not None and len(hit) < len(best):
                best = hit
                improvements += 1
                improved = True
                if verbose:
                    print(f"  Level 1: delete-1 → rank {len(best)} ✓")
                break

    # Phase B: random delete-2 + greedy repair.
    while time.monotonic() < deadline and len(best) > 1:
        i, j = rng.sample(range(len(best)), 2)
        contribs = [_triple_contribution(t, n) for t in best]
        n6 = len(contribs[0])
        removed_sum = [0] * n6
        for idx in (i, j):
            for c in range(n6):
                removed_sum[c] += contribs[idx][c]
        added = _greedy_repair(rng, n, removed_sum, pool_size, deadline,
                               max_rounds=2)
        if not added:
            continue
        added_contribs = [c for _, c in added]
        if _residual_violations(added_contribs, removed_sum) != 0:
            continue
        idxset = {i, j}
        candidate = [t for m, t in enumerate(best) if m not in idxset]
        candidate += [t for t, _ in added]
        if len(candidate) < len(best) and check(candidate, n).get("feasible"):
            best = candidate
            improvements += 1
            if verbose:
                print(f"  Level 1: delete-2+repair → rank {len(best)} ✓")

    return best, improvements


def _repaired_decomposition(base, factors):
    """Wrap repaired factors in a Decomposition carrying the provenance."""
    rank = len(factors)
    return Decomposition(
        f"repaired({base.name})", n=base.n, rank=rank,
        factors_fn=lambda f=list(factors): f,
        description=f"Level 1 delete-and-repair of {base.name}, rank {rank}",
        construction={
            "op": "level1_repair", "n": base.n, "rank": rank,
            "name": f"repaired({base.name})",
            "note": f"delete-k + greedy repair over {{-1,0,1}} seeded from {base.name}",
            "base": base.construction,
        },
    )


def run_multiscale(n, time_budget_secs, seed=0, verbose=True):
    """Run Level 3 -> Level 2 -> Level 1, keeping the best verified result.

    Returns (best_rank, best_decomposition, level_report). The best
    decomposition is always exactly verified; a level that finds nothing
    better just passes the incumbent down.
    """
    t0 = time.monotonic()
    f3, f2, f1 = _LEVEL_FRACTIONS
    level_report = {}

    # Level 3: composition enumeration over the registry.
    t3 = time.monotonic()
    l3 = search_compositions(n, max_rank=n ** 3 - 1,
                             time_budget_secs=f3 * time_budget_secs,
                             seed=seed)
    level_report["level3"] = {
        "candidates_verified": len(l3),
        "best_rank": l3[0][0] if l3 else None,
        "seconds": round(time.monotonic() - t3, 2),
    }
    if not l3:
        return None, None, level_report
    best_rank, best = l3[0]
    if verbose:
        print(f"Level 3 best: {best.name[:60]} rank {best_rank}")

    # Level 2: block-partition enumeration, strictly improving only.
    t2 = time.monotonic()
    l2 = level2_block_search(n, rank_cap=best_rank,
                             time_budget_secs=f2 * time_budget_secs,
                             seed=seed + 1, verbose=verbose)
    level_report["level2"] = {
        "candidates_verified": len(l2),
        "best_rank": l2[0][0] if l2 else best_rank,
        "seconds": round(time.monotonic() - t2, 2),
    }
    if l2 and l2[0][0] < best_rank:
        best_rank, best = l2[0]
        if verbose:
            print(f"Level 2 improved: rank {best_rank}")

    # Level 1: delete-and-repair polish on the incumbent.
    t1 = time.monotonic()
    factors, improvements = level1_repair(
        best.factors(), n, time_budget_secs=f1 * time_budget_secs,
        seed=seed + 2, verbose=verbose)
    level_report["level1"] = {
        "improvements": improvements,
        "best_rank": len(factors),
        "seconds": round(time.monotonic() - t1, 2),
    }
    if len(factors) < best_rank:
        best = _repaired_decomposition(best, factors)
        best_rank = len(factors)
        if verbose:
            print(f"Level 1 improved: rank {best_rank}")

    level_report["total_seconds"] = round(time.monotonic() - t0, 2)
    level_report["final_rank"] = best_rank
    return best_rank, best, level_report


if __name__ == "__main__":
    rank, decomp, report = run_multiscale(3, 60, seed=0)
    print("best rank:", rank)
    print("best:", decomp.name if decomp else None)
    print("report:", report)
