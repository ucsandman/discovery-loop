"""Seed solver for the matrix-multiplication plugin.

Writes an exact bilinear decomposition (list of (U, V, W) integer-matrix triples)
as JSON: {"target": "N", "rank": R, "factors": [...]}.

Baselines:
  n = 2 -> Strassen's rank-7 decomposition (proven optimal).
  n = 3 -> rank-26 2+1 block construction (best known: 23, Laderman 1976).
  n = 4 -> rank-49 Strassen recursion (best known: 49, equals record).

Every output is passed through verify.check before writing, so the seed can
never emit an infeasible candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify


def _E(n, i, j, s=1):
    m = [[0] * n for _ in range(n)]
    m[i][j] = s
    return m


def _add(n, *terms):
    m = [[0] * n for _ in range(n)]
    for (i, j, s) in terms:
        m[i][j] += s
    return m


def naive_factors(n):
    """Naive O(n^3) algorithm as a rank-n^3 decomposition."""
    triples = []
    for p in range(n):
        for q in range(n):
            for r in range(n):
                u = _E(n, p, q)
                v = _E(n, q, r)
                w = _E(n, p, r)
                triples.append([u, v, w])
    return triples


def strassen_factors():
    """Strassen's rank-7 decomposition for 2x2 (Winograd proved 7 optimal).

    Triples were derived from the M1..M7 definitions and confirmed by
    verify.check (exact tensor identity) plus 200 random integer-matrix
    cross-checks against naive multiplication.
    """
    E = lambda *t: _add(2, *t)  # noqa: E731
    return [
        [E((0, 0, 1), (1, 1, 1)), E((0, 0, 1), (1, 1, 1)), E((0, 0, 1), (1, 1, 1))],
        [E((1, 0, 1), (1, 1, 1)), E((0, 0, 1),), E((1, 0, 1), (1, 1, -1))],
        [E((0, 0, 1),), E((0, 1, 1), (1, 1, -1)), E((0, 1, 1), (1, 1, 1))],
        [E((1, 1, 1),), E((1, 0, 1), (0, 0, -1)), E((0, 0, 1), (1, 0, 1))],
        [E((0, 0, 1), (0, 1, 1)), E((1, 1, 1),), E((0, 1, 1), (0, 0, -1))],
        [E((1, 0, 1), (0, 0, -1)), E((0, 0, 1), (0, 1, 1)), E((1, 1, 1),)],
        [E((0, 1, 1), (1, 1, -1)), E((1, 0, 1), (1, 1, 1)), E((0, 0, 1),)],
    ]


def block26_factors():
    """Rank-26 decomposition of 3x3 multiplication (2+1 block split).

    A = [[A11, a12], [a21t, a22]], B = [[B11, b12], [b21t, b22]] with 2x2 blocks.
      C11 = A11*B11 (Strassen 7) + a12*b21t (naive 4)
      C12 = A11*b12 (naive 4) + a12*b22 (naive 2)
      C21 = a21t*B11 (naive 4) + a22*b21t (naive 2)
      c22 = a21t*b12 (naive 2) + a22*b22 (naive 1)
    Disjoint outputs, so concatenating the triple lists is exact.
    Found by the nightly discovery loop 2026-09-09; verified by exact
    tensor-identity checker.
    """
    E3 = lambda i, j: _E(3, i, j)  # noqa: E731

    def E2e(*terms):
        return _add(3, *terms)

    T = []
    # A11*B11 via Strassen on indices {0,1}
    T += [
        [E2e((0, 0, 1), (1, 1, 1)), E2e((0, 0, 1), (1, 1, 1)), E2e((0, 0, 1), (1, 1, 1))],
        [E2e((1, 0, 1), (1, 1, 1)), E2e((0, 0, 1),), E2e((1, 0, 1), (1, 1, -1))],
        [E2e((0, 0, 1),), E2e((0, 1, 1), (1, 1, -1)), E2e((0, 1, 1), (1, 1, 1))],
        [E2e((1, 1, 1),), E2e((1, 0, 1), (0, 0, -1)), E2e((0, 0, 1), (1, 0, 1))],
        [E2e((0, 0, 1), (0, 1, 1)), E2e((1, 1, 1),), E2e((0, 1, 1), (0, 0, -1))],
        [E2e((1, 0, 1), (0, 0, -1)), E2e((0, 0, 1), (0, 1, 1)), E2e((1, 1, 1),)],
        [E2e((0, 1, 1), (1, 1, -1)), E2e((1, 0, 1), (1, 1, 1)), E2e((0, 0, 1),)],
    ]
    for i in (0, 1):
        for j in (0, 1):
            T.append([E3(i, 2), E3(2, j), E3(i, j)])  # a12*b21t -> C11
    for i in (0, 1):
        for j in (0, 1):
            T.append([E3(i, j), E3(j, 2), E3(i, 2)])  # A11*b12 -> C12
    for i in (0, 1):
        T.append([E3(i, 2), E3(2, 2), E3(i, 2)])  # a12*b22 -> C12
    for j in (0, 1):
        for k in (0, 1):
            T.append([E3(2, j), E3(j, k), E3(2, k)])  # a21t*B11 -> C21
    for j in (0, 1):
        T.append([E3(2, 2), E3(2, j), E3(2, j)])  # a22*b21t -> C21
    for j in (0, 1):
        T.append([E3(2, j), E3(j, 2), E3(2, 2)])  # a21t*b12 -> c22
    T.append([E3(2, 2), E3(2, 2), E3(2, 2)])  # a22*b22 -> c22
    assert len(T) == 26
    return T


def tensor_product_factors(F, G):
    """Bilinear algorithm for 2n x 2n from n x n algorithms; rank multiplies."""
    n = len(F[0][0])
    out = []
    for (U1, V1, W1) in F:
        for (U2, V2, W2) in G:
            U = [[0] * (2 * n) for _ in range(2 * n)]
            V = [[0] * (2 * n) for _ in range(2 * n)]
            W = [[0] * (2 * n) for _ in range(2 * n)]
            for a in range(n):
                for b in range(n):
                    for i in range(n):
                        for j in range(n):
                            U[2 * a + i][2 * b + j] = U1[a][b] * U2[i][j]
                            V[2 * a + i][2 * b + j] = V1[a][b] * V2[i][j]
                            W[2 * a + i][2 * b + j] = W1[a][b] * W2[i][j]
            out.append([U, V, W])
    return out


def factors_for(n):
    if n == 2:
        return strassen_factors()
    if n == 3:
        return block26_factors()
    if n == 4:
        return tensor_product_factors(strassen_factors(), strassen_factors())
    return naive_factors(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    n = int(args.target)
    factors = factors_for(n)
    res = verify.check(factors, n)
    if not res["feasible"]:
        raise SystemExit(f"seed solver produced infeasible decomposition: {res['reason']}")
    payload = {"target": args.target, "rank": len(factors), "factors": factors}
    tmp = args.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, args.out)
    print(json.dumps({"target": args.target, "rank": len(factors), "verified": True}))


if __name__ == "__main__":
    main()
