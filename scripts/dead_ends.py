#!/usr/bin/env python3
"""Global dead-ends index: failed approaches the loop must not retry.

Per-problem pattern ledgers record what worked. This is the complement: a
single repo-wide list of approaches that were tried and failed, with the
evidence, so neither tonight's worker nor a future problem wastes a night
re-running them. Entries are keyed by approach + tags; `check` ranks them by
keyword overlap against a proposed approach description.

Seeded from problems/matrix_multiplication/RESEARCH-NOTES.md (real timeouts
and failures observed 2026-09-09). Append with `record`; consult with `check`
before writing a new candidate solver.

Usage:
    python3 scripts/dead_ends.py list
    python3 scripts/dead_ends.py check --problem matrix_multiplication \
        --query "SAT encoding for n=3 rank 26"
    python3 scripts/dead_ends.py record --problem matrix_multiplication \
        --approach "LNS with k>=6 on current SAT encoding" \
        --why "timeouts; needs a better encoding first" \
        --evidence problems/matrix_multiplication/RESEARCH-NOTES.md \
        --tags sat,lns,matrix_multiplication
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_INDEX_PATH = os.path.join(_REPO_ROOT, "problems", "_dead_ends.json")

_STOPWORDS = frozenset(
    "a an the and or for with from into onto over under of to in on at by "
    "is are was were be been it its this that these those we you he she they "
    "as not no yes if then than so such via using use used try tried".split()
)


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in _STOPWORDS and len(t) > 2}


def load() -> list:
    try:
        with open(_INDEX_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save(entries: list) -> None:
    tmp = _INDEX_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(tmp, _INDEX_PATH)


def record(problem: str, approach: str, why: str, evidence: str = "",
           tags: str = "") -> dict:
    """Append one dead end. Returns the entry."""
    entries = load()
    entry = {
        "id": f"de-{len(entries) + 1:03d}",
        "date": date.today().isoformat(),
        "problem": problem,
        "approach": approach,
        "why_failed": why,
        "evidence": evidence,
        "tags": sorted({t.strip().lower() for t in tags.split(",") if t.strip()}),
    }
    entries.append(entry)
    save(entries)
    return entry


def check(problem: str, query: str, top: int = 5) -> list:
    """Rank dead ends by overlap with the query. Problem match weighs double."""
    qtok = _tokens(query)
    scored = []
    for e in load():
        etok = _tokens(e["approach"] + " " + e["why_failed"]
                       + " " + " ".join(e.get("tags", [])))
        overlap = len(qtok & etok)
        if not overlap:
            continue
        score = overlap * (2 if e.get("problem") in (problem, "general") else 1)
        scored.append((score, e))
    scored.sort(key=lambda s: -s[0])
    return [e for _, e in scored[:top]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="print all dead ends")

    c = sub.add_parser("check", help="find dead ends resembling a proposed approach")
    c.add_argument("--problem", required=True)
    c.add_argument("--query", required=True)
    c.add_argument("--top", type=int, default=5)

    r = sub.add_parser("record", help="record a new dead end")
    r.add_argument("--problem", required=True)
    r.add_argument("--approach", required=True)
    r.add_argument("--why", required=True)
    r.add_argument("--evidence", default="")
    r.add_argument("--tags", default="")

    a = ap.parse_args(argv)
    if a.cmd == "list":
        entries = load()
        print(f"{len(entries)} dead ends:")
        for e in entries:
            print(f"- [{e['id']}] ({e['problem']}) {e['approach']}")
            print(f"    failed: {e['why_failed']}")
            if e.get("evidence"):
                print(f"    evidence: {e['evidence']}")
        return 0
    if a.cmd == "check":
        hits = check(a.problem, a.query, a.top)
        if not hits:
            print("no known dead ends resemble this approach.")
            return 0
        print(f"{len(hits)} similar dead end(s) -- do not retry without a new idea:")
        for e in hits:
            print(f"- [{e['id']}] ({e['problem']}) {e['approach']}")
            print(f"    failed: {e['why_failed']}")
        return 0
    if a.cmd == "record":
        e = record(a.problem, a.approach, a.why, a.evidence, a.tags)
        print(f"recorded {e['id']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
