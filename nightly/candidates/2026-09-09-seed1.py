#!/usr/bin/env python3
"""Night-1 candidate: sparsity-constrained exact search (sparse SMT).

Idea: optimal matrix-multiplication decompositions use sparse factor matrices.
Constraining each factor to at most K nonzeros makes exact SMT search tractable.
This rediscovers Strassen (n=2, R=7, K=2) in ~25s and provides a principled
attack on n=3/n=4 via rank reduction.

For each target n, tries R = champion_rank - 1 (n=2: R=7 calibration).
Saves the solution atomically iff the independent verifier accepts it.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify import check  # noqa: E402

try:
    from z3 import Int, Solver, sat, If
    HAVE_Z3 = True
except ImportError:
    HAVE_Z3 = False


# (n -> (R to try, max nonzeros per factor))
PLAN = {
    2: (7, 2),
    3: (26, 3),
    4: (63, 2),
}


def find_sparse(n, R, max_nz, timeout_ms, seed):
    s = Solver()
    s.set("random_seed", seed)
    if timeout_ms:
        s.set("timeout", timeout_ms)
    U = [[[Int(f"U_{r}_{a}_{b}") for b in range(n)] for a in range(n)] for r in range(R)]
    V = [[[Int(f"V_{r}_{c}_{d}") for d in range(n)] for c in range(n)] for r in range(R)]
    W = [[[Int(f"W_{r}_{e}_{f}") for f in range(n)] for e in range(n)] for r in range(R)]
    for M in (U, V, W):
        for r in range(R):
            for a in range(n):
                for b in range(n):
                    s.add(M[r][a][b] >= -1, M[r][a][b] <= 1)
    for r in range(R):
        for M in (U[r], V[r], W[r]):
            s.add(sum(If(M[a][b] != 0, 1, 0) for a in range(n) for b in range(n)) <= max_nz)
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(n):
                    for e in range(n):
                        for f in range(n):
                            t = 1 if (a == e and b == c and d == f) else 0
                            s.add(sum(U[r][a][b] * V[r][c][d] * W[r][e][f] for r in range(R)) == t)
    if s.check() != sat:
        return None
    m = s.model()

    def get(M):
        return [[[m.evaluate(M[r][a][b]).as_long() for b in range(n)] for a in range(n)] for r in range(R)]

    return get(U), get(V), get(W)


def save(out, target, U, V, W):
    R = len(U)
    factors = [[U[r], V[r], W[r]] for r in range(R)]
    res = check(factors, int(target))
    if not res["feasible"]:
        return False
    payload = {"target": target, "rank": R, "factors": factors,
               "method": "sparse-smt", "note": "sparsity-constrained exact SMT search"}
    tmp = out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, out)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    n = int(args.target)

    if not HAVE_Z3:
        print("z3 not available", flush=True)
        return

    if n not in PLAN:
        print(f"no plan for n={n}", flush=True)
        return

    R, max_nz = PLAN[n]
    # Reserve 10s for save/verify overhead; give the rest to z3.
    z3_ms = int(max(10, args.time - 15) * 1000)
    print(f"sparse-smt: n={n} R={R} max_nz={max_nz} z3_timeout={z3_ms}ms seed={args.seed}", flush=True)
    t0 = time.time()
    res = find_sparse(n, R, max_nz, z3_ms, args.seed)
    dt = time.time() - t0
    if res is None:
        print(f"sparse-smt: n={n} no solution (unsat or timeout, {dt:.1f}s)", flush=True)
        return
    U, V, W = res
    if save(args.out, args.target, U, V, W):
        print(f"sparse-smt: n={n} FOUND rank {R} ({dt:.1f}s), saved", flush=True)
    else:
        print(f"sparse-smt: n={n} z3 solution failed verification!", flush=True)


if __name__ == "__main__":
    main()
