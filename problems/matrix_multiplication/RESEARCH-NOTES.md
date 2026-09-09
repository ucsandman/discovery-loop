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

## Upgrade: better search (2026-09-09)

### 1. Discrete symmetry canonicalization (`symmetry.py`)
Two naive assumptions FAILED exact verification and were corrected:
- cyclic (U,V,W)->(V,W,U) does NOT preserve this repo's tensor convention
  (failed on Laderman-23: got 0, want 1 at one tensor equation);
- independent S_n^3 index permutations do NOT preserve the identity;
  positions 1 and 3 must share a permutation (S_n x S_n subgroup).
Valid generators: triple permutation, per-triple pairwise sign flips, 6
factor rearrangement/transpose patterns (found by exhaustive enumeration over
S3 x transpose masks, all 6 verified), S_n x S_n index relabeling.
canonical_form() BFSes the exact orbit (Laderman-23 orbit: 1296 keys);
cheap_key() for hot-loop dedup. Proof script: all 9 generator cases preserve
exact feasibility; 20 random symmetries -> identical canonical form; naive-2x2
vs Strassen-2x2 differ; Strassen vs symmetrized copy identical.

### 2. SAT/ILP encoding (`sat_encoding.py`)
The dominant tensor equations are cardinality equalities
sum(p_pos + ~p_neg) = R+t. Installed python-sat's PBEnc.equals IGNORED the
backend argument (identical CNFs for all backends) -- reimplemented with
genuinely selectable CardEnc.equals backends: pb/seqcounter/sortnetwrk/
cardnetwrk/totalizer/mtotalizer. n=2 R=7 K=2: all backends SAT and exact-
verified (legacy pb fastest at 1.2-3.6s despite larger model). n=3 R=26 K=2
build-only: mtotalizer 1,523,160 clauses / 466,842 vars / 3.8s vs legacy
2,091,510 / 673,068 / 12.0s (-27% clauses, -31% vars; beats the earlier
adder-tree -13%/-22%). BUT: n=3 R=26 K=2 mtotalizer still unsolved after
~143s solver time -- smaller CNF is not automatically faster, and n=3 direct
SAT remains out of reach. solve_cnf(timeout=...) has no internal interrupt;
the shell timeout is the real bound (API/doc mismatch to fix).

### 3. Coordinated k=2,3 delete-and-repair LNS (`multimove.py`)
- PROVEN: for the Laderman-23-minus-pair instance, NO single triple with ANY
  integer coefficients can complete the repair. Proof: flatten each triple's
  contribution to 9x81 with row=(a,b) [this groups the flat index as
  row=idx//81, col=idx%81]; a triple is then exactly an outer product
  vec(U)(x)(vec(V)(x)vec(W)) hence rank <= 1 (verified rank 1 on real
  triples). The removed pair sums to rank 2 (exact Bareiss, no floats).
  IMPORTANT: the flattening choice matters -- rows (a,b)x(c,d,e,f) gives the
  rank<=1 bound; the naive equation-index flattening does NOT.
- The k=2 joint neighborhood provably contains a feasible repair absent from
  every single-move neighborhood: the removed pair itself completes the
  repair (residual 0, exact-verified). Existence, not discovery.
- NEGATIVE (stochastic discovery): plain multi-start coordinate descent
  (600 rounds) best residual 7; simulated annealing (6x40k steps) stuck at
  15; iterated local search stuck at 15. Mechanism: the violation-count
  landscape has an all-zero attractor -- from any all-zero triple set, no
  single-entry move changes any contribution (a triple with a zero matrix
  contributes nothing), so improving-moves-only search cannot leave the
  plateau; reaching the true basin needs 3+ coordinated entries before the
  residual changes at all. Documented in multimove._hill_climb docstring.
- Wired into multiscale.level1_repair as Phase C (delete-3 + joint 2-slot
  repair, symmetry-deduped deletion sets); every adoption exact-verified.
- k=3 wiring: delete-3/repair-2 in attempt_joint_k_move; demo covers k=1,2
  joint repair + delete-3 Phase C. No rank<23 decomposition was found by any
  of this -- the machinery is the deliverable, not a new decomposition.

## 2026-09-09 — Laderman calibration, rank-22 LNS campaign, mixed-K encoder

### What worked
1. **K-sparsity calibration against Laderman-23** (`discovery-loop-nightly/laderman.py`,
   `laderman-2026-09-09.md`). Transcribed Laderman's 23 triples over {-1,0,1} and
   exact-verified feasibility. K distribution over triples: {1:5, 2:8, 3:4, 7:6}
   — SIX triples need K=7. All prior n=3 SAT/LNS work used K<=3, i.e. searched
   a space containing no rank-23 solution. Durable lesson: calibrate sparsity
   budgets against known solutions before searching; a "failing" solver can mean
   a wrong encoding, not a hard problem.
2. **Laderman-minus-1 + K=7 LNS is tractable** (`lns_laderman.py`). Removing one
   triple and re-optimizing 6 triples at K=7 yields UNSAT *proofs* in 546–1787s
   (~250k clauses / ~87k vars). First time K=7 search gave verdicts instead of
   timeouts. The neighborhood is small enough to prove empty.
3. **W-coverage subset selection** (`laderman-2026-09-09.md`). For a removed
   triple, the triples whose W matrices touch the same output cells are the
   minimal absorbing neighborhood (T19 -> {6,14}; T21 -> {14,16,17,18}).
   Replaces random subset choice; targeted runs are the ones to trust.
4. **Mixed-K encoder** (`mixedk_sat.py`, `mixedk-2026-09-09.md`). Per-triple K
   budgets. Honest negative on CNF size: mixed-K does NOT shrink the CNF
   (1.58M clauses either way — adder trees dominate). Positive on search space:
   tight K=1 budgets force entries to zero, pruning ~10^108 assignments.
   Benefit is pruning, not encoding size. Self-test passes (Laderman K
   distribution pinned SAT in 3.2s); first R=22 shot queued.
5. **Glue-triple analysis** (`laderman-structure.md`). 8 of 23 triples (T2, T5,
   T8, T9, T13, T15, T17, T18) source ZERO true monomials — pure cancellation
   machinery. Attack implication inverted: remove glue, not sparse triples.
   Exhaustive screen: local compression possible ONLY at 5->4 (60/33649 5-sets;
   0/1771 at 3->2, 0/8855 at 4->3, 0/253 pair fusions). Do-not-rerun list in
   the doc.
6. **Champion improvements**: n=3 27->26 (exact 2+1 block: Strassen-7 +
   a12·b21^T-4, C12=6, C21=6, c22=3 on disjoint outputs), n=4 64->49 (Strassen
   recursion). Both exact-verified + reproducibility cycle.

### What didn't work
1. **4/4 LNS rank-22 shots UNSAT** (dead ends de-008..de-011): random subsets
   {1,4,8,9,18,21} and {2,3,4,9,14} (637s, 627s), targeted {1,3,6,10,11,14}
   (1787s) and {1,3,14,16,17,18} (546s). All proofs, not timeouts. The 6-triple
   K=7 neighborhoods around glue triples T19/T21 are provably tight. Do not
   re-run these exact configurations; next attacks: wider K assignments,
   remaining surviving 5-sets, symmetry-broken direct R=22.
2. **n=4 "record matched" claim was wrong** (corrected 2026-09-09). Record is
   48 (rational coeffs, Dumas–Pernet–Sedoglavic 2025; 47 in Z2 via AlphaTensor
   2022), not 49. Our 49 = Strassen recursion, one short. n=3 record 23
   confirmed standing ("frozen for almost five decades", arXiv 2508.03857).
   Record-breaking targets: rank 22 (n=3), rank <=47 general coeffs (n=4).
3. **Mixed-K CNF-size hope**: mixed budgets do not reduce clause/var counts
   (see above) — the win is purely search-space pruning.

### Open threads
- Glue experiments A/B/C (remove T8/T2/T17, re-opt 4 triples at K=7) and
  mixed-K R=22 direct search (90 min) queued behind the LNS runs.
- War plan (`warplan-rank22.md`): dormant until a SAT hit. Verification bar:
  explicit machine-checkable certificate, exact integer arithmetic. No public
  claims without wes's approval.

### 2026-09-09: mixed-K R=22 verdict LOST (infrastructure, not a result)
- Config: `mixedk_sat.py 22 "7,2,7,3,2,7,3,2,2,7,7,3,2,7,2,3,2,2,1,1,1,1" 5400 0`
  (1,498,048 clauses, 432,793 vars). Ran the full 90-min budget; pipeline
  logged done 09:11:18 EDT.
- No SAT/UNSAT/TIMEOUT verdict was captured: the stdout log stream was
  disrupted by the mid-run consolidation move (discovery-loop-nightly ->
  discovery-loop/nightly). Log file mtime froze at 08:01 EDT with only the
  header lines. Process exited silently ~1 min before its internal timeout.
- This is NOT a dead end and NOT evidence of UNSAT. Do NOT add to
  _dead_ends.json. The configuration is untested; re-run with logs on
  stable absolute paths before drawing any conclusion.
- Lesson: never move files out from under a running process; pin long-run
  outputs to absolute paths first.
