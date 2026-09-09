#!/usr/bin/env python3
"""Mixed-K SAT encoder for 3x3 matrix-multiplication rank search.

Direct rank search (all R triples variable) with a *per-triple* sparsity
budget: triple r may use at most k_list[r] nonzeros in each of its U/V/W
factor matrices. Same tensor-identity + binary adder-tree encoding as
satenc2_adder.py; only the cardinality bounds vary per triple.

Motivation (laderman-2026-09-09.md): Laderman's rank-23 needs K=7, but only
6 of its 23 triples need it (dist: {1:5, 2:8, 3:4, 7:6}). A mixed-K scheme
keeps Laderman-class solutions in the search space while shrinking the CNF
vs uniform K=7.

Usage:
    mixedk_sat.py <R> <k_csv> <timeout> <seed>
        R       number of triples
        k_csv   comma-separated per-triple K, e.g. "7,7,3,3,3,...,2";
                a single value is broadcast to all R triples
        timeout solve-phase budget in seconds (0 = no limit)
        seed    accepted for interface compatibility; the encoding is
                deterministic and the seed is unused
    mixedk_sat.py selftest
        Runs the known-feasible check: pins Laderman's 23 triples into the
        CNF with Laderman-derived K budgets and expects SAT, plus prints
        the mixed-K vs uniform-K=7 CNF size comparison.

Does NOT modify satenc2_adder.py / lns_sat.py; reuses their adder helpers.
"""
import sys, time, multiprocessing as mp
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
from verify import check
from pysat.formula import CNF, IDPool
from pysat.card import CardEnc, EncType
from satenc2_adder import half_adder, sum_equals_adder  # noqa: F401  (half_adder kept for API parity)


def build_cnf_mixedk(n, R, k_list):
    """Build the direct rank-search CNF with per-triple sparsity budgets.

    k_list[r]: max nonzeros allowed in EACH of triple r's U/V/W matrices.
    Returns (cnf, pool, neg, pos) with the same layout as satenc2_adder.
    """
    assert len(k_list) == R, f"need {R} K values, got {len(k_list)}"
    assert all(0 <= k <= n * n for k in k_list), "K out of range"
    cnf = CNF()
    pool = IDPool(start_from=1)

    def V():
        return pool.id()

    false_var = V()
    cnf.append([-false_var])

    # entry booleans
    neg = [[[[V() for _ in range(n)] for _ in range(n)] for _ in range(3)] for _ in range(R)]
    pos = [[[[V() for _ in range(n)] for _ in range(n)] for _ in range(3)] for _ in range(R)]
    for r in range(R):
        for k in range(3):
            for a in range(n):
                for b in range(n):
                    cnf.append([-neg[r][k][a][b], -pos[r][k][a][b]])

    # per-triple sparsity: each factor matrix of triple r gets at most k_list[r] nonzeros
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
            card = CardEnc.atmost(lits=nz, bound=k_list[r], top_id=pool.top,
                                  encoding=EncType.seqcounter)
            cnf.extend(card.clauses)
            pool.top = max(pool.top, card.nv)

    # tensor identity: for each (a,b,c,d,e,f), sum_r U*V*W = t, via adder tree
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
                                cnf.append([-p_neg, a_nz]); cnf.append([-p_neg, odd])
                                cnf.append([-a_nz, -odd, p_neg])
                                cnf.append([-p_pos, a_nz]); cnf.append([-p_pos, -odd])
                                cnf.append([-a_nz, odd, p_pos])
                                lits.append(p_pos)
                                lits.append(-p_neg)
                            sum_equals_adder(cnf, pool, lits, t + R, false_var)
    return cnf, pool, neg, pos


# ---- timeout-enforced solve (child process; SIGALRM can't interrupt the C solver) ----
_child_clauses = None
_child_neg = None
_child_pos = None
_child_n = 3
_child_R = 0


def _solve_child(q):
    from pysat.solvers import Cadical103
    n, R = _child_n, _child_R
    with Cadical103() as s:
        for cl in _child_clauses:
            s.add_clause(cl)
        ok = s.solve()
        if not ok:
            q.put(('UNSAT', None))
            return
        model = set(v for v in s.get_model() if v > 0)
    neg, pos = _child_neg, _child_pos
    U = [[[0] * n for _ in range(n)] for _ in range(R)]
    Vv = [[[0] * n for _ in range(n)] for _ in range(R)]
    W = [[[0] * n for _ in range(n)] for _ in range(R)]
    for r in range(R):
        for k, M in enumerate((U, Vv, W)):
            for a in range(n):
                for b in range(n):
                    if neg[r][k][a][b] in model:
                        M[a][b] = -1
                    elif pos[r][k][a][b] in model:
                        M[a][b] = 1
    q.put(('SAT', [[U[r], Vv[r], W[r]] for r in range(R)]))


def solve_sat_mixedk(n, R, k_list, timeout=600):
    """Build + solve. Returns decoded triples on SAT, None on UNSAT/timeout."""
    t0 = time.time()
    cnf, pool, neg, pos = build_cnf_mixedk(n, R, k_list)
    t_build = time.time() - t0
    print(f"  mixed-K CNF: {len(cnf.clauses)} clauses, {pool.top} vars, "
          f"build {t_build:.1f}s (K dist {sorted(set(k_list))})", flush=True)

    global _child_clauses, _child_neg, _child_pos, _child_n, _child_R
    _child_clauses, _child_neg, _child_pos, _child_n, _child_R = \
        cnf.clauses, neg, pos, n, R
    ctx = mp.get_context('fork')
    q = ctx.Queue()
    p = ctx.Process(target=_solve_child, args=(q,))
    t1 = time.time()
    p.start()
    p.join(timeout if timeout and timeout > 0 else None)
    t_solve = time.time() - t1
    if p.is_alive():
        p.terminate()
        p.join()
        print(f"  TIMEOUT ({timeout}s, solve {t_solve:.1f}s)", flush=True)
        return None
    if p.exitcode != 0:
        print(f"  child exited with code {p.exitcode} ({t_solve:.1f}s)", flush=True)
        return None
    verdict, triples = q.get()
    if verdict != 'SAT':
        print(f"  UNSAT ({t_solve:.1f}s)", flush=True)
        return None
    print(f"  SAT ({t_solve:.1f}s)", flush=True)
    return triples


def pin_triples(cnf, neg, pos, triples):
    """Add unit clauses fixing every entry to the given triple values."""
    n = len(triples[0][0])
    for r, (U, Vv, W) in enumerate(triples):
        for k, M in enumerate((U, Vv, W)):
            for a in range(n):
                for b in range(n):
                    v = M[a][b]
                    if v < 0:
                        cnf.append([neg[r][k][a][b]])
                    elif v > 0:
                        cnf.append([pos[r][k][a][b]])
                    else:
                        cnf.append([-neg[r][k][a][b]])
                        cnf.append([-pos[r][k][a][b]])


def laderman_klist():
    """Per-triple K = actual max-nz of each Laderman factor matrix (tightest
    budget that still contains the known rank-23 solution)."""
    from laderman import laderman
    fac = laderman()
    kl = []
    for (u, v, w) in fac:
        m = 0
        for M in (u, v, w):
            m = max(m, sum(1 for row in M for x in row if x != 0))
        kl.append(m)
    return fac, kl


def selftest():
    """Known-feasible check: Laderman's 23 triples must satisfy the mixed-K CNF."""
    from pysat.solvers import Cadical103
    fac, kl = laderman_klist()
    from collections import Counter
    print(f"Laderman K distribution: {dict(sorted(Counter(kl).items()))}", flush=True)
    # every triple's actual max-nz fits its budget by construction
    n = 3
    t0 = time.time()
    cnf, pool, neg, pos = build_cnf_mixedk(n, len(fac), kl)
    t_build = time.time() - t0
    print(f"  mixed-K CNF: {len(cnf.clauses)} clauses, {pool.top} vars, build {t_build:.1f}s",
          flush=True)
    pin_triples(cnf, neg, pos, fac)
    print(f"  pinned Laderman entries: {len(cnf.clauses)} clauses total", flush=True)
    t1 = time.time()
    with Cadical103() as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        ok = s.solve()
    dt = time.time() - t1
    print(f"  pinned-CNF verdict: {'SAT' if ok else 'UNSAT'} ({dt:.1f}s)", flush=True)
    feas = check(fac, 3)
    print(f"  exact verifier: {feas}", flush=True)

    # size comparison vs uniform K=7
    t0 = time.time()
    cnf7, pool7, _, _ = build_cnf_mixedk(n, len(fac), [7] * len(fac))
    t7 = time.time() - t0
    print(f"  uniform K=7 CNF: {len(cnf7.clauses)} clauses, {pool7.top} vars, build {t7:.1f}s",
          flush=True)
    print(f"  saving: {len(cnf7.clauses) - len(cnf.clauses)} clauses "
          f"({100.0 * (len(cnf7.clauses) - len(cnf.clauses)) / len(cnf7.clauses):.1f}%), "
          f"{pool7.top - pool.top} vars "
          f"({100.0 * (pool7.top - pool.top) / pool7.top:.1f}%)", flush=True)
    return ok and feas['feasible']


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        t0 = time.time()
        ok = selftest()
        print(f"SELFTEST: {'PASS' if ok else 'FAIL'} in {time.time() - t0:.1f}s", flush=True)
        sys.exit(0 if ok else 1)

    R = int(sys.argv[1]) if len(sys.argv) > 1 else 23
    k_csv = sys.argv[2] if len(sys.argv) > 2 else None
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0  # deterministic; unused

    if k_csv is None:
        # default: Laderman-derived budgets when R == 23, else uniform K=3
        if R == 23:
            _, k_list = laderman_klist()
        else:
            k_list = [3] * R
        print(f"no k_csv given; using {'Laderman-derived' if R == 23 else 'uniform K=3'} budgets",
              flush=True)
    else:
        ks = [int(x) for x in k_csv.split(',')]
        k_list = ks * R if len(ks) == 1 else ks
    assert len(k_list) == R, f"k_csv must give 1 or {R} values, got {len(k_list)}"

    n = 3
    print(f"mixed-K direct search: n={n} R={R} timeout={timeout}s seed={seed}", flush=True)
    print(f"  K per triple: {k_list}", flush=True)
    t0 = time.time()
    fac = solve_sat_mixedk(n, R, k_list, timeout=timeout)
    dt = time.time() - t0
    if fac:
        feas = check(fac, n)['feasible']
        print(f"RESULT R={R}: feasible={feas} in {dt:.1f}s", flush=True)
        if feas:
            import json, datetime
            stamp = datetime.datetime.now().strftime('%Y-%m-%d')
            path = f'/home/hatch/workspace/discovery-loop/nightly/rank{R}-mixedk-{stamp}.json'
            with open(path, 'w') as f:
                json.dump(fac, f)
            print(f"Saved to {path}", flush=True)
    else:
        print(f"RESULT R={R}: no solution (UNSAT or timeout) in {dt:.1f}s", flush=True)
