# discovery-loop-nightly: matrix-multiplication rank search

Nightly autonomous search for low-rank decompositions of matrix multiplication,
run against the [discovery-loop](https://github.com/ucsandman/discovery-loop) atlas
(matrix-multiplication problem). Every candidate is verified by an exact
integer tensor-identity checker before promotion. Nothing is published without
hand review.

## Champion state (2026-09-09)

| n | rank | status |
|---|------|--------|
| 2 | 7 | optimal (Strassen), calibration |
| 3 | **26** | improved 27 → 26 on 2026-09-09; record is 23 (Laderman 1976) |
| 4 | **49** | improved 64 → 49 on 2026-09-09; one short of the record (48, rational coefficients, Dumas–Pernet–Sedoglavic 2025; 47 in Z₂ via AlphaTensor 2022) |

- n=3 rank 26: exact 2+1 block construction — C11 via Strassen(2×2)=7 triples +
  a12·b21ᵀ=4 triples, C12=6, C21=6, c22=3 = 26 triples on disjoint outputs.
- n=4 rank 49: exact Strassen recursion (tensor product of Strassen with itself).
- Both verified by exact tensor-identity check + 20 random cross-checks vs naive;
  reproducibility confirmed by an independent verification cycle the same day.
- Champions live in `champions/sol/n{2,3,4}.json`; run history in `runs.jsonl`.

## What the last 24 hours built (2026-09-08 → 2026-09-09)

**Rank improvements.** n=3: 27 → 26. n=4: 64 → 49 (Strassen recursion; one short of the 48 record). Both promoted
by the nightly driver (`nightly_matmul.py`) after exact verification.

**Laderman transcription + exact verification** (`laderman.py`). Laderman's 1976
rank-23 decomposition transcribed as 23 explicit [U,V,W] triples over {−1,0,1}
and proven feasible by the exact checker. This gives every subsequent search a
known-feasible starting point with the *right* sparsity.

**K-calibration lesson** (`laderman-2026-09-09.md`). Six of Laderman's 23 triples
need sparsity K=7 (max nonzeros per U/V/W). All prior n=3 SAT/LNS work used
K≤3 — those searches weren't "hard", they were searching a space that contains
no rank-23 solution at all. Durable rule: **calibrate sparsity against known
solutions before searching.**

**Rank-22 LNS program** (`lns_laderman.py`). Remove 1 triple from Laderman-23,
re-optimize a subset of the remaining 22 at K=7 via SAT. Four shots on 2026-09-09:
two random-subset neighborhoods **proven UNSAT** (~630s each — genuine proofs,
not timeouts), two targeted subsets running. Script takes an optional explicit
subset (5th arg, comma-separated).

**W-coverage subset selection** (`laderman-2026-09-09.md`). For a removed triple,
the triples whose W matrices touch the same output cells are the minimal
neighborhood that can absorb it (triple 19 → {6,14}; triple 21 → {14,16,17,18}).
Replaces random subset choice.

**Mixed-K SAT encoder** (`mixedk_sat.py`, `mixedk-2026-09-09.md`). Direct rank
search with per-triple sparsity budgets. Honest result: mixed-K does *not*
shrink the CNF (1.58M clauses either way — adder trees dominate), but it prunes
the search space by **10^108** (tight K=1 budgets force entries to zero).
Self-test passes; first R=22 shot queued.

**Laderman structural deep-dive** (`laderman-structure.md`). Four structural
families; the key inversion: 8 of the 23 triples are **"glue"** (T2, T5, T8, T9,
T13, T15, T17, T18) — sole source of *zero* true monomials, existing purely for
cancellation. Attack implication: remove glue, not sparse triples. Exhaustive
screen: local compression is possible *only* at the 5→4 level (60/33649 5-sets;
0/1771 at 3→2, 0/8855 at 4→3, 0/253 pairs fuse). Three glue-targeted LNS
experiments specified and queued.

**Symmetry breaking** (`satenc2_sym.py`, `symbreak-2026-09-09.md`). Permutation
(26!) + sign (4^26) symmetry breaking for the n=3 SAT encoding at 13k clauses
overhead.

**Adder-tree PB encoding** (`satenc2_adder.py`, `adder-2026-09-09.md`). Replaces
sequential-counter sum constraints with a ripple-carry binary adder tree.

**Rank-22 war plan** (`warplan-rank22.md`). Dormant until a SAT hit. Verification
standard (explicit machine-checkable certificate, exact integer arithmetic —
acceptance is surviving independent scrutiny), first-hour checklist (freeze +
hash before touching anything, triple re-verification, flag to wes with evidence
bundle), ranked outreach contacts, and an honest caveat: rank 22 gives
ω ≤ 2.814, which does *not* beat Strassen's 2.807 — the prize is the 50-year
exact-rank record.

**Pipeline hygiene.** Morning digest pointer fix: the feed job's run pointers now
get rewritten to the real outputs every cycle (cron finalization step), so the
07:00 digest and next night's context never read stale smoke-test pointers.

## Current compute pipeline

`queue_pipeline.sh` (auto): targeted LNS A/B → glue experiments A/B/C (k=4, fast
verdicts) → mixed-K R=22 direct search (90 min). Every landing is reported;
every UNSAT is a durable data point (exact subset, seed, budget recorded so it
is never re-run blindly).

## File index

| File | What it is |
|------|-----------|
| `nightly_matmul.py` | nightly driver: candidate → timed run → exact verify → promote |
| `laderman.py` | Laderman-23 triples + exact verifier + sparsity analysis |
| `lns_laderman.py` | LNS rank-22: remove-1, re-optimize subset at K=7 (explicit subset via 5th arg) |
| `lns_sat.py` | LNS SAT encoding (uniform K) |
| `mixedk_sat.py` | direct rank search, per-triple K budgets (`<R> <k_csv> <timeout> <seed>`) |
| `satenc2.py` / `satenc2_adder.py` / `satenc2_sym.py` | n=3 SAT encodings: baseline, adder-tree, symmetry-breaking |
| `n3_adder.py`, `n3_fresh.py`, `n3_sym_k2.py`, `n3_sym_k3.py` | n=3 direct-search experiments |
| `champions/sol/` | current champions (exact, verified) |
| `candidates/` | staged candidates per date/seed |
| `runs.jsonl` | append-only run log |
| `laderman-2026-09-09.md` | K-calibration, W-coverage, run log |
| `laderman-structure.md` | structural families, glue triples, compression screen, do-not-rerun list |
| `mixedk-2026-09-09.md` | mixed-K design, size table, cost estimates |
| `warplan-rank22.md` | dormant-until-SAT verification + outreach plan |
| `PATTERNS.md` | cross-problem pattern library (block decomposition, tensor recursion, …) |
| `MULTISCALE.md` | multiscale search notes |
| `cycle-2026-09-09.md` | nightly cycle report |

## Run it

Python env: `~/workspace/discovery-loop/.venv/bin/python` (system python lacks
pysat/z3).

```bash
# verify the n=3 champion exactly
python -c "from laderman import laderman; from verify import check; print(check(laderman(), 3))"
# LNS rank-22 shot: remove triple 19 (0-based 18), re-optimize explicit subset, 90 min
python lns_laderman.py 18 6 5400 0 0,2,5,9,10,13
# mixed-K R=22, Laderman-minus-19 budgets, 90 min
python mixedk_sat.py 22 "7,2,7,3,2,7,3,2,2,7,7,3,2,7,2,3,2,2,1,1,1,1" 5400 0
```

## What's next

1. Await pipeline verdicts (targeted LNS, glue A/B/C, mixed-K R=22).
2. If all UNSAT: wider K assignments for mixed-K; remaining surviving 5-sets;
   symmetry-broken direct R=22/23.
3. If SAT: **warplan-rank22.md activates** — freeze, hash, triple-verify, flag to
   wes. No public posts without his explicit go-ahead.
