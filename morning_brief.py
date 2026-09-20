"""Morning brief: last night, every recorded night, and anything awaiting publication.

Everything here is read from files the runner already writes (night.json, evidence.json,
retro.json, mission.json, best-*/scores.json). Nothing is fetched and nothing is sent.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from research_state import read_json

IDEA_CHARS = 260
RETRO_CHARS = 900
# What each plugin's stored ``record`` is. Only a public table earns an external submission; a local
# baseline win is progress, not a claim (see each plugin's module docstring).
RECORD_SOURCE = {
    "circle_packing": ("public", "Packomania csqv best-known packings"),
    "cvrp": ("public", "CVRPLIB X best-known solutions"),
    "miplib": ("public", "MIPLIB 2017 published solutions (ZIB)"),
    "miplib_open": ("public", "MIPLIB 2017 open instances (ZIB)"),
    "matrix_multiplication": ("public", "published rank bounds"),
    "miplib_heur": ("baseline", "HiGHS default on this machine, 60 s"),
    "pglib_opf": ("baseline", "PowerModels.jl + IPOPT listed objective"),
}
VERDICT_RE = re.compile(r"\*\*Does the evidence support a real effect\?\*\*\s*(.+?)(?:\n\s*\n|\Z)", re.S)
PROMISING = {"promising", "promising_unreviewed", "confirmed"}


def _read(path: Path, default: Any) -> Any:
    try:
        value = read_json(path, default)
    except (OSError, ValueError, TypeError):
        return default
    return value if value is not None else default


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _value_of(entry: Any) -> float | None:
    """A stored score entry keeps its number under ``value`` or, for circle packing, ``sum``."""
    if not isinstance(entry, dict):
        return None
    return _number(entry.get("value", entry.get("sum")))


def _trim(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _mission(run_dir: Path, problem: str) -> dict[str, Any]:
    mission = _read(run_dir / problem / "mission.json", {})
    if not isinstance(mission, dict):
        mission = {}
    return {
        "title": mission.get("source_title") or problem.replace("_", " "),
        "hypothesis": mission.get("bounded_hypothesis"),
        "success_criterion": mission.get("success_criterion"),
        "beneficiary": mission.get("beneficiary"),
        "source_problem_id": mission.get("source_problem_id"),
    }


def _candidates(development: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in development.get("candidates", []) if isinstance(development, dict) else []:
        if not isinstance(item, dict):
            continue
        comparison = item.get("comparison") if isinstance(item.get("comparison"), dict) else {}
        gain = _number(item.get("median_gain"))
        if gain is None:
            gain = _number(comparison.get("median_gain"))
        rows.append(
            {
                "iteration": item.get("iteration"),
                "arm": item.get("provider"),
                "model": item.get("actual_model") or item.get("model"),
                "idea": _trim(item.get("idea") or item.get("generation_error") or "", IDEA_CHARS),
                "median_gain": gain,
                # The development gate needs replication and a bound above zero, not a median alone, so the
                # review page shows both rather than a number a reader would take for a settled result.
                "median_lower_bound": _number(comparison.get("median_lower_bound")),
                "seeds": comparison.get("distinct_seeds")
                if isinstance(comparison.get("distinct_seeds"), int)
                else None,
                "status": item.get("status") or "unknown",
                "valid": item.get("valid"),
            }
        )
    return rows


def _confirmation(confirmation: Any) -> dict[str, Any] | None:
    pairs = confirmation.get("pairs") if isinstance(confirmation, dict) else None
    if not isinstance(pairs, list) or not pairs:
        return None
    gains = [_number(pair.get("gain")) for pair in pairs if isinstance(pair, dict)]
    gains = [gain for gain in gains if gain is not None]
    failures = sum(1 for pair in pairs if isinstance(pair, dict) and pair.get("candidate_failed") is True)
    return {
        "pairs": len(pairs),
        "wins": sum(1 for gain in gains if gain > 0),
        "losses": sum(1 for gain in gains if gain < 0),
        "candidate_failures": failures,
        "mean_gain": sum(gains) / len(gains) if gains else None,
        "median_gain": _number(confirmation.get("median_gain")),
    }


def _release_checks(checks: Any) -> dict[str, Any] | None:
    if not isinstance(checks, list) or not checks:
        return None
    passed = sum(1 for item in checks if isinstance(item, dict) and item.get("ok") is True)
    errors = [item.get("error") for item in checks if isinstance(item, dict) and item.get("ok") is not True]
    errors = [error for error in errors if isinstance(error, str)]
    return {"checked": len(checks), "passed": passed, "first_error": errors[0] if errors else None}


def _retro(run_dir: Path, problem: str) -> dict[str, Any] | None:
    retro = _read(run_dir / problem / "retro.json", None)
    if not isinstance(retro, dict):
        return None
    analysis = retro.get("analysis") if isinstance(retro.get("analysis"), str) else ""
    match = VERDICT_RE.search(analysis)
    return {
        "status": retro.get("status"),
        "arm": retro.get("provider"),
        "model": retro.get("model"),
        "verdict": _trim(match.group(1), 600) if match else None,
        "excerpt": _trim(analysis, RETRO_CHARS) if analysis else None,
        "limitations": [item for item in retro.get("limitations", []) if isinstance(item, str)],
    }


def _slot(run_dir: Path, root: Path, slot: dict[str, Any]) -> dict[str, Any]:
    problem = str(slot.get("problem") or "")
    evidence_path = run_dir / problem / "evidence.json"
    evidence = _read(evidence_path, {})
    if not isinstance(evidence, dict):
        evidence = {}
    usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
    development = evidence.get("development") if isinstance(evidence.get("development"), dict) else {}
    candidates = _candidates(development)
    scored = [row for row in candidates if row["median_gain"] is not None and row["valid"] is not False]
    best = max(scored, key=lambda row: row["median_gain"]) if scored else None
    stages = slot.get("stages") if isinstance(slot.get("stages"), dict) else {}
    research_stage = stages.get("research") if isinstance(stages.get("research"), dict) else {}
    return {
        "problem": problem,
        "kind": slot.get("kind"),
        "arm": slot.get("provider"),
        "status": slot.get("status") or evidence.get("status") or "unknown",
        "reason": slot.get("reason"),
        "started_at": slot.get("started_at"),
        "finished_at": slot.get("finished_at"),
        "work_count": research_stage.get("work_count"),
        "mission": _mission(run_dir, problem),
        "iterations": usage.get("iterations"),
        "calls": usage.get("calls"),
        "charged": _number(usage.get("charged")),
        "by_model": usage.get("by_model") if isinstance(usage.get("by_model"), dict) else {},
        "candidates": candidates,
        "best": best,
        "promising": sum(1 for row in candidates if row["status"] in PROMISING),
        "confirmed": evidence.get("confirmed") is True,
        "publishable": evidence.get("publishable") is True,
        "publishable_reason": evidence.get("publishable_reason"),
        "claim_type": evidence.get("claim_type"),
        "candidate_path": evidence.get("candidate_path"),
        "candidate_hash": evidence.get("candidate_hash"),
        "evidence_path": evidence_path.relative_to(root).as_posix() if evidence else None,
        "evidence_hash": _digest(evidence_path) if evidence else None,
        "confirmation": _confirmation(evidence.get("confirmation")),
        "release_checks": _release_checks(evidence.get("release_checks")),
        "generation_stop": evidence.get("generation_stop"),
        "retro": _retro(run_dir, problem),
        "limitations": [item for item in evidence.get("limitations", []) if isinstance(item, str)],
    }


def _night(run_dir: Path, root: Path) -> dict[str, Any] | None:
    night = _read(run_dir / "night.json", None)
    if not isinstance(night, dict):
        return None
    slots = [_slot(run_dir, root, slot) for slot in night.get("slots", []) if isinstance(slot, dict)]
    run_id = str(night.get("run_id") or run_dir.name)
    logical = night.get("scheduled_run_id") if isinstance(night.get("scheduled_run_id"), str) else run_id[:10]
    trial = night.get("trial") if isinstance(night.get("trial"), dict) else {}
    research = [slot for slot in slots if slot["kind"] == "research"]
    return {
        "run_id": run_id,
        "date": logical,
        "status": night.get("status") or "unknown",
        "invocation": night.get("invocation_kind"),
        "started_at": night.get("started_at"),
        "finished_at": night.get("updated_at"),
        "budget_used": _number(night.get("budget_used_api_equivalent")),
        "budget_limit": _number(night.get("budget_limit_api_equivalent")),
        "trial_index": trial.get("index"),
        "trial_assignment": trial.get("assignment") if isinstance(trial.get("assignment"), dict) else None,
        "limitations": [item for item in night.get("limitations", []) if isinstance(item, str)],
        "slots": slots,
        "totals": {
            "slots": len(slots),
            "completed": sum(1 for slot in slots if slot["status"] == "completed"),
            "candidates": sum(len(slot["candidates"]) for slot in research),
            "promising": sum(slot["promising"] for slot in research),
            "confirmed": sum(1 for slot in research if slot["confirmed"]),
            "publishable": sum(1 for slot in research if slot["publishable"]),
            "best_gain": max((slot["best"]["median_gain"] for slot in research if slot["best"]), default=None),
        },
    }


def nights(root: Path) -> list[dict[str, Any]]:
    research = root / "runs" / "research"
    if not research.is_dir():
        return []
    found = [_night(item, root) for item in research.iterdir() if item.is_dir() and (item / "night.json").is_file()]
    return sorted(
        (item for item in found if item), key=lambda item: (item["started_at"] or "", item["run_id"]), reverse=True
    )


def _beats(problem: str, value: float | None, record: float | None) -> bool | None:
    """Ask the plugin whether a stored result clears its public record; None when the plugin cannot answer."""
    if value is None or record is None:
        return None
    try:
        from problem_loader import load_problem

        return bool(load_problem(problem).beats(value, record))
    except Exception:  # noqa: BLE001 - a broken or missing plugin must not take the brief down
        return None


def incumbents(root: Path) -> list[dict[str, Any]]:
    rows = []
    for directory in sorted(root.glob("best*")):
        if not directory.is_dir():
            continue
        problem = "circle_packing" if directory.name == "best" else directory.name.removeprefix("best-")
        scores = _read(directory / "scores.json", {})
        submitted = _read(directory / "submitted.json", {})
        provenance = _read(directory / "confirmation.json", None)
        submitted = submitted if isinstance(submitted, dict) else {}
        targets = []
        for target, entry in scores.items() if isinstance(scores, dict) else []:
            value = _value_of(entry)
            record = _number(entry.get("record")) if isinstance(entry, dict) else None
            targets.append(
                {
                    "target": str(target),
                    "value": value,
                    "record": record,
                    "beats_record": _beats(problem, value, record),
                    "submitted_at": (submitted.get(str(target)) or {}).get("sent_at")
                    if isinstance(submitted.get(str(target)), dict)
                    else None,
                }
            )
        record_kind, record_source = RECORD_SOURCE.get(problem, ("unknown", "unregistered record source"))
        rows.append(
            {
                "problem": problem,
                "record_kind": record_kind,
                "record_source": record_source,
                "solver_path": (directory / "solver.py").relative_to(root).as_posix(),
                "incumbent": {
                    "classification": "confirmed_prior_candidate"
                    if isinstance(provenance, dict)
                    else "historical_best_unvalidated",
                    "evidence_path": provenance.get("evidence_path") if isinstance(provenance, dict) else None,
                    "confirmed_at": provenance.get("confirmed_at") if isinstance(provenance, dict) else None,
                    "publishable": provenance.get("publishable") if isinstance(provenance, dict) else None,
                },
                "targets": targets,
                "beating_record": sum(1 for row in targets if row["beats_record"] is True),
                "unsubmitted_beats": sum(
                    1 for row in targets if row["beats_record"] is True and not row["submitted_at"]
                ),
            }
        )
    return rows


def _releases(root: Path, problem: str, candidate_hash: str | None) -> list[str]:
    if not isinstance(candidate_hash, str) or len(candidate_hash) < 12:
        return []
    release_root = root / "releases" / problem
    if not release_root.is_dir():
        return []
    return sorted(
        item.relative_to(root).as_posix()
        for item in release_root.iterdir()
        if item.is_dir() and item.name.startswith(candidate_hash[:12] + "-")
    )


def awaiting_publication(
    root: Path, night_rows: list[dict[str, Any]], incumbent_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Everything the history says is done but nobody has published: three checks, all local."""
    items = []
    approvals = root / "runs" / "research" / "approvals"
    for night in night_rows:
        for slot in night["slots"]:
            if not slot["publishable"]:
                continue
            approval = _read(approvals / f"{slot['candidate_hash']}.json", None) if slot["candidate_hash"] else None
            releases = _releases(root, slot["problem"], slot["candidate_hash"])
            if releases:
                continue
            items.append(
                {
                    "kind": "approved_not_released" if isinstance(approval, dict) else "publishable_unapproved",
                    "problem": slot["problem"],
                    "run_id": night["run_id"],
                    "date": night["date"],
                    "claim_type": slot["claim_type"],
                    "evidence_path": slot["evidence_path"],
                    "candidate_hash": slot["candidate_hash"],
                    "detail": slot["publishable_reason"]
                    or "Confirmed and release-validated; nothing has approved or pushed it.",
                    "next_step": "Run publish.py --push-only with the approval"
                    if isinstance(approval, dict)
                    else "Open the review dashboard, inspect the evidence, queue the release approval",
                }
            )
    for row in incumbent_rows:
        if row["record_kind"] != "public":
            continue  # a local-baseline win is shown under incumbents, never queued for publication
        for target in row["targets"]:
            if target["beats_record"] is True and not target["submitted_at"]:
                items.append(
                    {
                        "kind": "record_beat_unsubmitted",
                        "problem": row["problem"],
                        "run_id": None,
                        "date": None,
                        "claim_type": "benchmark_record",
                        "evidence_path": row["solver_path"],
                        "candidate_hash": None,
                        "target": target["target"],
                        "value": target["value"],
                        "record": target["record"],
                        "detail": f"Stored incumbent result beats the stored {row['record_source']} value and no submission is logged.",
                        "next_step": "Re-verify against the live record table, then submit by hand",
                    }
                )
    return items


def legacy_runs(root: Path) -> list[dict[str, Any]]:
    """The pre-governance loops (runs*/log.jsonl): iterations, champions and record wins per problem."""
    rows = []
    for directory in sorted(root.glob("runs*")):
        log = directory / "log.jsonl"
        if not directory.is_dir() or not log.is_file():
            continue
        problem = "circle_packing" if directory.name == "runs" else directory.name.removeprefix("runs-")
        iterations = champions = 0
        wins: set[str] = set()
        last_idea = None
        best_total = None
        try:
            with log.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(row, dict):
                        continue
                    iterations += 1
                    if row.get("status") == "champion":
                        champions += 1
                        last_idea = _trim(row.get("idea"), IDEA_CHARS)
                    total = _number(row.get("total"))
                    if total is not None and (best_total is None or total > best_total):
                        best_total = total
                    if isinstance(row.get("wins"), list):
                        wins.update(str(item) for item in row["wins"])
        except OSError:
            continue
        rows.append(
            {
                "problem": problem,
                "iterations": iterations,
                "champions": champions,
                "wins": sorted(wins, key=lambda item: (len(item), item)),
                "best_total": best_total,
                "last_champion_idea": last_idea,
                "classification": "historical_unvalidated",
            }
        )
    return rows


def build_brief(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    night_rows = nights(root)
    incumbent_rows = incumbents(root)
    return {
        "last_night": night_rows[0] if night_rows else None,
        "nights": night_rows,
        "incumbents": incumbent_rows,
        "awaiting_publication": awaiting_publication(root, night_rows, incumbent_rows),
        "legacy": legacy_runs(root),
    }
