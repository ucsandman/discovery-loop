"""Integrity tests for the matrix_multiplication problem plugin."""

import json
import random

from problem_loader import load_problem


def test_plugin_loads_with_isolated_helpers():
    problem = load_problem("matrix_multiplication")
    assert problem.__name__ == "problems.matrix_multiplication.problem"
    assert problem.TARGETS == ["2", "3", "4"]
    assert problem.DEVELOPMENT == problem.TARGETS
    assert problem.MAXIMIZE is False
    assert problem.records_load() == {"2": 7, "3": 23, "4": 49}


def test_verifier_accepts_seed_and_rejects_tampering():
    from problems.matrix_multiplication import seed_solver as seed
    from problems.matrix_multiplication import verify

    for n in (2, 3, 4):
        factors = seed.factors_for(n)
        res = verify.check(factors, n)
        assert res["feasible"] is True, res["reason"]
        # Bilinear evaluation matches naive multiplication on random inputs.
        for _ in range(10):
            A = [[random.randint(-5, 5) for _ in range(n)] for _ in range(n)]
            B = [[random.randint(-5, 5) for _ in range(n)] for _ in range(n)]
            assert verify.apply(factors, A, B) == verify.naive_product(A, B)

    bad = seed.factors_for(2)
    bad[0][0][0][0] += 1
    assert verify.check(bad, 2)["feasible"] is False
    assert verify.check([], 2)["feasible"] is False
    assert verify.check(seed.factors_for(2), 3)["feasible"] is False


def test_strassen_hits_calibration_target():
    from problems.matrix_multiplication import seed_solver as seed
    from problems.matrix_multiplication import verify

    assert len(seed.strassen_factors()) == 7
    assert verify.check(seed.strassen_factors(), 2)["feasible"] is True


def test_evaluate_score_beats_roundtrip(tmp_path):
    problem = load_problem("matrix_multiplication")
    from problems.matrix_multiplication import seed_solver as seed

    rec = problem.records_load()
    for t in problem.TARGETS:
        path = tmp_path / f"n{t}.json"
        path.write_text(
            json.dumps(
                {"target": t, "rank": len(seed.factors_for(int(t))), "factors": seed.factors_for(int(t))}
            )
        )
        value, _ = problem.evaluate(str(path), t)
        assert value == len(seed.factors_for(int(t)))
        # Seed never beats a record (n=2 ties the optimum, n=4 ties the record).
        assert problem.beats(value, rec[t]) is False
        if t in ("2", "4"):
            assert value == rec[t]
            assert problem.score(value, rec[t]) == 0.0
        else:
            assert problem.score(value, rec[t]) < 0.0
    # A hypothetical rank-22 for n=3 beats the record.
    assert problem.beats(22, rec["3"]) is True
    assert problem.score(22, rec["3"]) > 0.0


def test_prompt_for_targets_does_not_leak_other_targets():
    problem = load_problem("matrix_multiplication")
    prompt = problem.prompt_for_targets(["3"])
    assert "n=3" in prompt
    assert "n=2" not in prompt and "n=4" not in prompt
