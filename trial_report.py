"""Descriptive comparison of scheduled research modes; never a model ranking claim."""

from collections import defaultdict
from pathlib import Path
import json
import math
import re


def _number(value):
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else 0.0
    )


def summarize(root):
    groups = defaultdict(
        lambda: {
            "runs": 0,
            "completed": 0,
            "confirmed": 0,
            "calls": 0,
            "allowance_charged": 0.0,
            "solver_seconds": 0.0,
            "solver_evaluations": 0,
            "confirmed_gains": [],
        }
    )
    unreadable = 0
    for path in sorted((Path(root) / "runs/research").glob("*/*/evidence.json")):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.parent.name):
            continue  # Exclude manual probes and UI fixtures from the scheduled trial.
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(evidence, dict):
                raise ValueError("Expected evidence object")
        except (OSError, ValueError):
            unreadable += 1
            continue
        provider = evidence.get("provider")
        problem = evidence.get("problem")
        if provider not in ("fable", "astra", "paired") or not isinstance(problem, str):
            unreadable += 1
            continue
        group = groups[(problem, provider)]
        group["runs"] += 1
        group["completed"] += evidence.get("status") == "completed"
        group["confirmed"] += evidence.get("confirmed") is True
        usage = evidence.get("usage") or {}
        group["calls"] += int(_number(usage.get("calls")))
        group["allowance_charged"] += _number(usage.get("charged"))
        group["solver_seconds"] += _number(evidence.get("solver_seconds"))
        group["solver_evaluations"] += int(_number(evidence.get("solver_evaluations")))
        gain = (evidence.get("confirmation") or {}).get("median_gain")
        if evidence.get("confirmed") is True and isinstance(gain, (int, float)) and math.isfinite(gain):
            group["confirmed_gains"].append(gain)
    rows = []
    for (problem, provider), data in sorted(groups.items()):
        charged = data["allowance_charged"]
        hours = data["solver_seconds"] / 3600
        rows.append(
            {
                "problem": problem,
                "provider": provider,
                **data,
                "allowance_charged": round(charged, 4),
                "solver_hours": round(hours, 4),
                "confirmed_per_allowance_unit": data["confirmed"] / charged if charged else None,
                "confirmed_per_solver_hour": data["confirmed"] / hours if hours else None,
            }
        )
    return {
        "rows": rows,
        "runs": sum(row["runs"] for row in rows),
        "unreadable": unreadable,
        "note": "Exploratory comparison at configured limits. Allowance uses API-equivalent estimates or conservative reservations, not subscription billing. Solver hours sum worker elapsed time, not CPU time. Small samples do not establish a model ranking.",
    }


if __name__ == "__main__":
    print(json.dumps(summarize(Path(__file__).resolve().parent), indent=2))
