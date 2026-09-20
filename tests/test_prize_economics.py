import json
import math

import pytest

import prize_economics
import prize_scaling


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _candidate(iteration, idea, *, cost=2.0, gain=None, call_id=None, rows=None, status="promising"):
    record = {
        "problem": "ecc_prize",
        "iteration": iteration,
        "provider": "fable",
        "idea": idea,
        "model": "claude-opus-5",
        "actual_model": "claude-opus-5",
        "family": "anthropic",
        "role": "generation",
        "cost_usd": cost,
        "elapsed_seconds": 120.0,
        "status": status,
        "median_gain": gain,
    }
    if call_id:
        record["routing_attempts"] = [{"logical_call_id": call_id, "physical": True}]
    if rows is not None:
        record["rows"] = rows
    return record


def _run(tmp_path, run_id, candidates, *, solver_seconds=3600.0, attempts=()):
    _write_json(
        tmp_path / "runs" / "research" / run_id / "ecc_prize" / "evidence.json",
        {
            "run_id": run_id,
            "problem": "ecc_prize",
            "solver_seconds": solver_seconds,
            "development": {"candidates": candidates},
        },
    )
    if attempts:
        _write_json(
            tmp_path / "runs" / "research" / run_id / "routing.json",
            {"schema_version": 1, "attempts": list(attempts)},
        )


def test_local_compute_usd_uses_the_published_constants():
    assert prize_economics.local_compute_usd(3600.0) == pytest.approx(
        prize_economics.LOCAL_KWH_PER_HOUR * prize_economics.USD_PER_KWH
    )
    assert prize_economics.local_compute_usd(-5) == 0.0
    assert prize_economics.local_compute_usd("nope") == 0.0


def test_ledger_reads_candidates_costs_and_reported_prices(tmp_path):
    _run(
        tmp_path,
        "2026-09-19",
        [
            _candidate(0, "IDEA: [kind: batched inversion] invert 64 walks at once", gain=0.21, call_id="call-a"),
            _candidate(1, "IDEA: [kind: batched inversion] widen the batch to 256", gain=0.02, call_id="call-b"),
        ],
        solver_seconds=7200.0,
        attempts=[
            {"logical_call_id": "call-a", "physical": True, "scope": "ecc_prize", "reported_cost": 0.91},
            {"logical_call_id": "call-b", "physical": True, "scope": "ecc_prize", "reported_cost": None},
            {"logical_call_id": "call-c", "physical": True, "scope": "cvrp", "reported_cost": 5.0},
            {"logical_call_id": "call-a", "physical": False, "scope": "ecc_prize", "reported_cost": 99.0},
        ],
    )
    book = prize_economics.ledger(tmp_path, "ecc_prize")
    json.dumps(book, allow_nan=False)

    assert book["problem"] == "ecc_prize"
    assert book["runs"] == ["2026-09-19"]
    assert len(book["candidates"]) == 2
    first, second = book["candidates"]
    # No per-row solver seconds: each candidate carries an equal share of the run total.
    assert first["solver_seconds"] == 3600.0
    assert first["local_compute_usd"] == pytest.approx(0.0225)
    assert first["reported_cost_usd"] == 0.91
    assert second["reported_cost_usd"] is None
    assert first["family"] == "batched inversion"
    assert first["model_family"] == "anthropic"
    assert book["totals"]["model_usd"] == 4.0
    assert book["totals"]["reported_usd"] == 0.91
    assert book["totals"]["solver_seconds"] == 7200.0
    assert book["totals"]["best_gain"] == 0.21
    assert any("charged allowance" in note for note in book["assumptions"])


def test_ledger_prefers_per_candidate_solver_rows_when_present(tmp_path):
    _run(
        tmp_path,
        "2026-09-19",
        [_candidate(0, "IDEA: [kind: rho walk] negation map", rows=[{"secs": 10.0}, {"secs": 5.0}])],
        solver_seconds=9999.0,
    )
    book = prize_economics.ledger(tmp_path, "ecc_prize")
    assert book["candidates"][0]["solver_seconds"] == 15.0


def test_ledger_is_empty_and_honest_without_runs(tmp_path):
    book = prize_economics.ledger(tmp_path, "ecc_prize")
    assert book["candidates"] == []
    assert book["directions"] == []
    assert book["totals"]["best_gain"] is None
    assert book["totals"]["model_usd"] == 0.0


def test_direction_summary_sentences_match_the_requested_wording():
    keep = prize_economics.direction_summary(
        [
            {"family": "batched inversion", "problem": "ecc_prize", "cost_usd": 3.0, "median_gain": 0.21},
        ]
    )
    assert keep[0]["verdict"] == "keep"
    assert keep[0]["sentence"] == (
        "This direction improved performance by 21 percent for approximately $3 equivalent research cost."
    )

    stop = prize_economics.direction_summary(
        [
            {"family": "sat encoding", "problem": "ecc_prize", "cost_usd": 2.4, "median_gain": -0.01, "run_id": "r1"}
            for _ in range(5)
        ]
    )
    assert stop[0]["verdict"] == "stop"
    assert stop[0]["attempts"] == 5
    assert stop[0]["sentence"] == (
        "This research branch consumed $12 across 5 attempts with no scaling improvement. Stop exploring it."
    )


def test_direction_summary_watches_a_thin_branch_and_orders_keep_first():
    directions = prize_economics.direction_summary(
        [
            {"family": "thin", "problem": "ecc_prize", "cost_usd": 1.0, "median_gain": 0.001},
            {"family": "good", "problem": "ecc_prize", "cost_usd": 1.0, "median_gain": 0.3},
        ]
    )
    assert [item["family"] for item in directions] == ["good", "thin"]
    assert directions[1]["verdict"] == "watch"
    assert "not enough evidence yet" in directions[1]["sentence"]
    assert directions[0]["gain_per_usd"] == pytest.approx(0.3)


def test_stop_recommendations_are_dead_end_shaped(tmp_path):
    _run(
        tmp_path,
        "2026-09-19",
        [_candidate(index, "IDEA: [kind: sat encoding] encode the group law", gain=-0.05) for index in range(3)],
    )
    book = prize_economics.ledger(tmp_path, "ecc_prize")
    recommendations = prize_economics.stop_recommendations(book)
    assert len(recommendations) == 1
    entry = recommendations[0]
    assert set(entry) == {"problem", "approach", "why_failed", "evidence", "tags"}
    assert entry["problem"] == "ecc_prize"
    assert entry["approach"].startswith("sat encoding:")
    assert "Stop exploring it." in entry["why_failed"]
    assert "runs/research/2026-09-19/ecc_prize/evidence.json" in entry["evidence"]
    assert "ecc_prize" in entry["tags"] and "sat" in entry["tags"]


def test_record_dead_end_numbers_from_the_highest_existing_id_not_the_length(tmp_path):
    _write_json(
        tmp_path / "problems" / "_dead_ends.json",
        [
            {"id": "de-001", "problem": "general", "approach": "a", "why_failed": "b"},
            {"id": "de-005", "problem": "cvrp", "approach": "c", "why_failed": "d"},
        ],
    )
    first = prize_economics.record_dead_end(
        tmp_path,
        {
            "problem": "ecc_prize",
            "approach": "sat encoding of the group law",
            "why_failed": "no measured improvement across 3 attempts",
            "evidence": "runs/research/2026-09-19/ecc_prize/evidence.json",
            "tags": ["SAT", " sat ", "ecc_prize"],
            "date": "2026-09-20",
        },
        "dashboard",
    )
    assert first["id"] == "de-006"
    assert first["tags"] == ["ecc_prize", "sat"]
    assert first["recorded_by"] == "dashboard"
    assert first["date"] == "2026-09-20"

    second = prize_economics.record_dead_end(
        tmp_path, {"problem": "ecc_prize", "approach": "another", "why_failed": "also nothing"}, "operator"
    )
    assert second["id"] == "de-007"

    stored = json.loads((tmp_path / "problems" / "_dead_ends.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in stored] == ["de-001", "de-005", "de-006", "de-007"]
    assert (tmp_path / "problems" / "_dead_ends.json.lock").exists()


def test_record_dead_end_starts_a_fresh_ledger_and_refuses_junk(tmp_path):
    entry = prize_economics.record_dead_end(tmp_path, {"approach": "x", "why_failed": "y"}, "operator")
    assert entry["id"] == "de-001"
    assert entry["problem"] == "general"

    with pytest.raises(ValueError):
        prize_economics.record_dead_end(tmp_path, {"approach": "", "why_failed": "y"}, "operator")

    (tmp_path / "problems" / "_dead_ends.json").write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(ValueError):
        prize_economics.record_dead_end(tmp_path, {"approach": "x", "why_failed": "y"}, "operator")


def test_progress_is_the_shape_prize_scoring_expects(tmp_path):
    _run(tmp_path, "2026-09-19", [_candidate(0, "IDEA: [kind: rho walk] tune", gain=0.12)])
    summary = prize_economics.progress(tmp_path, "ecc_prize")
    assert summary["best_gain"] == 0.12
    assert summary["attempts"] == 1
    assert summary["model_usd"] == 2.0


def _fitted_analysis():
    points = [{"bits": size, "seconds": 2.0 ** (-8.0 + 0.5 * size)} for size in (24, 28, 32, 36)]
    fit = prize_scaling.fit_scaling(points)
    return {"fit": fit, "target_bits": 131, "extrapolation": prize_scaling.extrapolate(fit, 131)}


def test_ev_impact_reports_the_verdict_move_without_fake_precision():
    impact = prize_economics.ev_impact(_fitted_analysis(), 0.21)
    json.dumps(impact, allow_nan=False)
    assert impact["speedup"] == pytest.approx(1.0 / 0.79, rel=1e-6)
    assert impact["verdict_before"] == "infeasible"
    assert impact["verdict_after"] == "infeasible"
    assert "does not change the verdict" in impact["sentence"]
    # log2(1/0.79) / beta, with beta = 0.5: a 21 percent gain buys under one bit of instance size.
    assert impact["bits_equivalent"] == pytest.approx(math.log2(1.0 / 0.79) / 0.5, rel=1e-3)
    assert "bits of instance size" in impact["sentence"]


def test_ev_impact_can_flip_a_small_target_from_expensive_to_feasible():
    points = [{"bits": size, "seconds": 2.0 ** (-8.0 + 0.5 * size)} for size in (24, 28, 32, 36)]
    fit = prize_scaling.fit_scaling(points)
    analysis = {"fit": fit, "target_bits": 70, "extrapolation": prize_scaling.extrapolate(fit, 70)}
    assert analysis["extrapolation"]["verdict"] == "expensive"
    impact = prize_economics.ev_impact(analysis, 0.95)
    assert impact["verdict_after"] == "feasible"
    assert "changes the verdict" in impact["sentence"]


def test_ev_impact_is_quiet_when_there_is_no_gain_or_no_ladder():
    none_yet = prize_economics.ev_impact(_fitted_analysis(), 0.0)
    assert none_yet["speedup"] is None
    assert "unchanged" in none_yet["sentence"]

    no_fit = prize_economics.ev_impact({"scaling": {}}, 0.2)
    assert no_fit["speedup"] is not None
    assert "unknown" in no_fit["sentence"]

    nonsense = prize_economics.ev_impact(_fitted_analysis(), 1.5)
    assert nonsense["speedup"] is None
    assert "not interpretable" in nonsense["sentence"]
