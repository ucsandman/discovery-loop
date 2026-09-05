import math
import types

import pytest

import evaluation


def test_matrix_repeats_the_same_seeds_for_every_target():
    matrix = evaluation.build_matrix(["a", "b"], seed_count=3, base_seed=40)
    assert matrix == [
        {"target": "a", "seed": 40},
        {"target": "b", "seed": 40},
        {"target": "a", "seed": 41},
        {"target": "b", "seed": 41},
        {"target": "a", "seed": 42},
        {"target": "b", "seed": 42},
    ]


def test_matrix_rejects_duplicate_targets():
    with pytest.raises(ValueError, match="unique"):
        evaluation.build_matrix(["a", "a"], seed_count=3)


def test_paired_gate_uses_median_effect_and_preserves_per_seed_distribution():
    incumbent = [
        {"target": "a", "seed": 1, "score": 1.0, "failed": False},
        {"target": "b", "seed": 1, "score": 1.0, "failed": False},
        {"target": "a", "seed": 2, "score": 1.0, "failed": False},
        {"target": "b", "seed": 2, "score": 1.0, "failed": False},
    ]
    candidate = [
        {"target": "a", "seed": 1, "score": 1.2, "failed": False},
        {"target": "b", "seed": 1, "score": 1.1, "failed": False},
        {"target": "a", "seed": 2, "score": 1.3, "failed": False},
        {"target": "b", "seed": 2, "score": 0.9, "failed": False},
    ]
    result = evaluation.compare_paired(incumbent, candidate, min_effect=0.1, min_seeds=2)
    assert result["median_gain"] == pytest.approx(0.15)
    assert result["passes"] is True
    assert result["per_seed"] == [
        {"seed": 1, "median_gain": pytest.approx(0.15), "gains": pytest.approx([0.2, 0.1])},
        {"seed": 2, "median_gain": pytest.approx(0.1), "gains": pytest.approx([0.3, -0.1])},
    ]


def test_paired_gate_rejects_a_higher_failure_rate_despite_large_gain():
    incumbent = [{"target": "a", "seed": 1, "score": 0.0, "failed": False}]
    candidate = [{"target": "a", "seed": 1, "score": 10.0, "failed": True}]
    result = evaluation.compare_paired(incumbent, candidate, min_effect=1.0)
    assert result["median_gain"] == 10.0
    assert result["failure_rate_ok"] is False
    assert result["passes"] is False


def test_paired_gate_rejects_mismatched_or_nonfinite_rows():
    good = [{"target": "a", "seed": 1, "score": 0.0}]
    with pytest.raises(ValueError, match="matrix mismatch"):
        evaluation.compare_paired(good, [{"target": "a", "seed": 2, "score": 1.0}], 0.1)
    with pytest.raises(ValueError, match="non-finite"):
        evaluation.compare_paired(good, [{"target": "a", "seed": 1, "score": math.nan}], 0.1)


def test_paired_gate_requires_three_distinct_seeds_for_confirmation():
    incumbent = [{"target": "a", "seed": seed, "score": 0.0, "failed": False} for seed in (1, 2)]
    candidate = [{"target": "a", "seed": seed, "score": 1.0, "failed": False} for seed in (1, 2)]
    result = evaluation.compare_paired(incumbent, candidate, min_effect=0.1)
    assert result["replication_ok"] is False
    assert result["passes"] is False


def test_manifest_keeps_existing_holdout_out_of_development_and_discloses_reuse():
    problem = types.SimpleNamespace(TARGETS=["train-a", "train-b"], HOLDOUT=["holdout-a"])
    manifest = evaluation.build_manifest(problem, "miplib_heur")
    assert manifest["confirmation"] == ["holdout-a"]
    assert manifest["release_holdout"] == []
    assert manifest["classification"] == "reused_holdout_confirmation"
    assert any("not a sealed generalization test" in line for line in manifest["limitations"])


def test_manifest_preserves_explicit_train_and_holdout_counts():
    training = [f"train-{index}" for index in range(16)]
    holdout = [f"holdout-{index}" for index in range(10)]
    problem = types.SimpleNamespace(
        TARGETS=training,
        DEVELOPMENT=training,
        VALIDATION=holdout,
        HOLDOUT=holdout,
        RELEASE_HOLDOUT=[],
    )
    manifest = evaluation.build_manifest(problem, "miplib_heur")
    assert manifest["development"] == training
    assert manifest["confirmation"] == holdout


def test_manifest_labels_legacy_validation_as_previously_exposed():
    targets = [f"seen-{i}" for i in range(10)]
    manifest = evaluation.build_manifest(types.SimpleNamespace(TARGETS=targets), "cvrp")
    assert manifest["development"] and manifest["validation"]
    assert set(manifest["development"] + manifest["validation"]) == set(targets)
    assert set(manifest["previously_exposed"]) == set(targets)
    assert manifest["classification"] == "previously_exposed_benchmark_validation"
    assert any("not unseen generalization" in line for line in manifest["limitations"])
