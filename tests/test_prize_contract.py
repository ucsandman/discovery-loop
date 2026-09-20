import copy
import importlib.util

import pytest

import prize_contract
from problem_loader import load_problem


DESCRIPTOR = {
    "objective": "Lower the verified wall time to a solved ladder instance.",
    "candidate_artifact": "solver.py writing {'target', 'k', 'iterations', 'elapsed'} to the --out path",
    "baseline": "problems/fake_prize/seed_solver.py",
    "development_benchmark": ["t-dev-1", "t-dev-2"],
    "holdout_benchmark": ["t-hold-1"],
    "independent_verifier": "problems/fake_prize/verify.py",
    "fitness_metrics": ["iterations", "iterations_per_second"],
    "real_target": "A public challenge instance, held as metadata only. Nothing is submitted.",
    "prize_registry_id": "certicom-eccp-131",
    "promotion_threshold": {"min_effect": 0.02, "seed_count": 3, "holdout_required": True},
    "estimated_scaling": "log2(seconds) = alpha + 0.5 * bits.",
    "publication_requirements": "Paired confirmation rows, the seeds, the machine and the scaling fit.",
    "submission_requirements": "Nothing is submitted; a real claim would be a manual step.",
}

BODY = """TARGETS = ["t-dev-1", "t-dev-2"]
HOLDOUT = ["t-hold-1"]
DEFAULTS = {"time": 60, "workers": 3}


def evaluate(path, t):
%(evaluate)s
    return 1.0, {"self_reported": True}


def score(v, rec):
    return 0.0


def beats(v, rec):
    return False


def validate_release(path, t, *, record=None):
    return {"ok": False, "supported": False}


PRIZE = %(prize)r
"""


def _plugin(tmp_path, *, name="fake_prize", prize=DESCRIPTOR, evaluate="    import verify", verifier=True):
    directory = tmp_path / "problems" / name
    directory.mkdir(parents=True, exist_ok=True)
    if verifier:
        (directory / "verify.py").write_text(
            "def check(value, target):\n    return {}\n", encoding="utf-8", newline="\n"
        )
    source = BODY % {"evaluate": evaluate, "prize": prize}
    path = directory / "problem.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location(f"{name}_problem", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_complete_plugin_satisfies_the_contract(tmp_path):
    module = _plugin(tmp_path)
    assert prize_contract.validate_prize_plugin(module, tmp_path) == {"ok": True, "missing": [], "errors": []}
    assert len(prize_contract.PRIZE_FIELDS) == 13


@pytest.mark.parametrize("field", prize_contract.PRIZE_FIELDS)
def test_removing_any_prize_field_fails(tmp_path, field):
    prize = copy.deepcopy(DESCRIPTOR)
    prize.pop(field)
    result = prize_contract.validate_prize_plugin(_plugin(tmp_path, prize=prize), tmp_path)
    assert result["ok"] is False
    assert result["missing"] == [field]


def test_evaluate_may_not_reach_for_the_measured_code(tmp_path):
    result = prize_contract.validate_prize_plugin(
        _plugin(tmp_path, evaluate="    import seed_solver\n    seed_solver.solve(path)"), tmp_path
    )
    assert result["ok"] is False
    assert any("seed_solver" in error for error in result["errors"])

    attribute = prize_contract.validate_prize_plugin(
        _plugin(tmp_path, name="attr_prize", evaluate="    return solver.rerun(path), {}"), tmp_path
    )
    assert attribute["ok"] is False
    assert any("references solver" in error for error in attribute["errors"])


@pytest.mark.parametrize(
    "prize_change, message",
    [
        ({"development_benchmark": ["t-dev-1", "t-unknown"]}, "outside TARGETS and HOLDOUT"),
        ({"holdout_benchmark": []}, "non-empty list of target names"),
        ({"objective": "  "}, "objective must be non-empty text"),
        ({"fitness_metrics": []}, "non-empty list or object"),
        ({"promotion_threshold": {"min_effect": 0.02, "seed_count": 3}}, "holdout_required must be true"),
        ({"promotion_threshold": {"min_effect": 0, "seed_count": 3, "holdout_required": True}}, "min_effect"),
        ({"promotion_threshold": {"min_effect": 0.02, "seed_count": 0, "holdout_required": True}}, "seed_count"),
        ({"independent_verifier": "problems/other_prize/verify.py"}, "names other_prize, not fake_prize"),
        ({"independent_verifier": "scripts/verify.py"}, "problems/<plugin>/verify.py"),
    ],
)
def test_a_present_but_wrong_field_is_an_error(tmp_path, prize_change, message):
    prize = copy.deepcopy(DESCRIPTOR)
    prize.update(prize_change)
    result = prize_contract.validate_prize_plugin(_plugin(tmp_path, prize=prize), tmp_path)
    assert result["ok"] is False
    assert any(message in error for error in result["errors"]), result["errors"]


def test_a_missing_verifier_file_is_reported(tmp_path):
    result = prize_contract.validate_prize_plugin(_plugin(tmp_path, verifier=False), tmp_path)
    assert result["ok"] is False
    assert any("independent_verifier file is missing" in error for error in result["errors"])


def test_a_plugin_without_a_prize_descriptor_reports_it(tmp_path):
    directory = tmp_path / "problems" / "plain"
    directory.mkdir(parents=True)
    path = directory / "problem.py"
    path.write_text("TARGETS = []\n", encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("plain_problem", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = prize_contract.validate_prize_plugin(module, tmp_path)
    assert result["ok"] is False
    assert "PRIZE" in result["missing"]
    assert "evaluate" in result["missing"]


def test_prize_plugins_lists_only_descriptor_carrying_directories(tmp_path):
    _plugin(tmp_path)
    (tmp_path / "problems" / "plain").mkdir(parents=True)
    (tmp_path / "problems" / "plain" / "problem.py").write_text("TARGETS = []\n", encoding="utf-8", newline="\n")
    (tmp_path / "problems" / "broken").mkdir(parents=True)
    (tmp_path / "problems" / "broken" / "problem.py").write_text("PRIZE = {\n", encoding="utf-8", newline="\n")

    assert prize_contract.prize_plugins(tmp_path) == ["fake_prize"]
    assert prize_contract.prize_plugins(tmp_path / "missing") == []


def test_every_installed_prize_plugin_satisfies_the_contract():
    plugins = prize_contract.prize_plugins()
    assert set(plugins) == {"circle_packing", "ecc_prize", "hash_collision_prize", "matrix_multiplication"}
    for name in plugins:
        result = prize_contract.validate_prize_plugin(load_problem(name))
        assert result == {"ok": True, "missing": [], "errors": []}, (name, result)
