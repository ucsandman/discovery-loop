"""Seed solver for the matrix-multiplication plugin.

Writes an exact bilinear decomposition (list of (U, V, W) integer-matrix triples)
as JSON: {"target": "N", "rank": R, "factors": [...]}.

Baselines:
  n = 2 -> Strassen's rank-7 decomposition (proven optimal).
  n = 3 -> naive rank-27 decomposition (best known: 23, Laderman 1976).
  n = 4 -> naive rank-64 decomposition (best known: 49, Strassen recursion).

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


def factors_for(n):
    if n == 2:
        return strassen_factors()
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
