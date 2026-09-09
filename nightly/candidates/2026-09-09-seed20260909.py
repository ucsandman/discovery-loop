#!/usr/bin/env python3
"""Nightly candidate (2026-09-09): block decomposition + rank-reduction search.

Substantive improvement: a 2+1 block decomposition of 3x3 multiplication.
  C11 = A11*B11 + a12*b21t : Strassen rank 7 + naive 4  = 11 triples
  C12 = A11*b12 + a12*b22  : naive 4 + naive 2          =  6 triples
  C21 = a21t*B11 + a22*b21t : naive 4 + naive 2         =  6 triples
  c22 = a21t*b12 + a22*b22  : naive 2 + naive 1         =  3 triples
for an exact rank-26 algorithm (champion was naive rank 27). Every output is
verified with the independent exact tensor-identity checker before saving.

  n=2: Strassen rank 7 (calibration; proven optimal).
  n=4: exact rank 49 = tensor product of Strassen with itself (Strassen recursion).
  n=3: exact rank-26 block construction above; then rank-reduction passes
       (delete one triple, repair the tensor identity with focused simulated
       annealing over {-1,0,1} entries) try to go below 26 with remaining time.

Interface contract: python solver.py --target N --time SECONDS --seed S --out PATH
writes JSON {"target","rank","factors"} with exact integer matrices; stdlib+numpy
only; atomic save on every improvement.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from verify import check  # on PYTHONPATH when the nightly driver runs us


# ---------------------------------------------------------------------------
# exact building blocks
# ---------------------------------------------------------------------------

def _E(n, i, j, s=1):
    m = [[0] * n for _ in range(n)]
    m[i][j] = s
    return m


def _add(n, *terms):
    m = [[0] * n for _ in range(n)]
    for (i, j, s) in terms:
        m[i][j] += s
    return m


def strassen_factors():
    """Strassen's rank-7 decomposition for 2x2 (Winograd proved 7 optimal)."""
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


def block26_factors():
    """Exact rank-26 decomposition of 3x3 multiplication (2+1 block split).

    A = [[A11, a12], [a21t, a22]], B = [[B11, b12], [b21t, b22]] with 2x2 blocks.
      C11 = A11*B11 (Strassen 7) + a12*b21t (naive 4)
      C12 = A11*b12 (naive 4) + a12*b22 (naive 2)
      C21 = a21t*B11 (naive 4) + a22*b21t (naive 2)
      c22 = a21t*b12 (naive 2) + a22*b22 (naive 1)
    Disjoint outputs, so concatenating the triple lists is exact.
    """
    E3 = lambda i, j: _E(3, i, j)  # noqa: E731

    def E2e(*terms):
        # 2x2 Strassen-style combination embedded in 3x3 (index 2 stays zero)
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


# ---------------------------------------------------------------------------
# tensor machinery (numpy, exact integer arithmetic) for the reduction search
# ---------------------------------------------------------------------------

def target_tensor(n):
    N = n * n
    M = np.zeros((N, N, N), dtype=np.int64)
    for a in range(n):
        for b in range(n):
            for d in range(n):
                M[a * n + b, b * n + d, a * n + d] = 1
    return M


def error_tensor(U, V, W, M):
    R = U.shape[0]
    N = U.shape[1] * U.shape[2]
    T = np.einsum("ra,rb,rc->abc", U.reshape(R, N), V.reshape(R, N),
                  W.reshape(R, N))
    return T - M


def factors_to_arrays(factors, n):
    R = len(factors)
    U = np.zeros((R, n, n), dtype=np.int64)
    V = np.zeros((R, n, n), dtype=np.int64)
    W = np.zeros((R, n, n), dtype=np.int64)
    for r, (u, v, w) in enumerate(factors):
        U[r] = np.asarray(u, dtype=np.int64)
        V[r] = np.asarray(v, dtype=np.int64)
        W[r] = np.asarray(w, dtype=np.int64)
    return U, V, W


def arrays_to_factors(U, V, W):
    return [[U[r].tolist(), V[r].tolist(), W[r].tolist()]
            for r in range(U.shape[0])]


def atomic_save(out, target, factors):
    payload = {"target": target, "rank": len(factors), "factors": factors}
    tmp = out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, out)


def save_verified(out, target, factors, tag):
    """Verify with the independent exact checker, then save atomically."""
    n = int(target)
    res = check(factors, n)
    if not res["feasible"]:
        print(f"n={target} [{tag}] NOT saved (infeasible): {res['reason']}",
              flush=True)
        return False
    atomic_save(out, target, factors)
    print(f"n={target} [{tag}] saved rank {len(factors)} (verified)",
          flush=True)
    return True


# ---------------------------------------------------------------------------
# rank-reduction search for n=3 (focused simulated annealing)
# ---------------------------------------------------------------------------

def focused_repair(U, V, W, M, rng, deadline):
    """Try to repair the tensor identity before deadline.

    Focused WalkSAT-style simulated annealing over entries in {-1,0,1}:
    each iteration samples a violated tensor position and evaluates every
    single-entry move on its three target entries by the exact global energy
    delta (numpy-vectorised), taking the best with occasional noise.
    Returns True iff the exact identity was restored.
    """
    n = U.shape[1]
    R = U.shape[0]
    N = n * n
    VALS = (-1, 0, 1)
    E = error_tensor(U, V, W, M)
    energy = int((E * E).sum())
    if energy == 0:
        return True
    mats = [U, V, W]
    t_start = time.time()
    total = max(deadline - t_start, 1e-3)
    since_best = 0
    while True:
        now = time.time()
        if now >= deadline:
            return False
        frac = (now - t_start) / total
        temp = 0.5 * (0.02 / 0.5) ** frac
        nz = np.argwhere(E != 0)
        if len(nz) == 0:
            E = error_tensor(U, V, W, M)
            if int((E * E).sum()) == 0:
                return True
            energy = int((E * E).sum())
            continue
        x = tuple(nz[int(rng.integers(len(nz)))])
        if E[x] == 0:
            continue
        ab, cd, ef = x
        a, b = divmod(ab, n)
        c, d = divmod(cd, n)
        e, f = divmod(ef, n)
        Us = [U[s].ravel() for s in range(R)]
        Vs = [V[s].ravel() for s in range(R)]
        Ws = [W[s].ravel() for s in range(R)]
        cands = []
        oVW = [np.outer(Vs[s], Ws[s]) for s in range(R)]
        ee0 = E[a * n + b]
        for s in range(R):
            old = int(U[s, a, b])
            base = oVW[s]
            for nv in VALS:
                if nv == old:
                    continue
                dd = (nv - old) * base
                dE = int(((ee0 + dd) ** 2 - ee0 ** 2).sum())
                cands.append((dE, 0, s, a, b, nv, dd))
        oUW = [np.outer(Us[s], Ws[s]) for s in range(R)]
        ee1 = E[:, c * n + d, :]
        for s in range(R):
            old = int(V[s, c, d])
            base = oUW[s]
            for nv in VALS:
                if nv == old:
                    continue
                dd = (nv - old) * base
                dE = int(((ee1 + dd) ** 2 - ee1 ** 2).sum())
                cands.append((dE, 1, s, c, d, nv, dd))
        oUV = [np.outer(Us[s], Vs[s]) for s in range(R)]
        ee2 = E[:, :, e * n + f]
        for s in range(R):
            old = int(W[s, e, f])
            base = oUV[s]
            for nv in VALS:
                if nv == old:
                    continue
                dd = (nv - old) * base
                dE = int(((ee2 + dd) ** 2 - ee2 ** 2).sum())
                cands.append((dE, 2, s, e, f, nv, dd))
        cands.sort(key=lambda t: t[0])
        if rng.random() < 0.12:
            pick = cands[int(rng.integers(len(cands)))]
        else:
            bd = cands[0][0]
            top = [t for t in cands if t[0] == bd]
            pick = top[int(rng.integers(len(top)))]
        dE, X, s, i, j, nv, dd = pick
        if dE <= 0 or rng.random() < np.exp(-dE / max(temp, 1e-9)):
            mats[X][s, i, j] = nv
            if X == 0:
                E[a * n + b] += dd
            elif X == 1:
                E[:, c * n + d, :] += dd
            else:
                E[:, :, e * n + f] += dd
            energy += dE
            if energy == 0:
                E = error_tensor(U, V, W, M)
                if int((E * E).sum()) == 0:
                    return True
                energy = int((E * E).sum())
            since_best = 0 if dE < 0 else since_best + 1
            if since_best > 25000:  # kick and continue
                for _ in range(20):
                    mm = mats[int(rng.integers(3))]
                    mm[int(rng.integers(R)), int(rng.integers(n)),
                       int(rng.integers(n))] = int(rng.integers(-1, 2))
                E = error_tensor(U, V, W, M)
                energy = int((E * E).sum())
                since_best = 0


def reduce_n3(args, rng, deadline):
    """Start from the exact rank-26 block construction; try rank-reduction."""
    n = 3
    M = target_tensor(n)
    factors = block26_factors()
    U, V, W = factors_to_arrays(factors, n)
    save_verified(args.out, args.target, arrays_to_factors(U, V, W), "block26")
    best = U.shape[0]
    # prefer deleting sparse (singleton) triples: single-violation starts
    while time.time() < deadline - 5:
        R = U.shape[0]
        nnz = (np.abs(U).sum(axis=(1, 2)) + np.abs(V).sum(axis=(1, 2))
               + np.abs(W).sum(axis=(1, 2)))
        order = np.argsort(nnz, kind="stable")
        order = order[rng.permutation(len(order))]
        progressed = False
        for s in order:
            if time.time() > deadline - 5:
                break
            U2 = np.delete(U, int(s), axis=0).copy()
            V2 = np.delete(V, int(s), axis=0).copy()
            W2 = np.delete(W, int(s), axis=0).copy()
            # sprinkle a little support to seed the focused search
            mats = [U2, V2, W2]
            R2 = U2.shape[0]
            for _ in range(30):
                mats[int(rng.integers(3))][int(rng.integers(R2)),
                                           int(rng.integers(n)),
                                           int(rng.integers(n))] = int(rng.integers(-1, 2))
            sl = min(deadline - 2, time.time() + max(10.0,
                     (deadline - 2 - time.time()) / max(len(order), 1)))
            if focused_repair(U2, V2, W2, M, rng, sl):
                fac = arrays_to_factors(U2, V2, W2)
                if save_verified(args.out, args.target, fac,
                                 f"reduction to {len(fac)}"):
                    U, V, W = U2, V2, W2
                    best = len(fac)
                    progressed = True
                    break
        if not progressed:
            print(f"n=3 no reduction below rank {best} found; stopping",
                  flush=True)
            break
    print(f"n=3 final rank {best}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    n = int(args.target)
    t_start = time.time()
    deadline = t_start + max(args.time - 8.0, 1.0)  # safety margin for save
    rng = np.random.default_rng(args.seed)

    if n == 2:
        factors = strassen_factors()
        save_verified(args.out, args.target, factors, "strassen")
    elif n == 4:
        factors = tensor_product_factors(strassen_factors(), strassen_factors())
        save_verified(args.out, args.target, factors, "strassen-recursive")
    elif n == 3:
        reduce_n3(args, rng, deadline)
    else:
        raise SystemExit(f"unsupported target {args.target}")
    print(json.dumps({"target": args.target, "wall_s":
                      round(time.time() - t_start, 1)}), flush=True)


if __name__ == "__main__":
    main()
