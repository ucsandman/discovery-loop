"""Synthetic island-policy tests; values here are not matrix-rank evidence."""

import hashlib
import json
import os
import types

import pytest

import island_evolution
import loop
from research_state import BudgetLedger


def _write_parent(root, name, score, *, verified=True):
    path = root / f"{name}.py"
    path.write_text(f"VARIANT = {name!r}\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "candidate_path": path.relative_to(root).as_posix(),
        "candidate_hash": digest,
        "fingerprint": hashlib.sha256(name.encode()).hexdigest(),
        "idea": f"synthetic {name}",
        "iteration": 0,
        "provider": "fixture",
        "selection_gain": score,
        "median_gain": score,
        "valid": True,
        "development_verified": verified,
        "confirmation": {"reward": 999},
        "publishable": True,
    }


def test_population_is_bounded_migrates_and_excludes_unverified_feedback(tmp_path):
    seed = _write_parent(tmp_path, "seed", 0.0)
    population = island_evolution.new_population(seed)
    admitted = [_write_parent(tmp_path, f"p{index}", float(index + 1)) for index in range(5)]
    for parent in admitted:
        assert island_evolution.admit(population, 0, parent) is True

    assert [len(island["parents"]) for island in population["islands"]] == [3, 3, 1]
    assert population["islands"][1]["parents"][0]["candidate_hash"] == admitted[-1]["candidate_hash"]
    assert island_evolution.plan(population, 1)["operator"] == "crossover"
    assert island_evolution.plan(population, 2)["operator"] == "mutation"
    assert all(
        "confirmation" not in parent and "publishable" not in parent
        for island in population["islands"]
        for parent in island["parents"]
    )

    unverified = _write_parent(tmp_path, "holdout_only", 999.0, verified=False)
    before = json.dumps(population, sort_keys=True)
    assert island_evolution.admit(population, 0, unverified) is False
    assert island_evolution.admit(population, 99, admitted[0]) is False
    assert json.dumps(population, sort_keys=True) == before
    assert island_evolution.validate_population(json.loads(json.dumps(population)), tmp_path) == population
    unknown = island_evolution.new_population(admitted[0])
    with pytest.raises(ValueError, match="unknown or unverified"):
        island_evolution.validate_membership(
            unknown,
            [],
            seed["candidate_path"],
            seed["candidate_hash"],
        )


def test_mature_population_round_trips_without_retaining_incumbent(tmp_path):
    parents = [_write_parent(tmp_path, f"mature{index}", float(index)) for index in range(9)]
    population = {
        "schema_version": 1,
        "island_count": 3,
        "capacity_per_island": 3,
        "islands": [
            {
                "id": island,
                "parents": [island_evolution.parent_from_record(item) for item in parents[island * 3 : island * 3 + 3]],
            }
            for island in range(3)
        ],
    }
    island_evolution.validate_population(population, tmp_path)
    plan = island_evolution.plan(population, 7)
    assert plan["island"] == 1
    assert plan["operator"] == "crossover"
    island_evolution.validate_plan(plan, population)

    (tmp_path / "mature3.py").write_text("tampered = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its hash"):
        island_evolution.validate_population(population, tmp_path)


class IslandProblem:
    TARGETS = ["a", "b", "holdout"]
    DEVELOPMENT_TARGETS = ["a", "b"]
    VALIDATION_TARGETS = ["holdout"]
    HOLDOUT = ["holdout"]
    EVOLUTION_POLICY = "solver_islands_v1"
    COMPARISON_POLICY = "per_target_pareto"
    DEFAULTS = {"time": 1, "workers": 1}
    FAIL_SCORE = -100.0
    PROMPT = "synthetic prompt"
    TASK = "write a synthetic solver"

    @staticmethod
    def prompt_for_targets(targets):
        return "development targets: " + ",".join(targets)

    @staticmethod
    def records_load():
        return {"a": 0.0, "b": 0.0, "holdout": 0.0}

    @staticmethod
    def evaluate(path, _target):
        return json.loads(open(path, encoding="utf-8").read())["value"], {}

    @staticmethod
    def score(value, _record):
        return value


class DefaultProblem:
    TARGETS = ["a", "b"]
    DEVELOPMENT = TARGETS
    VALIDATION = []
    RELEASE_HOLDOUT = []
    DEFAULTS = {"time": 1, "workers": 1}
    FAIL_SCORE = -100.0
    PROMPT = "ordinary prompt"
    TASK = "write an ordinary solver"

    @staticmethod
    def prompt_for_targets(targets):
        return "ordinary targets: " + ",".join(targets)

    @staticmethod
    def records_load():
        return {"a": 0.0, "b": 0.0}

    @staticmethod
    def evaluate(path, _target):
        return json.loads(open(path, encoding="utf-8").read())["value"], {}

    @staticmethod
    def score(value, _record):
        return value


def _fixture_root(tmp_path, problem="island"):
    champion = tmp_path / f"best-{problem}" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("VARIANT = 0\n", encoding="utf-8")


def _runner(_problem, solver, target, _budget, _seed, out, **_kwargs):
    source = open(solver, encoding="utf-8").read()
    variant = 0 if "VARIANT = 0" in source else 1
    value = 1.0 if variant == 0 or target == "holdout" else 2.0 if target == "a" else 0.0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as stream:
        json.dump({"value": value}, stream)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def _model(calls, *, interrupt_second=False):
    generated = 0

    def call(prompt, provider, max_cost, ledger, purpose, **_kwargs):
        nonlocal generated
        reservation = ledger.reserve(max_cost, f"{provider}:{purpose}")
        ledger.settle(reservation, max_cost, {"tokens": 1})
        calls.append((provider, purpose, prompt))
        if interrupt_second and len(calls) == 2:
            raise KeyboardInterrupt
        generated += 1
        return {
            "code": f"VARIANT = {generated}\n",
            "idea": f"synthetic program {generated}",
            "provider": provider,
            "model": provider + "-model",
        }

    return call


def _run(tmp_path, run_id, call_model, *, iters=2, problem_module=IslandProblem, provider="paired"):
    return loop.run_research(
        "island",
        provider=provider,
        run_id=run_id,
        call_budget=1.0,
        seed_count=3,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=iters,
        invocation_budget=4.0,
        root=tmp_path,
        problem_module=problem_module,
        call_model_fn=call_model,
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / f"{run_id}-budget.json", 4.0),
        paused_fn=lambda _root: False,
    )


def test_governed_paired_generation_uses_one_frozen_plan_and_reaches_crossover(tmp_path):
    _fixture_root(tmp_path)
    calls = []
    evidence = _run(tmp_path, "evolve", _model(calls))

    generations = [item for item in calls if item[1] == "generation"]
    assert len(generations) == 4
    assert generations[0][2] == generations[1][2]
    assert generations[2][2] == generations[3][2]
    assert "holdout" not in "".join(item[2] for item in generations)
    assert "CROSSOVER" not in generations[0][2]
    assert "CROSSOVER" in generations[2][2]
    candidates = evidence["development"]["candidates"]
    assert [item["operator"] for item in candidates] == ["mutation", "mutation", "crossover", "crossover"]
    assert candidates[0]["parent_hashes"] == candidates[1]["parent_hashes"]
    assert candidates[2]["parent_hashes"] == candidates[3]["parent_hashes"]
    assert all(len(item["prompt_hash"]) == 64 for item in candidates)
    population = evidence["development"]["evolution"]["population"]
    assert [len(island["parents"]) for island in population["islands"]] == [3, 3, 2]


def test_started_call_is_not_reissued_and_resume_uses_frozen_prompt_and_incumbent_rows(tmp_path):
    _fixture_root(tmp_path)
    calls = []
    interrupted = _run(tmp_path, "resume", _model(calls, interrupt_second=True), iters=1)
    assert interrupted["status"] == "interrupted"
    pending = interrupted["development"]["pending_generations"]
    assert [item["status"] for item in pending] == ["generated", "started"]
    assert pending[0]["prompt_hash"] == pending[1]["prompt_hash"]
    prompt_path = tmp_path / pending[0]["prompt_path"]
    original_prompt = prompt_path.read_bytes()

    prompt_path.write_bytes(original_prompt + b"\ntampered")
    with pytest.raises(ValueError, match="prompt does not match recorded hash"):
        _run(tmp_path, "resume", lambda *_args, **_kwargs: pytest.fail("must not call"), iters=1)
    prompt_path.write_bytes(original_prompt)

    runner_calls = []

    def counting_runner(*args, **kwargs):
        runner_calls.append((args[1], args[2]))
        return _runner(*args, **kwargs)

    resumed = loop.run_research(
        "island",
        provider="paired",
        run_id="resume",
        call_budget=1.0,
        seed_count=3,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=1,
        invocation_budget=4.0,
        root=tmp_path,
        problem_module=IslandProblem,
        call_model_fn=lambda *_args, **_kwargs: pytest.fail("started call must not be reissued"),
        solver_runner=counting_runner,
        ledger=BudgetLedger(tmp_path / "resume-budget.json", 4.0),
        paused_fn=lambda _root: False,
    )
    assert len(calls) == 2
    assert all("legacy_incumbent.py" not in solver for solver, _target in runner_calls)
    assert any(
        item.get("generation_error_kind") == "lost_response_indeterminate"
        for item in resumed["development"]["candidates"]
    )
    assert resumed["development"]["pending_generations"] == []


def test_plugin_without_opt_in_keeps_ordinary_generation_path(tmp_path):
    _fixture_root(tmp_path)
    calls = []
    result = _run(
        tmp_path,
        "ordinary",
        _model(calls),
        iters=1,
        problem_module=DefaultProblem,
        provider="fable",
    )
    assert "evolution" not in result["development"]
    assert "operator" not in result["development"]["candidates"][0]
    assert "CROSSOVER" not in calls[0][2]


def test_resume_accepts_mature_population_after_incumbent_is_evicted(tmp_path):
    _fixture_root(tmp_path)
    calls = []
    initial = _run(tmp_path, "mature-resume", _model(calls))
    evidence_path = tmp_path / "runs/research/mature-resume/island/evidence.json"
    candidates = initial["development"]["candidates"]
    refs = [island_evolution.parent_from_record(candidate) for candidate in candidates]
    initial["development"]["evolution"]["population"]["islands"] = [
        {"id": island, "parents": [refs[(island + offset) % len(refs)] for offset in range(3)]} for island in range(3)
    ]
    initial.update(status="interrupted", finished_at=None)
    evidence_path.write_text(json.dumps(initial), encoding="utf-8")
    runner_calls = []

    def forbidden_runner(*_args, **_kwargs):
        runner_calls.append(1)
        raise AssertionError("mature resume must reuse the frozen incumbent rows")

    resumed = loop.run_research(
        "island",
        provider="paired",
        run_id="mature-resume",
        call_budget=1.0,
        seed_count=3,
        min_effect=0.1,
        evidence_root=tmp_path / "runs" / "research",
        iters=0,
        invocation_budget=4.0,
        root=tmp_path,
        problem_module=IslandProblem,
        call_model_fn=lambda *_args, **_kwargs: pytest.fail("no model call expected"),
        solver_runner=forbidden_runner,
        ledger=BudgetLedger(tmp_path / "mature-resume-budget.json", 4.0),
        paused_fn=lambda _root: False,
    )
    assert resumed["status"] == "completed"
    assert runner_calls == []
    incumbent_hash = resumed["legacy_incumbent"]["sha256"]
    assert all(
        incumbent_hash not in {parent["candidate_hash"] for parent in island["parents"]}
        for island in resumed["development"]["evolution"]["population"]["islands"]
    )


def test_island_budget_stop_creates_no_generation_calls(tmp_path):
    _fixture_root(tmp_path)
    calls = []
    result = loop.run_research(
        "island",
        provider="paired",
        run_id="budget-stop",
        call_budget=1.0,
        evidence_root=tmp_path / "runs" / "research",
        iters=1,
        invocation_budget=1.0,
        root=tmp_path,
        problem_module=IslandProblem,
        call_model_fn=_model(calls),
        solver_runner=_runner,
        ledger=BudgetLedger(tmp_path / "budget-stop.json", 1.0),
        paused_fn=lambda _root: False,
    )
    assert calls == []
    assert result["generation_stop"]["reason"] == "budget_exhausted"
    assert result["development"]["evolution"]["population"]
