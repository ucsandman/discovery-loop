#!/usr/bin/env python3
"""Crossover child (prototype, 2026-09-09): exact constructions + rank-reduction search.

IDEA: [kind: crossover] fuse the champion's exact construction kit (Strassen /
block-26 / Strassen-recursion feasible starts for every target) with the nightly
candidate's WalkSAT-style rank-reduction engine, generalised to all targets
with a {-2..2} second repair phase and a multi-start portfolio.

Parent B (stronger; best-matrix_multiplication/solver.py): exact constructive
baselines -- Strassen rank 7 (n=2), rank-26 block construction (n=3), Strassen
recursion rank 49 (n=4). Guaranteed feasible, zero search.
Parent A (weaker; nightly/candidates/2026-09-09-seed20260909.py): focused
simulated-annealing rank-reduction engine (delete one triple, repair the tensor
identity over {-1,0,1}), applied only to n=3.

What the child adds over both parents:
  * rank-reduction applied to EVERY reducible target -- including n=4 from the
    rank-49 recursive start, which neither parent attempted;
  * a {-2..2} second repair phase per deleted triple (the plugin PROMPT says to
    try {-1,0,1} first, then {-2..2}; Parent A never did the second);
  * a multi-start portfolio: the time budget is split across independent
    trajectories with different RNG streams, best verified rank wins;
  * n=2 is provably optimal at rank 7, so reduction is skipped there and the
    run is a pure acceptance test of the pipeline.

Interface contract: python solver.py --target N --time SECONDS --seed S --out PATH
writes JSON {"target","rank","factors"} with exact integer matrices; stdlib+numpy
only; atomic save on every strict improvement; every save verified by the exact
tensor-identity checker.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from verify import check  # on PYTHONPATH when the loop/nightly driver runs us


# ---------------------------------------------------------------------------
# exact building blocks (from Parent B)
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
    """Exact rank-26 decomposition of 3x3 multiplication (2+1 block split)."""
    E3 = lambda i, j: _E(3, i, j)  # noqa: E731

    def E2e(*terms):
        return _add(3, *terms)

    T = []
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


def construction_for(n):
    """Parent B's feasible start for each target."""
    if n == 2:
        return strassen_factors()
    if n == 3:
        return block26_factors()
    if n == 4:
        s = strassen_factors()
        return tensor_product_factors(s, s)
    raise SystemExit(f"unsupported target {n}")


# ---------------------------------------------------------------------------
# tensor machinery (from Parent A)
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
# rank-reduction engine (from Parent A, generalised + {-2..2} second phase)
# ---------------------------------------------------------------------------

VALS1 = (-1, 0, 1)
VALS2 = (-2, -1, 0, 1, 2)


def focused_repair(U, V, W, M, rng, deadline, vals=VALS1):
    """Repair the tensor identity before deadline.

    WalkSAT-style simulated annealing over the given entry alphabet: each
    iteration samples a violated tensor position and evaluates every
    single-entry move on its three target entries by the exact global energy
    delta (numpy-vectorised), taking the best with occasional noise.
    Returns True iff the exact identity was restored.
    """
    n = U.shape[1]
    R = U.shape[0]
    vmin, vmax = min(vals), max(vals)
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
            for nv in vals:
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
            for nv in vals:
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
            for nv in vals:
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
                       int(rng.integers(n))] = int(rng.integers(vmin, vmax + 1))
                E = error_tensor(U, V, W, M)
                energy = int((E * E).sum())
                since_best = 0


def trajectory(n, M, start_factors, rng, deadline):
    """One delete-and-repair trajectory; returns best factor list found."""
    U, V, W = factors_to_arrays(start_factors, n)
    best = arrays_to_factors(U, V, W)
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
            repaired = False
            for vals in (VALS1, VALS2):  # {-1,0,1} first, then {-2..2}
                U2 = np.delete(U, int(s), axis=0).copy()
                V2 = np.delete(V, int(s), axis=0).copy()
                W2 = np.delete(W, int(s), axis=0).copy()
                mats = [U2, V2, W2]
                R2 = U2.shape[0]
                vmin, vmax = min(vals), max(vals)
                for _ in range(30):
                    mats[int(rng.integers(3))][int(rng.integers(R2)),
                                               int(rng.integers(n)),
                                               int(rng.integers(n))] = int(
                        rng.integers(vmin, vmax + 1))
                sl = min(deadline - 2, time.time() + max(
                    10.0, (deadline - 2 - time.time()) / max(len(order), 1)))
                if focused_repair(U2, V2, W2, M, rng, sl, vals):
                    U, V, W = U2, V2, W2
                    best = arrays_to_factors(U, V, W)
                    repaired = True
                    break
            if repaired:
                progressed = True
                break
        if not progressed:
            break
    return best


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

    if n == 2:
        # acceptance test: 7 is proven optimal, emit Strassen and stop.
        save_verified(args.out, args.target, strassen_factors(), "strassen")
        print(json.dumps({"target": args.target, "rank": 7,
                          "wall_s": round(time.time() - t_start, 1)}), flush=True)
        return

    start = construction_for(n)
    M = target_tensor(n)
    best_fac = start
    best_rank = len(start)
    save_verified(args.out, args.target, best_fac, "construction-start")

    # multi-start portfolio: independent RNG streams, best verified rank wins.
    K = 3
    for k in range(K):
        if time.time() > deadline - 10:
            break
        traj_rng = np.random.default_rng(args.seed * 100003 + 17 * k + 1)
        fac = trajectory(n, M, start, traj_rng, deadline - 5)
        if len(fac) < best_rank:
            res = check(fac, n)  # belt and suspenders; save_verified re-checks
            if res["feasible"]:
                best_fac, best_rank = fac, len(fac)
                save_verified(args.out, args.target, best_fac,
                              f"portfolio-traj{k}-rank{best_rank}")
    print(json.dumps({"target": args.target, "rank": best_rank,
                      "wall_s": round(time.time() - t_start, 1)}), flush=True)


if __name__ == "__main__":
    main()
