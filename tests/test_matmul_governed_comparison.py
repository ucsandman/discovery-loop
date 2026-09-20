"""Synthetic policy tests only; these rows are not matrix-rank discovery evidence."""

import json
import os
import types

import evaluation
import isolation
import loop
from problem_loader import load_problem
from research_state import BudgetLedger


RECORDS = {"2": 7, "3": 23, "4": 49}


def _score(rank, target):
    record = RECORDS[target]
    return -min((rank - record) / record, 0.5)


def _rows(ranks, seed_count=3, failed_target=None):
    return [
        {
            "target": target,
            "seed": seed,
            "score": -1.0 if target == failed_target else _score(rank, target),
            "failed": target == failed_target,
        }
        for seed in range(seed_count)
        for target, rank in zip(("2", "3", "4"), ranks, strict=True)
    ]


def test_matmul_policy_accepts_single_target_progress_without_changing_default_policy():
    incumbent = _rows([7, 26, 49])
    candidate = _rows([7, 25, 49])

    ordinary = evaluation.compare_paired(incumbent, candidate, 0.0001)
    assert ordinary["median_gain"] == 0.0
    assert ordinary["passes"] is False
    assert "selection_gain" not in ordinary

    problem = load_problem("matrix_multiplication")
    result = evaluation.compare_paired(
        incumbent,
        candidate,
        0.0001,
        policy=problem.COMPARISON_POLICY,
    )
    assert result["policy"] == "per_target_pareto"
    assert result["median_gain"] == 0.0
    assert result["selection_gain"] == 1 / 23
    assert result["non_regressing"] is True
    assert result["passes"] is True
    assert {item["target"]: item["median_gain"] for item in result["per_target"]} == {
        "2": 0.0,
        "3": 1 / 23,
        "4": 0.0,
    }


def test_matmul_policy_rejects_regression_no_progress_failures_and_too_few_seeds():
    incumbent = _rows([7, 26, 49])
    policy = "per_target_pareto"

    regressed = evaluation.compare_paired(incumbent, _rows([8, 25, 48]), 0.0001, policy=policy)
    assert regressed["selection_gain"] > 0
    assert regressed["non_regressing"] is False
    assert regressed["passes"] is False

    unchanged = evaluation.compare_paired(incumbent, _rows([7, 26, 49]), 0.0001, policy=policy)
    assert unchanged["selection_gain"] == 0.0
    assert unchanged["passes"] is False

    failed = evaluation.compare_paired(incumbent, _rows([7, 25, 49], failed_target="3"), 0.0001, policy=policy)
    assert failed["candidate_failures"] == 3
    assert failed["passes"] is False

    too_few = evaluation.compare_paired(
        _rows([7, 26, 49], seed_count=2),
        _rows([7, 25, 49], seed_count=2),
        0.0001,
        policy=policy,
    )
    assert too_few["distinct_seeds"] == 2
    assert too_few["replication_ok"] is False
    assert too_few["passes"] is False


def test_matmul_worker_stages_only_solver_wrapper_and_exact_verifier(tmp_path):
    problem = tmp_path / "problems" / "matrix_multiplication"
    problem.mkdir(parents=True)
    (problem / "verify.py").write_text("# trusted exact verifier\n", encoding="utf-8")
    (problem / "research-notes.txt").write_text("must not enter worker\n", encoding="utf-8")
    solver = tmp_path / "candidate.py"
    solver.write_text("VARIANT = 0\n", encoding="utf-8")
    stage = tmp_path / "stage"

    isolation._stage_inputs(tmp_path, "matrix_multiplication", solver, "3", stage)

    assert sorted(str(path.relative_to(stage)).replace("\\", "/") for path in stage.rglob("*") if path.is_file()) == [
        "problems/matrix_multiplication/verify.py",
        "solver.py",
        "worker_entry.py",
    ]


class SyntheticMatmulProblem:
    """A cheap rank-shaped fixture; it never claims tensor feasibility."""

    TARGETS = ["2", "3", "4"]
    DEVELOPMENT = TARGETS
    VALIDATION = []
    RELEASE_HOLDOUT = []
    CONFIRMATION_ON_DEVELOPMENT = True
    COMPARISON_POLICY = "per_target_pareto"
    DEFAULTS = {"time": 1, "workers": 1}
    FAIL_SCORE = -1.0
    PROMPT = "synthetic matrix-rank fixture"
    TASK = "write a synthetic solver fixture"

    @staticmethod
    def prompt_for_targets(targets):
        return "synthetic targets: " + ",".join(targets)

    @staticmethod
    def records_load():
        return dict(RECORDS)

    @staticmethod
    def evaluate(path, _target):
        return json.loads(open(path, encoding="utf-8").read())["value"], {}

    @staticmethod
    def score(value, record):
        return -min((value - record) / record, 0.5)

    @staticmethod
    def validate_release(_path, _target, *, record=None):
        return {"ok": False, "supported": True, "error": "synthetic fixture is not release evidence", "metrics": {}}


def _synthetic_runner(_problem, solver, target, _budget, _seed, out, **_kwargs):
    source = open(solver, encoding="utf-8").read()
    variant = 2 if "VARIANT = 2" in source else 1 if "VARIANT = 1" in source else 0
    ranks = {
        0: {"2": 7, "3": 26, "4": 49},
        1: {"2": 7, "3": 25, "4": 49},
        2: {"2": 7, "3": 24, "4": 49},
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as stream:
        json.dump({"value": ranks[variant][target]}, stream)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def test_governed_run_uses_policy_for_development_confirmation_selection_and_resume(tmp_path):
    champion = tmp_path / "best-matrix_multiplication" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("VARIANT = 0\n", encoding="utf-8")
    generated = 0

    def model_call(_prompt, provider, max_cost, ledger, purpose, **_kwargs):
        nonlocal generated
        reservation = ledger.reserve(max_cost, f"{provider}:{purpose}")
        ledger.settle(reservation, 0.1, {"tokens": 1})
        if purpose == "critique":
            return {"text": "synthetic review", "provider": provider, "model": provider + "-model", "cost": 0.1}
        generated += 1
        return {
            "code": f"VARIANT = {generated}\n",
            "idea": f"synthetic candidate {generated}",
            "provider": provider,
            "model": provider + "-model",
            "cost": 0.1,
        }

    evidence_root = tmp_path / "runs" / "research"
    evidence = loop.run_research(
        "matrix_multiplication",
        provider="fable",
        run_id="synthetic-matmul",
        call_budget=1.0,
        seed_count=3,
        min_effect=0.0001,
        evidence_root=evidence_root,
        iters=2,
        invocation_budget=10.0,
        root=tmp_path,
        problem_module=SyntheticMatmulProblem,
        call_model_fn=model_call,
        solver_runner=_synthetic_runner,
        ledger=BudgetLedger(tmp_path / "budget.json", 10.0),
        paused_fn=lambda _root: False,
        development_seeds=1,
    )

    candidates = evidence["development"]["candidates"]
    assert [item["median_gain"] for item in candidates] == [0.0, 0.0]
    assert candidates[1]["selection_gain"] > candidates[0]["selection_gain"] > 0
    assert evidence["development"]["best_selection_gain"] == candidates[1]["selection_gain"]
    assert evidence["confirmation"]["policy"] == "per_target_pareto"
    assert evidence["confirmation"]["passes"] is True
    assert evidence["confirmed"] is True
    assert evidence["publishable"] is False
    assert champion.read_text(encoding="utf-8") == "VARIANT = 2\n"

    calls_before_resume = generated
    resumed = loop.run_research(
        "matrix_multiplication",
        provider="fable",
        run_id="synthetic-matmul",
        evidence_root=evidence_root,
        root=tmp_path,
        problem_module=SyntheticMatmulProblem,
        call_model_fn=model_call,
        solver_runner=_synthetic_runner,
        ledger=BudgetLedger(tmp_path / "budget.json", 10.0),
        paused_fn=lambda _root: False,
        development_seeds=1,
    )
    assert resumed == evidence
    assert generated == calls_before_resume

    assert loop._selection_gain({"median_gain": 0.25}) == 0.25
    assert loop._selection_gain({"median_gain": 0.0, "selection_gain": 0.5}) == 0.5
