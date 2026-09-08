"""Small, development-only memory helpers for the solver discovery loop."""

import ast
import hashlib
import math
import re
from collections import Counter


_FAMILY_TAG = re.compile(r"\[kind:\s*([^\]]+)\]", re.IGNORECASE)
_NEGATIVE_STATUSES = {
    "generation_failed",
    "invalid",
    "syntax_error",
    "duplicate",
    "rejected",
    "evaluation_failed",
    "promising_unreviewed",
}
_DEVELOPMENT_STATUSES = _NEGATIVE_STATUSES | {"evaluated", "promising"}
_VALID_DEVELOPMENT_STATUSES = {"rejected", "promising", "promising_unreviewed", "evaluated"}
_ABSOLUTE_PATH = re.compile(r"(?<![:\w])(?:[A-Za-z]:[\\/]|/(?!/))[A-Za-z0-9_.~\\/-]+")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_PROVIDER_FAMILIES = {"anthropic", "openai", "fable", "astra", "paired"}


def analyze_candidate(code, known_fingerprints=()):
    """Parse *code* and compare its position-free AST hash to prior candidates.

    Python's parser already discards comments and whitespace.  Docstrings stay
    in the tree because changing ``__doc__`` can change program behavior.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "valid": False,
            "syntax_error": f"{exc.msg} (line {exc.lineno})",
            "fingerprint": None,
            "duplicate": False,
        }
    normalized = ast.dump(tree, annotate_fields=True, include_attributes=False)
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "valid": True,
        "syntax_error": None,
        "fingerprint": fingerprint,
        "duplicate": fingerprint in set(known_fingerprints),
    }


def _redact(value, hidden_targets, limit):
    text = str(value) if isinstance(value, str) else ""
    for target in hidden_targets:
        text = text.replace(str(target), "[withheld reference removed]")
    return _ABSOLUTE_PATH.sub("[local path removed]", text)[:limit]


def _family(record, idea):
    value = record.get("idea_family")
    if isinstance(value, str) and value:
        return re.sub(r"\s+", " ", value.strip().lower())[:80]
    match = _FAMILY_TAG.search(idea)
    if match:
        return re.sub(r"\s+", " ", match.group(1).strip().lower())[:80]
    value = record.get("family")
    if isinstance(value, str) and value and value.strip().lower() not in _PROVIDER_FAMILIES:
        return re.sub(r"\s+", " ", value.strip().lower())[:80]
    return "unclassified"


def _finite_number(value, *, positive=False):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None
    value = float(value)
    return value if not positive or value >= 0 else None


def _iteration(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _development_entry(record, hidden_targets):
    idea = _redact(record.get("idea"), hidden_targets, 500)
    critique = record.get("critique") if isinstance(record.get("critique"), dict) else {}
    raw_status = record.get("development_status", record.get("status"))
    status = raw_status if isinstance(raw_status, str) and raw_status in _DEVELOPMENT_STATUSES else ""
    negative_result = _redact(record.get("negative_result"), hidden_targets, 240)
    if not negative_result and status in _NEGATIVE_STATUSES:
        negative_result = status
    fingerprint = record.get("fingerprint")
    fingerprint = fingerprint if isinstance(fingerprint, str) and _FINGERPRINT.fullmatch(fingerprint) else None
    return {
        "problem": _redact(record.get("problem"), hidden_targets, 120),
        "iteration": _iteration(record.get("iteration")),
        "provider": _redact(record.get("provider"), hidden_targets, 80),
        "actual_model": _redact(record.get("actual_model", record.get("model")), hidden_targets, 160),
        "role": _redact(record.get("role") or "generation", hidden_targets, 80),
        "family": _redact(_family(record, idea), hidden_targets, 80),
        "idea": idea,
        "development_status": status,
        "negative_result": negative_result,
        "median_gain": _finite_number(record.get("median_gain")),
        # "valid" means a successful development evaluation, not merely a
        # parseable candidate. Integration should set this flag explicitly.
        "valid": bool(record["valid"])
        if isinstance(record.get("valid"), bool)
        else status in _VALID_DEVELOPMENT_STATUSES,
        "novel": bool(record["novel"]) if isinstance(record.get("novel"), bool) else False,
        "promising": bool(record["promising"]) if isinstance(record.get("promising"), bool) else status == "promising",
        "fingerprint": fingerprint,
        "cost_usd": _finite_number(record.get("cost_usd", record.get("cost")), positive=True),
        "elapsed_seconds": _finite_number(record.get("elapsed_seconds", record.get("secs")), positive=True),
        "critique": {
            "provider": _redact(critique.get("provider"), hidden_targets, 80),
            "text": _redact(critique.get("text"), hidden_targets, 400),
            "error": _redact(critique.get("error"), hidden_targets, 300),
        },
    }


def summarize_development(history, *, hidden_targets=(), limit=20, family_limit=12):
    """Return a bounded prompt-safe projection plus recurring-family outcomes.

    The compact family rollup considers all supplied development observations,
    so a recurring old failed approach survives even when its individual rows
    fall outside the recent window.
    """
    if limit < 1 or family_limit < 1:
        raise ValueError("memory limits must be positive")
    entries = [_development_entry(item, hidden_targets) for item in history if isinstance(item, dict)]
    families = {}
    for entry in entries:
        family = entry["family"]
        item = families.setdefault(
            family,
            {
                "family": family,
                "attempts": 0,
                "valid": 0,
                "novel": 0,
                "promising": 0,
                "negative_results": Counter(),
                "last_iteration": None,
            },
        )
        item["attempts"] += 1
        item["valid"] += int(entry["valid"])
        item["novel"] += int(entry["novel"])
        item["promising"] += int(entry["promising"])
        if entry["negative_result"]:
            item["negative_results"][entry["negative_result"]] += 1
        item["last_iteration"] = entry["iteration"]
    ordered_families = sorted(
        families.values(),
        key=lambda item: (-sum(item["negative_results"].values()), -item["attempts"], str(item["family"])),
    )[:family_limit]
    for item in ordered_families:
        total = sum(item["negative_results"].values())
        item["negative_results"] = dict(
            sorted(item["negative_results"].items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        )
        item["negative_total"] = total
    return {"entries": entries[-limit:], "families": ordered_families}


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def operational_stats(history):
    """Summarize development attempts by problem, actual model, and role only."""
    entries = history.get("entries", []) if isinstance(history, dict) else history
    groups = {}
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        entry = _development_entry(raw, ())
        key = (entry["problem"], entry["actual_model"], entry["role"])
        group = groups.setdefault(
            key,
            {
                "problem": key[0],
                "actual_model": key[1],
                "role": key[2],
                "attempts": 0,
                "valid": 0,
                "novel": 0,
                "promising": 0,
                "cost_usd": 0.0,
                "elapsed_seconds": 0.0,
            },
        )
        group["attempts"] += 1
        for field in ("valid", "novel", "promising"):
            group[field] += int(entry[field])
        group["cost_usd"] += _number(entry["cost_usd"])
        group["elapsed_seconds"] += _number(entry["elapsed_seconds"])
    result = []
    for group in groups.values():
        attempts = group["attempts"]
        group.update({field + "_rate": group[field] / attempts for field in ("valid", "novel", "promising")})
        result.append(group)
    return sorted(result, key=lambda item: (item["problem"], item["actual_model"], item["role"]))


def rank_auto_allocation(stats, choices, *, min_samples=3, exploration_slots=1):
    """Rank a first automatic choice while reserving under-sampled exploration.

    This is an operational ordering only.  It neither changes the caller's
    fixed fallback chain nor consumes confirmation, promotion, or gain data.
    """
    if min_samples < 1 or exploration_slots < 0:
        raise ValueError("minimum samples and exploration slots must be non-negative")
    indexed = {
        (item.get("problem", ""), item.get("actual_model", ""), item.get("role", "")): item
        for item in stats
        if isinstance(item, dict)
    }
    mature, exploratory = [], []
    for index, choice in enumerate(choices):
        item = dict(choice)
        group = indexed.get(
            (item.get("problem", ""), item.get("actual_model", item.get("model", "")), item.get("role", "generation"))
        )
        attempts = int(group.get("attempts", 0)) if group else 0
        item["attempts"] = attempts
        if attempts < min_samples:
            exploratory.append((index, item))
            continue
        score = group["valid_rate"] + group["novel_rate"] + group["promising_rate"]
        elapsed = group["elapsed_seconds"] / attempts
        item["operational_score"] = score
        item["mean_elapsed_seconds"] = elapsed
        mature.append((score, -elapsed, -index, item))
    mature.sort(reverse=True)
    exploratory.sort(key=lambda pair: (pair[1]["attempts"], pair[0]))
    return {
        "primary": mature[0][3] if mature else None,
        "ranked": [item for _, _, _, item in mature],
        "exploration": [item for _, item in exploratory[:exploration_slots]],
    }
