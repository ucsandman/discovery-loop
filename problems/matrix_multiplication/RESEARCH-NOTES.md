# Matrix Multiplication — Research Notes (n=3 campaign, 2026-09-08/09)

Goal: beat the naive n=3 rank-27 decomposition (record is Laderman 23, 1976).
Verifier: exact integer tensor identity, no floating-point tolerance.

## Champions (unchanged after this campaign)
- n=2: 7 (Strassen, optimal)
- n=3: 27 (naive)
- n=4: 64 (naive)

## Approach: bit-blasted SAT (Cadical103 via python-sat)

Each entry in {-1,0,1} → two booleans (neg, pos), not both true.
Product p = U·V·W in {-1,0,1} → (p_neg, p_pos) via Tseitin.
Sum identity per tensor equation: Σ_r (p_pos[r] + ¬p_neg[r]) = t + R
  (pseudo-boolean, all coefficients 0/1, seqcounter encoding).
Sparsity: CardEnc.atmost(nonzero-lits, K) per factor matrix.

Encoder lives at `~/workspace/discovery-loop-nightly/satenc2.py`
(not in this repo — nightly research tooling, kept out of the plugin).

### n=2 validation
- R=7, K=2: 24,480 clauses / 7,944 vars, **SAT in 0.9s**, verifier confirms feasible.
- ~20x faster than the earlier Z3 attempt (~20s).

### n=3 direct SAT — TRIED, timed out
- R=26, K=2: 2,091,510 clauses / 673,068 vars, builds in ~4-6s.
- **Timeout at 120s, 600s.** Solver cannot finish. This is a timeout, NOT UNSAT.
- Bottleneck: the pseudo-boolean sum encoding (729 equations × 52 literals via seqcounter),
  not clause count per se.

## Approach: LNS (large neighborhood search) from naive-minus-1

Start from 26 triples (naive 27 minus one), re-optimize a random subset of k triples
with K=3 sparsity, freeze the rest. Encoder: `~/workspace/discovery-loop-nightly/lns_sat.py`.

### Results — k ≤ 5 ruled out, k ≥ 6 intractable
| k | Result |
|---|---|
| 4 | **UNSAT in ~2-4s** (multiple seeds) — 4 triples provably insufficient |
| 5 | **UNSAT in ~40s** (two seeds) — 5 triples provably insufficient |
| 6 | **Timeout at 360s** (238k clauses / 86k vars) |
| 7 | **Timeout at 360s** (290k clauses / 102k vars) |

The gap: small enough to solve is provably impossible; large enough to matter chokes the solver.

## Approach: symmetry breaking — TRIED, did not help

`~/workspace/discovery-loop-nightly/satenc2_sym.py` adds two constraint families:
1. **Permutation breaking (26! symmetries):** T_0 ≤ T_1 ≤ ... ≤ T_25 lexicographic over
   each triple flattened to 3n² ternary entries. Prefix-equality auxiliaries, 14 clauses
   per entry per adjacent pair → 9,450 clauses for n=3, R=26.
2. **Sign breaking (4^26 symmetries):** UVW product invariant under pairwise sign flips.
   First-nonzero-entry-positive rules via prefix-all-zero chains → ~3.5k clauses.

Total overhead: 13,037 clauses on 2,091,510 base. Verified sound and active on n=2
(SAT in 1.2s, triples confirmed sorted, sign rules confirmed non-vacuous).

**n=3 R=26 with symmetry breaking: still timeout** (K=2 at ~700s, K=3 at 400s).
Conclusion: symmetries were not the bottleneck. The PB sum encoding is.

## Ruled out (do not retry without a new idea)
- Direct SAT R=26 K=2 (with or without symmetry breaking) — solver chokes on PB encoding.
- LNS with k ≤ 5 — provably UNSAT, don't waste cycles.
- LNS with k ≥ 6 and current encoding — timeouts; needs a better encoding first.
- Z3 for this problem — 20x slower than bit-blasted SAT on n=2.
- Stochastic/local search — stalled in earlier research, no traction.

## Open leads (not yet tried)
1. **Tighter PB encoding:** binary adder tree instead of seqcounter for the
   Σ(p_pos + ¬p_neg) = t+R constraints — could cut ~1M variables from the n=3 CNF.
   Highest-leverage single change.
2. **Structure-aware LNS on the sym-broken encoding:** smaller subproblems may benefit
   more from symmetry pruning than the full R=26.
3. **CEGAR:** solve a relaxed problem, add violated tensor equations lazily.
4. **Smarter starting points for LNS:** naive-minus-1 may be a bad neighborhood;
   try seeding from known structured decompositions.

## Process lesson (2026-09-09)
Research code was written to /tmp and lost to automatic tmp cleanup mid-session
(satenc2.py, lns1.py, n3-research.md all deleted; had to reconstruct from memory).
**All durable research code now lives in ~/workspace/discovery-loop-nightly/.
Never write important files to /tmp.**
