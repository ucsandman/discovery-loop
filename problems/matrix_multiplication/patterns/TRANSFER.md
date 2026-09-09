# Transferring patterns to another problem

`patterns/library.py` is problem-agnostic: it never imports anything
matrix-specific. Any problem directory can keep its own `patterns/`
folder with the same JSON schema, or share one library across the atlas.

## Schema

Each pattern is one JSON file:

```json
{
  "name": "block-decomposition",
  "description": "Partition into blocks, solve each, combine disjoint outputs.",
  "applies_when": ["block-structure", "disjoint-outputs"],
  "transform_ref": "problems/tsp/my_solver.py:split_into_clusters",
  "successes": 2,
  "failures": 1,
  "notes": ["2026-09-10: helped on 50-city TSP, hurt on dense graphs"]
}
```

Tags in `applies_when` are free-form; a problem queries with the tags
that describe it and gets back matching patterns.

## Example: a future TSP problem borrows from matrix multiplication

```python
from patterns.library import PatternLibrary

lib = PatternLibrary.load("problems/matrix_multiplication/patterns")
for p in lib.applicable(["block-structure", "fast-verifier"]):
    print(p["name"], "->", p["transform_ref"])   # try these tricks first
lib.register("2opt-swap", "Reverse a tour segment if shorter",
             ["tour-structure", "fast-verifier"],
             "problems/tsp/solver.py:two_opt")
lib.record_outcome("2opt-swap", True, "cut 5% off 50-city baseline")
lib.save("problems/tsp/patterns")
```

## Rules of the ledger

- `record_outcome` after every real attempt, win or lose. A pattern with
  10 recorded failures is as valuable as one with 10 wins.
- Never edit counts by hand to look better. The JSON is the evidence.
- `transform_ref` must point at code that exists.
