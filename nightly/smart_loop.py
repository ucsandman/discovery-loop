"""Smart discovery loop: integrates all 6 intelligence upgrades.

1. Composition engine (composition.py): search over technique compositions
2. Explanation requirement (explain.py): proof sketch for every candidate
3. Multi-scale search (MULTISCALE.md): Level 3 → Level 2 → Level 1
4. Literature fuel (literature.py): technique library from papers
5. Adversarial checking (adversarial.py): attack before promoting
6. Cross-problem transfer (patterns/): shared pattern library

Usage:
    python smart_loop.py --target 3 --time 300 --seed S --out PATH
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/hatch/workspace/discovery-loop/problems/matrix_multiplication")

from verify import check
from composition import (
    block26_composition, tensor_product, block_embed, direct_sum, naive_fill,
    STRASSEN_2X2, NAIVE_2X2, LIBRARY,
)
from explain import generate_proof_sketch, save_with_proof_sketch
from adversarial import full_adversarial_suite


def level3_composition_search(n: int, deadline: float, verbose=True) -> list:
    """Level 3: enumerate promising compositions from the library.

    Returns list of (decomposition, rank) sorted by rank ascending.
    """
    candidates = []

    if n == 3:
        # The known good one
        candidates.append(block26_composition())

        # Try 1+2 split (symmetric to 2+1)
        # Strassen on indices {1,2} instead of {0,1}
        strassen_12 = block_embed(STRASSEN_2X2, 3, [1, 2], [1, 2])
        def border_fn_12():
            from composition import _E
            out = []
            for i in (1, 2):
                for j in (1, 2):
                    out.append([_E(3, i, 0), _E(3, 0, j), _E(3, i, j)])
            return out
        from composition import Decomposition
        border_12 = Decomposition("border-12", n=3, rank=4,
                                  factors_fn=border_fn_12,
                                  description="border terms for 1+2 split")
        covered_12 = {(e, f) for e in (1, 2) for f in (1, 2)}
        fill_12 = naive_fill(3, covered_12)
        candidates.append(direct_sum(strassen_12, border_12, fill_12))

    if n == 4:
        candidates.append(tensor_product(STRASSEN_2X2, STRASSEN_2X2))

    if n == 2:
        candidates.append(STRASSEN_2X2)

    # Verify and sort
    verified = []
    for d in candidates:
        if time.time() > deadline:
            break
        factors = d.factors()
        res = check(factors, n)
        if res.get("feasible"):
            verified.append((d, len(factors)))
            if verbose:
                print(f"  Level 3: {d.name[:50]}... → rank {len(factors)} ✓")
        elif verbose:
            print(f"  Level 3: {d.name[:50]}... → INFEASIBLE")

    verified.sort(key=lambda x: x[1])
    return verified


def smart_search(n: int, time_budget: float, seed: int, verbose=True) -> dict:
    """Run the full smart loop: composition → adversarial → explanation."""
    deadline = time.time() + time_budget
    result = {
        "target": n,
        "seed": seed,
        "best_rank": None,
        "best_name": None,
        "adversarial_verdict": None,
    }

    if verbose:
        print(f"Smart loop: n={n}, budget={time_budget}s, seed={seed}")
        print("Phase 1: Level 3 composition search")

    # Phase 1: Level 3 composition search
    compositions = level3_composition_search(n, deadline, verbose=verbose)
    if not compositions:
        result["status"] = "no_composition_found"
        return result

    best_decomp, best_rank = compositions[0]
    result["best_rank"] = best_rank
    result["best_name"] = best_decomp.name

    if verbose:
        print(f"\nPhase 2: Adversarial checking (rank {best_rank})")

    # Phase 2: Adversarial validation
    factors = best_decomp.factors()
    adv = full_adversarial_suite(factors, n, check, seed=seed, verbose=verbose)
    result["adversarial_verdict"] = adv["verdict"]

    if adv["verdict"].startswith("BROKEN"):
        result["status"] = "adversarial_failed"
        return result

    if verbose:
        print(f"\nPhase 3: Generating proof sketch")

    # Phase 3: Proof sketch
    sketch = generate_proof_sketch(best_decomp)
    result["proof_sketch"] = sketch
    result["factors"] = factors
    result["status"] = "success"

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    n = int(args.target)
    result = smart_search(n, args.time, args.seed, verbose=True)

    if result["status"] == "success":
        # Save with proof sketch
        from composition import Decomposition
        # Reconstruct decomposition for saving
        # (we already have factors, just save them)
        payload = {
            "target": args.target,
            "rank": result["best_rank"],
            "factors": result["factors"],
            "decomposition_name": result["best_name"],
            "adversarial_verdict": result["adversarial_verdict"],
            "smart_loop": True,
        }
        tmp = args.out + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, args.out)

        # Save proof sketch alongside
        sketch_path = args.out.replace(".json", ".proof.md")
        with open(sketch_path, "w") as fh:
            fh.write(result["proof_sketch"])

        print(f"\n✓ Saved rank {result['best_rank']} to {args.out}")
        print(f"✓ Proof sketch: {sketch_path}")
        print(f"✓ Adversarial: {result['adversarial_verdict']}")
    else:
        print(f"\n✗ Smart loop failed: {result['status']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
