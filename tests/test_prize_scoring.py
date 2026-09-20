import json

import prize_scoring


def _prize(**overrides):
    prize = {
        "id": "example-prize",
        "name": "Example prize",
        "category": "benchmark-record",
        "status": "verified_active",
        "status_confidence": "high",
        "estimated_usd": 10000.0,
        "plugin": "example_plugin",
        "admission": "ready",
        "probability_category": "possible",
        "computational_difficulty": "moderate",
        "research_difficulty": "incremental",
        "compute_cost_estimate": {"category": "cheap", "note": "a few CPU hours"},
        "model_cost_estimate": {"category": "cheap", "note": "a handful of calls"},
        "publication_value": "medium",
        "commercial_value": "low",
        "transfer_value": "medium",
        "competition_level": "low",
        "time_horizon": "weeks",
        "parallelizable": True,
        "dense_feedback": True,
        "independent_verification": "strong",
        "research_priority": "active",
    }
    prize.update(overrides)
    return prize


def test_score_is_json_safe_and_separates_cash_from_credibility():
    score = prize_scoring.score_prize(_prize())
    json.dumps(score, allow_nan=False)
    assert score["prize_id"] == "example-prize"
    # 10000 USD x 0.15 probability x 1.0 status factor.
    assert score["cash_ev_usd"]["mid"] == 1500.0
    # medium + low + medium credibility categories, probability-weighted, status-independent.
    assert score["credibility_ev_usd"]["mid"] == round((3000.0 + 500.0 + 3000.0) * 0.15, 4)
    assert score["cash_ev_usd"]["low"] <= score["cash_ev_usd"]["mid"] <= score["cash_ev_usd"]["high"]
    assert score["bucket"] == "measurable-progress"
    assert 0.0 <= score["information_gain"] <= 1.0
    assert score["rationale"]


def test_closed_status_zeroes_the_cash_expectation():
    score = prize_scoring.score_prize(_prize(status="closed", research_priority="excluded"))
    assert score["cash_ev_usd"] == {"low": 0.0, "mid": 0.0, "high": 0.0}
    assert score["bucket"] == "excluded"
    assert score["priority_score"] == 0.0


def test_probability_categories_map_monotonically():
    order = ["negligible", "remote", "unlikely", "possible", "likely"]
    scores = [prize_scoring.score_prize(_prize(probability_category=name))["cash_ev_usd"]["mid"] for name in order]
    assert scores == sorted(scores)
    assert scores[0] < scores[-1]


def test_big_hopeless_prize_ranks_below_a_small_tractable_one():
    hopeless = _prize(
        id="hopeless",
        estimated_usd=100000.0,
        probability_category="negligible",
        computational_difficulty="infeasible_today",
        research_difficulty="breakthrough_required",
        dense_feedback=False,
        independent_verification="weak",
        compute_cost_estimate={"category": "prohibitive", "note": "2^131 operations"},
        model_cost_estimate={"category": "expensive", "note": "long generations"},
        time_horizon="open_ended",
    )
    tractable = _prize(id="tractable", estimated_usd=10000.0)
    ranked = prize_scoring.rank([hopeless, tractable])
    assert [row["prize_id"] for row in ranked] == ["tractable", "hopeless"]
    assert ranked[0]["bucket"] == "measurable-progress"
    assert ranked[1]["bucket"] == "moonshot"


def test_rank_puts_excluded_prizes_last_even_when_scored_high():
    excluded = _prize(id="excluded-but-rich", estimated_usd=500000.0, research_priority="excluded")
    ordinary = _prize(id="ordinary", estimated_usd=1.0)
    ranked = prize_scoring.rank([excluded, ordinary])
    assert [row["prize_id"] for row in ranked] == ["ordinary", "excluded-but-rich"]


def test_measured_progress_raises_information_gain_only():
    plain = prize_scoring.score_prize(_prize())
    with_progress = prize_scoring.score_prize(_prize(), progress={"best_gain": 0.2, "attempts": 4})
    assert with_progress["information_gain"] > plain["information_gain"]
    assert with_progress["cash_ev_usd"] == plain["cash_ev_usd"]


def test_allocate_respects_the_max_share_cap_and_stays_within_the_allowance():
    strong = _prize(id="strong", estimated_usd=40000.0)
    weak = _prize(id="weak", estimated_usd=10.0)
    moon = _prize(id="moon", estimated_usd=20000.0, probability_category="remote")
    plan = prize_scoring.allocate(
        [strong, weak, moon], allowance_usd=10.0, minutes=60, moonshot_share=0.2, max_share=0.5
    )
    json.dumps(plan, allow_nan=False)
    by_id = {item["prize_id"]: item for item in plan["allocations"]}
    assert by_id["strong"]["usd"] <= 5.0
    assert any("capped" in note for note in plan["notes"])
    total = sum(item["usd"] for item in plan["allocations"])
    assert total + plan["unallocated_usd"] <= 10.0 + 0.01
    assert by_id["moon"]["bucket"] == "moonshot"
    assert all(item["minutes"] >= 1 for item in plan["allocations"])


def test_allocate_skips_excluded_and_unready_prizes():
    ready = _prize(id="ready")
    unready = _prize(id="unready", admission="needs_setup")
    excluded = _prize(id="excluded", research_priority="excluded")
    plan = prize_scoring.allocate([ready, unready, excluded], allowance_usd=8.0, minutes=30)
    assert [item["prize_id"] for item in plan["allocations"]] == ["ready"]
    assert any("unready" in note for note in plan["notes"])
    assert all("excluded" not in note for note in plan["notes"])


def test_allocate_is_empty_for_a_non_positive_allowance():
    plan = prize_scoring.allocate([_prize()], allowance_usd=0.0, minutes=60)
    assert plan["allocations"] == []
    assert plan["notes"] == ["allowance is zero or negative; nothing planned"]


def test_allocate_is_deterministic():
    prizes = [_prize(id="a"), _prize(id="b", estimated_usd=2000.0), _prize(id="c", probability_category="unlikely")]
    first = prize_scoring.allocate(prizes, allowance_usd=12.0, minutes=90)
    second = prize_scoring.allocate(list(reversed(prizes)), allowance_usd=12.0, minutes=90)
    assert first == second


def test_admission_defaults_to_the_presence_of_a_plugin():
    assert prize_scoring.score_prize({"id": "x", "plugin": "cvrp"})["admission"] == "ready"
    assert prize_scoring.score_prize({"id": "x", "plugin": None})["admission"] == "needs_setup"


def test_score_prize_tolerates_junk_without_raising():
    score = prize_scoring.score_prize({"id": "junk", "estimated_usd": "lots", "probability_category": "certain"})
    json.dumps(score, allow_nan=False)
    assert score["cash_ev_usd"]["mid"] == 0.0
    assert score["bucket"] in prize_scoring.BUCKETS


def test_load_prizes_returns_a_list_when_no_registry_data_exists(tmp_path):
    assert prize_scoring.load_prizes(tmp_path) == []
