"""Validate ARC-AGI-N catalogue cards and bind reviewed cards to local research.

Upstream card text is stored only as quoted, untrusted display data. Executable
mission briefs come from the reviewed bindings below and can target only an
existing discovery-loop plugin, baseline and verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from research_state import FileLock, atomic_json, read_json


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT.parent / "arc-agi-n"
DEFAULT_STATE = ROOT / "runs" / "arc"
SOURCE_REPOSITORY = "https://github.com/yorkeccak/arc-agi-n"
MAX_FILES = 500
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_RE = re.compile(r"[a-f0-9]{64}\Z")
GIT_REV_RE = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\Z")
FIELDS = {"Mathematics", "Physics", "Computer science", "Biology", "Chemistry"}
SCALES = {"foothold", "frontier", "monument"}
READINESS = {"agent-ready", "hybrid", "physical-world"}
SOURCE_KINDS = {"primary", "survey", "index"}


# Every string here is locally reviewed. None is copied from an upstream prompt.
ADMISSIONS = {
    "cvrp-budgeted-routing": {
        "plugin": "cvrp",
        "baseline": "best-cvrp/solver.py",
        "verifier": "problems/cvrp/verify.py",
        "beneficiary": (
            "More reliable routing heuristics can reduce distance and planning time in bounded fleet, "
            "public-service delivery and disaster-response benchmarks."
        ),
        "bounded_hypothesis": (
            "A concrete change to the current CVRP solver can improve the existing development benchmark "
            "without losing feasibility on an independent confirmation split."
        ),
        "resources": "The repository's CVRP plugin, incumbent solver, local benchmark instances and isolated runner.",
        "split": (
            "Generate and tune only on the plugin manifest's development targets. Keep validation, "
            "confirmation and release-holdout targets out of prompts."
        ),
        "success_criterion": (
            "Beat the frozen incumbent by the slot's paired minimum-effect threshold with zero confirmation "
            "failures; otherwise record a bounded negative result."
        ),
        "max_minutes": 210,
        "max_allowance": 40.0,
        "max_per_call_allowance": 2.0,
    },
    "mip-budgeted-primal-heuristics": {
        "plugin": "miplib_heur",
        "baseline": "best-miplib_heur/solver.py",
        "verifier": "problems/miplib_heur/verify.py",
        "beneficiary": (
            "Better bounded primal heuristics can produce useful feasible plans sooner in scheduling, "
            "allocation and infrastructure optimization benchmarks."
        ),
        "bounded_hypothesis": (
            "A concrete change to the current MIP heuristic can improve the existing development benchmark "
            "without losing feasibility on an independent confirmation split."
        ),
        "resources": "The repository's MIPLIB heuristic plugin, incumbent solver, local instances and isolated runner.",
        "split": (
            "Generate and tune only on the plugin manifest's development targets. Keep validation, "
            "confirmation and release-holdout targets out of prompts."
        ),
        "success_criterion": (
            "Beat the frozen incumbent by the slot's paired minimum-effect threshold with zero confirmation "
            "failures; otherwise record a bounded negative result."
        ),
        "max_minutes": 210,
        "max_allowance": 40.0,
        "max_per_call_allowance": 2.0,
    },
    "matrix-multiplication": {
        "plugin": "matrix_multiplication",
        "baseline": "best-matrix_multiplication/solver.py",
        "verifier": "problems/matrix_multiplication/verify.py",
        "beneficiary": (
            "Faster exact matrix-multiplication algorithms reduce the cost of scientific computing, machine "
            "learning training, and graphics workloads that all bottom out at matmul."
        ),
        "bounded_hypothesis": (
            "A concrete search-strategy change can lower the verified rank on the development targets "
            "without losing exact feasibility under the independent tensor-identity check."
        ),
        "resources": "The repository's matrix-multiplication plugin, seed solver, exact verifier and local runner.",
        "split": (
            "Generate and tune only on the plugin manifest's development targets (n=2,3,4). n=2 is a "
            "calibration target: rank 7 is proven optimal and cannot be beaten."
        ),
        "success_criterion": (
            "Beat the frozen best-known rank on n=3 or n=4 with zero confirmation failures on the exact "
            "verifier; otherwise record a bounded negative result."
        ),
        "max_minutes": 210,
        "max_allowance": 40.0,
        "max_per_call_allowance": 2.0,
    },
}


class CatalogueError(ValueError):
    """The source catalogue or a mission binding is unsafe or malformed."""


def _utc_now(now=None):
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _object(value, name):
    if not isinstance(value, dict):
        raise CatalogueError(f"{name} must be an object")
    return value


def _text(value, name, limit, *, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise CatalogueError(f"{name} must be text")
    clean = " ".join(value.split())
    if required and not clean:
        raise CatalogueError(f"{name} cannot be empty")
    if len(clean) > limit:
        raise CatalogueError(f"{name} exceeds {limit} characters")
    if any(ord(character) < 32 for character in clean):
        raise CatalogueError(f"{name} contains control characters")
    return clean


def _string_list(value, name, *, limit=24, item_limit=120):
    if not isinstance(value, list) or len(value) > limit:
        raise CatalogueError(f"{name} must contain at most {limit} text items")
    return [_text(item, f"{name} item", item_limit) for item in value]


def _https_url(value, name):
    clean = _text(value, name, 2048)
    parsed = urlsplit(clean)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CatalogueError(f"{name} must be a public HTTPS URL without credentials")
    return clean


def _source(value, index):
    source = _object(value, f"sources[{index}]")
    kind = _text(source.get("kind"), f"sources[{index}].kind", 16)
    if kind not in SOURCE_KINDS:
        raise CatalogueError(f"sources[{index}].kind is unsupported")
    result = {
        "title": _text(source.get("title"), f"sources[{index}].title", 300),
        "url": _https_url(source.get("url"), f"sources[{index}].url"),
        "kind": kind,
    }
    for key, limit in (("passage", 800), ("publishedAt", 32), ("sourceType", 80), ("doi", 160)):
        if source.get(key) is not None:
            result[key] = _text(source[key], f"sources[{index}].{key}", limit)
    return result


def validate_card(value, filename=None):
    card = _object(value, "card")
    problem_id = _text(card.get("id"), "id", 80)
    if not ID_RE.fullmatch(problem_id):
        raise CatalogueError("id must be a lowercase hyphenated slug")
    if filename is not None and filename != f"{problem_id}.json":
        raise CatalogueError("card filename must match its id")
    field = _text(card.get("field"), "field", 40)
    if field not in FIELDS:
        raise CatalogueError("field is unsupported")
    scale = _text(card.get("scale"), "scale", 20)
    if scale not in SCALES:
        raise CatalogueError("scale is unsupported")
    readiness = card.get("agentReadiness")
    if readiness is not None:
        readiness = _text(readiness, "agentReadiness", 24)
        if readiness not in READINESS:
            raise CatalogueError("agentReadiness is unsupported")
    score = card.get("agentFit")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        raise CatalogueError("agentFit must be a number from 0 to 100")
    sources = card.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 12:
        raise CatalogueError("sources must contain 1 to 12 entries")
    result = {
        "id": problem_id,
        "title": _text(card.get("title"), "title", 200),
        "field": field,
        "subfield": _text(card.get("subfield"), "subfield", 120),
        "summary": _text(card.get("summary"), "summary", 600),
        "statement": _text(card.get("statement"), "statement", 1200),
        "why_open": _text(card.get("whyOpen"), "whyOpen", 1200),
        "smallest_step": _text(card.get("smallestStep"), "smallestStep", 1000),
        "agent_fit": float(score),
        "scale": scale,
        "tags": _string_list(card.get("tags"), "tags"),
        "tools": _string_list(card.get("tools"), "tools"),
        "sources": [_source(source, index) for index, source in enumerate(sources)],
        "agent_readiness": readiness,
        "execution_resources": _text(card.get("executionResources"), "executionResources", 800, required=False),
        "success_criterion": _text(card.get("successCriterion"), "successCriterion", 800, required=False),
        "source_reviewed_at": _text(card.get("verified"), "verified", 40),
        "content_classification": "untrusted_quoted_source",
        "literature_status": {
            "independently_checked_by_discovery_loop": False,
            "note": "The source card was imported as written. Current literature status has not been independently checked.",
        },
    }
    admission = ADMISSIONS.get(problem_id)
    result["admission"] = (
        {"status": "ready", **admission}
        if admission
        else {
            "status": "needs_setup",
            "reason": "No reviewed local plugin, baseline, verifier and bounded split are registered for this card.",
        }
    )
    return result


def _git_provenance(source_root):
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CatalogueError("source checkout revision is unavailable") from exc
    revision = result.stdout.strip().lower()
    if not GIT_REV_RE.fullmatch(revision):
        raise CatalogueError("source checkout revision is invalid")
    try:
        status = subprocess.run(
            ["git", "-C", str(source_root), "status", "--porcelain", "--", "data/atlas"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CatalogueError("source checkout worktree status is unavailable") from exc
    return revision, bool(status.stdout.strip())


def import_catalogue(source_root=DEFAULT_SOURCE, *, revision=None, now=None):
    source_root = Path(source_root).resolve()
    atlas = source_root / "data" / "atlas"
    if not atlas.is_dir() or atlas.is_symlink():
        raise CatalogueError("source data/atlas directory is unavailable or symbolic")
    files = sorted(atlas.glob("*.json"))
    if not files or len(files) > MAX_FILES:
        raise CatalogueError(f"catalogue must contain 1 to {MAX_FILES} JSON cards")
    problems = []
    seen = set()
    total_bytes = 0
    raw_hasher = hashlib.sha256()
    for path in files:
        if path.is_symlink() or path.parent != atlas or not ID_RE.fullmatch(path.stem):
            raise CatalogueError("catalogue filenames must be direct lowercase slug JSON files")
        size = path.stat().st_size
        if size <= 0 or size > MAX_FILE_BYTES:
            raise CatalogueError(f"{path.name} exceeds the card size limit")
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise CatalogueError("catalogue exceeds the total size limit")
        try:
            raw = path.read_bytes()
            if len(raw) != size:
                raise CatalogueError(f"{path.name} changed during import")
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CatalogueError(f"{path.name} is not valid UTF-8 JSON") from exc
        raw_hasher.update(path.name.encode("utf-8"))
        raw_hasher.update(b"\0")
        raw_hasher.update(raw)
        raw_hasher.update(b"\0")
        card = validate_card(value, path.name)
        if card["id"] in seen:
            raise CatalogueError(f"duplicate card id: {card['id']}")
        seen.add(card["id"])
        problems.append(card)
    if revision is None:
        revision, worktree_dirty = _git_provenance(source_root)
    else:
        revision, worktree_dirty = revision.lower(), False
    if not GIT_REV_RE.fullmatch(revision):
        raise CatalogueError("revision must be a full lowercase git SHA")
    payload = {
        "schema_version": 1,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "revision": revision,
            "worktree_dirty": worktree_dirty,
            "subdirectory": "data/atlas",
            "imported_at": _utc_now(now),
            "file_count": len(problems),
            "raw_source_hash": raw_hasher.hexdigest(),
            "content_classification": "untrusted_quoted_source",
        },
        "problems": problems,
    }
    payload["catalogue_hash"] = _catalogue_digest(payload)
    return payload


def _catalogue_digest(snapshot):
    payload = json.loads(json.dumps(snapshot))
    payload.pop("catalogue_hash", None)
    source = payload.get("source")
    if isinstance(source, dict):
        source.pop("imported_at", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_snapshot(value):
    snapshot = _object(value, "snapshot")
    if snapshot.get("schema_version") != 1:
        raise CatalogueError("snapshot schema version is unsupported")
    source = _object(snapshot.get("source"), "snapshot source")
    if source.get("repository") != SOURCE_REPOSITORY or source.get("subdirectory") != "data/atlas":
        raise CatalogueError("snapshot source identity is invalid")
    if not isinstance(source.get("revision"), str) or not GIT_REV_RE.fullmatch(source["revision"]):
        raise CatalogueError("snapshot source revision is invalid")
    if not isinstance(source.get("worktree_dirty"), bool):
        raise CatalogueError("snapshot worktree status is invalid")
    if not isinstance(source.get("raw_source_hash"), str) or not SHA256_RE.fullmatch(source["raw_source_hash"]):
        raise CatalogueError("snapshot raw source hash is invalid")
    problems = snapshot.get("problems")
    if not isinstance(problems, list) or not 1 <= len(problems) <= MAX_FILES:
        raise CatalogueError("snapshot problem list is invalid")
    if source.get("file_count") != len(problems):
        raise CatalogueError("snapshot file count does not match")
    seen = set()
    for problem in problems:
        problem = _object(problem, "snapshot problem")
        problem_id = problem.get("id")
        if not isinstance(problem_id, str) or not ID_RE.fullmatch(problem_id) or problem_id in seen:
            raise CatalogueError("snapshot problem id is invalid or duplicated")
        seen.add(problem_id)
        if problem.get("content_classification") != "untrusted_quoted_source" or "starterPrompt" in problem:
            raise CatalogueError("snapshot content classification is invalid")
        sources = problem.get("sources")
        if not isinstance(sources, list) or not 1 <= len(sources) <= 12:
            raise CatalogueError("snapshot source list is invalid")
        for index, item in enumerate(sources):
            _source(item, index)
        expected = ADMISSIONS.get(problem_id)
        admission = problem.get("admission")
        if expected:
            if admission != {"status": "ready", **expected}:
                raise CatalogueError("snapshot reviewed admission was modified")
        elif not isinstance(admission, dict) or admission.get("status") != "needs_setup":
            raise CatalogueError("snapshot unsupported card was promoted without review")
    digest = snapshot.get("catalogue_hash")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) or digest != _catalogue_digest(snapshot):
        raise CatalogueError("snapshot catalogue hash does not match its content")
    return json.loads(json.dumps(snapshot))


def refresh_catalogue(source_root=DEFAULT_SOURCE, state_root=DEFAULT_STATE, *, revision=None, now=None):
    state_root = Path(state_root).resolve()
    snapshot_path = state_root / "catalogue.json"
    status_path = state_root / "refresh-status.json"
    state_root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(status_path) + ".lock"):
        try:
            previous = validate_snapshot(read_json(snapshot_path))
        except (CatalogueError, TypeError, ValueError):
            previous = None
        try:
            snapshot = import_catalogue(source_root, revision=revision, now=now)
            atomic_json(snapshot_path, snapshot)
            status = {
                "schema_version": 1,
                "status": "fresh",
                "attempted_at": _utc_now(now),
                "catalogue_hash": snapshot["catalogue_hash"],
                "revision": snapshot["source"]["revision"],
                "problem_count": len(snapshot["problems"]),
            }
        except (CatalogueError, OSError, ValueError) as exc:
            snapshot = previous if isinstance(previous, dict) else None
            status = {
                "schema_version": 1,
                "status": "stale" if snapshot else "unavailable",
                "attempted_at": _utc_now(now),
                "error": str(exc)[:300],
                "catalogue_hash": snapshot.get("catalogue_hash") if snapshot else None,
                "revision": (snapshot.get("source") or {}).get("revision") if snapshot else None,
                "problem_count": len(snapshot.get("problems", [])) if snapshot else 0,
            }
        atomic_json(status_path, status)
    return {"snapshot": snapshot, "refresh": status}


def load_catalogue(state_root=DEFAULT_STATE):
    snapshot = read_json(Path(state_root) / "catalogue.json")
    try:
        return validate_snapshot(snapshot)
    except (CatalogueError, TypeError, ValueError):
        return None


def _ready_ids(snapshot):
    if not isinstance(snapshot, dict):
        return []
    return sorted(
        problem["id"]
        for problem in snapshot.get("problems", [])
        if isinstance(problem, dict) and (problem.get("admission") or {}).get("status") == "ready"
    )


def load_control(state_root=DEFAULT_STATE, snapshot=None):
    state_root = Path(state_root)
    control = read_json(state_root / "control.json")
    ready = _ready_ids(snapshot)
    if not isinstance(control, dict) or control.get("schema_version") != 1:
        return {"schema_version": 1, "enabled_ids": ready, "next_id": None, "updated_at": None}
    enabled = sorted({item for item in control.get("enabled_ids", []) if item in ready})
    next_id = control.get("next_id") if control.get("next_id") in enabled else None
    return {**control, "schema_version": 1, "enabled_ids": enabled, "next_id": next_id}


def update_control(problem_id, *, enabled=None, choose_next=False, state_root=DEFAULT_STATE, now=None):
    if not isinstance(problem_id, str) or not ID_RE.fullmatch(problem_id):
        raise CatalogueError("problem_id must be a lowercase hyphenated slug")
    if (enabled is None) == (choose_next is False):
        raise CatalogueError("set exactly one of enabled or choose_next")
    if enabled is not None and not isinstance(enabled, bool):
        raise CatalogueError("enabled must be true or false")
    state_root = Path(state_root).resolve()
    snapshot = load_catalogue(state_root)
    ready = _ready_ids(snapshot)
    if problem_id not in ready:
        raise CatalogueError("problem is not admitted for local execution")
    path = state_root / "control.json"
    state_root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock"):
        control = load_control(state_root, snapshot)
        selected = set(control["enabled_ids"])
        if enabled is True:
            selected.add(problem_id)
        elif enabled is False:
            selected.discard(problem_id)
            if control.get("next_id") == problem_id:
                control["next_id"] = None
        else:
            selected.add(problem_id)
            control["next_id"] = problem_id
        control.update(enabled_ids=sorted(selected), updated_at=_utc_now(now))
        atomic_json(path, control)
    return control


def consume_next(state_root, problem_id, run_id, now=None):
    state_root = Path(state_root).resolve()
    path = state_root / "control.json"
    with FileLock(str(path) + ".lock"):
        snapshot = load_catalogue(state_root)
        control = load_control(state_root, snapshot)
        if control.get("next_id") != problem_id:
            return control
        control["next_id"] = None
        control["last_choice"] = {"problem_id": problem_id, "run_id": str(run_id)[:128], "consumed_at": _utc_now(now)}
        control["updated_at"] = _utc_now(now)
        atomic_json(path, control)
    return control


def catalogue_view(state_root=DEFAULT_STATE):
    state_root = Path(state_root)
    snapshot = load_catalogue(state_root)
    refresh = read_json(state_root / "refresh-status.json")
    if not isinstance(refresh, dict):
        refresh = {"status": "unavailable", "problem_count": 0}
    if not snapshot:
        return {
            "source": None,
            "catalogue_hash": None,
            "problems": [],
            "control": load_control(state_root),
            "refresh": refresh,
        }
    control = load_control(state_root, snapshot)
    enabled = set(control["enabled_ids"])
    problems = []
    for problem in snapshot["problems"]:
        copy = json.loads(json.dumps(problem))
        copy["enabled"] = copy["id"] in enabled
        copy["chosen_next"] = copy["id"] == control.get("next_id")
        problems.append(copy)
    return {
        "source": snapshot["source"],
        "catalogue_hash": snapshot["catalogue_hash"],
        "problems": problems,
        "control": control,
        "refresh": refresh,
    }


def mission_plan(snapshot, control, slots):
    if not isinstance(snapshot, dict):
        return {}
    enabled = set((control or {}).get("enabled_ids", []))
    next_id = (control or {}).get("next_id")
    by_plugin = {}
    for problem in snapshot.get("problems", []):
        admission = problem.get("admission") or {}
        if problem.get("id") not in enabled or admission.get("status") != "ready":
            continue
        plugin = admission.get("plugin")
        if plugin not in by_plugin or problem.get("id") == next_id:
            by_plugin[plugin] = problem
    planned = {}
    for slot in slots:
        if slot.get("kind") != "research" or slot.get("problem") not in by_plugin:
            continue
        problem = by_plugin[slot["problem"]]
        admission = problem["admission"]
        minutes = float(slot.get("minutes", 0))
        allowance = float(slot.get("effective_slot_budget_usd", slot.get("slot_budget_usd", 0)))
        per_call = float(slot.get("per_call_budget_usd", 0))
        if (
            minutes > admission["max_minutes"]
            or allowance > admission["max_allowance"]
            or per_call > admission["max_per_call_allowance"]
        ):
            continue
        planned[slot["id"]] = {
            "schema_version": 1,
            "source_problem_id": problem["id"],
            "source_title": problem["title"],
            "source_repository": snapshot["source"]["repository"],
            "source_revision": snapshot["source"]["revision"],
            "catalogue_hash": snapshot["catalogue_hash"],
            "source_reviewed_at": problem["source_reviewed_at"],
            "literature_status": problem["literature_status"],
            "plugin": admission["plugin"],
            "baseline": admission["baseline"],
            "verifier": admission["verifier"],
            "beneficiary": admission["beneficiary"],
            "bounded_hypothesis": admission["bounded_hypothesis"],
            "resources": admission["resources"],
            "development_confirmation_split": admission["split"],
            "success_criterion": admission["success_criterion"],
            "source_urls": [source["url"] for source in problem["sources"]],
            "budget": {
                "minutes": minutes,
                "allowance": allowance,
                "per_call_allowance": per_call,
                "seed_count": int(slot.get("seed_count", 1)),
                "minimum_effect": float(slot.get("min_effect", 0.0)),
            },
            "content_policy": "Only this reviewed brief is executable; source card prose is excluded from prompts.",
        }
    return planned


def mission_selection(snapshot, control, slots):
    planned = mission_plan(snapshot, control, slots)
    if not isinstance(snapshot, dict):
        return {"missions": planned, "skip_slot_ids": []}
    enabled = set((control or {}).get("enabled_ids", []))
    ready_by_plugin = {}
    for problem in snapshot.get("problems", []):
        admission = problem.get("admission") or {}
        if admission.get("status") == "ready":
            ready_by_plugin.setdefault(admission.get("plugin"), set()).add(problem.get("id"))
    skips = [
        slot["id"]
        for slot in slots
        if slot.get("kind") == "research"
        and slot.get("problem") in ready_by_plugin
        and not (ready_by_plugin[slot["problem"]] & enabled)
    ]
    return {"missions": planned, "skip_slot_ids": skips}


def validate_mission(value, expected_plugin=None):
    mission = _object(value, "mission")
    if mission.get("schema_version") != 1 or mission.get("source_repository") != SOURCE_REPOSITORY:
        raise CatalogueError("mission source identity is invalid")
    problem_id = mission.get("source_problem_id")
    admission = ADMISSIONS.get(problem_id)
    if not admission or mission.get("plugin") != admission["plugin"]:
        raise CatalogueError("mission does not match a reviewed admission")
    if expected_plugin is not None and mission["plugin"] != expected_plugin:
        raise CatalogueError("mission plugin does not match the research problem")
    for key in (
        "baseline",
        "verifier",
        "beneficiary",
        "bounded_hypothesis",
        "resources",
        "development_confirmation_split",
        "success_criterion",
    ):
        if mission.get(key) != admission[key if key != "development_confirmation_split" else "split"]:
            raise CatalogueError(f"mission {key} does not match the reviewed binding")
    revision = mission.get("source_revision")
    catalogue_hash = mission.get("catalogue_hash")
    if not isinstance(revision, str) or not GIT_REV_RE.fullmatch(revision):
        raise CatalogueError("mission source revision is invalid")
    if not isinstance(catalogue_hash, str) or not SHA256_RE.fullmatch(catalogue_hash):
        raise CatalogueError("mission catalogue hash is invalid")
    source_urls = mission.get("source_urls")
    if not isinstance(source_urls, list) or not 1 <= len(source_urls) <= 12:
        raise CatalogueError("mission source URLs are invalid")
    for index, url in enumerate(source_urls):
        _https_url(url, f"mission source_urls[{index}]")
    if (
        mission.get("content_policy")
        != "Only this reviewed brief is executable; source card prose is excluded from prompts."
    ):
        raise CatalogueError("mission content policy is invalid")
    budget = _object(mission.get("budget"), "mission budget")
    numbers = {}
    for key in ("minutes", "allowance", "per_call_allowance", "minimum_effect"):
        value = budget.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise CatalogueError(f"mission budget {key} is invalid")
        numbers[key] = float(value)
    seed_count = budget.get("seed_count")
    if isinstance(seed_count, bool) or not isinstance(seed_count, int) or seed_count < 1:
        raise CatalogueError("mission budget seed_count is invalid")
    if numbers["minutes"] > admission["max_minutes"]:
        raise CatalogueError("mission minutes exceed the reviewed limit")
    if numbers["allowance"] > admission["max_allowance"]:
        raise CatalogueError("mission allowance exceeds the reviewed limit")
    if numbers["per_call_allowance"] > admission["max_per_call_allowance"]:
        raise CatalogueError("mission per-call allowance exceeds the reviewed limit")
    return json.loads(json.dumps(mission))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import a local ARC-AGI-N catalogue without executing it")
    parser.add_argument("command", choices=("refresh", "show"))
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    args = parser.parse_args(argv)
    if args.command == "refresh":
        result = refresh_catalogue(args.source, args.state)
        output = {"refresh": result["refresh"], "retained_snapshot": result["snapshot"] is not None}
    else:
        output = catalogue_view(args.state)
    print(json.dumps(output, indent=2, allow_nan=False))
    return 0 if output.get("refresh", {}).get("status") in (None, "fresh", "stale") else 1


if __name__ == "__main__":
    raise SystemExit(main())
