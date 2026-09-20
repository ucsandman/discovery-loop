"""What each research direction on a prize plugin cost, and what it bought.

Reads only what the research loop already wrote: ``runs/research/<run>/<problem>/evidence.json``
for the per-candidate records and ``runs/research/<run>/routing.json`` for the provider-reported
cost of each model call. Nothing is fetched and no model is called.

Two cost numbers are kept apart on purpose. ``model_usd`` is *charged allowance*, the envelope
the budget ledger consumed, which for subscription CLIs is not a price. ``reported_usd`` is the
subset the provider actually put a number on. ``local_compute_usd`` is an electricity estimate
from the solver seconds, using the two constants below. None of the three is a bill.

``record_dead_end`` is the only writer here, and it appends to the repo-wide
``problems/_dead_ends.json`` under the same lock-and-atomic-write discipline as every other
ledger in this repo (``scripts/dead_ends.py`` predates that discipline; do not copy it).
"""

from __future__ import annotations

import math
import re
from datetime import date
from pathlib import Path
from typing import Any

from research_state import FileLock, atomic_json, read_json

# Electricity assumptions for locally-run solver time. Both are reported as assumptions
# on every ledger so a reader can substitute their own numbers.
LOCAL_KWH_PER_HOUR = 0.15
USD_PER_KWH = 0.15
SECONDS_PER_HOUR = 3600.0

DEFAULT_MIN_EFFECT = 0.02
STOP_AFTER_ATTEMPTS = 3
IDEA_CHARS = 200
DEAD_ENDS_PATH = ("problems", "_dead_ends.json")
_DEAD_END_ID = re.compile(r"de-(\d+)\Z")
_WORD = re.compile(r"[a-z0-9]+")


def _finite(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    return value if math.isfinite(value) else default


def _trim(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _money(value: float) -> str:
    return f"{value:.0f}" if abs(value) >= 1 else f"{value:.2f}"


def _percent(value: float) -> str:
    percent = value * 100.0
    if abs(percent) >= 10:
        return f"{percent:.0f}"
    if abs(percent) >= 1:
        return f"{percent:.1f}"
    return f"{percent:.2g}"


def _idea_family(record: dict, idea: str) -> str:
    """The research direction a candidate belongs to, not the provider family.

    ``research_memory`` already classifies an idea by its ``[kind: ...]`` tag and writes that
    under ``family`` in the development-history rows; reuse it when importable, and fall back
    to the first three words of the idea so ungrouped candidates still cluster sensibly.
    """
    try:
        import research_memory

        family = research_memory._family(record, idea)
    except Exception:  # noqa: BLE001 - grouping must never break a read-only report
        family = ""
    if isinstance(family, str) and family and family != "unclassified":
        return family
    words = _WORD.findall(idea.lower())[:3]
    return " ".join(words) or "unclassified"


def _routing_reported(run_dir: Path, problem: str) -> dict[str, float]:
    """``{logical_call_id: reported_cost}`` for physical attempts scoped to ``problem``."""
    try:
        journal = read_json(run_dir / "routing.json", None)
    except (OSError, ValueError):
        return {}
    attempts = journal.get("attempts") if isinstance(journal, dict) else None
    totals: dict[str, float] = {}
    for attempt in attempts if isinstance(attempts, list) else []:
        if not isinstance(attempt, dict) or attempt.get("physical") is not True:
            continue
        if attempt.get("scope") != problem:
            continue
        call_id = attempt.get("logical_call_id")
        cost = _finite(attempt.get("reported_cost"))
        if not isinstance(call_id, str) or cost is None:
            continue
        totals[call_id] = totals.get(call_id, 0.0) + cost
    return totals


def _candidate_call_ids(candidate: dict) -> list[str]:
    attempts = candidate.get("routing_attempts")
    ids = []
    for attempt in attempts if isinstance(attempts, list) else []:
        call_id = attempt.get("logical_call_id") if isinstance(attempt, dict) else None
        if isinstance(call_id, str) and call_id not in ids:
            ids.append(call_id)
    return ids


def _candidate_solver_seconds(candidate: dict, share: float) -> float:
    rows = candidate.get("rows")
    if isinstance(rows, list) and rows:
        total = 0.0
        seen = False
        for row in rows:
            seconds = _finite(row.get("secs")) if isinstance(row, dict) else None
            if seconds is not None and seconds >= 0:
                total += seconds
                seen = True
        if seen:
            return total
    return share


def _candidate_row(candidate: dict, *, run_id: str, problem: str, reported: dict[str, float], share: float) -> dict:
    idea = _trim(candidate.get("idea") or candidate.get("generation_error") or "", IDEA_CHARS)
    cost_usd = _finite(candidate.get("cost_usd"), 0.0) or 0.0
    reported_usd = sum(reported.get(call_id, 0.0) for call_id in _candidate_call_ids(candidate))
    solver_seconds = _candidate_solver_seconds(candidate, share)
    status = candidate.get("development_status") or candidate.get("status")
    return {
        "run_id": run_id,
        "problem": problem,
        "iteration": candidate.get("iteration"),
        "idea": idea,
        "family": _idea_family(candidate, idea),
        "model_family": candidate.get("family"),
        "provider": candidate.get("provider"),
        "actual_model": candidate.get("actual_model") or candidate.get("model"),
        "development_status": status if isinstance(status, str) else "unknown",
        "cost_usd": round(max(0.0, cost_usd), 6),
        "reported_cost_usd": round(max(0.0, reported_usd), 6) if reported_usd else None,
        "elapsed_seconds": _finite(candidate.get("elapsed_seconds")),
        "solver_seconds": round(max(0.0, solver_seconds), 6),
        "local_compute_usd": round(local_compute_usd(solver_seconds), 6),
        "median_gain": _finite(candidate.get("median_gain")),
        "selection_gain": _finite(candidate.get("selection_gain")),
    }


def local_compute_usd(solver_seconds: float) -> float:
    """Electricity estimate for locally-run solver time, at the module's two constants."""
    seconds = max(0.0, _finite(solver_seconds, 0.0) or 0.0)
    return seconds / SECONDS_PER_HOUR * LOCAL_KWH_PER_HOUR * USD_PER_KWH


def ledger(root, problem: str) -> dict:
    """Per-candidate and per-direction economics for one prize plugin across every run."""
    problem = str(problem)
    research_root = Path(root) / "runs" / "research"
    candidates: list[dict] = []
    runs: list[str] = []
    for evidence_path in sorted(research_root.glob(f"*/{problem}/evidence.json")):
        try:
            evidence = read_json(evidence_path, None)
        except (OSError, ValueError):
            continue
        if not isinstance(evidence, dict):
            continue
        run_dir = evidence_path.parent.parent
        run_id = evidence.get("run_id")
        run_id = run_id if isinstance(run_id, str) and run_id else run_dir.name
        runs.append(run_id)
        development = evidence.get("development") if isinstance(evidence.get("development"), dict) else {}
        rows = development.get("candidates")
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        run_solver_seconds = _finite(evidence.get("solver_seconds"), 0.0) or 0.0
        share = run_solver_seconds / len(rows) if rows else 0.0
        reported = _routing_reported(run_dir, problem)
        for candidate in rows:
            candidates.append(_candidate_row(candidate, run_id=run_id, problem=problem, reported=reported, share=share))

    directions = direction_summary(candidates)
    gains = [row["median_gain"] for row in candidates if row["median_gain"] is not None]
    solver_seconds = sum(row["solver_seconds"] for row in candidates)
    return {
        "problem": problem,
        "runs": sorted(set(runs)),
        "candidates": candidates,
        "directions": directions,
        "totals": {
            "model_usd": round(sum(row["cost_usd"] for row in candidates), 6),
            "reported_usd": round(sum(row["reported_cost_usd"] or 0.0 for row in candidates), 6),
            "local_compute_usd": round(sum(row["local_compute_usd"] for row in candidates), 6),
            "solver_seconds": round(solver_seconds, 6),
            "best_gain": max(gains) if gains else None,
            "candidates": len(candidates),
        },
        "assumptions": [
            "model_usd is charged allowance from the budget ledger, not a bill; subscription CLIs "
            "report no price for most calls.",
            "reported_usd counts only the calls whose provider reported a cost in routing.json.",
            f"local_compute_usd assumes {LOCAL_KWH_PER_HOUR:g} kWh per solver-hour at ${USD_PER_KWH:g} per kWh.",
            "A candidate without per-row solver seconds is charged an equal share of its run's total solver seconds.",
        ],
    }


def direction_summary(candidates, *, min_effect: float = DEFAULT_MIN_EFFECT) -> list[dict]:
    """Group candidate rows into research directions and give each one a verdict sentence."""
    min_effect = _finite(min_effect, DEFAULT_MIN_EFFECT) or DEFAULT_MIN_EFFECT
    groups: dict[str, dict] = {}
    for row in candidates if isinstance(candidates, (list, tuple)) else []:
        if not isinstance(row, dict):
            continue
        family = row.get("family") if isinstance(row.get("family"), str) and row.get("family") else "unclassified"
        group = groups.setdefault(
            family,
            {
                "family": family,
                "problem": row.get("problem"),
                "attempts": 0,
                "best_gain": None,
                "total_cost_usd": 0.0,
                "ideas": [],
                "runs": [],
            },
        )
        group["attempts"] += 1
        group["total_cost_usd"] += _finite(row.get("cost_usd"), 0.0) or 0.0
        group["total_cost_usd"] += _finite(row.get("local_compute_usd"), 0.0) or 0.0
        gain = _finite(row.get("median_gain"))
        if gain is not None and (group["best_gain"] is None or gain > group["best_gain"]):
            group["best_gain"] = gain
        idea = row.get("idea")
        if isinstance(idea, str) and idea and idea not in group["ideas"]:
            group["ideas"].append(idea)
        run_id = row.get("run_id")
        if isinstance(run_id, str) and run_id not in group["runs"]:
            group["runs"].append(run_id)

    summaries = []
    for family in sorted(groups):
        group = groups[family]
        cost = round(group["total_cost_usd"], 6)
        best_gain = group["best_gain"]
        attempts = group["attempts"]
        effective_gain = best_gain if best_gain is not None else 0.0
        if effective_gain > min_effect:
            verdict = "keep"
            sentence = (
                f"This direction improved performance by {_percent(effective_gain)} percent "
                f"for approximately ${_money(cost)} equivalent research cost."
            )
        elif attempts >= STOP_AFTER_ATTEMPTS:
            verdict = "stop"
            sentence = (
                f"This research branch consumed ${_money(cost)} across {attempts} attempts "
                f"with no scaling improvement. Stop exploring it."
            )
        else:
            verdict = "watch"
            sentence = (
                f"This direction has {attempts} attempt{'s' if attempts != 1 else ''} and a best measured "
                f"gain of {_percent(effective_gain)} percent for approximately ${_money(cost)} equivalent "
                f"research cost; not enough evidence yet."
            )
        summaries.append(
            {
                "family": family,
                "problem": group["problem"],
                "attempts": attempts,
                "best_gain": best_gain,
                "total_cost_usd": cost,
                "gain_per_usd": round(effective_gain / cost, 6) if cost > 0 else None,
                "verdict": verdict,
                "sentence": sentence,
                "min_effect": min_effect,
                "ideas": group["ideas"][:3],
                "runs": group["runs"],
            }
        )
    summaries.sort(key=lambda item: (item["verdict"] != "keep", -(item["best_gain"] or 0.0), item["family"]))
    return summaries


def progress(root, problem: str) -> dict:
    """The small summary ``prize_scoring.score_prize`` takes as ``progress``."""
    book = ledger(root, problem)
    return {
        "problem": problem,
        "best_gain": book["totals"]["best_gain"],
        "attempts": book["totals"]["candidates"],
        "model_usd": book["totals"]["model_usd"],
        "local_compute_usd": book["totals"]["local_compute_usd"],
    }


def stop_recommendations(book: dict) -> list[dict]:
    """Dead-end-shaped rows a human confirms before ``record_dead_end`` writes them."""
    if not isinstance(book, dict):
        return []
    problem = book.get("problem") if isinstance(book.get("problem"), str) else "general"
    recommendations = []
    for direction in book.get("directions") or []:
        if not isinstance(direction, dict) or direction.get("verdict") != "stop":
            continue
        family = direction.get("family") or "unclassified"
        example = (direction.get("ideas") or [""])[0]
        approach = f"{family}: {example}" if example else str(family)
        tags = sorted({word for word in _WORD.findall(str(family).lower()) if len(word) > 2} | {problem})
        evidence = ", ".join(f"runs/research/{run}/{problem}/evidence.json" for run in direction.get("runs") or [])
        recommendations.append(
            {
                "problem": problem,
                "approach": _trim(approach, 300),
                "why_failed": direction.get("sentence") or "no measured improvement",
                "evidence": evidence or f"runs/research/*/{problem}/evidence.json",
                "tags": tags,
            }
        )
    return recommendations


def _next_dead_end_id(entries: list) -> str:
    highest = 0
    for entry in entries:
        match = _DEAD_END_ID.fullmatch(str(entry.get("id", ""))) if isinstance(entry, dict) else None
        if match:
            highest = max(highest, int(match.group(1)))
    return f"de-{highest + 1:03d}"


def record_dead_end(root, entry: dict, by: str) -> dict:
    """Append one confirmed dead end to ``problems/_dead_ends.json``.

    Same record shape as ``scripts/dead_ends.py`` plus a ``recorded_by`` provenance field, but
    written under ``FileLock`` + ``atomic_json`` and with an id one past the highest existing
    numeric id, so a concurrent writer cannot mint a duplicate.
    """
    if not isinstance(entry, dict):
        raise ValueError("a dead end entry must be a dict")
    approach = _trim(entry.get("approach"), 300)
    why_failed = _trim(entry.get("why_failed"), 400)
    if not approach or not why_failed:
        raise ValueError("a dead end needs both an approach and why it failed")
    tags = entry.get("tags")
    tags = sorted({str(tag).strip().lower() for tag in tags if str(tag).strip()}) if isinstance(tags, list) else []
    record = {
        "id": "",
        "date": str(entry.get("date") or date.today().isoformat()),
        "problem": str(entry.get("problem") or "general"),
        "approach": approach,
        "why_failed": why_failed,
        "evidence": _trim(entry.get("evidence"), 500),
        "tags": tags,
        "recorded_by": _trim(by, 80) or "unknown",
    }
    path = Path(root) / Path(*DEAD_ENDS_PATH)
    with FileLock(str(path) + ".lock"):
        existing = read_json(path, [])
        if not isinstance(existing, list):
            raise ValueError("problems/_dead_ends.json is not a list; refusing to overwrite it")
        record["id"] = _next_dead_end_id(existing)
        atomic_json(path, [*existing, record])
    return record


def _fit_and_bits(prize_score: Any) -> tuple[dict | None, int | None, dict | None]:
    if not isinstance(prize_score, dict):
        return None, None, None
    scaling = prize_score.get("scaling") if isinstance(prize_score.get("scaling"), dict) else prize_score
    fit = scaling.get("fit") if isinstance(scaling.get("fit"), dict) else None
    bits = scaling.get("target_bits")
    bits = bits if isinstance(bits, int) and not isinstance(bits, bool) and bits > 0 else None
    extrapolation = scaling.get("extrapolation") if isinstance(scaling.get("extrapolation"), dict) else None
    return fit, bits, extrapolation


def ev_impact(prize_score: Any, gain: float) -> dict:
    """How far a measured gain moves the scaling verdict. One sentence, no fake precision."""
    measured = _finite(gain, 0.0) or 0.0
    result = {
        "gain": measured,
        "speedup": None,
        "bits_equivalent": None,
        "verdict_before": None,
        "verdict_after": None,
        "sentence": "",
    }
    fit, bits, extrapolation = _fit_and_bits(prize_score)
    if measured <= 0:
        result["sentence"] = "No measured gain on this plugin, so the scaling verdict is unchanged."
        result["verdict_before"] = extrapolation.get("verdict") if extrapolation else None
        result["verdict_after"] = result["verdict_before"]
        return result
    if measured >= 1:
        result["sentence"] = "The reported gain is not interpretable as a speedup; no scaling impact is claimed."
        return result

    speedup = 1.0 / (1.0 - measured)
    result["speedup"] = round(speedup, 6)
    if fit is None or bits is None:
        result["sentence"] = (
            f"A {_percent(measured)} percent gain is about a {speedup:.3g}x speedup, but this prize has no "
            "fitted scaling ladder, so its effect on the real target is unknown."
        )
        return result

    import prize_scaling

    beta = _finite(fit.get("beta"))
    before = extrapolation or prize_scaling.extrapolate(fit, bits)
    shifted = dict(fit)
    shifted["alpha"] = (_finite(fit.get("alpha"), 0.0) or 0.0) - math.log2(speedup)
    after = prize_scaling.extrapolate(shifted, bits)
    bits_equivalent = math.log2(speedup) / beta if beta and beta > 0 else None
    result["bits_equivalent"] = round(bits_equivalent, 4) if bits_equivalent is not None else None
    result["verdict_before"] = before.get("verdict")
    result["verdict_after"] = after.get("verdict")
    moved = "changes" if before.get("verdict") != after.get("verdict") else "does not change"
    equivalent = (
        f" That is worth about {bits_equivalent:.3g} bits of instance size on this ladder."
        if bits_equivalent is not None
        else ""
    )
    result["sentence"] = (
        f"A {_percent(measured)} percent gain is about a {speedup:.3g}x speedup; applied to the {bits}-bit "
        f"target it {moved} the verdict ({before.get('verdict')} -> {after.get('verdict')})." + equivalent
    )
    return result
