#!/usr/bin/env python3
"""LLM crossover operator for the discovery loop (genetic-algorithm style).

Prototype: FunSearch-style crossover. Two parent solvers go in (worst first,
best second); one child comes out that fuses their strategies. The loop's
existing single-parent "mutation" prompt is unchanged; this is a second
generator the loop can call alongside it.

Usage:
    python crossover.py <worse_parent.py> <better_parent.py> --out <child.py>
                       [--model <model>] [--idea-a "..."] [--idea-b "..."]

The caller owns fitness and parent ordering. The child IDEA line is tagged
[kind: crossover] so history/family tracking sees the operator.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from providers import call_model  # noqa: E402
from research_memory import analyze_candidate  # noqa: E402

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import problem  # noqa: E402


def build_crossover_prompt(worse_src, better_src, idea_worse="", idea_better=""):
    """Two parents, worst-to-best (FunSearch ordering), asking for a fused v3."""
    note_a = f" (its IDEA line was: {idea_worse})" if idea_worse else ""
    note_b = f" (its IDEA line was: {idea_better})" if idea_better else ""
    return f"""{problem.PROMPT}

You are performing CROSSOVER, a genetic-algorithm operator: combine two parent
solvers into ONE child solver that is strictly better than both.

PARENT A (the WEAKER parent){note_a}:
```python
{worse_src}
```

PARENT B (the STRONGER parent){note_b}:
```python
{better_src}
```

CROSSOVER TASK: identify the core algorithmic idea in each parent (the energy
function, the neighbourhood moves, the rank-reduction strategy, symmetry
exploitation, the search schedule, the time budget split). Design one child
solver that fuses the strongest ideas of both parents into a single coherent
program: keep what makes Parent B strong, graft in the mechanism from Parent A
that Parent B lacks, and resolve any conflicts in favour of verified
feasibility. Do NOT merely concatenate code; the child must be one coherent
solver. Obey the INTERFACE CONTRACT above exactly (CLI flags, JSON output,
atomic saves, allowed imports, feasibility of every saved candidate).

OUTPUT FORMAT: first line "IDEA: [kind: crossover] <one sentence naming the
fused ideas>", then exactly one ```python block with the full file. Nothing else."""


def validate_child(code, known_fingerprints=()):
    """Syntax + AST-fingerprint dedupe, reusing the loop's own machinery."""
    return analyze_candidate(code, known_fingerprints)


def crossover(
    worse_path,
    better_path,
    out_path,
    model=None,
    timeout=900,
    max_cost=2.0,
    idea_worse="",
    idea_better="",
    known_fingerprints=(),
):
    """Run one crossover. Returns a dict with idea/code/cost/validation."""
    worse_src = open(worse_path, encoding="utf-8").read()
    better_src = open(better_path, encoding="utf-8").read()
    prompt = build_crossover_prompt(worse_src, better_src, idea_worse, idea_better)
    result = call_model(
        prompt, provider="fable", model=model, timeout=timeout,
        max_cost=max_cost, purpose="crossover",
    )
    if result.get("error"):
        return {"ok": False, "error": result["error"], "cost": result.get("cost") or 0.0}
    code, idea, cost = result["code"], result["idea"], result.get("cost") or 0.0
    if not code:
        return {"ok": False, "error": "model returned no code", "idea": idea, "cost": cost}
    validation = validate_child(code, known_fingerprints)
    if not validation["valid"]:
        return {"ok": False, "error": "syntax: " + validation["syntax_error"],
                "idea": idea, "cost": cost, "validation": validation}
    if validation["duplicate"]:
        return {"ok": False, "error": "child is an AST duplicate of a known candidate",
                "idea": idea, "cost": cost, "validation": validation}
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(code)
    return {"ok": True, "idea": idea, "cost": cost, "out": out_path,
            "fingerprint": validation["fingerprint"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="LLM crossover of two solver programs.")
    ap.add_argument("worse", help="path to the weaker parent solver.py")
    ap.add_argument("better", help="path to the stronger parent solver.py")
    ap.add_argument("--out", required=True, help="where to write the child solver.py")
    ap.add_argument("--model", default=None)
    ap.add_argument("--idea-worse", default="")
    ap.add_argument("--idea-better", default="")
    args = ap.parse_args(argv)
    res = crossover(args.worse, args.better, args.out, model=args.model,
                    idea_worse=args.idea_worse, idea_better=args.idea_better)
    if res["ok"]:
        print(f"[crossover] OK cost=${res['cost']:.2f} IDEA: {res['idea']}")
        print(f"[crossover] child -> {res['out']} fp={res['fingerprint'][:12]}")
        return 0
    print(f"[crossover] FAILED: {res['error']} (idea: {res.get('idea')})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
