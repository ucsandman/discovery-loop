"""Subscription-CLI model providers with conservative run-budget accounting."""

import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

from model_registry import MODEL_REGISTRY, alias_for_model, model_spec

DEFAULT_MODELS = {
    provider: next(item["model"] for item in MODEL_REGISTRY.values() if item["transport"] == provider)
    for provider in ("fable", "astra")
}
_PROVIDER_TRANSPORT = {"fable": "fable", "anthropic": "fable", "astra": "astra", "openai": "astra"}
_CLAUDE_SUBSCRIPTIONS = {"max", "pro", "team", "enterprise"}
_CLAUDE_SYSTEM_PROMPT = (
    "You are an expert in numerical and combinatorial optimisation. Answer the request directly without using "
    "tools, network access, or code execution."
)
_ASTRA_INSTRUCTIONS = (
    f"{_CLAUDE_SYSTEM_PROMPT} Put the complete answer in text, a complete Python program in code when requested "
    "(otherwise an empty string), and the core idea in idea (otherwise an empty string)."
)
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "code": {"type": "string"},
        "idea": {"type": "string"},
    },
    "required": ["text", "code", "idea"],
    "additionalProperties": False,
}


class ProviderTimeout(TimeoutError):
    """The provider CLI exceeded its hard wall-clock limit."""


def _finite_positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def _clean_environment(provider):
    del provider
    allowed = {
        "APPDATA",
        "CODEX_HOME",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "USERNAME",
        "WINDIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _kill_process_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def _resolved_command(command):
    executable = command[0]
    if os.name == "nt" and executable.lower() == "codex":
        resolved = shutil.which("codex.cmd") or shutil.which(executable)
    else:
        resolved = shutil.which(executable)
    if not resolved:
        # Let the subprocess boundary report a missing executable consistently.
        return list(command)
    if os.name == "nt" and Path(resolved).suffix.lower() in (".cmd", ".bat"):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", resolved, *command[1:]]
    return [resolved, *command[1:]]


def _run_cli(command, *, prompt, cwd, env, timeout):
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        _resolved_command(command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        process.communicate()
        raise ProviderTimeout from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


DIAGNOSTICS_DIR = Path(__file__).resolve().parent / "runs" / "provider-diagnostics"


def _redact_diagnostic(value):
    """Remove credentials and machine paths from retained CLI diagnostics."""
    value = re.sub(
        r"(?im)\b(authorization|proxy-authorization)\b\s*[:=]\s*(?:bearer|basic)\s+[^\r\n]*",
        r"\1: [REDACTED]",
        value,
    )
    value = re.sub(
        r"(?im)\b(api[_ -]?key|access[_ -]?token|authorization|bearer|password|secret|cookie|credential)\b"
        r"(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)\bbearer\s+[a-z0-9._-]{8,}", "Bearer [REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", value)
    value = re.sub(r"(?i)(?:[a-z]:\\|/)(?:[^\s\"']+[\\/])*(?:[^\s\"']*)", "<local-path>", value)
    return value


def _write_diagnostic(provider, completed, limit=4000):
    """Keep the CLI's stderr/stdout tail on disk for a failed call.

    The error string stays concise and private; this file is the place to look
    when a night reports "exited with status 1" (2026-09-05 lost three failures
    with no captured cause).  Returns the file path, or None when nothing was
    captured or the write failed.
    """
    stderr = _redact_diagnostic((completed.stderr or "")[-limit:])
    stdout = _redact_diagnostic(_structured_failure_text(provider, completed)[-limit:])
    if not stderr.strip() and not stdout.strip():
        return None
    try:
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        path = DIAGNOSTICS_DIR / f"{stamp}-{provider}-{os.getpid()}-{_diagnostic_counter()}.txt"
        path.write_text(
            f"provider: {provider}\nreturncode: {completed.returncode}\n\n--- stderr (tail) ---\n{stderr}\n\n--- stdout (tail) ---\n{stdout}\n",
            encoding="utf-8",
        )
        try:
            return str(path.relative_to(Path(__file__).resolve().parent))
        except ValueError:
            return None
    except OSError:
        return None


_DIAGNOSTIC_SEQUENCE = 0


def _diagnostic_counter():
    global _DIAGNOSTIC_SEQUENCE
    _DIAGNOSTIC_SEQUENCE += 1
    return _DIAGNOSTIC_SEQUENCE


def _run_auth_command(command, provider):
    return subprocess.run(
        _resolved_command(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_clean_environment(provider),
        timeout=15,
        check=False,
    )


def auth_status(provider):
    """Return sanitized subscription status; API-key and unknown authentication fail closed."""
    if provider not in _PROVIDER_TRANSPORT:
        raise ValueError(f"unknown provider {provider!r}; expected anthropic, openai, fable or astra")
    provider = _PROVIDER_TRANSPORT[provider]
    try:
        if provider == "fable":
            completed = _run_auth_command(["claude", "auth", "status", "--json"], provider)
            if completed.returncode != 0:
                raise ValueError
            payload = json.loads(completed.stdout)
            if not isinstance(payload, dict):
                raise ValueError
            raw_method = payload.get("authMethod")
            raw_subscription = payload.get("subscriptionType")
            method = raw_method if raw_method == "claude.ai" else "unknown"
            subscription = raw_subscription if raw_subscription in _CLAUDE_SUBSCRIPTIONS else "unknown"
            ok = payload.get("loggedIn") is True and method == "claude.ai" and subscription in _CLAUDE_SUBSCRIPTIONS
        else:
            completed = _run_auth_command(["codex", "login", "status"], provider)
            status = (completed.stdout + "\n" + completed.stderr).strip().lower()
            method = "chatgpt" if status == "logged in using chatgpt" else "unknown"
            subscription = "active" if completed.returncode == 0 and method == "chatgpt" else "unknown"
            ok = completed.returncode == 0 and method == "chatgpt"
    except subprocess.TimeoutExpired:
        return {"ok": False, "auth_method": "unknown", "subscription_status": "unknown", "error_kind": "timeout"}
    except OSError:
        return {"ok": False, "auth_method": "unknown", "subscription_status": "unknown", "error_kind": "unavailable"}
    except (json.JSONDecodeError, TypeError, ValueError):
        method = "unknown"
        subscription = "unknown"
        ok = False
    return {
        "ok": ok,
        "auth_method": method if isinstance(method, str) else "unknown",
        "subscription_status": subscription if isinstance(subscription, str) else "unknown",
    }


def preflight(providers=("fable", "astra"), *, models=None, probe_models=False, probe_budget=0.25, ledger=None):
    """Verify subscription auth, optionally making a minimal configured-model acceptance probe.

    The default remains auth-only for cheap diagnostics. Callers must label it as such;
    ``probe_models=True`` records whether the exact configured model accepted a real call.
    """
    if probe_models and ledger is None:
        raise ValueError("model acceptance probes require a shared accounting ledger")
    details = {}
    for provider in providers:
        status = auth_status(provider)
        details[provider] = {
            "ok": status["ok"],
            "auth_mode": "subscription" if status["ok"] else "rejected",
            "auth_method": status["auth_method"],
            "subscription_status": status["subscription_status"],
        }
        if probe_models and status["ok"]:
            selected = (models or {}).get(provider, DEFAULT_MODELS[_PROVIDER_TRANSPORT[provider]])
            response = call_model(
                "Return the single word ready.",
                provider=provider,
                model=selected,
                timeout=60,
                max_cost=probe_budget,
                ledger=ledger,
                purpose="preflight",
            )
            details[provider].update(
                model=selected,
                model_acceptance="accepted" if not response.get("error") else "rejected",
                model_error_kind=response.get("error_kind"),
            )
            details[provider]["ok"] = details[provider]["ok"] and not response.get("error")
    return {"ok": bool(details) and all(item["ok"] for item in details.values()), "details": details}


def _structured_failure_text(provider, completed):
    """Extract only CLI-owned error fields, never generated response prose."""
    fragments = [completed.stderr or ""]
    if provider == "fable":
        try:
            payload = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if isinstance(payload, dict) and payload.get("is_error") is True:
            for key in ("error", "message", "error_type", "code", "subtype", "errors"):
                fragments.extend(_error_envelope_fragments(payload.get(key)))
            # Claude's JSON print envelope places CLI failures in ``result`` only
            # when it also marks the response as an error.  A normal model answer
            # must never influence transport/fallback classification.
            if "structured_output" not in payload and isinstance(payload.get("result"), str):
                fragments.append(payload["result"])
    else:
        for line in (completed.stdout or "").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") not in {"error", "turn.failed"}:
                continue
            for value in (event.get("message"), event.get("error"), event.get("code"), event.get("subtype")):
                if isinstance(value, str):
                    fragments.append(value)
                elif isinstance(value, dict):
                    fragments.extend(str(value[key]) for key in ("message", "type", "code") if key in value)
    return "\n".join(fragments)


def _error_envelope_fragments(value):
    """Return conventional error values from a CLI error envelope only."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            value[key] for key in ("message", "type", "code", "subtype", "error") if isinstance(value.get(key), str)
        ]
    if isinstance(value, list):
        fragments = []
        for item in value:
            fragments.extend(_error_envelope_fragments(item))
        return fragments
    return []


def _failure_kind(provider, completed, error):
    """Classify a failed CLI call without retaining provider text or inventing reset data."""
    raw = _structured_failure_text(provider, completed)
    if re.search(
        r"usage[_ -]?limit|out of usage credits|quota[_ -]?(?:exceeded|exhausted)|insufficient_quota|(?:you have|you've) hit your[^\n]{0,40}limit|(?:usage|limit|quota|credits?|window)[^\n]{0,48}reset(?:s|ting)?\s+(?:at|on|in)|reset(?:s|ting)?\s+(?:at|on|in)[^\n]{0,48}(?:usage|limit|quota|credits?|window)",
        raw,
        re.I,
    ):
        return "usage_limit", f"{provider} subscription usage limit reached"
    if re.search(r"rate[_ -]?limit|too many requests|http\s*429", raw, re.I):
        return "rate_limited_unclassified", f"{provider} subscription rate limited"
    if re.search(
        r"capacity(?:[_ -]?(?:error|exceeded))?|overload(?:ed)?|service unavailable|temporarily unavailable|http\s*5(?:0[0-9]|[1-9][0-9])",
        raw,
        re.I,
    ):
        return "capacity", f"{provider} provider capacity unavailable"
    if re.search(
        r"(?:unknown[_ -]?model|model[^\n]{0,80}(?:not found|unavailable|unsupported|does not exist))", raw, re.I
    ):
        return "model_unavailable", f"{provider} model unavailable"
    if re.search(r"unauthori[sz]ed|authentication|invalid[_ -]?grant|login required|http\s*401", raw, re.I):
        return "authentication", f"{provider} subscription authentication required"
    if "attempted prohibited tool use" in (error or ""):
        return "prohibited_tool", error
    if "malformed output" in (error or ""):
        return "malformed_response", error
    if "ended before completing" in (error or ""):
        return "incomplete_response", error
    if _contains_model_output(provider, completed):
        return "malformed_response", f"{provider} CLI returned malformed output"
    if completed.returncode != 0:
        return "infrastructure_error", error
    return None, error


def _contains_model_output(provider, completed):
    """Recognize a model response without treating its text as a CLI error."""
    if provider == "fable":
        try:
            payload = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("is_error") is not True
            and any(key in payload for key in ("result", "structured_output"))
        )
    for line in (completed.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            return True
    return False


def _model_for_provider(model, provider):
    """Normalize registered aliases and reject a model from the other family."""
    family = "anthropic" if provider == "fable" else "openai"
    if model in MODEL_REGISTRY:
        spec = model_spec(model)
        if spec["family"] != family:
            raise ValueError(f"model {model!r} is absent from the canonical registry for this family")
        return spec["model"]
    alias_for_model(model, family)
    return model


def _usage(value):
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key, item in value.items():
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)) and math.isfinite(item):
            clean[str(key)] = item
        elif isinstance(item, dict):
            nested = _usage(item)
            if nested:
                clean[str(key)] = nested
    return clean


def _cost(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _fields(payload, fallback_text=""):
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            payload = decoded
        else:
            payload = {"text": payload}
    if not isinstance(payload, dict):
        payload = {}
    text = payload.get("text") if isinstance(payload.get("text"), str) else fallback_text
    code = payload.get("code") if isinstance(payload.get("code"), str) else ""
    idea = payload.get("idea") if isinstance(payload.get("idea"), str) else ""
    if not code and text:
        match = re.search(r"```python\s*\n(.*?)```", text, re.S)
        code = match.group(1) if match else ""
    if not idea and text:
        match = re.search(r"^IDEA:\s*(.+)$", text, re.M)
        idea = match.group(1).strip() if match else ""
    return text, code or None, idea or None


def _parse_fable(completed):
    try:
        outer = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        outer = {}
    if not isinstance(outer, dict):
        outer = {}
    usage = _usage(outer.get("usage"))
    cost = _cost(outer.get("total_cost_usd"))
    if completed.returncode != 0:
        return "", None, None, cost, usage, f"fable CLI exited with status {completed.returncode}"
    if outer.get("is_error"):
        return "", None, None, cost, usage, "fable CLI reported an error"
    payload = outer.get("structured_output")
    fallback = outer.get("result") if isinstance(outer.get("result"), str) else ""
    if payload is None and fallback:
        payload = fallback
    text, code, idea = _fields(payload, fallback)
    if not text and not code and not idea:
        return "", None, None, cost, usage, "fable CLI returned malformed output"
    return text, code, idea, cost, usage, None


def _parse_astra(completed):
    events = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    usage = {}
    message = ""
    completed_turn = False
    prohibited_tool = False
    failed_turn = False
    for event in events:
        if event.get("type") == "turn.completed":
            usage = _usage(event.get("usage"))
            completed_turn = True
        if event.get("type") in ("turn.failed", "error"):
            failed_turn = True
        item = event.get("item")
        if isinstance(item, dict):
            if item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "tool_call", "web_search"):
                prohibited_tool = True
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                if isinstance(item.get("text"), str):
                    message = item["text"]
    if completed.returncode != 0:
        return "", None, None, None, usage, f"astra CLI exited with status {completed.returncode}"
    if failed_turn:
        return "", None, None, None, usage, "astra CLI reported an error"
    if prohibited_tool:
        return "", None, None, None, usage, "astra CLI attempted prohibited tool use"
    if not completed_turn:
        return "", None, None, None, usage, "astra CLI ended before completing"
    text, code, idea = _fields(message)
    if not text and not code and not idea:
        return "", None, None, None, usage, "astra CLI returned malformed output"
    return text, code, idea, None, usage, None


def call_model(prompt, provider="fable", model=None, timeout=900, max_cost=2.0, ledger=None, purpose="generation"):
    """Call a logged-in provider CLI and return one provider-neutral response dictionary."""
    requested_provider = provider
    if provider not in _PROVIDER_TRANSPORT:
        raise ValueError(f"unknown provider {provider!r}; expected anthropic, openai, fable or astra")
    provider = _PROVIDER_TRANSPORT[provider]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a nonempty string")
    timeout = _finite_positive(timeout, "timeout")
    max_cost = _finite_positive(max_cost, "max_cost")
    model = model or DEFAULT_MODELS[provider]
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a nonempty string")
    model = _model_for_provider(model, provider)
    canonical_family_request = requested_provider in {"anthropic", "openai"}

    result = {
        "text": "",
        "code": None,
        "idea": None,
        "provider": requested_provider,
        "model": model,
        "cost": None,
        "usage": {},
        "error": None,
        "billing_mode": "subscription",
        "cost_basis": "reserved_allowance",
    }
    if canonical_family_request:
        # Routing uses these fields instead of a shared-ledger snapshot, which
        # races when multiple model attempts are active.  Legacy callers keep
        # their exact response shape.
        result.update(_accounting_reserved=0.0, _accounting_charged=0.0)
    authentication = auth_status(provider)
    if not authentication["ok"]:
        result["error"] = f"{provider} subscription authentication required"
        result["error_kind"] = "authentication"
        if authentication.get("error_kind"):
            result["error_kind"] = authentication["error_kind"]
        return result

    reservation = ledger.reserve(max_cost, f"{purpose}:{provider}:{model}") if ledger is not None else None
    if canonical_family_request:
        result["_accounting_reserved"] = max_cost
    try:
        with tempfile.TemporaryDirectory(prefix=f"discovery-{provider}-", ignore_cleanup_errors=True) as temporary:
            temporary_path = Path(temporary)
            schema_path = temporary_path / "response-schema.json"
            schema_path.write_text(json.dumps(_RESPONSE_SCHEMA), encoding="utf-8")
            if provider == "fable":
                mcp_path = temporary_path / "mcp.json"
                mcp_path.write_text('{"mcpServers":{}}', encoding="utf-8")
                command = [
                    "claude",
                    "-p",
                    "--model",
                    model,
                    "--output-format",
                    "json",
                    "--max-turns",
                    "1",
                    "--max-budget-usd",
                    str(max_cost),
                    "--restricted",
                    "--strict-mcp-config",
                    "--mcp-config",
                    str(mcp_path),
                    "--setting-sources",
                    "",
                    "--tools",
                    "",
                    "--no-session-persistence",
                    "--system-prompt",
                    _CLAUDE_SYSTEM_PROMPT,
                ]
            else:
                command = [
                    "codex",
                    "exec",
                    "--model",
                    model,
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--ephemeral",
                    "--json",
                    "--output-schema",
                    str(schema_path),
                    "--sandbox",
                    "read-only",
                    "--disable",
                    "shell_tool",
                    "--disable",
                    "unified_exec",
                    "--disable",
                    "code_mode_host",
                    "--disable",
                    "view_image",
                    "--disable",
                    "image_generation",
                    "--disable",
                    "computer_use",
                    "--disable",
                    "browser_use",
                    "--disable",
                    "in_app_browser",
                    "--disable",
                    "apps",
                    "--disable",
                    "enable_mcp_apps",
                    "--disable",
                    "tool_suggest",
                    "--disable",
                    "skill_search",
                    "--config",
                    'web_search="disabled"',
                    "--config",
                    "mcp_servers={}",
                    "--config",
                    "project_doc_max_bytes=0",
                    "--config",
                    'model_provider="openai"',
                    "--skip-git-repo-check",
                    "--color",
                    "never",
                    "-C",
                    str(temporary_path),
                    "-",
                ]
            cli_prompt = prompt if provider == "fable" else f"{_ASTRA_INSTRUCTIONS}\n\nRequest:\n{prompt}"
            completed = _run_cli(
                command,
                prompt=cli_prompt,
                cwd=temporary_path,
                env=_clean_environment(provider),
                timeout=timeout,
            )
            parsed = _parse_fable(completed) if provider == "fable" else _parse_astra(completed)
            text, code, idea, cost, usage, error = parsed
            result.update(text=text, code=code, idea=idea, cost=cost, usage=usage, error=error)
            if error:
                result["diagnostic_path"] = _write_diagnostic(provider, completed)
                kind, message = _failure_kind(provider, completed, error)
                result["error"] = message
                if kind:
                    result["error_kind"] = kind
            if provider == "fable" and cost is not None:
                result["cost_basis"] = "reported_api_equivalent"
    except ProviderTimeout:
        result["error"] = f"{provider} CLI timed out"
        result["error_kind"] = "timeout"
    except OSError:
        result["error"] = f"{provider} CLI unavailable"
        result["error_kind"] = "unavailable"
    finally:
        if ledger is not None:
            settled = ledger.settle(reservation, cost=result["cost"], usage=result["usage"])
            if canonical_family_request:
                result["_accounting_charged"] = (
                    float(settled)
                    if isinstance(settled, (int, float)) and not isinstance(settled, bool)
                    else (result["cost"] if result["cost"] is not None else max_cost)
                )
        elif canonical_family_request:
            result["_accounting_charged"] = result["cost"] if result["cost"] is not None else max_cost
    return result
