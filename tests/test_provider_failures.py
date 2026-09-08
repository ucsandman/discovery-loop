import json
import subprocess

import pytest

import providers


class Ledger:
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


def test_generated_prose_never_becomes_a_rate_limit(monkeypatch):
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "HTTP 429"}},
        {"type": "turn.failed", "message": "invalid candidate response"},
        {"type": "turn.completed", "usage": {"input_tokens": 3}},
    ]
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 1, "\n".join(map(json.dumps, events)), ""),
    )
    result = providers.call_model("prompt", provider="astra")
    assert result["error_kind"] == "malformed_response"
    assert result["error"] == "astra CLI returned malformed output"
    assert result["usage"] == {"input_tokens": 3}


def test_structured_natural_quota_message_is_usage_limit_and_is_charged(monkeypatch):
    payload = {
        "is_error": True,
        "result": "You've hit your limit. Your window resets tomorrow.",
        "usage": {"input_tokens": 7},
        "total_cost_usd": 0.12,
    }
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 1, json.dumps(payload), ""),
    )
    ledger = Ledger()
    result = providers.call_model("prompt", provider="fable", max_cost=0.25, ledger=ledger)
    assert result["error_kind"] == "usage_limit"
    assert result["error"] == "fable subscription usage limit reached"
    assert result["usage"] == {"input_tokens": 7}
    assert result["cost"] == 0.12
    assert ledger.settled == [("reservation-1", 0.12, {"input_tokens": 7})]


def test_fable_out_of_usage_credits_envelope_is_usage_limit(monkeypatch):
    payload = {
        "is_error": True,
        "subtype": "success",
        "result": "You're out of usage credits. Switch to another model, or manage usage credits at claude.ai.",
    }
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 1, json.dumps(payload), ""),
    )
    result = providers.call_model("prompt", provider="fable")
    assert result["error_kind"] == "usage_limit"
    assert result["error"] == "fable subscription usage limit reached"


@pytest.mark.parametrize("message", ["Connection reset in transport", "socket resetting in 2 seconds"])
def test_transport_reset_wording_is_not_usage_limit(monkeypatch, message):
    payload = {"is_error": True, "result": message}
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 1, json.dumps(payload), ""),
    )
    result = providers.call_model("prompt", provider="fable")
    assert result["error_kind"] == "infrastructure_error"


def test_successful_fable_prose_cannot_become_usage_limit(monkeypatch):
    payload = {
        "result": "You're out of usage credits. This is an example sentence, not a CLI failure.",
        "usage": {"output_tokens": 2},
    }
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 0, json.dumps(payload), ""),
    )
    result = providers.call_model("prompt", provider="fable")
    assert result["error"] is None
    assert "error_kind" not in result


def test_fable_error_envelope_errors_list_classifies_capacity(monkeypatch):
    payload = {
        "is_error": True,
        "subtype": "error_during_execution",
        "errors": [{"code": "capacity_error", "message": "service temporarily unavailable"}],
        "result": "error_during_execution",
    }
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 1, json.dumps(payload), ""),
    )
    result = providers.call_model("prompt", provider="fable")
    assert result["error_kind"] == "capacity"
    assert result["error"] == "fable provider capacity unavailable"


def test_wrong_family_model_is_rejected_before_auth_or_cli(monkeypatch):
    monkeypatch.setattr(providers, "_run_cli", lambda *_args, **_kwargs: pytest.fail("CLI should not run"))
    with pytest.raises(ValueError, match="canonical registry"):
        providers.call_model("prompt", provider="anthropic", model="gpt-6-astra")


def test_canonical_auth_failure_has_no_reservation_or_charge(monkeypatch):
    monkeypatch.setattr(providers, "auth_status", lambda provider: {"ok": False})
    ledger = Ledger()
    result = providers.call_model("prompt", provider="anthropic", ledger=ledger)
    assert result["_accounting_reserved"] == 0.0
    assert result["_accounting_charged"] == 0.0
    assert ledger.reserved == []


def test_canonical_timeout_charges_its_reservation(monkeypatch):
    monkeypatch.setattr(
        providers, "_run_cli", lambda *_args, **_kwargs: (_ for _ in ()).throw(providers.ProviderTimeout())
    )
    ledger = Ledger()
    result = providers.call_model("prompt", provider="openai", max_cost=0.75, ledger=ledger)
    assert result["error_kind"] == "timeout"
    assert result["_accounting_reserved"] == 0.75
    assert result["_accounting_charged"] == 0.75
    assert ledger.settled == [("reservation-1", None, {})]


def test_canonical_reported_cost_can_exceed_reservation(monkeypatch):
    payload = {
        "result": "ok",
        "usage": {"output_tokens": 4},
        "total_cost_usd": 0.5,
    }
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 0, json.dumps(payload), ""),
    )
    ledger = Ledger()
    result = providers.call_model("prompt", provider="anthropic", max_cost=0.25, ledger=ledger)
    assert result["_accounting_reserved"] == 0.25
    assert result["_accounting_charged"] == 0.5
    assert ledger.settled == [("reservation-1", 0.5, {"output_tokens": 4})]


def test_registered_alias_uses_its_family_cli(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, json.dumps({"result": "ok", "usage": {}}), "")

    monkeypatch.setattr(providers, "_run_cli", fake_run)
    result = providers.call_model("prompt", provider="anthropic", model="opus")
    assert result["model"] == "claude-opus-5"
    assert seen["command"][0] == "claude"
    assert "--restricted" in seen["command"]
    assert "--strict-mcp-config" in seen["command"]
    assert not any(key.startswith("ANTHROPIC_") or key.startswith("CLAUDE_") for key in seen["env"])


def test_untrusted_fable_result_is_malformed_not_infrastructure(monkeypatch):
    payload = {"result": "HTTP 429 generated by a proposed solver"}
    monkeypatch.setattr(
        providers,
        "_run_cli",
        lambda command, **_: subprocess.CompletedProcess(command, 1, json.dumps(payload), ""),
    )
    result = providers.call_model("prompt", provider="fable")
    assert result["error_kind"] == "malformed_response"


def test_diagnostics_redact_secrets_and_return_relative_path(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "DIAGNOSTICS_DIR", tmp_path / "runs" / "provider-diagnostics")
    completed = subprocess.CompletedProcess(
        ["claude"],
        1,
        json.dumps({"is_error": True, "result": "usage_limit"}),
        "authorization: bearer-value Bearer sk-private-token C:\\Users\\private\\trace.log\n"
        "Authorization: Bearer example.jwt.token\nAuthorization: Basic QmFzaWMgdG9rZW4=",
    )
    path = providers._write_diagnostic("fable", completed)
    diagnostic = next((tmp_path / "runs" / "provider-diagnostics").iterdir())
    contents = diagnostic.read_text(encoding="utf-8")
    assert path is None
    assert "bearer-value" not in contents
    assert "sk-private-token" not in contents
    assert "example.jwt.token" not in contents
    assert "QmFzaWMgdG9rZW4=" not in contents
    assert "C:\\Users\\private" not in contents
    assert "[REDACTED]" in contents


def test_probe_models_require_shared_ledger(monkeypatch):
    monkeypatch.setattr(
        providers, "auth_status", lambda provider: {"ok": True, "auth_method": "x", "subscription_status": "x"}
    )
    with pytest.raises(ValueError, match="shared accounting ledger"):
        providers.preflight(probe_models=True)


def test_preflight_probe_uses_ledger_and_model_specific_result(monkeypatch):
    ledger = Ledger()
    seen = []
    monkeypatch.setattr(
        providers, "auth_status", lambda provider: {"ok": True, "auth_method": "x", "subscription_status": "x"}
    )

    def fake_call(prompt, **kwargs):
        seen.append(kwargs)
        return {"error": None}

    monkeypatch.setattr(providers, "call_model", fake_call)
    result = providers.preflight(providers=("fable",), models={"fable": "opus"}, probe_models=True, ledger=ledger)
    assert result["details"]["fable"]["model"] == "opus"
    assert result["details"]["fable"]["model_acceptance"] == "accepted"
    assert seen[0]["ledger"] is ledger


@pytest.mark.parametrize(
    ("family", "model"),
    [("anthropic", "claude-opus-5"), ("openai", "gpt-5.6-sol")],
)
def test_canonical_family_preflight_uses_exact_model(monkeypatch, family, model):
    ledger = Ledger()
    seen = []
    monkeypatch.setattr(
        providers,
        "auth_status",
        lambda provider: {"ok": True, "auth_method": "subscription", "subscription_status": "active"},
    )

    def fake_call(prompt, **kwargs):
        seen.append(kwargs)
        return {"error": None}

    monkeypatch.setattr(providers, "call_model", fake_call)
    result = providers.preflight(
        providers=(family,),
        models={family: model},
        probe_models=True,
        ledger=ledger,
    )
    assert result["details"][family]["model"] == model
    assert result["details"][family]["model_acceptance"] == "accepted"
    assert seen == [
        {"provider": family, "model": model, "timeout": 60, "max_cost": 0.25, "ledger": ledger, "purpose": "preflight"}
    ]
