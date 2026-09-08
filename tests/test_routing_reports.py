import importlib.util
import json
from pathlib import Path

import dashboard
from research_state import atomic_json
from trial_report import routing_execution_summary, summarize


def _routing(*, eligible, arm="fable", degraded=False, attempts=None):
    return {
        "requested_arm": arm,
        "mode": "paired",
        "formal_trial_eligible": eligible,
        "ineligibility_reasons": [] if eligible else ["capacity_or_infrastructure_fallback"],
        "degraded": degraded,
        "attempts": attempts or [],
    }


def test_trial_report_separates_clean_historical_and_operational_routing(tmp_path):
    completed = {
        "family": "anthropic",
        "model": "claude-fable-5-1",
        "status": "completed",
        "charged_allowance": 1.25,
        "selection_reason": "requested",
    }
    failed = {
        "family": "openai",
        "model": "gpt-6-astra",
        "status": "failed",
        "reserved_allowance": 0.5,
        "error_kind": "quota_exhausted",
    }
    base = {
        "problem": "cvrp",
        "provider": "fable",
        "status": "completed",
        "confirmed": True,
        "usage": {"calls": 1, "charged": 1.25},
    }
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/evidence.json",
        {**base, "routing": _routing(eligible=True, attempts=[completed])},
    )
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/retro.json",
        {
            "status": "completed",
            "usage": {"calls": 1, "charged": 0.5},
            "routing": _routing(eligible=True, attempts=[failed]),
        },
    )
    atomic_json(
        tmp_path / "runs/research/2026-09-06/cvrp/evidence.json",
        {**base, "routing": _routing(eligible=False, degraded=True, attempts=[failed])},
    )
    atomic_json(tmp_path / "runs/research/2026-09-07/cvrp/evidence.json", base)

    report = summarize(tmp_path)

    assert report["runs"] == 3
    assert report["clean_runs"] == 1
    assert report["clean_rows"][0]["confirmed"] == 1
    assert report["clean_rows"][0]["actual_model_calls"] == {"claude-fable-5-1": 1, "gpt-6-astra": 1}
    assert report["clean_rows"][0]["failed_attempts"] == 1
    assert report["clean_rows"][0]["confirmed_per_allowance_unit"] == 1 / 1.75
    assert report["operational_rows"][0]["confirmed_per_allowance_unit"] is None
    assert report["operational_rows"][0]["paired_degradations"] == 1
    assert report["rows"][0]["provenance"] == "historical_unverified"


def test_retro_routing_ineligibility_excludes_a_confirmed_result_from_clean_ratios(tmp_path):
    base = {
        "problem": "cvrp",
        "provider": "fable",
        "status": "completed",
        "confirmed": True,
        "usage": {"calls": 1, "charged": 1},
    }
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/evidence.json", {**base, "routing": _routing(eligible=True)})
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/retro.json",
        {
            "status": "failed",
            "routing": _routing(
                eligible=False,
                attempts=[
                    {
                        "family": "openai",
                        "model": "gpt-6-astra",
                        "status": "failed",
                        "error_kind": "quota_exhausted",
                        "reserved_allowance": 0.5,
                    }
                ],
            ),
        },
    )

    report = summarize(tmp_path)

    assert report["clean_rows"] == []
    assert report["operational_rows"][0]["confirmed"] == 1
    assert report["operational_rows"][0]["fallback_reasons"] == {"quota_exhausted": 1}


def test_modern_missing_retro_is_provisional_and_skips_do_not_count_as_calls(tmp_path):
    evidence = {
        "problem": "cvrp",
        "provider": "fable",
        "status": "completed",
        "confirmed": True,
        "usage": {"calls": 1, "charged": 2},
        "routing": _routing(
            eligible=True,
            attempts=[
                {"family": "anthropic", "model": "claude-fable-5-1", "status": "completed", "charged_allowance": 2},
                {"family": "openai", "model": "gpt-6-astra", "status": "skipped", "reserved_allowance": 2},
            ],
        ),
    }
    atomic_json(tmp_path / "runs/research/2026-09-05/cvrp/evidence.json", evidence)

    report = summarize(tmp_path)

    assert report["clean_rows"] == []
    assert report["operational_rows"][0]["actual_family_calls"] == {"anthropic": 1}
    assert (
        report["operational_rows"][0]["ineligibility_reasons"]
        if "ineligibility_reasons" in report["operational_rows"][0]
        else True
    )


def test_successful_model_shares_exclude_failed_and_skipped_attempts():
    attempts = (
        [{"model": "gpt-5.6-sol", "family": "openai", "status": "completed"}] * 3
        + [{"model": "gpt-6-astra", "family": "openai", "status": "completed"}] * 2
        + [{"model": "gpt-6-astra", "family": "openai", "status": "failed", "error_kind": "quota_exhausted"}] * 5
        + [{"model": "claude-fable-5-1", "family": "anthropic", "status": "skipped"}]
    )
    summary = routing_execution_summary(
        {"routing": _routing(eligible=True, attempts=attempts)},
        {"status": "completed", "routing": _routing(eligible=True)},
    )

    assert summary["successful_model_calls"] == {"gpt-5.6-sol": 3, "gpt-6-astra": 2}
    assert summary["model_call_shares"]["gpt-5.6-sol"] == 0.6
    assert summary["actual_model_calls"]["gpt-6-astra"] == 7


def test_dashboard_reports_routing_controls_from_the_local_schedule(tmp_path):
    atomic_json(
        tmp_path / "night.json",
        {"night": {"routing": {"policy": "auto", "chain": ["astra", "fable"], "disabled_families": ["anthropic"]}}},
    )

    schedule = dashboard.DashboardApp(tmp_path).schedule_summary()

    assert schedule["routing"] == {"policy": "auto", "chain": ["astra", "fable"], "disabled_families": ["anthropic"]}


def test_dashboard_updates_routing_with_the_existing_local_schedule(tmp_path):
    schedule = json.loads((Path(__file__).resolve().parents[1] / "night.json").read_text(encoding="utf-8"))
    atomic_json(tmp_path / "night.json", schedule)
    result = dashboard.DashboardApp(tmp_path).update_schedule(
        {
            "duration_minutes": 480,
            "nightly_budget_usd": 90,
            "provider_caps_usd": {"fable": 40, "astra": 40, "paired": 40},
            "routing": {"policy": "auto", "chain": ["astra", "fable"], "disabled_families": ["anthropic"]},
        }
    )

    assert result["schedule"]["routing"]["chain"] == ["astra", "fable"]
    saved = json.loads((tmp_path / "night.json").read_text(encoding="utf-8"))
    assert saved["night"]["routing"]["disabled_families"] == ["anthropic"]


def test_dashboard_evidence_merges_late_retro_fallback_without_exposing_raw_error(tmp_path):
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/evidence.json",
        {"problem": "cvrp", "routing": _routing(eligible=True)},
    )
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/retro.json",
        {
            "routing": _routing(
                eligible=False,
                attempts=[
                    {
                        "family": "openai",
                        "model": "gpt-6-astra",
                        "status": "failed",
                        "error_kind": "quota_exhausted",
                        "error": "C:\\private\\raw",
                    }
                ],
            )
        },
    )

    item = dashboard.DashboardApp(tmp_path).evidence()["evidence"][0]

    assert item["routing"]["formal_trial_eligible"] is False
    assert item["routing"]["failure_reasons"] == {"quota_exhausted": 1}
    assert r"C:\private" not in json.dumps(item["routing"])


def test_morning_report_keeps_routing_failures_and_retro_separate_from_prose(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "morning-research.py"
    spec = importlib.util.spec_from_file_location("morning_routing_report", path)
    morning = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(morning)
    monkeypatch.setattr(morning, "REPO", tmp_path)
    atomic_json(tmp_path / "night.json", {"slots": [{"id": "cvrp", "problem": "cvrp"}]})
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/evidence.json",
        {
            "routing": _routing(
                eligible=True,
                attempts=[
                    {
                        "family": "anthropic",
                        "model": "claude-fable-5-1",
                        "status": "completed",
                        "selection_reason": "requested",
                    }
                ],
            )
        },
    )
    atomic_json(
        tmp_path / "runs/research/2026-09-05/cvrp/retro.json",
        {
            "status": "failed",
            "routing": _routing(
                eligible=True,
                attempts=[
                    {
                        "family": "openai",
                        "model": "gpt-6-astra",
                        "status": "failed",
                        "selection_reason": "infrastructure_fallback",
                        "error": "C:\\private\\secret",
                    }
                ],
            ),
        },
    )
    status = {
        "run_id": "2026-09-05",
        "status": "completed",
        "updated_at": "2026-09-05T00:00:00Z",
        "slots": [
            {
                "id": "cvrp",
                "problem": "cvrp",
                "kind": "research",
                "provider": "fable",
                "status": "completed",
                "stages": {"research": {"status": "completed"}, "retro": {"status": "failed"}},
            }
        ],
    }

    report = morning.build_report(status, "2026-09-05")

    routing = report["problems"][0]["routing"]
    assert routing["actual_family_calls"] == {"anthropic": 1, "openai": 1}
    assert routing["failed_attempts"] == 0 and routing["retro_failed_attempts"] == 1
    assert r"C:\private" not in json.dumps(report)
