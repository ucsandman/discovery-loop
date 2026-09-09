"""Explanation requirement for discovery-loop candidates.

Every candidate must include a human-readable proof sketch explaining WHY
it works, not just THAT it works. This forces structural understanding:
if the loop can't explain a construction, it can't build on it.

The proof sketch is stored alongside the factors JSON and must cover:
1. Construction: how was this built? (composition tree, search, etc.)
2. Correctness argument: why does it compute the right answer?
3. Rank analysis: where does each triple go? (output coverage map)
4. Novelty: what makes this different from existing decompositions?
"""

from __future__ import annotations

import json


PROOF_SKETCH_TEMPLATE = """# Proof Sketch: {name}

## Construction
{construction}

## Correctness Argument
{correctness}

## Rank Analysis
Total rank: {rank}
{rank_breakdown}

## Output Coverage
{coverage}

## Novelty
{novelty}
"""


def generate_proof_sketch(decomposition, coverage_map=None) -> str:
    """Auto-generate a proof sketch skeleton from a Decomposition.

    The loop fills in the construction and correctness sections;
    rank breakdown and coverage are computed automatically.
    """
    # Build rank breakdown from the composition tree
    breakdown = _rank_breakdown(decomposition, indent=0)

    # Build coverage map: which outputs does each part touch?
    if coverage_map is None:
        coverage_map = _compute_coverage(decomposition)

    return PROOF_SKETCH_TEMPLATE.format(
        name=decomposition.name,
        construction=f"[TODO: describe how {decomposition.name} was constructed]\n"
                     f"Base components: {decomposition.description}",
        correctness="[TODO: explain why this correctly computes C = A·B]",
        rank=decomposition.rank,
        rank_breakdown=breakdown,
        coverage=coverage_map,
        novelty="[TODO: what makes this different from naive/Strassen/Laderman?]",
    )


def _rank_breakdown(decomp, indent=0) -> str:
    """Recursively break down rank by composition tree."""
    prefix = "  " * indent
    lines = [f"{prefix}- {decomp.name}: rank {decomp.rank}"]
    # If it's a direct_sum or other composite, recurse into parts
    # (we store parts as an attribute on composite decompositions)
    parts = getattr(decomp, '_parts', None)
    if parts:
        for p in parts:
            lines.append(_rank_breakdown(p, indent + 1))
    return "\n".join(lines)


def _compute_coverage(decomp) -> str:
    """Compute which outputs each triple writes to (W matrix support)."""
    n = decomp.n
    factors = decomp.factors()
    # For each output (e,f), count triples with W[e][f] != 0
    output_counts = {}
    for (U, V, W) in factors:
        for e in range(n):
            for f in range(n):
                if W[e][f] != 0:
                    output_counts[(e, f)] = output_counts.get((e, f), 0) + 1

    lines = [f"Output coverage for {n}×{n} ({len(factors)} triples):"]
    for e in range(n):
        row = []
        for f in range(n):
            c = output_counts.get((e, f), 0)
            row.append(f"C[{e}][{f}]:{c}")
        lines.append("  " + " ".join(row))

    # Check: every output must be covered by at least one triple
    uncovered = [(e, f) for e in range(n) for f in range(n)
                 if (e, f) not in output_counts]
    if uncovered:
        lines.append(f"  WARNING: uncovered outputs: {uncovered}")
    else:
        lines.append("  All outputs covered ✓")

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
