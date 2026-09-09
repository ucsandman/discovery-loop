# Multi-Scale Search Architecture

## Problem
Current search operates at the lowest level: individual {-1, 0, 1} matrix
entries. For n=3, R=26, that's 26 × 27 = 702 ternary variables. The SAT
solver chokes. This is like writing a novel by searching over letters.

## Solution: Search at Multiple Scales

### Level 3 (Strategic): Composition choice
Search over: which decompositions to compose, and how?
- Operators: tensor_product, block_embed, direct_sum, naive_fill
- Library: strassen-2x2, naive-2x2, naive-3x3, [future: laderman-23, winograd variants]
- Search space: ~dozens of compositions, not millions of entries
- Example: "block_embed(strassen-2x2, 3, [0,1], [0,1]) + naive_fill" → rank 26

### Level 2 (Tactical): Block structure
Search over: how to partition the matrix into blocks?
- Which indices go in which block?
- Which decomposition for each block?
- How to handle cross-block terms (borders)?
- Search space: partitions of {0,...,n-1} × technique per block

### Level 1 (Operational): Entry-level repair
Search over: individual matrix entries, but ONLY within a small neighborhood.
- Start from a Level 3 composition
- Delete k triples, re-optimize with SAT/LNS
- This is where the current LNS lives — but now it's the LAST resort,
  not the first attempt

### Level 0 (Verification): Exact checking
- Tensor identity verifier (already exists)
- No search here, just ground truth

## Search Strategy
1. **Top-down:** Start at Level 3. Enumerate promising compositions.
   Verify each. Keep the best.
2. **Refine:** Take the best Level 3 result. Try Level 2 variations
   (different partitions, different block techniques).
3. **Repair:** Take the best Level 2 result. Try Level 1 local search
   (delete-1, delete-2 + SAT repair).
4. **Never start at Level 1.** That's what we did all night, and it failed.

## Why This Works
- Level 3 search space is tiny (dozens of options) but captures the big wins
- Level 2 is moderate (hundreds of partitions) and captures structural variations
- Level 1 is huge but now starts from a good solution, so small neighborhoods suffice
- Each level's output is the next level's starting point

## Implementation Plan
1. Composition enumerator: generate all Level 3 compositions up to rank R
   (using composition.py operators)
2. Partition enumerator: generate Level 2 variations of a given composition
3. LNS repair: existing lns_laderman.py, but seeded from Level 2 output
4. Orchestrator: runs 1→2→3 in sequence, passes best result down

## Expected Impact
- n=3: Level 3 alone found rank 26 (already done). Level 2 might find 25 or 24
  via smarter partitions. Level 1 might shave 1-2 more via repair.
- The path to <23 likely requires all three levels working together.
