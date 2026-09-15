import json
import os
import types
from pathlib import Path

import pytest

import loop
import night
import research_context
from scripts import schedule_night


def _write(root, relative, payload):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_dead_ends_scoped_sanitized_and_bounded(tmp_path):
    _write(
        tmp_path,
        "problems/_dead_ends.json",
        [
            {
                "id": "de-100",
                "date": "2026-09-10",
                "problem": "cvrp",
                "approach": "oracle tuning on holdout-instance X-n999",
                "why_failed": "leaks the confirmation split at /private/run.json",
                "tags": ["oracle"],
            },
            {
                "id": "de-101",
                "date": "2026-09-10",
                "problem": "miplib_heur",
                "approach": "unrelated",
                "why_failed": "off scope",
            },
            {
                "id": "de-102",
                "date": "2026-09-10",
                "problem": "general",
                "approach": "blanket retry of the same code",
                "why_failed": "exact duplicate",
            },
        ],
    )
    text, ids = research_context.dead_ends_for("cvrp", str(tmp_path), hidden_targets=("X-n999",))
    assert ids == ["de-100", "de-102"]
    assert "de-101" not in text
    assert "X-n999" not in text
    assert "/private" not in text
    assert "blanket retry" in text


def test_patterns_normalize_both_schemas_and_rank(tmp_path):
    _write(
        tmp_path,
        "problems/matrix_multiplication/patterns/block.json",
        {
            "name": "block-decomposition",
            "description": "split into blocks, solve each",
            "applies_when": ["block-structure"],
            "transform_ref": "problems/matrix_multiplication/composition.py:block_embed",
            "successes": 2,
            "failures": 0,
        },
    )
    _write(
        tmp_path,
        "nightly/patterns/glue.json",
        {
            "name": "glue-analysis",
            "abstract_description": "remove cancellation-only components first",
            "origin_problem": "matrix_multiplication",
            "applicability": "composite constructions",
            "operators": ["remove_glue_first"],
            "success_count": 0,
            "failure_count": 1,
        },
    )
    _write(
        tmp_path,
        "nightly/patterns/block_dup.json",
        {
            "name": "block-decomposition",
            "abstract_description": "nightly wording without exact tags",
            "applicability": "block moves",
            "success_count": 1,
            "failure_count": 0,
        },
    )
    _write(tmp_path, "problems/x/patterns/_bandit.json", {"state": True})
    merged = [p for p in research_context.load_patterns(str(tmp_path)) if p["name"] == "block-decomposition"]
    assert len(merged) == 1
    assert "block-structure" in merged[0]["tags"]
    assert merged[0]["outcomes"] == 3
    plugin = types.SimpleNamespace(PATTERN_TAGS=["block-structure"])
    text, names = research_context.patterns_for("cvrp", plugin, str(tmp_path))
    assert names[0] == "block-decomposition"
    assert "glue-analysis" in names
    assert "state" not in names
    assert "outcome" not in text
    assert "transform_ref" not in text and "composition.py" not in text
    assert "remove cancellation-only" in text


def test_blocks_empty_when_nothing_recorded(tmp_path):
    result = research_context.blocks("cvrp", types.SimpleNamespace(), str(tmp_path))
    assert result == {"text": "", "dead_ends": [], "patterns": []}


class _FakeProblem:
    TARGETS = ["dev", "validation"]
    DEVELOPMENT_TARGETS = ["dev"]  # noqa: vulture (read by loop.py via the plugin)
    VALIDATION_TARGETS = ["validation"]  # noqa: vulture
    HOLDOUT = ["holdout"]  # noqa: vulture
    DEFAULTS = {"time": 1, "workers": 2}
    FAIL_SCORE = -100.0
    PATTERN_TAGS = ["block-structure"]
    PROMPT = "legacy prompt"
    TASK = "write the solver"

    @staticmethod
    def prompt_for_targets(targets):
        return "development targets: " + ",".join(targets)

    @staticmethod
    def records_load():
        return {"dev": 0.0, "validation": 0.0, "holdout": 0.0}

    @staticmethod
    def evaluate(path, _target):
        return json.loads(open(path, encoding="utf-8").read())["value"], {}

    @staticmethod
    def score(value, _record):
        return value


def _fixture_root(tmp_path):
    champion = tmp_path / "best-fake" / "solver.py"
    champion.parent.mkdir(parents=True)
    champion.write_text("# incumbent\n", encoding="utf-8")
    return champion


def _runner(_problem, solver, target, _budget, seed, out, **_kwargs):
    source = open(solver, encoding="utf-8").read()
    value = 2.0 if "fable candidate" in source else 1.0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as stream:
        json.dump({"value": value}, stream)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def test_prompt_carries_dead_ends_and_patterns(tmp_path):
    _write(
        tmp_path,
        "problems/_dead_ends.json",
        [{"id": "de-1", "problem": "fake", "approach": "retry naive encoding", "why_failed": "timeout"}],
    )
    _write(
        tmp_path,
        "problems/fake/patterns/block.json",
        {
            "name": "block-decomposition",
            "description": "split into blocks",
            "applies_when": ["block-structure"],
            "transform_ref": "x:y",
            "successes": 1,
        },
    )
    instance = loop.Loop("fake", root=tmp_path, problem_module=_FakeProblem, initialize_best=False)
    prompt = instance.build_research_prompt(
        "# incumbent\n", ["dev"], {"dev": 0.0}, [], hidden_targets=("holdout",)
    )
    assert "KNOWN DEAD ENDS" in prompt
    assert "retry naive encoding" in prompt
    assert "TRANSFERABLE PATTERNS" in prompt
    assert "block-decomposition" in prompt
    assert "holdout" not in prompt


def test_run_research_records_prompt_context(tmp_path):
    _fixture_root(tmp_path)
    _write(
        tmp_path,
        "problems/_dead_ends.json",
        [{"id": "de-7", "problem": "fake", "approach": "blind restart", "why_failed": "stall"}],
    )
    calls = []

    def model(prompt, **_kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return {"code": "# fable candidate\nVALUE = 2\n", "idea": "[kind: test] improved"}
        return {"error": "stop", "error_kind": "usage_limit"}

    evidence = loop.run_research(
        "fake",
        root=tmp_path,
        provider="fable",
        iters=2,
        problem_module=_FakeProblem,
        call_model_fn=model,
        solver_runner=_runner,
    )
    assert evidence["prompt_context"]["dead_ends"] == ["de-7"]
    assert "KNOWN DEAD ENDS" in evidence["prompt_context"]["text"]
    assert "KNOWN DEAD ENDS" in calls[0]
    assert "blind restart" in calls[0]


def test_prompt_context_restored_from_evidence_on_resume(tmp_path):
    recorded = {
        "text": "KNOWN DEAD ENDS (verified failures in this lab):\n- [de-1] old context",
        "dead_ends": ["de-1"],
        "patterns": ["p-1"],
    }
    _write(
        tmp_path,
        "problems/_dead_ends.json",
        [{"id": "de-9", "problem": "fake", "approach": "newer entry", "why_failed": "x"}],
    )
    plugin = types.SimpleNamespace(PATTERN_TAGS=[])
    restored = loop._prompt_context({"prompt_context": recorded}, "fake", plugin, str(tmp_path), ())
    assert restored == recorded
    fresh = loop._prompt_context({}, "fake", plugin, str(tmp_path), ())
    assert fresh["dead_ends"] == ["de-9"]


def test_planned_slots_orders_extra_research_before_validation():
    config = night.load_schedule(Path(night.HERE) / "night.json")
    config["slots"].insert(
        2,
        {
            "id": "matmul-research",
            "problem": "matrix_multiplication",
            "kind": "research",
            "provider": "paired",
            "minutes": 30,
            "research_minutes": 20,
            "retro_minutes": 10,
            "slot_budget_usd": 10.0,
            "per_call_budget_usd": 2.0,
            "retro_budget_usd": 2.0,
            "iters": 10,
            "seed_count": 1,
            "min_effect": 0.0001,
            "time_per_target": 60,
            "workers": 1,
        },
    )
    slots = night.planned_slots(config, "2026-09-06")
    assert [slot["problem"] for slot in slots][-2:] == ["matrix_multiplication", "pglib_opf"]
    matmul = slots[2]
    assert matmul["provider"] == "paired"
    assert "trial_index" not in matmul
    assert matmul["effective_slot_budget_usd"] == 10.0


def test_load_schedule_rejects_unknown_configured_provider(tmp_path):
    config = json.loads((Path(night.HERE) / "night.json").read_text(encoding="utf-8"))
    config["slots"][0]["provider"] = "bogus"
    path = tmp_path / "night.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="configured slot providers"):
        night.load_schedule(path)


def test_schedule_history_reads_governed_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_night, "_RUNS_DIR", str(tmp_path))
    _write(
        tmp_path,
        "research/2026-09-10/cvrp/run.json",
        {"problem": "cvrp", "status": "completed", "finished_at": "2026-09-10T05:00:00Z"},
    )
    _write(
        tmp_path,
        "research/2026-09-11/cvrp/run.json",
        {"problem": "cvrp", "status": "error", "updated_at": "2026-09-11T05:00:00Z"},
    )
    history = schedule_night._history("cvrp")
    assert len(history) == 2
    assert history[0]["generated_at"] == "2026-09-11T05:00:00Z"
    assert history[1]["status"] == "success"
    score = schedule_night.score_problem("cvrp")
    assert score["runs_recorded"] == 2
    assert 0 <= score["components"]["velocity"] <= 3.0


def test_dry_run_reports_schedule_plan(tmp_path):
    config = night.load_schedule(Path(night.HERE) / "night.json")
    config["arc"]["enabled"] = False
    config["night"]["evidence_root"] = str(tmp_path)
    plan = night.run_night(config, "2026-09-12", dry_run=True)
    assert plan["dry_run"] is True
    assert plan["schedule_plan"]["budget_s"] == 480 * 60.0
    assert set(plan["schedule_plan"]["allocations"]) >= {"cvrp", "miplib_heur", "pglib_opf"}
