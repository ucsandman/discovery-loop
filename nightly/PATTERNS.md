# Cross-Problem Transfer: Shared Pattern Library

## Vision
The discovery-loop atlas has 69 open problems. A technique that works on
one problem should be tried on others. Currently each problem is siloed —
insights don't transfer.

## The Pattern Library

### What is a "pattern"?
A reusable problem-solving technique abstracted from its original domain:
- **Block decomposition:** "split into subproblems, solve each, combine"
  - Used in: matrix multiplication (rank 26 via 2+1 blocks)
  - Applicable to: any problem with natural substructure
- **Tensor product / recursion:** "solve small case, combine via product"
  - Used in: matrix multiplication (Strassen recursion → rank 49)
  - Applicable to: recursive problem structures
- **Direct sum for disjoint outputs:** "partition outputs, solve independently"
  - Used in: matrix multiplication (block26)
  - Applicable to: any problem with independent output components

### Pattern format
```json
{
  "name": "block-decomposition",
  "abstract_description": "Partition the problem into blocks, solve each block with the best available method, combine results for disjoint outputs.",
  "origin_problem": "matrix_multiplication",
  "origin_result": "rank 26 for n=3 via 2+1 block split",
  "applicability": "Problems with natural block/subproblem structure and disjoint outputs",
  "operators": ["block_embed", "direct_sum", "naive_fill"],
  "success_count": 1,
  "failure_count": 0
}
```

### Transfer protocol
1. When a problem finds a successful technique, abstract it into a pattern
2. Store in the shared library (`~/workspace/discovery-loop/nightly/patterns/`)
3. When starting a new problem (or a new cycle on an existing one), the loop
   checks the pattern library for applicable techniques
4. Each application updates success/failure counts (patterns earn trust)

### Current patterns (seeded from matrix multiplication work)
1. **block-decomposition** — split and conquer with disjoint outputs
2. **tensor-recursion** — solve base case, combine via tensor product
3. **composition-search** — search over technique combinations, not raw variables
4. **adversarial-validation** — random attacks + redundancy checks before accepting
5. **sparsity-calibration** — calibrate sparsity/complexity budgets against known
   solutions *before* searching. (Origin: n=3 rank search used K≤3 for weeks;
   Laderman-23 needs K=7 in six triples, so those searches occupied a space
   containing no solution at all. Lesson: a solver "failing" can mean the
   encoding is wrong, not the problem hard. Applicable to: any parameterized
   SAT/CP/optimization search.)
6. **mixed-budgets** — give each variable its own tight budget instead of one
   uniform bound. (Origin: per-triple K budgets didn't shrink the CNF at all
   but pruned the search space 10^108, because tight bounds propagate where
   loose ones don't. Applicable to: any combinatorial search with a uniformity
   assumption.)
7. **glue-analysis** — classify components into workhorses (carry the real
   load) vs glue (exist purely for cancellation/constraint satisfaction);
   attack glue first. (Origin: 8 of Laderman's 23 triples source zero true
   monomials — removing glue orphans nothing. Applicable to: any composite
   construction: proofs, circuits, decompositions.)
8. **feasible-minus-k LNS** — start from a known-feasible solution, remove k
   components, re-optimize the neighborhood with the full solver.
   (Origin: Laderman-minus-1 + 6-triple K=7 re-optimization; two neighborhoods
   proven UNSAT in ~10 min each. Applicable to: any improvement search where a
   feasible baseline exists.)

## Implementation phases
- **Phase 1 (now):** Pattern library as JSON files, manually curated
- **Phase 2:** Loop automatically abstracts successful techniques into patterns
- **Phase 3:** Loop queries pattern library at the start of each cycle
- **Phase 4:** Cross-problem suggestions ("technique X worked on problem A,
  try it on problem B")

## Why this matters for "benefiting humanity"
Individual problems are narrow. But a growing library of *transferable
problem-solving patterns* is a general intelligence asset. Each problem
solved makes the loop smarter for all future problems. This is the
compounding effect that turns a problem-solver into a discovery engine.
