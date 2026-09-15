from research_state import atomic_json
from trial_report import summarize


def _routing(arm, attempts):
    return {
        "requested_arm": arm,
        "mode": "scheduled",
        "formal_trial_eligible": True,
        "ineligibility_reasons": [],
        "attempts": attempts,
    }


def _attempt(arm, *, physical=True):
    return {
        "model": f"{arm}-model",
        "requested_alias": arm,
        "model_alias": arm,
        "family": "synthetic",
        "physical": physical,
        "status": "completed",
        "charged_allowance": 1.0,
    }


def _evidence(problem, provider, routing):
    return {
        "problem": problem,
        "provider": provider,
        "status": "completed",
        "confirmed": True,
        "usage": {"calls": 1, "charged": 1.0},
        "routing": routing,
    }


def _retro(arm):
    return {"status": "completed", "routing": _routing(arm, [])}


def test_suffixed_scheduled_runs_are_covered_and_extras_are_operational(tmp_path):
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")])),
    )
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/retro.json", _retro("fable"))
    atomic_json(
        tmp_path / "runs/research/2026-09-06-scheduled/cvrp/evidence.json",
        _evidence("cvrp", "astra", _routing("astra", [_attempt("astra")])),
    )
    atomic_json(tmp_path / "runs/research/2026-09-06-scheduled/cvrp/retro.json", _retro("astra"))
    atomic_json(
        tmp_path / "runs/research/2026-09-06/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")])),
    )
    atomic_json(tmp_path / "runs/research/2026-09-06/cvrp/retro.json", _retro("fable"))
    atomic_json(
        tmp_path / "runs/research/2026-09-05/matrix_multiplication/evidence.json",
        _evidence("matrix_multiplication", "paired", _routing("paired", [_attempt("fable")])),
    )
    atomic_json(tmp_path / "runs/research/2026-09-05/matrix_multiplication/retro.json", _retro("paired"))
    atomic_json(
        tmp_path / "runs/research/2026-99-99/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")])),
    )
    atomic_json(
        tmp_path / "runs/research/manual-probe/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")])),
    )

    report = summarize(tmp_path)

    assert report["clean_runs"] == 2
    coverage = report["coverage"]
    assert coverage["observed_date_window"] == {"start": "2026-09-05", "end": "2026-09-06", "days": 2}
    assert coverage["expected_slots"] == 28
    assert coverage["completed_slots"] == 2
    assert coverage["attempted_research_calls"] == 2
    assert coverage["successful_research_calls"] == 2
    assert coverage["successful_generation_calls"] == 2
    assert coverage["generation_research_calls"] == 2
    assert coverage["critique_research_calls"] == 0
    assert coverage["partial_cycle"] is True and coverage["complete"] is False
    assert len(coverage["missing_slots"]) == 26
    assert any(row["provenance"] == "historical_duplicate" for row in report["operational_rows"])
    assert any(
        row["problem"] == "matrix_multiplication" and row["provenance"] == "operational_extra"
        for row in report["operational_rows"]
    )


def test_clean_rows_require_physical_matching_research_calls_and_completed_retro(tmp_path):
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [_attempt("fable", physical=False)])),
    )
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/retro.json", _retro("fable"))
    atomic_json(
        tmp_path / "runs/research/2026-09-06/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")])),
    )
    atomic_json(tmp_path / "runs/research/2026-09-06/cvrp/retro.json", _retro("fable"))

    report = summarize(tmp_path)

    assert report["clean_rows"] == []
    assert report["coverage"]["attempted_research_calls"] == 1
    assert report["coverage"]["successful_research_calls"] == 1
    assert report["ineligible_reasons"] == {
        "no_successful_physical_research_call": 1,
        "requested_arm_does_not_match_trial_assignment": 1,
        "successful_call_does_not_match_requested_arm": 1,
    }


def test_critique_only_physical_success_cannot_make_a_clean_generation_slot(tmp_path):
    critique = _attempt("fable")
    critique["purpose"] = "critique"
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [critique])),
    )
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/retro.json", _retro("fable"))

    report = summarize(tmp_path)

    assert report["clean_rows"] == []
    assert report["coverage"]["attempted_research_calls"] == 1
    assert report["coverage"]["successful_research_calls"] == 1
    assert report["coverage"]["generation_research_calls"] == 0
    assert report["coverage"]["critique_research_calls"] == 1
    assert report["ineligible_reasons"]["no_successful_physical_research_call"] == 1


def test_clean_rows_require_completed_evidence_and_explicitly_eligible_retro(tmp_path):
    running = _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")]))
    running["status"] = "running"
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/evidence.json", running)
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/retro.json", _retro("fable"))
    atomic_json(
        tmp_path / "runs/research/2026-09-06/cvrp/evidence.json",
        _evidence("cvrp", "astra", _routing("astra", [_attempt("astra")])),
    )
    atomic_json(
        tmp_path / "runs/research/2026-09-06/cvrp/retro.json",
        {"status": "completed", "routing": {**_routing("astra", []), "formal_trial_eligible": False}},
    )

    report = summarize(tmp_path)

    assert report["clean_rows"] == []
    assert report["ineligible_reasons"]["research_not_completed"] == 1
    assert report["ineligible_reasons"]["retro_not_formally_eligible"] == 1


def test_duplicate_history_cannot_merge_with_a_scheduled_operational_fallback(tmp_path):
    for run_id in ("2026-09-06", "2026-09-06-scheduled"):
        atomic_json(
            tmp_path / f"runs/research/{run_id}/cvrp/evidence.json",
            _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")])),
        )
        atomic_json(tmp_path / f"runs/research/{run_id}/cvrp/retro.json", _retro("fable"))

    report = summarize(tmp_path)
    rows = [row for row in report["operational_rows"] if row["problem"] == "cvrp" and row["provider"] == "fable"]

    assert {(row["provenance"], row["runs"]) for row in rows} == {
        ("historical_duplicate", 1),
        ("routing_recorded_ineligible", 1),
    }
    assert report["coverage"]["successful_research_calls"] <= report["coverage"]["attempted_research_calls"]


def test_trial_track_outside_configured_cycle_is_an_operational_extra(tmp_path):
    atomic_json(
        tmp_path / "runs/research/2026-10-01/cvrp/evidence.json",
        _evidence("cvrp", "fable", _routing("fable", [_attempt("fable")])),
    )
    atomic_json(tmp_path / "runs/research/2026-10-01/cvrp/retro.json", _retro("fable"))

    report = summarize(tmp_path)

    assert report["clean_runs"] == 0
    assert report["operational_rows"][0]["provenance"] == "operational_extra"
    assert report["coverage"]["completed_slots"] == 0
