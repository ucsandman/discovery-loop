import json
import sys
import types
from pathlib import Path

import night
import pytest
import retro
import routing
from research_state import BudgetLedger, atomic_json


def test_schema_two_schedule_without_routing_uses_the_legacy_paired_default(tmp_path):
    source = json.loads((Path(night.HERE) / "night.json").read_text(encoding="utf-8"))
    del source["night"]["routing"]
    path = tmp_path / "night.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    config = night.load_schedule(path)

    assert config["schema_version"] == 2
    assert config["night"]["routing"] == {
        "policy": "scheduled",
        "chain": ["fable", "opus", "astra", "sol"],
        "disabled_families": [],
    }


def test_preflight_only_checks_families_reachable_after_a_disable():
    config = night.load_schedule()
    config["night"]["routing"] = {
        "policy": "auto",
        "chain": ["astra", "sol"],
        "disabled_families": ["anthropic"],
    }
    seen = {}

    result = night._preflight(
        config,
        night.planned_slots(config, "2026-09-05"),
        provider_check=lambda **kwargs: seen.update(kwargs) or {"ok": True, "details": {"astra": {"ok": True}}},
        sandbox_check=lambda **_: {"ok": True},
    )

    assert seen["providers"] == ("astra",)
    assert result["ok"] is True
    assert result["available_families"] == ["openai"]


def test_resume_rejects_a_changed_routing_configuration(tmp_path, monkeypatch):
    config = night.load_schedule()
    config["night"]["evidence_root"] = str(tmp_path / "research")
    monkeypatch.setattr(night, "ROOT", tmp_path)
    monkeypatch.setattr(night, "HERE", str(tmp_path))
    monkeypatch.setattr(night, "STATUS", str(tmp_path / "runs" / "night-status.json"))
    monkeypatch.setattr(night, "LOCK", tmp_path / "runs" / "night.lock")
    first = night.run_night(
        config,
        "2026-09-05",
        provider_check=lambda **_: {"ok": False, "details": {"fable": {"ok": False}, "astra": {"ok": False}}},
        sandbox_check=lambda **_: {"ok": True},
    )
    assert first["status"] == "failed"
    config["night"]["routing"]["policy"] = "openai_only"

    with pytest.raises(ValueError, match="preserve the configured routing policy"):
        night.run_night(config, "2026-09-05", resume=True)


def test_retro_fallback_is_journaled_and_uses_bounded_development_only_history(tmp_path, monkeypatch):
    root = tmp_path / "research"
    problem_root = root / "2026-09-05" / "cvrp"
    problem_root.mkdir(parents=True)
    (problem_root / "evidence.json").write_text(
        json.dumps(
            {
                "run_id": "2026-09-05",
                "problem": "cvrp",
                "provider": "astra",
                "confirmed": True,
                "candidate_hash": "hidden",
            }
        ),
        encoding="utf-8",
    )
    history = root / "development-history" / "cvrp.jsonl"
    history.parent.mkdir()
    history.write_text(
        "\n".join(
            json.dumps(
                {
                    "iteration": index,
                    "provider": "astra",
                    "idea": f"idea {index}",
                    "status": "rejected",
                    "candidate_hash": "hidden",
                    "confirmed": True,
                }
            )
            for index in range(100)
        ),
        encoding="utf-8",
    )
    ledger = root / "2026-09-05" / "budget.json"
    BudgetLedger(ledger, 45.0)
    prompts, models = [], []

    def call_model(prompt, **kwargs):
        prompts.append(prompt)
        models.append(kwargs["model"])
        if kwargs["model"] == "claude-fable-5-1":
            return {"text": "", "cost": 0.0, "usage": {}, "error": "limit", "error_kind": "usage_limit"}
        return {"text": "### Evidence assessment\nOK", "cost": 0.2, "usage": {}, "error": None}

    monkeypatch.setitem(sys.modules, "providers", types.SimpleNamespace(call_model=call_model))
    result = retro.run_research_retro("cvrp", "2026-09-05", root, ledger, 2.5, provider="fable")

    assert models == ["claude-fable-5-1", "claude-opus-5"]
    assert result["routing"]["fallback_used"] is True
    assert result["routing"]["formal_trial_eligible"] is False
    assert "hidden" not in prompts[0] and "confirmed" not in prompts[0]
    assert prompts[0].count('"iteration"') == 20

    models.clear()
    retro.run_research_retro("cvrp", "2026-09-05", root, ledger, 2.5, provider="fable")
    assert models == []


def test_retro_recovers_an_orphaned_attempt_and_preserves_its_invocation_cap(tmp_path, monkeypatch):
    root = tmp_path / "research"
    problem_root = root / "2026-09-05" / "cvrp"
    problem_root.mkdir(parents=True)
    (problem_root / "evidence.json").write_text(json.dumps({"provider": "fable"}), encoding="utf-8")
    ledger = root / "2026-09-05" / "budget.json"
    BudgetLedger(ledger, 45.0)
    journal = root / "2026-09-05" / "routing.json"
    atomic_json(
        journal,
        {
            "schema_version": 1,
            "disabled_families": [],
            "model_breakers": {},
            "family_breakers": {},
            "attempts": [
                {
                    "attempt_id": "orphan",
                    "scope": "cvrp:retro",
                    "status": "started",
                    "owner_pid": -1,
                    "reserved_allowance": 2.5,
                    "charged_allowance": None,
                }
            ],
        },
    )
    monkeypatch.setitem(
        sys.modules,
        "providers",
        types.SimpleNamespace(
            call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cap must stop a new call"))
        ),
    )
    monkeypatch.setattr(routing, "_pid_alive", lambda _pid: False)

    result = retro.run_research_retro("cvrp", "2026-09-05", root, ledger, 2.5, provider="astra")
    saved = json.loads(journal.read_text(encoding="utf-8"))["attempts"][0]

    assert result["status"] == "failed"
    assert result["routing"]["formal_trial_eligible"] is False
    assert "uncertain_interrupted_attempt" in result["routing"]["ineligibility_reasons"]
    assert saved["status"] == "uncertain"
    assert saved["charged_allowance"] == 2.5


def test_successful_retro_writes_bounded_sanitized_hypothesis_memory_and_failure_preserves_it(tmp_path, monkeypatch):
    root = tmp_path / "research"
    problem_root = root / "2026-09-05" / "cvrp"
    problem_root.mkdir(parents=True)
    (problem_root / "evidence.json").write_text(json.dumps({"provider": "fable"}), encoding="utf-8")
    (problem_root / "run.json").write_text(
        json.dumps({"manifest": {"validation": ["hidden-target"], "confirmation": [], "release_holdout": []}}),
        encoding="utf-8",
    )
    ledger = root / "2026-09-05" / "budget.json"
    BudgetLedger(ledger, 45.0)
    analysis = (
        "### Evidence assessment\nhidden-target C:\\private\\raw "
        + "a" * 1200
        + "\n### Failure analysis\nfailed\n### Next experiment\nhidden-target C:\\private\\next "
        + "b" * 1200
        + "\n### Limitations\none"
    )
    monkeypatch.setitem(
        sys.modules,
        "providers",
        types.SimpleNamespace(
            call_model=lambda *_args, **_kwargs: {"text": analysis, "cost": 0.1, "usage": {}, "error": None}
        ),
    )

    result = retro.run_research_retro("cvrp", "2026-09-05", root, ledger, 2.5, provider="astra")
    memory_path = root / "development-history" / "cvrp-retro.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8"))

    assert result["status"] == "completed"
    assert set(memory) == {
        "schema_version",
        "source_run_id",
        "actual_analyst_model",
        "analyst_family",
        "lessons",
        "next_experiment",
        "updated_at",
    }
    assert memory["source_run_id"] == "2026-09-05"
    assert len(memory["lessons"]) <= 1000 and len(memory["next_experiment"]) <= 1000
    assert "hidden-target" not in json.dumps(memory) and r"C:\private" not in json.dumps(memory)

    prior = memory_path.read_text(encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "providers",
        types.SimpleNamespace(
            call_model=lambda *_args, **_kwargs: {"text": "", "cost": None, "usage": {}, "error": "unavailable"}
        ),
    )
    failed = retro.run_research_retro("cvrp", "2026-09-05", root, ledger, 2.5, provider="astra")
    assert failed["status"] == "failed"
    assert memory_path.read_text(encoding="utf-8") == prior
