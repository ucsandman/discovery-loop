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


DEFAULT_MODELS = {"fable": "claude-fable-5-1", "astra": "gpt-6-astra"}
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
        raise OSError(f"{executable} executable not found")
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
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"unknown provider {provider!r}; expected fable or astra")
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


def preflight(providers=("fable", "astra")):
    """Verify every selected CLI uses subscription authentication without making a model request."""
    details = {}
    for provider in providers:
        status = auth_status(provider)
        details[provider] = {
            "ok": status["ok"],
            "auth_mode": "subscription" if status["ok"] else "rejected",
            "auth_method": status["auth_method"],
            "subscription_status": status["subscription_status"],
        }
    return {"ok": bool(details) and all(item["ok"] for item in details.values()), "details": details}


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
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"unknown provider {provider!r}; expected fable or astra")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a nonempty string")
    timeout = _finite_positive(timeout, "timeout")
    max_cost = _finite_positive(max_cost, "max_cost")
    model = model or DEFAULT_MODELS[provider]
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a nonempty string")

    result = {
        "text": "",
        "code": None,
        "idea": None,
        "provider": provider,
        "model": model,
        "cost": None,
        "usage": {},
        "error": None,
        "billing_mode": "subscription",
        "cost_basis": "reserved_allowance",
    }
    authentication = auth_status(provider)
    if not authentication["ok"]:
        result["error"] = f"{provider} subscription authentication required"
        result["error_kind"] = "authentication"
        if authentication.get("error_kind"):
            result["error_kind"] = authentication["error_kind"]
        return result

    reservation = ledger.reserve(max_cost, f"{purpose}:{provider}:{model}") if ledger is not None else None
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
            if error and re.search(
                r"usage[_ ]limit|rate[_ ]limit|quota[_ ]exceeded|insufficient_quota",
                completed.stdout + completed.stderr,
                re.I,
            ):
                result["error"] = f"{provider} subscription usage limit reached"
                result["error_kind"] = "usage_limit"
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
            ledger.settle(reservation, cost=result["cost"], usage=result["usage"])
    return result
