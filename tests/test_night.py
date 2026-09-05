import json
import importlib.util
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import night


def _morning_module():
    path = Path(night.HERE) / "scripts" / "morning-research.py"
    spec = importlib.util.spec_from_file_location("morning_research_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _config():
    return night.load_schedule(Path(night.HERE) / "night.json")


def test_trial_is_balanced_and_pglib_is_validation_only():
    config = _config()
    assert config["night"]["budget_usd"] == 90
    assert config["night"]["provider_caps_usd"] == {"fable": 40.0, "astra": 40.0, "paired": 40.0}
    assert sum(slot["slot_budget_usd"] + slot["retro_budget_usd"] for slot in config["slots"]) == 90
    counts = {
        problem: Counter(entry[problem] for entry in config["trial"]["cycle"]) for problem in ("cvrp", "miplib_heur")
    }
    assert counts["cvrp"] == {"fable": 5, "astra": 5, "paired": 4}
    assert counts["miplib_heur"] == {"fable": 5, "astra": 5, "paired": 4}
    first = Counter(entry["order"][0] for entry in config["trial"]["cycle"])
    assert first == {"cvrp": 7, "miplib_heur": 7}
    for offset in range(14):
        run_id = f"2026-09-{5 + offset:02d}"
        slots = night.planned_slots(config, run_id)
        assert slots[-1]["problem"] == "pglib_opf"
        assert slots[-1]["kind"] == "validation"
        command = night._research_command(slots[-1], run_id, Path("ledger"), Path("evidence"), 1)
        assert "--eval-only" in command and "--no-publish" in command


def test_command_separates_per_call_and_slot_caps():
    slot = night.planned_slots(_config(), "2026-09-05")[0]
    command = night._research_command(slot, "2026-09-05", Path("ledger"), Path("evidence"), 1)
    assert command[command.index("--call-budget") + 1] == "2.0"
    assert command[command.index("--budget") + 1] == "40.0"
    assert "--no-publish" in command


def test_scheduled_window_blocks_daytime_catchup():
    assert night.scheduled_window(datetime(2026, 9, 5, 22, 0))
    assert night.scheduled_window(datetime(2026, 9, 6, 5, 59))
    assert not night.scheduled_window(datetime(2026, 9, 6, 6, 0))
    assert not night.scheduled_window(datetime(2026, 9, 6, 12, 0))


def test_after_midnight_schedule_resumes_prior_date_and_caps_at_six():
    current = datetime(2026, 9, 6, 2, 15, tzinfo=timezone(timedelta(hours=-4)))
    assert night.scheduled_run_id(current) == "2026-09-05"
    assert night.scheduled_deadline(current) == datetime(2026, 9, 6, 6, 0, tzinfo=timezone(timedelta(hours=-4)))
    evening = datetime(2026, 9, 5, 22, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert night.scheduled_run_id(evening) == "2026-09-05"
    assert night.scheduled_deadline(evening).date().isoformat() == "2026-09-06"


def test_zero_work_is_not_success():
    assert night.evidence_work_count({"status": "completed", "usage": {"calls": 0}}) == 0
    assert night.evidence_work_count({"usage": {"generation_calls": 1}, "development": {"results": [1, 2]}}) == 3


def test_scheduled_cli_automatically_resumes_existing_checkpoint(tmp_path, monkeypatch):
    import sys

    config = _config()
    config["night"]["evidence_root"] = str(tmp_path)
    checkpoint = tmp_path / "2026-09-05" / "night.json"
    checkpoint.parent.mkdir()
    checkpoint.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["night.py", "--scheduled", "--run-id", "2026-09-05"])
    monkeypatch.setattr(night, "scheduled_window", lambda current: True)
    monkeypatch.setattr(night, "load_schedule", lambda path: config)
    captured = []
    monkeypatch.setattr(
        night, "run_night", lambda config, run_id, **kwargs: captured.append(kwargs) or {"status": "completed"}
    )
    assert night.main() == 0
    assert captured[0]["resume"] is True
    assert captured[0]["deadline_cap"] is not None


def test_completed_night_resume_needs_no_new_provider_or_worker(tmp_path, monkeypatch):
    config = _config()
    config["night"]["evidence_root"] = str(tmp_path)
    checkpoint = tmp_path / "2026-09-05" / "night.json"
    checkpoint.parent.mkdir()
    original = {"run_id": "2026-09-05", "status": "completed"}
    checkpoint.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(night, "LOCK", tmp_path / "night.lock")

    def unavailable(**kwargs):
        raise AssertionError("Completed nights must not launch preflight or new work")

    assert (
        night.run_night(config, "2026-09-05", resume=True, provider_check=unavailable, sandbox_check=unavailable)
        == original
    )


def test_morning_report_surfaces_review_bookmark_without_a_path(tmp_path, monkeypatch):
    morning = _morning_module()
    monkeypatch.setattr(morning, "REPO", tmp_path)
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs/control.json").write_text(
        json.dumps(
            {
                "review_request": {"evidence_path": "runs/research/probe/cvrp/evidence.json"},
            }
        ),
        encoding="utf-8",
    )
    report = morning.build_report({}, "2026-09-05")
    assert report["marked_for_human_review"] == "cvrp"
    assert "evidence.json" not in json.dumps(report)


def test_resume_skips_completed_slots_and_never_publishes(tmp_path, monkeypatch):
    config = _config()
    config["night"]["evidence_root"] = str(tmp_path / "evidence")
    monkeypatch.setattr(night, "ROOT", tmp_path)
    monkeypatch.setattr(night, "HERE", str(tmp_path))
    monkeypatch.setattr(night, "STATUS", str(tmp_path / "runs" / "night-status.json"))
    monkeypatch.setattr(night, "LOCK", tmp_path / "runs" / "night.lock")
    monkeypatch.setattr(night, "paused", lambda _root: False)
    monkeypatch.setattr(night, "publish_slot", lambda *_: (_ for _ in ()).throw(AssertionError("published")))
    calls = []

    def fake_run(command, _log, _deadline, _heartbeat_seconds, heartbeat):
        calls.append(command)
        problem = command[command.index("--problem") + 1]
        run_root = Path(config["night"]["evidence_root"]) / "2026-09-05" / problem
        run_root.mkdir(parents=True, exist_ok=True)
        if command[2].endswith("loop.py"):
            evidence = {
                "status": "completed",
                "provider": command[command.index("--provider") + 1],
                "usage": {"generation_calls": 1} if "--eval-only" not in command else {},
                "development": {"results": []},
                "confirmation": {"results": [1]} if "--eval-only" in command else {"results": []},
            }
            (run_root / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
        else:
            (run_root / "retro.json").write_text(
                json.dumps({"status": "completed", "provider": command[command.index("--provider") + 1]}),
                encoding="utf-8",
            )
        heartbeat()
        return 0, "exited"

    monkeypatch.setattr(night, "_run_bounded", fake_run)
    checks = {
        "provider_check": lambda **_: {"ok": True, "details": {}},
        "sandbox_check": lambda **_: {"ok": True, "details": {}},
    }
    result = night.run_night(config, "2026-09-05", **checks)
    assert result["status"] == "completed"
    assert len(calls) == 5  # two research + two retro + one validation
    calls.clear()
    resumed = night.run_night(config, "2026-09-05", resume=True, **checks)
    assert resumed["status"] == "completed"
    assert calls == []


def test_preflight_failure_starts_no_generation(tmp_path, monkeypatch):
    config = _config()
    config["night"]["evidence_root"] = str(tmp_path / "evidence")
    monkeypatch.setattr(night, "ROOT", tmp_path)
    monkeypatch.setattr(night, "HERE", str(tmp_path))
    monkeypatch.setattr(night, "STATUS", str(tmp_path / "runs" / "night-status.json"))
    monkeypatch.setattr(night, "LOCK", tmp_path / "runs" / "night.lock")
    monkeypatch.setattr(
        night,
        "_run_bounded",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("generation started")),
    )
    result = night.run_night(
        config,
        "2026-09-05",
        provider_check=lambda **_: {"ok": False, "details": {"fable": {"auth_mode": "rejected"}}},
        sandbox_check=lambda **_: {"ok": True, "details": {"worker_image": "ready"}},
    )
    assert result["status"] == "failed"
    assert result["preflight"]["ok"] is False
    assert not (tmp_path / "evidence" / "2026-09-05" / "budget.json").exists()


def test_installer_defaults_to_review_only():
    source = (Path(night.HERE) / "scripts" / "install-night-tasks.ps1").read_text(encoding="utf-8")
    assert "[switch]$Apply" in source
    assert "if (-not $Apply)" in source
    assert "Export-ScheduledTask" in source
    assert "PT8H15M" in source and "--scheduled" in source


def test_morning_report_is_sanitized_and_zero_work_is_visible(tmp_path, monkeypatch):
    morning = _morning_module()
    monkeypatch.setattr(morning, "REPO", tmp_path)
    (tmp_path / "night.json").write_text(json.dumps({"slots": [{"id": "cvrp-research"}]}), encoding="utf-8")
    now = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
    status = {
        "run_id": "2026-09-05",
        "status": "partial",
        "updated_at": "2026-09-06T09:30:00Z",
        "slots": [
            {
                "id": "cvrp-research",
                "problem": "cvrp",
                "kind": "research",
                "provider": "fable",
                "status": "failed",
                "stages": {"research": {"status": "failed", "error": r"C:\private\raw model text"}},
            }
        ],
        "limitations": ["RAW MODEL RESPONSE"],
    }
    report = morning.build_report(
        status,
        "2026-09-05",
        now=now,
        task_info={"name": "discovery-loop-night", "available": True, "last_result": 1},
    )
    rendered = json.dumps(report)
    assert r"C:\private" not in rendered and "RAW MODEL RESPONSE" not in rendered
    assert report["accounting"]["unit"] == "reported_total_cost_usd API-equivalent"
    assert report["accounting"]["actual_cash_billed"] is None
    assert '"cost_usd"' not in rendered and '"charged_usd"' not in rendered
    assert report["fresh"] is True
    assert "scheduled night task returned a failure result" in report["limitations"]
    assert "no research work was recorded" in report["limitations"]
    assert report["failed_stages"] == [{"problem": "cvrp", "stage": "research", "status": "failed"}]


def test_meditation_context_transforms_in_memory_only(tmp_path, monkeypatch):
    morning = _morning_module()
    runner = tmp_path / "run-nightly.sh"
    source = 'CMD=(/c/tool -p "/meditate $MODE")\nCMD=(/c/tool -p "/meditate $MODE")\n'
    runner.write_text(source, encoding="utf-8")
    observed = {}

    def fake_run(command, **kwargs):
        observed.update(command=command, **kwargs)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(morning.subprocess, "run", fake_run)
    result = morning.run_meditation_with_context(
        "bash.exe", [str(runner)], {"status": "partial"}, tmp_path / "morning.json"
    )
    assert result == 0 and observed["command"] == ["bash.exe", "-s"]
    assert "DISCOVERY_LOOP_RESEARCH_REPORT_JSON" in observed["env"]
    assert "MEDITATION_PROMPT" in observed["input"]
    assert runner.read_text(encoding="utf-8") == source
