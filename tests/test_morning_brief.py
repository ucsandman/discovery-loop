import hashlib
import json
import urllib.request

import pytest

import dashboard
import morning_brief
from research_state import atomic_json

CANDIDATE_HASH = "a" * 64


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _night(run_id, status, slots, started, **extra):
    return {
        "schema_version": 2,
        "run_id": run_id,
        "status": status,
        "started_at": started,
        "updated_at": started.replace("02:00", "07:30"),
        "budget_limit_api_equivalent": 105.0,
        "budget_used_api_equivalent": 60.5,
        "slots": slots,
        "limitations": ["matrix_multiplication research skipped because its admitted mission is disabled"],
        **extra,
    }


def _slot(problem, provider, status, kind="research"):
    return {
        "id": f"{problem}-research",
        "problem": problem,
        "kind": kind,
        "provider": provider,
        "status": status,
        "stages": {"research": {"status": status, "work_count": 3}},
    }


def _evidence(problem, *, confirmed, publishable, reason=None):
    return {
        "run_id": "2026-09-10-scheduled",
        "problem": problem,
        "provider": "fable",
        "status": "completed",
        "confirmed": confirmed,
        "publishable": publishable,
        "publishable_reason": reason,
        "claim_type": "benchmark_record" if publishable else "benchmark_tuning",
        "candidate_hash": CANDIDATE_HASH,
        "candidate_path": f"runs/research/2026-09-10-scheduled/{problem}/candidates/iter001-fable/solver.py",
        "usage": {
            "calls": 4,
            "charged": 3.5,
            "iterations": 2,
            "by_model": {"claude-opus-5": 3, "gpt-6-astra": 1},
        },
        "development": {
            "candidates": [
                {
                    "iteration": 0,
                    "provider": "fable",
                    "actual_model": "claude-opus-5",
                    "idea": "[kind: ruin and recreate] " + "x" * 400,
                    "median_gain": -0.001,
                    "status": "rejected",
                    "valid": True,
                },
                {
                    "iteration": 1,
                    "provider": "fable",
                    "actual_model": "claude-opus-5",
                    "idea": "gated SWAP* with split",
                    "median_gain": 0.0021,
                    "comparison": {"median_lower_bound": 0.0008, "distinct_seeds": 3},
                    "status": "promising",
                    "valid": True,
                },
                {
                    "iteration": 1,
                    "provider": "astra",
                    "generation_error": "astra CLI reported an error",
                    "status": "generation_failed",
                    "valid": False,
                },
            ]
        },
        "confirmation": {
            "median_gain": 0.0015,
            "pairs": [
                {"target": "X-n401-k29", "seed": 1, "gain": 0.002, "candidate_failed": False},
                {"target": "X-n401-k29", "seed": 2, "gain": -0.0005, "candidate_failed": False},
                {"target": "X-n491-k59", "seed": 1, "gain": 0.001, "candidate_failed": False},
            ],
        },
        "release_checks": [
            {
                "target": "X-n401-k29",
                "ok": publishable,
                "error": None if publishable else "cost does not beat the integer record",
            },
        ],
        "generation_stop": {"reason": "budget_exhausted"},
        "limitations": ["Confirmation on this split measures repeatability on known benchmark data."],
    }


@pytest.fixture
def research_root(tmp_path):
    night_dir = tmp_path / "runs" / "research" / "2026-09-10-scheduled"
    _write(
        night_dir / "night.json",
        _night(
            "2026-09-10-scheduled",
            "completed",
            [_slot("cvrp", "fable", "completed"), _slot("pglib_opf", None, "completed", kind="validation")],
            "2026-09-11T02:00:00Z",
            scheduled_run_id="2026-09-10",
            trial={"index": 5, "assignment": {"cvrp": "fable", "order": ["cvrp"]}},
        ),
    )
    _write(night_dir / "cvrp" / "evidence.json", _evidence("cvrp", confirmed=True, publishable=True))
    _write(
        night_dir / "cvrp" / "mission.json",
        {
            "source_title": "Budgeted CVRP route improvement on CVRPLIB X",
            "bounded_hypothesis": "A concrete change can improve the development benchmark.",
            "success_criterion": "Beat the frozen incumbent with zero confirmation failures.",
            "beneficiary": "Fleet routing planners.",
        },
    )
    _write(
        night_dir / "cvrp" / "retro.json",
        {
            "status": "completed",
            "provider": "astra",
            "model": "gpt-6-astra",
            "analysis": "### Evidence assessment\n\n**What completed.** Two iterations.\n\n"
            "**Does the evidence support a real effect?** Weakly. One promising candidate on two seeds.\n\n"
            "### Lessons\n- stop re-trying swap moves",
            "limitations": [],
        },
    )
    older = tmp_path / "runs" / "research" / "2026-09-09-scheduled"
    _write(
        older / "night.json",
        _night("2026-09-09-scheduled", "partial", [_slot("cvrp", "astra", "failed")], "2026-09-10T02:00:00Z"),
    )
    _write(
        older / "cvrp" / "evidence.json", _evidence("cvrp", confirmed=False, publishable=False, reason="no candidate")
    )
    # A directory without night.json is ignored; a broken night.json is skipped.
    _write(tmp_path / "runs" / "research" / "development-history" / "cvrp.json", {})
    _write(tmp_path / "runs" / "research" / "broken" / "night.json", "{not json")
    # Stored incumbents: a public-record beat on cvrp, a baseline beat on miplib_heur, a submitted circle win.
    _write(tmp_path / "best-cvrp" / "scores.json", {"X-n101-k25": {"value": 27000, "iter": 3, "record": 27591.0}})
    _write(tmp_path / "best-cvrp" / "solver.py", "print('cvrp')\n")
    _write(tmp_path / "best-miplib_heur" / "scores.json", {"glass4": {"value": 0.4, "iter": 1, "record": 0.5}})
    _write(tmp_path / "best-miplib_heur" / "solver.py", "print('heur')\n")
    _write(tmp_path / "best" / "scores.json", {"101": {"value": 5.29, "iter": 15, "record": 5.16}})
    _write(tmp_path / "best" / "submitted.json", {"101": {"value": 5.29, "sent_at": "2026-09-03T11:56:49"}})
    _write(tmp_path / "best" / "solver.py", "print('circle')\n")
    _write(
        tmp_path / "runs" / "log.jsonl",
        "\n".join(
            json.dumps(row)
            for row in [
                {"iter": 0, "total": 59.3, "status": "seed", "idea": "seed", "wins": [101]},
                {"iter": 1, "total": 59.5, "status": "champion", "idea": "basin hopping", "wins": [101, 102]},
                {"iter": 2, "total": 59.1, "status": "rejected", "idea": "worse", "wins": []},
            ]
        ),
    )
    return tmp_path


def test_last_night_reads_ideas_outcomes_and_verdict(research_root):
    brief = morning_brief.build_brief(research_root)

    night = brief["last_night"]
    assert night["run_id"] == "2026-09-10-scheduled" and night["date"] == "2026-09-10"
    assert [item["run_id"] for item in brief["nights"]] == ["2026-09-10-scheduled", "2026-09-09-scheduled"]
    assert night["totals"] == {
        "slots": 2,
        "completed": 2,
        "candidates": 3,
        "promising": 1,
        "confirmed": 1,
        "publishable": 1,
        "best_gain": 0.0021,
    }
    cvrp = night["slots"][0]
    assert cvrp["mission"]["title"] == "Budgeted CVRP route improvement on CVRPLIB X"
    assert cvrp["best"]["idea"] == "gated SWAP* with split" and cvrp["best"]["status"] == "promising"
    assert (
        cvrp["candidates"][0]["idea"].endswith("…") and len(cvrp["candidates"][0]["idea"]) <= morning_brief.IDEA_CHARS
    )
    assert cvrp["candidates"][2]["idea"] == "astra CLI reported an error"
    # A median alone is not what the gate accepts, so the review page carries the bound and the replication.
    promoted = cvrp["candidates"][1]
    assert promoted["median_lower_bound"] == 0.0008 and promoted["seeds"] == 3
    assert cvrp["candidates"][0]["median_lower_bound"] is None and cvrp["candidates"][0]["seeds"] is None
    assert cvrp["confirmation"] == {
        "pairs": 3,
        "wins": 2,
        "losses": 1,
        "candidate_failures": 0,
        "mean_gain": pytest.approx(0.0008333, rel=1e-3),
        "median_gain": 0.0015,
    }
    assert cvrp["release_checks"] == {"checked": 1, "passed": 1, "first_error": None}
    assert cvrp["retro"]["verdict"] == "Weakly. One promising candidate on two seeds."
    assert cvrp["by_model"] == {"claude-opus-5": 3, "gpt-6-astra": 1}
    assert (
        cvrp["evidence_hash"]
        == hashlib.sha256(
            (research_root / "runs/research/2026-09-10-scheduled/cvrp/evidence.json").read_bytes()
        ).hexdigest()
    )
    validation = night["slots"][1]
    assert validation["kind"] == "validation" and validation["candidates"] == [] and validation["retro"] is None


def test_awaiting_publication_tracks_approval_release_and_record_beats(research_root):
    brief = morning_brief.build_brief(research_root)
    kinds = {(item["kind"], item["problem"], item.get("target")) for item in brief["awaiting_publication"]}
    assert kinds == {
        ("publishable_unapproved", "cvrp", None),
        ("record_beat_unsubmitted", "cvrp", "X-n101-k25"),
    }
    # Baseline problems never queue; the submitted circle-packing win is already logged.
    incumbents = {row["problem"]: row for row in brief["incumbents"]}
    assert incumbents["miplib_heur"]["record_kind"] == "baseline"
    assert incumbents["miplib_heur"]["unsubmitted_beats"] == 1
    assert incumbents["circle_packing"]["beating_record"] == 1
    assert incumbents["circle_packing"]["unsubmitted_beats"] == 0
    assert incumbents["cvrp"]["incumbent"]["classification"] == "historical_best_unvalidated"

    atomic_json(
        research_root / "runs" / "research" / "approvals" / f"{CANDIDATE_HASH}.json",
        {"candidate_hash": CANDIDATE_HASH, "confirmed": True},
    )
    approved = morning_brief.build_brief(research_root)["awaiting_publication"]
    assert [item["kind"] for item in approved if item["problem"] == "cvrp" and not item.get("target")] == [
        "approved_not_released"
    ]

    (research_root / "releases" / "cvrp" / f"{CANDIDATE_HASH[:12]}-deadbeef0000").mkdir(parents=True)
    released = morning_brief.build_brief(research_root)["awaiting_publication"]
    assert all(item.get("target") for item in released)


def test_legacy_loops_report_wins_and_last_champion(research_root):
    legacy = morning_brief.build_brief(research_root)["legacy"]
    assert legacy == [
        {
            "problem": "circle_packing",
            "iterations": 3,
            "champions": 1,
            "wins": ["101", "102"],
            "best_total": 59.5,
            "last_champion_idea": "basin hopping",
            "classification": "historical_unvalidated",
        }
    ]


def test_empty_root_builds_an_empty_brief(tmp_path):
    assert morning_brief.build_brief(tmp_path) == {
        "last_night": None,
        "nights": [],
        "incumbents": [],
        "awaiting_publication": [],
        "legacy": [],
    }


def test_dashboard_serves_the_brief_and_the_page(research_root):
    server = dashboard.create_server(root=research_root, port=0, csrf_token="test-token")
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/morning", timeout=5) as response:
            payload = json.loads(response.read())
        assert payload["last_night"]["run_id"] == "2026-09-10-scheduled"
        assert payload["awaiting_publication"][0]["kind"] == "publishable_unapproved"
        assert "generated_at" in payload
        for path in ("/morning", "/morning.js"):
            with urllib.request.urlopen(base + path, timeout=5) as response:
                assert response.status == 200
                body = response.read().decode("utf-8")
        assert "renderIncumbents" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
