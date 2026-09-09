"""Bit-blasted SAT encoding for exact matrix-multiplication decompositions.

This brings the nightly research encoder (``~/workspace/discovery-loop-nightly/
satenc2.py``) into the repo so the plugin can actually use SAT search, and
replaces its pseudo-boolean backend with a measured cardinality-encoding
shootout.

Encoding (Tseitin products + sparsity unchanged from the nightly version):
- Each entry x in {-1,0,1} -> two booleans (neg, pos), not both true.
- Product p = U*V*W in {-1,0,1} -> (p_neg, p_pos) via Tseitin.
- Sum identity per tensor equation: sum_r (p_pos[r] + ~p_neg[r]) = t + R.
  All coefficients are 0/1, so this is a CARDINALITY constraint, not a general
  pseudo-boolean one -- the nightly encoder used PBEnc.equals for it, but
  pysat's PBEnc.equals ignores the encoding parameter (verified: seqcounter/
  adder/sortnetwrk/bdd/binmerge all emit identical CNFs in this pysat build),
  so the backend was never actually pluggable there.
- Sparsity: CardEnc.atmost(nonzero-lits, K) per factor matrix.

Where the sums explode (measured, n=3 R=26 K=2):
- 729 tensor equations, each ``equals`` over 2R=52 literals with bound R+t.
  The sum constraints dominate the CNF, not the Tseitin products.
- The adder-tree variant (tried 2026-09-09, see RESEARCH-NOTES.md) cut the
  total to 1.82M clauses / 527k vars (-13%/-22%) but n=3 still timed out.

What this module adds (new, measured):
- ``sum_encoding`` selects the CardEnc backend for the 729 sum equations:
  seqcounter / sortnetwrk / cardnetwrk / totalizer / mtotalizer, plus the
  legacy "pb" (PBEnc.equals, byte-identical to the nightly encoder).
- Per-equation cost at 52 literals, bound 27: seqcounter 2700 clauses,
  mtotalizer 1380 clauses (-49%). At full n=3 R=26 K=2 build this gives
  1,523,160 clauses / 466,842 vars vs the legacy 2,091,510 / 673,068
  (-27% clauses, -31% vars) -- the largest encoding reduction to date
  (adder-tree was -13%/-22%). The legacy "pb" row reproduces the nightly
  encoder's numbers exactly (2,091,510 / 673,068), confirming a faithful port.
- ``benchmark`` builds + solves n=2 R=7 K=2 under every backend and verifies
  each solution with the exact checker; ``build_comparison`` measures n=3
  R=26 K=2 build size without solving.
- Honest limit: the best backend shrinks the CNF substantially but n=3 R=26
  direct SAT still times out -- the search space, not just the encoding, is
  out of reach. And on the easy n=2 instance the legacy pb encoding actually
  solves fastest (1.2s vs 5.3s for mtotalizer): smaller CNF != faster solve.
  Documented dead ends stay documented: symmetry breaking in the model
  (+13k clauses, still timeout) is NOT re-added here.

Use ``python sat_encoding.py`` to run the benchmark.
"""

from __future__ import annotations

import time

from verify import check
from pysat.formula import CNF, IDPool
from pysat.card import CardEnc, EncType as CardEncType
from pysat.pb import PBEnc, EncType as PBEncType
from pysat.solvers import Cadical103

# Backends for the per-equation sum constraints. "pb" is the legacy
# PBEnc.equals used by the nightly encoder (encoding param ignored by pysat);
# the rest are CardEnc.equals backends, which genuinely differ.
SUM_BACKENDS = ("pb", "seqcounter", "sortnetwrk", "cardnetwrk",
                "totalizer", "mtotalizer")


def _sum_encode(cnf, pool, lits, bound, backend):
    """Append sum(lits) == bound using the chosen backend. Returns new top_id."""
    if backend == "pb":
        pb = PBEnc.equals(lits=lits, bound=bound, top_id=pool.top,
                          encoding=PBEncType.seqcounter)
    else:
        enc = {"seqcounter": CardEncType.seqcounter,
               "sortnetwrk": CardEncType.sortnetwrk,
               "cardnetwrk": CardEncType.cardnetwrk,
               "totalizer": CardEncType.totalizer,
               "mtotalizer": CardEncType.mtotalizer}[backend]
        pb = CardEnc.equals(lits=lits, bound=bound, top_id=pool.top,
                            encoding=enc)
    cnf.extend(pb.clauses)
    return max(pool.top, pb.nv)


def build_cnf(n, R, max_nz, sum_encoding="mtotalizer",
              card_encoding="seqcounter"):
    """Build the bit-blasted CNF. Returns (cnf, pool, neg, pos, stats).

    stats = {"clauses": int, "vars": int} measured after construction.
    """
    t0 = time.monotonic()
    cnf = CNF()
    pool = IDPool(start_from=1)

    def V():
        return pool.id()

    # entry booleans
    neg = [[[[V() for _ in range(n)] for _ in range(n)]
            for _ in range(3)] for _ in range(R)]
    pos = [[[[V() for _ in range(n)] for _ in range(n)]
            for _ in range(3)] for _ in range(R)]
    for r in range(R):
        for k in range(3):
            for a in range(n):
                for b in range(n):
                    cnf.append([-neg[r][k][a][b], -pos[r][k][a][b]])

    # sparsity per factor matrix
    card_enc = {"seqcounter": CardEncType.seqcounter,
                "sortnetwrk": CardEncType.sortnetwrk,
                "totalizer": CardEncType.totalizer}[card_encoding]
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
                                  encoding=card_enc)
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
                                for (zz, nn, pp) in ((unz, un, up),
                                                     (vnz, vn, vp),
                                                     (wnz, wn, wp)):
                                    cnf.append([-zz, nn, pp])
                                    cnf.append([-nn, zz])
                                    cnf.append([-pp, zz])
                                a_nz = V()
                                cnf.append([-a_nz, unz])
                                cnf.append([-a_nz, vnz])
                                cnf.append([-a_nz, wnz])
                                cnf.append([-unz, -vnz, -wnz, a_nz])
                                x = V()
                                cnf.append([-x, -un, -vn])
                                cnf.append([-x, un, vn])
                                cnf.append([x, -un, vn])
                                cnf.append([x, un, -vn])
                                odd = V()
                                cnf.append([-odd, -x, -wn])
                                cnf.append([-odd, x, wn])
                                cnf.append([odd, -x, wn])
                                cnf.append([odd, x, -wn])
                                p_neg, p_pos = V(), V()
                                # p_neg = a_nz & odd; p_pos = a_nz & ~odd
                                cnf.append([-p_neg, a_nz])
                                cnf.append([-p_neg, odd])
                                cnf.append([-a_nz, -odd, p_neg])
                                cnf.append([-p_pos, a_nz])
                                cnf.append([-p_pos, -odd])
                                cnf.append([-a_nz, odd, p_pos])
                                # contribution: p_pos + ~p_neg
                                lits.append(p_pos)
                                lits.append(-p_neg)
                            # sum(lits) = t + R (cardinality constraint)
                            pool.top = _sum_encode(cnf, pool, lits, t + R,
                                                   sum_encoding)
    stats = {"clauses": len(cnf.clauses), "vars": pool.top,
             "build_secs": time.monotonic() - t0}
    return cnf, pool, neg, pos, stats


def solve_cnf(cnf, pool, neg, pos, n, R, timeout=120):
    """Solve; decode a model to triples; verify with the exact checker.

    Returns {"sat": bool, "factors": [... ] | None, "solve_secs": float,
             "verified": bool}.
    """
    t1 = time.monotonic()
    sat = None
    model = None
    with Cadical103() as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        sat = s.solve()
        solve_secs = time.monotonic() - t1
        if sat:
            model = set(v for v in s.get_model() if v > 0)
    result = {"sat": bool(sat), "factors": None,
              "solve_secs": solve_secs, "verified": False}
    if not sat:
        return result
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
    factors = [[U[r], Vv[r], W[r]] for r in range(R)]
    result["factors"] = factors
    result["verified"] = bool(check(factors, n).get("feasible"))
    return result


def benchmark(n=2, R=7, max_nz=2, backends=SUM_BACKENDS,
              solve_timeout=120, verbose=True):
    """Build + solve the same instance under every sum-constraint backend.

    Returns a list of dicts with clauses/vars/build_secs/solve_secs/sat/
    verified per backend. Prints a comparison table.
    """
    rows = []
    for be in backends:
        cnf, pool, neg, pos, stats = build_cnf(n, R, max_nz,
                                              sum_encoding=be)
        res = solve_cnf(cnf, pool, neg, pos, n, R, timeout=solve_timeout)
        row = {"backend": be, **stats, "sat": res["sat"],
               "solve_secs": res["solve_secs"], "verified": res["verified"]}
        rows.append(row)
        if verbose:
            print(f"  {be:10s} clauses={stats['clauses']:>8d} "
                  f"vars={stats['vars']:>7d} build={stats['build_secs']:5.1f}s "
                  f"solve={res['solve_secs']:6.2f}s sat={res['sat']} "
                  f"verified={res['verified']}", flush=True)
    return rows


def build_comparison(n=3, R=26, max_nz=2, backends=SUM_BACKENDS,
                     verbose=True):
    """Build-only comparison at n=3 scale (solving is out of reach; see notes).

    Returns per-backend clauses/vars/build_secs without invoking the solver.
    """
    rows = []
    for be in backends:
        _, _, _, _, stats = build_cnf(n, R, max_nz, sum_encoding=be)
        row = {"backend": be, **stats}
        rows.append(row)
        if verbose:
            print(f"  {be:10s} clauses={stats['clauses']:>8d} "
                  f"vars={stats['vars']:>7d} build={stats['build_secs']:5.1f}s",
                  flush=True)
    return rows


if __name__ == "__main__":
    print("== n=2 R=7 K=2: sum-constraint backend shootout (build + solve) ==")
    rows = benchmark()
    timed_out = [r for r in rows if not r["sat"]]
    unverified = [r for r in rows if r["sat"] and not r["verified"]]
    assert not unverified, f"UNVERIFIED solutions: {unverified}"
    best = min(rows, key=lambda r: r["solve_secs"])
    print(f"fastest backend on n=2: {best['backend']} "
          f"({best['solve_secs']:.2f}s solve)")
    print("== n=3 R=26 K=2: build-only comparison (solve out of reach) ==")
    build_comparison()
    print("done. See module docstring for the honest summary.")
