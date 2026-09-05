import hashlib
import json
import os
import types

import pytest

import loop
from research_state import BudgetLedger


class FakeProblem:
    TARGETS = ["dev", "validation"]
    DEVELOPMENT_TARGETS = ["dev"]
    VALIDATION_TARGETS = ["validation"]
    HOLDOUT = ["holdout"]
    DEFAULTS = {"time": 1, "workers": 2}
    FAIL_SCORE = -100.0
    PROMPT = "legacy prompt"
    TASK = "write the solver"

    @staticmethod
    def prompt_for_targets(targets):
        return "development targets: " + ",".join(targets)

    @staticmethod
    def records_load():
        return {"dev": 0.0, "validation": 0.0, "holdout": 0.0}

    @staticmethod
    def evaluate(path, _target):
        return json.loads(open(path, encoding="utf-8").read())["value"], {}

    @staticmethod
    def score(value, _record):
        return value

    @staticmethod
    def validate_release(_path, _target, *, record=None):
        return {"ok": False, "supported": False, "error": "not release validated", "metrics": {}}


def _fixture_root(tmp_path):
    champion = tmp_path / "best-fake" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("# incumbent\n", encoding="utf-8")
    return champion


def _runner(_problem, solver, target, _budget, seed, out, **_kwargs):
    source = open(solver, encoding="utf-8").read()
    if "fable candidate" in source:
        value = 2.0 if target == "dev" else 1.25 + (seed % 2) * 0.05
    elif "astra candidate" in source:
        value = 0.5
    else:
        value = 1.0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as stream:
        json.dump({"value": value}, stream)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def test_provider_limit_stops_generation_without_repeated_calls(tmp_path):
    _fixture_root(tmp_path)
    calls = []

    def limited(*args, **kwargs):
        calls.append(1)
        return {"error": "astra subscription usage limit reached", "error_kind": "usage_limit"}

    result = loop.run_research(
        "fake",
        root=tmp_path,
        provider="astra",
        iters=20,
        problem_module=FakeProblem,
        call_model_fn=limited,
        solver_runner=_runner,
    )
    assert result["status"] == "provider_unavailable"
    assert len(calls) == 1
    assert result["confirmed"] is False


def test_research_pins_worker_image_and_records_its_identity(tmp_path, monkeypatch):
    import isolation

    _fixture_root(tmp_path)
    image_id = "sha256:" + "a" * 64
    monkeypatch.setattr(isolation, "preflight", lambda **kwargs: {"ok": True, "details": {"image_id": image_id}})
    seen = []

    def worker(*args, **kwargs):
        seen.append(kwargs["image"])
        return _runner(*args, **kwargs)

    monkeypatch.setattr(isolation, "run_solver", worker)
    result = loop.run_research("fake", root=tmp_path, iters=0, problem_module=FakeProblem)
    assert seen == [image_id]
    assert result["worker_environment"]["image_id"] == image_id


def test_problem_path_is_rejected_before_creating_run_state(tmp_path):
    with pytest.raises(ValueError, match="plugin name"):
        loop.run_research("../outside", root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_research_matrix_rejects_valid_output_from_nonzero_solver_exit(tmp_path):
    def crashed_runner(_problem, _solver, _target, _budget, _seed, out, **_kwargs):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as stream:
            json.dump({"value": 99.0}, stream)
        return types.SimpleNamespace(returncode=3, stdout="", stderr="crashed after checkpoint")

    instance = loop.Loop(
        "fake",
        root=tmp_path,
        problem_module=FakeProblem,
        initialize_best=False,
    )
    rows = instance.evaluate_matrix(
        tmp_path / "candidate.py",
        [{"target": "dev", "seed": 1}],
        1,
        tmp_path / "outputs",
        1,
        crashed_runner,
    )
    scored = loop.evaluation.score_rows(FakeProblem, FakeProblem.records_load(), rows)
    assert scored[0]["failed"] is True
    assert scored[0]["score"] == FakeProblem.FAIL_SCORE
    assert scored[0]["returncode"] == 3
    assert "crashed after checkpoint" in scored[0]["error"]


def test_paired_research_uses_one_snapshot_critiques_only_promising_and_writes_bound_evidence(tmp_path):
    champion = _fixture_root(tmp_path)
    original_hash = hashlib.sha256(champion.read_bytes()).hexdigest()
    calls = []

    def model_call(prompt, provider, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, f"{provider}:{purpose}")
        ledger.settle(reservation, 0.1, {"tokens": 10})
        calls.append({"prompt": prompt, "provider": provider, "purpose": purpose})
        if purpose == "critique":
            return {
                "text": "reviewed",
                "code": None,
                "idea": None,
                "provider": provider,
                "model": provider + "-model",
                "cost": 0.1,
                "usage": {"tokens": 10},
                "error": None,
            }
        return {
            "text": "",
            "code": f"# {provider} candidate\n",
            "idea": provider + " idea",
            "provider": provider,
            "model": provider + "-model",
            "cost": 0.1,
            "usage": {"tokens": 10},
            "error": None,
        }

    ledger = BudgetLedger(tmp_path / "ledger.json", 10.0)
    evidence = loop.run_research(
        "fake",
        provider="paired",
        run_id="paired-test",
        call_budget=1.0,
        seed_count=3,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=1,
        invocation_budget=10.0,
        root=tmp_path,
        problem_module=FakeProblem,
        call_model_fn=model_call,
        solver_runner=_runner,
        ledger=ledger,
        paused_fn=lambda _root: False,
    )

    generations = [call for call in calls if call["purpose"] == "generation"]
    critiques = [call for call in calls if call["purpose"] == "critique"]
    assert [call["provider"] for call in generations] == ["fable", "astra"]
    assert generations[0]["prompt"] == generations[1]["prompt"]
    assert "holdout" not in generations[0]["prompt"]
    assert [call["provider"] for call in critiques] == ["astra"]
    assert evidence["status"] == "completed"
    assert evidence["confirmed"] is True
    assert evidence["publishable"] is False
    assert evidence["confirmation"]["classification"] == "reused_holdout_confirmation"
    assert len(evidence["confirmation"]["per_seed"]) == 3
    assert evidence["candidate_path"].startswith("runs/research/paired-test/fake/")
    assert len(evidence["candidate_hash"]) == 64
    assert len(evidence["artifacts"]) == 3
    assert set(evidence["artifact_targets"].values()) == {"holdout"}
    assert all(not os.path.isabs(path) for path in evidence["artifacts"])
    assert evidence["usage"]["calls"] == 3
    assert evidence["usage"]["iterations"] == 1
    assert evidence["solver_evaluations"] == 9
    assert evidence["usage"]["solver_evaluations"] == 9
    assert evidence["solver_seconds"] >= 0
    assert evidence["legacy_incumbent"]["sha256"] == original_hash
    assert champion.read_text(encoding="utf-8") == "# fable candidate\n"
    provenance = json.loads((champion.parent / "confirmation.json").read_text())
    assert provenance["candidate_hash"] == hashlib.sha256(champion.read_bytes()).hexdigest()
    prior_evidence = tmp_path / provenance["evidence_path"]
    assert provenance["evidence_hash"] == hashlib.sha256(prior_evidence.read_bytes()).hexdigest()
    history = (tmp_path / "runs/research/development-history/fake.jsonl").read_text(encoding="utf-8")
    assert "holdout" not in history
    assert json.loads((tmp_path / "runs/research/paired-test/fake/evidence.json").read_text()) == evidence

    resumed = loop.run_research(
        "fake",
        provider="fable",
        run_id="resume-test",
        call_budget=1.0,
        seed_count=1,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=0,
        invocation_budget=1.0,
        root=tmp_path,
        problem_module=FakeProblem,
        call_model_fn=model_call,
        solver_runner=_runner,
        ledger=ledger,
        paused_fn=lambda _root: False,
    )
    assert resumed["legacy_incumbent"]["classification"] == "confirmed_prior_candidate"
    assert resumed["legacy_incumbent"]["evidence_hash"] == provenance["evidence_hash"]

    artifact = tmp_path / next(iter(evidence["artifacts"]))
    artifact.write_text('{"value": 999}', encoding="utf-8")
    with pytest.raises(ValueError, match="artifact does not match"):
        loop.run_research(
            "fake",
            provider="paired",
            run_id="paired-test",
            call_budget=1.0,
            seed_count=3,
            min_effect=0.1,
            evidence_root=tmp_path / "runs" / "research",
            iters=0,
            invocation_budget=10.0,
            root=tmp_path,
            problem_module=FakeProblem,
            call_model_fn=model_call,
            solver_runner=_runner,
            ledger=ledger,
            paused_fn=lambda _root: False,
        )


def test_generation_failures_are_charged_and_never_become_candidates(tmp_path):
    _fixture_root(tmp_path)

    def failed_call(_prompt, provider, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, f"{provider}:{purpose}")
        ledger.settle(reservation)  # Unknown cost consumes the whole reservation.
        return {
            "text": "",
            "code": None,
            "idea": None,
            "provider": provider,
            "model": provider + "-model",
            "cost": None,
            "usage": {},
            "error": "provider failed",
        }

    evidence = loop.run_research(
        "fake",
        provider="fable",
        run_id="failed-call",
        call_budget=2.0,
        seed_count=2,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=1,
        invocation_budget=2.0,
        root=tmp_path,
        problem_module=FakeProblem,
        call_model_fn=failed_call,
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / "ledger.json", 2.0),
        paused_fn=lambda _root: False,
    )
    assert evidence["status"] == "partial"
    assert evidence["confirmed"] is False
    assert evidence["candidate_path"] is None
    assert evidence["development"]["candidates"][0]["status"] == "generation_failed"
    assert evidence["usage"]["calls"] == 1
    assert evidence["usage"]["charged"] == 2.0


def test_budget_stop_after_promising_candidate_still_runs_confirmation(tmp_path):
    _fixture_root(tmp_path)

    def model_call(_prompt, provider, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, f"{provider}:{purpose}")
        ledger.settle(reservation, 0.1)
        return {
            "text": "reviewed" if purpose == "critique" else "",
            "code": None if purpose == "critique" else "# fable candidate\n",
            "idea": "candidate",
            "provider": provider,
            "model": provider + "-model",
            "cost": 0.1,
            "usage": {},
            "error": None,
        }

    evidence = loop.run_research(
        "fake",
        provider="fable",
        run_id="budget-confirm",
        call_budget=0.5,
        seed_count=3,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=2,
        invocation_budget=0.6,
        root=tmp_path,
        problem_module=FakeProblem,
        call_model_fn=model_call,
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / "ledger.json", 0.6),
        paused_fn=lambda _root: False,
    )
    assert evidence["status"] == "completed"
    assert evidence["generation_stop"]["reason"] == "budget_exhausted"
    assert evidence["confirmed"] is True
    assert evidence["confirmation"]["replication_ok"] is True
    assert evidence["usage"]["calls"] == 2


def test_pause_serializes_completed_development_work(tmp_path):
    _fixture_root(tmp_path)
    checks = {"count": 0}

    def pause_after_first_candidate(_root):
        checks["count"] += 1
        return checks["count"] >= 5

    def model_call(_prompt, provider, max_cost, ledger, purpose, **_kwargs):
        reservation = ledger.reserve(max_cost, f"{provider}:{purpose}")
        ledger.settle(reservation, 0.1)
        return {
            "text": "reviewed" if purpose == "critique" else "",
            "code": None if purpose == "critique" else "# fable candidate\n",
            "idea": "candidate",
            "provider": provider,
            "model": provider + "-model",
            "cost": 0.1,
            "usage": {},
            "error": None,
        }

    evidence = loop.run_research(
        "fake",
        provider="fable",
        run_id="pause-after-work",
        call_budget=0.5,
        seed_count=3,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=2,
        invocation_budget=2.0,
        root=tmp_path,
        problem_module=FakeProblem,
        call_model_fn=model_call,
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / "ledger.json", 2.0),
        paused_fn=pause_after_first_candidate,
    )
    assert evidence["status"] == "paused"
    assert len(evidence["development"]["candidates"]) == 1
    assert evidence["development"]["best_median_gain"] == 1.0
    assert evidence["solver_evaluations"] == 2

    resumed = loop.run_research(
        "fake",
        provider="fable",
        run_id="pause-after-work",
        call_budget=0.5,
        seed_count=3,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=0,
        invocation_budget=2.0,
        root=tmp_path,
        problem_module=FakeProblem,
        call_model_fn=model_call,
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / "ledger.json", 2.0),
        paused_fn=lambda _root: False,
    )
    assert resumed["status"] == "completed"
    assert resumed["confirmed"] is True
    assert len(resumed["development"]["candidates"]) == 1
    assert resumed["usage"]["calls"] == 0


def test_cli_entry_is_local_only_and_routes_to_research(monkeypatch):
    captured = {}

    def fake_run(problem, **kwargs):
        captured.update(problem=problem, **kwargs)
        return {"run_id": "r", "problem": problem, "status": "completed", "confirmed": False, "publishable": False}

    monkeypatch.setattr(loop, "run_research", fake_run)
    assert loop.cli_main(["--problem", "cvrp", "--iters", "2"]) == 0
    assert captured["problem"] == "cvrp"
    assert captured["provider"] == "paired"
    assert captured["iters"] == 2
    assert "publish" not in captured


def test_cli_legacy_model_maps_to_one_provider_and_targets_remain_explicit(monkeypatch):
    captured = {}

    def fake_run(problem, **kwargs):
        captured.update(problem=problem, **kwargs)
        return {"run_id": "r", "problem": problem, "status": "completed", "confirmed": False, "publishable": False}

    monkeypatch.setattr(loop, "run_research", fake_run)
    assert loop.cli_main(["--problem", "cvrp", "--model", "claude-fable-5-1", "--targets", "a,b"]) == 0
    assert captured["provider"] == "fable"
    assert captured["model"] == "claude-fable-5-1"
    assert captured["targets"] == ["a", "b"]


def test_cli_eval_only_accepts_zero_model_budgets(monkeypatch):
    captured = {}

    def fake_run(problem, **kwargs):
        captured.update(problem=problem, **kwargs)
        return {"run_id": "r", "problem": problem, "status": "completed", "confirmed": False, "publishable": False}

    monkeypatch.setattr(loop, "run_research", fake_run)
    assert loop.cli_main(["--problem", "pglib_opf", "--eval-only", "--budget", "0", "--call-budget", "0"]) == 0
    assert captured["iters"] == 0
    assert captured["invocation_budget"] == 0.0
    assert captured["call_budget"] == 0.0


def test_eval_only_run_accepts_zero_ledger_without_model_call(tmp_path):
    _fixture_root(tmp_path)

    def forbidden_model_call(*_args, **_kwargs):
        raise AssertionError("eval-only must not call a model")

    evidence = loop.run_research(
        "fake",
        provider="fable",
        run_id="zero-budget-eval",
        call_budget=0.0,
        seed_count=1,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=0,
        invocation_budget=0.0,
        root=tmp_path,
        problem_module=FakeProblem,
        call_model_fn=forbidden_model_call,
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / "ledger.json", 0.0),
        paused_fn=lambda _root: False,
    )
    assert evidence["status"] == "completed"
    assert evidence["usage"]["calls"] == 0
    assert evidence["solver_evaluations"] == 1
