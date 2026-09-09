"""Literature fuel: search, download, and mine arXiv papers for matrix-multiplication techniques.

What this module actually does:
1. search_arxiv(): query the arXiv API for papers matching a query.
2. download_paper(): download a paper's PDF from export.arxiv.org into a
   local cache dir (~/.cache/discovery-loop/papers). Cached files are
   never re-downloaded and are never committed to the repo.
3. extract_text(): turn a cached PDF into plain text using pdftotext
   (poppler). If pdftotext is missing, falls back to downloading the
   arXiv source tarball and crudely stripping LaTeX; raises a clear
   error if neither path works.
4. extract_rank_claims(): regex-scan extracted text for rank claims
   ("rank 23", "M(3) <= 23", "border rank", ...) and return each with
   its surrounding context. These are raw claims from prose, not
   verified facts — a claim is only trusted after exact verification.
5. Technique registry (techniques.json, committed): a curated list of
   decomposition techniques with schema {name, source_paper, citation,
   claimed_rank, status, notes}. status is "verified" only for entries
   whose decompositions pass this repo's exact tensor-identity checker
   (verify.check). Everything else is "unverified". register_technique()
   adds entries, list_techniques() reads them, technique_report()
   renders them.

What this module does NOT do: it does not convert papers into
Decomposition objects, and it does not promote a paper's rank claim
to a verified result. Verification happens elsewhere (verify.check).

Portability: PDFs are never committed (copyright + bloat). Any machine
can populate its own cache with:
    python literature.py fetch --all
This reads arxiv_id from each registry entry that has one and downloads
the PDFs into the local cache dir, skipping ones already cached.
Downloaded/extracted material stays in the cache dir and is never
committed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_PDF = "https://export.arxiv.org/pdf"
ARXIV_EPRINT = "https://export.arxiv.org/e-print"

DEFAULT_CACHE_DIR = os.path.expanduser("~/.cache/discovery-loop/papers")
REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "techniques.json")

VERIFIED = "verified"
UNVERIFIED = "unverified"


def search_arxiv(query: str, max_results: int = 10) -> list[dict]:
    """Search arXiv for papers matching the query."""
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


def _safe_arxiv_id(arxiv_id: str) -> str:
    """Sanitize an arXiv id for use as a cache filename."""
    cleaned = arxiv_id.strip().split("/")[-1]
    if not re.fullmatch(r"[0-9a-zA-Z.\-]+v?\d*", cleaned) or not cleaned:
        raise ValueError(f"not a plausible arXiv id: {arxiv_id!r}")
    return cleaned.replace("/", "_")


def download_paper(arxiv_id: str, cache_dir: str | None = None) -> str:
    """Download a paper's PDF into the cache dir; skip if already cached.

    Returns the path to the cached PDF. Downloaded content is kept in
    the cache dir only — never written into the repo.
    """
    cache = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache, exist_ok=True)
    safe = _safe_arxiv_id(arxiv_id)
    pdf_path = os.path.join(cache, safe + ".pdf")
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        return pdf_path
    url = f"{ARXIV_PDF}/{safe}.pdf"
    req = urllib.request.Request(url, headers={"User-Agent": "discovery-loop-literature/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(pdf_path, "wb") as f:
        shutil.copyfileobj(resp, f)
    return pdf_path


def _pdftotext_available() -> bool:
    return shutil.which("pdftotext") is not None


def extract_text(pdf_path: str, arxiv_id: str | None = None,
                 cache_dir: str | None = None) -> str:
    """Extract plain text from a cached PDF.

    Primary path: pdftotext (poppler). Fallback: download the arXiv
    source tarball for arxiv_id and crudely strip LaTeX from its .tex
    files. Raises RuntimeError if neither path works.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"no such PDF: {pdf_path}")

    if _pdftotext_available():
        txt_path = os.path.splitext(pdf_path)[0] + ".txt"
        proc = subprocess.run(
            ["pdftotext", "-layout", pdf_path, txt_path],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pdftotext failed on {pdf_path}: {proc.stderr.strip()}")
        with open(txt_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    # Fallback: arXiv source tarball -> strip LaTeX from .tex files.
    if arxiv_id is None:
        raise RuntimeError(
            "pdftotext is not installed and no arxiv_id was given, so the "
            "source-tarball fallback cannot run. Install poppler-utils."
        )
    cache = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache, exist_ok=True)
    safe = _safe_arxiv_id(arxiv_id)
    tar_path = os.path.join(cache, safe + "-source.tar.gz")
    if not (os.path.exists(tar_path) and os.path.getsize(tar_path) > 0):
        url = f"{ARXIV_EPRINT}/{safe}"
        req = urllib.request.Request(url, headers={"User-Agent": "discovery-loop-literature/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tar_path, "wb") as f:
            shutil.copyfileobj(resp, f)
    extract_dir = os.path.join(cache, safe + "-source")
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with tarfile.open(tar_path, "r:*") as tar:
            tar.extractall(extract_dir, filter="data")
    except Exception as e:
        raise RuntimeError(f"could not unpack source tarball for {safe}: {e}")
    chunks = []
    for root, _dirs, files in os.walk(extract_dir):
        for name in sorted(files):
            if name.endswith(".tex"):
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as f:
                    chunks.append(f.read())
    if not chunks:
        raise RuntimeError(f"source tarball for {safe} contained no .tex files")
    text = "\n".join(chunks)
    # Crude LaTeX stripping: drop comments, commands, and math delimiters.
    text = re.sub(r"(?m)^%.*$", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[\\{}$_^&~]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


_RANK_PATTERNS = [
    # M(3) <= 23, M_3 \le 23
    re.compile(r"M\s*[_\s]*\(?\s*(\d+)\s*\)?\s*(?:<=|≤|<)\s*(\d+)"),
    # rank 23, rank of M(3) is 23
    re.compile(r"\brank\b(?:\s+of\s+M\s*\(?\s*\d+\s*\)?)?\s*(?:is\s+|of\s+|at\s+most\s+|≤\s*|=\s*)?(\d+)", re.IGNORECASE),
    # border rank ... 23
    re.compile(r"\bborder\s+rank\b[^.\n]{0,80}?(\d+)", re.IGNORECASE),
    # tensor rank ... 23
    re.compile(r"\btensor\s+rank\b[^.\n]{0,80}?(\d+)", re.IGNORECASE),
    # only 23 multiplications
    re.compile(r"\bonly\s+(\d+)\s+multiplications\b", re.IGNORECASE),
    # using 23 multiplications
    re.compile(r"\busing\s+(?:only\s+)?(\d+)\s+multiplications\b", re.IGNORECASE),
]


def extract_rank_claims(text: str, context_chars: int = 160) -> list[dict]:
    """Find rank claims in text; return [{claim_text, context_snippet}].

    These are raw claims from prose, NOT verified facts. A claim only
    becomes trusted after the decomposition passes verify.check.
    """
    claims = []
    seen_spans = set()
    for pat in _RANK_PATTERNS:
        for m in pat.finditer(text):
            span = (m.start(), m.end())
            if any(s <= span[0] < e or s < span[1] <= e for s, e in seen_spans):
                continue
            seen_spans.add(span)
            lo = max(0, m.start() - context_chars)
            hi = min(len(text), m.end() + context_chars)
            snippet = " ".join(text[lo:hi].split())
            claims.append({
                "claim_text": " ".join(m.group(0).split()),
                "context_snippet": snippet,
            })
    claims.sort(key=lambda c: len(c["claim_text"]))
    return claims


def _load_registry() -> dict:
    if not os.path.exists(REGISTRY_PATH):
        return {"techniques": []}
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if "techniques" not in data or not isinstance(data["techniques"], list):
        raise ValueError(f"malformed registry at {REGISTRY_PATH}")
    return data


def _save_registry(data: dict) -> None:
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def list_techniques() -> list[dict]:
    """Return all registry entries."""
    return _load_registry()["techniques"]


def register_technique(name: str, source_paper: str, citation: str,
                       claimed_rank: dict, status: str = UNVERIFIED,
                       notes: str = "") -> dict:
    """Add or update a technique entry in the registry.

    claimed_rank is a dict like {"n": 3, "rank": 23}. status must be
    "verified" or "unverified". Mark "verified" ONLY if the
    decomposition passes this repo's exact checker (verify.check).
    """
    if status not in (VERIFIED, UNVERIFIED):
        raise ValueError(f"status must be {VERIFIED!r} or {UNVERIFIED!r}, got {status!r}")
    if not isinstance(claimed_rank, dict) or "n" not in claimed_rank or "rank" not in claimed_rank:
        raise ValueError("claimed_rank must be a dict like {'n': 3, 'rank': 23}")
    entry = {
        "name": name,
        "source_paper": source_paper,
        "citation": citation,
        "claimed_rank": claimed_rank,
        "status": status,
        "notes": notes,
    }
    data = _load_registry()
    data["techniques"] = [t for t in data["techniques"] if t.get("name") != name]
    data["techniques"].append(entry)
    data["techniques"].sort(key=lambda t: t["name"])
    _save_registry(data)
    return entry


def technique_report() -> str:
    """Render the technique registry as a human-readable report."""
    lines = ["# Technique Registry", ""]
    techniques = list_techniques()
    if not techniques:
        return "# Technique Registry\n\n(no entries)\n"
    for t in techniques:
        cr = t.get("claimed_rank", {})
        lines.append(f"## {t['name']} — {t['status']}")
        lines.append(f"  n={cr.get('n')}, claimed rank={cr.get('rank')}")
        lines.append(f"  Source: {t.get('source_paper')}")
        lines.append(f"  Citation: {t.get('citation')}")
        if t.get("notes"):
            lines.append(f"  Notes: {t['notes']}")
        lines.append("")
    lines.append("---")
    lines.append("Paper PDFs are never committed. To populate this machine's")
    lines.append("paper cache from the registry: python literature.py fetch --all")
    lines.append("")
    return "\n".join(lines)


def fetch_papers(cache_dir: str | None = None) -> list[dict]:
    """Download PDFs for every registry entry that has an arxiv_id.

    Skips entries without an arxiv_id and ones already cached. Returns
    a list of {name, arxiv_id, status} where status is one of
    "ok", "skip", "fail". Prints one line per paper.
    """
    results = []
    for t in list_techniques():
        arxiv_id = t.get("arxiv_id")
        name = t.get("name", "?")
        if not arxiv_id:
            results.append({"name": name, "arxiv_id": None, "status": "skip"})
            print(f"skip  {name}: no arXiv id")
            continue
        try:
            cache = cache_dir or DEFAULT_CACHE_DIR
            safe = _safe_arxiv_id(arxiv_id)
            already = os.path.exists(os.path.join(cache, safe + ".pdf"))
            path = download_paper(arxiv_id, cache_dir=cache_dir)
            status = "skip" if already else "ok"
            results.append({"name": name, "arxiv_id": arxiv_id, "status": status})
            print(f"{status}   {name} [{arxiv_id}] -> {path}")
        except Exception as e:
            results.append({"name": name, "arxiv_id": arxiv_id, "status": "fail"})
            print(f"fail  {name} [{arxiv_id}]: {e}")
    return results


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Literature fuel for the discovery loop")
    parser.add_argument("command", nargs="?", default="report",
                        choices=["report", "fetch"],
                        help="'report' prints the technique registry; "
                             "'fetch' downloads registry papers into the cache")
    parser.add_argument("--all", action="store_true",
                        help="with 'fetch': download every registry entry that has an arxiv_id")
    args = parser.parse_args()

    if args.command == "fetch":
        if not args.all:
            parser.error("fetch currently requires --all")
        fetch_papers()
    else:
        print(technique_report())
        print("=" * 60)
        print("Cache dir:", DEFAULT_CACHE_DIR)
        print("Downloaded/extracted material stays in the cache dir and is never committed.")
