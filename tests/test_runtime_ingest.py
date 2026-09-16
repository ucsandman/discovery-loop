"""runtime_ingest: Claude Code runtime events become OBSERVATIONS, never confirmations."""

import importlib.util
import json
from pathlib import Path


def ingest():
    path = Path(__file__).resolve().parents[1] / "runtime_ingest.py"
    spec = importlib.util.spec_from_file_location("runtime_ingest", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def ev(seq, kind, data, agent_id=None):
    row = {"seq": seq, "t": 1789590000000 + seq * 1000, "kind": kind, "source": "test", "data": data}
    if agent_id:
        row["agentId"] = agent_id
    return row


def test_screen_events_triggers_on_constructed_cases_and_not_on_clean_ones():
    m = ingest()
    clean = [
        ev(
            1,
            "SessionStarted",
            {"supports": {"toolInterception": True, "toolResultMutation": True, "usageSignals": True}},
        ),
        ev(2, "ToolRequested", {"tool": "Read", "tool_use_id": "a", "args": {"file_path": "x"}}),
        ev(3, "ToolCompleted", {"tool": "Read", "tool_use_id": "a", "ms": 1}),
        ev(4, "ContextChanged", {"messageCount": 10, "contextTokens": 1000}),
        ev(5, "ContextChanged", {"messageCount": 12, "contextTokens": 1100}),
        ev(
            6,
            "SubagentStarted",
            {"childAgentId": "c", "type": "haiku-scout", "model": "claude-haiku-4-5", "requestedModel": "haiku"},
        ),
        ev(7, "UnknownKindFromAFutureBuild", {"x": 1}),
    ]
    assert m.screen_events(clean, session="s", source_path="p") == []

    hot = [
        ev(
            1,
            "SessionStarted",
            {"supports": {"toolInterception": True, "toolResultMutation": False, "usageSignals": True}},
        ),
        *[
            ev(10 + i, "ToolRequested", {"tool": "Bash", "tool_use_id": "b%d" % i, "args": {"command": "npm test"}})
            for i in range(3)
        ],
        *[ev(20 + i, "FileObserved", {"tool": "Read", "path": "C:/p/hot.md"}) for i in range(5)],
        ev(30, "ContextChanged", {"messageCount": 10, "contextTokens": 1000}),
        ev(31, "ContextChanged", {"messageCount": 12, "contextTokens": 2000}),
        ev(
            40,
            "SubagentStarted",
            {"childAgentId": "c", "type": "haiku-scout", "model": "claude-haiku-4-5", "requestedModel": "opus"},
        ),
    ]
    obs = m.screen_events(hot, session="s", source_path="p")
    families = {o["family"] for o in obs}
    assert "repeated_retries" in families
    assert "tool_thrashing" in families
    assert "unexpected_context_growth" in families
    assert "routing_prediction_error" in families
    assert "capability_regression" in families
    for o in obs:
        assert o["count"] >= 1 and o["session"] == "s" and o["source_path"] == "p"


def test_shadow_pairs_and_subagent_estimates():
    m = ingest()
    classic = [
        {
            "session": "s",
            "subsystem": "routing",
            "key": "k1",
            "side": "classic",
            "decision": "deny",
            "reasonCodes": ["x"],
        }
    ]
    mod = [
        {"session": "s", "subsystem": "routing", "key": "k1", "side": "mod", "decision": "allow", "reasonCodes": ["y"]},
        {"session": "s", "subsystem": "readCache", "key": "p#3", "side": "mod", "decision": "serve", "reasonCodes": []},
    ]
    pairs = m.screen_shadow_pairs(classic, mod, source_path="p")
    assert any(o["family"] == "classic_vs_mod_disagreement" for o in pairs)
    assert any(o["family"] == "cache_intervention_outcome" for o in m.screen_cache_interventions(mod, source_path="p"))
    agree = m.screen_shadow_pairs(classic, [{**mod[0], "decision": "deny"}], source_path="p")
    assert not any(o["family"] == "classic_vs_mod_disagreement" for o in agree), "agreement is not an observation"
    rows = [
        {
            "session": "s",
            "decision": "measured",
            "type": "haiku-scout",
            "declared": 20000,
            "measured": 60000,
            "predictionError": 40000,
        }
    ]
    assert any(o["family"] == "subagent_estimate_error" for o in m.screen_subagent_estimates(rows, source_path="p"))
    rows_ok = [
        {
            "session": "s",
            "decision": "measured",
            "type": "haiku-scout",
            "declared": 20000,
            "measured": 21000,
            "predictionError": 1000,
        }
    ]
    assert m.screen_subagent_estimates(rows_ok, source_path="p") == []


def test_rows_are_observations_and_dry_run_writes_nothing(tmp_path):
    m = ingest()
    obs = m.screen_events(
        [*[ev(10 + i, "FileObserved", {"tool": "Read", "path": "C:/p/hot.md"}) for i in range(6)]],
        session="s",
        source_path="p",
    )
    rows = m.to_observation_rows(obs)
    assert rows, "a thrash case yields at least one row"
    for r in rows:
        blob = json.dumps(r).lower()
        assert "observation" in blob, "every row is marked as an observation"
        assert r.get("development_status", "") in ("", None), "never a promoted/confirmed status"
    events_path = tmp_path / "e.jsonl"
    events_path.write_text(
        "\n".join(
            json.dumps(e)
            for e in [*[ev(10 + i, "FileObserved", {"tool": "Read", "path": "C:/p/hot.md"}) for i in range(6)]]
        )
        + "\n",
        encoding="utf8",
    )
    history = tmp_path / "history.jsonl"
    code = m.main(["--events", str(events_path), "--history-path", str(history), "--dry-run"])
    assert code in (0, None)
    assert not history.exists(), "--dry-run writes nothing"
