import json
import os
import types

import loop
import research_memory
from research_state import BudgetLedger


class MemoryProblem:
    TARGETS = ["dev", "validation"]
    DEVELOPMENT_TARGETS = ["dev"]  # noqa
    VALIDATION_TARGETS = ["validation"]  # noqa
    HOLDOUT = []
    DEFAULTS = {"time": 1, "workers": 1}
    FAIL_SCORE = -100.0
    PROMPT = "legacy prompt"
    TASK = "write the solver"

    @staticmethod
    def prompt_for_targets(targets):
        return "development targets: " + ",".join(targets)

    @staticmethod
    def records_load():
        return {"dev": 0.0, "validation": 0.0}

    @staticmethod
    def evaluate(path, _target):
        return json.loads(open(path, encoding="utf-8").read())["value"], {}

    @staticmethod
    def score(value, _record):
        return value


def _root(tmp_path):
    champion = tmp_path / "best-memory" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("incumbent = True\n", encoding="utf-8")
    return champion


def _runner(_problem, solver, _target, _budget, _seed, out, **_kwargs):
    source = open(solver, encoding="utf-8").read()
    value = 0.0 if "new_mechanism" in source else 1.0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as stream:
        json.dump({"value": value}, stream)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def _model(code, idea, prompts):
    def call(prompt, provider, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, f"{provider}:{purpose}")
        ledger.settle(reservation, 0.1)
        prompts.append(prompt)
        return {
            "text": "",
            "code": code,
            "idea": idea,
            "provider": provider,
            "model": "gpt-6-astra",
            "cost": 0.1,
            "usage": {},
            "error": None,
        }

    return call


def _run(tmp_path, run_id, code, idea, prompts, *, iters=1):
    allowance = 0.5 * iters
    return loop.run_research(
        "memory",
        provider="astra",
        run_id=run_id,
        call_budget=0.5,
        seed_count=1,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=iters,
        invocation_budget=allowance,
        root=tmp_path,
        problem_module=MemoryProblem,
        call_model_fn=_model(code, idea, prompts),
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / f"{run_id}-ledger.json", allowance),
        paused_fn=lambda _root: False,
        routing_journal_path=tmp_path / "runs" / "research" / run_id / "routing.json",
    )


def test_next_run_rejects_exact_ast_duplicate_older_than_prompt_window(tmp_path):
    _root(tmp_path)
    history_path = tmp_path / "runs" / "research" / "development-history" / "memory.jsonl"
    history_path.parent.mkdir(parents=True)
    old_code = "answer = 1\n"
    old_fingerprint = research_memory.analyze_candidate(old_code)["fingerprint"]
    rows = [
        {
            "run_id": "2026-09-08",
            "iteration": 0,
            "idea": "[kind: prior] saved September 8 candidate",
            "development_status": "rejected",
            "fingerprint": old_fingerprint,
        }
    ]
    rows.extend(
        {
            "run_id": f"newer-{number}",
            "iteration": number,
            "idea": f"[kind: newer] candidate {number}",
            "development_status": "rejected",
            "fingerprint": f"{number + 1:064x}",
        }
        for number in range(81)
    )
    rows.append({"run_id": "2026-09-08", "status": "retrospective", "fingerprint": "f" * 64})
    history_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    loaded = loop._read_development_memory(history_path)
    assert old_fingerprint in loaded["fingerprints"]
    assert "f" * 64 not in loaded["fingerprints"]
    assert len(loaded["history"]) == 80
    assert loaded["total_observations"] == 82

    prompts = []
    evidence = _run(
        tmp_path,
        "next-run-duplicate",
        "answer=1  # formatting changed\n",
        "[kind: prior] repeat the saved candidate",
        prompts,
        iters=2,
    )
    candidate = evidence["development"]["candidates"][0]
    assert candidate["status"] == "duplicate"
    assert candidate["negative_result"] == "exact AST duplicate"
    assert evidence["solver_evaluations"] == 1
    appended = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    assert appended["run_id"] == "next-run-duplicate"
    assert '"recorded_candidate_observations":83' in prompts[1]
    assert evidence["development_memory_scope"] == {
        "recorded_candidate_observations": 82,
        "aggregate_window_observations": 80,
        "aggregate_window_limit": 80,
        "recent_prompt_observation_limit": 20,
        "known_prior_candidate_fingerprints": 82,
    }


def test_related_family_with_concrete_new_mechanism_is_evaluated(tmp_path):
    _root(tmp_path)
    history_path = tmp_path / "runs" / "research" / "development-history" / "memory.jsonl"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        json.dumps(
            {
                "run_id": "2026-09-08",
                "iteration": 0,
                "idea": "[kind: exchange] random exchanges exhausted their budget",
                "development_status": "rejected",
                "negative_result": "no gain",
                "fingerprint": research_memory.analyze_candidate("old_mechanism = True\n")["fingerprint"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    prompts = []
    evidence = _run(
        tmp_path,
        "changed-mechanism",
        "new_mechanism = True\n",
        "[kind: exchange] use constraint-linked exchanges instead of random exchanges to address wasted budget",
        prompts,
    )
    candidate = evidence["development"]["candidates"][0]
    assert candidate["status"] == "rejected"
    assert candidate["novel"] is True
    assert evidence["solver_evaluations"] == 2
    assert "changed mechanism within a previously tried family is allowed" in prompts[0].lower()
    assert "do not claim guaranteed gains or" in prompts[0].lower()


def test_history_scope_and_stats_exclude_retrospective_rows():
    summary = research_memory.summarize_development(
        [
            {"run_id": "run-a", "status": "rejected", "family": "exchange"},
            {"run_id": "run-a", "status": "retrospective", "family": "analysis"},
        ],
        total_observations=1,
    )
    assert summary["scope"]["recorded_candidate_observations"] == 1
    assert summary["scope"]["aggregate_window_observations"] == 1
    assert summary["scope"]["recent_observations_included"] == 1
    assert summary["entries"][0]["run_id"] == "run-a"
    assert [item["family"] for item in summary["families"]] == ["exchange"]
    assert research_memory.operational_stats([{"problem": "p", "actual_model": "m", "status": "retrospective"}]) == []
