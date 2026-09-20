"""Validate the operator-curated prize registry and bind reviewed prizes to local research.

``data/prizes.json`` is untrusted, quoted intake: every amount, deadline and status sentence is
copied from a public page and carries its own evidence rows. Nothing in that file can promote a
prize to executable work. The reviewed bindings live in ``PRIZE_BINDINGS`` below, in code, for the
same reason ``arc_catalogue.ADMISSIONS`` does: :func:`validate_snapshot` re-derives every admission
from this module, so a rewritten JSON file cannot admit a prize no human reviewed.

Nothing here submits, claims, emails or spends anything. The only code path that touches the
network is the explicit ``check-sources`` command, which fetches URLs already present in the
registry and reports their HTTP status; it never edits ``data/prizes.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import arc_catalogue
from arc_catalogue import CatalogueError
from research_state import FileLock, atomic_json, read_json


ROOT = Path(__file__).resolve().parent
DATA_RELATIVE = "data/prizes.json"
DATA_PATH = ROOT / "data" / "prizes.json"
EVIDENCE_RELATIVE = "data/prizes/evidence/"
# Only a balance read from a block explorer API backs a "verified on chain" claim.
CHAIN_EVIDENCE_PREFIXES = (
    "https://mempool.space/api/address/",
    "https://blockstream.info/api/address/",
)
MAX_PRIZES = 200
MAX_FILE_BYTES = 512 * 1024
MAX_EVIDENCE = 64
MAX_HISTORY = 200
MAX_SOURCE_BYTES = 512 * 1024
SOURCE_TIMEOUT = 10.0
USER_AGENT = "discovery-loop-prize-registry"

ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_RE = re.compile(r"[a-f0-9]{64}\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")

CATEGORIES = {"ecdlp", "hash-collision", "compression", "benchmark-record", "publication", "other"}
CURRENCIES = {"USD", "BTC", "EUR", "none"}
STATUSES = {
    "verified_active",
    "probably_active",
    "status_uncertain",
    "historical",
    "closed",
    "solved",
    "not_prize_eligible",
}
CONFIDENCES = {"high", "medium", "low"}
COMPUTATIONAL_DIFFICULTY = {"trivial", "small", "moderate", "large", "infeasible_today"}
RESEARCH_DIFFICULTY = {"engineering", "incremental", "open_problem", "breakthrough_required"}
PROBABILITY_CATEGORIES = {"likely", "possible", "unlikely", "remote", "negligible"}
COST_CATEGORIES = {"negligible", "cheap", "moderate", "expensive", "prohibitive"}
VALUE_LEVELS = {"none", "low", "medium", "high"}
TIME_HORIZONS = {"days", "weeks", "months", "years", "open_ended"}
VERIFICATION_LEVELS = {"strong", "partial", "weak"}
PRIORITIES = {"active", "queued", "watch", "parked", "excluded"}
# A prize in one of these statuses is display data only; it never becomes a run target.
UNRUNNABLE_STATUSES = {"closed", "solved", "not_prize_eligible"}

CLAIM_NOTE = (
    "Prize wording, amount and availability are quoted from the source named in evidence and have "
    "not been independently confirmed with the sponsor."
)


# Every string here is locally reviewed. None of it is read from data/prizes.json.
PRIZE_BINDINGS = {
    "certicom-eccp-131": {
        "plugin": "ecc_prize",
        "baseline": "problems/ecc_prize/seed_solver.py",
        "verifier": "problems/ecc_prize/verify.py",
        "development": ["ecdlp-p24-dev", "ecdlp-p28-dev", "ecdlp-p32-dev", "ecdlp-p36-dev"],
        "holdout": ["ecdlp-p28-hold", "ecdlp-p32-hold", "ecdlp-p36-hold", "ecdlp-p40-hold"],
        "success_criterion": (
            "Solve the generated ladder instances faster than the frozen baseline by the slot's paired "
            "minimum-effect threshold, with every holdout solution accepted by the independent verifier. "
            "The 131-bit challenge instance is never a run target."
        ),
        "max_minutes": 120,
        "max_slot_budget_usd": 12.0,
        "max_per_call_budget_usd": 1.0,
    },
    "todd-sha256-collision": {
        "plugin": "hash_collision_prize",
        "baseline": "problems/hash_collision_prize/seed_solver.py",
        "verifier": "problems/hash_collision_prize/verify.py",
        "development": ["sha256-t28-dev", "sha256-t32-dev", "sha256-t36-dev", "ripemd160-t32-dev"],
        "holdout": ["sha256-t32-hold", "sha256-t36-hold", "ripemd160-t32-hold", "sha256r24-t32-hold"],
        "success_criterion": (
            "Find truncated-digest collisions on the ladder faster than the frozen baseline by the slot's "
            "paired minimum-effect threshold. Truncated collisions measure search machinery only; they are "
            "not partial progress toward a full collision."
        ),
        "max_minutes": 120,
        "max_slot_budget_usd": 12.0,
        "max_per_call_budget_usd": 1.0,
    },
    "packomania-csqv-records": {
        "plugin": "circle_packing",
        "baseline": "problems/circle_packing/seed_solver.py",
        "verifier": "problems/circle_packing/verify.py",
        "development": ["26", "32", "101", "102", "103", "105", "106", "107", "108", "109", "111", "114"],
        "holdout": [],
        "success_criterion": (
            "Improve a development packing past the frozen incumbent with zero overlap or containment "
            "failures under the independent verifier; any upstream claim goes through the existing "
            "evidence and approval chain."
        ),
        "max_minutes": 210,
        "max_slot_budget_usd": 40.0,
        "max_per_call_budget_usd": 2.0,
    },
    "matmul-rank-records": {
        "plugin": "matrix_multiplication",
        "baseline": "problems/matrix_multiplication/seed_solver.py",
        "verifier": "problems/matrix_multiplication/verify.py",
        "development": ["2", "3", "4"],
        "holdout": [],
        "success_criterion": (
            "Lower the verified integer rank on n=3 or n=4 with the exact tensor identity accepted by the "
            "independent verifier; n=2 is a calibration target that cannot be beaten."
        ),
        "max_minutes": 210,
        "max_slot_budget_usd": 40.0,
        "max_per_call_budget_usd": 2.0,
    },
    "cvrplib-x-open": {
        "plugin": "cvrp",
        "baseline": "problems/cvrp/seed_solver.py",
        "verifier": "problems/cvrp/verify.py",
        "development": [
            "X-n280-k17",
            "X-n303-k21",
            "X-n327-k20",
            "X-n336-k84",
            "X-n401-k29",
            "X-n411-k19",
            "X-n429-k61",
            "X-n459-k26",
            "X-n480-k70",
            "X-n491-k59",
        ],
        "holdout": [],
        "success_criterion": (
            "Beat the frozen incumbent cost by the slot's paired minimum-effect threshold with zero "
            "feasibility failures on the independent verifier; otherwise record a bounded negative result."
        ),
        "max_minutes": 210,
        "max_slot_budget_usd": 40.0,
        "max_per_call_budget_usd": 2.0,
    },
}
PRIZE_BINDINGS["todd-ripemd160-collision"] = dict(PRIZE_BINDINGS["todd-sha256-collision"])
PRIZE_BINDINGS["todd-hash160-collision"] = dict(PRIZE_BINDINGS["todd-sha256-collision"])
PRIZE_BINDINGS["todd-hash256-collision"] = dict(PRIZE_BINDINGS["todd-sha256-collision"])


class RegistryError(ValueError):
    """The prize registry, a snapshot or a control file is unsafe or malformed."""


_utc_now = arc_catalogue._utc_now


def _utc_date(now=None):
    return _utc_now(now)[:10]


def _object(value, name):
    try:
        return arc_catalogue._object(value, name)
    except CatalogueError as exc:
        raise RegistryError(str(exc)) from None


def _text(value, name, limit, *, required=True):
    try:
        return arc_catalogue._text(value, name, limit, required=required)
    except CatalogueError as exc:
        raise RegistryError(str(exc)) from None


def _string_list(value, name, *, limit=24, item_limit=120):
    try:
        return arc_catalogue._string_list(value, name, limit=limit, item_limit=item_limit)
    except CatalogueError as exc:
        raise RegistryError(str(exc)) from None


def _url(value, name, *, required=True):
    """Public http(s) URL without credentials. Plain http is allowed: the Hutter Prize page uses it."""
    clean = _text(value, name, 2048, required=required)
    if clean is None:
        return None
    parsed = urlsplit(clean)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise RegistryError(f"{name} must be a public HTTP or HTTPS URL without credentials")
    return clean


def _enum(value, name, allowed, *, limit=40):
    clean = _text(value, name, limit)
    if clean not in allowed:
        raise RegistryError(f"{name} is unsupported")
    return clean


def _date(value, name, *, required=True):
    clean = _text(value, name, 40, required=required)
    if clean is None:
        return None
    if not DATE_RE.fullmatch(clean):
        raise RegistryError(f"{name} must be a YYYY-MM-DD date")
    return clean


def _flag(value, name):
    if not isinstance(value, bool):
        raise RegistryError(f"{name} must be true or false")
    return value


def _money(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RegistryError(f"{name} must be a number or null")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise RegistryError(f"{name} must be a finite nonnegative number")
    return number


def _cost(value, name):
    cost = _object(value, name)
    return {
        "category": _enum(cost.get("category"), f"{name}.category", COST_CATEGORIES),
        "note": _text(cost.get("note"), f"{name}.note", 400),
    }


def _scalar(value, name):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _text(value, name, 300)
    raise RegistryError(f"{name} must be text, a number, a boolean or null")


def _evidence_file(value, name):
    clean = _text(value, name, 300, required=False)
    if clean is None:
        return None
    if "\\" in clean or clean.startswith("/") or ".." in clean.split("/"):
        raise RegistryError(f"{name} must be a repository-relative POSIX path")
    if not clean.startswith(EVIDENCE_RELATIVE) or not clean.endswith(".json"):
        raise RegistryError(f"{name} must name a JSON file under {EVIDENCE_RELATIVE}")
    return clean


def _evidence(value, index):
    row = _object(value, f"evidence[{index}]")
    return {
        "date": _date(row.get("date"), f"evidence[{index}].date"),
        "url": _url(row.get("url"), f"evidence[{index}].url"),
        "observed": _text(row.get("observed"), f"evidence[{index}].observed", 800),
        "file": _evidence_file(row.get("file"), f"evidence[{index}].file"),
    }


def _history(value, index):
    row = _object(value, f"history[{index}]")
    return {
        "date": _date(row.get("date"), f"history[{index}].date"),
        "field": _text(row.get("field"), f"history[{index}].field", 60),
        "from": _scalar(row.get("from"), f"history[{index}].from"),
        "to": _scalar(row.get("to"), f"history[{index}].to"),
        "by": _text(row.get("by"), f"history[{index}].by", 60),
        "note": _text(row.get("note"), f"history[{index}].note", 400, required=False) or "",
    }


def _verified_on_chain(status, evidence_rows):
    """A chain claim needs a chain observation: an evidence row read from a block explorer API."""
    if status != "verified_active":
        return False
    return any(str(row.get("url") or "").startswith(CHAIN_EVIDENCE_PREFIXES) for row in evidence_rows)


def validate_prize(value):
    """Return a normalized prize entry, or raise :class:`RegistryError`."""
    prize = _object(value, "prize")
    prize_id = _text(prize.get("id"), "id", 80)
    if not ID_RE.fullmatch(prize_id):
        raise RegistryError("id must be a lowercase hyphenated slug")
    evidence = prize.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE:
        raise RegistryError(f"evidence must contain at most {MAX_EVIDENCE} rows")
    history = prize.get("history")
    if not isinstance(history, list) or len(history) > MAX_HISTORY:
        raise RegistryError(f"history must contain at most {MAX_HISTORY} rows")
    status = _enum(prize.get("status"), "status", STATUSES)
    plugin = _text(prize.get("plugin"), "plugin", 60, required=False)
    if plugin is not None and not re.fullmatch(r"[a-z][a-z0-9_]*", plugin):
        raise RegistryError("plugin must be a lowercase plugin directory name")
    evidence_rows = [_evidence(row, index) for index, row in enumerate(evidence)]
    return {
        "id": prize_id,
        "name": _text(prize.get("name"), "name", 200),
        "category": _enum(prize.get("category"), "category", CATEGORIES),
        "description": _text(prize.get("description"), "description", 800),
        "source_url": _url(prize.get("source_url"), "source_url"),
        "rules_url": _url(prize.get("rules_url"), "rules_url", required=False),
        "advertised_prize": _text(prize.get("advertised_prize"), "advertised_prize", 300),
        "currency": _enum(prize.get("currency"), "currency", CURRENCIES),
        "estimated_usd": _money(prize.get("estimated_usd"), "estimated_usd"),
        "estimated_usd_basis": _text(prize.get("estimated_usd_basis"), "estimated_usd_basis", 800),
        "status": status,
        "status_confidence": _enum(prize.get("status_confidence"), "status_confidence", CONFIDENCES),
        "last_verified": _date(prize.get("last_verified"), "last_verified", required=False),
        "submission_requirements": _text(prize.get("submission_requirements"), "submission_requirements", 800),
        "target_definition": _text(prize.get("target_definition"), "target_definition", 800),
        "known_best_result": _text(prize.get("known_best_result"), "known_best_result", 800),
        "verification_method": _text(prize.get("verification_method"), "verification_method", 800),
        "computational_difficulty": _enum(
            prize.get("computational_difficulty"), "computational_difficulty", COMPUTATIONAL_DIFFICULTY
        ),
        "research_difficulty": _enum(prize.get("research_difficulty"), "research_difficulty", RESEARCH_DIFFICULTY),
        "authorization_notes": _text(prize.get("authorization_notes"), "authorization_notes", 800),
        "plugin": plugin,
        "probability_category": _enum(
            prize.get("probability_category"), "probability_category", PROBABILITY_CATEGORIES
        ),
        "compute_cost_estimate": _cost(prize.get("compute_cost_estimate"), "compute_cost_estimate"),
        "model_cost_estimate": _cost(prize.get("model_cost_estimate"), "model_cost_estimate"),
        "publication_value": _enum(prize.get("publication_value"), "publication_value", VALUE_LEVELS),
        "commercial_value": _enum(prize.get("commercial_value"), "commercial_value", VALUE_LEVELS),
        "transfer_value": _enum(prize.get("transfer_value"), "transfer_value", VALUE_LEVELS),
        "competition_level": _enum(prize.get("competition_level"), "competition_level", VALUE_LEVELS),
        "time_horizon": _enum(prize.get("time_horizon"), "time_horizon", TIME_HORIZONS),
        "parallelizable": _flag(prize.get("parallelizable"), "parallelizable"),
        "dense_feedback": _flag(prize.get("dense_feedback"), "dense_feedback"),
        "independent_verification": _enum(
            prize.get("independent_verification"), "independent_verification", VERIFICATION_LEVELS
        ),
        "research_priority": _enum(prize.get("research_priority"), "research_priority", PRIORITIES),
        "notes": _text(prize.get("notes"), "notes", 800, required=False) or "",
        "evidence": evidence_rows,
        "history": [_history(row, index) for index, row in enumerate(history)],
        "content_classification": "untrusted_quoted_source",
        "claim_status": {
            "independently_checked_by_discovery_loop": False,
            "verified_on_chain": _verified_on_chain(status, evidence_rows),
            "note": CLAIM_NOTE,
        },
    }


def validate_registry(value):
    """Validate the whole ``data/prizes.json`` document and return it normalized."""
    document = _object(value, "registry")
    if document.get("schema_version") != 1:
        raise RegistryError("registry schema version is unsupported")
    updated_at = _date(document.get("updated_at"), "updated_at")
    prizes = document.get("prizes")
    if not isinstance(prizes, list) or not 1 <= len(prizes) <= MAX_PRIZES:
        raise RegistryError(f"registry must contain 1 to {MAX_PRIZES} prizes")
    seen = set()
    entries = []
    for item in prizes:
        prize = validate_prize(item)
        if prize["id"] in seen:
            raise RegistryError(f"duplicate prize id: {prize['id']}")
        seen.add(prize["id"])
        entries.append(prize)
    return {"schema_version": 1, "updated_at": updated_at, "prizes": entries}


def load_registry(path=DATA_PATH):
    """Read and validate ``data/prizes.json``. Raises :class:`RegistryError` on invalid data."""
    path = Path(path)
    if path.is_symlink():
        raise RegistryError("registry file must not be a symbolic link")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RegistryError(f"registry file is unavailable: {exc}") from None
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise RegistryError("registry file is empty or exceeds the size limit")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"registry file is not valid UTF-8 JSON: {exc}") from None
    return validate_registry(document)


def admission(prize, root=ROOT):
    """Re-derive one prize's admission from the reviewed bindings and the local plugin files."""
    prize_id = prize.get("id") if isinstance(prize, dict) else None
    binding = PRIZE_BINDINGS.get(prize_id)
    if not binding:
        return {
            "admission": "needs_setup",
            "reason": "No reviewed binding names a local plugin, baseline and verifier for this prize.",
            "binding": None,
        }
    status = prize.get("status")
    priority = prize.get("research_priority")
    reason = None
    if status in UNRUNNABLE_STATUSES and not (status == "not_prize_eligible" and priority == "active"):
        # A benchmark with no cash prize is still runnable when the operator keeps it active: its
        # value is publication or commercial, and the scorer reports it under credibility, not cash.
        reason = f"The registry records this prize as {status}, so it is not an executable prize target."
    elif priority == "excluded":
        reason = "The operator excluded this prize from research."
    else:
        root = Path(root)
        missing = [
            relative
            for relative in (f"problems/{binding['plugin']}/problem.py", f"problems/{binding['plugin']}/verify.py")
            if not (root / relative).is_file()
        ]
        if missing:
            reason = f"The bound plugin is not installed locally: {', '.join(missing)}."
    if reason:
        return {"admission": "needs_setup", "reason": reason, "binding": None}
    return {"admission": "ready", "reason": None, "binding": json.loads(json.dumps(binding))}


def _registry_digest(payload):
    copy = json.loads(json.dumps(payload))
    copy.pop("registry_hash", None)
    source = copy.get("source")
    if isinstance(source, dict):
        source.pop("imported_at", None)
    canonical = json.dumps(copy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def snapshot(root=ROOT, *, now=None):
    """Build the validated, admission-stamped snapshot for ``<root>/data/prizes.json``."""
    root = Path(root).resolve()
    path = root / "data" / "prizes.json"
    document = load_registry(path)
    raw_source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    prizes = []
    for prize in document["prizes"]:
        verdict = admission(prize, root)
        prizes.append(
            {
                **prize,
                "admission": verdict["admission"],
                "admission_reason": verdict["reason"],
                "binding": verdict["binding"],
            }
        )
    payload = {
        "schema_version": 1,
        "source": {
            "path": DATA_RELATIVE,
            "raw_source_hash": raw_source_hash,
            "imported_at": _utc_now(now),
            "updated_at": document["updated_at"],
            "prize_count": len(prizes),
            "content_classification": "untrusted_quoted_source",
        },
        "prizes": prizes,
        "registry_hash": None,
    }
    payload["registry_hash"] = _registry_digest(payload)
    return payload


def validate_snapshot(value, root=ROOT):
    """Re-validate a cached snapshot and re-derive every admission from code (tamper detection)."""
    cached = _object(value, "snapshot")
    if cached.get("schema_version") != 1:
        raise RegistryError("snapshot schema version is unsupported")
    source = _object(cached.get("source"), "snapshot source")
    if source.get("path") != DATA_RELATIVE:
        raise RegistryError("snapshot source identity is invalid")
    if source.get("content_classification") != "untrusted_quoted_source":
        raise RegistryError("snapshot content classification is invalid")
    raw_hash = source.get("raw_source_hash")
    if not isinstance(raw_hash, str) or not SHA256_RE.fullmatch(raw_hash):
        raise RegistryError("snapshot raw source hash is invalid")
    prizes = cached.get("prizes")
    if not isinstance(prizes, list) or not 1 <= len(prizes) <= MAX_PRIZES:
        raise RegistryError("snapshot prize list is invalid")
    if source.get("prize_count") != len(prizes):
        raise RegistryError("snapshot prize count does not match")
    seen = set()
    for item in prizes:
        entry = _object(item, "snapshot prize")
        prize = validate_prize(entry)
        if prize["id"] in seen:
            raise RegistryError("snapshot prize id is duplicated")
        seen.add(prize["id"])
        expected = admission(prize, root)
        if (
            entry.get("admission") != expected["admission"]
            or entry.get("admission_reason") != expected["reason"]
            or entry.get("binding") != expected["binding"]
        ):
            raise RegistryError("snapshot reviewed admission was modified")
    digest = cached.get("registry_hash")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) or digest != _registry_digest(cached):
        raise RegistryError("snapshot registry hash does not match its content")
    return json.loads(json.dumps(cached))


def state_root(root=ROOT):
    return Path(root) / "runs" / "prizes"


def refresh_registry(root=ROOT, *, now=None):
    """Re-snapshot ``data/prizes.json`` into ``runs/prizes/``. This never fetches anything."""
    root = Path(root).resolve()
    state = state_root(root)
    snapshot_path = state / "registry.json"
    status_path = state / "refresh-status.json"
    state.mkdir(parents=True, exist_ok=True)
    with FileLock(str(status_path) + ".lock"):
        try:
            previous = validate_snapshot(read_json(snapshot_path), root)
        except (RegistryError, TypeError, ValueError):
            previous = None
        try:
            current = snapshot(root, now=now)
            atomic_json(snapshot_path, current)
            status = {
                "schema_version": 1,
                "status": "fresh",
                "attempted_at": _utc_now(now),
                "registry_hash": current["registry_hash"],
                "prize_count": len(current["prizes"]),
                "ready_count": len(ready_ids(current)),
            }
        except (RegistryError, OSError, ValueError) as exc:
            current = previous if isinstance(previous, dict) else None
            status = {
                "schema_version": 1,
                "status": "stale" if current else "unavailable",
                "attempted_at": _utc_now(now),
                "error": str(exc)[:300],
                "registry_hash": current.get("registry_hash") if current else None,
                "prize_count": len(current.get("prizes", [])) if current else 0,
                "ready_count": len(ready_ids(current)) if current else 0,
            }
        atomic_json(status_path, status)
    return {"snapshot": current, "refresh": status}


def load_snapshot(root=ROOT):
    """Return the cached snapshot when it still validates against the in-code bindings, else None."""
    try:
        return validate_snapshot(read_json(state_root(root) / "registry.json"), root)
    except (RegistryError, TypeError, ValueError):
        return None


def ready_ids(cached):
    if not isinstance(cached, dict):
        return []
    return sorted(
        prize["id"]
        for prize in cached.get("prizes", [])
        if isinstance(prize, dict) and prize.get("admission") == "ready"
    )


def load_control(root=ROOT, cached=None):
    control = read_json(state_root(root) / "control.json")
    ready = ready_ids(cached)
    if not isinstance(control, dict) or control.get("schema_version") != 1:
        return {"schema_version": 1, "enabled_ids": ready, "next_id": None, "updated_at": None}
    enabled = sorted({item for item in control.get("enabled_ids", []) if item in ready})
    next_id = control.get("next_id") if control.get("next_id") in enabled else None
    return {**control, "schema_version": 1, "enabled_ids": enabled, "next_id": next_id}


def _slug(value, name):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise RegistryError(f"{name} must be a lowercase hyphenated slug")
    return value


def update_control(root=ROOT, *, enable=None, disable=None, next_id=None, clear_next=False, now=None):
    """Enable, disable or pre-select a prize. Only admitted prizes can be enabled or chosen."""
    actions = [enable, disable, next_id]
    if not any(action is not None for action in actions) and not clear_next:
        raise RegistryError("set at least one of enable, disable, next_id or clear_next")
    root = Path(root).resolve()
    cached = load_snapshot(root)
    ready = ready_ids(cached)
    for value, name in ((enable, "enable"), (disable, "disable"), (next_id, "next_id")):
        if value is None:
            continue
        _slug(value, name)
        if name != "disable" and value not in ready:
            raise RegistryError("prize is not admitted for local execution")
    path = state_root(root) / "control.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock"):
        control = load_control(root, cached)
        selected = set(control["enabled_ids"])
        if enable is not None:
            selected.add(enable)
        if disable is not None:
            selected.discard(disable)
            if control.get("next_id") == disable:
                control["next_id"] = None
        if clear_next:
            control["next_id"] = None
        if next_id is not None:
            selected.add(next_id)
            control["next_id"] = next_id
        control.update(enabled_ids=sorted(selected), updated_at=_utc_now(now))
        atomic_json(path, control)
    return control


def consume_next(root, prize_id, run_id, now=None):
    root = Path(root).resolve()
    path = state_root(root) / "control.json"
    with FileLock(str(path) + ".lock"):
        control = load_control(root, load_snapshot(root))
        if control.get("next_id") != prize_id:
            return control
        control["next_id"] = None
        control["last_choice"] = {"prize_id": prize_id, "run_id": str(run_id)[:128], "consumed_at": _utc_now(now)}
        control["updated_at"] = _utc_now(now)
        atomic_json(path, control)
    return control


def registry_view(root=ROOT):
    """The dashboard payload: snapshot prizes plus enable/next state and the last refresh result."""
    root = Path(root)
    cached = load_snapshot(root)
    refresh = read_json(state_root(root) / "refresh-status.json")
    if not isinstance(refresh, dict):
        refresh = {"status": "unavailable", "prize_count": 0, "ready_count": 0}
    if not cached:
        return {
            "source": None,
            "registry_hash": None,
            "prizes": [],
            "control": load_control(root),
            "refresh": refresh,
        }
    control = load_control(root, cached)
    enabled = set(control["enabled_ids"])
    prizes = []
    for prize in cached["prizes"]:
        copy = json.loads(json.dumps(prize))
        copy["enabled"] = copy["id"] in enabled
        copy["chosen_next"] = copy["id"] == control.get("next_id")
        prizes.append(copy)
    return {
        "source": cached["source"],
        "registry_hash": cached["registry_hash"],
        "prizes": prizes,
        "control": control,
        "refresh": refresh,
    }


def update_status(
    path,
    prize_id,
    *,
    status=None,
    status_confidence=None,
    last_verified=None,
    observed,
    url,
    by="operator",
    note=None,
    now=None,
):
    """Record a re-checked prize status. Evidence is appended; nothing is ever deleted."""
    path = Path(path)
    _slug(prize_id, "prize_id")
    observed = _text(observed, "observed", 800)
    url = _url(url, "url")
    by = _text(by, "by", 60)
    note = _text(note, "note", 400, required=False) or ""
    if status is not None:
        status = _enum(status, "status", STATUSES)
    if status_confidence is not None:
        status_confidence = _enum(status_confidence, "status_confidence", CONFIDENCES)
    date = _date(last_verified, "last_verified") if last_verified else _utc_date(now)
    with FileLock(str(path) + ".lock"):
        load_registry(path)  # refuse to touch a file that does not already validate
        document = json.loads(path.read_bytes().decode("utf-8"))
        entries = document["prizes"]
        index = next((i for i, entry in enumerate(entries) if entry.get("id") == prize_id), None)
        if index is None:
            raise RegistryError(f"unknown prize id: {prize_id}")
        entry = json.loads(json.dumps(entries[index]))
        history = list(entry.get("history") or [])
        for field, value in (
            ("status", status),
            ("status_confidence", status_confidence),
            ("last_verified", date),
        ):
            if value is None or entry.get(field) == value:
                continue
            history.append(
                {"date": date, "field": field, "from": entry.get(field), "to": value, "by": by, "note": note}
            )
            entry[field] = value
        evidence = list(entry.get("evidence") or [])
        evidence.append({"date": date, "url": url, "observed": observed, "file": None})
        if len(evidence) > MAX_EVIDENCE or len(history) > MAX_HISTORY:
            raise RegistryError("prize evidence or history would exceed its limit; archive the entry first")
        entry["evidence"] = evidence
        entry["history"] = history
        entries[index] = entry
        document["updated_at"] = date
        validate_registry(document)
        atomic_json(path, document)
    return validate_prize(entry)


def _source_keyword(prize):
    """The most distinctive token of target_definition: what a live page should still contain.

    Names that identify an instance carry a digit ("ECCp-131", "SHA-256", "enwik9"), so the longest
    token containing one beats the longest word.
    """
    tokens = TOKEN_RE.findall(prize.get("target_definition") or "")
    if not tokens:
        return None
    numbered = [token for token in tokens if any(character.isdigit() for character in token)]
    return max(numbered or tokens, key=len)


def _fetch_source(url, timeout=SOURCE_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - registry URLs only
            return response.status, response.read(MAX_SOURCE_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"error: {exc}"


def check_sources(root=ROOT, *, opener=None, timeout=SOURCE_TIMEOUT, now=None):
    """Fetch every registered source_url and report its HTTP status. Never edits data/prizes.json."""
    root = Path(root).resolve()
    fetch = opener or _fetch_source
    document = load_registry(root / "data" / "prizes.json")
    rows = []
    for prize in document["prizes"]:
        keyword = _source_keyword(prize)
        status, body = fetch(prize["source_url"], timeout)
        rows.append(
            {
                "id": prize["id"],
                "url": prize["source_url"],
                "http_status": status,
                "keyword": keyword,
                "keyword_present": bool(keyword) and keyword.lower() in (body or "").lower(),
                "bytes_read": len(body or ""),
            }
        )
    report = {"schema_version": 1, "checked_at": _utc_now(now), "results": rows}
    atomic_json(state_root(root) / "source-check.json", report)
    return report


def _board(root):
    view = registry_view(root)
    return [
        {
            "id": prize["id"],
            "name": prize["name"],
            "status": prize["status"],
            "confidence": prize["status_confidence"],
            "advertised_prize": prize["advertised_prize"],
            "estimated_usd": prize["estimated_usd"],
            "admission": prize["admission"],
            "plugin": prize["plugin"],
            "research_priority": prize["research_priority"],
            "enabled": prize["enabled"],
        }
        for prize in view["prizes"]
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect the local prize registry without claiming anything")
    parser.add_argument("command", choices=("list", "show", "set-status", "refresh", "check-sources"))
    parser.add_argument("prize_id", nargs="?", default=None)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--status", default=None)
    parser.add_argument("--confidence", default=None)
    parser.add_argument("--url", default=None)
    parser.add_argument("--observed", default=None)
    parser.add_argument("--by", default="operator")
    parser.add_argument("--note", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.command == "refresh":
        result = refresh_registry(root)
        output = {"refresh": result["refresh"], "retained_snapshot": result["snapshot"] is not None}
    elif args.command == "list":
        output = {"prizes": _board(root)}
    elif args.command == "show":
        if not args.prize_id:
            parser.error("show needs a prize id")
        prizes = {prize["id"]: prize for prize in registry_view(root)["prizes"]}
        if args.prize_id not in prizes:
            parser.error(f"unknown prize id: {args.prize_id}")
        output = prizes[args.prize_id]
    elif args.command == "check-sources":
        output = check_sources(root)
    else:
        if not args.prize_id or not args.status or not args.url or not args.observed:
            parser.error("set-status needs a prize id and --status, --url and --observed")
        output = update_status(
            root / "data" / "prizes.json",
            args.prize_id,
            status=args.status,
            status_confidence=args.confidence,
            observed=args.observed,
            url=args.url,
            by=args.by,
            note=args.note,
        )
    print(json.dumps(output, indent=2, allow_nan=False))
    return 0 if output.get("refresh", {}).get("status") in (None, "fresh", "stale") else 1


if __name__ == "__main__":
    raise SystemExit(main())
