from research_state import atomic_json
from trial_report import summarize


def test_comparison_counts_failures_and_excludes_manual_probes(tmp_path):
    evidence = {
        "problem": "cvrp",
        "provider": "paired",
        "status": "completed",
        "confirmed": True,
        "usage": {"calls": 3, "charged": 2},
        "solver_seconds": 3600,
        "solver_evaluations": 12,
        "confirmation": {"median_gain": 0.01},
    }
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/evidence.json", evidence)
    atomic_json(tmp_path / "runs/research/manual-probe/cvrp/evidence.json", evidence)
    failed = {**evidence, "status": "failed", "confirmed": False, "confirmation": {}}
    atomic_json(tmp_path / "runs/research/2026-09-06/cvrp/evidence.json", failed)
    report = summarize(tmp_path)
    assert report["runs"] == 2
    assert report["rows"][0]["confirmed"] == 1
    assert report["rows"][0]["completed"] == 1
    assert report["rows"][0]["allowance_charged"] == 4
    assert report["rows"][0]["confirmed_per_solver_hour"] == 0.5


def test_empty_trial_is_not_reported_as_a_winner(tmp_path):
    assert summarize(tmp_path)["rows"] == []
    assert summarize(tmp_path)["runs"] == 0
