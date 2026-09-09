"""Exact verifier for matrix-multiplication tensor decompositions.

A rank-R bilinear algorithm for n x n multiplication is a list of R triples
(U_r, V_r, W_r) of n x n integer matrices such that for all A, B:

    C[e,f] = sum_r (sum_{a,b} U_r[a,b] A[a,b]) (sum_{c,d} V_r[c,d] B[c,d]) W_r[e,f]
           = sum_b A[e,b] B[b,f]

Matching coefficients of A[a,b] B[c,d] gives the tensor identity checked here:
for every (a,b,c,d,e,f), sum_r U_r[a,b] V_r[c,d] W_r[e,f] must equal
delta_{a,e} * delta_{b,c} * delta_{d,f}. All arithmetic is exact integers, so
there are no tolerances and no false positives.
"""

from __future__ import annotations


def _is_int_matrix(m, n):
    if not isinstance(m, list) or len(m) != n:
        return False
    for row in m:
        if not isinstance(row, list) or len(row) != n:
            return False
        for x in row:
            if not isinstance(x, int) or isinstance(x, bool):
                return False
    return True


def check(factors, n):
    """Independently verify a decomposition. Returns a result dict.

    result = {"feasible": bool, "rank": int, "reason": str|None}
    """
    if not isinstance(n, int) or n < 2:
        return {"feasible": False, "rank": 0, "reason": "n must be an integer >= 2"}
    if not isinstance(factors, list) or not factors:
        return {"feasible": False, "rank": 0, "reason": "factors must be a non-empty list"}
    rank = len(factors)
    parsed = []
    for i, triple in enumerate(factors):
        if not isinstance(triple, (list, tuple)) or len(triple) != 3:
            return {"feasible": False, "rank": rank, "reason": f"triple {i} is not (U, V, W)"}
        u, v, w = triple
        if not _is_int_matrix(u, n) or not _is_int_matrix(v, n) or not _is_int_matrix(w, n):
            return {
                "feasible": False,
                "rank": rank,
                "reason": f"triple {i}: entries must be {n}x{n} integer matrices",
            }
        parsed.append((u, v, w))
    # Tensor identity: sum_r U_r[a,b] V_r[c,d] W_r[e,f] == d(a,e) d(b,c) d(d,f).
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(n):
                    for e in range(n):
                        # Inner loop over f; hoist the (a,b,c,d,e)-dependent part.
                        ub = [u[a][b] for (u, v, w) in parsed]
                        vd = [v[c][d] for (u, v, w) in parsed]
                        for f in range(n):
                            total = 0
                            for r in range(rank):
                                total += ub[r] * vd[r] * parsed[r][2][e][f]
                            want = 1 if (a == e and b == c and d == f) else 0
                            if total != want:
                                return {
                                    "feasible": False,
                                    "rank": rank,
                                    "reason": (
                                        f"tensor identity fails at "
                                        f"(a,b,c,d,e,f)=({a},{b},{c},{d},{e},{f}): "
                                        f"got {total}, want {want}"
                                    ),
                                }
    return {"feasible": True, "rank": rank, "reason": None}


def apply(factors, A, B):
    """Evaluate the bilinear algorithm on integer matrices A, B (independent cross-check)."""
    n = len(A)
    C = [[0] * n for _ in range(n)]
    for (u, v, w) in factors:
        alpha = sum(u[a][b] * A[a][b] for a in range(n) for b in range(n))
        beta = sum(v[c][d] * B[c][d] for c in range(n) for d in range(n))
        m = alpha * beta
        if m:
            for e in range(n):
                for f in range(n):
                    C[e][f] += m * w[e][f]
    return C


def naive_product(A, B):
    n = len(A)
    return [[sum(A[a][b] * B[b][f] for b in range(n)) for f in range(n)] for a in range(n)]
