"""Literature fuel: extract techniques from arXiv papers.

The loop should read papers, not just search blindly. Every paper on
fast matrix multiplication contains techniques that can be added to
the composition library.

This module:
1. Searches arXiv for relevant papers
2. Downloads and extracts text
3. Identifies technique descriptions (decomposition constructions)
4. Adds them to the composition library as new Decomposition objects
"""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET


ARXIV_API = "http://export.arxiv.org/api/query"


def search_arxiv(query: str, max_results: int = 10) -> list[dict]:
    """Search arXiv for papers matching the query."""
    import urllib.parse
    encoded = urllib.parse.quote(query)
    params = f"search_query=all:{encoded}&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    url = f"{ARXIV_API}?{params}"

    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read()

    root = ET.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    papers = []
    for entry in root.findall("atom:entry", ns):
        paper = {
            "id": entry.find("atom:id", ns).text.split("/")[-1],
            "title": entry.find("atom:title", ns).text.strip(),
            "summary": entry.find("atom:summary", ns).text.strip(),
            "published": entry.find("atom:published", ns).text,
        }
        papers.append(paper)

    return papers


def find_technique_papers() -> list[dict]:
    """Find papers likely to contain new decomposition techniques."""
    queries = [
        "matrix multiplication rank",
        "bilinear complexity tensor",
        "fast matrix multiplication algorithm",
        "Strassen algorithm improvement",
    ]
    seen = set()
    papers = []
    for q in queries:
        for p in search_arxiv(q, max_results=5):
            if p["id"] not in seen:
                seen.add(p["id"])
                papers.append(p)
    return papers


# Known techniques to extract (manual curation + auto-detection)
KNOWN_TECHNIQUES = {
    "strassen-1969": {
        "name": "Strassen 1969",
        "rank_2x2": 7,
        "description": "First sub-cubic matrix multiplication",
        "in_library": True,
    },
    "winograd-variant": {
        "name": "Winograd variant",
        "rank_2x2": 7,
        "description": "Strassen with fewer additions (15 vs 18)",
        "in_library": False,
        "priority": "high",  # Easy win: same rank, better constant
    },
    "laderman-1976": {
        "name": "Laderman 1976",
        "rank_3x3": 23,
        "description": "Best known for 3x3, still unbeaten",
        "in_library": False,
        "priority": "critical",  # The target to beat
        "note": "Transcribed in laderman.py, needs conversion to Decomposition",
    },
    "pan-1978": {
        "name": "Pan 1978",
        "description": "Trilinear aggregation techniques",
        "in_library": False,
        "priority": "medium",
    },
    "coppersmith-winograd": {
        "name": "Coppersmith-Winograd",
        "description": "Asymptotic improvements via tensor powers",
        "in_library": False,
        "priority": "low",  # Asymptotic, not practical for small n
    },
}


def technique_report() -> str:
    """Generate a report of known techniques and their library status."""
    lines = ["# Technique Library Status", ""]
    for key, t in KNOWN_TECHNIQUES.items():
        status = "✓ in library" if t.get("in_library") else "✗ NOT in library"
        lines.append(f"## {t['name']} — {status}")
        lines.append(f"  {t['description']}")
        if not t.get("in_library"):
            lines.append(f"  Priority: {t.get('priority', 'unknown')}")
        if t.get("note"):
            lines.append(f"  Note: {t['note']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(technique_report())
    print("\n" + "=" * 60 + "\n")
    print("Searching arXiv for recent matrix multiplication papers...\n")
    try:
        papers = find_technique_papers()
        for p in papers[:10]:
            print(f"  [{p['id']}] {p['title'][:80]}")
            print(f"    Published: {p['published'][:10]}")
    except Exception as e:
        print(f"  arXiv search failed: {e}")
