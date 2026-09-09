# Laderman's rank-23 decomposition: structural deep-dive

Date: 2026-09-09. Source: `laderman.py` (transcribed from Courtois et al.,
arXiv:1108.2830, section 2.4). Triple numbering T1..T23 matches P01..P23.
All claims below are computed from the transcription, not hand-derived.
Speculation is marked **[speculation]**.

## 1. Headline findings

1. **Four structural families.** The 23 triples fall into clean roles
   (table in section 2): 5 sparse monomial correctors (T19-23), 2 global
   distributors (T6, T14: monomial core, W spread over 7 outputs each),
   4 single-output dense triples (T1, T3, T10, T11: dense on one side,
   monomial on the other), and 12 small blocks (2-3 nonzeros per side).
2. **Eight "glue" triples are sole source of ZERO true output monomials:**
   T2, T5, T8, T9, T13, T15, T17, T18. They exist purely for cancellation
   support. This inverts the obvious attack: instead of removing a sparse
   monomial triple (T19/T21, sole-sourced, tight), remove a *glue* triple
   and let the reoptimized set rebalance the junk.
3. **Exact local tightness (proven).** 0 of 253 triple pairs can fuse into a
   single {-1,0,1} triple with all others fixed (exact integer-arithmetic
   rank-1 test, section 5). Exhaustive unfolding-rank screen: 0/1771
   subsets compress 3->2, 0/8855 compress 4->3, 60/33649 compress 5->4.
   Local compression can only hide at the 5->4 level, in 60 specific
   5-sets -- every coherent one contains glue triples.
4. **Three concrete LNS experiments** (section 6): remove one glue triple
   from a surviving 5-set, re-optimize the other four at K=7, with exact
   verified commands.
5. **No exploitable symmetry.** All 69 U/V/W linear forms are distinct up to
   sign; transpose-swap, cyclic, and 180-degree rotation symmetries all fail
   to permute the triple set.
6. **c11 is the only "clean" output**: exactly 3 monomials from exactly
   3 triples, zero cancellation terms. Every other output mixes true
   monomials with junk that cancels globally.

## 2. Role clustering

Per triple: nonzeros in (U, V, W); whether U/V are monomial (single entry);
W output cells with signs.

| # | U | V | W | U mono | V mono | W cells |
|---|---|---|---|--------|--------|---------|
| T1 | 7 | 1 | 1 | n | Y | c12+ |
| T2 | 2 | 2 | 2 | n | n | c21+ c22+ |
| T3 | 1 | 7 | 1 | Y | n | c21+ |
| T4 | 3 | 3 | 3 | n | n | c12- c21+ c22+ |
| T5 | 2 | 2 | 2 | n | n | c12+ c22- |
| T6 | 1 | 1 | 7 | Y | Y | c11- c12- c13- c21+ c22+ c31+ c33+ |
| T7 | 3 | 3 | 3 | n | n | c13- c31+ c33+ |
| T8 | 2 | 2 | 2 | n | n | c31- c33- |
| T9 | 2 | 2 | 2 | n | n | c13+ c33- |
| T10 | 7 | 1 | 1 | n | Y | c13+ |
| T11 | 1 | 7 | 1 | Y | n | c31+ |
| T12 | 3 | 3 | 3 | n | n | c12- c31+ c32+ |
| T13 | 2 | 2 | 2 | n | n | c31+ c32+ |
| T14 | 1 | 1 | 7 | Y | Y | c11+ c12+ c13+ c21+ c23+ c31- c32- |
| T15 | 2 | 2 | 2 | n | n | c12+ c32- |
| T16 | 3 | 3 | 3 | n | n | c13+ c21+ c23+ |
| T17 | 2 | 2 | 2 | n | n | c21+ c23+ |
| T18 | 2 | 2 | 2 | n | n | c13+ c23+ |
| T19 | 1 | 1 | 1 | Y | Y | c11+ |
| T20 | 1 | 1 | 1 | Y | Y | c22+ |
| T21 | 1 | 1 | 1 | Y | Y | c23+ |
| T22 | 1 | 1 | 1 | Y | Y | c32+ |
| T23 | 1 | 1 | 1 | Y | Y | c33+ |

Families:
- **Sparse correctors** (T19-23): `(a_ij)(b_kl)` -> single output cell.
  T19: a12*b21 -> c11. T20: a23*b32 -> c22. T21: a21*b13 -> c23.
  T22: a31*b12 -> c32. T23: a33*b33 -> c33.
- **Global distributors** (T6, T14): monomial x monomial core, W on 7 cells.
  T6 = (a11)(-b11); T14 = (a13)(b31). Together their W-supports cover all
  9 outputs (T6 misses c23,c32; T14 misses c22,c33).
- **Single-output dense** (T1, T3, T10, T11): one side dense (7 nz), other
  side monomial, single W cell. T1: U dense 7 x (-b22) -> c12.
  T3: (a22) x V dense 7 -> c21. T10: U dense 7 x (b23) -> c13.
  T11: (a32) x V dense 7 -> c31.
- **Small blocks** (T2, T4, T5, T7, T8, T9, T12, T13, T15, T16, T17, T18):
  2-3 nonzeros per factor, 2-3 W cells.

## 3. Monomial accounting (all 81 output-monomial equations verified OK)

Notation: `T{k}{coeff}` = triple k contributes coeff * monomial.
True product monomials must total +1; all others must total 0.

### c11 (true: a11*b11, a12*b21, a13*b31) -- the clean output
- a11*b11: T6+1.  a12*b21: T19+1.  a13*b31: T14+1.  (No junk terms at all.)

### c12 (true: a11*b12, a12*b22, a13*b32)
- a11*b11: T4-1 T6+1 | a11*b12: T4+1 | a11*b22: T1-1 T4+1 | a12*b22: T1+1
- a13*b22: T1+1 T12-1 | a13*b31: T12-1 T14+1 | a13*b32: T12+1
- a21*b11: T4-1 T5+1 | a21*b12: T4+1 T5-1 | a21*b22: T1-1 T4+1
- a22*b11: T4+1 T5-1 | a22*b12: T4-1 T5+1 | a22*b22: T1+1 T4-1
- a32*b22: T1+1 T12-1 | a32*b31: T12-1 T15+1 | a32*b32: T12+1 T15-1
- a33*b22: T1+1 T12-1 | a33*b31: T12-1 T15+1 | a33*b32: T12+1 T15-1

### c13 (true: a11*b13, a12*b23, a13*b33)
- a11*b11: T6+1 T7-1 | a11*b13: T7+1 | a11*b23: T7-1 T10+1 | a12*b23: T10+1
- a13*b23: T10-1 T16+1 | a13*b31: T14+1 T16-1 | a13*b33: T16+1
- a22*b23: T10-1 T16+1 | a22*b31: T16-1 T18+1 | a22*b33: T16+1 T18-1
- a23*b23: T10+1 T16-1 | a23*b31: T16+1 T18-1 | a23*b33: T16-1 T18+1
- a31*b11: T7-1 T9+1 | a31*b13: T7+1 T9-1 | a31*b23: T7-1 T10+1
- a32*b11: T7-1 T9+1 | a32*b13: T7+1 T9-1 | a32*b23: T7-1 T10+1

### c21 (true: a21*b11, a22*b21, a23*b31)
- a11*b11: T4+1 T6-1 | a11*b12: T2+1 T4-1 | a11*b22: T2+1 T4-1
- a13*b23: T16+1 T17-1 | a13*b31: T14+1 T16-1 | a13*b33: T16+1 T17-1
- a21*b11: T4+1 | a21*b12: T2+1 T4-1 | a21*b22: T2+1 T4-1
- a22*b11: T3+1 T4-1 | a22*b12: T3-1 T4+1 | a22*b21: T3+1
- a22*b22: T3-1 T4+1 | a22*b23: T3-1 T16+1 | a22*b31: T3+1 T16-1
- a22*b33: T3-1 T16+1 | a23*b23: T16-1 T17+1 | a23*b31: T16+1
- a23*b33: T16-1 T17+1

### c22 (true: a21*b12, a22*b22, a23*b32)
- a11*b11: T4+1 T6-1 | a11*b12: T2+1 T4-1 | a11*b22: T2+1 T4-1
- a21*b11: T4+1 T5-1 | a21*b12: T2+1 T4-1 T5+1 | a21*b22: T2+1 T4-1
- a22*b11: T4-1 T5+1 | a22*b12: T4+1 T5-1 | a22*b22: T4+1 | a23*b32: T20+1

### c23 (true: a21*b13, a22*b23, a23*b33)
- a13*b23: T16+1 T17-1 | a13*b31: T14+1 T16-1 | a13*b33: T16+1 T17-1
- a21*b13: T21+1 | a22*b23: T16+1 | a22*b31: T16-1 T18+1
- a22*b33: T16+1 T18-1 | a23*b23: T16-1 T17+1 | a23*b31: T16+1 T18-1
- a23*b33: T16-1 T17+1 T18+1

### c31 (true: a31*b11, a32*b21, a33*b31)
- a11*b11: T6-1 T7+1 | a11*b13: T7-1 T8+1 | a11*b23: T7+1 T8-1
- a13*b22: T12+1 T13-1 | a13*b31: T12+1 T14-1 | a13*b32: T12-1 T13+1
- a31*b11: T7+1 | a31*b13: T7-1 T8+1 | a31*b23: T7+1 T8-1
- a32*b11: T7+1 T11-1 | a32*b13: T7-1 T11+1 | a32*b21: T11+1
- a32*b22: T11-1 T12+1 | a32*b23: T7+1 T11-1 | a32*b31: T11-1 T12+1
- a32*b32: T11+1 T12-1 | a33*b22: T12+1 T13-1 | a33*b31: T12+1
- a33*b32: T12-1 T13+1

### c32 (true: a31*b12, a32*b22, a33*b32)
- a13*b22: T12+1 T13-1 | a13*b31: T12+1 T14-1 | a13*b32: T12-1 T13+1
- a31*b12: T22+1 | a32*b22: T12+1 | a32*b31: T12+1 T15-1
- a32*b32: T12-1 T15+1 | a33*b22: T12+1 T13-1 | a33*b31: T12+1 T15-1
- a33*b32: T12-1 T13+1 T15+1

### c33 (true: a31*b13, a32*b23, a33*b33)
- a11*b11: T6-1 T7+1 | a11*b13: T7-1 T8+1 | a11*b23: T7+1 T8-1
- a31*b11: T7+1 T9-1 | a31*b13: T7-1 T8+1 T9+1 | a31*b23: T7+1 T8-1
- a32*b11: T7+1 T9-1 | a32*b13: T7-1 T9+1 | a32*b23: T7+1 | a33*b33: T23+1

## 4. Sole-source analysis: workhorses vs glue

Of the 27 true product monomials, 23 have a SOLE source triple; 4 are
shared (c22/a21b12, c23/a23b33, c32/a33b32, c33/a31b13).

Sole-source true monomials per triple:
- **3 each (workhorses):** T4 (a11b12@c12, a21b11@c21, a22b22@c22),
  T7 (a11b13@c13, a31b11@c31, a32b23@c33),
  T12 (a13b32@c12, a33b31@c31, a32b22@c32),
  T16 (a13b33@c13, a23b31@c21, a22b23@c23).
- **1 each:** T1, T3, T6, T10, T11, T14, T19, T20, T21, T22, T23.
- **0 each (glue — pure cancellation support):**
  **T2, T5, T8, T9, T13, T15, T17, T18.**

The workhorses each anchor 3 true monomials in 3 different outputs; they
are the structural backbone. The glue triples contribute only junk terms
and shared monomials. Removing a glue triple orphans NO true monomial;
removing a sparse triple (T19-23) orphans exactly one.

## 5. Exact tightness results

**Pair merges: 0/253.** For every pair (i,j), the tensor sum t_i + t_j was
tested for exact rank-1 factorization u(x)v(x)w with u,v,w in {-1,0,1}^9,
using exact integer arithmetic (gauge-fixed fiber derivation + full
reconstruction check; all 23 singles pass as sanity). No pair fuses.
A necessary pre-filter is also exact and cheap: a single triple's tensor
has all entries in {-1,0,1}, so any pair-sum with an entry of magnitude
>= 2 is immediately impossible.

**Cluster compression screen** (can m triples be replaced by m-1 with all
others fixed? tested via mode-unfolding ranks — a *necessary* condition, so
"tight" is definitive and "survives" means "not ruled out"):

| Cluster | size | target | max unfolding rank | verdict |
|---|---|---|---|---|
| {T6,T14,T19} (c11) | 3 | 2 | 3 | tight (impossible) |
| {T19,T20,T21,T22,T23} (sparse) | 5 | 4 | 5 | tight (impossible) |
| {T6,T14} (globals) | 2 | 1 | 2 | tight (impossible) |
| {T1,T3,T10,T11} | 4 | 3 | 4 | tight (impossible) |
| {T16,T17,T18}, {T7,T8,T9}, {T2,T4,T5}, {T12,T13,T15} | 3 | 2 | 3 | tight (impossible) |
| {T2,T4,T5,T20} (c22), {T16,T17,T18,T21} (c23) | 4 | 3 | 4 | tight (impossible) |
| {T6,T7,T8,T9,T23} (c33) | 5 | 4 | 4 | SURVIVES (not ruled out) |

**Systematic screen (exhaustive).** Every subset of size 3, 4, 5 tested:
- size 3 -> 2: **0 of 1771** survive. No 3 triples compress to 2.
- size 4 -> 3: **0 of 8855** survive. No 4 triples compress to 3.
- size 5 -> 4: **60 of 33649** survive.

So local compression (others fixed) can *only* hide at the 5->4 level, in
one of 60 specific 5-sets. The structurally coherent survivors (output
clusters / multi-glue sets) include:
{T6,T7,T8,T9,T23} (c33), {T1,T2,T3,T4,T5} (top-left),
{T3,T14,T16,T17,T18}, {T6,T7,T8,T9,T10}, {T6,T7,T8,T9,T11},
{T1,T11,T12,T13,T14}, {T1,T12,T13,T14,T15}, {T3,T10,T14,T16,T17},
{T3,T10,T16,T17,T18}, {T2,T3,T4,T5,T6}, plus variants...
(full list regenerable; see section 8). Every coherent survivor contains
at least one glue triple; several contain two.

**Symmetries:** no two of the 69 U/V/W forms coincide up to sign;
transpose-swap, cyclic-permutation, and 180-degree-rotation of the triple
set all fail. The decomposition is fully asymmetric — no symmetry to
exploit for a hand construction.

## 6. The lead: glue-triple removal LNS at the 5->4 level (three exact experiments)

**Reasoning.** The systematic screen (section 5) proves local compression
can only hide at the 5->4 level: 0/1771 subsets compress 3->2, 0/8855
compress 4->3, and only 60/33649 compress 5->4. All rank-22 attempts so far
remove a *sparse* triple (T19/T21) whose true monomial is sole-sourced --
and the sparse 5-set is provably tight. The 60 surviving 5-sets are the only
places left; the coherent ones all contain glue triples (T2,T5,T8,T9,T13,
T15,T17,T18), whose removal orphans NO true monomial. So: remove one glue
triple from a surviving 5-set, re-optimize the other four at K=7.

- **Exp A (c33 5->4):** remove T8 (glue), re-optimize T6,T7,T9,T23.
  Command: `lns_laderman.py 7 4 5400 0 5,6,7,21`
- **Exp B (top-left 5->4):** remove T2 (glue), re-optimize T1,T3,T4,T5.
  Command: `lns_laderman.py 1 4 5400 0 0,1,2,3`
- **Exp C (5->4):** remove T17 (glue), re-optimize T3,T14,T16,T18.
  Command: `lns_laderman.py 16 4 5400 0 2,13,15,16`

(Subset indices are into the post-removal filtered triple list; each was
verified by mapping back to the intended original triples. K=7 for the
reoptimized triples. Each is a small LNS; the k=6 runs decided UNSAT in
~10 min, so expect fast verdicts. If SAT: `rank22.json` exists -> run the
exact verifier in `laderman.py` (`check()`) independently before claiming
anything. If UNSAT: that 5-set is tight -- record it.)

Fallbacks if all three are UNSAT: try the other glue triple in the same
5-set (T9 for A, T5 for B, T18 for C); widen the reoptimization set to the
full W-covering set of the removed triple (section 7); or try further
surviving 5-sets from the screen.

**[speculation]** Why glue removal might succeed where sparse removal
failed: regenerating an orphaned true monomial (a12*b21) forces a specific
bilinear term into some triple's core, which then perturbs that triple's
7-cell W footprint and cascades. Rebalancing junk only requires the *sums*
to stay zero, which has many more degrees of freedom. This is unproven;
the experiments decide.

## 7. W-covering sets (for future LNS subset design)

Triples sharing at least one output cell with the given triple:

- T1: 4,5,6,12,14,15 | T2: 3,4,5,6,14,16,17,20 | T3: 2,4,6,14,16,17
- T4: 1,2,3,5,6,12,14,15,16,17,20 | T5: 1,2,4,6,12,14,15,20
- T6: 1,2,3,4,5,7,8,9,10,11,12,13,14,15,16,17,18,19,20,23
- T7: 6,8,9,10,11,12,13,14,16,18,23 | T8: 6,7,9,11,12,13,14,23
- T9: 6,7,8,10,14,16,18,23 | T10: 6,7,9,14,16,18 | T11: 6,7,8,12,13,14
- T12: 1,4,5,6,7,8,11,13,14,15,22 | T13: 6,7,8,11,12,14,15,22
- T14: 1,2,3,4,5,6,7,8,9,10,11,12,13,15,16,17,18,19,21,22
- T15: 1,4,5,6,12,13,14,22 | T16: 2,3,4,6,7,9,10,14,17,18,21
- T17: 2,3,4,6,14,16,18,21 | T18: 6,7,9,10,14,16,17,21
- T19: 6,14 | T20: 2,4,5,6 | T21: 14,16,17,18 | T22: 12,13,14,15
- T23: 6,7,8,9

## 8. Notes for the next loop

- The pair-merge impossibility + exhaustive subset screen say Laderman is
  *locally* tight almost everywhere: no 3->2 (0/1771), no 4->3 (0/8855);
  only sixty 5-sets can possibly compress 5->4. Rank 22 needs one of those
  5-sets or genuinely global restructuring.
- Do NOT re-run: pair merges (0/253 proven); any 3->2 or 4->3 local
  compression (exhaustively ruled out); sparse-set {T19-23}->4;
  c11 {T6,T14,T19}->2; c22/c23 4-sets->3.
- The glue-triple 5->4 experiments in section 6 are the highest-value
  untried shots. Exps A/B/C are small (k=4) and should verdict quickly.
- Regeneration: the analysis scripts were one-off heredocs; the key
  computations are (a) monomial expansion per (output, triple),
  (b) exact integer rank-1 test via gauge-fixed fibers, (c) unfolding
  ranks via SVD. Re-derive from `laderman.py` if needed.

## 9. Design-principle observations (read-only value)

- The decomposition is a *signed cancellation scheme*: most triples emit
  "junk" monomials that sum to zero globally, while 23 designated true
  monomials survive. c11 is the exception that proves the rule (no junk).
- Complexity lives in exactly one place per triple: either a dense U/V
  linear form with a focused W (T1,T3,T10,T11), or a monomial core with a
  wide W distribution (T6,T14), or small-everywhere blocks. No triple is
  dense in all three factors beyond 3 nonzeros.
- The 2x2-block intuition (our rank-26: C11 = Strassen + corrections) does
  NOT visibly appear in Laderman; it is fully entangled, which is presumably
  where the 26 -> 23 savings come from.
