import io
import json
from pathlib import Path

from scripts import research_ledger


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _evidence(run_id, problem, *, status="completed", candidates=1, gain=0.1, provider="fable", charged=1.5):
    return {
        "run_id": run_id,
        "problem": problem,
        "provider": provider,
        "status": status,
        "confirmed": False,
        "publishable": False,
        "usage": {"iterations": candidates, "charged": charged},
        "development": {"candidates": [{"iteration": i + 1, "median_gain": gain} for i in range(candidates)]},
        "finished_at": f"{run_id}T06:00:00Z",
    }


def _tree(tmp_path):
    research = tmp_path / "runs" / "research"
    _write_json(research / "2026-09-01" / "cvrp" / "evidence.json", _evidence("2026-09-01", "cvrp"))
    _write_json(research / "2026-09-01" / "cvrp" / "retro.json", {"status": "completed", "analysis": "ok"})
    _write_json(
        research / "development-history" / "cvrp-retro.json",
        {"source_run_id": "2026-09-01", "next_experiment": "try a granular neighbourhood"},
    )
    _write_json(research / "2026-09-02" / "cvrp" / "evidence.json", _evidence("2026-09-02", "cvrp", gain=0.2))
    _write_json(
        research / "2026-09-02" / "ecc_prize" / "evidence.json", _evidence("2026-09-02", "ecc_prize", provider="astra")
    )
    _write_json(research / "2026-09-02" / "ecc_prize" / "retro.json", {"status": "failed"})
    _write_json(research / "2026-09-03" / "cvrp" / "evidence.json", _evidence("2026-09-03", "cvrp", status="running"))
    _write_json(
        research / "2026-09-03" / "pglib_opf" / "evidence.json", _evidence("2026-09-03", "pglib_opf", candidates=0)
    )
    return tmp_path


def test_run_rows_read_every_run_and_carry_the_distilled_next_experiment(tmp_path):
    rows = research_ledger.run_rows(_tree(tmp_path))
    by_key = {(row["run_id"], row["problem"]): row for row in rows}
    assert len(rows) == 5
    first = by_key[("2026-09-01", "cvrp")]
    assert first["retro"] == "completed"
    assert first["next_experiment"] == "try a granular neighbourhood"
    assert first["best_gain"] == 0.1 and first["charged_usd"] == 1.5
    assert by_key[("2026-09-02", "cvrp")]["retro"] == "missing"
    assert by_key[("2026-09-02", "cvrp")]["next_experiment"] == ""  # the memory file belongs to another run
    assert by_key[("2026-09-02", "ecc_prize")]["retro"] == "failed"
    assert by_key[("2026-09-03", "pglib_opf")]["candidates"] == 0


def test_missing_retros_skips_running_runs_and_validation_runs_with_no_candidates(tmp_path):
    missing = research_ledger.missing_retros(_tree(tmp_path))
    assert [(row["run_id"], row["problem"]) for row in missing] == [
        ("2026-09-02", "cvrp"),
        ("2026-09-02", "ecc_prize"),
    ]
    assert research_ledger.missing_retros(tmp_path, problem="ecc_prize")[0]["problem"] == "ecc_prize"


def test_retro_command_uses_the_cross_model_analyst_and_real_retro_flags(tmp_path):
    rows = {row["problem"]: row for row in research_ledger.missing_retros(_tree(tmp_path))}
    fable_run = research_ledger.retro_command(rows["cvrp"], call_budget=1.25)
    astra_run = research_ledger.retro_command(rows["ecc_prize"])
    assert fable_run[fable_run.index("--provider") + 1] == "astra"
    assert astra_run[astra_run.index("--provider") + 1] == "fable"
    assert fable_run[fable_run.index("--call-budget") + 1] == "1.25"
    assert fable_run[2].endswith("retro.py")
    # Every flag the ledger emits is one retro.py's parser declares.
    declared = set((research_ledger.ROOT / "retro.py").read_text(encoding="utf-8").split('add_argument("')[1:])
    declared = {item.split('"')[0] for item in declared}
    assert {flag for flag in fable_run[3:] if flag.startswith("--")} <= declared


def test_audit_exits_one_and_names_each_gap_with_its_command(tmp_path):
    stream = io.StringIO()
    assert research_ledger.audit(_tree(tmp_path), stream) == 1
    out = stream.getvalue()
    assert "5 runs on record, 3 finished with candidates, 2 without a retrospective" in out
    assert "2026-09-02 cvrp: " in out and "--provider astra" in out
    assert "retro --all-missing" in out


def test_audit_is_clean_when_every_finished_run_has_a_retro(tmp_path):
    research = tmp_path / "runs" / "research"
    _write_json(research / "2026-09-01" / "cvrp" / "evidence.json", _evidence("2026-09-01", "cvrp"))
    _write_json(research / "2026-09-01" / "cvrp" / "retro.json", {"status": "completed", "analysis": "ok"})
    stream = io.StringIO()
    assert research_ledger.audit(tmp_path, stream) == 0
    assert "0 without a retrospective" in stream.getvalue()


def test_retro_all_missing_runs_one_command_per_gap_through_the_injected_runner(tmp_path):
    root = _tree(tmp_path)
    launched = []

    def runner(command):
        launched.append(command)
        return 0 if "cvrp" in command else 3

    stream = io.StringIO()
    code = research_ledger.run_retro(root, stream, all_missing=True, runner=runner)
    assert code == 1
    assert [c[c.index("--problem") + 1] for c in launched] == ["cvrp", "ecc_prize"]
    assert "2 retrospectives run, 1 failed" in stream.getvalue()


def test_retro_for_one_run_refuses_an_unknown_run_without_launching(tmp_path):
    root = _tree(tmp_path)
    stream = io.StringIO()
    code = research_ledger.run_retro(root, stream, run_id="nope", problem="cvrp", runner=lambda c: 0)
    assert code == 2 and "no recorded run" in stream.getvalue()


def test_list_prints_every_run(tmp_path):
    stream = io.StringIO()
    assert research_ledger.list_runs(_tree(tmp_path), stream) == 0
    assert "5 runs on record" in stream.getvalue()
    assert "try a granular neighbourhood" in stream.getvalue()
