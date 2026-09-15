"""Descriptive comparison of scheduled research modes; never a model ranking claim."""

from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
import json
import math
import re


def _number(value):
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else 0.0
    )


def _routing_attempts(routing):
    attempts = routing.get("attempts") if isinstance(routing, dict) else []
    return [attempt for attempt in attempts if isinstance(attempt, dict)] if isinstance(attempts, list) else []


def _physical_attempt(attempt):
    """Legacy records omitted physical; treat that omission consistently as physical."""
    return attempt.get("physical") is not False


def routing_execution_summary(evidence, retro):
    """Merge immutable research and retro routing records for every report surface."""
    routing = evidence.get("routing") if isinstance(evidence.get("routing"), dict) else None
    if routing is None:
        return {"provenance": "historical_unverified", "formal_trial_eligible": False}
    retro_routing = retro.get("routing") if isinstance(retro.get("routing"), dict) else None
    retro_status = retro.get("status") if isinstance(retro.get("status"), str) else "missing"
    reasons = [item for item in routing.get("ineligibility_reasons", []) if isinstance(item, str)]
    research_attempts = _routing_attempts(routing)
    successful_research = [
        attempt
        for attempt in research_attempts
        if _is_generation_attempt(attempt) and attempt.get("status") == "completed" and _physical_attempt(attempt)
    ]
    if not successful_research:
        reasons.append("no_successful_physical_research_call")
    if evidence.get("status") != "completed":
        reasons.append("research_not_completed")
    if retro_status != "completed" or retro_routing is None:
        reasons.append("retro_pending_or_unreadable")
    elif retro_routing.get("formal_trial_eligible") is not True:
        retro_reasons = [item for item in retro_routing.get("ineligibility_reasons", []) if isinstance(item, str)]
        reasons.extend(retro_reasons or ["retro_not_formally_eligible"])
    models, families, successful_models, failures, fallbacks = Counter(), Counter(), Counter(), Counter(), Counter()
    allowance, allowance_complete, attempts = 0.0, True, 0
    research_failed = retro_failed = 0
    last_successful_model = last_fallback_reason = None
    for source, role in ((routing, "research"), (retro_routing or {}, "retro")):
        for attempt in _routing_attempts(source):
            if attempt.get("status") == "skipped":
                continue
            attempts += 1
            models[attempt.get("model") if isinstance(attempt.get("model"), str) else "unknown"] += 1
            families[attempt.get("family") if isinstance(attempt.get("family"), str) else "unknown"] += 1
            if attempt.get("status") != "completed":
                if role == "retro":
                    retro_failed += 1
                else:
                    research_failed += 1
            if isinstance(attempt.get("error_kind"), str):
                failures[attempt["error_kind"]] += 1
                fallbacks[attempt["error_kind"]] += 1
                last_fallback_reason = attempt["error_kind"]
            elif attempt.get("status") == "completed":
                model = attempt.get("model") if isinstance(attempt.get("model"), str) else "unknown"
                successful_models[model] += 1
                last_successful_model = model
            amount = attempt.get("charged_allowance")
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                amount = attempt.get("reserved_allowance")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount):
                allowance += float(amount)
            else:
                allowance_complete = False
    return {
        "provenance": "recorded_routing",
        "formal_trial_eligible": routing.get("formal_trial_eligible") is True and not reasons,
        "ineligibility_reasons": sorted(set(reasons)),
        "retro_status": retro_status,
        "actual_model_calls": dict(sorted(models.items())),
        "actual_family_calls": dict(sorted(families.items())),
        "successful_model_calls": dict(sorted(successful_models.items())),
        "model_call_shares": {
            name: count / sum(successful_models.values()) for name, count in sorted(successful_models.items())
        },
        "last_successful_model": last_successful_model,
        "last_fallback_reason": last_fallback_reason,
        "failure_reasons": dict(sorted(failures.items())),
        "fallback_reasons": dict(sorted(fallbacks.items())),
        "failed_attempts": research_failed,
        "retro_failed_attempts": retro_failed,
        "paired_degradations": int(routing.get("degraded") is True)
        + int(bool(retro_routing and retro_routing.get("degraded") is True)),
        "allowance": allowance,
        "allowance_complete": allowance_complete and attempts > 0,
    }


def _scheduled_date(run_id):
    """Return a logical scheduled date, accepting legacy and suffixed run ids only."""
    if not isinstance(run_id, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-scheduled)?", run_id):
        return None
    try:
        return date.fromisoformat(run_id[:10])
    except ValueError:
        return None


def _schedule(root):
    path = Path(root) / "night.json"
    if not path.is_file():
        path = Path(__file__).resolve().with_name("night.json")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    trial = config.get("trial") if isinstance(config, dict) else None
    if not isinstance(trial, dict) or not isinstance(trial.get("cycle"), list):
        return None
    try:
        anchor = date.fromisoformat(trial["anchor_date"])
    except (KeyError, TypeError, ValueError):
        return None
    cycle = [entry for entry in trial["cycle"] if isinstance(entry, dict)]
    tracks = set.intersection(*(set(entry) - {"order"} for entry in cycle)) if cycle else set()
    return {"anchor": anchor, "cycle": cycle, "tracks": tracks}


def _assignment(schedule, logical_date, problem):
    if schedule is None or problem not in schedule["tracks"]:
        return None
    index = (logical_date - schedule["anchor"]).days
    if not 0 <= index < len(schedule["cycle"]):
        return None
    arm = schedule["cycle"][index].get(problem)
    return arm if isinstance(arm, str) else None


def _attempt_matches_arm(attempt, arm):
    aliases = {"fable", "astra"} if arm == "paired" else {arm}
    requested_alias = attempt.get("requested_alias")
    actual_alias = attempt.get("model_alias")
    if isinstance(requested_alias, str) and isinstance(actual_alias, str):
        return requested_alias in aliases and actual_alias == requested_alias
    if isinstance(requested_alias, str):
        return requested_alias in aliases
    model = attempt.get("model")
    if not isinstance(model, str):
        return False
    lowered = model.lower()
    return arm in lowered or (arm == "paired" and any(name in lowered for name in ("fable", "astra")))


def _is_generation_attempt(attempt):
    """Legacy routing records omitted purpose; current records must say generation."""
    return attempt.get("purpose") in (None, "generation")


def _coverage(
    schedule,
    observed_dates,
    observed_slots,
    completed_slots,
    attempted_research_calls,
    successful_research_calls,
    successful_generation_calls,
    generation_research_calls,
    critique_research_calls,
):
    if schedule is None:
        return {
            "observed_date_window": None,
            "expected_slots": 0,
            "missing_slots": [],
            "completed_slots": 0,
            "attempted_research_calls": attempted_research_calls,
            "successful_research_calls": successful_research_calls,
            "successful_generation_calls": successful_generation_calls,
            "generation_research_calls": generation_research_calls,
            "critique_research_calls": critique_research_calls,
            "partial_cycle": True,
            "complete": False,
        }
    expected = []
    for index in range(len(schedule["cycle"])):
        current = schedule["anchor"] + timedelta(days=index)
        for problem in sorted(schedule["tracks"]):
            arm = _assignment(schedule, current, problem)
            if arm is not None:
                expected.append((current.isoformat(), problem, arm))
    missing = [
        {"run_date": run_date, "problem": problem, "requested_arm": arm}
        for run_date, problem, arm in expected
        if (run_date, problem) not in observed_slots
    ]
    complete = completed_slots == len(expected) and not missing
    return {
        "observed_date_window": (
            {
                "start": min(observed_dates).isoformat(),
                "end": max(observed_dates).isoformat(),
                "days": (max(observed_dates) - min(observed_dates)).days + 1,
            }
            if observed_dates
            else None
        ),
        "expected_slots": len(expected),
        "missing_slots": missing,
        "completed_slots": completed_slots,
        "attempted_research_calls": attempted_research_calls,
        "successful_research_calls": successful_research_calls,
        "successful_generation_calls": successful_generation_calls,
        "generation_research_calls": generation_research_calls,
        "critique_research_calls": critique_research_calls,
        "partial_cycle": not complete,
        "complete": complete,
    }


def _group():
    return {
        "runs": 0,
        "completed": 0,
        "confirmed": 0,
        "calls": 0,
        "allowance_charged": 0.0,
        "solver_seconds": 0.0,
        "solver_evaluations": 0,
        "confirmed_gains": [],
    }


def _add_evidence(group, evidence):
    group["runs"] += 1
    group["completed"] += evidence.get("status") == "completed"
    group["confirmed"] += evidence.get("confirmed") is True
    _add_usage(group, evidence)
    gain = (evidence.get("confirmation") or {}).get("median_gain")
    if evidence.get("confirmed") is True and isinstance(gain, (int, float)) and math.isfinite(gain):
        group["confirmed_gains"].append(gain)


def _add_usage(group, evidence):
    usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
    group["calls"] += int(_number(usage.get("calls")))
    group["allowance_charged"] += _number(usage.get("charged"))
    group["solver_seconds"] += _number(evidence.get("solver_seconds"))
    group["solver_evaluations"] += int(_number(evidence.get("solver_evaluations")))


def _routing_fields(data):
    successful = dict(sorted(data.pop("successful_model_calls", {}).items()))
    return {
        "actual_model_calls": dict(sorted(data.pop("actual_model_calls", {}).items())),
        "successful_model_calls": successful,
        "model_call_shares": {name: count / sum(successful.values()) for name, count in successful.items()}
        if successful
        else {},
        "actual_family_calls": dict(sorted(data.pop("actual_family_calls", {}).items())),
        "fallback_reasons": dict(sorted(data.pop("fallback_reasons", {}).items())),
        "failed_attempts": data.pop("failed_attempts", 0),
        "paired_degradations": data.pop("paired_degradations", 0),
        "routing_cost": round(data.pop("routing_cost", 0.0), 4),
        "actual_strategy": ", ".join(sorted(data.pop("actual_strategies", {}).keys())),
    }


def summarize(root):
    schedule = _schedule(root)
    groups = defaultdict(_group)
    clean_groups = defaultdict(_group)
    operational_groups = defaultdict(_group)
    ineligible_reasons = Counter()
    unreadable = 0
    observed_dates, observed_slots = set(), set()
    completed_slots = attempted_research_calls = successful_research_calls = 0
    successful_generation_calls = generation_research_calls = critique_research_calls = 0
    for path in sorted((Path(root) / "runs/research").glob("*/*/evidence.json")):
        logical_date = _scheduled_date(path.parent.parent.name)
        if logical_date is None:
            continue  # Exclude manual probes and UI fixtures from the scheduled trial.
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(evidence, dict):
                raise ValueError("Expected evidence object")
        except (OSError, ValueError):
            unreadable += 1
            continue
        provider = evidence.get("provider")
        problem = evidence.get("problem")
        if not isinstance(provider, str) or not isinstance(problem, str):
            unreadable += 1
            continue
        assigned_arm = _assignment(schedule, logical_date, problem)
        canonical = assigned_arm is not None
        duplicate_of_scheduled = (
            not path.parent.parent.name.endswith("-scheduled")
            and (
                path.parent.parent.with_name(f"{logical_date.isoformat()}-scheduled")
                / path.parent.name
                / "evidence.json"
            ).is_file()
        )
        if duplicate_of_scheduled:
            canonical = False
        if canonical:
            observed_dates.add(logical_date)
            observed_slots.add((logical_date.isoformat(), problem))
            completed_slots += evidence.get("status") == "completed"
        routing = evidence.get("routing")
        if not isinstance(routing, dict):
            _add_evidence(groups[(problem, provider)], evidence)
            continue
        retro_path = path.with_name("retro.json")
        try:
            retro = json.loads(retro_path.read_text(encoding="utf-8")) if retro_path.is_file() else {}
        except (OSError, ValueError):
            retro = {}
        if not isinstance(retro, dict):
            retro = {}
        execution = routing_execution_summary(evidence, retro)
        arm = routing.get("requested_arm") if isinstance(routing.get("requested_arm"), str) else provider
        if canonical:
            research_attempts = _routing_attempts(routing)
            attempted_research_calls += sum(
                _physical_attempt(attempt) and attempt.get("status") != "skipped" for attempt in research_attempts
            )
            successful_research_calls += sum(
                attempt.get("status") == "completed" and _physical_attempt(attempt) for attempt in research_attempts
            )
            generation_research_calls += sum(
                _physical_attempt(attempt) and attempt.get("status") != "skipped" and _is_generation_attempt(attempt)
                for attempt in research_attempts
            )
            critique_research_calls += sum(
                _physical_attempt(attempt)
                and attempt.get("status") != "skipped"
                and attempt.get("purpose") == "critique"
                for attempt in research_attempts
            )
            successful_generation_calls += sum(
                attempt.get("status") == "completed" and _physical_attempt(attempt) and _is_generation_attempt(attempt)
                for attempt in research_attempts
            )
            if arm != assigned_arm:
                execution["formal_trial_eligible"] = False
                execution["ineligibility_reasons"] = sorted(
                    set(execution["ineligibility_reasons"] + ["requested_arm_does_not_match_trial_assignment"])
                )
            elif not any(
                attempt.get("status") == "completed"
                and _physical_attempt(attempt)
                and _is_generation_attempt(attempt)
                and _attempt_matches_arm(attempt, arm)
                for attempt in _routing_attempts(routing)
            ):
                execution["formal_trial_eligible"] = False
                execution["ineligibility_reasons"] = sorted(
                    set(execution["ineligibility_reasons"] + ["successful_call_does_not_match_requested_arm"])
                )
        else:
            execution["formal_trial_eligible"] = False
        if canonical and execution["formal_trial_eligible"]:
            group = clean_groups[(problem, arm)]
        else:
            provenance = (
                "historical_duplicate"
                if duplicate_of_scheduled
                else "routing_recorded_ineligible"
                if canonical
                else "operational_extra"
            )
            group = operational_groups[(problem, arm, provenance)]
        _add_evidence(group, evidence)
        _add_usage(group, retro)
        for name, count in execution["actual_model_calls"].items():
            group.setdefault("actual_model_calls", Counter())[name] += count
        for name, count in execution["successful_model_calls"].items():
            group.setdefault("successful_model_calls", Counter())[name] += count
        for name, count in execution["actual_family_calls"].items():
            group.setdefault("actual_family_calls", Counter())[name] += count
        for name, count in execution["fallback_reasons"].items():
            group.setdefault("fallback_reasons", Counter())[name] += count
        group["failed_attempts"] = (
            group.get("failed_attempts", 0) + execution["failed_attempts"] + execution["retro_failed_attempts"]
        )
        group["paired_degradations"] = group.get("paired_degradations", 0) + execution["paired_degradations"]
        group.setdefault("actual_strategies", Counter())[
            routing.get("mode") if isinstance(routing.get("mode"), str) else "unknown"
        ] += 1
        if execution["allowance_complete"]:
            group["routing_allowance"] = group.get("routing_allowance", 0.0) + execution["allowance"]
            group["routing_allowance_complete"] = True
        if not execution["formal_trial_eligible"]:
            for reason in execution["ineligibility_reasons"]:
                if isinstance(reason, str):
                    ineligible_reasons[reason] += 1
            continue
    rows = []
    for (problem, provider), data in sorted(groups.items()):
        charged = data["allowance_charged"]
        hours = data["solver_seconds"] / 3600
        rows.append(
            {
                "problem": problem,
                "provider": provider,
                "provenance": "historical_unverified",
                "formal_trial_eligible": False,
                **data,
                "allowance_charged": round(charged, 4),
                "solver_hours": round(hours, 4),
                "confirmed_per_allowance_unit": data["confirmed"] / charged if charged else None,
                "confirmed_per_solver_hour": data["confirmed"] / hours if hours else None,
            }
        )
    clean_rows = []
    for (problem, arm), data in sorted(clean_groups.items()):
        charged = (
            data["routing_allowance"] if data.pop("routing_allowance_complete", False) else data["allowance_charged"]
        )
        hours = data["solver_seconds"] / 3600
        clean_rows.append(
            {
                "problem": problem,
                "provider": arm,
                "requested_arm": arm,
                "provenance": "clean_formal_trial",
                "formal_trial_eligible": True,
                **data,
                **_routing_fields(data),
                "allowance_charged": round(charged, 4),
                "solver_hours": round(hours, 4),
                "confirmed_per_allowance_unit": data["confirmed"] / charged if charged else None,
                "confirmed_per_solver_hour": data["confirmed"] / hours if hours else None,
            }
        )
    operational_rows = []
    for (problem, arm, provenance), data in sorted(operational_groups.items()):
        charged = (
            data["routing_allowance"] if data.pop("routing_allowance_complete", False) else data["allowance_charged"]
        )
        hours = data["solver_seconds"] / 3600
        operational_rows.append(
            {
                "problem": problem,
                "provider": arm,
                "requested_arm": arm,
                "provenance": provenance,
                "formal_trial_eligible": False,
                **data,
                **_routing_fields(data),
                "allowance_charged": round(charged, 4),
                "solver_hours": round(hours, 4),
                "confirmed_per_allowance_unit": None,
                "confirmed_per_solver_hour": None,
            }
        )
    return {
        "rows": rows,
        "clean_rows": clean_rows,
        "runs": sum(row["runs"] for row in rows)
        + sum(row["runs"] for row in clean_rows)
        + sum(row["runs"] for row in operational_rows),
        "clean_runs": sum(row["runs"] for row in clean_rows),
        "operational_rows": operational_rows,
        "unreadable": unreadable,
        "ineligible_reasons": dict(sorted(ineligible_reasons.items())),
        "coverage": _coverage(
            schedule,
            observed_dates,
            observed_slots,
            completed_slots,
            attempted_research_calls,
            successful_research_calls,
            successful_generation_calls,
            generation_research_calls,
            critique_research_calls,
        ),
        "note": "Historical evidence is readable but has unverified routing provenance. Clean ratios include only canonical 14-night slots with recorded successful physical research calls, matching requested assignments, eligible routing, and completed retros. Operational extras and validation are descriptive only. Allowance uses API-equivalent estimates or conservative reservations, not subscription billing. Solver hours sum worker elapsed time, not CPU time. Small samples do not establish a model ranking or justify automatic reallocation.",
    }


if __name__ == "__main__":
    print(json.dumps(summarize(Path(__file__).resolve().parent), indent=2))
