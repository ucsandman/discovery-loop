#!/usr/bin/env python3
"""Bit-blasted SAT encoding for exact matrix-multiplication decompositions,
with symmetry breaking.

Extends satenc2.py (imported, not modified) with:
  1. Permutation symmetry breaking: T_0 <= T_1 <= ... <= T_{R-1} lexicographically,
     each triple flattened to its 3n^2 ternary entries in {-1,0,1}.
     Uses prefix-equality auxiliary variables with full Tseitin reification.
  2. Sign symmetry breaking: each triple (U,V,W) has 4 sign variants
     (U,V,W), (-U,-V,W), (U,-V,-W), (-U,V,-W) with identical UVW products.
     Rule S1: first nonzero entry of W is positive.
     Rule S2: first nonzero entry of flattened (U,V) is positive.
     Both via "prefix-all-zero" (fz) chains.

Ternary entry (neg,pos): -1=(1,0), 0=(0,0), 1=(0,1).
x <= y for ternary (given equal prefix so far) is enforced by two clauses:
    [-eq, neg_x, -neg_y]            # forbids x>=0, y=-1
    [-eq, neg_x, -pos_x, pos_y]     # forbids x=1, y=0
"""
import sys, time
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
import satenc2
from verify import check
from pysat.solvers import Cadical103


def _flat_entries(neg, pos, n, r, ks):
    out = []
    for k in ks:
        for a in range(n):
            for b in range(n):
                out.append((neg[r][k][a][b], pos[r][k][a][b]))
    return out


def add_lex_order(cnf, pool, neg, pos, n, R):
    """T_0 <= T_1 <= ... <= T_{R-1} lexicographic over flattened ternary entries."""
    m = 3 * n * n
    F = [_flat_entries(neg, pos, n, r, (0, 1, 2)) for r in range(R)]
    for r in range(R - 1):
        X, Y = F[r], F[r + 1]
        eq = [pool.id() for _ in range(m + 1)]
        cnf.append([eq[0]])  # empty prefixes are equal
        for j in range(m):
            nx, px = X[j]
            ny, py = Y[j]
            e1 = pool.id()  # e1 <-> (nx <-> ny)
            cnf.append([-e1, -nx, ny])
            cnf.append([-e1, nx, -ny])
            cnf.append([nx, ny, e1])
            cnf.append([-nx, -ny, e1])
            e2 = pool.id()  # e2 <-> (px <-> py)
            cnf.append([-e2, -px, py])
            cnf.append([-e2, px, -py])
            cnf.append([px, py, e2])
            cnf.append([-px, -py, e2])
            # eq[j+1] <-> (eq[j] & e1 & e2)
            cnf.append([-eq[j + 1], eq[j]])
            cnf.append([-eq[j + 1], e1])
            cnf.append([-eq[j + 1], e2])
            cnf.append([-eq[j], -e1, -e2, eq[j + 1]])
            # eq[j] -> (entry_x <= entry_y), ternary order -1 < 0 < 1
            cnf.append([-eq[j], nx, -ny])
            cnf.append([-eq[j], nx, -px, py])


def add_sign_break(cnf, pool, neg, pos, n, R):
    """First-nonzero-positive rules on W and on flattened (U,V)."""
    for r in range(R):
        for ks in ((2,), (0, 1)):
            seq = _flat_entries(neg, pos, n, r, ks)
            fz = [pool.id() for _ in range(len(seq) + 1)]
            cnf.append([fz[0]])
            for j, (ng, ps) in enumerate(seq):
                # fz[j+1] <-> (fz[j] & ~ng & ~ps)
                cnf.append([-fz[j + 1], fz[j]])
                cnf.append([-fz[j + 1], -ng])
                cnf.append([-fz[j + 1], -ps])
                cnf.append([-fz[j], ng, ps, fz[j + 1]])
                # fz[j] -> ~ng : first nonzero entry is positive
                cnf.append([-fz[j], -ng])


def build_cnf_sym(n, R, max_nz, lex=True, sign=True):
    cnf, pool, neg, pos = satenc2.build_cnf(n, R, max_nz)
    n0 = len(cnf.clauses)
    if lex:
        add_lex_order(cnf, pool, neg, pos, n, R)
    if sign:
        add_sign_break(cnf, pool, neg, pos, n, R)
    return cnf, pool, neg, pos, n0


def solve_sat_sym(n, R, max_nz, timeout=600, lex=True, sign=True):
    t0 = time.time()
    cnf, pool, neg, pos, n0 = build_cnf_sym(n, R, max_nz, lex, sign)
    t_build = time.time() - t0
    print(f"  CNF: {len(cnf.clauses)} clauses ({n0} base + {len(cnf.clauses)-n0} sym), "
          f"{pool.top} vars, build {t_build:.1f}s", flush=True)
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
    U = [[[0] * n for _ in range(n)] for _ in range(R)]
    Vv = [[[0] * n for _ in range(n)] for _ in range(R)]
    W = [[[0] * n for _ in range(n)] for _ in range(R)]
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
    fac = solve_sat_sym(2, 7, 2, timeout=120)
    dt = time.time() - t0
    if fac:
        print("feasible:", check(fac, 2)["feasible"], f"total {dt:.1f}s")
    else:
        print("no solution", f"total {dt:.1f}s")
