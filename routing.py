"""Durable model routing with explicit provenance, retry limits and breakers."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from pathlib import Path
import time
import uuid

from model_registry import DEFAULT_CHAIN, model_spec, policy_chain
from research_state import FileLock, atomic_json, read_json


SCHEMA_VERSION = 1
RETRYABLE = frozenset({"timeout", "rate_limited_unclassified", "capacity"})
MODEL_BREAKERS = frozenset({"usage_limit", "quota_exhausted", "model_unavailable"})
FAMILY_BREAKERS = frozenset({"authentication", "unavailable"})
FALLBACK_ERRORS = RETRYABLE | MODEL_BREAKERS | FAMILY_BREAKERS
FALLBACK_ERRORS = FALLBACK_ERRORS | {"infrastructure_error"}


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_state(disabled_families=()) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "disabled_families": sorted(set(disabled_families)),
        "model_breakers": {},
        "family_breakers": {},
        "attempts": [],
    }


def _pid_alive(pid):
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.CloseHandle.restype = ctypes.c_int
            process = kernel32.OpenProcess(0x1000, False, int(pid))
            if not process:
                kernel32.GetLastError.restype = ctypes.c_ulong
                return kernel32.GetLastError() != 87
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(process, ctypes.byref(code)):
                    return True
                return code.value == 259
            finally:
                kernel32.CloseHandle(process)
        except (AttributeError, OSError, TypeError, ValueError):
            return True
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


class RoutingJournal:
    """Process-safe per-night journal shared by generation, critique and retro."""

    def __init__(self, path, disabled_families=()):
        self.path = Path(path)
        self.lock_path = Path(str(self.path) + ".lock")
        configured = sorted(set(disabled_families))
        with FileLock(self.lock_path):
            state = read_json(self.path, None)
            if state is None:
                state = _new_state(configured)
                atomic_json(self.path, state)
            self._validate(state)
            if sorted(set(state.get("disabled_families", []))) != configured:
                raise ValueError("resume must preserve disabled routing families")

    @staticmethod
    def _validate(state):
        if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("routing journal has an unsupported schema")
        if not isinstance(state.get("attempts"), list):
            raise ValueError("routing journal attempts must be a list")
        if not isinstance(state.get("model_breakers"), dict) or not isinstance(state.get("family_breakers"), dict):
            raise ValueError("routing journal breakers must be objects")

    @property
    def state(self):
        with FileLock(self.lock_path):
            state = read_json(self.path)
            self._validate(state)
            return state

    def _mutate(self, update):
        with FileLock(self.lock_path):
            state = read_json(self.path)
            self._validate(state)
            value = update(state)
            atomic_json(self.path, state)
            return value

    def append(self, attempt):
        record = dict(attempt)
        self._mutate(lambda state: state["attempts"].append(record))
        return record

    def update(self, attempt_id, **changes):
        def update(state):
            attempt = next((item for item in reversed(state["attempts"]) if item.get("attempt_id") == attempt_id), None)
            if attempt is None:
                raise KeyError(f"unknown routing attempt {attempt_id}")
            attempt.update(changes)
            return dict(attempt)

        return self._mutate(update)

    def open_breaker(self, spec, error_kind):
        record = {"reason": error_kind, "opened_at": _iso()}

        def update(state):
            if error_kind in FAMILY_BREAKERS:
                state["family_breakers"][spec["family"]] = record
            elif error_kind in MODEL_BREAKERS or error_kind in RETRYABLE:
                state["model_breakers"][spec["alias"]] = record

        self._mutate(update)

    def recover_interrupted(self, scope=None):
        """Fail closed only for orphaned attempts; live processes retain ownership."""
        recovered = []

        def update(state):
            for attempt in state["attempts"]:
                if attempt.get("status") != "started" or (scope and attempt.get("scope") != scope):
                    continue
                if _pid_alive(attempt.get("owner_pid")):
                    continue
                attempt.update(
                    status="uncertain",
                    error_kind="interrupted_unknown",
                    retryable=False,
                    charged_allowance=float(attempt.get("reserved_allowance") or 0.0),
                    accounting_disposition="reserved_allowance_preserved_after_interruption",
                    finished_at=_iso(),
                )
                recovered.append(dict(attempt))

        self._mutate(update)
        return recovered


def _error_response(requested, error_kind, message, attempts, logical_call_id):
    return {
        "text": "",
        "code": None,
        "idea": None,
        "provider": requested["transport"],
        "family": requested["family"],
        "model": requested["model"],
        "cost": None,
        "usage": {},
        "error": message,
        "error_kind": error_kind,
        "billing_mode": "subscription",
        "cost_basis": "reserved_allowance",
        "_routing_attempts": attempts,
        "_logical_call_id": logical_call_id,
    }


def route_call(
    prompt,
    *,
    requested_alias,
    policy="scheduled",
    chain=DEFAULT_CHAIN,
    disabled_families=(),
    ledger,
    max_cost,
    purpose,
    call_fn,
    journal: RoutingJournal,
    deadline=None,
    checkpoint=None,
    scope=None,
    legacy_provider_callback=False,
    allowance_remaining=None,
    retry_delay=1.0,
    sleep_fn=time.sleep,
):
    """Execute one logical call and journal every started/finished physical attempt."""
    requested = model_spec(requested_alias)
    candidates = policy_chain(policy, chain, requested_alias)
    logical_call_id = uuid.uuid4().hex
    disabled = set(disabled_families) | set(journal.state.get("disabled_families", []))
    if not candidates:
        return _error_response(
            requested, "routing_unavailable", "routing policy selects no configured model", [], logical_call_id
        )
    attempts = []
    last = None
    physical_index = 0
    charged_this_call = 0.0
    for fallback_depth, alias in enumerate(candidates):
        spec = model_spec(alias)
        state = journal.state
        blocked = None
        if spec["family"] in disabled:
            blocked = {"reason": "family_disabled", "source": "configuration"}
        elif spec["family"] in state["family_breakers"]:
            blocked = state["family_breakers"][spec["family"]]
        elif alias in state["model_breakers"]:
            blocked = state["model_breakers"][alias]
        common = {
            "logical_call_id": logical_call_id,
            "scope": scope,
            "purpose": purpose,
            "strategy": policy,
            "requested_alias": requested_alias,
            "requested_family": requested["family"],
            "requested_model": requested["model"],
            "family": spec["family"],
            "model_alias": alias,
            "model": spec["model"],
            "fallback_depth": fallback_depth,
        }
        if blocked:
            item = {
                **common,
                "attempt_id": uuid.uuid4().hex,
                "attempt_index": None,
                "physical": False,
                "selection_reason": "breaker_or_configuration",
                "started_at": None,
                "finished_at": _iso(),
                "status": "skipped",
                "error_kind": blocked.get("reason", "routing_unavailable"),
                "root_reason": blocked,
                "retryable": False,
                "reserved_allowance": 0.0,
                "charged_allowance": 0.0,
                "reported_cost": None,
                "elapsed_seconds": 0.0,
                "usage": {},
            }
            attempts.append(journal.append(item))
            if checkpoint:
                checkpoint()
            continue
        for same_model_try in range(2):
            if deadline is not None and time.time() >= deadline:
                return _error_response(
                    requested, "timeout", "research deadline reached before routed call", attempts, logical_call_id
                )
            shared_remaining = float(getattr(ledger, "remaining", math.inf)) if ledger is not None else math.inf
            invocation_remaining = (
                float(allowance_remaining()) - charged_this_call if allowance_remaining is not None else math.inf
            )
            if min(shared_remaining, invocation_remaining) + 1e-9 < float(max_cost):
                return _error_response(
                    requested,
                    "budget_exhausted",
                    "insufficient allowance for routed attempt",
                    attempts,
                    logical_call_id,
                )
            physical_index += 1
            started_mono = time.monotonic()
            item = {
                **common,
                "attempt_id": uuid.uuid4().hex,
                "attempt_index": physical_index,
                "physical": True,
                "owner_pid": os.getpid(),
                "selection_reason": "requested"
                if fallback_depth == 0 and same_model_try == 0
                else ("transient_retry" if same_model_try else "infrastructure_fallback"),
                "started_at": _iso(),
                "finished_at": None,
                "status": "started",
                "error_kind": None,
                "retryable": False,
                "reserved_allowance": float(max_cost),
                "charged_allowance": None,
                "reported_cost": None,
                "elapsed_seconds": None,
                "usage": {},
            }
            journal.append(item)
            if checkpoint:
                checkpoint()
            try:
                response = call_fn(
                    prompt,
                    provider=spec["transport"] if legacy_provider_callback else spec["family"],
                    model=spec["model"],
                    timeout=(900 if deadline is None else max(0.001, min(900, deadline - time.time()))),
                    max_cost=max_cost,
                    ledger=ledger,
                    purpose=purpose,
                )
            except Exception:
                charged = float(max_cost)
                charged_this_call += charged
                journal.update(
                    item["attempt_id"],
                    status="failed",
                    finished_at=_iso(),
                    error_kind="provider_exception",
                    retryable=False,
                    charged_allowance=charged,
                    elapsed_seconds=round(time.monotonic() - started_mono, 6),
                )
                if checkpoint:
                    checkpoint()
                raise
            error_kind = response.get("error_kind") if response.get("error") else None
            status = "failed" if response.get("error") else "completed"
            retryable = error_kind in RETRYABLE and same_model_try == 0
            if response.get("_accounting_charged") is not None:
                charged = float(response["_accounting_charged"])
            elif error_kind == "authentication":
                charged = 0.0
            else:
                charged = response.get("cost") if response.get("cost") is not None else float(max_cost)
            charged_this_call += charged
            item = journal.update(
                item["attempt_id"],
                status=status,
                finished_at=_iso(),
                error_kind=error_kind,
                retryable=retryable,
                reserved_allowance=float(response.get("_accounting_reserved", max_cost)),
                charged_allowance=charged,
                reported_cost=response.get("cost"),
                elapsed_seconds=round(time.monotonic() - started_mono, 6),
                usage=response.get("usage") or {},
                diagnostic_path=response.get("diagnostic_path"),
            )
            attempts.append(item)
            if checkpoint:
                checkpoint()
            response = dict(response)
            response.update(
                family=spec["family"],
                model=spec["model"],
                provider=spec["transport"],
                _routing_attempts=list(attempts),
                _logical_call_id=logical_call_id,
            )
            last = response
            if not response.get("error"):
                return response
            if error_kind not in FALLBACK_ERRORS:
                return response
            if retryable:
                delay = max(0.0, float(retry_delay))
                if deadline is not None and time.time() + delay >= deadline:
                    return response
                if delay:
                    sleep_fn(delay)
                continue
            journal.open_breaker(spec, error_kind)
            break
    if last is not None:
        last["_routing_attempts"] = attempts
        return last
    return _error_response(
        requested, "routing_unavailable", "all configured routes are unavailable", attempts, logical_call_id
    )


def routing_summary(
    attempts,
    *,
    requested_arm,
    mode,
    configured_chain=(),
    disabled_families=(),
    explicit_override=False,
    model_override=False,
):
    """Build the stable per-stage routing summary consumed by evidence and reports."""
    scoped = [dict(item) for item in attempts]
    completed = [item for item in scoped if item.get("status") == "completed"]
    actual_families = sorted({item.get("family") for item in completed if item.get("family")})
    actual_models = sorted({item.get("model") for item in completed if item.get("model")})
    requested_aliases = ("fable", "astra") if requested_arm == "paired" else (requested_arm,)
    requested_specs = [model_spec(alias) for alias in requested_aliases if alias in {"fable", "astra"}]
    reasons = []
    if explicit_override:
        reasons.append("routing_override")
    if model_override:
        reasons.append("model_override")
    if not completed:
        reasons.append("no_completed_model_call")
    if any(item.get("fallback_depth", 0) > 0 and item.get("physical") is True for item in scoped):
        reasons.append("capacity_or_infrastructure_fallback")
    if any(item.get("status") == "uncertain" for item in scoped):
        reasons.append("uncertain_interrupted_attempt")
    if requested_arm == "paired" or mode == "paired":
        generation = [item for item in completed if item.get("purpose") == "generation"]
        if {item.get("requested_family") for item in generation} != {"anthropic", "openai"} or {
            item.get("family") for item in generation
        } != {"anthropic", "openai"}:
            reasons.append("paired_families_incomplete")
    reasons = list(dict.fromkeys(reasons))
    by_model = {}
    by_family = {}
    for item in [item for item in scoped if item.get("physical") is True]:
        model = item.get("model")
        family = item.get("family")
        if model:
            by_model[model] = by_model.get(model, 0) + 1
        if family:
            by_family[family] = by_family.get(family, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "requested_arm": requested_arm,
        "mode": mode,
        "formal_trial_eligible": not reasons,
        "ineligibility_reasons": reasons,
        "requested_family": "mixed"
        if len({item["family"] for item in requested_specs}) > 1
        else (requested_specs[0]["family"] if requested_specs else None),
        "requested_model": "mixed"
        if len(requested_specs) > 1
        else (requested_specs[0]["model"] if requested_specs else None),
        "actual_family": "mixed" if len(actual_families) > 1 else (actual_families[0] if actual_families else None),
        "actual_model": "mixed" if len(actual_models) > 1 else (actual_models[0] if actual_models else None),
        "fallback_used": any(item.get("fallback_depth", 0) > 0 and item.get("physical") is True for item in scoped),
        "degraded": bool(reasons),
        "configured_chain": list(configured_chain),
        "disabled_families": list(disabled_families),
        "attempts": scoped,
        "by_model": by_model,
        "by_family": by_family,
    }
