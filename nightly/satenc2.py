#!/usr/bin/env python3
"""Bit-blasted SAT encoding for exact matrix-multiplication decompositions.

Reconstructed 2026-09-09 after /tmp cleanup lost the original.
Each entry x in {-1,0,1} -> two booleans (neg, pos), not both true.
Product p = U*V*W in {-1,0,1} -> (p_neg, p_pos) via Tseitin.
Sum identity: sum_r (p_pos[r] + ~p_neg[r]) = t + R (pseudo-boolean, all coeffs 0/1).
Sparsity: CardEnc.atmost(nonzero-lits, K) per factor matrix.
"""
import sys, time
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
from verify import check
from pysat.formula import CNF, IDPool
from pysat.card import CardEnc, EncType
from pysat.pb import PBEnc, EncType as PBEncType
from pysat.solvers import Cadical103


def build_cnf(n, R, max_nz):
    cnf = CNF()
    pool = IDPool(start_from=1)

    def V():
        return pool.id()

    # entry booleans
    neg = [[[[V() for _ in range(n)] for _ in range(n)] for _ in range(3)] for _ in range(R)]
    pos = [[[[V() for _ in range(n)] for _ in range(n)] for _ in range(3)] for _ in range(R)]
    for r in range(R):
        for k in range(3):
            for a in range(n):
                for b in range(n):
                    cnf.append([-neg[r][k][a][b], -pos[r][k][a][b]])

    # sparsity per factor matrix
    for r in range(R):
        for k in range(3):
            nz = []
            for a in range(n):
                for b in range(n):
                    v = V()
                    cnf.append([-v, neg[r][k][a][b], pos[r][k][a][b]])
                    cnf.append([-neg[r][k][a][b], v])
                    cnf.append([-pos[r][k][a][b], v])
                    nz.append(v)
            card = CardEnc.atmost(lits=nz, bound=max_nz, top_id=pool.top,
                                  encoding=EncType.seqcounter)
            cnf.extend(card.clauses)
            pool.top = max(pool.top, card.nv)

    # tensor identity: for each (a,b,c,d,e,f), sum_r U*V*W = t
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(n):
                    for e in range(n):
                        for f in range(n):
                            t = 1 if (a == e and b == c and d == f) else 0
                            lits = []
                            for r in range(R):
                                un, up = neg[r][0][a][b], pos[r][0][a][b]
                                vn, vp = neg[r][1][c][d], pos[r][1][c][d]
                                wn, wp = neg[r][2][e][f], pos[r][2][e][f]
                                unz, vnz, wnz = V(), V(), V()
                                for (zz, nn, pp) in ((unz, un, up), (vnz, vn, vp), (wnz, wn, wp)):
                                    cnf.append([-zz, nn, pp])
                                    cnf.append([-nn, zz])
                                    cnf.append([-pp, zz])
                                a_nz = V()
                                cnf.append([-a_nz, unz]); cnf.append([-a_nz, vnz]); cnf.append([-a_nz, wnz])
                                cnf.append([-unz, -vnz, -wnz, a_nz])
                                x = V()
                                cnf.append([-x, -un, -vn]); cnf.append([-x, un, vn])
                                cnf.append([x, -un, vn]); cnf.append([x, un, -vn])
                                odd = V()
                                cnf.append([-odd, -x, -wn]); cnf.append([-odd, x, wn])
                                cnf.append([odd, -x, wn]); cnf.append([odd, x, -wn])
                                p_neg, p_pos = V(), V()
                                # p_neg = a_nz & odd; p_pos = a_nz & ~odd
                                cnf.append([-p_neg, a_nz]); cnf.append([-p_neg, odd])
                                cnf.append([-a_nz, -odd, p_neg])
                                cnf.append([-p_pos, a_nz]); cnf.append([-p_pos, -odd])
                                cnf.append([-a_nz, odd, p_pos])
                                # contribution: p_pos + ~p_neg
                                lits.append(p_pos)
                                lits.append(-p_neg)
                            # PB: sum(lits) = t + R  (each r contributes p_pos + (1-p_neg))
                            # sum over r of (p_pos[r] + ~p_neg[r]) = t + R
                            pb = PBEnc.equals(lits=lits, bound=t + R, top_id=pool.top,
                                              encoding=PBEncType.seqcounter)
                            cnf.extend(pb.clauses)
                            pool.top = max(pool.top, pb.nv)
    return cnf, pool, neg, pos


def solve_sat(n, R, max_nz, timeout=120, seed=0):
    t0 = time.time()
    cnf, pool, neg, pos = build_cnf(n, R, max_nz)
    t_build = time.time() - t0
    print(f"  CNF: {len(cnf.clauses)} clauses, {pool.top} vars, build {t_build:.1f}s", flush=True)
    t1 = time.time()
    with Cadical103() as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        ok = s.solve()
        t_solve = time.time() - t1
        if not ok:
            print(f"  UNSAT ({t_solve:.1f}s)", flush=True)
            return None
        model = set(v for v in s.get_model() if v > 0)
    U = [[[0]*n for _ in range(n)] for _ in range(R)]
    Vv = [[[0]*n for _ in range(n)] for _ in range(R)]
    W = [[[0]*n for _ in range(n)] for _ in range(R)]
    for r in range(R):
        for k, M in enumerate((U, Vv, W)):
            for a in range(n):
                for b in range(n):
                    if neg[r][k][a][b] in model:
                        M[r][a][b] = -1
                    elif pos[r][k][a][b] in model:
                        M[r][a][b] = 1
    print(f"  SAT ({t_solve:.1f}s)", flush=True)
    return [[U[r], Vv[r], W[r]] for r in range(R)]


if __name__ == '__main__':
    t0 = time.time()
    fac = solve_sat(2, 7, 2, timeout=120, seed=0)
    dt = time.time() - t0
    if fac:
        print("feasible:", check(fac, 2)["feasible"], f"total {dt:.1f}s")
    else:
        print("no solution", f"total {dt:.1f}s")
