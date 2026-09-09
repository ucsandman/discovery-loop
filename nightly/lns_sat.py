#!/usr/bin/env python3
"""LNS-SAT: fix most triples, re-optimize a subset via SAT.

Reconstructed 2026-09-09 after /tmp cleanup lost the original lns1.py.
S0: 26 triples (naive-27 minus one). 1 equation violated.
Pick subset of triples to re-optimize; SAT finds new values for their entries.
"""
import sys, time, random
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
from verify import check
from pysat.formula import CNF, IDPool
from pysat.card import CardEnc, EncType
from pysat.solvers import Cadical103


def naive(n):
    U, V, W = [], [], []
    for p in range(n):
        for q in range(n):
            for r in range(n):
                Eu = [[1 if (a == p and b == q) else 0 for b in range(n)] for a in range(n)]
                Ev = [[1 if (a == q and b == r) else 0 for b in range(n)] for a in range(n)]
                Ew = [[1 if (a == p and b == r) else 0 for b in range(n)] for a in range(n)]
                U.append(Eu); V.append(Ev); W.append(Ew)
    return U, V, W


def lns_sat(n, triples, var_idx, max_nz=3, timeout=300, seed=0):
    """triples: list of (U,V,W) int matrices. var_idx: set of triple indices to re-optimize.
    Returns new triples list or None."""
    from pysat.pb import PBEnc, EncType as PBEncType
    R = len(triples)
    var_idx = set(var_idx)
    fix_idx = [i for i in range(R) if i not in var_idx]
    var_list = sorted(var_idx)

    cnf = CNF()
    pool = IDPool(start_from=1)
    def V():
        return pool.id()

    # booleans for variable triples' entries
    neg = {}
    pos = {}
    for r in var_list:
        for k in range(3):
            for a in range(n):
                for b in range(n):
                    neg[(r,k,a,b)] = V()
                    pos[(r,k,a,b)] = V()
                    cnf.append([-neg[(r,k,a,b)], -pos[(r,k,a,b)]])

    # sparsity for variable triples
    for r in var_list:
        for k in range(3):
            nz = []
            for a in range(n):
                for b in range(n):
                    v = V()
                    cnf.append([-v, neg[(r,k,a,b)], pos[(r,k,a,b)]])
                    cnf.append([-neg[(r,k,a,b)], v])
                    cnf.append([-pos[(r,k,a,b)], v])
                    nz.append(v)
            card = CardEnc.atmost(lits=nz, bound=max_nz, top_id=pool.top,
                                  encoding=EncType.seqcounter)
            cnf.extend(card.clauses)
            pool.top = max(pool.top, card.nv)

    # tensor identity with fixed triples as constants
    def entry(r, k, a, b):
        """Return (is_neg_var, is_pos_var, const_val) for triple r entry."""
        if r in var_idx:
            return (neg[(r,k,a,b)], pos[(r,k,a,b)], None)
        else:
            return (None, None, triples[r][k][a][b])

    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(n):
                    for e in range(n):
                        for f in range(n):
                            t = 1 if (a == e and b == c and d == f) else 0
                            lits = []
                            for r in range(R):
                                # get U,V,W entries
                                parts = []
                                for k, (aa, bb) in enumerate([(a,b),(c,d),(e,f)]):
                                    nn, pp, const = entry(r, k, aa, bb)
                                    parts.append((nn, pp, const))
                                # compute product contribution
                                # if any fixed entry is 0 -> product 0, contributes (0,0)-> p_pos=0,p_neg=0
                                # else use variables/constants
                                fixed_zero = any(p[2] == 0 for p in parts)
                                if fixed_zero:
                                    # p=0: contributes p_pos=0, ~p_neg=1 -> literal False, True
                                    # p_pos[r]=False -> add literal that is False: use a fresh var forced false
                                    fv = V()
                                    cnf.append([-fv])
                                    lits.append(fv)      # p_pos = False
                                    lits.append(-fv)     # ~p_neg: p_neg=False so ~p_neg=True; -fv with fv=False is True
                                    # wait: we need p_pos + ~p_neg where p=0 means p_pos=0,p_neg=0
                                    # so contribution = 0 + 1 = 1. lits: [False, True] sums to 1. 
                                    # fv=False: lits get fv(False) and -fv(True). Sum=1. Correct.
                                else:
                                    # build product from (neg,pos) vars or constants
                                    # un = (U<0), up = (U>0), etc.
                                    def get_np(nn, pp, const):
                                        if const is not None:
                                            # return constant (neg,pos) as formulas: use fixed literals
                                            if const < 0:
                                                t_var = V(); cnf.append([t_var])
                                                f_var = V(); cnf.append([-f_var])
                                                return (t_var, f_var)
                                            elif const > 0:
                                                t_var = V(); cnf.append([t_var])
                                                f_var = V(); cnf.append([-f_var])
                                                return (f_var, t_var)
                                            else:
                                                f1, f2 = V(), V()
                                                cnf.append([-f1]); cnf.append([-f2])
                                                return (f1, f2)
                                        return (nn, pp)
                                    (un, up) = get_np(*parts[0])
                                    (vn, vp) = get_np(*parts[1])
                                    (wn, wp) = get_np(*parts[2])
                                    unz, vnz, wnz = V(), V(), V()
                                    for (zz, mm, qq) in ((unz, un, up), (vnz, vn, vp), (wnz, wn, wp)):
                                        cnf.append([-zz, mm, qq])
                                        cnf.append([-mm, zz])
                                        cnf.append([-qq, zz])
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
                                    cnf.append([-p_neg, a_nz]); cnf.append([-p_neg, odd])
                                    cnf.append([-a_nz, -odd, p_neg])
                                    cnf.append([-p_pos, a_nz]); cnf.append([-p_pos, -odd])
                                    cnf.append([-a_nz, odd, p_pos])
                                    lits.append(p_pos)
                                    lits.append(-p_neg)
                            pb = PBEnc.equals(lits=lits, bound=t + R, top_id=pool.top,
                                              encoding=PBEncType.seqcounter)
                            cnf.extend(pb.clauses)
                            pool.top = max(pool.top, pb.nv)
    print(f"  LNS CNF: {len(cnf.clauses)} clauses, {pool.top} vars ({R} triples, {len(var_list)} variable)", flush=True)
    t0 = time.time()
    with Cadical103() as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        ok = s.solve()
        dt = time.time() - t0
        if not ok:
            print(f"  UNSAT ({dt:.1f}s)", flush=True)
            return None
        model = set(v for v in s.get_model() if v > 0)
    print(f"  SAT ({dt:.1f}s)", flush=True)
    new_triples = []
    for r in range(R):
        if r in var_idx:
            U = [[0]*n for _ in range(n)]; Vv = [[0]*n for _ in range(n)]; W = [[0]*n for _ in range(n)]
            for k, M in enumerate((U, Vv, W)):
                for a in range(n):
                    for b in range(n):
                        if neg[(r,k,a,b)] in model: M[a][b] = -1
                        elif pos[(r,k,a,b)] in model: M[a][b] = 1
            new_triples.append((U, Vv, W))
        else:
            new_triples.append(triples[r])
    return new_triples


if __name__ == '__main__':
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    n = 3
    U, V, W = naive(n)
    triples = [(U[i], V[i], W[i]) for i in range(1, 27)]
    print(f"LNS k={k} budget={budget}s seed={seed}", flush=True)
    random.seed(seed)
    var_idx = random.sample(range(26), k)
    print(f"var_idx={sorted(var_idx)}", flush=True)
    t0 = time.time()
    res = lns_sat(n, triples, var_idx=var_idx, max_nz=3, timeout=budget, seed=seed)
    dt = time.time() - t0
    if res:
        fac = [[r[0], r[1], r[2]] for r in res]
        print(f"RESULT k={k}: feasible={check(fac, n)['feasible']} in {dt:.1f}s", flush=True)
    else:
        print(f"RESULT k={k}: no solution in {dt:.1f}s", flush=True)
