"""Bounded cross-problem context for generation prompts.

Two repo-local ledgers feed this module, both development-only:

- ``problems/_dead_ends.json``: verified failed approaches recorded through
  ``scripts/dead_ends.py``. Consulted at candidate design so a night does not
  re-run a proven dead end without a changed mechanism.
- ``problems/*/patterns/*.json`` and ``nightly/patterns/*.json``: transferable
  search patterns. Two record schemas exist -- the ``patterns/library.py``
  record (``description``/``applies_when``/``transform_ref``/``successes``) and
  the free-text PATTERNS.md record (``abstract_description``/``applicability``/
  ``success_count``) -- both are normalized to a name, a one-line description,
  an origin problem and an outcome count.

Everything injected here is sanitized like the rest of development memory:
withheld target names and local paths are stripped before reaching a prompt,
and the run evidence records exactly which entries were injected.
"""

from __future__ import annotations

import glob
import json
import os
import re

from research_memory import redact_targets, strip_local_paths

_TOKEN = re.compile(r"[a-z0-9]+")


def _sanitize(text, hidden_targets):
    return strip_local_paths(redact_targets(text, hidden_targets))


def _tokens(text):
    return set(_TOKEN.findall(str(text).lower()))


def load_dead_ends(root):
    """All recorded dead ends, file order (oldest first)."""
    path = os.path.join(root, "problems", "_dead_ends.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict) and entry.get("approach")]


def dead_ends_for(problem, root, hidden_targets=(), limit=15):
    """Newest ``limit`` dead ends for *problem* (plus ``general``), sanitized for a prompt."""
    entries = [
        entry
        for entry in load_dead_ends(root)
        if entry.get("problem") in (problem, "general")
    ][-limit:]
    lines = []
    for entry in entries:
        approach = str(entry.get("approach", ""))[:220]
        why = str(entry.get("why_failed", ""))[:220]
        line = f"- [{entry.get('id', '?')}] {approach} -- failed: {why}"
        tags = [str(tag)[:30] for tag in entry.get("tags", [])][:8]
        if tags:
            line += f" (tags: {', '.join(tags)})"
        lines.append(line)
    return _sanitize("\n".join(lines), hidden_targets), [entry.get("id") for entry in entries]


def _normalize_pattern(record, origin, path):
    name = record.get("name")
    description = record.get("description") or record.get("abstract_description") or ""
    outcomes = int(record.get("successes", 0) or 0) + int(record.get("failures", 0) or 0)
    outcomes += int(record.get("success_count", 0) or 0) + int(record.get("failure_count", 0) or 0)
    tags = set(record.get("applies_when", []) or [])
    if not tags:
        tags = _tokens(
            " ".join(
                str(part)
                for part in (
                    record.get("applicability", ""),
                    " ".join(record.get("operators", []) or []),
                )
            )
        )
    return {
        "name": name,
        "description": str(description)[:220],
        "origin": origin,
        "outcomes": outcomes,
        "tags": tags,
        "ref": record.get("transform_ref") or "",
        "path": path,
    }


def load_patterns(root):
    """Every pattern record under ``problems/*/patterns/`` and top-level ``*/patterns/``."""
    roots = glob.glob(os.path.join(root, "problems", "*", "patterns")) + glob.glob(
        os.path.join(root, "*", "patterns")
    )
    patterns = []
    seen = set()
    for directory in sorted(set(roots)):
        for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
            if os.path.basename(path).startswith("_"):
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    record = json.load(fh)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or not record.get("name") or record["name"] in seen:
                continue
            seen.add(record["name"])
            origin = record.get("origin_problem") or os.path.basename(os.path.dirname(directory))
            patterns.append(_normalize_pattern(record, origin, path))
    return patterns


def patterns_for(problem, plugin, root, hidden_targets=(), limit=10):
    """Patterns ranked for *problem*: tag overlap first, then observed outcomes."""
    wanted = set(getattr(plugin, "PATTERN_TAGS", ()) or ())
    wanted.add(problem)
    scored = []
    for pattern in load_patterns(root):
        overlap = len(wanted & set(pattern["tags"]))
        scored.append((overlap, pattern["outcomes"], pattern["name"], pattern))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    chosen = scored[:limit]
    lines = []
    for overlap, _outcomes, _name, pattern in chosen:
        line = f"- {pattern['name']} (from {pattern['origin']}, {pattern['outcomes']} outcome(s)"
        if overlap:
            line += f", {overlap} matching tag(s)"
        line += f"): {pattern['description']}"
        if pattern["ref"]:
            line += f" [{pattern['ref'][:100]}]"
        lines.append(line)
    return _sanitize("\n".join(lines), hidden_targets), [item[3]["name"] for item in chosen]


def blocks(problem, plugin, root, hidden_targets=(), dead_end_limit=15, pattern_limit=10):
    """The prompt context for one run: rendered text plus the injected ids for evidence."""
    dead_text, dead_ids = dead_ends_for(problem, root, hidden_targets, dead_end_limit)
    pattern_text, pattern_names = patterns_for(problem, plugin, root, hidden_targets, pattern_limit)
    sections = []
    if dead_text:
        sections.append(
            "KNOWN DEAD ENDS (verified failures in this lab; a repeat needs a changed mechanism "
            "and a sentence naming it):\n" + dead_text
        )
    if pattern_text:
        sections.append(
            "TRANSFERABLE PATTERNS (techniques recorded from other problems; adapt only when the "
            "problem structure fits):\n" + pattern_text
        )
    return {
        "text": "\n\n".join(sections),
        "dead_ends": dead_ids,
        "patterns": pattern_names,
    }
