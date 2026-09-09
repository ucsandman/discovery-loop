#!/usr/bin/env python3
"""Nightly budget scheduler: split tonight's compute across problems.

Scores each problem by a heuristic proxy for expected information gain and
allocates the night's time budget accordingly, with a floor per problem so no
problem starves. Components (all documented, all heuristic -- this is a
scheduling proxy, not a measured quantity):

  staleness    hours since the last run / 24, capped at 7. A problem untouched
               for days deserves another look.
  velocity     fraction of the last 5 runs with status "success", times 3.
               A productive loop keeps getting fed.
  exploration  +2 when a problem has fewer than 3 recorded runs: new problems
               need calibration before their velocity means anything.

Allocation: every problem gets --floor seconds; the remainder splits
proportionally to score. History comes from runs/*/loop_report.json (nightly
runs) and the runs/.latest_<problem>.json pointers.

Usage:
    python3 scripts/schedule_night.py --budget 7200 \
        --problems matrix_multiplication circle_packing
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_RUNS_DIR = os.path.join(_REPO_ROOT, "runs")


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _history(problem: str) -> list:
    """Recent loop reports for a problem, newest first (best-effort)."""
    reports = []
    for path in glob.glob(os.path.join(_RUNS_DIR, "*", "loop_report.json")):
        try:
            with open(path) as fh:
                rep = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if rep.get("problem") == problem:
            reports.append(rep)
    reports.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
    return reports


def _last_run_at(problem: str, history: list) -> datetime | None:
    pointer = os.path.join(_RUNS_DIR, f".latest_{problem}.json")
    try:
        with open(pointer) as fh:
            at = _parse_time(json.load(fh).get("generated_at"))
            if at:
                return at
    except (OSError, json.JSONDecodeError):
        pass
    for rep in history:
        at = _parse_time(rep.get("generated_at"))
        if at:
            return at
    return None


def score_problem(problem: str) -> dict:
    """Score a problem's expected information gain (heuristic)."""
    history = _history(problem)
    now = datetime.now(timezone.utc)
    last = _last_run_at(problem, history)
    if last is None:
        staleness_h = 72.0
    else:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        staleness_h = max(0.0, (now - last).total_seconds() / 3600)
    staleness = min(staleness_h / 24.0, 7.0)

    recent = history[:5]
    velocity = (sum(1 for r in recent if r.get("status") == "success")
                / max(1, len(recent))) * 3.0 if recent else 0.0

    exploration = 2.0 if len(history) < 3 else 0.0

    total = staleness + velocity + exploration
    return {
        "problem": problem,
        "score": round(total, 2),
        "components": {
            "staleness": round(staleness, 2),
            "velocity": round(velocity, 2),
            "exploration": round(exploration, 2),
        },
        "runs_recorded": len(history),
        "hours_since_last_run": round(staleness_h, 1),
    }


def allocate(budget_s: float, problems: list, floor_s: float = 600.0) -> dict:
    """Split budget_s across problems. Returns the plan dict."""
    scored = [score_problem(p) for p in problems]
    n = len(scored)
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "budget_s": budget_s,
        "floor_s": floor_s,
        "allocations": {},
    }
    if n == 0:
        return plan
    if budget_s <= floor_s * n:
        # Not enough for floors: split evenly, say so honestly.
        each = budget_s / n
        for s in scored:
            plan["allocations"][s["problem"]] = {
                "seconds": round(each),
                "score": s["score"],
                "components": s["components"],
                "note": "budget below floors; split evenly",
            }
        return plan
    remaining = budget_s - floor_s * n
    total_score = sum(s["score"] for s in scored) or 1.0
    for s in scored:
        secs = floor_s + remaining * (s["score"] / total_score)
        plan["allocations"][s["problem"]] = {
            "seconds": int(round(secs)),
            "score": s["score"],
            "components": s["components"],
            "runs_recorded": s["runs_recorded"],
            "hours_since_last_run": s["hours_since_last_run"],
        }
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--budget", type=float, default=7200,
                    help="total seconds for the night (default 7200)")
    ap.add_argument("--problems", nargs="+",
                    default=["matrix_multiplication", "circle_packing"])
    ap.add_argument("--floor", type=float, default=600,
                    help="minimum seconds per problem (default 600)")
    ap.add_argument("--save", default=None,
                    help="write the plan JSON here (default: "
                         "runs/schedule_YYYYMMDD.json)")
    a = ap.parse_args(argv)

    plan = allocate(a.budget, a.problems, a.floor)
    save_path = a.save or os.path.join(
        _RUNS_DIR, f"schedule_{datetime.now(timezone.utc):%Y%m%d}.json")
    try:
        os.makedirs(_RUNS_DIR, exist_ok=True)
        with open(save_path, "w") as fh:
            json.dump(plan, fh, indent=2)
    except OSError as exc:
        print(f"warning: could not save plan: {exc}", file=sys.stderr)

    print(f"Nightly budget: {a.budget:.0f}s across {len(a.problems)} problems")
    for prob, alloc in plan["allocations"].items():
        c = alloc["components"]
        print(f"- {prob}: {alloc['seconds']}s "
              f"(score {alloc['score']}: staleness {c['staleness']}, "
              f"velocity {c['velocity']}, exploration {c['exploration']}; "
              f"{alloc.get('runs_recorded', '?')} runs recorded, "
              f"last run {alloc.get('hours_since_last_run', '?')}h ago)"
              + (f" [{alloc['note']}]" if alloc.get("note") else ""))
    print(f"Plan saved: {save_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
