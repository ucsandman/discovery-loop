"""Smart discovery loop for matrix multiplication.

Six modules, each honestly scoped:

1. composition.search_compositions — Level 3: enumerates operator
   applications (tensor products, block embeddings, naive fills) over a
   registry of known, exactly-verified decompositions.
2. multiscale.run_multiscale — orchestrates Level 3 (composition choice)
   -> Level 2 (block-partition enumeration) -> Level 1
   (delete-and-repair), keeping the best exactly-verified decomposition
   seen at any level.
3. adversarial.breaker_suite — promotion gate: the candidate is promoted
   only on verdict "survived". A survived verdict is bounded evidence
   from a fixed attack budget, never a proof of optimality.
4. explain.generate_proof_sketch — complete proof sketch for the promoted
   candidate: construction tree, exact-checker correctness, rank
   breakdown, output coverage, novelty vs curated baselines. No
   placeholders.
5. literature.technique_report — the curated technique registry rendered
   for context: what is already known, with citations and verification
   status. Included in the run output, not wired into search.
6. patterns.PatternLibrary.record_outcome — the run's outcome is recorded
   against the pattern ledger (success iff the promoted rank is at or
   below the best known rank for n), so future problems inherit the
   evidence.

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

from verify import check
from composition import REGISTRY  # noqa: F401  (documents the search library)
from multiscale import run_multiscale
from adversarial import breaker_suite
from explain import generate_proof_sketch
from literature import technique_report
from patterns.library import PatternLibrary

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATTERNS_DIR = os.path.join(_HERE, "patterns")

# Curated known results. Same facts as adversarial.lower_bound_check:
# n=2 is proven optimal (Strassen 1969 / Winograd 1971); n=3's 23 is the
# best known (Laderman 1976), optimality not proven.
_BEST_KNOWN = {2: 7, 3: 23}


def smart_search(n: int, time_budget: float, seed: int, verbose=True) -> dict:
    """Run the smart loop: multiscale search -> breaker gate -> explanation.

    Returns a result dict. status is "success" only when a candidate was
    found AND survived the breaker suite; otherwise "no_candidate" or
    "adversarial_failed". The pattern ledger is updated in all cases.
    """
    t0 = time.monotonic()
    result = {
        "target": n,
        "seed": seed,
        "best_rank": None,
        "best_name": None,
        "breaker_verdict": None,
        "status": None,
    }

    # Module 5: literature context — what is already known.
    lit_report = technique_report()
    result["literature_report"] = lit_report
    if verbose:
        print("Literature context (technique registry):")
        for line in lit_report.splitlines()[:8]:
            print("  " + line)

    # Modules 1+2: multi-scale search (composition enumeration inside).
    ms_budget = 0.65 * time_budget
    if verbose:
        print(f"\nSmart loop: n={n}, budget={time_budget}s, seed={seed}")
        print(f"Phase 1: multi-scale search ({ms_budget:.0f}s)")
    best_rank, best_decomp, level_report = run_multiscale(
        n, ms_budget, seed=seed, verbose=verbose)
    result["level_report"] = level_report

    def _record_patterns(success: bool, note: str, used_ops: str):
        """Record the run's outcome against the pattern ledger."""
        try:
            lib = PatternLibrary.load(_PATTERNS_DIR)
        except Exception as exc:  # ledger I/O must never fail the run
            if verbose:
                print(f"  pattern ledger unavailable: {exc}")
            return
        outcomes = [
            ("composition-search", success, note),
            ("adversarial-validation", success, note),
        ]
        if "block_embed" in used_ops:
            outcomes.append(("block-decomposition", success, note))
        if "tensor_product" in used_ops:
            outcomes.append(("tensor-recursion", success, note))
        for name, ok, note_text in outcomes:
            try:
                lib.record_outcome(name, ok, note_text)
            except KeyError:
                if verbose:
                    print(f"  pattern not in ledger, skipped: {name}")
        try:
            lib.save(_PATTERNS_DIR)
        except Exception as exc:
            if verbose:
                print(f"  pattern ledger save failed: {exc}")

    if best_decomp is None:
        result["status"] = "no_candidate"
        _record_patterns(False, f"n={n}: no verified candidate found", "")
        return result

    best_rank = best_decomp.rank
    result["best_rank"] = best_rank
    result["best_name"] = best_decomp.name
    used_ops = best_decomp.describe_construction()

    # Final exact check before the breaker (belt and suspenders).
    factors = best_decomp.factors()
    final_check = check(factors, n)
    if not final_check.get("feasible"):
        result["status"] = "verification_failed"
        _record_patterns(False, f"n={n}: best candidate failed final check", used_ops)
        return result

    # Module 3: adversarial breaker as the promotion gate.
    adv_budget = max(5.0, 0.25 * time_budget)
    if verbose:
        print(f"\nPhase 2: breaker suite (rank {best_rank}, {adv_budget:.0f}s)")
    breaker = breaker_suite(factors, n, check, seed=seed,
                            time_budget_secs=adv_budget, verbose=verbose)
    result["breaker_verdict"] = breaker["verdict"]
    result["breaker_recommendation"] = breaker["recommendation"]

    known = _BEST_KNOWN.get(n)
    if known is None:
        # No curated best known: success means promoted and sub-naive.
        success_bar = f"promoted and sub-naive (rank {best_rank} < {n ** 3})"
        is_success = breaker["verdict"] == "survived" and best_rank < n ** 3
    else:
        success_bar = f"promoted at rank {best_rank} <= best known {known}"
        is_success = breaker["verdict"] == "survived" and best_rank <= known

    if breaker["verdict"] != "survived":
        result["status"] = "adversarial_failed"
        _record_patterns(
            False,
            f"n={n}: rank {best_rank} {best_decomp.name} broken by breaker suite",
            used_ops,
        )
        return result

    # Module 4: complete proof sketch for the promoted candidate.
    if verbose:
        print("\nPhase 3: proof sketch")
    sketch = generate_proof_sketch(best_decomp)
    assert "[TODO]" not in sketch, "placeholder leaked into proof sketch"
    result["proof_sketch"] = sketch
    result["factors"] = factors
    result["status"] = "success"

    # Module 6: record the outcome in the pattern ledger.
    _record_patterns(is_success, f"n={n}: {success_bar}", used_ops)

    result["total_seconds"] = round(time.monotonic() - t0, 2)
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
        payload = {
            "target": args.target,
            "rank": result["best_rank"],
            "factors": result["factors"],
            "decomposition_name": result["best_name"],
            "breaker_verdict": result["breaker_verdict"],
            "level_report": result["level_report"],
            "smart_loop": True,
        }
        tmp = args.out + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, args.out)

        sketch_path = args.out.replace(".json", ".proof.md")
        with open(sketch_path, "w") as fh:
            fh.write(result["proof_sketch"])

        print(f"\nSaved rank {result['best_rank']} to {args.out}")
        print(f"Proof sketch: {sketch_path}")
        print(f"Breaker: {result['breaker_verdict']}")
    else:
        print(f"\nSmart loop ended: {result['status']}")
        if result.get("breaker_recommendation"):
            print(result["breaker_recommendation"])
        sys.exit(1)


if __name__ == "__main__":
    main()
