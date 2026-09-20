import io
import json
import shutil
from pathlib import Path

import pytest

import night
import prize_registry
from scripts import prize_hunt


REPO = Path(night.HERE)
# admission() only checks that problems/<plugin>/{problem.py,verify.py} exist under the root it is
# given, so a tmp root needs the real registry file and empty stubs for the bound plugins.
BOUND_PLUGINS = ("ecc_prize", "hash_collision_prize", "circle_packing", "matrix_multiplication", "cvrp")


def _registry_root(tmp_path):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    shutil.copy(REPO / "data" / "prizes.json", root / "data" / "prizes.json")
    for plugin in BOUND_PLUGINS:
        folder = root / "problems" / plugin
        folder.mkdir(parents=True)
        (folder / "problem.py").write_text("", encoding="utf-8")
        (folder / "verify.py").write_text("", encoding="utf-8")
    return root


def _document():
    return json.loads((REPO / "night.json").read_text(encoding="utf-8"))


def _schedule(tmp_path, document):
    path = tmp_path / "night.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _config(**prizes):
    config = night.load_schedule(REPO / "night.json")
    config["arc"] = {"enabled": False, "source_checkout": "../arc-agi-n"}
    if prizes:
        config["prizes"] = {**config["prizes"], **prizes}
    return config


def test_committed_schedule_keeps_prizes_disabled_and_changes_nothing(tmp_path):
    config = night.load_schedule(REPO / "night.json")
    assert config["prizes"]["enabled"] is False
    slots = night.planned_slots(config, "2026-09-05")
    extra, summary = night._prepare_prizes(config, slots, "2026-09-05", tmp_path)
    assert extra == []
    assert summary["status"] == "disabled" and summary["slot"] is None and summary["mission"] is None
    assert night._with_prize_slots(slots, extra) is slots
    assert [slot["id"] for slot in slots][-1] == "pglib-validation"
    assert not (tmp_path / "runs").exists()


def test_enabled_block_inserts_one_bounded_prize_slot_before_validation(tmp_path):
    root = _registry_root(tmp_path)
    config = _config(enabled=True)
    slots = night.planned_slots(config, "2026-09-05")
    extra, summary = night._prepare_prizes(config, slots, "2026-09-05", root)
    assert len(extra) == 1
    slot = extra[0]
    assert summary["status"] == "selected" and summary["prize_id"] == slot["prize_id"]
    binding = prize_registry.PRIZE_BINDINGS[slot["prize_id"]]
    assert slot["problem"] == binding["plugin"]
    assert slot["problem"] not in {other["problem"] for other in slots}
    assert slot["kind"] == "research" and slot["id"] == f"prize-{slot['prize_id']}"
    assert 0 < slot["per_call_budget_usd"] <= slot["slot_budget_usd"] <= binding["max_slot_budget_usd"]
    assert slot["per_call_budget_usd"] <= binding["max_per_call_budget_usd"]
    assert slot["minutes"] <= binding["max_minutes"]
    assert slot["slot_budget_usd"] <= config["prizes"]["slot_budget_usd"]
    threshold = night._promotion_threshold(slot["problem"])
    assert slot["seed_count"] >= threshold["seed_count"]
    assert slot["min_effect"] >= threshold["min_effect"]
    ordered = night._with_prize_slots(slots, extra)
    assert [entry["id"] for entry in ordered[-2:]] == [slot["id"], "pglib-validation"]
    assert summary["mission"]["schema_version"] == 1
    assert summary["mission"]["prize_id"] == slot["prize_id"]
    assert summary["mission"]["registry_hash"] == summary["registry_hash"]
    assert summary["mission"]["budget"]["seed_count"] == slot["seed_count"]


def test_a_block_over_every_binding_ceiling_selects_nothing_and_says_why(tmp_path):
    root = _registry_root(tmp_path)
    config = _config(
        enabled=True,
        minutes=300,
        research_minutes=280,
        retro_minutes=20,
        slot_budget_usd=30.0,
        per_call_budget_usd=3.0,
    )
    slots = night.planned_slots(config, "2026-09-05")
    extra, summary = night._prepare_prizes(config, slots, "2026-09-05", root)
    assert extra == [] and summary["status"] == "none" and summary["slot"] is None
    reasons = [row["reason"] for row in summary["dropped"]]
    assert summary["dropped"] and all(reasons)
    assert any("300 minutes" in reason for reason in reasons)


def test_a_plugin_already_scheduled_tonight_is_dropped_not_double_booked(tmp_path):
    root = _registry_root(tmp_path)
    config = _config(enabled=True)
    slots = night.planned_slots(config, "2026-09-05")
    slots.insert(0, {"id": "circle-packing-research", "problem": "circle_packing", "kind": "research", "minutes": 30})
    extra, summary = night._prepare_prizes(config, slots, "2026-09-05", root)
    dropped = {row["prize_id"]: row["reason"] for row in summary["dropped"]}
    assert dropped["packomania-csqv-records"] == "circle_packing already has a slot tonight"
    assert dropped["cvrplib-x-open"] == "cvrp already has a slot tonight"
    assert dropped["matmul-rank-records"] == "matrix_multiplication already has a slot tonight"
    assert extra and extra[0]["problem"] not in {slot["problem"] for slot in slots}


def test_load_schedule_rejects_a_prize_block_that_does_not_fit(tmp_path):
    """The committed schedule has no headroom, so the refusal has to name the exact shortfall."""
    document = _document()
    document["prizes"]["enabled"] = True
    with pytest.raises(ValueError, match="past its deadline") as deadline:
        night.load_schedule(_schedule(tmp_path, document))
    assert "600 planned minutes against a 540-minute deadline, 60 minutes over" in str(deadline.value)

    document["slots"][0].update(minutes=150, research_minutes=120, retro_minutes=30)
    with pytest.raises(ValueError, match="exceed the night budget") as money:
        night.load_schedule(_schedule(tmp_path, document))
    assert "$115.00 planned against a $105.00 budget, $10.00 over" in str(money.value)

    # The reduction the shortfall asks for, and the one docs/PRIZE-HUNT.md documents, is enough.
    document["slots"][0]["slot_budget_usd"] = 30.0
    config = night.load_schedule(_schedule(tmp_path, document))
    assert config["prizes"]["enabled"] is True


@pytest.mark.parametrize(
    "block,message",
    [
        ([], "boolean enabled flag"),
        ({"enabled": "yes"}, "boolean enabled flag"),
        ({"enabled": True, "minutes": 10, "research_minutes": 8, "retro_minutes": 4}, "fit inside the prize slot"),
        (
            {
                "enabled": True,
                "minutes": 10,
                "research_minutes": 8,
                "retro_minutes": 2,
                "slot_budget_usd": 1.0,
                "per_call_budget_usd": 2.0,
            },
            "within its slot cap",
        ),
        (
            {
                "enabled": True,
                "minutes": 10,
                "research_minutes": 8,
                "retro_minutes": 2,
                "slot_budget_usd": 1.0,
                "per_call_budget_usd": 0.5,
                "provider": "opus",
            },
            "prize provider must be",
        ),
    ],
)
def test_load_schedule_validates_an_enabled_block(tmp_path, block, message):
    document = _document()
    document["prizes"] = block
    with pytest.raises(ValueError, match=message):
        night.load_schedule(_schedule(tmp_path, document))


def test_prize_slot_command_carries_its_own_budgets(tmp_path):
    root = _registry_root(tmp_path)
    config = _config(enabled=True)
    slots = night.planned_slots(config, "2026-09-05")
    extra, _ = night._prepare_prizes(config, slots, "2026-09-05", root)
    slot = extra[0]
    command = night._research_command(slot, "2026-09-05", Path("ledger"), Path("evidence"), 45)
    assert command[command.index("--problem") + 1] == slot["problem"]
    assert command[command.index("--budget") + 1] == str(slot["effective_slot_budget_usd"])
    assert command[command.index("--call-budget") + 1] == str(slot["per_call_budget_usd"])
    assert command[command.index("--seed-count") + 1] == str(slot["seed_count"])
    assert command[command.index("--min-effect") + 1] == str(slot["min_effect"])
    assert "--no-publish" in command and "--eval-only" not in command


def _fake_runner(config, calls):
    def fake_run(command, _log, _deadline, _heartbeat_seconds, heartbeat):
        calls.append(command)
        problem = command[command.index("--problem") + 1]
        run_root = Path(config["night"]["evidence_root"]) / "2026-09-05" / problem
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


def _patch_night(monkeypatch, root, tmp_path):
    monkeypatch.setattr(night, "ROOT", root)
    monkeypatch.setattr(night, "HERE", str(root))
    monkeypatch.setattr(night, "STATUS", str(tmp_path / "night-status.json"))
    monkeypatch.setattr(night, "LOCK", tmp_path / "night.lock")
    monkeypatch.setattr(night, "paused", lambda _root: False)


CHECKS = {
    "provider_check": lambda **_: {"ok": True, "details": {}},
    "sandbox_check": lambda **_: {"ok": True, "details": {}},
}


def test_run_night_runs_the_prize_slot_and_records_its_mission(tmp_path, monkeypatch):
    root = _registry_root(tmp_path)
    config = _config(enabled=True)
    config["night"]["evidence_root"] = str(root / "evidence")
    _patch_night(monkeypatch, root, tmp_path)
    calls = []
    monkeypatch.setattr(night, "_run_bounded", _fake_runner(config, calls))
    result = night.run_night(config, "2026-09-05", **CHECKS)
    assert result["status"] == "completed"
    assert len(calls) == 9  # four research + four retro + one validation
    summary = result["prizes"]
    assert summary["status"] == "selected"
    ids = [entry["id"] for entry in result["slots"]]
    assert ids[-2:] == [f"prize-{summary['prize_id']}", "pglib-validation"]
    assert result["slots"][-2]["prize_id"] == summary["prize_id"]
    mission_path = root / "evidence" / "2026-09-05" / summary["plugin"] / "prize-mission.json"
    mission = json.loads(mission_path.read_text(encoding="utf-8"))
    assert mission["prize_id"] == summary["prize_id"] and mission["schema_version"] == 1
    assert "nothing is submitted" in mission["note"].lower()
    assert not any("--mission" in command for command in calls)


def test_resume_replays_the_checkpointed_prize_choice(tmp_path, monkeypatch):
    root = _registry_root(tmp_path)
    config = _config(enabled=True)
    config["night"]["evidence_root"] = str(root / "evidence")
    _patch_night(monkeypatch, root, tmp_path)
    stored = {
        "id": "prize-todd-ripemd160-collision",
        "problem": "hash_collision_prize",
        "kind": "research",
        "provider": "paired",
        "prize_id": "todd-ripemd160-collision",
        "minutes": 60.0,
        "research_minutes": 45.0,
        "retro_minutes": 15.0,
        "slot_budget_usd": 1.25,
        "effective_slot_budget_usd": 1.25,
        "per_call_budget_usd": 1.0,
        "retro_budget_usd": 2.0,
        "iters": 20,
        "seed_count": 5,
        "min_effect": 0.05,
        "time_per_target": 60.0,
        "workers": 2,
    }
    checkpoint = root / "evidence" / "2026-09-05" / "night.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        json.dumps(
            {
                "run_id": "2026-09-05",
                "status": "partial",
                "deadline": night._iso(night.time.time() + 3600),
                "routing": {**config["night"]["routing"], "override": False},
                "slots": [],
                "limitations": [],
                "arc": {},
                "prizes": {
                    "status": "selected",
                    "prize_id": stored["prize_id"],
                    "plugin": stored["problem"],
                    "slot": stored,
                },
            }
        ),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(night, "_run_bounded", _fake_runner(config, calls))
    result = night.run_night(config, "2026-09-05", resume=True, **CHECKS)
    assert result["prizes"]["resumed"] is True
    assert result["prizes"]["prize_id"] == stored["prize_id"]
    launched = [
        command[command.index("--budget") + 1]
        for command in calls
        if command[2].endswith("loop.py") and command[command.index("--problem") + 1] == stored["problem"]
    ]
    assert launched == ["1.25"]
    assert [entry["id"] for entry in result["slots"]][-2:] == [stored["id"], "pglib-validation"]


def test_prize_hunt_next_prints_only_flags_loop_accepts():
    flags = prize_hunt.loop_cli_flags(REPO)
    assert {"--no-publish", "--wall-minutes", "--evidence-root"} <= flags
    result = prize_hunt.next_command(REPO, provider="paired", run_id="2026-09-05")
    command = result["command"]
    assert command[:2] == ["python", "loop.py"]
    assert {token for token in command if token.startswith("--")} <= flags
    binding = prize_registry.PRIZE_BINDINGS[result["prize_id"]]
    assert result["plugin"] == binding["plugin"]
    assert command[command.index("--problem") + 1] == binding["plugin"]
    assert command[command.index("--budget") + 1] == f"{binding['max_slot_budget_usd']:g}"
    assert command[command.index("--call-budget") + 1] == f"{binding['max_per_call_budget_usd']:g}"
    assert command[command.index("--wall-minutes") + 1] == f"{binding['max_minutes']:g}"
    assert command[command.index("--run-id") + 1] == "2026-09-05"
    assert command[-1] == "--no-publish"


def test_prize_hunt_next_refuses_a_flag_loop_no_longer_accepts():
    # Positive control for the flag check: drop one flag from the parser and the command must fail.
    flags = prize_hunt.loop_cli_flags(REPO) - {"--wall-minutes"}
    with pytest.raises(ValueError, match="--wall-minutes"):
        prize_hunt.next_command(REPO, flags=flags)


def test_prize_hunt_board_and_allocate_read_without_writing(tmp_path):
    root = _registry_root(tmp_path)
    stream = io.StringIO()
    assert prize_hunt.board(root, stream) == 0
    assert prize_hunt.allocate(root, stream, allowance=10.0, minutes=60.0, moonshot_share=0.2, max_share=0.5) == 0
    assert prize_hunt.economics(root, stream, problem="ecc_prize") == 0
    assert prize_hunt.scaling(root, stream, prize_id="certicom-eccp-131") == 0
    output = stream.getvalue()
    assert "Prize board" in output and prize_registry.CLAIM_NOTE in output
    assert "nothing is spent by this command" in output
    assert prize_hunt.scaling(root, stream, prize_id="no-such-prize") == 1
    assert not (root / "runs").exists()


def test_prize_hunt_contracts_reports_every_installed_prize_plugin():
    stream = io.StringIO()
    assert prize_hunt.contracts(REPO, stream) == 0
    out = stream.getvalue()
    for plugin in ("circle_packing", "ecc_prize", "hash_collision_prize", "matrix_multiplication"):
        assert f"{plugin:<26} ok" in out
    assert "0 of 4 prize plugins fail the contract" in out
