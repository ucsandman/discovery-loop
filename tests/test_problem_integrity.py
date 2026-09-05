import importlib
import json
import math
from pathlib import Path

import pytest

from problem_loader import load_problem


ROOT = Path(__file__).resolve().parents[1]


def test_loader_uses_distinct_package_qualified_helpers():
    loaded = {name: load_problem(name) for name in ("circle_packing", "cvrp", "miplib", "miplib_open")}

    for name, problem in loaded.items():
        assert problem.__name__ == f"problems.{name}.problem"
        assert problem.records.__name__ == f"problems.{name}.records"
        assert problem.verify.__name__ == f"problems.{name}.verify"

    assert len({id(problem.records) for problem in loaded.values()}) == len(loaded)
    assert len({id(problem.verify) for problem in loaded.values()}) == len(loaded)


@pytest.mark.parametrize("name", ["../circle_packing", "circle-packing", "", "__pycache__"])
def test_loader_rejects_non_plugin_names(name):
    with pytest.raises((ValueError, ModuleNotFoundError)):
        load_problem(name)


def test_prompt_for_targets_does_not_reveal_other_named_instances():
    problem = load_problem("miplib_heur")
    chosen = problem.DEVELOPMENT[:1]
    prompt = problem.prompt_for_targets(chosen)

    assert chosen[0] in prompt
    assert all(name not in prompt for name in problem.DEVELOPMENT[1:])
    assert all(name not in prompt for name in problem.RELEASE_HOLDOUT)


def test_previously_exposed_targets_are_not_claimed_as_release_holdout():
    for name in ("circle_packing", "cvrp", "miplib", "miplib_open", "pglib_opf"):
        problem = load_problem(name)
        assert problem.DEVELOPMENT == problem.TARGETS
        assert problem.VALIDATION == []
        assert problem.RELEASE_HOLDOUT == []

    heuristic = load_problem("miplib_heur")
    assert heuristic.DEVELOPMENT == heuristic.TARGETS
    assert heuristic.VALIDATION == heuristic.HOLDOUT
    assert heuristic.RELEASE_HOLDOUT == []
    assert set(heuristic.DEVELOPMENT).isdisjoint(heuristic.VALIDATION)


@pytest.mark.parametrize(
    "circles",
    [
        [[math.nan, 0.5, 0.1]],
        [[0.5, math.inf, 0.1]],
        [[0.5, 0.5, math.inf]],
    ],
)
def test_circle_verifier_rejects_every_non_finite_coordinate(circles):
    verify = importlib.import_module("problems.circle_packing.verify")
    result = verify.check(circles, 1)

    assert result["feasible"] is False
    assert "finite" in result["error"]


def test_circle_record_requires_numerical_and_feasibility_margin(tmp_path):
    problem = load_problem("circle_packing")
    record = 1.0

    assert problem.beats(record + problem.WIN_MARGIN / 2, record) is False
    assert problem.beats(record + 2 * problem.WIN_MARGIN, record) is True

    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"n": 1, "circles": [[0.5, 0.5, 0.5]]}))
    result = problem.validate_release(candidate, "1", record=0.49)
    assert result["ok"] is False
    assert result["metrics"]["min_wall_slack"] == 0.0

    candidate.write_text(json.dumps({"n": 1, "circles": [[0.5, 0.5, 0.4]]}))
    result = problem.validate_release(candidate, "1", record=0.39)
    assert result["ok"] is True


def test_pglib_baseline_rounding_uncertainty_is_computed_from_source_text():
    records = importlib.import_module("problems.pglib_opf.records")

    assert records.baseline_uncertainty("pglib_opf_case3_lmbd") == pytest.approx(0.05)
    assert records.baseline_uncertainty("pglib_opf_case197_snem") == pytest.approx(0.00005)


def test_legacy_pglib_tolerance_exploit_is_not_release_valid():
    problem = load_problem("pglib_opf")
    target = "pglib_opf_case197_snem"
    case = Path(problem.records.INSTANCES) / f"{target}.m"
    if not case.exists():
        pytest.skip("local PGLib case is absent; live historical-candidate check requires the original input")
    candidate = ROOT / "best-pglib_opf" / "sol" / f"{target}.json"
    saved = json.loads(candidate.read_text())
    assert problem.beats(saved["obj"], problem.records_load()[target]) is True
    result = problem.validate_release(candidate, target)

    assert result["ok"] is False
    assert result["supported"] is True
    assert result["metrics"]["max_violation"] > problem.RELEASE_FEASIBILITY_TOL
    assert "original" in result["error"].lower()
    with pytest.raises(ValueError, match="infeasible"):
        problem.evaluate(candidate, target)


def test_mip_release_validators_fail_closed_on_missing_solution(tmp_path):
    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}")

    for name in ("miplib", "miplib_open", "miplib_heur"):
        problem = load_problem(name)
        result = problem.validate_release(candidate, problem.TARGETS[0])
        assert problem.RELEASE_VALIDATION_SUPPORTED is True
        assert result["ok"] is False
        assert result["supported"] is True
        assert result["error"]


def test_shared_mip_checker_accepts_official_point_and_rejects_non_finite_value():
    records = importlib.import_module("problems.miplib_open.records")
    verify = importlib.import_module("problems.miplib.verify")
    target = "assign1-10-4"
    instance = Path(records._R.INSTANCES) / f"{target}.mps"
    official = Path(records._R.INSTANCES) / f"{target}.bks.sol"
    if not instance.exists() or not official.exists():
        pytest.skip("local official MIPLIB point is absent")
    solution = records.parse_sol(official.read_text())

    accepted = verify.check(solution, target, tol=1e-8)
    assert accepted["feasible"] is True
    assert accepted["obj"] == pytest.approx(records.best_known(target))

    key = next(iter(solution))
    rejected = verify.check({**solution, key: math.inf}, target, tol=1e-8)
    assert rejected["feasible"] is False
    assert rejected["nonfinite_vars"] == [key]
