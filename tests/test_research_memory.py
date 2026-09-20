import research_memory


def test_analyze_candidate_ignores_formatting_and_comments_but_keeps_semantics():
    first = research_memory.analyze_candidate("x = 1  # ordinary comment\n")
    formatted = research_memory.analyze_candidate("x=1\n", [first["fingerprint"]])
    changed = research_memory.analyze_candidate("x = 2\n", [first["fingerprint"]])
    docstring = research_memory.analyze_candidate('"new docstring"\nx = 1\n', [first["fingerprint"]])
    assert first["valid"] and formatted["duplicate"]
    assert not changed["duplicate"] and not docstring["duplicate"]


def test_analyze_candidate_reports_invalid_python_without_fingerprint():
    result = research_memory.analyze_candidate("def broken(:\n")
    assert result == {
        "valid": False,
        "syntax_error": "invalid syntax (line 1)",
        "fingerprint": None,
        "duplicate": False,
    }


def test_summary_excludes_confirmation_paths_and_redacts_hidden_targets():
    summary = research_memory.summarize_development(
        [
            {
                "problem": "demo",
                "provider": "fable",
                "model": "actual",
                "idea": "[kind: swap] use hidden-1 at C:\\private\\path",
                "status": "rejected",
                "median_gain": -0.1,
                "candidate_hash": "secret",
                "candidate_path": "private/path",
                "confirmation": {"passes": True},
                "promoted": True,
                "critique": {"text": "hidden-1 failed in /tmp/private"},
            }
        ],
        hidden_targets=("hidden-1",),
    )
    entry = summary["entries"][0]
    assert entry["family"] == "swap" and entry["negative_result"] == "rejected"
    assert "hidden-1" not in repr(summary)
    assert "candidate_hash" not in repr(summary) and "private/path" not in repr(summary)
    assert "confirmation" not in repr(summary) and "promoted" not in repr(summary)
    assert "C:\\private" not in repr(summary) and "/tmp/private" not in repr(summary)


def test_summary_retains_old_recurring_negative_family_with_recent_limit():
    history = [{"family": "old failure", "status": "rejected"} for _ in range(3)]
    history += [{"family": "recent", "status": "promising"} for _ in range(4)]
    summary = research_memory.summarize_development(history, limit=2)
    assert len(summary["entries"]) == 2
    old = next(item for item in summary["families"] if item["family"] == "old failure")
    assert old["negative_results"] == {"rejected": 3} and old["negative_total"] == 3


def test_summary_default_is_compact_for_long_history():
    summary = research_memory.summarize_development(
        [{"iteration": number, "idea": "x" * 1000, "critique": {"text": "y" * 1000}} for number in range(80)]
    )
    assert len(summary["entries"]) == 20
    assert summary["entries"][0]["iteration"] == 60
    assert all(len(entry["idea"]) == 500 and len(entry["critique"]["text"]) == 400 for entry in summary["entries"])


def test_summary_rejects_unknown_statuses_and_invalid_scalar_values():
    entry = research_memory.summarize_development(
        [
            {
                "status": {"confirmation": "completed"},
                "valid": "yes",
                "novel": 1,
                "median_gain": float("nan"),
                "iteration": -1,
                "fingerprint": "not-a-hash",
                "cost": float("inf"),
            }
        ]
    )["entries"][0]
    assert entry["development_status"] == "" and not entry["valid"] and not entry["novel"]
    assert entry["median_gain"] is None and entry["iteration"] is None
    assert entry["fingerprint"] is None and entry["cost_usd"] is None


def test_summary_preserves_only_valid_fingerprints():
    valid = "a" * 64
    entries = research_memory.summarize_development([{"fingerprint": valid}, {"fingerprint": valid + "x"}])["entries"]
    assert entries[0]["fingerprint"] == valid and entries[1]["fingerprint"] is None


def test_summary_prefers_idea_family_or_tag_over_provider_family():
    entries = research_memory.summarize_development(
        [
            {"family": "anthropic", "idea": "[kind: swap] replace mutation"},
            {"family": "legacy constructive", "idea": "no tag"},
            {"family": "openai", "idea": "no tag"},
            {"family": "legacy", "idea_family": "Exact neighborhood", "idea": "[kind: ignored]"},
        ]
    )["entries"]
    assert [entry["family"] for entry in entries] == [
        "swap",
        "legacy constructive",
        "unclassified",
        "exact neighborhood",
    ]


def test_summary_bounds_distinct_negative_reasons():
    history = [{"family": "same", "negative_result": f"reason {number}", "status": "rejected"} for number in range(8)]
    family = research_memory.summarize_development(history)["families"][0]
    assert len(family["negative_results"]) == 5 and family["negative_total"] == 8


def test_summary_redacts_explicit_family_paths():
    family = research_memory.summarize_development(
        [{"family": "C:\\agents\\private", "negative_result": "/tmp/private failed", "status": "rejected"}]
    )["families"][0]
    assert "C:\\agents" not in repr(family) and "/tmp/private" not in repr(family)


def test_operational_stats_separate_problem_model_and_role():
    rows = [
        {
            "problem": "a",
            "actual_model": "m1",
            "role": "generation",
            "valid": True,
            "novel": True,
            "promising": True,
            "cost_usd": 2,
            "elapsed_seconds": 3,
        },
        {
            "problem": "a",
            "actual_model": "m1",
            "role": "generation",
            "valid": False,
            "novel": False,
            "promising": False,
        },
        {"problem": "a", "actual_model": "m2", "role": "generation", "valid": True},
        {"problem": "b", "actual_model": "m1", "role": "retro", "valid": True},
    ]
    stats = research_memory.operational_stats(rows)
    generation = next(item for item in stats if item["problem"] == "a" and item["actual_model"] == "m1")
    assert generation["attempts"] == 2 and generation["valid_rate"] == 0.5
    assert generation["cost_usd"] == 2.0 and len(stats) == 3


def test_allocation_requires_samples_and_preserves_exploration():
    stats = [
        {
            "problem": "a",
            "actual_model": "mature",
            "role": "generation",
            "attempts": 3,
            "valid_rate": 1.0,
            "novel_rate": 1.0,
            "promising_rate": 0.5,
            "elapsed_seconds": 9.0,
        }
    ]
    choices = [
        {"problem": "a", "actual_model": "mature", "role": "generation", "family": "stable"},
        {"problem": "a", "actual_model": "new", "role": "generation", "family": "explore"},
    ]
    allocation = research_memory.rank_auto_allocation(stats, choices, min_samples=3, exploration_slots=1)
    assert allocation["primary"]["family"] == "stable"
    assert allocation["exploration"][0]["family"] == "explore"


def test_allocation_orders_exploration_by_fewest_attempts_then_choice_order():
    stats = [
        {
            "problem": "a",
            "actual_model": "mature",
            "role": "generation",
            "attempts": 3,
            "valid_rate": 1,
            "novel_rate": 1,
            "promising_rate": 1,
            "elapsed_seconds": 3,
        },
        {
            "problem": "a",
            "actual_model": "some",
            "role": "generation",
            "attempts": 2,
            "valid_rate": 1,
            "novel_rate": 1,
            "promising_rate": 0,
            "elapsed_seconds": 2,
        },
    ]
    choices = [
        {"problem": "a", "actual_model": "mature", "role": "generation"},
        {"problem": "a", "actual_model": "some", "role": "generation", "family": "seen"},
        {"problem": "a", "actual_model": "new", "role": "generation", "family": "new"},
    ]
    exploration = research_memory.rank_auto_allocation(stats, choices, exploration_slots=2)["exploration"]
    assert [item["family"] for item in exploration] == ["new", "seen"]


def _paired(target, seed, gain, failed=False):
    return {"target": target, "seed": seed, "gain": gain, "candidate_failed": failed}


def test_cell_outcomes_report_per_target_medians_and_counts():
    record = {
        "status": "rejected",
        "idea": "[kind: swap*] granular swap",
        "comparison": {
            "pairs": [
                _paired("alpha", 1, 0.01),
                _paired("alpha", 2, 0.004),
                _paired("beta", 1, -0.006),
                _paired("gamma", 1, 0.0, failed=True),
            ]
        },
    }
    cells = research_memory.summarize_development([record])["entries"][0]["cells"]
    assert (cells["won"], cells["lost"], cells["failed"]) == (2, 1, 1)
    assert cells["targets"] == {"alpha": 0.7, "beta": -0.6, "gamma": 0.0}
    assert research_memory.cells_text(cells) == "alpha +0.700% | beta -0.600% | gamma +0.000%"


def test_cell_outcomes_drop_withheld_targets():
    record = {
        "status": "rejected",
        "idea": "[kind: swap*] granular swap",
        "comparison": {"pairs": [_paired("alpha", 1, 0.01), _paired("secret", 1, -0.02)]},
    }
    cells = research_memory.summarize_development([record], hidden_targets=("secret",))["entries"][0]["cells"]
    assert set(cells["targets"]) == {"alpha"}


def test_cell_outcomes_absent_without_paired_rows():
    assert (
        research_memory.summarize_development([{"status": "syntax_error", "idea": "x"}])["entries"][0]["cells"] is None
    )


def test_family_rollup_keeps_per_target_gains():
    records = [
        {
            "status": "rejected",
            "idea": "[kind: swap*] granular swap",
            "comparison": {"pairs": [_paired("alpha", 1, gain), _paired("beta", 1, -0.01)]},
        }
        for gain in (0.004, 0.006)
    ]
    family = research_memory.summarize_development(records)["families"][0]
    assert family["family"] == "swap*" and family["target_gains"] == {"alpha": 0.5, "beta": -1.0}


def test_projected_cells_survive_being_summarized_again():
    record = {
        "status": "rejected",
        "idea": "[kind: swap*] granular swap",
        "comparison": {"pairs": [_paired("alpha", 1, 0.01), _paired("beta", 1, -0.006)]},
    }
    stored = research_memory.summarize_development([record])["entries"][0]
    # History is written projected: re-reading it must not empty the per-target outcomes.
    again = research_memory.summarize_development([stored])
    assert again["entries"][0]["cells"]["targets"] == {"alpha": 1.0, "beta": -0.6}
    assert again["entries"][0]["cells"]["won"] == 1
    assert again["families"][0]["target_gains"] == {"alpha": 1.0, "beta": -0.6}


def test_a_withheld_target_is_dropped_when_projected_cells_are_re_read():
    stored = {
        "status": "rejected",
        "idea": "x",
        "cells": {"won": 1, "lost": 1, "targets": {"alpha": 1.0, "secret": -2.0}},
    }
    cells = research_memory.summarize_development([stored], hidden_targets=("secret",))["entries"][0]["cells"]
    assert set(cells["targets"]) == {"alpha"}
