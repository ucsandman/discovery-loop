"""Build the sanitized morning research report and gate existing morning tasks.

This wrapper never sends or publishes research.  It passes only the sanitized
report to an explicitly configured next process and propagates that process's
exit code.  The task installer wires the existing meditation and fleet actions
through it only when run with ``-Apply``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from research_state import atomic_json, read_json  # noqa: E402

STATUS_PATH = REPO / "runs" / "night-status.json"
REPORT_PATH = REPO / "runs" / "research" / "morning.json"
TERMINAL = {"completed", "partial", "failed", "paused"}
KNOWN_PROBLEMS = {"cvrp", "miplib_heur", "pglib_opf"}
KNOWN_PROVIDERS = {"fable", "astra", "paired", "validation"}


def _provider_accounting_row() -> dict[str, Any]:
    return {
        "slots": 0,
        "calls": 0,
        "charged_api_equivalent": 0.0,
        "reported_total_cost_usd_api_equivalent": 0.0,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def expected_run_id(now: datetime | None = None) -> str:
    current = (now or _utc_now()).astimezone()
    night = current.date() - timedelta(days=1) if current.time() < time(12, 0) else current.date()
    return night.isoformat()


def scheduled_task_info(name: str) -> dict[str, Any]:
    """Read stable task facts without copying the action or any local paths."""
    if os.name != "nt":
        return {"name": name, "available": False}
    escaped = name.replace("'", "''")
    command = (
        f"$i=Get-ScheduledTaskInfo -TaskName '{escaped}';"
        f"$t=Get-ScheduledTask -TaskName '{escaped}';"
        "[ordered]@{name=$t.TaskName;state=[string]$t.State;last_result=$i.LastTaskResult;"
        "last_run_time=$i.LastRunTime.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress"
    )
    try:
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        payload = json.loads(process.stdout) if process.returncode == 0 else {}
        return {
            "name": name,
            "available": bool(payload),
            "state": str(payload.get("state", "unknown"))[:30],
            "last_result": int(payload["last_result"]) if isinstance(payload.get("last_result"), int) else None,
            "last_run_time": payload.get("last_run_time"),
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return {"name": name, "available": False}


def _count_collection(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("count", "evaluations", "targets", "results"):
            if key in value:
                nested = value[key]
                return int(nested) if isinstance(nested, (int, float)) else _count_collection(nested)
    return 0


def _usage_counts(evidence: dict[str, Any]) -> dict[str, int]:
    usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
    by_purpose = usage.get("by_purpose") if isinstance(usage.get("by_purpose"), dict) else {}
    generation = int(usage.get("generation_calls", by_purpose.get("generation", usage.get("calls", 0))) or 0)
    review = int(usage.get("review_calls", by_purpose.get("critique", 0)) or 0)
    evaluations = _count_collection(evidence.get("development")) + _count_collection(evidence.get("confirmation"))
    return {"generation_calls": generation, "review_calls": review, "evaluations": evaluations}


def _safe_problem(value: Any) -> str:
    return value if value in KNOWN_PROBLEMS else "unknown"


def _safe_status(value: Any) -> str:
    allowed = {"pending", "running", "completed", "partial", "failed", "paused", "timed_out", "missing"}
    return value if value in allowed else "unknown"


def _latest_slots(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest = {}
    for entry in status.get("slots", []):
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            latest[entry["id"]] = entry
    return latest


def build_report(
    status: dict[str, Any],
    run_id: str,
    *,
    now: datetime | None = None,
    max_age_hours: float = 12,
    task_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a fixed-schema report containing no model prose or filesystem paths."""
    current = now or _utc_now()
    updated = _parse_iso(status.get("updated_at") or status.get("finished_at"))
    age_hours = (current - updated).total_seconds() / 3600 if updated else None
    fresh = bool(
        status.get("run_id") == run_id
        and status.get("status") in TERMINAL
        and age_hours is not None
        and 0 <= age_hours <= max_age_hours
    )
    schedule = read_json(REPO / "night.json", {}) or {}
    expected_ids = [slot.get("id") for slot in schedule.get("slots", []) if isinstance(slot, dict)]
    latest = _latest_slots(status)
    problems = []
    failed_stages = []
    missing_stages = []
    totals = {"generation_calls": 0, "review_calls": 0, "evaluations": 0, "retros_completed": 0}
    provider_breakdown: dict[str, dict[str, Any]] = {}
    evidence_root = REPO / "runs" / "research" / run_id
    for slot_id in expected_ids:
        slot = latest.get(slot_id)
        if not slot:
            missing_stages.append({"slot": slot_id, "stage": "research"})
            continue
        problem = _safe_problem(slot.get("problem"))
        provider = slot.get("provider") if slot.get("provider") in KNOWN_PROVIDERS else "validation"
        evidence = read_json(evidence_root / problem / "evidence.json", {}) or {}
        counts = _usage_counts(evidence)
        for key in ("generation_calls", "review_calls", "evaluations"):
            totals[key] += counts[key]
        stages = slot.get("stages") if isinstance(slot.get("stages"), dict) else {}
        for stage_name in ("research", "retro") if slot.get("kind") == "research" else ("research",):
            stage = stages.get(stage_name)
            if not isinstance(stage, dict):
                missing_stages.append({"problem": problem, "stage": stage_name})
            elif stage.get("status") != "completed":
                failed_stages.append(
                    {"problem": problem, "stage": stage_name, "status": _safe_status(stage.get("status"))}
                )
        if isinstance(stages.get("retro"), dict) and stages["retro"].get("status") == "completed":
            totals["retros_completed"] += 1
        usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
        by_provider = usage.get("by_provider") if isinstance(usage.get("by_provider"), dict) else {}
        safe_provider_counts = {
            name: int(value)
            for name, value in by_provider.items()
            if name in {"fable", "astra"} and isinstance(value, (int, float))
        }
        if safe_provider_counts:
            for name in safe_provider_counts:
                provider_row = provider_breakdown.setdefault(name, _provider_accounting_row())
                provider_row["slots"] += 1
        elif provider in {"fable", "astra", "paired"}:
            provider_row = provider_breakdown.setdefault(provider, _provider_accounting_row())
            provider_row["slots"] += 1
        problems.append(
            {
                "problem": problem,
                "provider": provider,
                "status": _safe_status(slot.get("status")),
                "confirmed": evidence.get("confirmed") if isinstance(evidence.get("confirmed"), bool) else None,
                "publishable": False,
                **counts,
            }
        )
    ledger = read_json(evidence_root / "budget.json", {}) or {}
    reservations = ledger.get("reservations") if isinstance(ledger.get("reservations"), dict) else {}
    settled = [entry for entry in reservations.values() if isinstance(entry, dict) and entry.get("status") == "settled"]
    reserved = [
        entry for entry in reservations.values() if isinstance(entry, dict) and entry.get("status") == "reserved"
    ]
    charged = round(sum(float(entry.get("charged", 0) or 0) for entry in settled), 6)
    reported = round(
        sum(float(entry.get("charged", 0) or 0) for entry in settled if entry.get("cost_known") is True), 6
    )
    held = round(sum(float(entry.get("amount", 0) or 0) for entry in reserved), 6)
    limit = float(
        ledger.get(
            "limit",
            status.get("budget_limit_api_equivalent", status.get("budget_limit_usd", 0)),
        )
        or 0
    )
    for entry in reservations.values():
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", ""))
        for name in ("fable", "astra"):
            if f":{name}:" in f":{label}:":
                provider_row = provider_breakdown.setdefault(name, _provider_accounting_row())
                provider_row["calls"] += 1
                if entry.get("status") == "settled":
                    amount = float(entry.get("charged", 0) or 0)
                    provider_row["charged_api_equivalent"] = round(provider_row["charged_api_equivalent"] + amount, 6)
                    if entry.get("cost_known") is True:
                        provider_row["reported_total_cost_usd_api_equivalent"] = round(
                            provider_row["reported_total_cost_usd_api_equivalent"] + amount, 6
                        )
                break
    limitations = []
    if not status:
        limitations.append("night status is missing")
    elif status.get("run_id") != run_id:
        limitations.append("night status belongs to a different run")
    elif not fresh:
        limitations.append("night status is stale or unfinished")
    if task_info and task_info.get("available") and task_info.get("last_result") != 0:
        limitations.append("scheduled night task returned a failure result")
    if status.get("status") not in {"completed", "partial"}:
        limitations.append(f"night ended with {_safe_status(status.get('status'))} status")
    if totals["generation_calls"] + totals["review_calls"] + totals["evaluations"] == 0:
        limitations.append("no research work was recorded")
    control = read_json(REPO / "runs" / "control.json", {}) or {}
    request = control.get("review_request") if isinstance(control, dict) else None
    marked_problem = None
    if isinstance(request, dict) and isinstance(request.get("evidence_path"), str):
        parts = request["evidence_path"].split("/")
        if len(parts) == 5 and parts[:2] == ["runs", "research"] and parts[-1] == "evidence.json":
            marked_problem = _safe_problem(parts[-2])
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": _iso(current),
        "status": _safe_status(status.get("status")) if status else "missing",
        "fresh": fresh,
        "marked_for_human_review": marked_problem,
        "task": task_info or {"name": "discovery-loop-night", "available": False},
        "counts": {
            "slots_expected": len(expected_ids),
            "slots_completed": sum(row["status"] == "completed" for row in problems),
            **totals,
        },
        "accounting": {
            "unit": "reported_total_cost_usd API-equivalent",
            "billing_mode": "monthly subscription CLI",
            "actual_cash_billed": None,
            "limit_api_equivalent": limit,
            "charged_api_equivalent": charged,
            "reported_total_cost_usd_api_equivalent": reported,
            "reserved_api_equivalent": held,
            "remaining_api_equivalent": max(0.0, round(limit - charged - held, 6)),
            "calls": len(reservations),
        },
        "provider_breakdown": provider_breakdown,
        "problems": problems,
        "missing_stages": missing_stages,
        "failed_stages": failed_stages,
        "limitations": limitations,
    }
    return report


def meditation_is_fresh(path: Path, task_info: dict[str, Any], now: datetime | None = None) -> bool:
    """Require the digest line to be newer than today's meditation start."""
    if not path.is_file():
        return False
    current = (now or _utc_now()).astimezone()
    last_run = _parse_iso(task_info.get("last_run_time"))
    if last_run is None or last_run.astimezone().date() != current.date():
        return False
    return path.stat().st_mtime >= last_run.timestamp()


def run_next(executable: str, arguments: list[str], report: dict[str, Any], report_path: Path) -> int:
    environment = dict(os.environ)
    environment["DISCOVERY_LOOP_RESEARCH_REPORT_JSON"] = json.dumps(report, separators=(",", ":"))
    environment["DISCOVERY_LOOP_RESEARCH_REPORT_PATH"] = str(report_path)
    process = subprocess.run([executable, *arguments], env=environment, check=False)
    return process.returncode


def run_meditation_with_context(
    executable: str, arguments: list[str], report: dict[str, Any], report_path: Path
) -> int:
    """Run the existing meditation source in memory with one prompt transform."""
    if len(arguments) != 1:
        raise ValueError("meditation-context mode requires exactly one runner script")
    runner = Path(arguments[0]).resolve()
    transformer_path = REPO / "scripts" / "install-morning-context.py"
    spec = importlib.util.spec_from_file_location("morning_context_transform", transformer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("morning context transformer is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transformed = module.transform(runner.read_text(encoding="utf-8"))
    environment = dict(os.environ)
    environment["DISCOVERY_LOOP_RESEARCH_REPORT_JSON"] = json.dumps(report, separators=(",", ":"))
    environment["DISCOVERY_LOOP_RESEARCH_REPORT_PATH"] = str(report_path)
    process = subprocess.run(
        [executable, "-s"],
        input=transformed,
        text=True,
        cwd=runner.parent,
        env=environment,
        check=False,
    )
    return process.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("report", "meditation", "meditation-context", "fleet"), default="report")
    parser.add_argument("--run-id")
    parser.add_argument("--max-age-hours", type=float, default=12)
    parser.add_argument("--next-executable")
    parser.add_argument("--next-argument", action="append", default=[])
    parser.add_argument("--meditation-line")
    args = parser.parse_args()
    run_id = args.run_id or expected_run_id()
    status = read_json(STATUS_PATH, {}) or {}
    task = scheduled_task_info("discovery-loop-night")
    report = build_report(status, run_id, max_age_hours=args.max_age_hours, task_info=task)
    atomic_json(REPORT_PATH, report)
    print(json.dumps(report, indent=2))
    if args.mode == "report":
        return 0 if report["fresh"] and report["status"] in {"completed", "partial"} else 2
    if not args.next_executable:
        print("next executable is required for wrapper modes", file=sys.stderr)
        return 2
    if args.mode == "fleet":
        line = (
            Path(args.meditation_line)
            if args.meditation_line
            else Path.home() / ".claude/meditations/digests/latest-line.txt"
        )
        if not meditation_is_fresh(line, scheduled_task_info("NightlyMeditation")):
            print("fleet skipped: today's meditation artifact is missing or stale", file=sys.stderr)
            return 3
    if args.mode == "meditation-context":
        return run_meditation_with_context(args.next_executable, args.next_argument, report, REPORT_PATH)
    # Meditation runs even for missing/partial research so its digest can make
    # that limitation visible instead of silently reusing stale evidence.
    return run_next(args.next_executable, args.next_argument, report, REPORT_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
