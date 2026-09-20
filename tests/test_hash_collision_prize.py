"""Integrity tests for the hash_collision_prize problem plugin."""

import ast
import hashlib
import json
from pathlib import Path
import time

import pytest

import evaluation
import research_memory
from problem_loader import load_problem
from problems.hash_collision_prize import records, seed_solver, verify


# The non-claim sentence is load bearing: it must appear verbatim in the docstring, the PROMPT and the metadata.
NON_CLAIM = "Truncated collisions measure search machinery only; they are not partial progress toward a full collision."

# Mirrors prize_contract.PRIZE_FIELDS (slice A); duplicated so this plugin's tests do not depend on that module.
PRIZE_FIELDS = (
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
)

RIPEMD160_VECTORS = {
    b"": "9c1185a5c5e9fc54612808977ee8f548b2258d31",
    b"a": "0bdc9d2d256b3ee9daae347be6f4dc835a467ffe",
    b"abc": "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc",
    b"message digest": "5d0689ef49d2fae572b881b123a85ffa21595f36",
    b"abcdefghijklmnopqrstuvwxyz": "f71c27109c692c1b56bbdceb5b9d2865b3708dbc",
}


def _collision(target="sha256-t28-dev", seed=1, budget=30.0):
    result = seed_solver.solve(records.load_target(target), budget=budget, seed=seed)
    assert result is not None, f"seed solver found no collision for {target} in {budget}s"
    return result


def test_plugin_loads_with_isolated_helpers():
    problem = load_problem("hash_collision_prize")

    assert problem.__name__ == "problems.hash_collision_prize.problem"
    assert problem.records.__name__ == "problems.hash_collision_prize.records"
    assert problem.verify.__name__ == "problems.hash_collision_prize.verify"
    assert problem.TARGETS == problem.DEVELOPMENT == records.DEVELOPMENT
    assert problem.VALIDATION == problem.HOLDOUT == records.HOLDOUT
    assert problem.RELEASE_HOLDOUT == []
    assert set(problem.DEVELOPMENT).isdisjoint(problem.VALIDATION)
    assert problem.MAXIMIZE is False
    assert problem.FAIL_SCORE == -1.0
    assert problem.DEFAULTS == {"time": 60, "workers": 3}
    assert problem.CONFIRMATION_ON_DEVELOPMENT is False
    assert problem.COMPARISON_POLICY == "median"
    assert problem.RELEASE_VALIDATION_SUPPORTED is False


def test_manifest_confirms_on_the_concealed_holdout():
    problem = load_problem("hash_collision_prize")
    manifest = evaluation.build_manifest(problem, "hash_collision_prize")

    assert manifest["development"] == problem.DEVELOPMENT
    assert manifest["confirmation"] == problem.HOLDOUT
    assert set(manifest["concealed"]) == set(problem.HOLDOUT)


def test_sha256_rounds_equals_hashlib_at_sixty_four_rounds():
    for message in (b"", b"abc", b"message digest", b"a" * 200, bytes(range(256))):
        assert verify.sha256_rounds(message, 64) == hashlib.sha256(message).digest()

    assert verify.sha256_rounds(b"abc", 24) != hashlib.sha256(b"abc").digest()
    for bad in (0, 65, 1.5, True, "24"):
        with pytest.raises(ValueError):
            verify.sha256_rounds(b"abc", bad)


def test_pure_python_ripemd160_matches_published_vectors():
    for message, expected in RIPEMD160_VECTORS.items():
        assert verify.ripemd160_python(message).hex() == expected

    if verify.RIPEMD160_BACKEND == "hashlib":  # the fallback must agree with OpenSSL wherever OpenSSL still ships it
        for message in (*RIPEMD160_VECTORS, b"a" * 1000, bytes(range(256))):
            assert verify.ripemd160_python(message) == hashlib.new("ripemd160", message).digest()
    assert verify.ripemd160(b"abc").hex() == RIPEMD160_VECTORS[b"abc"]


def test_digest_dispatch_and_truncation():
    assert verify.digest("sha256", None, b"abc") == hashlib.sha256(b"abc").digest()
    assert verify.digest("ripemd160", None, b"abc") == verify.ripemd160(b"abc")
    assert verify.digest("sha256-reduced", 24, b"abc") == verify.sha256_rounds(b"abc", 24)

    with pytest.raises(ValueError):
        verify.digest("md5", None, b"abc")
    with pytest.raises(ValueError):
        verify.digest("sha256-reduced", None, b"abc")

    raw = bytes([0xAB, 0xCD, 0xEF])
    assert verify.truncated_int(raw, 8) == 0xAB
    assert verify.truncated_int(raw, 12) == 0xABC
    assert verify.prefix_hex(verify.truncated_int(raw, 12), 12) == "abc"
    with pytest.raises(ValueError):
        verify.truncated_int(raw, 25)


def test_records_are_deterministic_and_measured():
    table = records.table()

    assert set(table) == set(records.ALL_TARGETS)
    assert records.LARGE_TARGETS == [
        "sha256-t40-large",
        "sha256-t44-large",
        "ripemd160-t36-large",
        "ripemd160-t40-large",
    ]
    for name, spec in table.items():
        assert spec["salt"] == records.salt_for(name)
        assert len(bytes.fromhex(spec["salt"])) == records.SALT_BYTES
        assert spec["reference"]["expected_hashes"] == pytest.approx(records.expected_hashes(spec["bits"]))
        assert spec["function"] in verify.FUNCTIONS
    assert table["sha256r24-t32-hold"]["rounds"] == 24
    for name in records.DEVELOPMENT + records.HOLDOUT:
        baseline = table[name]["reference"]["baseline_seconds"]
        assert baseline is None or baseline > 0
        assert table[name]["reference"]["note"]
    assert records.load()["sha256-t28-dev"] == table["sha256-t28-dev"]["reference"]["baseline_seconds"]


def test_seed_solver_finds_a_verified_collision_quickly():
    started = time.time()
    result = _collision("sha256-t28-dev", seed=1, budget=5.0)
    elapsed = time.time() - started

    assert elapsed < 5.0
    assert result["m1"] != result["m2"]
    assert 1 <= len(bytes.fromhex(result["m1"])) <= verify.MAX_MESSAGE_BYTES
    assert result["hashes"] > 0 and result["distinguished_points"] > 0
    assert verify.check(result["m1"], result["m2"], "sha256-t28-dev")["feasible"] is True


def test_seed_solver_cli_writes_a_verified_collision(tmp_path):
    out = tmp_path / "result.json"
    code = seed_solver.main(["--target", "sha256-t32-dev", "--time", "30", "--seed", "1", "--out", str(out)])

    assert code == 0
    written = json.loads(out.read_text())
    assert written["target"] == "sha256-t32-dev"
    assert verify.check(written["m1"], written["m2"], "sha256-t32-dev")["feasible"] is True


@pytest.mark.parametrize("function", ["ripemd160", "sha256-reduced"])
def test_seed_solver_handles_every_digest_backend(function):
    target = "ripemd160-t32-dev" if function == "ripemd160" else "sha256r24-t32-hold"
    result = _collision(target, seed=2, budget=60.0)

    assert verify.check(result["m1"], result["m2"], target)["feasible"] is True


def test_verifier_rejects_equal_wrong_and_oversized_messages():
    result = _collision()
    m1, m2 = result["m1"], result["m2"]

    assert verify.check(m1, m1, "sha256-t28-dev") == {
        "feasible": False,
        "reason": "m1 and m2 are the same message",
        "digest_prefix": None,
    }
    wrong = verify.check(m1, (bytes.fromhex(m2)[:-1] + b"\xff").hex(), "sha256-t28-dev")
    assert wrong["feasible"] is False and "differ" in wrong["reason"]
    assert verify.check(m1, ("00" * 65), "sha256-t28-dev")["feasible"] is False
    assert verify.check(m1, "", "sha256-t28-dev")["feasible"] is False
    assert verify.check(m1, "zz", "sha256-t28-dev")["feasible"] is False
    assert verify.check(m1, None, "sha256-t28-dev")["feasible"] is False
    # A genuine collision on one target is not a collision on another (different salt).
    assert verify.check(m1, m2, "sha256-t32-dev")["feasible"] is False


def test_evaluate_scores_a_verified_collision_and_rejects_tampering(tmp_path):
    problem = load_problem("hash_collision_prize")
    result = _collision("sha256-t28-dev", seed=3)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result))

    value, payload = problem.evaluate(str(path), "sha256-t28-dev")
    assert value == pytest.approx(min(max(result["elapsed"], problem.VALUE_FLOOR_SECONDS), 105.0))
    assert payload["self_reported"] is True
    assert payload["expected_hashes"] == pytest.approx(records.expected_hashes(28))
    assert payload["ratio"] == pytest.approx(result["hashes"] / payload["expected_hashes"])
    assert payload["digest_prefix"]

    tampered = dict(result, m2=(bytes.fromhex(result["m2"])[:-1] + b"\x00").hex())
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="no verified collision"):
        problem.evaluate(str(path), "sha256-t28-dev")

    path.write_text(json.dumps(dict(result, target="sha256-t32-dev")))
    with pytest.raises(ValueError, match="does not match"):
        problem.evaluate(str(path), "sha256-t28-dev")

    path.write_text(json.dumps({k: v for k, v in result.items() if k != "elapsed"}))
    with pytest.raises(ValueError, match="elapsed"):
        problem.evaluate(str(path), "sha256-t28-dev")

    path.write_text(json.dumps(dict(result, elapsed=-1.0)))
    with pytest.raises(ValueError, match="non-positive"):
        problem.evaluate(str(path), "sha256-t28-dev")


def test_self_reported_time_is_clamped_to_the_worker_budget(tmp_path):
    problem = load_problem("hash_collision_prize")
    result = _collision("sha256-t28-dev", seed=4)
    path = tmp_path / "result.json"

    path.write_text(json.dumps(dict(result, elapsed=1e9, time_budget=60.0)))
    assert problem.evaluate(str(path), "sha256-t28-dev")[0] == pytest.approx(105.0)

    path.write_text(json.dumps(dict(result, elapsed=1e-9, time_budget=60.0)))
    assert problem.evaluate(str(path), "sha256-t28-dev")[0] == pytest.approx(problem.VALUE_FLOOR_SECONDS)


def test_score_is_bounded_and_beats_never_fires():
    problem = load_problem("hash_collision_prize")

    assert problem.score(1.0, 1.0) == pytest.approx(0.0)
    assert problem.score(0.5, 1.0) == pytest.approx(0.5)
    assert problem.score(0.0, 1.0) == pytest.approx(1.0)
    assert problem.score(2.0, 1.0) == pytest.approx(-1.0)
    assert problem.score(100.0, 1.0) == pytest.approx(-1.0)
    assert problem.score(1.0, None) == 0.0
    assert problem.better(1.0, 2.0) is True

    for value in (0.0, 1e-9, 1.0, 1e9):
        assert problem.beats(value, 1.0) is False
        assert problem.beats(value, None) is False


def test_release_validation_is_unsupported(tmp_path):
    problem = load_problem("hash_collision_prize")
    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}")

    outcome = problem.validate_release(str(candidate), "sha256-t28-dev")
    assert outcome["ok"] is False
    assert outcome["supported"] is False
    assert outcome["error"] == "ladder benchmark; not a public record"
    assert outcome["metrics"]["non_claim"] == NON_CLAIM


def test_prompt_never_names_a_holdout_target():
    problem = load_problem("hash_collision_prize")

    for prompt in (problem.PROMPT, problem.TASK, problem.prompt_for_targets(problem.DEVELOPMENT)):
        for hidden in problem.HOLDOUT:
            assert hidden not in prompt
            assert research_memory.mentions_target(prompt, hidden) is False

    chosen = problem.DEVELOPMENT[:1]
    focused = problem.prompt_for_targets(chosen)
    assert chosen[0] in focused
    assert all(name not in focused for name in problem.DEVELOPMENT[1:])
    assert problem.prompt_for_targets(problem.LARGE_TARGETS[:1])
    with pytest.raises(ValueError, match="non-development"):
        problem.prompt_for_targets(problem.HOLDOUT[:1])


def test_non_claim_sentence_is_verbatim_everywhere():
    problem = load_problem("hash_collision_prize")

    assert NON_CLAIM in problem.__doc__
    assert NON_CLAIM in problem.PROMPT
    assert NON_CLAIM in problem.SUBMIT_NOTE
    assert NON_CLAIM in problem.LIMITATIONS
    assert problem.PRIZE_TARGET_METADATA["non_claim"] == NON_CLAIM
    assert NON_CLAIM in seed_solver.__doc__
    assert NON_CLAIM in verify.__doc__

    bounties = problem.PRIZE_TARGET_METADATA["bounties"]
    assert set(bounties) == {
        "todd-sha256-collision",
        "todd-ripemd160-collision",
        "todd-hash160-collision",
        "todd-hash256-collision",
    }
    for entry in bounties.values():
        assert entry["non_claim"] == NON_CLAIM
        assert entry["address"] and entry["script"]
    assert bounties["todd-sha256-collision"]["address"] == "35Snmmy3uhaer2gTboc81ayCip4m9DT4ko"
    assert bounties["todd-sha256-collision"]["balance_btc"] == 0.27734251


def test_prize_descriptor_matches_the_contract():
    problem = load_problem("hash_collision_prize")
    prize = problem.PRIZE

    assert set(prize) == set(PRIZE_FIELDS)
    assert all(prize[field] for field in PRIZE_FIELDS)
    assert set(prize["development_benchmark"]) <= set(problem.TARGETS) | set(problem.HOLDOUT)
    assert set(prize["holdout_benchmark"]) <= set(problem.TARGETS) | set(problem.HOLDOUT)
    assert prize["independent_verifier"] == "problems/hash_collision_prize/verify.py"
    assert prize["promotion_threshold"] == {"min_effect": 0.05, "seed_count": 5, "holdout_required": True}
    assert NON_CLAIM in prize["real_target"]
    assert set(prize["fitness_metrics"]) == set(problem.FITNESS_METRICS)


def test_problem_module_never_imports_a_solver():
    """The verifier path must stay independent of any solver module (prize contract isolation rule)."""
    source = (Path(records.HERE) / "problem.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)

    assert not {name for name in imported if "seed_solver" in name or name.split(".")[-1] == "solver"}
    assert {"records", "verify"} & imported


def test_a_solve_at_the_baseline_time_scores_above_the_fail_score(tmp_path):
    """The value floor must sit below every measured baseline, or a verified solve scores as a failure."""
    problem = load_problem("hash_collision_prize")
    baselines = records.load()
    assert problem.VALUE_FLOOR_SECONDS < min(baseline for baseline in baselines.values() if baseline is not None)

    path = tmp_path / "result.json"
    for target in problem.DEVELOPMENT:
        baseline = baselines[target]
        result = _collision(target, seed=1, budget=30.0)
        path.write_text(json.dumps(dict(result, elapsed=baseline, time_budget=60.0)))

        value, _payload = problem.evaluate(str(path), target)
        assert value == pytest.approx(baseline), f"{target}: the floor clamped a baseline-time solve"
        assert problem.score(value, baseline) > problem.FAIL_SCORE
