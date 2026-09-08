import os
import hashlib
import json
import types
import sys

import pytest

import loop
import night
import routing
from model_registry import policy_chain, validate_routing_config
from research_state import BudgetLedger


def _attempt(**changes):
    value = {
        "status": "completed",
        "physical": True,
        "purpose": "generation",
        "family": "anthropic",
        "model": "claude-fable-5-1",
        "requested_family": "anthropic",
        "fallback_depth": 0,
    }
    value.update(changes)
    return value


def test_registry_policies_never_invent_models_and_exact_modes_are_exact():
    assert policy_chain("auto", ["astra", "sol", "opus"], "fable") == ["astra", "sol", "opus"]
    assert policy_chain("ordered", ["astra", "sol", "opus"], "fable") == ["astra", "sol", "opus"]
    assert policy_chain("ordered", ["astra", "sol", "opus"], "astra") == ["astra", "sol", "opus"]
    assert policy_chain("astra_only", ["sol", "astra", "fable"], "fable") == ["astra"]
    assert policy_chain("fable_only", ["opus", "astra"], "fable") == []
    assert policy_chain("scheduled", ["fable", "opus", "astra"], "fable") == ["fable", "opus", "astra"]
    assert validate_routing_config({})["policy"] == "scheduled"


@pytest.mark.parametrize("purpose", ["generation", "critique", "retro:demo"])
def test_ordered_policy_uses_astra_sol_opus_for_every_role(tmp_path, purpose):
    calls = []

    def call(_prompt, provider, model, **_kwargs):
        calls.append((provider, model))
        if model != "claude-opus-5":
            return {"error": "usage exhausted", "error_kind": "usage_limit", "cost": 0.0, "usage": {}}
        return {"error": None, "cost": 0.0, "usage": {}, "text": "ok"}

    response = routing.route_call(
        "prompt",
        requested_alias="fable" if purpose != "generation" else "astra",
        policy="ordered",
        chain=("astra", "sol", "opus"),
        ledger=None,
        max_cost=1.0,
        purpose=purpose,
        call_fn=call,
        journal=routing.RoutingJournal(tmp_path / (purpose.replace(":", "-") + ".json")),
        retry_delay=0,
    )

    assert calls == [
        ("openai", "gpt-6-astra"),
        ("openai", "gpt-5.6-sol"),
        ("anthropic", "claude-opus-5"),
    ]
    assert all(model != "claude-fable-5-1" for _provider, model in calls)
    assert response["model"] == "claude-opus-5"
    summary = routing.routing_summary(
        response["_routing_attempts"],
        requested_arm="astra",
        mode="ordered",
        configured_chain=("astra", "sol", "opus"),
        explicit_override=True,
    )
    assert summary["formal_trial_eligible"] is False
    assert "routing_override" in summary["ineligibility_reasons"]


def test_night_cli_applies_ordered_chain_override(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "night.py",
            "--dry-run",
            "--run-id",
            "2026-09-08",
            "--routing",
            "ordered",
            "--model-chain",
            "astra",
            "sol",
            "opus",
        ],
    )

    assert night.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["routing"] == {
        "policy": "ordered",
        "chain": ["astra", "sol", "opus"],
        "disabled_families": [],
        "override": True,
    }


def test_journal_merges_writers_and_does_not_reclaim_live_owner(tmp_path):
    path = tmp_path / "routing.json"
    first = routing.RoutingJournal(path)
    second = routing.RoutingJournal(path)
    first.append({"attempt_id": "a", "status": "completed"})
    second.append({"attempt_id": "b", "status": "completed"})
    first.append({"attempt_id": "live", "status": "started", "owner_pid": os.getpid(), "scope": "p"})

    assert [item["attempt_id"] for item in second.state["attempts"]] == ["a", "b", "live"]
    assert second.recover_interrupted("p") == []
    assert second.state["attempts"][-1]["status"] == "started"


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific liveness implementation")
def test_windows_liveness_never_calls_os_kill(monkeypatch):
    monkeypatch.setattr(routing.os, "kill", lambda *_: pytest.fail("os.kill must not probe Windows processes"))
    assert routing._pid_alive(99999999) is False


def test_auth_breaker_skips_family_and_preserves_zero_charge(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json", 2.0)
    journal = routing.RoutingJournal(tmp_path / "routing.json")
    calls = []

    def call(_prompt, provider, model, max_cost, ledger, purpose, **_kwargs):
        calls.append((provider, model))
        if provider == "anthropic":
            return {
                "error": "authentication required",
                "error_kind": "authentication",
                "cost": None,
                "usage": {},
                "_accounting_reserved": 0.0,
                "_accounting_charged": 0.0,
            }
        reservation = ledger.reserve(max_cost, purpose)
        ledger.settle(reservation, 0.2)
        return {"error": None, "cost": 0.2, "usage": {}, "text": "ok"}

    response = routing.route_call(
        "prompt",
        requested_alias="fable",
        ledger=ledger,
        max_cost=1.0,
        purpose="generation",
        call_fn=call,
        journal=journal,
        allowance_remaining=lambda: 1.0,
        retry_delay=0,
    )

    assert calls == [("anthropic", "claude-fable-5-1"), ("openai", "gpt-6-astra")]
    assert response["family"] == "openai"
    physical = [item for item in response["_routing_attempts"] if item["physical"]]
    assert [item["charged_allowance"] for item in physical] == [0.0, 0.2]
    assert any(item["status"] == "skipped" and item["model_alias"] == "opus" for item in response["_routing_attempts"])


def test_transient_retry_is_once_and_malformed_response_never_switches(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json", 3.0)
    journal = routing.RoutingJournal(tmp_path / "routing.json")
    sleeps = []
    calls = []

    def call(_prompt, provider, model, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, purpose)
        ledger.settle(reservation, 0.1)
        calls.append(model)
        if len(calls) == 1:
            return {"error": "rate limited", "error_kind": "rate_limited_unclassified", "cost": 0.1, "usage": {}}
        return {"error": None, "cost": 0.1, "usage": {}, "text": "ok"}

    response = routing.route_call(
        "prompt",
        requested_alias="fable",
        ledger=ledger,
        max_cost=1.0,
        purpose="generation",
        call_fn=call,
        journal=journal,
        allowance_remaining=lambda: 3.0,
        retry_delay=0.25,
        sleep_fn=sleeps.append,
    )
    assert calls == ["claude-fable-5-1", "claude-fable-5-1"]
    assert sleeps == [0.25]
    assert response["_routing_attempts"][1]["selection_reason"] == "transient_retry"

    malformed_calls = []

    def malformed(*_args, **_kwargs):
        malformed_calls.append(1)
        return {"error": "bad response", "error_kind": "malformed_response", "cost": None, "usage": {}}

    malformed_response = routing.route_call(
        "prompt",
        requested_alias="astra",
        ledger=None,
        max_cost=1.0,
        purpose="generation",
        call_fn=malformed,
        journal=routing.RoutingJournal(tmp_path / "malformed.json"),
        retry_delay=0,
    )
    assert malformed_response["error_kind"] == "malformed_response"
    assert malformed_calls == [1]


def test_usage_exhaustion_breaks_only_requested_model_then_falls_back(tmp_path):
    journal = routing.RoutingJournal(tmp_path / "routing.json")
    calls = []

    def call(_prompt, model, **_kwargs):
        calls.append(model)
        if model == "claude-fable-5-1":
            return {
                "error": "fable subscription usage limit reached",
                "error_kind": "usage_limit",
                "cost": 0.0,
                "usage": {},
            }
        return {"error": None, "cost": 0.0, "usage": {}, "text": "ok"}

    response = routing.route_call(
        "prompt",
        requested_alias="fable",
        ledger=None,
        max_cost=1.0,
        purpose="generation",
        call_fn=call,
        journal=journal,
        retry_delay=0,
    )

    assert calls == ["claude-fable-5-1", "claude-opus-5"]
    assert response["model"] == "claude-opus-5"
    assert journal.state["model_breakers"]["fable"]["reason"] == "usage_limit"
    assert journal.state["family_breakers"] == {}


def test_all_model_breakers_resume_as_skips_without_new_charge(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json", 10.0)
    journal_path = tmp_path / "routing.json"
    journal = routing.RoutingJournal(journal_path)
    calls = []
    checkpoints = []
    call_observed = []

    def exhausted(_prompt, model, max_cost, ledger, purpose, **_kwargs):
        call_observed.append(journal.state["attempts"][-1]["status"])
        reservation = ledger.reserve(max_cost, purpose)
        ledger.settle(reservation, 0.1)
        calls.append(model)
        return {"error": "usage exhausted", "error_kind": "usage_limit", "cost": 0.1, "usage": {}}

    first = routing.route_call(
        "prompt",
        requested_alias="fable",
        ledger=ledger,
        max_cost=1.0,
        purpose="generation",
        call_fn=exhausted,
        journal=journal,
        checkpoint=lambda: checkpoints.append(journal.state["attempts"][-1]["status"]),
        retry_delay=0,
    )
    spent = ledger.spent
    resumed = routing.RoutingJournal(journal_path)
    second = routing.route_call(
        "prompt",
        requested_alias="fable",
        ledger=ledger,
        max_cost=1.0,
        purpose="generation",
        call_fn=exhausted,
        journal=resumed,
        retry_delay=0,
    )

    assert calls == ["claude-fable-5-1", "claude-opus-5", "gpt-6-astra", "gpt-5.6-sol"]
    assert first["error_kind"] == "usage_limit"
    assert call_observed == ["started"] * 4
    assert checkpoints.count("started") == 4
    assert checkpoints.count("failed") == 4
    assert second["error_kind"] == "routing_unavailable"
    assert all(item["status"] == "skipped" and item["physical"] is False for item in second["_routing_attempts"])
    assert ledger.spent == spent == 0.4


class _RoutedProblem:
    TARGETS = ["dev", "confirmation"]
    DEVELOPMENT_TARGETS = ["dev"]
    VALIDATION_TARGETS = ["confirmation"]
    HOLDOUT = ["confirmation"]
    DEFAULTS = {"time": 1, "workers": 1}
    FAIL_SCORE = -100.0
    TASK = "Improve the solver."

    @staticmethod
    def prompt_for_targets(targets):
        return "development=" + ",".join(targets)

    @staticmethod
    def records_load():
        return {"dev": 0.0, "confirmation": 0.0}

    @staticmethod
    def evaluate(path, _target):
        return json.loads(open(path, encoding="utf-8").read())["value"], {}

    @staticmethod
    def score(value, _record):
        return value

    @staticmethod
    def validate_release(_path, _target, *, record=None):
        return {"ok": False, "supported": False, "metrics": {}}


def _routed_runner(_problem, solver, _target, _budget, _seed, out, **_kwargs):
    value = 2.0 if "VALUE = 2" in open(solver, encoding="utf-8").read() else 1.0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as stream:
        json.dump({"value": value}, stream)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def _run_routed_critique(tmp_path, fail_all_critics=False, captured_prompts=None):
    champion = tmp_path / "best-routed" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("VALUE = 1\n", encoding="utf-8")
    ledger = BudgetLedger(tmp_path / "budget.json", 10.0)
    journal_path = tmp_path / "runs" / "research" / "routed" / "routing.json"
    calls = []

    def model_call(_prompt, provider, model, max_cost, ledger, purpose, **_kwargs):
        if captured_prompts is not None:
            captured_prompts.append((purpose, _prompt))
        reservation = ledger.reserve(max_cost, f"{purpose}:{model}")
        ledger.settle(reservation, 0.1)
        calls.append((purpose, provider, model))
        if purpose == "generation":
            return {"error": None, "cost": 0.1, "usage": {}, "code": "VALUE = 2\n", "idea": "change"}
        if model == "claude-fable-5-1" or fail_all_critics:
            return {"error": "usage exhausted", "error_kind": "usage_limit", "cost": 0.1, "usage": {}}
        return {"error": None, "cost": 0.1, "usage": {}, "text": "reviewed"}

    evidence = loop.run_research(
        "routed",
        provider="astra",
        run_id="routed",
        evidence_root=tmp_path / "runs" / "research",
        routing_journal_path=journal_path,
        root=tmp_path,
        problem_module=_RoutedProblem,
        solver_runner=_routed_runner,
        call_model_fn=model_call,
        ledger=ledger,
        call_budget=1.0,
        invocation_budget=10.0,
        min_effect=0.1,
        iters=1,
        paused_fn=lambda _root: False,
    )
    return evidence, calls, ledger


def test_production_generation_loads_saved_development_retro(tmp_path):
    memory_path = tmp_path / "runs" / "research" / "development-history" / "routed-retro.json"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lessons": "Repeated swaps stalled. C:\\private\\solver.py",
                "next_experiment": "Try a relocation neighborhood.",
                "confirmation": "SEALED_RESULT_MUST_NOT_ENTER_PROMPT",
            }
        ),
        encoding="utf-8",
    )
    prompts = []
    _run_routed_critique(tmp_path, captured_prompts=prompts)
    generation = next(prompt for purpose, prompt in prompts if purpose == "generation")
    assert "Repeated swaps stalled" in generation
    assert "Try a relocation neighborhood" in generation
    assert "untested" in generation.lower()
    assert "SEALED_RESULT_MUST_NOT_ENTER_PROMPT" not in generation
    assert "C:\\private" not in generation


def test_production_research_records_critique_fallback_and_independence(tmp_path):
    evidence, calls, ledger = _run_routed_critique(tmp_path)

    assert calls == [
        ("generation", "astra", "gpt-6-astra"),
        ("critique", "fable", "claude-fable-5-1"),
        ("critique", "fable", "claude-opus-5"),
    ]
    candidate = evidence["development"]["candidates"][0]
    assert candidate["critique"]["model"] == "claude-opus-5"
    assert candidate["critique"]["independent"] is True
    assert evidence["routing"]["fallback_used"] is True
    assert evidence["routing"]["formal_trial_eligible"] is False
    assert "capacity_or_infrastructure_fallback" in evidence["routing"]["ineligibility_reasons"]
    assert ledger.snapshot()["calls"] == 3


def test_pending_candidate_is_checkpointed_when_every_critic_route_stops(tmp_path):
    evidence, calls, ledger = _run_routed_critique(tmp_path, fail_all_critics=True)

    assert evidence["status"] == "provider_unavailable"
    assert [model for purpose, _provider, model in calls if purpose == "critique"] == [
        "claude-fable-5-1",
        "claude-opus-5",
        "gpt-6-astra",
        "gpt-5.6-sol",
    ]
    candidate = evidence["development"]["candidates"][0]
    assert candidate["status"] == "promising_unreviewed"
    assert candidate["candidate_hash"]
    assert (tmp_path / candidate["candidate_path"]).is_file()
    persisted = json.loads((tmp_path / "runs/research/routed/routed/evidence.json").read_text(encoding="utf-8"))
    assert persisted["development"]["candidates"][0]["candidate_hash"] == candidate["candidate_hash"]
    assert ledger.snapshot()["calls"] == 5


def test_paired_first_proposal_survives_second_generation_exhaustion(tmp_path):
    champion = tmp_path / "best-routed" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("VALUE = 1\n", encoding="utf-8")
    ledger = BudgetLedger(tmp_path / "budget.json", 10.0)
    calls = []

    def model_call(_prompt, model, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, f"{purpose}:{model}")
        ledger.settle(reservation, 0.1)
        calls.append((purpose, model))
        if len(calls) == 1:
            return {"error": None, "cost": 0.1, "usage": {}, "code": "VALUE = 2\n", "idea": "first"}
        return {"error": "usage exhausted", "error_kind": "usage_limit", "cost": 0.1, "usage": {}}

    evidence = loop.run_research(
        "routed",
        provider="paired",
        run_id="paired-stop",
        evidence_root=tmp_path / "runs" / "research",
        routing_journal_path=tmp_path / "runs/research/paired-stop/routing.json",
        root=tmp_path,
        problem_module=_RoutedProblem,
        solver_runner=_routed_runner,
        call_model_fn=model_call,
        ledger=ledger,
        call_budget=1.0,
        invocation_budget=10.0,
        min_effect=0.1,
        iters=1,
        paused_fn=lambda _root: False,
    )

    assert evidence["status"] == "provider_unavailable"
    candidate = evidence["development"]["candidates"][0]
    assert candidate["provider"] == "fable"
    assert candidate["candidate_hash"]
    assert candidate["status"] == "promising_unreviewed"
    assert evidence["routing"]["formal_trial_eligible"] is False


def test_development_evaluation_failure_is_invalid_without_model_fallback(tmp_path):
    champion = tmp_path / "best-routed" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("VALUE = 1\n", encoding="utf-8")
    ledger = BudgetLedger(tmp_path / "budget.json", 3.0)
    calls = []

    def model_call(_prompt, model, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, purpose)
        ledger.settle(reservation, 0.1)
        calls.append(model)
        return {"error": None, "cost": 0.1, "usage": {}, "code": "VALUE = 2\n", "idea": "candidate"}

    def failed_candidate_runner(_problem, solver, _target, _budget, _seed, out, **_kwargs):
        if "VALUE = 2" in open(solver, encoding="utf-8").read():
            return types.SimpleNamespace(returncode=2, stdout="", stderr="invalid worker output")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as stream:
            json.dump({"value": 1.0}, stream)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    evidence = loop.run_research(
        "routed",
        provider="fable",
        run_id="invalid-eval",
        evidence_root=tmp_path / "runs" / "research",
        routing_journal_path=tmp_path / "runs/research/invalid-eval/routing.json",
        root=tmp_path,
        problem_module=_RoutedProblem,
        solver_runner=failed_candidate_runner,
        call_model_fn=model_call,
        ledger=ledger,
        call_budget=1.0,
        invocation_budget=3.0,
        min_effect=0.1,
        iters=1,
        paused_fn=lambda _root: False,
    )

    candidate = evidence["development"]["candidates"][0]
    assert candidate["status"] == "evaluation_failed"
    assert candidate["valid"] is False
    assert candidate["comparison"]["candidate_failures"] == 1
    assert calls == ["claude-fable-5-1"]


def test_summary_is_ineligible_without_work_and_when_pair_collapses_family():
    empty = routing.routing_summary([], requested_arm="fable", mode="scheduled")
    assert empty["formal_trial_eligible"] is False
    assert "no_completed_model_call" in empty["ineligibility_reasons"]

    collapsed = routing.routing_summary(
        [
            _attempt(requested_family="anthropic"),
            _attempt(requested_family="openai", model="claude-opus-5"),
        ],
        requested_arm="paired",
        mode="scheduled",
    )
    assert collapsed["formal_trial_eligible"] is False
    assert "paired_families_incomplete" in collapsed["ineligibility_reasons"]


def test_paired_iteration_failure_cannot_hide_behind_earlier_clean_pair():
    records = [
        {"iteration": 0, "family": "anthropic", "generation_error": None},
        {"iteration": 0, "family": "openai", "generation_error": None},
        {"iteration": 1, "family": "anthropic", "generation_error": "failed"},
        {"iteration": 1, "family": "openai", "generation_error": "failed"},
    ]
    assert loop._paired_iterations_complete(records) is False


def test_auto_allocation_reorders_only_primary_and_preserves_fallbacks():
    history = []
    for index in range(3):
        history.extend(
            [
                {
                    "problem": "demo",
                    "iteration": index,
                    "actual_model": "claude-fable-5-1",
                    "role": "generation",
                    "status": "rejected",
                    "valid": True,
                    "novel": False,
                    "promising": False,
                    "elapsed_seconds": 10,
                },
                {
                    "problem": "demo",
                    "iteration": index,
                    "actual_model": "gpt-6-astra",
                    "role": "generation",
                    "status": "promising",
                    "valid": True,
                    "novel": True,
                    "promising": True,
                    "elapsed_seconds": 5,
                },
            ]
        )
    chain, allocation = loop._auto_route_chain("demo", history, ("fable", "opus", "astra", "sol"))
    assert chain == ("opus", "fable", "astra", "sol")
    assert allocation["exploration"][0]["alias"] == "opus"


def test_registered_model_override_routes_exact_primary_and_is_ineligible(tmp_path):
    journal = routing.RoutingJournal(tmp_path / "routing.json")
    seen = []

    def call(_prompt, provider, model, **_kwargs):
        seen.append((provider, model))
        return {"error": None, "cost": 0.0, "usage": {}, "text": "ok"}

    response = routing.route_call(
        "prompt",
        requested_alias="opus",
        policy="scheduled",
        ledger=None,
        max_cost=1.0,
        purpose="generation",
        call_fn=call,
        journal=journal,
        retry_delay=0,
    )
    summary = routing.routing_summary(
        response["_routing_attempts"],
        requested_arm="fable",
        mode="scheduled",
        model_override=True,
    )
    assert seen == [("anthropic", "claude-opus-5")]
    assert summary["formal_trial_eligible"] is False
    assert "model_override" in summary["ineligibility_reasons"]


def test_orphaned_started_attempt_becomes_uncertain(monkeypatch, tmp_path):
    journal = routing.RoutingJournal(tmp_path / "routing.json")
    journal.append(
        {
            "attempt_id": "orphan",
            "status": "started",
            "owner_pid": 123,
            "scope": "p",
            "reserved_allowance": 2.0,
            "charged_allowance": None,
        }
    )
    monkeypatch.setattr(routing, "_pid_alive", lambda _pid: False)

    recovered = journal.recover_interrupted("p")

    assert recovered[0]["status"] == "uncertain"
    assert recovered[0]["error_kind"] == "interrupted_unknown"
    assert recovered[0]["charged_allowance"] == 2.0


def test_resume_keeps_frozen_incumbent_when_current_champion_changed(tmp_path):
    class Problem:
        TARGETS = ["dev", "confirm"]
        DEVELOPMENT_TARGETS = ["dev"]
        VALIDATION_TARGETS = ["confirm"]
        DEFAULTS = {"time": 1, "workers": 1}
        FAIL_SCORE = -100.0
        TASK = "improve"

        @staticmethod
        def prompt_for_targets(targets):
            return ",".join(targets)

        @staticmethod
        def records_load():
            return {"dev": 0.0, "confirm": 0.0}

        @staticmethod
        def evaluate(path, _target):
            return json.loads(open(path, encoding="utf-8").read())["value"], {}

        @staticmethod
        def score(value, _record):
            return value

    champion = tmp_path / "best-demo" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("value = 2\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "research" / "resume" / "demo"
    run_dir.mkdir(parents=True)
    snapshot = run_dir / "legacy_incumbent.py"
    snapshot.write_text("value = 1\n", encoding="utf-8")
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    (run_dir / "evidence.json").write_text(
        json.dumps(
            {
                "run_id": "resume",
                "problem": "demo",
                "provider": "fable",
                "model": None,
                "status": "running",
                "development": {},
                "legacy_incumbent": {"sha256": snapshot_hash, "classification": "frozen"},
            }
        ),
        encoding="utf-8",
    )

    def runner(_problem, _solver, _target, _budget, _seed, out, **_kwargs):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as stream:
            json.dump({"value": 1.0}, stream)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    evidence = loop.run_research(
        "demo",
        provider="fable",
        run_id="resume",
        evidence_root=tmp_path / "runs" / "research",
        root=tmp_path,
        problem_module=Problem,
        solver_runner=runner,
        call_model_fn=lambda *_args, **_kwargs: pytest.fail("no model call expected"),
        iters=0,
    )

    assert snapshot.read_text(encoding="utf-8") == "value = 1\n"
    assert evidence["legacy_incumbent"]["sha256"] == snapshot_hash


def test_development_prompt_has_bounded_rich_history():
    fake = loop.Loop.__new__(loop.Loop)
    fake.P = type(
        "PromptProblem",
        (),
        {
            "TASK": "Improve it.",
            "prompt_for_targets": staticmethod(lambda targets: "targets=" + ",".join(targets)),
        },
    )
    history = [
        {
            "iteration": index,
            "provider": "fable",
            "idea": "[kind: local search] change",
            "status": "rejected",
            "negative_result": "no gain",
            "critique": {"text": "x" * 4000},
        }
        for index in range(80)
    ]
    prompt = fake.build_research_prompt(
        "pass\n",
        ["dev"],
        {"dev": 1.0},
        history,
        hidden_targets=("holdout",),
        retro_memory={
            "lessons": "holdout failed at C:\\private\\run.json",
            "next_experiment": "try bounded neighborhood search",
        },
    )
    assert len(prompt) < 20_000
    assert "[kind: <algorithm family>]" in prompt
    assert '"attempts":80' in prompt
    assert "untested hypothesis" in prompt
    assert "bounded neighborhood search" in prompt
    assert "holdout" not in prompt
    assert "C:\\private" not in prompt
