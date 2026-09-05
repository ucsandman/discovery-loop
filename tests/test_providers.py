import json
import subprocess

import pytest

import providers


ORIGINAL_AUTH_STATUS = providers.auth_status


class FakeLedger:
    def __init__(self):
        self.reserved = []
        self.settled = []

    def reserve(self, amount, label):
        self.reserved.append((amount, label))
        return "reservation-1"

    def settle(self, reservation, cost=None, usage=None):
        self.settled.append((reservation, cost, usage))


@pytest.fixture(autouse=True)
def subscription_auth(monkeypatch):
    monkeypatch.setattr(
        providers,
        "auth_status",
        lambda provider: {
            "ok": True,
            "auth_method": "claude.ai" if provider == "fable" else "chatgpt",
            "subscription_status": "max" if provider == "fable" else "active",
        },
    )


def test_fable_uses_restricted_subscription_cli_and_settles_reported_cost(monkeypatch):
    seen = {}

    def fake_run(command, *, prompt, cwd, env, timeout):
        seen.update(command=command, prompt=prompt, cwd=cwd, env=env, timeout=timeout)
        payload = {
            "result": "",
            "structured_output": {"text": "done", "code": "print('ok')", "idea": "small change"},
            "usage": {"input_tokens": 12, "output_tokens": 7},
            "total_cost_usd": 0.03,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(providers, "_run_cli", fake_run)
    ledger = FakeLedger()
    result = providers.call_model("write it", provider="fable", timeout=17, max_cost=0.5, ledger=ledger)

    command = " ".join(seen["command"])
    assert "claude-fable-5-1" in command
    assert "--restricted" in seen["command"]
    assert "--strict-mcp-config" in seen["command"]
    assert "--max-budget-usd" in seen["command"]
    assert seen["prompt"] == "write it"
    assert seen["timeout"] == 17
    assert not any(k.startswith("ANTHROPIC_") or k.startswith("CLAUDE_") for k in seen["env"])
    assert result == {
        "text": "done",
        "code": "print('ok')",
        "idea": "small change",
        "provider": "fable",
        "model": "claude-fable-5-1",
        "cost": 0.03,
        "usage": {"input_tokens": 12, "output_tokens": 7},
        "error": None,
        "billing_mode": "subscription",
        "cost_basis": "reported_api_equivalent",
    }
    assert ledger.reserved == [(0.5, "generation:fable:claude-fable-5-1")]
    assert ledger.settled == [("reservation-1", 0.03, {"input_tokens": 12, "output_tokens": 7})]


def test_astra_parses_jsonl_usage_and_reserves_unknown_cost(monkeypatch):
    seen = {}

    def fake_run(command, *, prompt, cwd, env, timeout):
        seen.update(command=command, prompt=prompt, cwd=cwd, env=env)
        events = [
            {"type": "thread.started", "thread_id": "private-id"},
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps({"text": "review", "code": "", "idea": "check bounds"}),
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 21, "output_tokens": 8}},
        ]
        return subprocess.CompletedProcess(command, 0, "\n".join(map(json.dumps, events)), "")

    monkeypatch.setattr(providers, "_run_cli", fake_run)
    ledger = FakeLedger()
    result = providers.call_model("review", provider="astra", max_cost=0.4, ledger=ledger, purpose="review")

    command = " ".join(seen["command"])
    assert "gpt-6-astra" in command
    assert "--ignore-user-config" in seen["command"]
    assert "--ephemeral" in seen["command"]
    assert "--sandbox" in seen["command"] and "read-only" in seen["command"]
    assert "--output-schema" in seen["command"]
    assert "shell_tool" in seen["command"] and "unified_exec" in seen["command"]
    assert 'web_search="disabled"' in seen["command"]
    assert "mcp_servers={}" in seen["command"]
    assert "project_doc_max_bytes=0" in seen["command"]
    assert 'model_provider="openai"' in seen["command"]
    assert "--ignore-rules" in seen["command"]
    assert seen["prompt"].endswith("Request:\nreview")
    assert not any(k in seen["env"] for k in ("OPENAI_API_KEY", "CODEX_API_KEY"))
    assert result["text"] == "review"
    assert result["code"] is None
    assert result["idea"] == "check bounds"
    assert result["cost"] is None
    assert result["billing_mode"] == "subscription"
    assert result["cost_basis"] == "reserved_allowance"
    assert result["usage"] == {"input_tokens": 21, "output_tokens": 8}
    assert ledger.reserved == [(0.4, "review:astra:gpt-6-astra")]
    assert ledger.settled == [("reservation-1", None, {"input_tokens": 21, "output_tokens": 8})]


def test_error_is_concise_and_unknown_charge_consumes_reservation(monkeypatch):
    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 9, "private model output", "private diagnostic")

    monkeypatch.setattr(providers, "_run_cli", fake_run)
    ledger = FakeLedger()
    result = providers.call_model("prompt", provider="fable", max_cost=0.25, ledger=ledger)

    assert result["error"] == "fable CLI exited with status 9"
    assert "private" not in result["error"]
    assert result["cost"] is None
    assert ledger.settled == [("reservation-1", None, {})]


def test_invalid_provider_never_falls_back():
    with pytest.raises(ValueError, match="provider"):
        providers.call_model("prompt", provider="other")


def test_timeout_is_a_failed_charged_call(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise providers.ProviderTimeout

    monkeypatch.setattr(providers, "_run_cli", fake_run)
    ledger = FakeLedger()
    result = providers.call_model("prompt", provider="astra", max_cost=0.75, ledger=ledger)

    assert result["error"] == "astra CLI timed out"
    assert ledger.settled == [("reservation-1", None, {})]


def test_astra_rejects_tool_events_even_when_cli_exits_zero(monkeypatch):
    def fake_run(command, **_kwargs):
        events = [
            {"type": "item.completed", "item": {"type": "command_execution", "command": "private"}},
            {"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}},
        ]
        return subprocess.CompletedProcess(command, 0, "\n".join(map(json.dumps, events)), "")

    monkeypatch.setattr(providers, "_run_cli", fake_run)
    result = providers.call_model("prompt", provider="astra")
    assert result["error"] == "astra CLI attempted prohibited tool use"


def test_astra_requires_completed_turn(monkeypatch):
    def fake_run(command, **_kwargs):
        event = {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": '{"text":"partial","code":"","idea":""}'},
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(event), "")

    monkeypatch.setattr(providers, "_run_cli", fake_run)
    result = providers.call_model("prompt", provider="astra")
    assert result["error"] == "astra CLI ended before completing"


def test_claude_saved_api_auth_is_rejected_before_reservation(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_run_auth_command",
        lambda command, provider: subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"loggedIn": True, "authMethod": "api_key", "subscriptionType": "api"}),
            "",
        ),
    )
    monkeypatch.setattr(providers, "auth_status", ORIGINAL_AUTH_STATUS)
    monkeypatch.setattr(providers, "_run_cli", lambda *_args, **_kwargs: pytest.fail("paid CLI call attempted"))
    ledger = FakeLedger()

    result = providers.call_model("prompt", provider="fable", ledger=ledger)

    assert result["error"] == "fable subscription authentication required"
    assert result["billing_mode"] == "subscription"
    assert ledger.reserved == []


def test_codex_unknown_or_custom_auth_is_rejected(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_run_auth_command",
        lambda command, provider: subprocess.CompletedProcess(command, 0, "Logged in using API key", ""),
    )
    monkeypatch.setattr(providers, "auth_status", ORIGINAL_AUTH_STATUS)
    status = providers.auth_status("astra")
    assert status == {"ok": False, "auth_method": "unknown", "subscription_status": "unknown"}


def test_provider_preflight_reports_only_sanitized_subscription_metadata(monkeypatch):
    statuses = {
        "fable": {"ok": True, "auth_method": "claude.ai", "subscription_status": "max"},
        "astra": {"ok": True, "auth_method": "chatgpt", "subscription_status": "active"},
    }
    monkeypatch.setattr(providers, "auth_status", lambda provider: statuses[provider])
    result = providers.preflight()
    assert result == {
        "ok": True,
        "details": {
            "fable": {
                "ok": True,
                "auth_mode": "subscription",
                "auth_method": "claude.ai",
                "subscription_status": "max",
            },
            "astra": {
                "ok": True,
                "auth_mode": "subscription",
                "auth_method": "chatgpt",
                "subscription_status": "active",
            },
        },
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"loggedIn": True, "authMethod": "attacker-controlled", "subscriptionType": "custom-plan"},
    ],
)
def test_claude_malformed_or_unknown_auth_metadata_fails_closed_and_is_sanitized(monkeypatch, payload):
    monkeypatch.setattr(
        providers,
        "_run_auth_command",
        lambda command, provider: subprocess.CompletedProcess(command, 0, json.dumps(payload), ""),
    )
    monkeypatch.setattr(providers, "auth_status", ORIGINAL_AUTH_STATUS)

    assert providers.auth_status("fable") == {
        "ok": False,
        "auth_method": "unknown",
        "subscription_status": "unknown",
    }


def test_legacy_model_entry_points_reject_api_auth(monkeypatch):
    import loop
    import retro

    monkeypatch.setattr(providers, "auth_status", lambda provider: {"ok": False})
    monkeypatch.setattr(
        providers, "_run_cli", lambda *args, **kwargs: pytest.fail("generation attempted with rejected auth")
    )
    code, cost, error = loop.Loop.call_model("prompt", "claude-fable-5-1")
    assert code is None and cost == 0 and "subscription authentication required" in error
    text, cost, error = retro.call_text("prompt")
    assert text == "" and cost == 0 and "subscription authentication required" in error


def test_usage_limit_is_sanitized_and_stops_retries(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            '{"type":"error","message":"usage_limit reached; account details omitted"}',
            "",
        ),
    )
    result = providers.call_model("prompt", provider="astra")
    assert result["error_kind"] == "usage_limit"
    assert result["error"] == "astra subscription usage limit reached"
