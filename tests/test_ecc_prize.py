"""Tests for the ecc_prize ECDLP ladder plugin: generation, the independent verifier, the seed solver
baseline, the scoring contract and prompt hygiene.

Everything runs offline against the committed records.json. The seed solver is exercised on the two
smallest rungs only, which keeps the whole module well under fifteen seconds.
"""

import ast
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import research_memory
from problem_loader import load_problem


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "problems" / "ecc_prize"

curves = importlib.import_module("problems.ecc_prize.curves")


@pytest.fixture(scope="module")
def problem():
    return load_problem("ecc_prize")


@pytest.fixture(scope="module")
def seed_solver():
    sys.path.insert(0, str(PLUGIN))
    return importlib.import_module("problems.ecc_prize.seed_solver")


@pytest.fixture(scope="module")
def known_instance():
    """A freshly generated 24-bit rung whose secret scalar the test knows."""
    return curves.make_instance(24, "dev")


def test_generation_is_deterministic_and_yields_a_prime_order_curve(known_instance):
    instance, secret = known_instance
    again, again_secret = curves.make_instance(24, "dev")

    assert again == instance
    assert again_secret == secret
    assert instance["name"] == "ecdlp-p24-dev"
    assert instance["p"].bit_length() == 24
    assert curves.is_probable_prime(instance["p"])
    assert curves.is_probable_prime(instance["n"])
    assert instance["n"] not in (instance["p"], instance["p"] + 1)
    assert 1 <= secret < instance["n"]


def test_committed_ladder_matches_the_generator_for_the_smallest_rung(known_instance):
    instance, _secret = known_instance
    committed = dict(importlib.import_module("problems.ecc_prize.records").load_instance("ecdlp-p24-dev"))
    committed.pop("reference")

    assert committed == instance


def test_every_committed_instance_is_a_prime_order_curve_with_a_measured_baseline(problem):
    verify = problem.verify
    records = problem.records
    for name in records.ALL_TARGETS:
        instance = records.load_instance(name)
        p, a, b, n, generator, challenge = verify.instance_fields(instance)
        assert instance["bits"] == p.bit_length()
        assert curves.is_probable_prime(p)
        assert curves.is_probable_prime(n)
        assert verify.is_on_curve(generator, p, a, b)
        assert verify.is_on_curve(challenge, p, a, b)
        assert verify.scalar_mult(n, generator, p, a) is None, f"{name}: P does not have order n"
        reference = instance["reference"]
        assert reference["baseline_seconds"] > 0.0, f"{name}: baseline was never measured"
        assert reference["expected_iterations"] == pytest.approx(curves.expected_iterations(n))


def test_scalar_multiplication_agrees_with_repeated_addition(problem):
    verify = problem.verify
    instance = problem.records.load_instance("ecdlp-p24-dev")
    p, a, _b, _n, generator, _challenge = verify.instance_fields(instance)

    accumulated = None
    for multiple in range(1, 12):
        accumulated = verify.point_add(accumulated, generator, p, a)
        assert verify.scalar_mult(multiple, generator, p, a) == accumulated
    assert verify.scalar_mult(0, generator, p, a) is None
    assert verify.point_add(generator, verify.negate(generator, p), p, a) is None


@pytest.mark.parametrize("offset", [0, 1, -1])
def test_verifier_rejects_every_neighbouring_scalar(problem, known_instance, offset):
    instance, secret = known_instance
    verify = problem.verify

    assert verify.check_instance(secret, instance)["feasible"] is True
    outcome = verify.check_instance(secret + offset if offset else 0, instance)
    assert outcome["feasible"] is False
    assert outcome["reason"]


def test_verifier_rejects_out_of_range_and_non_integer_claims(problem, known_instance):
    instance, _secret = known_instance
    verify = problem.verify

    assert verify.check_instance(instance["n"], instance)["feasible"] is False
    assert verify.check_instance(-1, instance)["feasible"] is False
    assert verify.check_instance(True, instance)["feasible"] is False
    assert verify.check_instance("7", instance)["feasible"] is False
    assert verify.check_instance(1, {"p": 23, "a": 1, "b": 1, "n": 0, "P": [0, 0], "Q": [0, 0]})["feasible"] is False


def test_seed_solver_solves_the_two_smallest_rungs_for_two_seeds(problem, seed_solver):
    started = time.perf_counter()
    for target in ("ecdlp-p24-dev", "ecdlp-p28-dev"):
        for seed in (1, 2):
            result = seed_solver.solve_target(target, budget=10.0, seed=seed)
            assert result["k"] is not None, f"{target} seed {seed} did not solve"
            assert problem.verify.check(result["k"], target)["feasible"] is True
            assert result["iterations"] > 0
            assert result["distinguished_points"] > 0
    assert time.perf_counter() - started < 10.0


def test_solver_cli_writes_a_verified_scalar(problem, tmp_path):
    out = tmp_path / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(PLUGIN / "seed_solver.py"),
            "--target",
            "ecdlp-p24-dev",
            "--time",
            "20",
            "--seed",
            "1",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["target"] == "ecdlp-p24-dev"
    assert problem.verify.check(written["k"], "ecdlp-p24-dev")["feasible"] is True


def test_evaluate_accepts_a_verified_result_and_rejects_tampering(problem, seed_solver, tmp_path):
    target = "ecdlp-p24-dev"
    result = seed_solver.solve_target(target, budget=10.0, seed=3)
    assert result["k"] is not None
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")

    value, payload = problem.evaluate(path, target)
    assert problem.ELAPSED_FLOOR <= value <= problem.ELAPSED_CEILING
    assert payload["k"] == result["k"]
    assert payload["self_reported"] is True
    assert payload["iterations_per_second"] > 0
    assert payload["expected_iterations"] > 0

    tampered = dict(result, k=result["k"] + 1)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="unverified"):
        problem.evaluate(path, target)

    path.write_text(json.dumps(dict(result, target="ecdlp-p28-dev")), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        problem.evaluate(path, target)

    path.write_text(json.dumps(dict(result, elapsed=0.0)), encoding="utf-8")
    with pytest.raises(ValueError, match="elapsed"):
        problem.evaluate(path, target)


def test_elapsed_is_clamped_into_the_scored_window(problem, seed_solver, tmp_path):
    target = "ecdlp-p24-dev"
    result = seed_solver.solve_target(target, budget=10.0, seed=1)
    path = tmp_path / "result.json"

    path.write_text(json.dumps(dict(result, elapsed=1e-9)), encoding="utf-8")
    assert problem.evaluate(path, target)[0] == problem.ELAPSED_FLOOR
    path.write_text(json.dumps(dict(result, elapsed=10_000.0)), encoding="utf-8")
    assert problem.evaluate(path, target)[0] == problem.ELAPSED_CEILING


def test_generation_prompt_for_one_rung_hides_every_other_target(problem):
    chosen = problem.DEVELOPMENT[:1]
    prompt = problem.prompt_for_targets(chosen)

    assert research_memory.mentions_target(prompt, chosen[0])
    for hidden in problem.HOLDOUT + problem.DEVELOPMENT[1:] + problem.LARGE_TARGETS:
        assert not research_memory.mentions_target(prompt, hidden), f"prompt leaks {hidden}"
    with pytest.raises(ValueError, match="non-development"):
        problem.prompt_for_targets(["ecdlp-p40-hold"])
    assert problem.prompt_for_targets(["ecdlp-p44-large"])


def test_plugin_contract_and_helper_isolation(problem):
    assert problem.__name__ == "problems.ecc_prize.problem"
    assert problem.records.__name__ == "problems.ecc_prize.records"
    assert problem.verify.__name__ == "problems.ecc_prize.verify"

    for attribute in (
        "TITLE",
        "TARGETS",
        "DEVELOPMENT",
        "HOLDOUT",
        "VALIDATION",
        "RELEASE_HOLDOUT",
        "LARGE_TARGETS",
        "DEFAULTS",
        "MAXIMIZE",
        "FAIL_SCORE",
        "PATTERN_TAGS",
        "PROMPT",
        "TASK",
        "TOTAL_DESC",
        "SUBMIT_NOTE",
        "EMAIL_TO",
        "PRIZE",
        "FITNESS_METRICS",
        "PRIZE_TARGET_METADATA",
        "LIMITATIONS",
    ):
        assert hasattr(problem, attribute), f"missing {attribute}"
    for function in (
        "score",
        "better",
        "beats",
        "evaluate",
        "save",
        "raw_path",
        "validate_release",
        "records_load",
        "records_fetch",
        "prompt_for_targets",
        "email_subject",
        "email_body",
    ):
        assert callable(getattr(problem, function)), f"missing {function}"

    assert problem.DEVELOPMENT == problem.TARGETS
    assert problem.VALIDATION == problem.HOLDOUT
    assert problem.RELEASE_HOLDOUT == []
    assert set(problem.DEVELOPMENT).isdisjoint(problem.VALIDATION)
    assert set(problem.DEFAULTS) == {"time", "workers"}
    assert problem.MAXIMIZE is False
    assert problem.CONFIRMATION_ON_DEVELOPMENT is False
    assert problem.RELEASE_VALIDATION_SUPPORTED is False
    assert problem.EMAIL_TO is None

    # Verifier isolation: problem.py may name the baseline in prose, never import it.
    tree = ast.parse(Path(problem.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
            if node.module:
                imported.add(node.module.split(".")[-1])
    assert imported.isdisjoint({"seed_solver", "solver", "curves"})
    assert "verify" in imported


def test_records_and_scoring_behave_as_the_loop_expects(problem):
    loaded = problem.records_load()
    assert set(loaded) == set(problem.records.ALL_TARGETS)
    assert all(value > 0 for value in loaded.values())
    assert problem.records_fetch() == loaded

    reference = loaded["ecdlp-p36-dev"]
    assert problem.score(reference, reference) == pytest.approx(0.0)
    assert problem.score(reference / 2, reference) == pytest.approx(0.5)
    assert problem.score(reference * 3, reference) == pytest.approx(-1.0)
    assert problem.score(reference / 1000, reference) <= problem.GAP_CLIP
    assert problem.score(1.0, None) == 0.0
    assert problem.better(1.0, 2.0) is True
    assert problem.better(2.0, 1.0) is False
    assert problem.score(reference * 10, reference) >= problem.FAIL_SCORE


def test_win_gate_and_release_validation_are_closed(problem, seed_solver, tmp_path):
    assert problem.beats(0.0, 1.0) is False
    assert problem.beats(1e-9, None) is False

    target = "ecdlp-p24-dev"
    result = seed_solver.solve_target(target, budget=10.0, seed=1)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")

    release = problem.validate_release(path, target)
    assert release["ok"] is False
    assert release["supported"] is False
    assert release["error"]
    assert release["metrics"]["verified"] is True

    path.write_text("{}", encoding="utf-8")
    closed = problem.validate_release(path, target)
    assert closed["ok"] is False and closed["metrics"]["verified"] is False


def test_prize_descriptor_names_the_registry_entry_and_the_independent_verifier(problem):
    prize = problem.PRIZE
    for field in (
        "objective",
        "candidate_artifact",
        "baseline",
        "development_benchmark",
        "holdout_benchmark",
        "independent_verifier",
        "fitness_metrics",
        "real_target",
        "prize_registry_id",
        "promotion_threshold",
        "estimated_scaling",
        "publication_requirements",
        "submission_requirements",
    ):
        assert prize.get(field), f"PRIZE is missing {field}"

    assert prize["independent_verifier"] == "problems/ecc_prize/verify.py"
    assert (ROOT / prize["independent_verifier"]).is_file()
    assert prize["prize_registry_id"] == "certicom-eccp-131"
    assert set(prize["development_benchmark"]) <= set(problem.TARGETS) | set(problem.HOLDOUT)
    assert set(prize["holdout_benchmark"]) <= set(problem.TARGETS) | set(problem.HOLDOUT)
    assert set(prize["promotion_threshold"]) == {"min_effect", "seed_count", "holdout_required"}
    assert prize["promotion_threshold"]["holdout_required"] is True

    metadata = problem.PRIZE_TARGET_METADATA["certicom-eccp-131"]
    assert metadata["p"] == "048E1D43F293469E33194C43186B3ABC0B"
    assert "never a loop target" in metadata["status"]
    assert "certicom-eccp-131" not in problem.TARGETS
    assert "Nothing is submitted" in problem.SUBMIT_NOTE
    assert any("not partial progress" in line for line in problem.LIMITATIONS)


def test_save_writes_a_repo_relative_artifact(problem, seed_solver, tmp_path):
    target = "ecdlp-p24-dev"
    result = seed_solver.solve_target(target, budget=10.0, seed=1)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    value, payload = problem.evaluate(path, target)

    best = tmp_path / "best-ecc_prize"
    problem.save(target, payload, value, str(best), "tests")
    written = json.loads(Path(problem.raw_path(target, str(best))).read_text(encoding="utf-8"))

    assert written["target"] == target
    assert written["k"] == result["k"]
    assert written["author"] == "tests"


def test_records_json_is_anchored_by_the_committed_digests(tmp_path, monkeypatch, known_instance):
    """A curve swapped under a known target name must not reach the verifier (records.DIGESTS)."""
    module = importlib.import_module("problems.ecc_prize.records")
    assert set(module.DIGESTS) == set(module.ALL_TARGETS)

    document = json.loads(json.dumps(module.table()))
    foreign, _secret = curves.make_instance(24, "hold")  # a real curve, but not this target's
    victim = "ecdlp-p24-dev"
    document["instances"][victim].update({field: foreign[field] for field in ("p", "a", "b", "n", "P", "Q")})
    planted = tmp_path / "records.json"
    planted.write_text(json.dumps(document), encoding="utf-8")

    monkeypatch.setattr(module, "RECORDS", str(planted))
    monkeypatch.setattr(module, "_CACHE", None)
    with pytest.raises(RuntimeError, match="does not match its committed digest"):
        module.table()

    document["instances"].pop(victim)
    planted.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(module, "_CACHE", None)
    with pytest.raises(RuntimeError, match="target missing"):
        module.table()

    # The untouched committed file still validates, and the generator reproduces the same digests.
    monkeypatch.undo()
    instance, _ = known_instance
    assert module.digest_for(module.load_instance("ecdlp-p24-dev")) == module.digest_for(instance)
    assert curves.digests_for(module.table()) == module.DIGESTS


def test_a_solve_at_the_baseline_time_scores_above_the_fail_score(problem, seed_solver, tmp_path):
    """The elapsed floor must sit below every measured baseline, or a verified solve scores as a failure."""
    baselines = problem.records_load()
    assert problem.ELAPSED_FLOOR < min(baselines.values())

    path = tmp_path / "result.json"
    for target in problem.DEVELOPMENT:
        baseline = baselines[target]
        result = seed_solver.solve_target(target, budget=20.0, seed=1)
        assert result["k"] is not None, f"{target} did not solve"
        path.write_text(json.dumps(dict(result, elapsed=baseline)), encoding="utf-8")

        value, _payload = problem.evaluate(path, target)
        assert value == pytest.approx(baseline), f"{target}: the floor clamped a baseline-time solve"
        assert problem.score(value, baseline) > problem.FAIL_SCORE
