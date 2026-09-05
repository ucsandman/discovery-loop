import json
import sys
import types

import retro
from research_state import BudgetLedger


def test_cross_model_analyst_never_reuses_single_generation_provider():
    assert retro.cross_model_provider("fable", "2026-09-05") == "astra"
    assert retro.cross_model_provider("astra", "2026-09-05") == "fable"
    assert retro.cross_model_provider("paired", "2026-09-05") in {"fable", "astra"}


def test_research_retro_prompt_excludes_code_and_local_paths():
    prompt = retro.build_research_retro_prompt(
        {
            "run_id": "2026-09-05",
            "problem": "cvrp",
            "provider": "fable",
            "candidate_path": r"C:\private\solver.py",
            "code": "SECRET MODEL TEXT",
            "confirmation": {"secret_target": 123},
        }
    )
    assert r"C:\private" not in prompt
    assert "SECRET MODEL TEXT" not in prompt
    assert "secret_target" not in prompt
    assert "development evidence only" in prompt


def test_model_error_still_writes_usable_local_retro(tmp_path, monkeypatch):
    evidence_root = tmp_path / "research"
    problem_root = evidence_root / "2026-09-05" / "cvrp"
    problem_root.mkdir(parents=True)
    (problem_root / "evidence.json").write_text(
        json.dumps({"status": "completed", "problem": "cvrp", "provider": "fable"}), encoding="utf-8"
    )
    ledger_path = evidence_root / "2026-09-05" / "budget.json"
    BudgetLedger(ledger_path, 45.0)
    fake = types.SimpleNamespace(
        call_model=lambda *args, **kwargs: {
            "text": "",
            "provider": "astra",
            "model": "gpt-6-astra",
            "cost": None,
            "usage": {},
            "error": "provider unavailable: private detail",
        }
    )
    monkeypatch.setitem(sys.modules, "providers", fake)
    result = retro.run_research_retro("cvrp", "2026-09-05", evidence_root, ledger_path, 2.5, provider="astra")
    saved = json.loads((problem_root / "retro.json").read_text(encoding="utf-8"))
    assert result["status"] == saved["status"] == "failed"
    assert saved["limitations"] == ["analyst model call failed"]
    assert "private detail" not in json.dumps(saved)
    history = (evidence_root / "development-history" / "cvrp.jsonl").read_text(encoding="utf-8")
    assert "private detail" not in history and '"status": "retrospective"' in history


def test_successful_cross_model_retro_is_local_and_structured(tmp_path, monkeypatch):
    evidence_root = tmp_path / "research"
    problem_root = evidence_root / "2026-09-05" / "miplib_heur"
    problem_root.mkdir(parents=True)
    (problem_root / "evidence.json").write_text(
        json.dumps({"status": "partial", "problem": "miplib_heur", "provider": "astra"}), encoding="utf-8"
    )
    ledger_path = evidence_root / "2026-09-05" / "budget.json"
    BudgetLedger(ledger_path, 45.0)
    monkeypatch.setitem(
        sys.modules,
        "providers",
        types.SimpleNamespace(
            call_model=lambda *args, **kwargs: {
                "text": "### Evidence assessment\nMeasured.\n### Failure analysis\nNone.\n### Next experiment\nRun.\n### Limitations\nOne run.",
                "provider": "fable",
                "model": "claude-fable-5-1",
                "cost": 0.5,
                "usage": {"input_tokens": 10},
                "error": None,
            }
        ),
    )
    result = retro.run_research_retro("miplib_heur", "2026-09-05", evidence_root, ledger_path, 2.5, provider="fable")
    assert result["status"] == "completed"
    assert result["provider"] == "fable"
    assert result["reported_total_cost_usd_api_equivalent"] == 0.5
    assert (problem_root / "retro.json").is_file()
    line = json.loads((evidence_root / "development-history" / "miplib_heur.jsonl").read_text(encoding="utf-8"))
    assert len(line["critique"]["text"]) <= 2000
    assert "confirmation" not in line and line["idea"] == ""
