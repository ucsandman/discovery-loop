# Matrix Multiplication — Next Steps (2026-09-09)

## Where we are
- n=2: 7 (Strassen, optimal — done)
- n=3: 26 (2+1 block construction, found 2026-09-09 by nightly loop)
- n=3 record: 23 (Laderman 1976) — the real target
- n=4: 49 (Strassen recursion, equals record — done)

## Priority 1: Push n=3 below 26 with block constructions
The 2+1 split gave 26. The construction is just "apply Strassen to the 2×2
block, do everything else naively." Variations to try:
- **1+2 split** (1×1 block + 2×2 block): symmetric argument, likely also 26,
  but the repair neighborhoods differ.
- **Asymmetric block sizes** for the border terms: some border products can
  share triples (e.g., a12·b22 and a21ᵀ·b12 overlap in structure).
- **Nested structure:** apply a non-naive decomposition to the 2×2 border
  blocks instead of pure naive.
- **Any block construction beating 26** is a publishable improvement over
  naive and a stepping stone toward 23.

## Priority 2: LNS from the rank-26 champion (not from naive)
The old LNS started from naive-minus-1 (26 triples from a bad 27).
Now start from the actual rank-26 block solution and try delete-one + repair:
- Delete 1 triple → 25 triples → try to re-satisfy with local search.
- The block structure gives natural neighborhoods (repair within one block
  at a time instead of across all 26 triples).
- This is strictly better than every LNS attempt to date.

## Priority 3: K=7 LNS from Laderman-23 (needs working long-run harness)
Searching *down* from the champion for rank < 23. Requirements:
- Mixed-K encoding (K=3 for most triples, K=7 for a few) — full K=7 is too big.
- **Foreground execution only.** Background processes die when the worker
  exits. Use a cron worker that blocks on `wait`, or a single long foreground
  exec. Verify processes are alive 5 minutes after launch.
- Start with Laderman-minus-1 (22 triples + re-optimize 1) before attempting
  larger neighborhoods.

## Priority 4: Keep the nightly loop running
It's working — it found both promotions. Don't break it. The 02:43 EDT cron
is the discovery engine; the research notes are the memory.

## Explicitly NOT next
- Blind SAT at R=26 K=2 (dead — solver chokes on PB encoding).
- LNS with k ≤ 5 from naive (provably UNSAT).
- Z3 (20x slower than bit-blasted SAT).
- Unstructured stochastic search (stalled, no traction).
- Re-running the failed overnight LNS batches without fixing the harness first.

## The big picture
We're 3 away from Laderman (26 → 23). The gap is small enough that a clever
block construction or a successful LNS repair could close it. The SAT-solver
approach hit a wall; constructive mathematics is the way forward.
