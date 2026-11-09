"""Night run and slot lifecycle: the one table for every status night.py writes.

``runs/night-status.json`` and ``runs/research/<run_id>/night.json`` carry three vocabularies: the night's
top-level ``status``, each slot attempt's ``status`` and each stage result under ``slots[].stages``. This module
is the single source for all three, for the legal moves between them and for the labels the dashboard and the
morning brief show. It is pure: no I/O and no imports from ``night`` or ``loop``.

Stored values are kept verbatim. Writers store ``.value`` so the JSON bytes are unchanged. StrEnum members compare
and hash equal to their string value (``NightState.RUNNING == SlotState.RUNNING``), so each machine has its own
table and label dict and ``assert_transition`` dispatches on the requested member's type.

Read paths never call the guard: an unrecognised legacy value reads as ``known: False`` and is never rewritten.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class NightState(StrEnum):
    RUNNING = "running"
    PREFLIGHT_RETRY = "preflight_retry"
    PAUSED = "paused"
    FAILED = "failed"
    PARTIAL = "partial"
    COMPLETED = "completed"


class SlotState(StrEnum):
    RUNNING = "running"
    SKIPPED = "skipped"
    PAUSED = "paused"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PARTIAL = "partial"
    FAILED = "failed"


class StageResult(StrEnum):
    """Vocabulary of ``slots[].stages.{research,retro}.status``; each stage result is written once."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    PAUSED = "paused"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


# The "(none)" row: what a night or a slot id may start as.
NIGHT_INITIAL: tuple[NightState, ...] = (NightState.RUNNING,)
SLOT_INITIAL: tuple[SlotState, ...] = (SlotState.RUNNING, SlotState.SKIPPED)

NIGHT_TRANSITIONS: dict[NightState, tuple[NightState, ...]] = {
    # A crashed night is resumed as running; the preflight wait, a pause, a failed preflight and the final
    # aggregation all leave from running.
    NightState.RUNNING: (
        NightState.RUNNING,
        NightState.PREFLIGHT_RETRY,
        NightState.PAUSED,
        NightState.FAILED,
        NightState.PARTIAL,
        NightState.COMPLETED,
    ),
    # Repeated five-minute Docker waits, then the heartbeat after a good probe or the failed preflight.
    NightState.PREFLIGHT_RETRY: (NightState.RUNNING, NightState.PREFLIGHT_RETRY, NightState.FAILED),
    # An at-rest night only moves again when cron or a person resumes it.
    NightState.PAUSED: (NightState.RUNNING,),
    NightState.FAILED: (NightState.RUNNING,),
    NightState.PARTIAL: (NightState.RUNNING,),
    # Resuming a completed night returns its checkpoint unchanged.
    NightState.COMPLETED: (),
}

_RETRYABLE = (SlotState.RUNNING, SlotState.SKIPPED)
SLOT_TRANSITIONS: dict[SlotState, tuple[SlotState, ...]] = {
    # A new outcome only comes from a running attempt. running -> failed is also the orphan close on resume.
    SlotState.RUNNING: (
        SlotState.PAUSED,
        SlotState.COMPLETED,
        SlotState.TIMED_OUT,
        SlotState.BUDGET_EXHAUSTED,
        SlotState.PARTIAL,
        SlotState.FAILED,
    ),
    SlotState.SKIPPED: (),
    # An unfinished slot gets a new attempt on resume, or is skipped when its mission is now disabled.
    SlotState.PAUSED: _RETRYABLE,
    SlotState.COMPLETED: (),
    SlotState.TIMED_OUT: _RETRYABLE,
    SlotState.BUDGET_EXHAUSTED: _RETRYABLE,
    SlotState.PARTIAL: _RETRYABLE,
    SlotState.FAILED: _RETRYABLE,
}

NIGHT_TERMINAL = frozenset(state for state, targets in NIGHT_TRANSITIONS.items() if not targets)
SLOT_TERMINAL = frozenset(state for state, targets in SLOT_TRANSITIONS.items() if not targets)
# A live night.py process owns an active night; every other state is at rest until the next resume.
NIGHT_ACTIVE = frozenset({NightState.RUNNING, NightState.PREFLIGHT_RETRY})
NIGHT_AT_REST = frozenset(NightState) - NIGHT_ACTIVE

# (label, tone); tone is one of the dashboard stamp classes good, warn, neutral.
NIGHT_LABELS: dict[NightState, tuple[str, str]] = {
    NightState.RUNNING: ("Run in progress", "good"),
    NightState.PREFLIGHT_RETRY: ("Waiting for Docker", "warn"),
    NightState.PAUSED: ("Research paused", "warn"),
    NightState.FAILED: ("Review needed", "warn"),
    NightState.PARTIAL: ("Partly finished", "warn"),
    NightState.COMPLETED: ("Run complete", "good"),
}
SLOT_LABELS: dict[SlotState, tuple[str, str]] = {
    SlotState.RUNNING: ("Running", "good"),
    SlotState.SKIPPED: ("Skipped", "neutral"),
    SlotState.PAUSED: ("Paused", "warn"),
    SlotState.COMPLETED: ("Completed", "good"),
    SlotState.TIMED_OUT: ("Timed out", "warn"),
    SlotState.BUDGET_EXHAUSTED: ("Budget exhausted", "warn"),
    SlotState.PARTIAL: ("Partly finished", "warn"),
    SlotState.FAILED: ("Failed", "warn"),
}
# Display-only states, never stored.
_STALLED_LABEL = ("Run stopped responding", "warn")
_UNKNOWN_NIGHT_LABEL = ("Awaiting next run", "neutral")
_PAUSE_REQUESTED_LABEL = ("Pause requested", "warn")
_INTERRUPTED_LABEL = ("Interrupted", "warn")

# The night heartbeat writes every few seconds while a slot runs and the preflight wait writes every five
# minutes, so a stored running night this old has lost its process.
STALE_AFTER_SECONDS = 600
ORPHAN_REASON = "orphaned_on_resume"

_MACHINES: dict[type, tuple[str, tuple, dict]] = {
    NightState: ("night", NIGHT_INITIAL, NIGHT_TRANSITIONS),
    SlotState: ("slot", SLOT_INITIAL, SLOT_TRANSITIONS),
}


class IllegalTransition(ValueError):
    """A status write the table does not allow; raised before the mutation, so nothing reaches disk."""

    def __init__(self, machine: str, current: Any, requested: str, allowed: list[str], slot_id: Any = None):
        self.machine = machine
        self.current = current
        self.requested = requested
        self.allowed = list(allowed)
        self.slot_id = slot_id
        where = f"{machine} {slot_id}" if slot_id is not None else machine
        shown = "(none)" if current is None else current
        super().__init__(f"{where}: {shown} -> {requested} is not allowed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "illegal_transition",
            "current": self.current,
            "requested": self.requested,
            "allowed": list(self.allowed),
            "message": str(self),
        }


def _parse(machine: type, value: Any):
    if isinstance(value, machine):
        return value
    if not isinstance(value, str):
        return None
    try:
        return machine(value)
    except ValueError:
        return None


def next_states(current: Any, machine: type = NightState) -> list[str]:
    """Stored values reachable from ``current`` in declaration order; [] for a value outside the machine."""
    _, initial, table = _MACHINES[machine]
    if current is None:
        targets = initial
    else:
        state = _parse(machine, current)
        targets = table[state] if state is not None else ()
    return [member.value for member in machine if member in targets]


def assert_transition(current: Any, requested: NightState | SlotState, *, slot_id: Any = None):
    """Return ``requested`` when ``current -> requested`` is in its machine's table, else raise IllegalTransition."""
    machine = type(requested)
    if machine not in _MACHINES:
        raise TypeError("requested must be a NightState or a SlotState member")
    allowed = next_states(current, machine)
    if requested.value not in allowed:
        raise IllegalTransition(_MACHINES[machine][0], current, requested.value, allowed, slot_id)
    return requested


def check_stage_result(value: Any, *, slot_id: Any = None) -> str:
    """Return the stored stage result for ``value``, refusing anything outside StageResult."""
    result = _parse(StageResult, value)
    if result is None:
        raise IllegalTransition("stage", None, str(value), [member.value for member in StageResult], slot_id)
    return result.value


def _latest_for(slots: list, slot_id: Any) -> dict | None:
    return next((entry for entry in reversed(slots) if isinstance(entry, dict) and entry.get("id") == slot_id), None)


def append_attempt(slots: list, record: dict) -> dict:
    """Append a new attempt after checking the latest attempt for the same slot id may move to its status."""
    slot_id = record.get("id")
    requested = SlotState(record["status"])
    latest = _latest_for(slots, slot_id)
    assert_transition(latest.get("status") if latest else None, requested, slot_id=slot_id)
    slots.append(record)
    return record


def close_orphaned_attempts(slots: list, *, finished_at: str) -> list[dict]:
    """Mark every stored running attempt failed with ORPHAN_REASON; returns the closed records.

    Only called on resume, under the night lock: the lock is released when its process dies, so a running
    attempt found here has no process left. The record says the night lost track of it; it does not prove a
    child process died.
    """
    closed = []
    for entry in slots:
        if not isinstance(entry, dict) or entry.get("status") != SlotState.RUNNING:
            continue
        outcome = assert_transition(entry.get("status"), SlotState.FAILED, slot_id=entry.get("id"))
        entry["status"] = outcome.value
        entry["reason"] = ORPHAN_REASON
        entry.setdefault("finished_at", finished_at)
        closed.append(entry)
    return closed


def latest_attempts(slots: Any) -> list[dict]:
    """The latest attempt per slot id in first-seen order; an attempt without an id stands alone."""
    latest: dict[Any, dict] = {}
    for index, entry in enumerate(slots if isinstance(slots, list) else []):
        if isinstance(entry, dict):
            slot_id = entry.get("id")
            # Reassigning a key keeps its first position, so the order is first-seen.
            latest[slot_id if isinstance(slot_id, str) else ("no id", index)] = entry
    return list(latest.values())


def _age_seconds(value: Any, now: datetime) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (now - stamp).total_seconds()


def night_display(night_status: Any, *, paused: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """Read-only view of a night checkpoint for people and agents; never raises on legacy or odd data."""
    status = night_status if isinstance(night_status, dict) else {}
    raw = status.get("status")
    state = _parse(NightState, raw)
    display_state = state.value if state is not None else "unknown"
    current = now or datetime.now(timezone.utc)
    if state is NightState.RUNNING:
        age = _age_seconds(status.get("updated_at"), current)
        if age is not None and age > STALE_AFTER_SECONDS:
            display_state = "stalled"
    active = display_state in NIGHT_ACTIVE
    if paused:
        label, tone = _PAUSE_REQUESTED_LABEL if active else NIGHT_LABELS[NightState.PAUSED]
    elif display_state == "stalled":
        label, tone = _STALLED_LABEL
    elif state is not None:
        label, tone = NIGHT_LABELS[state]
    else:
        label, tone = _UNKNOWN_NIGHT_LABEL
    latest = latest_attempts(status.get("slots"))
    return {
        "state": raw if isinstance(raw, str) else None,
        "known": state is not None,
        "display_state": display_state,
        "label": label,
        "tone": tone,
        "terminal": state in NIGHT_TERMINAL,
        "active": active,
        "allowed_next": next_states(raw),
        "slots_finished": sum(1 for entry in latest if entry.get("status") == SlotState.COMPLETED),
        "slots_total": len(latest),
    }


def slot_label(night_status: Any, slot_status: Any) -> tuple[str | None, str | None]:
    """(label, tone) for one slot attempt; (None, None) for a value outside SlotState.

    A running attempt inside an at-rest night reads Interrupted: the night stopped and nothing closed it.
    The stored value stays running; legacy files are read, never rewritten.
    """
    state = _parse(SlotState, slot_status)
    if state is None:
        return None, None
    night = _parse(NightState, night_status)
    if state is SlotState.RUNNING and night in NIGHT_AT_REST:
        return _INTERRUPTED_LABEL
    return SLOT_LABELS[state]
