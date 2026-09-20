"""Operator-driven intake of one public prize page into a reviewable candidate file.

Nothing here is admitted automatically. `add` fetches exactly one operator-typed URL,
quotes what it saw, and writes `data/prizes/intake/<slug>.json` with
`content_classification: "untrusted_quoted_source"`. Page text is never executed and
never reaches a model prompt; only `approve` moves a reviewed entry into
`data/prizes.json`, through prize_registry's validation.
"""

from __future__ import annotations

import argparse
import copy
import html as html_module
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from research_state import FileLock, atomic_json, read_json


ROOT = Path(__file__).resolve().parent
INTAKE_RELATIVE = "data/prizes/intake"
REGISTRY_RELATIVE = "data/prizes.json"
USER_AGENT = "discovery-loop-prize-intake"
FETCH_TIMEOUT_SECONDS = 10
MAX_FETCH_BYTES = 512 * 1024
KINDS = ("challenge", "issue", "competition", "paper", "benchmark", "bounty")
PRIORITIES = ("queued", "watch")
ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MAX_AMOUNTS = 24
MAX_DEADLINE_HINTS = 12
EXCERPT_CHARS = 600

_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_TAG_RE = re.compile(r"(?s)<[^>]*>")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_H1_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
_USD_RE = re.compile(r"(?:US)?\$\s?\d[\d,]*(?:\.\d+)?")
_BTC_RE = re.compile(r"\d+(?:\.\d+)?\s?BTC")
_EUR_RE = re.compile(r"€\s?\d[\d,']*(?:\.\d+)?")
_DEADLINE_RE = re.compile(r"(?i)\b(?:deadline|closes|until)\b[^.\n]{0,80}")

# Keyword guesses only: the operator sets the real category before approval.
_CATEGORY_KEYWORDS = (
    ("ecdlp", ("ecdlp", "elliptic curve", "discrete logarithm", "certicom")),
    ("hash-collision", ("collision", "preimage", "sha-256", "sha256", "ripemd", "hash160")),
    ("compression", ("compression", "compressor", "enwik", "lossless")),
    ("benchmark-record", ("benchmark", "best known", "record", "instance library")),
    ("publication", ("paper", "journal", "conference", "proceedings")),
)


class IntakeError(ValueError):
    """The URL, the fetched page or the intake file is unsafe or malformed."""


def _utc_now(now=None):
    moment = now or datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def _clean(value, limit):
    text = " ".join(str(value).split())
    text = "".join(character for character in text if ord(character) >= 32)
    return text[:limit]


def validate_url(url):
    """Return the URL when it is a plain http/https address without credentials."""
    if not isinstance(url, str):
        raise IntakeError("url must be text")
    clean = url.strip()
    if len(clean) > 2048:
        raise IntakeError("url exceeds 2048 characters")
    parsed = urlsplit(clean)
    if parsed.scheme not in ("http", "https"):
        raise IntakeError("url must start with http:// or https://")
    if not parsed.hostname or parsed.username or parsed.password:
        raise IntakeError("url must name a host and carry no credentials")
    return clean


def fetch(url, *, timeout=FETCH_TIMEOUT_SECONDS, max_bytes=MAX_FETCH_BYTES):
    """Fetch one operator-typed page. The only network call in this module."""
    target = validate_url(url)
    request = urllib.request.Request(target, headers={"User-Agent": USER_AGENT}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", None) or response.getcode()
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise IntakeError(f"response exceeds the {max_bytes} byte cap")
    return {"url": target, "http_status": int(status), "html": body.decode(charset, errors="replace")}


def visible_text(html):
    """Strip scripts, styles, comments and tags; nothing from the page is ever executed."""
    stripped = _SCRIPT_RE.sub(" ", html or "")
    stripped = _COMMENT_RE.sub(" ", stripped)
    stripped = _TAG_RE.sub(" ", stripped)
    return " ".join(html_module.unescape(stripped).split())


def _slug(value, fallback):
    base = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    if not base:
        base = re.sub(r"[^a-z0-9]+", "-", str(fallback or "").lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)[:64].strip("-")
    if not base or not ID_RE.match(base):
        raise IntakeError("could not derive a slug; pass --name")
    return base


def _amounts(text):
    found = []
    for pattern in (_USD_RE, _BTC_RE, _EUR_RE):
        for match in pattern.findall(text):
            item = _clean(match, 64)
            if item and item not in found:
                found.append(item)
    return found[:MAX_AMOUNTS]


def _deadline_hints(text):
    hints = []
    for match in _DEADLINE_RE.findall(text):
        item = _clean(match, 120)
        if any(character.isdigit() for character in item) and item not in hints:
            hints.append(item)
    return hints[:MAX_DEADLINE_HINTS]


def _category_guess(text):
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


def extract(html, url):
    """Quote the page: title, opening text, currency mentions, deadline phrases, category guess."""
    target = validate_url(url)
    text = visible_text(html)
    title_match = _TITLE_RE.search(html or "") or _H1_RE.search(html or "")
    title = _clean(html_module.unescape(title_match.group(1)), 300) if title_match else ""
    return {
        "url": target,
        "title": title,
        "excerpt": text[:EXCERPT_CHARS],
        "amounts": _amounts(text),
        "deadline_hints": _deadline_hints(text),
        "category_guess": _category_guess(f"{title} {text}"),
    }


def _currency(amounts):
    for amount in amounts:
        if "BTC" in amount:
            return "BTC"
        if "€" in amount:
            return "EUR"
        if "$" in amount:
            return "USD"
    return "none"


def propose(extracted, kind, name=None, *, now=None):
    """Build a PRIZE-shaped entry with every uncertain field marked, never a prize claim."""
    if kind not in KINDS:
        raise IntakeError(f"kind must be one of {', '.join(KINDS)}")
    url = validate_url(extracted.get("url"))
    host = urlsplit(url).hostname or ""
    amounts = list(extracted.get("amounts") or [])
    title = _clean(extracted.get("title") or "", 300)
    display_name = _clean(name or title or host, 200)
    slug = _slug(name or title or host, host)
    unassessed = "not assessed at intake; operator review required"
    return {
        "id": slug,
        "name": display_name,
        "category": extracted.get("category_guess") or "other",
        "description": _clean(extracted.get("excerpt") or "", 600),
        "source_url": url,
        "rules_url": None,
        "advertised_prize": amounts[0] if amounts else "unspecified on the fetched page",
        "currency": _currency(amounts),
        "estimated_usd": None,
        "estimated_usd_basis": "no rate observed at intake; quoted wording only",
        "status": "status_uncertain",
        "status_confidence": "low",
        "last_verified": None,
        "submission_requirements": unassessed,
        "target_definition": unassessed,
        "known_best_result": unassessed,
        "verification_method": unassessed,
        "computational_difficulty": "moderate",
        "research_difficulty": "open_problem",
        "authorization_notes": (
            f"fetched from {host} as a {kind}; not confirmed as an explicitly authorized "
            "challenge until the operator says so"
        ),
        "plugin": None,
        "probability_category": "remote",
        "compute_cost_estimate": {"category": "moderate", "note": unassessed},
        "model_cost_estimate": {"category": "moderate", "note": unassessed},
        "publication_value": "none",
        "commercial_value": "none",
        "transfer_value": "none",
        "competition_level": "medium",
        "time_horizon": "open_ended",
        "parallelizable": False,
        "dense_feedback": False,
        "independent_verification": "weak",
        "research_priority": "watch",
        "notes": (
            "Intake candidate: every category above is an intake default, not a measurement. "
            f"Amounts quoted from the page: {', '.join(amounts) if amounts else 'none found'}."
        ),
        "evidence": [
            {
                "date": _today(now),
                "url": url,
                "observed": _clean(
                    f"intake fetch of {url}; page title {title or 'none'}; "
                    f"amounts quoted: {', '.join(amounts) if amounts else 'none'}",
                    400,
                ),
                "file": None,
            }
        ],
        "history": [],
    }


def intake_dir(root=ROOT):
    return Path(root) / INTAKE_RELATIVE


def intake_path(slug, root=ROOT):
    if not ID_RE.match(str(slug)):
        raise IntakeError("slug must be a lowercase hyphenated id")
    return intake_dir(root) / f"{slug}.json"


def load_intake(slug, root=ROOT):
    record = read_json(intake_path(slug, root))
    if not isinstance(record, dict):
        raise IntakeError(f"no intake candidate named {slug}")
    return record


def _write_intake(record, root, slug):
    path = intake_path(slug, root)
    with FileLock(path.with_suffix(".lock")):
        atomic_json(path, record)
    return f"{INTAKE_RELATIVE}/{slug}.json"


def add(url, *, kind="challenge", name=None, root=ROOT, fetcher=None, now=None):
    """Fetch one page and write a candidate file. Admits nothing."""
    if kind not in KINDS:
        raise IntakeError(f"kind must be one of {', '.join(KINDS)}")
    fetched = (fetcher or fetch)(validate_url(url))
    extracted = extract(fetched.get("html") or "", fetched.get("url") or url)
    entry = propose(extracted, kind, name, now=now)
    record = {
        "schema_version": 1,
        "status": "candidate",
        "url": extracted["url"],
        "kind": kind,
        "fetched_at": _utc_now(now),
        "http_status": int(fetched.get("http_status") or 0),
        "title": extracted["title"],
        "excerpt": extracted["excerpt"],
        "amounts": extracted["amounts"],
        "deadline_hints": extracted["deadline_hints"],
        "category_guess": extracted["category_guess"],
        "proposed_entry": entry,
        "content_classification": "untrusted_quoted_source",
    }
    path = _write_intake(record, root, entry["id"])
    return {"slug": entry["id"], "path": path, "record": record}


def list_candidates(root=ROOT):
    directory = intake_dir(root)
    rows = []
    for path in sorted(directory.glob("*.json")):
        record = read_json(path)
        if not isinstance(record, dict):
            continue
        rows.append(
            {
                "slug": path.stem,
                "status": record.get("status"),
                "url": record.get("url"),
                "title": record.get("title"),
                "kind": record.get("kind"),
                "fetched_at": record.get("fetched_at"),
                "path": f"{INTAKE_RELATIVE}/{path.name}",
            }
        )
    return rows


def _registry_module():
    try:
        import prize_registry
    except ImportError as error:  # pragma: no cover - exercised only without slice A
        raise IntakeError("prize_registry is unavailable; cannot approve an intake candidate") from error
    return prize_registry


def _validated_write(registry_path, document, registry):
    """Write data/prizes.json only after prize_registry validates the merged document."""
    registry_error = getattr(registry, "RegistryError", ValueError)
    candidate = registry_path.with_name(f".{registry_path.stem}-candidate.json")
    try:
        atomic_json(candidate, document)
        try:
            registry.load_registry(candidate)
        except registry_error as error:
            raise IntakeError(f"proposed entry fails registry validation: {error}") from error
    finally:
        if candidate.exists():
            candidate.unlink()
    atomic_json(registry_path, document)


def approve(slug, *, root=ROOT, priority="queued", by="operator", now=None, registry_path=None):
    """Move a reviewed candidate into data/prizes.json and mark the intake file approved."""
    if priority not in PRIORITIES:
        raise IntakeError(f"priority must be one of {', '.join(PRIORITIES)}")
    record = load_intake(slug, root)
    if record.get("status") != "candidate":
        raise IntakeError(f"{slug} is already {record.get('status')}")
    entry = copy.deepcopy(record.get("proposed_entry"))
    if not isinstance(entry, dict) or not ID_RE.match(str(entry.get("id", ""))):
        raise IntakeError(f"{slug} carries no usable proposed entry")
    entry["research_priority"] = priority
    history = list(entry.get("history") or [])
    history.append(
        {
            "date": _today(now),
            "field": "research_priority",
            "from": None,
            "to": priority,
            "by": by,
            "note": f"approved from intake candidate {slug}",
        }
    )
    entry["history"] = history

    path = Path(registry_path) if registry_path else Path(root) / REGISTRY_RELATIVE
    registry = _registry_module()
    with FileLock(path.with_suffix(".lock")):
        document = read_json(path) or {"schema_version": 1, "updated_at": _today(now), "prizes": []}
        prizes = list(document.get("prizes") or [])
        if any(isinstance(item, dict) and item.get("id") == entry["id"] for item in prizes):
            raise IntakeError(f"{entry['id']} is already in the registry")
        prizes.append(entry)
        document = {"schema_version": 1, "updated_at": _today(now), "prizes": prizes}
        _validated_write(path, document, registry)

    record["status"] = "approved"
    record["approved_at"] = _utc_now(now)
    record["approved_by"] = by
    record["approved_priority"] = priority
    record["proposed_entry"] = entry
    _write_intake(record, root, slug)
    return {"slug": slug, "prize_id": entry["id"], "registry": REGISTRY_RELATIVE, "prizes": len(prizes)}


def reject(slug, *, reason, root=ROOT, by="operator", now=None):
    record = load_intake(slug, root)
    if record.get("status") != "candidate":
        raise IntakeError(f"{slug} is already {record.get('status')}")
    record["status"] = "rejected"
    record["rejected_at"] = _utc_now(now)
    record["rejected_by"] = by
    record["reject_reason"] = _clean(reason, 400)
    if not record["reject_reason"]:
        raise IntakeError("a reject needs a reason")
    path = _write_intake(record, root, slug)
    return {"slug": slug, "status": "rejected", "path": path}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch and review one public prize page; admits nothing")
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser = sub.add_parser("add", help="fetch one http(s) URL into a candidate file")
    add_parser.add_argument("url")
    add_parser.add_argument("--kind", choices=KINDS, default="challenge")
    add_parser.add_argument("--name", default=None)
    approve_parser = sub.add_parser("approve", help="move a candidate into data/prizes.json")
    approve_parser.add_argument("slug")
    approve_parser.add_argument("--priority", choices=PRIORITIES, default="queued")
    reject_parser = sub.add_parser("reject", help="mark a candidate rejected")
    reject_parser.add_argument("slug")
    reject_parser.add_argument("--reason", required=True)
    sub.add_parser("list", help="list candidate files")
    args = parser.parse_args(argv)

    try:
        if args.command == "add":
            result = add(args.url, kind=args.kind, name=args.name, root=ROOT)
            print(result["path"])
            print("not admitted: run approve to add it to data/prizes.json")
            return 0
        if args.command == "approve":
            result = approve(args.slug, root=ROOT, priority=args.priority)
        elif args.command == "reject":
            result = reject(args.slug, root=ROOT, reason=args.reason)
        else:
            result = {"candidates": list_candidates(ROOT)}
    except IntakeError as error:
        print(f"intake error: {error}")
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
