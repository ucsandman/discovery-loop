"""Adversarial checking: breaker agent for discovery-loop candidates.

Every candidate decomposition must survive adversarial scrutiny before
promotion. The breaker tries to:
1. Find a counterexample (random integer matrices where candidate != naive)
2. Prove infeasibility (show the tensor identity fails for some indices)
3. Find redundant triples (triples that can be removed without breaking correctness)
4. Check for hidden assumptions (e.g., does it only work for specific inputs?)

This is how mathematics actually works: conjecture → attack → refine.
"""

from __future__ import annotations

import random


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
        print("  [1/3] Redundancy attack...")
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
