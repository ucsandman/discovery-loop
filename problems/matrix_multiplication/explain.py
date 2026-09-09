"""Explanation requirement for discovery-loop candidates.

Every candidate must include a human-readable proof sketch explaining WHY
it works, not just THAT it works. This forces structural understanding:
if the loop can't explain a construction, it can't build on it.

generate_proof_sketch(decomposition) produces six sections, all filled with
real computed content — never placeholders:

1. Title: what the decomposition is (name, n, rank).
2. Construction: the construction tree, walked via
   decomposition.describe_construction().
3. Rank breakdown: per-component rank contributions computed from the
   construction tree; the numbers add up to the total rank (tensor
   products multiply instead of adding, which is stated explicitly).
4. Correctness: the exact tensor-identity checker from verify.py is RUN on
   the factors and its verdict reported. Correctness is never claimed
   without running the checker.
5. Output coverage map: for each output entry (i, j), the triple indices
   whose W matrix touches it, computed from the factors.
6. Novelty: rank compared against real baselines (naive n^3, Strassen,
   Laderman). A new record is claimed only if rank is strictly below the
   best known figure.

No figure in the sketch is invented: every number is computed from the
decomposition's factors or construction tree, or comes from the curated
baselines below.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verify import check


# Curated baselines. "best known" figures are the published records;
# a new record is claimed only against these, never against naive.
BASELINES = {
    2: [
        (8, "naive n^3"),
        (7, "Strassen 1969 — proven optimal"),
    ],
    3: [
        (27, "naive n^3"),
        (23, "Laderman 1976 — best known"),
    ],
    4: [
        (64, "naive n^3"),
        (49, "Strassen recursion — best known"),
    ],
}


PROOF_SKETCH_TEMPLATE = """# Proof Sketch: {name} (n={n}, rank={rank})

## Construction
{construction}

## Rank Breakdown
{rank_breakdown}

## Correctness
{correctness}

## Output Coverage
{coverage}

## Novelty
{novelty}
"""


def generate_proof_sketch(decomposition) -> str:
    """Generate a complete proof sketch for a Decomposition.

    All six sections are filled with computed content. The exact checker
    is run on the factors; nothing is claimed without evidence.
    """
    n = decomposition.n
    rank = decomposition.rank

    return PROOF_SKETCH_TEMPLATE.format(
        name=decomposition.name,
        n=n,
        rank=rank,
        construction=decomposition.describe_construction(),
        rank_breakdown=_rank_breakdown(decomposition),
        correctness=_correctness_section(decomposition),
        coverage=_coverage_section(decomposition),
        novelty=_novelty_section(decomposition),
    )


# ---------------------------------------------------------------------------
# Rank breakdown: per-component contributions from the construction tree
# ---------------------------------------------------------------------------

def _tree_total(construction) -> int:
    """Recompute the expected total rank from a construction tree."""
    op = construction.get("op", "opaque")
    rank = construction.get("rank")
    if op == "direct_sum":
        return sum(_tree_total(p) for p in construction["parts"])
    if op == "tensor_product":
        return _tree_total(construction["left"]) * _tree_total(construction["right"])
    # library, block_embed, naive_fill, border_terms, opaque: rank is as stored
    return rank


def _breakdown_lines(construction, indent=0) -> list[str]:
    """Render per-component rank contributions; numbers must add up."""
    pad = "  " * indent
    op = construction.get("op", "opaque")
    rank = construction.get("rank")
    if op == "direct_sum":
        lines = [f"{pad}direct_sum — total rank {rank} = "
                 f"{' + '.join(str(p.get('rank')) for p in construction['parts'])} "
                 f"({len(construction['parts'])} parts):"]
        for i, part in enumerate(construction["parts"]):
            lines.append(f"{pad}  part {i + 1}:")
            lines.extend(_breakdown_lines(part, indent + 2))
        return lines
    if op == "tensor_product":
        left, right = construction["left"], construction["right"]
        lines = [f"{pad}tensor_product — rank multiplies: "
                 f"{left.get('rank')} x {right.get('rank')} = {rank}:"]
        lines.append(f"{pad}  left factor:")
        lines.extend(_breakdown_lines(left, indent + 2))
        lines.append(f"{pad}  right factor:")
        lines.extend(_breakdown_lines(right, indent + 2))
        return lines
    if op == "block_embed":
        lines = [f"{pad}block_embed of '{construction['base_name']}' "
                 f"at rows={construction['rows']}, cols={construction['cols']} — "
                 f"rank {rank} (embedding preserves rank):"]
        lines.extend(_breakdown_lines(construction["base"], indent + 1))
        return lines
    if op == "naive_fill":
        return [f"{pad}naive_fill — {construction['outputs']} uncovered outputs "
                f"x {construction['n']} = rank {rank}"]
    if op == "border_terms":
        return [f"{pad}border_terms — {construction['note']} — rank {rank}"]
    if op == "library":
        year = f" ({construction['year']})" if construction.get("year") else ""
        return [f"{pad}library: '{construction['name']}' — "
                f"{construction['citation']}{year} — rank {rank}"]
    return [f"{pad}{op}: {construction.get('name', '?')} — rank {rank}"]


def _rank_breakdown(decomposition) -> str:
    """Rank contributions per component, with an arithmetic consistency check."""
    lines = _breakdown_lines(decomposition.construction)
    tree_total = _tree_total(decomposition.construction)
    if tree_total == decomposition.rank:
        lines.append(f"Check: components account for {tree_total} = "
                     f"declared rank {decomposition.rank}.")
    else:
        lines.append(f"WARNING: construction tree accounts for {tree_total} "
                     f"but declared rank is {decomposition.rank}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Correctness: run the exact checker, report its verdict
# ---------------------------------------------------------------------------

def _correctness_section(decomposition) -> str:
    """Run the exact tensor-identity checker and report what it says."""
    factors = decomposition.factors()
    result = check(factors, decomposition.n)
    feasible = result.get("feasible")
    lines = [
        f"Exact tensor-identity check (verify.check on {len(factors)} triples, "
        f"n={decomposition.n}):",
        f"  feasible: {feasible}",
    ]
    reason = result.get("reason")
    if reason:
        lines.append(f"  detail: {reason}")
    if feasible:
        lines.append("  The decomposition provably computes C = A*B: every one of "
                     "the n^6 tensor equations holds over the integers.")
    else:
        lines.append("  WARNING: the checker rejects this decomposition — "
                     "do not trust or promote it.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output coverage: which triples write to which outputs
# ---------------------------------------------------------------------------

def _coverage_section(decomposition) -> str:
    """For each output (i, j), list the triple indices whose W touches it."""
    n = decomposition.n
    factors = decomposition.factors()
    contributors: dict[tuple[int, int], list[int]] = {}
    for t, (_U, _V, W) in enumerate(factors):
        for e in range(n):
            for f in range(n):
                if W[e][f] != 0:
                    contributors.setdefault((e, f), []).append(t)

    lines = [f"Output coverage for {n}x{n} ({len(factors)} triples):"]
    uncovered = []
    thin = []
    for e in range(n):
        row = []
        for f in range(n):
            ts = contributors.get((e, f), [])
            if not ts:
                uncovered.append((e, f))
            elif len(ts) == 1:
                thin.append((e, f))
            row.append(f"C[{e}][{f}]:{len(ts)}")
        lines.append("  " + " ".join(row))

    lines.append("")
    if uncovered:
        lines.append(f"  UNCOVERED outputs (no triple writes here): {uncovered}")
    else:
        lines.append("  Every output is covered by at least one triple.")
    if thin:
        lines.append(f"  Thinly covered (exactly one triple): {thin}")

    # Triple-level detail: which outputs each triple touches
    lines.append("")
    lines.append("  Per-triple output support:")
    for t, (_U, _V, W) in enumerate(factors):
        outs = [(e, f) for e in range(n) for f in range(n) if W[e][f] != 0]
        lines.append(f"    triple {t}: {len(outs)} outputs {outs}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Novelty: rank vs real baselines, honest record claims
# ---------------------------------------------------------------------------

def _novelty_section(decomposition) -> str:
    """Compare rank against curated baselines; claim records only if earned."""
    n = decomposition.n
    rank = decomposition.rank
    lines = [f"Rank {rank} for {n}x{n} matrix multiplication."]
    baselines = BASELINES.get(n, [(n ** 3, "naive n^3")])
    best_known = None
    best_cite = ""
    for b_rank, cite in baselines:
        if "best known" in cite or "proven optimal" in cite:
            if best_known is None or b_rank < best_known:
                best_known, best_cite = b_rank, cite
        if b_rank == n ** 3:
            lines.append(f"  vs naive n^3 = {b_rank}: "
                         f"{'saves ' + str(b_rank - rank) + ' multiplications' if rank < b_rank else 'no improvement'}")
        elif rank == b_rank:
            lines.append(f"  vs {cite} (rank {b_rank}): equal — matches, does not beat")
        elif rank < b_rank:
            lines.append(f"  vs {cite} (rank {b_rank}): BETTER by {b_rank - rank}")
        else:
            lines.append(f"  vs {cite} (rank {b_rank}): worse by {rank - b_rank}")
    if best_known is not None:
        if rank < best_known:
            lines.append(f"  NEW RECORD: rank {rank} beats the best known {best_known} "
                         f"({best_cite}).")
        elif rank == best_known and "proven optimal" in best_cite:
            lines.append(f"  Matches the proven optimum ({best_cite}).")
        else:
            lines.append(f"  Not a new record: best known is {best_known} ({best_cite}); "
                         f"gap = {rank - best_known}.")
    return "\n".join(lines)


def save_with_proof_sketch(decomp, out_path: str, proof_sketch: str = None):
    """Save a decomposition with its proof sketch as a sidecar file."""
    factors = decomp.factors()
    payload = {
        "target": str(decomp.n),
        "rank": len(factors),
        "factors": factors,
        "decomposition_name": decomp.name,
        "description": decomp.description,
    }
    with open(out_path, "w") as fh:
        json.dump(payload, fh)

    sketch_path = out_path.replace(".json", ".proof.md")
    if proof_sketch is None:
        proof_sketch = generate_proof_sketch(decomp)
    with open(sketch_path, "w") as fh:
        fh.write(proof_sketch)

    return out_path, sketch_path


if __name__ == "__main__":
    from composition import block26_composition

    decomp = block26_composition()
    sketch = generate_proof_sketch(decomp)

    assert "[TODO]" not in sketch, "placeholder leaked into proof sketch"
    sections = ["# Proof Sketch:", "## Construction", "## Rank Breakdown",
                "## Correctness", "## Output Coverage", "## Novelty"]
    for s in sections:
        assert s in sketch, f"missing section: {s}"
        body = sketch.split(s, 1)[1].split("##", 1)[0].strip() if s.startswith("##") else ""
        if s.startswith("##"):
            assert body, f"empty section: {s}"
    print(f"All 6 sections present and non-empty. Sketch length: {len(sketch)} chars.")
