"""Deterministic, development-only solver-program island evolution."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

SCHEMA_VERSION = 1
ISLAND_COUNT = 3
ISLAND_CAPACITY = 3

_PARENT_KEYS = (
    "candidate_path",
    "candidate_hash",
    "fingerprint",
    "idea",
    "iteration",
    "provider",
    "selection_gain",
    "median_gain",
    "valid",
)


def _score(parent):
    value = parent.get("selection_gain")
    if value is None:
        value = parent.get("median_gain")
    return float("-inf") if value is None else float(value)


def _ordered(parents):
    return sorted(parents, key=lambda item: (-_score(item), item["candidate_hash"]))


def _bounded(parents):
    distinct = {}
    for parent in _ordered(parents):
        distinct.setdefault(parent["candidate_hash"], parent)
    return list(distinct.values())[:ISLAND_CAPACITY]


def parent_from_record(record):
    """Return a prompt-safe parent reference after an independent development evaluation."""
    if record.get("development_verified") is not True or record.get("valid") is not True:
        return None
    path = record.get("candidate_path")
    digest = record.get("candidate_hash")
    fingerprint = record.get("fingerprint")
    if (
        not isinstance(path, str)
        or not path
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        return None
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        return None
    for key in ("selection_gain", "median_gain"):
        value = record.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
        ):
            return None
    parent = {key: record.get(key) for key in _PARENT_KEYS}
    parent["development_verified"] = True
    return parent


def new_population(incumbent):
    """Seed three islands with one run-verified frozen incumbent."""
    parent = parent_from_record(incumbent)
    if parent is None:
        raise ValueError("island evolution requires a development-verified incumbent")
    return {
        "schema_version": SCHEMA_VERSION,
        "island_count": ISLAND_COUNT,
        "capacity_per_island": ISLAND_CAPACITY,
        "islands": [{"id": index, "parents": [dict(parent)]} for index in range(ISLAND_COUNT)],
    }


def plan(population, iteration):
    """Choose one frozen parent plan; callers reuse it for every paired provider."""
    island_id = iteration % ISLAND_COUNT
    parents = _ordered(population["islands"][island_id]["parents"])
    if not parents:
        raise ValueError("selected island has no verified parent")
    crossover = iteration % 2 == 1 and len(parents) >= 2
    selected = parents[:2] if crossover else parents[:1]
    # The crossover prompt orders the weaker parent first and elite second.
    if crossover:
        selected = list(reversed(selected))
    return {
        "iteration": iteration,
        "island": island_id,
        "operator": "crossover" if crossover else "mutation",
        "parent_hashes": [parent["candidate_hash"] for parent in selected],
        "parent_paths": [parent["candidate_path"] for parent in selected],
    }


def admit(population, island_id, record):
    """Admit one development-verified program and share the global elite once."""
    parent = parent_from_record(record)
    if parent is None or isinstance(island_id, bool) or island_id not in range(ISLAND_COUNT):
        return False
    island = population["islands"][island_id]
    island["parents"] = _bounded([*island["parents"], parent])
    elite = _ordered(parent for item in population["islands"] for parent in item["parents"])[0]
    destination = population["islands"][(island_id + 1) % ISLAND_COUNT]
    destination["parents"] = _bounded([*destination["parents"], elite])
    return True


def _validated_solver_path(root, relative_value, run_dir=None):
    root_path = Path(root).resolve()
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("island parent path leaves the checkout")
    path = (root_path / relative).resolve()
    try:
        path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("island parent path leaves the checkout") from exc
    if run_dir is not None:
        run_path = Path(run_dir).resolve()
        try:
            run_relative = path.relative_to(run_path)
        except ValueError as exc:
            raise ValueError("island parent path leaves the current run") from exc
        allowed = run_relative == Path("legacy_incumbent.py") or (
            len(run_relative.parts) == 3
            and run_relative.parts[0] == "candidates"
            and run_relative.parts[2] == "solver.py"
        )
        if not allowed:
            raise ValueError("island parent path is not a current-run solver")
    return path


def validate_population(population, root, run_dir=None):
    """Validate bounds, development provenance, containment, and current file hashes."""
    if not isinstance(population, dict) or population.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid island population schema")
    if population.get("island_count") != ISLAND_COUNT or population.get("capacity_per_island") != ISLAND_CAPACITY:
        raise ValueError("island population limits changed")
    islands = population.get("islands")
    if not isinstance(islands, list) or [item.get("id") for item in islands if isinstance(item, dict)] != list(
        range(ISLAND_COUNT)
    ):
        raise ValueError("island population identifiers are invalid")
    for island in islands:
        parents = island.get("parents")
        if not isinstance(parents, list) or not 1 <= len(parents) <= ISLAND_CAPACITY:
            raise ValueError("island population occupancy is invalid")
        hashes = set()
        for parent in parents:
            if not isinstance(parent, dict) or parent_from_record(parent) != parent:
                raise ValueError("island parent is not development verified")
            digest = parent["candidate_hash"]
            if digest in hashes:
                raise ValueError("island parent hashes must be distinct")
            hashes.add(digest)
            path = _validated_solver_path(root, parent["candidate_path"], run_dir)
            if not path.is_file():
                raise ValueError("island parent file is unavailable")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != digest:
                raise ValueError("island parent file does not match its hash")
            for key in ("selection_gain", "median_gain"):
                value = parent.get(key)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                ):
                    raise ValueError("island parent score is invalid")
    return population


def validate_plan_files(plan_record, root, run_dir):
    """Bind an ancestry record to solver files inside its own run."""
    if not isinstance(plan_record, dict):
        raise ValueError("island parent plan is invalid")
    iteration = plan_record.get("iteration")
    island_id = plan_record.get("island")
    operator = plan_record.get("operator")
    hashes = plan_record.get("parent_hashes")
    paths = plan_record.get("parent_paths")
    if (
        isinstance(iteration, bool)
        or not isinstance(iteration, int)
        or island_id != iteration % ISLAND_COUNT
        or operator not in ("mutation", "crossover")
        or not isinstance(hashes, list)
        or not isinstance(paths, list)
        or len(hashes) != len(paths)
        or len(hashes) != (2 if operator == "crossover" else 1)
        or len(set(hashes)) != len(hashes)
    ):
        raise ValueError("island parent plan is invalid")
    for digest, relative in zip(hashes, paths):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("island parent plan hash is invalid")
        path = _validated_solver_path(root, relative, run_dir)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("island parent plan file does not match its hash")
    return plan_record


def validate_membership(population, candidate_records, incumbent_path, incumbent_hash):
    """Exclude population entries that were not verified in this run."""
    known = {(incumbent_hash, incumbent_path)}
    for record in candidate_records:
        parent = parent_from_record(record)
        if parent is not None:
            known.add((parent["candidate_hash"], parent["candidate_path"]))
    if any(
        (parent["candidate_hash"], parent["candidate_path"]) not in known
        for island in population["islands"]
        for parent in island["parents"]
    ):
        raise ValueError("island population contains an unknown or unverified parent")
    return population


def validate_plan(plan_record, population):
    """Reject resumed plans whose parents are absent from the recorded island."""
    if not isinstance(plan_record, dict):
        raise ValueError("island parent plan is invalid")
    iteration = plan_record.get("iteration")
    island_id = plan_record.get("island")
    operator = plan_record.get("operator")
    hashes = plan_record.get("parent_hashes")
    paths = plan_record.get("parent_paths")
    if (
        isinstance(iteration, bool)
        or not isinstance(iteration, int)
        or island_id != iteration % ISLAND_COUNT
        or operator not in ("mutation", "crossover")
        or not isinstance(hashes, list)
        or not isinstance(paths, list)
        or len(hashes) != len(paths)
        or len(hashes) != (2 if operator == "crossover" else 1)
        or len(set(hashes)) != len(hashes)
    ):
        raise ValueError("island parent plan is invalid")
    available = {
        parent["candidate_hash"]: parent["candidate_path"] for parent in population["islands"][island_id]["parents"]
    }
    if any(available.get(digest) != path for digest, path in zip(hashes, paths)):
        raise ValueError("island parent plan is outside the recorded population")
    return plan_record
