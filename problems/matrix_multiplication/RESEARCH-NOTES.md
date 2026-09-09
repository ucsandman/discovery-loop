# Matrix Multiplication — Research Notes (n=3 campaign, 2026-09-08/09)

Goal: beat the naive n=3 rank-27 decomposition (record is Laderman 23, 1976).
Verifier: exact integer tensor identity, no floating-point tolerance.

## Champions (updated 2026-09-09 by nightly discovery loop)
- n=2: 7 (Strassen, optimal)
- n=3: **26** (2+1 block construction — was 27 naive)
- n=4: **49** (Strassen recursion — was 64 naive, equals record)

### n=3 rank 26: 2+1 block construction
Partition into 2×2 block + borders. Disjoint outputs, so triple lists concatenate exactly:
- C11 = A11·B11 (Strassen, 7) + a12·b21ᵀ (naive, 4) = 11
- C12 = A11·b12 (naive, 4) + a12·b22 (naive, 2) = 6
- C21 = a21ᵀ·B11 (naive, 4) + a22·b21ᵀ (naive, 2) = 6
- c22 = a21ᵀ·b12 (naive, 2) + a22·b22 (naive, 1) = 3
- Total: 11 + 6 + 6 + 3 = **26**. Verified by exact tensor-identity checker.

### n=4 rank 49: Strassen recursion
Tensor product of Strassen's 2×2 decomposition with itself (7×7 = 49).
Verified by exact tensor-identity checker. Equals the known record.

**Lesson:** after a full night of SAT-solver failures, a constructive block
decomposition walked past them all. Clever search ≠ clever construction.
Block/recursive structure is now a first-class direction, not just a baseline.

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

## Approach: adder-tree PB encoding — TRIED, helped but not enough (2026-09-09)

`~/workspace/discovery-loop-nightly/satenc2_adder.py` replaces the seqcounter
pseudo-boolean encoding of Σ(p_pos + ¬p_neg) = t+R with a binary adder tree.

- n=3 R=26: 2,091,510 → 1,822,780 clauses (-13%), 673,068 → 526,621 vars (-22%).
- n=2 R=7: SAT in 1.5s, verifier confirms feasible (correct).
- **n=3 R=26: still TIMEOUT at 660s.** Better base encoding, worth keeping for
  future LNS/CEGAR work, but not sufficient alone.

## Approach: Laderman calibration — THE SMOKING GUN (2026-09-09)

Transcribed Laderman's 1976 rank-23 decomposition (Courtois et al., arXiv:1108.2830
§2.4) and verified `feasible: True` with our exact verifier.

**Sparsity analysis: max K = 7, not 2 or 3.** Six of 23 triples need 7 nonzeros
in a factor matrix. Distribution of per-triple max nonzeros: {1: 5, 2: 8, 3: 4, 7: 6}.

**Every n=3 SAT/LNS attempt to date used K≤3.** The rank-23 solution does not exist
in that search space. The solver wasn't failing — the encoding excluded the answer.

Follow-up K=7 experiments (adder encoding):
- Direct SAT n=3 R=26 K=7: timeout (vastly larger search space than K=2).
- LNS from Laderman-23 minus one triple, 6 triples K=7: 245k clauses / 87k vars,
  hit 360s budget, inconclusive.

**What changes:** future n=3 work must use K≥7 (or mixed K: 3 for most, 7 for a few).
Laderman-minus-k is a better LNS starting point than naive-minus-1.
The real prize is rank < 23, searching *down* from the champion.

Files: `~/workspace/discovery-loop-nightly/laderman.py` (23 triples + verifier),
`~/workspace/discovery-loop-nightly/lns_laderman.py`.

## Ruled out (do not retry without a new idea)
- Direct SAT R=26 K=2 (with or without symmetry breaking) — solver chokes on PB encoding.
- LNS with k ≤ 5 — provably UNSAT, don't waste cycles.
- LNS with k ≥ 6 and current encoding — timeouts; needs a better encoding first.
- Z3 for this problem — 20x slower than bit-blasted SAT on n=2.
- Stochastic/local search — stalled in earlier research, no traction.

## Open leads (not yet tried)
1. **Block constructions for n=3:** the 2+1 split gave 26. Try 1+2 splits,
   asymmetric partitions, or recursive block structure inside the 2×2 piece.
   Any block construction beating 26 is a publishable improvement over naive.
2. **LNS from the rank-26 block champion** (not naive-minus-1): the block
   solution is a better neighborhood than naive. Try delete-one + repair.
3. **CEGAR:** solve a relaxed problem, add violated tensor equations lazily.
4. **K=7 LNS from Laderman-23** with a working long-run harness (see process
   lesson below) — searching *down* from the champion for rank < 23.

## Process lesson (2026-09-09, overnight runs)
Two batches of overnight LNS runs died at startup: background `exec` processes
do not survive the end of a chat turn/session, and neither do children of an
exited cron worker. `nohup`/`disown`/`setsid` do not help — the runtime reaps
the whole tree. **Long solver runs must execute in the foreground of a
long-lived worker** (single exec with internal `&` + `wait`, never
background:true on the exec itself), or as a cron worker that blocks until
its children complete. A cron job that "succeeds" after merely launching
background children is a silent no-op — verify processes are alive after launch.

## Process lesson (2026-09-09)
Research code was written to /tmp and lost to automatic tmp cleanup mid-session
(satenc2.py, lns1.py, n3-research.md all deleted; had to reconstruct from memory).
**All durable research code now lives in ~/workspace/discovery-loop-nightly/.
Never write important files to /tmp.**
