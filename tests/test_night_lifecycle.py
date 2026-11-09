"""Night run and slot lifecycle: the table, its guard, and every surface that reads or writes it."""

import ast
import importlib.util
import json
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import dashboard
import morning_brief
import night
from night_lifecycle import (
    NIGHT_ACTIVE,
    NIGHT_AT_REST,
    NIGHT_INITIAL,
    NIGHT_LABELS,
    NIGHT_TERMINAL,
    NIGHT_TRANSITIONS,
    ORPHAN_REASON,
    SLOT_INITIAL,
    SLOT_LABELS,
    SLOT_TERMINAL,
    SLOT_TRANSITIONS,
    STALE_AFTER_SECONDS,
    IllegalTransition,
    NightState,
    SlotState,
    StageResult,
    append_attempt,
    assert_transition,
    check_stage_result,
    close_orphaned_attempts,
    latest_attempts,
    next_states,
)

REPO = Path(night.HERE)
RUN_ID = "2026-09-05"
CHECKS = {
    "provider_check": lambda **_: {"ok": True, "details": {}},
    "sandbox_check": lambda **_: {"ok": True, "details": {}},
}

# The stored vocabularies, written out by hand so a change to the module cannot silently move the expectation.
NIGHT_VALUES = ["running", "preflight_retry", "paused", "failed", "partial", "completed"]
SLOT_VALUES = ["running", "skipped", "paused", "completed", "timed_out", "budget_exhausted", "partial", "failed"]
STAGE_VALUES = [
    "completed",
    "partial",
    "failed",
    "timed_out",
    "paused",
    "budget_exhausted",
    "interrupted",
    "error",
    "provider_unavailable",
]
# Every edge comes from a writer line verified in night.py (see the plan's transition list).
NIGHT_EDGES = {
    (None, "running"),
    ("running", "running"),
    ("running", "preflight_retry"),
    ("running", "paused"),
    ("running", "failed"),
    ("running", "partial"),
    ("running", "completed"),
    ("preflight_retry", "preflight_retry"),
    ("preflight_retry", "running"),
    ("preflight_retry", "failed"),
    ("paused", "running"),
    ("failed", "running"),
    ("partial", "running"),
}
_UNFINISHED = ["paused", "failed", "timed_out", "budget_exhausted", "partial"]
SLOT_EDGES = (
    {(None, "running"), (None, "skipped")}
    | {("running", target) for target in ["paused", "completed", "timed_out", "budget_exhausted", "partial", "failed"]}
    | {(source, target) for source in _UNFINISHED for target in ["running", "skipped"]}
)


def _illegal(values, edges):
    return [(source, target) for source in [None, *values] for target in values if (source, target) not in edges]


def _allowed(values, edges, source):
    return [target for target in values if (source, target) in edges]


def _edge_id(edge):
    source, target = edge
    return f"{source or '(none)'}->{target}"


NIGHT_ILLEGAL = _illegal(NIGHT_VALUES, NIGHT_EDGES)
SLOT_ILLEGAL = _illegal(SLOT_VALUES, SLOT_EDGES)


def _table_edges(initial, table):
    return {(None, target.value) for target in initial} | {
        (source.value, target.value) for source, targets in table.items() for target in targets
    }


def _morning_module():
    path = REPO / "scripts" / "morning-research.py"
    spec = importlib.util.spec_from_file_location("morning_research_lifecycle_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- legal transitions are accepted --------------------------------------------------------------------------


def test_the_expected_edge_counts_match_the_plan():
    assert (len(NIGHT_EDGES), len(SLOT_EDGES)) == (13, 18)
    assert (len(NIGHT_ILLEGAL), len(SLOT_ILLEGAL)) == (29, 54)


@pytest.mark.parametrize("edge", sorted(NIGHT_EDGES, key=_edge_id), ids=_edge_id)
def test_legal_night_transition_is_accepted(edge):
    source, target = edge
    assert assert_transition(source, NightState(target)) is NightState(target)


@pytest.mark.parametrize("edge", sorted(SLOT_EDGES, key=_edge_id), ids=_edge_id)
def test_legal_slot_transition_is_accepted(edge):
    source, target = edge
    assert assert_transition(source, SlotState(target), slot_id="cvrp-research") is SlotState(target)


@pytest.mark.parametrize("value", STAGE_VALUES)
def test_every_stage_result_is_accepted_as_written(value):
    result = check_stage_result(value)
    assert result == value and type(result) is str


# --- illegal transitions are refused, with the contract fields ---------------------------------------------


@pytest.mark.parametrize("edge", NIGHT_ILLEGAL, ids=_edge_id)
def test_illegal_night_transition_is_refused(edge):
    source, target = edge
    with pytest.raises(IllegalTransition) as refused:
        assert_transition(source, NightState(target))
    assert refused.value.to_dict() == {
        "error": "illegal_transition",
        "current": source,
        "requested": target,
        "allowed": _allowed(NIGHT_VALUES, NIGHT_EDGES, source),
        "message": f"night: {source or '(none)'} -> {target} is not allowed",
    }


@pytest.mark.parametrize("edge", SLOT_ILLEGAL, ids=_edge_id)
def test_illegal_slot_transition_is_refused(edge):
    source, target = edge
    with pytest.raises(IllegalTransition) as refused:
        assert_transition(source, SlotState(target), slot_id="cvrp-research")
    refusal = refused.value.to_dict()
    assert refusal["error"] == "illegal_transition"
    assert (refusal["current"], refusal["requested"]) == (source, target)
    assert refusal["allowed"] == _allowed(SLOT_VALUES, SLOT_EDGES, source)
    assert refusal["message"] == f"slot cvrp-research: {source or '(none)'} -> {target} is not allowed"


@pytest.mark.parametrize("legacy", ["partial_failure", "unavailable", "unknown"])
def test_an_unrecognised_stored_night_value_cannot_resume(legacy):
    with pytest.raises(IllegalTransition) as refused:
        assert_transition(legacy, NightState.RUNNING)
    assert refused.value.to_dict()["allowed"] == []
    assert next_states(legacy) == []


@pytest.mark.parametrize("value", ["exited", "killed", "unknown", "partial_failure"])
def test_a_stage_result_outside_the_vocabulary_is_refused(value):
    with pytest.raises(IllegalTransition) as refused:
        check_stage_result(value, slot_id="cvrp-research")
    refusal = refused.value.to_dict()
    assert (refusal["current"], refusal["requested"], refusal["allowed"]) == (None, value, STAGE_VALUES)
    assert refusal["message"] == f"stage cvrp-research: (none) -> {value} is not allowed"


def test_refusal_is_a_value_error_with_exactly_the_contract_keys():
    assert issubclass(IllegalTransition, ValueError)
    with pytest.raises(IllegalTransition) as refused:
        assert_transition("completed", NightState.RUNNING)
    assert set(refused.value.to_dict()) == {"error", "current", "requested", "allowed", "message"}
    assert (refused.value.machine, refused.value.current, refused.value.requested) == ("night", "completed", "running")


def test_night_and_slot_tables_never_share_edges_despite_equal_strings():
    assert NightState.RUNNING == SlotState.RUNNING
    assert assert_transition(None, SlotState.SKIPPED) is SlotState.SKIPPED
    with pytest.raises(IllegalTransition):
        assert_transition(None, NightState.PAUSED)
    assert assert_transition("running", NightState.RUNNING) is NightState.RUNNING
    with pytest.raises(IllegalTransition):
        assert_transition("running", SlotState.RUNNING)
    with pytest.raises(TypeError):
        assert_transition(None, "running")


def test_a_second_open_attempt_for_one_slot_id_is_refused_until_the_orphan_is_closed():
    """The 2026-10-03 night stored five open attempts of miplib-heur-research."""
    slots = [{"id": "cvrp-research", "status": "completed"}, {"id": "miplib-heur-research", "status": "running"}]
    with pytest.raises(IllegalTransition) as refused:
        append_attempt(slots, {"id": "miplib-heur-research", "status": "running"})
    assert refused.value.to_dict()["current"] == "running"
    assert "miplib-heur-research" in refused.value.to_dict()["message"]
    assert len(slots) == 2
    with pytest.raises(IllegalTransition):
        append_attempt(slots, {"id": "cvrp-research", "status": "running"})

    closed = close_orphaned_attempts(slots, finished_at="2026-10-04T06:00:00Z")

    assert closed == [slots[1]]
    assert slots[1] == {
        "id": "miplib-heur-research",
        "status": "failed",
        "reason": ORPHAN_REASON,
        "finished_at": "2026-10-04T06:00:00Z",
    }
    append_attempt(slots, {"id": "miplib-heur-research", "status": "running"})
    assert [entry["status"] for entry in slots] == ["completed", "failed", "running"]
    assert close_orphaned_attempts([{"id": "a", "status": "completed"}], finished_at="x") == []


def test_latest_attempts_keep_first_seen_order_and_id_less_records():
    slots = [
        {"id": "a", "status": "failed"},
        {"status": "completed"},
        {"id": "b", "status": "running"},
        {"id": "a", "status": "completed"},
        "not a record",
    ]
    assert latest_attempts(slots) == [
        {"id": "a", "status": "completed"},
        {"status": "completed"},
        {"id": "b", "status": "running"},
    ]
    assert latest_attempts(None) == []


# --- table invariants ----------------------------------------------------------------------------------------


def test_tables_hold_exactly_the_verified_edges():
    assert _table_edges(NIGHT_INITIAL, NIGHT_TRANSITIONS) == NIGHT_EDGES
    assert _table_edges(SLOT_INITIAL, SLOT_TRANSITIONS) == SLOT_EDGES


def test_stored_values_are_verbatim():
    assert [state.value for state in NightState] == NIGHT_VALUES
    assert [state.value for state in SlotState] == SLOT_VALUES
    assert [result.value for result in StageResult] == STAGE_VALUES


@pytest.mark.parametrize(
    ("machine", "initial", "table"),
    [(NightState, NIGHT_INITIAL, NIGHT_TRANSITIONS), (SlotState, SLOT_INITIAL, SLOT_TRANSITIONS)],
    ids=["night", "slot"],
)
def test_every_state_is_reachable_and_each_table_covers_its_enum(machine, initial, table):
    assert set(table) == set(machine)
    assert all(type(target) is machine for targets in table.values() for target in targets)
    assert all(type(state) is machine for state in initial)
    seen = set(initial)
    queue = deque(initial)
    while queue:
        for target in table[queue.popleft()]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    assert seen == set(machine)


def test_terminal_sets_are_the_old_literals_and_only_terminals_lack_exits():
    # night.py:894 compared to "completed"; night.py:982 and :1134 used {"completed", "skipped"}.
    assert NIGHT_TERMINAL == {"completed"}
    assert SLOT_TERMINAL == {"completed", "skipped"}
    for terminal, table in ((NIGHT_TERMINAL, NIGHT_TRANSITIONS), (SLOT_TERMINAL, SLOT_TRANSITIONS)):
        for state, targets in table.items():
            assert (state in terminal) == (not targets), state


def test_active_and_at_rest_partition_the_night_states():
    assert NIGHT_ACTIVE | NIGHT_AT_REST == set(NightState)
    assert not NIGHT_ACTIVE & NIGHT_AT_REST
    assert NIGHT_TERMINAL <= NIGHT_AT_REST
    assert NIGHT_ACTIVE == {"running", "preflight_retry"}
    morning = _morning_module()
    assert morning.TERMINAL == {state.value for state in NIGHT_AT_REST}
    assert morning.TERMINAL == {"completed", "partial", "failed", "paused"}


def test_labels_cover_every_state_with_a_known_tone():
    assert set(NIGHT_LABELS) == set(NightState)
    assert set(SLOT_LABELS) == set(SlotState)
    tones = {tone for _, tone in [*NIGHT_LABELS.values(), *SLOT_LABELS.values()]}
    assert tones <= {"good", "warn", "neutral"}
    assert NIGHT_LABELS[NightState.PARTIAL] == ("Partly finished", "warn")
    assert NIGHT_LABELS[NightState.PREFLIGHT_RETRY] == ("Waiting for Docker", "warn")


def test_night_py_writes_no_status_literal():
    """Every subscript status write in night.py goes through the enum and the guard."""
    tree = ast.parse((REPO / "night.py").read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "status"
            ):
                continue
            if any(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in ast.walk(node.value)):
                offenders.append(node.lineno)
    assert offenders == []


def test_morning_report_keeps_every_lifecycle_value_and_hides_the_rest():
    morning = _morning_module()
    for value in {*NIGHT_VALUES, *SLOT_VALUES, *STAGE_VALUES}:
        assert morning._safe_status(value) == value
    assert morning._safe_status("partial_failure") == "unknown"
    assert morning._safe_status(r"C:\private") == "unknown"


# --- surfaces: night.py --------------------------------------------------------------------------------------


def _isolated_night(tmp_path, monkeypatch):
    config = night.load_schedule(REPO / "night.json")
    config["night"]["evidence_root"] = str(tmp_path / "evidence")
    config["arc"]["enabled"] = False
    monkeypatch.setattr(night, "ROOT", tmp_path)
    monkeypatch.setattr(night, "HERE", str(tmp_path))
    monkeypatch.setattr(night, "STATUS", str(tmp_path / "runs" / "night-status.json"))
    monkeypatch.setattr(night, "LOCK", tmp_path / "runs" / "night.lock")
    monkeypatch.setattr(night, "paused", lambda _root: False)
    return config


def _fake_run(config, calls):
    def fake_run(command, _log, _kill_deadline, _heartbeat_seconds, heartbeat):
        calls.append(command)
        problem = command[command.index("--problem") + 1]
        run_root = Path(config["night"]["evidence_root"]) / RUN_ID / problem
        run_root.mkdir(parents=True, exist_ok=True)
        if command[2].endswith("loop.py"):
            evidence = {
                "status": "completed",
                "usage": {"generation_calls": 1} if "--eval-only" not in command else {},
                "development": {"results": []},
                "confirmation": {"results": [1]} if "--eval-only" in command else {"results": []},
            }
            (run_root / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
        else:
            (run_root / "retro.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        heartbeat()
        return 0, "exited"

    return fake_run


def _stored_checkpoint(tmp_path, config, night_status):
    run_root = Path(config["night"]["evidence_root"]) / RUN_ID
    run_root.mkdir(parents=True, exist_ok=True)
    status = night._new_status(
        config, RUN_ID, time.time() + 3600, run_root / "budget.json", config["night"]["routing"], False
    )
    status["status"] = night_status
    checkpoint = run_root / "night.json"
    checkpoint.write_text(json.dumps(status), encoding="utf-8")
    return checkpoint


def test_resume_closes_an_orphaned_attempt_before_appending_the_next(tmp_path, monkeypatch):
    config = _isolated_night(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(night, "_run_bounded", _fake_run(config, calls))
    first = night.run_night(config, RUN_ID, **CHECKS)
    assert first["status"] == "completed"
    checkpoint = Path(config["night"]["evidence_root"]) / RUN_ID / "night.json"
    # A power-off in the middle of the cvrp slot: the night and that attempt are still stored as running.
    crashed = json.loads(checkpoint.read_text(encoding="utf-8"))
    crashed["status"] = "running"
    crashed.pop("finished_at")
    orphan = next(slot for slot in crashed["slots"] if slot["id"] == "cvrp-research")
    orphan.update(status="running", stages={})
    orphan.pop("finished_at")
    checkpoint.write_text(json.dumps(crashed), encoding="utf-8")
    calls.clear()

    resumed = night.run_night(config, RUN_ID, resume=True, **CHECKS)

    attempts = [slot for slot in resumed["slots"] if slot["id"] == "cvrp-research"]
    assert [attempt["status"] for attempt in attempts] == ["failed", "completed"]
    assert attempts[0]["reason"] == ORPHAN_REASON and attempts[0]["finished_at"]
    assert len(resumed["slots"]) == len(first["slots"]) + 1
    assert not any(slot["status"] == "running" for slot in resumed["slots"])
    assert [command[command.index("--problem") + 1] for command in calls] == ["cvrp", "cvrp"]
    assert resumed["status"] == "completed"
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["slots"] == resumed["slots"]


def test_resume_refuses_an_unrecognised_night_status_and_writes_nothing(tmp_path, monkeypatch):
    config = _isolated_night(tmp_path, monkeypatch)
    monkeypatch.setattr(night, "_run_bounded", lambda *_args, **_kwargs: pytest.fail("a slot started"))
    checkpoint = _stored_checkpoint(tmp_path, config, "partial_failure")
    before = checkpoint.read_bytes()

    with pytest.raises(IllegalTransition) as refused:
        night.run_night(config, RUN_ID, resume=True, **CHECKS)

    assert refused.value.to_dict()["allowed"] == []
    assert checkpoint.read_bytes() == before
    assert not Path(night.STATUS).exists()


def test_cli_refusal_exits_2_with_the_contract_on_stderr(tmp_path, monkeypatch, capsys):
    config = _isolated_night(tmp_path, monkeypatch)
    checkpoint = _stored_checkpoint(tmp_path, config, "partial_failure")
    before = checkpoint.read_bytes()
    monkeypatch.setattr(night, "load_schedule", lambda _path: config)
    monkeypatch.setattr(night, "limit_cpu", lambda _fraction: {"applied": False})
    monkeypatch.setenv("DISCOVERY_CPU_LIMIT", "{}")
    monkeypatch.setattr(night, "_preflight_with_retry", lambda *_args, **_kwargs: pytest.fail("preflight ran"))
    monkeypatch.setattr(sys, "argv", ["night.py", "--resume", "--run-id", RUN_ID])

    assert night.main() == 2

    captured = capsys.readouterr()
    refusal = json.loads(captured.err)
    assert refusal["error"] == "illegal_transition"
    assert (refusal["current"], refusal["requested"], refusal["allowed"]) == ("partial_failure", "running", [])
    assert captured.out == ""
    assert checkpoint.read_bytes() == before


def test_cli_stdout_reports_allowed_next_without_storing_it(monkeypatch, capsys):
    returned = {"run_id": RUN_ID, "status": "partial"}
    monkeypatch.setattr(night, "run_night", lambda _config, _run_id, **_kwargs: returned)
    monkeypatch.setattr(night, "limit_cpu", lambda _fraction: {"applied": False})
    monkeypatch.setenv("DISCOVERY_CPU_LIMIT", "{}")
    monkeypatch.setattr(sys, "argv", ["night.py", "--run-id", RUN_ID])

    assert night.main() == 1

    printed = json.loads(capsys.readouterr().out)
    assert printed["allowed_next"] == ["running"] and printed["status"] == "partial"
    assert "allowed_next" not in returned


def test_load_schedule_refuses_a_duplicated_slot_id(tmp_path):
    schedule = json.loads((REPO / "night.json").read_text(encoding="utf-8"))
    research = [slot for slot in schedule["slots"] if slot["problem"] == "miplib_heur"][0]
    validation = [slot for slot in schedule["slots"] if slot["kind"] == "validation"][0]
    validation["id"] = research["id"]
    path = tmp_path / "night.json"
    path.write_text(json.dumps(schedule), encoding="utf-8")
    with pytest.raises(ValueError, match="each slot id may appear at most once"):
        night.load_schedule(path)


# --- surfaces: dashboard /api/status -------------------------------------------------------------------------


def _iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


def _status(root, night_status=None, *, control=None, raw=None):
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    if control is not None:
        (runs / "control.json").write_text(json.dumps(control), encoding="utf-8")
    if raw is not None:
        (runs / "night-status.json").write_text(raw, encoding="utf-8")
    elif night_status is not None:
        (runs / "night-status.json").write_text(json.dumps(night_status), encoding="utf-8")
    return dashboard.DashboardApp(root, csrf_token="test-token").status()


def test_dashboard_labels_a_partial_night_and_mirrors_the_file(tmp_path):
    stored = {"run_id": RUN_ID, "status": "partial", "updated_at": _iso(datetime.now(timezone.utc)), "slots": []}
    body = _status(tmp_path, stored)
    lifecycle = body["night_lifecycle"]
    assert (lifecycle["label"], lifecycle["tone"]) == ("Partly finished", "warn")
    assert lifecycle["allowed_next"] == ["running"]
    assert (lifecycle["state"], lifecycle["known"], lifecycle["terminal"], lifecycle["active"]) == (
        "partial",
        True,
        False,
        False,
    )
    assert body["night_status"] == stored


def test_dashboard_says_a_silent_running_night_stopped_responding(tmp_path):
    stale = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert 20 * 60 > STALE_AFTER_SECONDS
    lifecycle = _status(tmp_path, {"status": "running", "updated_at": _iso(stale)})["night_lifecycle"]
    assert (lifecycle["state"], lifecycle["display_state"]) == ("running", "stalled")
    assert (lifecycle["label"], lifecycle["tone"], lifecycle["active"]) == ("Run stopped responding", "warn", False)


def test_dashboard_pause_requested_only_while_a_night_is_active(tmp_path):
    fresh = {"status": "running", "updated_at": _iso(datetime.now(timezone.utc))}
    lifecycle = _status(tmp_path, fresh, control={"paused": True})["night_lifecycle"]
    assert (lifecycle["label"], lifecycle["tone"], lifecycle["display_state"]) == ("Pause requested", "warn", "running")
    at_rest = _status(tmp_path, {"status": "partial"}, control={"paused": True})["night_lifecycle"]
    assert at_rest["label"] == "Research paused"
    waiting = _status(tmp_path, {"status": "preflight_retry"}, control={"paused": False})["night_lifecycle"]
    assert (waiting["label"], waiting["active"]) == ("Waiting for Docker", True)


def test_dashboard_never_raises_on_an_unreadable_night_file(tmp_path):
    body = _status(tmp_path, raw="[1, 2]")
    lifecycle = body["night_lifecycle"]
    assert body["night_status"] == {"status": "unavailable"}
    assert (lifecycle["known"], lifecycle["label"], lifecycle["tone"]) == (False, "Awaiting next run", "neutral")
    assert (lifecycle["allowed_next"], lifecycle["display_state"]) == ([], "unknown")


def test_dashboard_counts_each_slot_id_once_at_its_latest_attempt(tmp_path):
    slots = [{"id": "a", "status": "failed"}, {"id": "a", "status": "completed"}, {"id": "b", "status": "running"}]
    lifecycle = _status(tmp_path, {"status": "partial", "slots": slots})["night_lifecycle"]
    assert (lifecycle["slots_finished"], lifecycle["slots_total"]) == (1, 2)
    id_less = _status(tmp_path, {"status": "paused", "slots": [{"status": "completed"}]})["night_lifecycle"]
    assert (id_less["slots_finished"], id_less["slots_total"], id_less["label"]) == (1, 1, "Research paused")


def _function_body(source, name):
    start = source.index(f"function {name}(")
    return source[start : source.index("\n  }\n", start)]


def test_dashboard_stamp_and_count_come_from_the_lifecycle_table():
    source = (REPO / "web" / "app.js").read_text(encoding="utf-8")
    render = _function_body(source, "renderNight")
    assert "status.night_lifecycle" in render
    for field in ("lifecycle.label", "lifecycle.tone", "lifecycle.slots_finished", "lifecycle.slots_total"):
        assert field in render
    assert "partial_failure" not in source and "slot.exit_code" not in source
    assert '"Run in progress"' not in render and '"Review needed"' not in render


def test_morning_page_uses_brief_labels_with_the_status_fallback():
    source = (REPO / "web" / "morning.js").read_text(encoding="utf-8")
    assert "night.label ?? titleCase(night.status)" in source
    assert "night.tone ?? statusKind(night.status)" in source
    assert "stamp(slot.label ?? titleCase(slot.status), slot.tone ?? statusKind(slot.status))" in source
    assert "stamp(titleCase(slot.status)" not in source and "stamp(titleCase(night.status)" not in source


# --- surfaces: morning report and morning brief --------------------------------------------------------------


def test_morning_report_names_budget_exhausted_and_reports_allowed_next(tmp_path, monkeypatch):
    morning = _morning_module()
    monkeypatch.setattr(morning, "REPO", tmp_path)
    (tmp_path / "night.json").write_text(json.dumps({"slots": [{"id": "cvrp-research"}]}), encoding="utf-8")
    status = {
        "run_id": RUN_ID,
        "status": "partial",
        "updated_at": "2026-09-06T09:30:00Z",
        "slots": [
            {
                "id": "cvrp-research",
                "problem": "cvrp",
                "kind": "research",
                "provider": "fable",
                "status": "budget_exhausted",
                "stages": {"research": {"status": "budget_exhausted"}, "retro": {"status": "provider_unavailable"}},
            }
        ],
    }

    report = morning.build_report(status, RUN_ID, now=datetime(2026, 9, 6, 10, tzinfo=timezone.utc))

    assert report["problems"][0]["status"] == "budget_exhausted"
    assert report["allowed_next"] == ["running"]
    assert report["failed_stages"] == [
        {"problem": "cvrp", "stage": "research", "status": "budget_exhausted"},
        {"problem": "cvrp", "stage": "retro", "status": "provider_unavailable"},
    ]
    assert morning.build_report({**status, "status": "completed"}, RUN_ID)["allowed_next"] == []


def _write_night(root, run_id, document):
    path = root / "runs" / "research" / run_id / "night.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_morning_brief_labels_nights_and_slots_and_counts_ids_once(tmp_path):
    def slot(slot_id, problem, status):
        return {"id": slot_id, "problem": problem, "kind": "research", "provider": "fable", "status": status}

    _write_night(
        tmp_path,
        "2026-09-09-scheduled",
        {
            "run_id": "2026-09-09-scheduled",
            "status": "partial",
            "started_at": "2026-09-10T02:00:00Z",
            "slots": [
                slot("cvrp-research", "cvrp", "failed"),
                slot("cvrp-research", "cvrp", "completed"),
                slot("miplib-heur-research", "miplib_heur", "timed_out"),
            ],
        },
    )
    legacy = {
        "run_id": "2026-09-08-scheduled",
        "status": "completed",
        "started_at": "2026-09-09T02:00:00Z",
        "slots": [slot("cvrp-research", "cvrp", "running")],
    }
    legacy_path = _write_night(tmp_path, "2026-09-08-scheduled", legacy)
    before = legacy_path.read_bytes()

    rows = {row["run_id"]: row for row in morning_brief.nights(tmp_path)}

    partial = rows["2026-09-09-scheduled"]
    assert (partial["label"], partial["tone"]) == ("Partly finished", "warn")
    assert (partial["totals"]["slots"], partial["totals"]["completed"]) == (2, 1)
    assert [(row["status"], row["label"]) for row in partial["slots"]] == [
        ("failed", "Failed"),
        ("completed", "Completed"),
        ("timed_out", "Timed out"),
    ]
    orphan = rows["2026-09-08-scheduled"]["slots"][0]
    assert orphan["status"] == "running"
    assert (orphan["label"], orphan["tone"]) == ("Interrupted", "warn")
    assert legacy_path.read_bytes() == before
