"""Problem-agnostic pattern library for cross-problem transfer.

A pattern is a reusable search/validation trick observed to work on one
problem, recorded so other problems can try it. This module only moves
JSON records around; it contains no problem-specific logic.

Schema per pattern (dict):
    name: unique string id
    description: one or two sentences on what the trick is
    applies_when: list of tags describing problem features the trick needs
    transform_ref: "module.path:function" (or doc path) implementing it
    successes: int, outcomes recorded as successful
    failures: int, outcomes recorded as failed
    notes: list of strings, dated observations

Usage:
    lib = PatternLibrary.load("problems/matrix_multiplication/patterns")
    for p in lib.applicable(["fast-verifier"]):
        print(p["name"], p["transform_ref"])
"""

from __future__ import annotations

import json
import os
from datetime import date


class PatternLibrary:
    """In-memory collection of patterns backed by one JSON file per pattern."""

    def __init__(self, patterns: dict[str, dict] | None = None):
        self._patterns: dict[str, dict] = dict(patterns or {})

    @classmethod
    def load(cls, directory: str) -> "PatternLibrary":
        """Load every ``*.json`` file in *directory* as one pattern each.

        Files that do not contain a dict with a ``name`` key are skipped.
        """
        patterns: dict[str, dict] = {}
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(directory, fname), encoding="utf-8") as fh:
                record = json.load(fh)
            if isinstance(record, dict) and record.get("name"):
                patterns[record["name"]] = _normalize(record)
        return cls(patterns)

    def save(self, directory: str) -> list[str]:
        """Write each pattern to ``<name>.json`` in *directory*.

        Returns the list of file paths written. Files are written with
        indent=2 and a fixed key order so diffs stay readable.
        """
        os.makedirs(directory, exist_ok=True)
        written: list[str] = []
        for name in sorted(self._patterns):
            path = os.path.join(directory, f"{name}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(_ordered(self._patterns[name]), fh, indent=2)
                fh.write("\n")
            written.append(path)
        return written

    def register(
        self,
        name: str,
        description: str,
        applies_when: list[str],
        transform_ref: str,
    ) -> None:
        """Add a new pattern with zero recorded outcomes.

        Raises ValueError if *name* is already registered.
        """
        if name in self._patterns:
            raise ValueError(f"pattern already registered: {name}")
        self._patterns[name] = {
            "name": name,
            "description": description,
            "applies_when": list(applies_when),
            "transform_ref": transform_ref,
            "successes": 0,
            "failures": 0,
            "notes": [],
        }

    def record_outcome(self, name: str, success: bool, note: str = "") -> None:
        """Record one observed outcome for *name*.

        Increments ``successes`` or ``failures``. If *note* is given it is
        appended to ``notes`` with today's date. Raises KeyError for
        unknown names.
        """
        pattern = self._patterns[name]
        pattern["successes" if success else "failures"] += 1
        if note:
            pattern["notes"].append(f"{date.today().isoformat()}: {note}")

    def applicable(self, problem_tags: list[str]) -> list[dict]:
        """Return patterns whose ``applies_when`` tags intersect *problem_tags*.

        Sorted by total recorded outcomes (descending), then name.
        """
        tags = set(problem_tags)
        matches = [
            p for p in self._patterns.values() if tags & set(p["applies_when"])
        ]
        matches.sort(key=lambda p: (-(p["successes"] + p["failures"]), p["name"]))
        return matches

    def stats(self) -> dict:
        """Return summary: pattern count, totals, and per-pattern counts."""
        per_pattern = {
            name: {
                "successes": p["successes"],
                "failures": p["failures"],
                "tags": list(p["applies_when"]),
            }
            for name, p in sorted(self._patterns.items())
        }
        return {
            "patterns": len(self._patterns),
            "total_successes": sum(p["successes"] for p in per_pattern.values()),
            "total_failures": sum(p["failures"] for p in per_pattern.values()),
            "per_pattern": per_pattern,
        }

    def get(self, name: str) -> dict:
        """Return the pattern record for *name* (KeyError if unknown)."""
        return self._patterns[name]

    def names(self) -> list[str]:
        """Return all registered pattern names, sorted."""
        return sorted(self._patterns)


def _normalize(record: dict) -> dict:
    """Fill in missing schema fields with defaults; keep existing values."""
    return {
        "name": record["name"],
        "description": record.get("description", ""),
        "applies_when": list(record.get("applies_when", [])),
        "transform_ref": record.get("transform_ref", ""),
        "successes": int(record.get("successes", 0)),
        "failures": int(record.get("failures", 0)),
        "notes": list(record.get("notes", [])),
    }


def _ordered(pattern: dict) -> dict:
    """Return the pattern with keys in canonical order for stable diffs."""
    return {
        "name": pattern["name"],
        "description": pattern["description"],
        "applies_when": pattern["applies_when"],
        "transform_ref": pattern["transform_ref"],
        "successes": pattern["successes"],
        "failures": pattern["failures"],
        "notes": pattern["notes"],
    }
