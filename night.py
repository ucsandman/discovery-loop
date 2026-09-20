"""Bounded, resumable nightly research with local-only evidence output.

The canonical path shares one deadline and budget ledger across research,
review and retrospective stages. It never invokes publication or email.
Legacy ``publish_slot`` and ``retro_slot`` call signatures remain available
for existing callers, but ``main`` does not use the publisher.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from loop import (
    DEFAULT_DEVELOPMENT_SEEDS,
    DEFAULT_POSTMORTEM_BUDGET,
    DEFAULT_POSTMORTEM_LIMIT,
    DEFAULT_SCREEN_FRACTION,
)
from model_registry import VALID_ROUTING_POLICIES, model_spec, policy_chain, routing_config
from research_state import BudgetLedger, FileLock, atomic_json, paused, read_json

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(HERE, "night.json")
STATUS = os.path.join(HERE, "runs", "night-status.json")
ROOT = Path(HERE)
LOCK = ROOT / "runs" / "night.lock"
SUCCESS_STATUSES = {"completed"}


def limit_cpu(fraction=0.5):
    """Pin this process (and every child it spawns) to a fraction of the logical CPUs at below-normal priority.

    Two hard power-offs on 2026-09-05 happened while the night ran all-core alongside a game and coding agents.
    Solvers and CLIs inherit the affinity mask and priority class, so the whole night stays under the cap.
    Returns a small record for the status file; never raises.
    """
    total = os.cpu_count() or 1
    allowed = max(1, int(total * fraction))
    record = {"logical_cpus": total, "allowed_cpus": allowed, "fraction": fraction, "applied": False}
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetProcessAffinityMask.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
            kernel32.SetProcessAffinityMask.restype = ctypes.c_int
            kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            kernel32.SetPriorityClass.restype = ctypes.c_int
            handle = kernel32.GetCurrentProcess()
            mask = (1 << allowed) - 1
            record["applied"] = bool(kernel32.SetProcessAffinityMask(handle, mask))
            if not record["applied"]:
                record["error"] = f"SetProcessAffinityMask failed: {ctypes.get_last_error()}"
            kernel32.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
        elif hasattr(os, "sched_setaffinity"):
            os.sched_setaffinity(0, set(range(allowed)))
            os.nice(5)
            record["applied"] = True
    except (OSError, AttributeError, ValueError) as exc:
        record["error"] = str(exc)[:200]
    return record


def layout(problem):
    suf = "" if problem == "circle_packing" else "-" + problem
    return os.path.join(HERE, "best" + suf), os.path.join(HERE, "runs" + suf)


def retro_slot(problem, since_iter):
    """One model call after the slot: append what worked, what didn't, lessons and five Next directions to
    docs/retro/<problem>.md so tomorrow's prompt starts from tonight's result instead of repeating it. Synchronous
    (a few minutes at most) so the retro exists before publish_slot pushes the repo. Output: runs-<P>/retro.log."""
    _, runs = layout(problem)
    os.makedirs(runs, exist_ok=True)
    with open(os.path.join(runs, "retro.log"), "a", encoding="utf-8") as lf:
        subprocess.run(
            [sys.executable, os.path.join(HERE, "retro.py"), "--problem", problem, "--since-iter", str(since_iter)],
            cwd=HERE,
            stdout=lf,
            stderr=subprocess.STDOUT,
            timeout=1200,
        )


def publish_slot(problem):
    """One email per slot: publish.py re-verifies every winner the slot pushed and requests ONE approval for all
    of them (Wes, 2026-09-04). Detached, so its 24h approval wait never delays the next slot; a crashed slot still
    submits what it won. Output: runs-<P>/publish.log."""
    _, runs = layout(problem)
    os.makedirs(runs, exist_ok=True)
    subprocess.Popen(
        [sys.executable, os.path.join(HERE, "publish.py"), "--problem", problem],
        cwd=HERE,
        stdout=open(os.path.join(runs, "publish.log"), "a"),
        stderr=subprocess.STDOUT,
    )


def _iso(timestamp=None):
    value = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp is not None else datetime.now(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def load_schedule(path=SCHEDULE):
    """Load and reject schedules that could escape the agreed experiment."""
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema_version") != 2:
        raise ValueError("night schedule must use schema_version 2")
    arc = config.get("arc", {})
    if not isinstance(arc, dict) or not isinstance(arc.get("enabled", False), bool):
        raise ValueError("arc schedule settings must be an object with a boolean enabled flag")
    source_checkout = arc.get("source_checkout", "../arc-agi-n")
    if not isinstance(source_checkout, str) or not source_checkout.strip() or "\x00" in source_checkout:
        raise ValueError("arc source_checkout must be a nonempty path")
    night = config.get("night", {})
    # Schema-2 schedules predate routing. Their historical meaning is the
    # scheduled trial policy over the canonical default chain, so normalize in
    # memory without requiring a schedule migration.
    night["routing"] = routing_config(config)
    if not 0 < float(night.get("budget_usd", 0)) <= 130:
        raise ValueError("night API-equivalent allowance must be in (0, 130]")
    if not 1 <= int(night.get("deadline_minutes", 0)) <= 720:
        raise ValueError("night deadline_minutes must be in [1, 720]")
    modes = {"fable", "astra", "paired"}
    caps = night.get("provider_caps_usd", {})
    if set(caps) != modes or any(not 0 <= float(value) <= 90 for value in caps.values()):
        raise ValueError("provider caps must define fable, astra and paired in [0, 90] API-equivalent units")
    cycle = config.get("trial", {}).get("cycle", [])
    if len(cycle) != 14:
        raise ValueError("trial cycle must contain exactly 14 nights")
    for entry in cycle:
        if entry.get("cvrp") not in modes or entry.get("miplib_heur") not in modes:
            raise ValueError("trial providers must be fable, astra, or paired")
        if sorted(entry.get("order", [])) != ["cvrp", "miplib_heur"]:
            raise ValueError("each trial night must order cvrp and miplib_heur once")
    slots = config.get("slots", [])
    problems = [slot.get("problem") for slot in slots]
    if len(set(problems)) != len(problems):
        raise ValueError("each problem may appear in at most one slot")
    research = {slot.get("problem") for slot in slots if slot.get("kind") == "research"}
    if not {"cvrp", "miplib_heur"} <= research:
        raise ValueError("research slots must include cvrp and miplib_heur")
    if any(
        slot.get("kind") == "research" and slot.get("provider") is not None and slot["provider"] not in modes
        for slot in slots
    ):
        raise ValueError("configured slot providers must be fable, astra, or paired")
    validation = [slot for slot in slots if slot.get("problem") == "pglib_opf"]
    if len(validation) != 1 or validation[0].get("kind") != "validation":
        raise ValueError("pglib_opf must appear exactly once and validation-only")
    if any(float(slot.get("minutes", 0)) <= 0 for slot in slots):
        raise ValueError("slot minutes must be positive")
    if sum(float(slot["minutes"]) for slot in slots) > float(night["deadline_minutes"]):
        raise ValueError("slot minutes exceed the night deadline")
    for slot in slots:
        slot_budget = float(slot.get("slot_budget_usd", 0))
        per_call = float(slot.get("per_call_budget_usd", 0))
        if slot["kind"] == "research" and not 0 < per_call <= slot_budget:
            raise ValueError("research per-call budget must be positive and within its slot cap")
        if slot["kind"] == "research" and (
            float(slot.get("research_minutes", 0)) <= 0
            or float(slot.get("retro_minutes", 0)) <= 0
            or float(slot["research_minutes"]) + float(slot["retro_minutes"]) > float(slot["minutes"])
        ):
            raise ValueError("research and retro minutes must be positive and fit inside the slot")
        if slot["kind"] == "validation" and (slot_budget != 0 or per_call != 0):
            raise ValueError("validation-only slots cannot have model budget")
    configured = sum(float(slot.get("slot_budget_usd", 0)) + float(slot.get("retro_budget_usd", 0)) for slot in slots)
    if configured > float(night["budget_usd"]):
        raise ValueError("slot call and retro caps exceed the night budget")
    prizes = _prize_block(config)
    if prizes is not None:
        _validate_prize_block(prizes, config, slots, modes, configured)
    return config


def _prize_block(config):
    """Return the nightly prize block only when it is enabled, else None.

    An absent or disabled block is the committed default: nothing about the night's plan,
    budget or commands changes, and the block's numbers are not validated beyond their types.
    """
    block = config.get("prizes")
    if block is None:
        return None
    if not isinstance(block, dict) or not isinstance(block.get("enabled", False), bool):
        raise ValueError("night prize settings must be an object with a boolean enabled flag")
    return block if block.get("enabled", False) else None


def _validate_prize_block(block, config, slots, modes, configured_usd):
    """An enabled prize slot must fit inside the same deadline and budget ledger as every other slot."""
    minutes = float(block.get("minutes", 0))
    research_minutes = float(block.get("research_minutes", 0))
    retro_minutes = float(block.get("retro_minutes", 0))
    if minutes <= 0 or research_minutes <= 0 or retro_minutes <= 0 or research_minutes + retro_minutes > minutes:
        raise ValueError("prize research and retro minutes must be positive and fit inside the prize slot")
    slot_budget = float(block.get("slot_budget_usd", 0))
    per_call = float(block.get("per_call_budget_usd", 0))
    retro_budget = float(block.get("retro_budget_usd", 0))
    if not 0 < per_call <= slot_budget:
        raise ValueError("prize per-call budget must be positive and within its slot cap")
    if retro_budget < 0:
        raise ValueError("prize retro budget cannot be negative")
    if block.get("provider", "paired") not in modes:
        raise ValueError("configured prize provider must be fable, astra, or paired")
    for name in ("moonshot_share", "max_share"):
        if not 0 <= float(block.get(name, 0.2)) <= 1:
            raise ValueError("prize moonshot_share and max_share must be fractions in [0, 1]")
    deadline = float(config["night"]["deadline_minutes"])
    planned_minutes = sum(float(slot["minutes"]) for slot in slots) + minutes
    if planned_minutes > deadline:
        raise ValueError(
            "the prize slot pushes the night past its deadline: "
            f"{planned_minutes:g} planned minutes against a {deadline:g}-minute deadline, "
            f"{planned_minutes - deadline:g} minutes over; shorten a slot by that much"
        )
    budget = float(config["night"]["budget_usd"])
    planned_usd = configured_usd + slot_budget + retro_budget
    if planned_usd > budget:
        raise ValueError(
            "prize slot and retro caps exceed the night budget: "
            f"${planned_usd:.2f} planned against a ${budget:.2f} budget, "
            f"${planned_usd - budget:.2f} over; lower a slot budget by that much"
        )


def trial_for(config, run_id):
    anchor = date.fromisoformat(config["trial"]["anchor_date"])
    current = _logical_run_date(run_id)
    index = (current - anchor).days % 14
    return index, config["trial"]["cycle"][index]


def planned_slots(config, run_id):
    """Resolve the counterbalanced providers and fixed validation tail."""
    index, assignment = trial_for(config, run_id)
    by_problem = {slot["problem"]: dict(slot) for slot in config["slots"]}
    ordered = []
    for problem in assignment["order"]:
        slot = by_problem[problem]
        slot["provider"] = assignment[problem]
        slot["trial_index"] = index
        slot["effective_slot_budget_usd"] = min(
            float(slot["slot_budget_usd"]),
            float(config["night"]["provider_caps_usd"][slot["provider"]]),
        )
        ordered.append(slot)
    # Research slots outside the trial keep their configured provider and run
    # in information-gain order before the validation tail.
    extras = [
        slot
        for problem, slot in by_problem.items()
        if problem not in assignment["order"] and problem != "pglib_opf" and slot.get("kind") == "research"
    ]
    try:
        from scripts.schedule_night import score_problem

        extras.sort(key=lambda slot: score_problem(slot["problem"])["score"], reverse=True)
    except Exception:
        pass  # ordering is advisory; never break the night's plan
    for slot in extras:
        slot["provider"] = slot.get("provider") or "paired"
        slot["effective_slot_budget_usd"] = min(
            float(slot["slot_budget_usd"]),
            float(config["night"]["provider_caps_usd"][slot["provider"]]),
        )
        ordered.append(slot)
    # PGLib is confirmation-only and deliberately has no generation provider.
    ordered.append(by_problem["pglib_opf"])
    return ordered


def schedule_advice(config, slots):
    """Advisory information-gain allocation for the night's status and morning report."""
    try:
        from scripts.schedule_night import allocate
    except ImportError:
        return None
    try:
        return allocate(
            float(config["night"]["deadline_minutes"]) * 60.0,
            [slot["problem"] for slot in slots],
        )
    except Exception:
        return None


def _routing_families(config, slots):
    """Return only families that can be selected by the configured night."""
    routing = config["night"]["routing"]
    families = set()
    for slot in slots:
        if slot.get("kind") != "research":
            continue
        for alias in policy_chain(routing["policy"], routing["chain"], slot["provider"]):
            family = model_spec(alias)["family"]
            if family not in routing["disabled_families"]:
                families.add(family)
    return families


def analyst_provider(generation_provider, run_id):
    """Use the other model as analyst; alternate paired trials by date."""
    if generation_provider == "fable":
        return "astra"
    if generation_provider == "astra":
        return "fable"
    return "fable" if _logical_run_date(run_id).toordinal() % 2 == 0 else "astra"


def _logical_run_date(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-scheduled)?", run_id):
        raise ValueError("night run id must be YYYY-MM-DD or YYYY-MM-DD-scheduled")
    return date.fromisoformat(run_id[:10])


def _stop_process_tree(process):
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
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _run_bounded(command, logfile, deadline, heartbeat_seconds, heartbeat):
    """Run until the actual remaining deadline while checking pause state."""
    logfile.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONUTF8="1")
    environment.setdefault("OMP_NUM_THREADS", "2")
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with logfile.open("a", encoding="utf-8") as output:
        try:
            process = subprocess.Popen(
                command,
                cwd=HERE,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=environment,
                **options,
            )
        except OSError:
            return None, "failed"
        try:
            while process.poll() is None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    _stop_process_tree(process)
                    return process.returncode, "timed_out"
                if paused(HERE):
                    _stop_process_tree(process)
                    return process.returncode, "paused"
                heartbeat()
                try:
                    process.wait(timeout=min(float(heartbeat_seconds), remaining))
                except subprocess.TimeoutExpired:
                    continue
            return process.returncode, "exited"
        except KeyboardInterrupt:
            _stop_process_tree(process)
            raise


def _count_collection(value):
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("count", "evaluations", "targets", "results"):
            if key in value:
                nested = value[key]
                return int(nested) if isinstance(nested, (int, float)) else _count_collection(nested)
    return 0


def evidence_work_count(evidence):
    """Count observable calls/evaluations so zero-work cannot be success."""
    usage = evidence.get("usage") or {}
    calls = sum(
        int(usage.get(key, 0) or 0)
        for key in ("calls", "model_calls", "generation_calls", "review_calls")
        if isinstance(usage.get(key, 0), (int, float))
    )
    return calls + _count_collection(evidence.get("development")) + _count_collection(evidence.get("confirmation"))


def _write_status(status, checkpoint):
    status["updated_at"] = _iso()
    atomic_json(STATUS, status)
    atomic_json(checkpoint, status)


def _preflight(config, slots, provider_check=None, sandbox_check=None):
    """Check Docker and only subscription families reachable by this night."""
    if provider_check is None:
        from providers import preflight as provider_check
    if sandbox_check is None:
        from isolation import preflight as sandbox_check

    transports = {"anthropic": "fable", "openai": "astra"}
    required_families = _routing_families(config, slots)
    providers = provider_check(providers=tuple(transports[family] for family in sorted(required_families)))
    sandbox = sandbox_check(root=HERE)
    details = providers.get("details", {}) if isinstance(providers, dict) else {}
    available = {family for family in required_families if details.get(transports[family], {}).get("ok") is True}
    # Lightweight test doubles and older preflight integrations returned only
    # aggregate success.  Preserve that contract while real preflight reports
    # per-family availability.
    if providers.get("ok") is True and not details:
        available = set(required_families)
    return {
        "ok": bool(available) and sandbox.get("ok") is True,
        "providers": providers,
        "sandbox": sandbox,
        "required_families": sorted(required_families),
        "available_families": sorted(available),
    }


PREFLIGHT_RETRY_SECONDS = 300.0
PREFLIGHT_RETRY_WINDOW_SECONDS = 1800.0


def _preflight_with_retry(
    config,
    slots,
    *,
    provider_check=None,
    sandbox_check=None,
    deadline=None,
    on_wait=None,
    sleep_fn=time.sleep,
    clock=time.time,
):
    """Re-probe a failed Docker sandbox every 5 minutes for 30 minutes before giving the night up.

    A Docker engine still booting after a host reboot used to end the night on the first probe (2026-09-19:
    one failed probe at 02:00, no work recorded, eight hours of deadline left). A provider that is unreachable
    at the start is an authentication problem and needs a person, so that failure is never re-probed; a
    subscription window that closes mid-night is handled by the routing breakers instead.
    """
    window_minutes = config.get("night", {}).get("preflight_retry_minutes", PREFLIGHT_RETRY_WINDOW_SECONDS / 60)
    window_end = clock() + 60.0 * float(window_minutes)
    attempts = 0
    while True:
        checks = _preflight(config, slots, provider_check=provider_check, sandbox_check=sandbox_check)
        attempts += 1
        checks["attempts"] = attempts
        if checks["ok"] or checks["sandbox"].get("ok") is True:
            return checks
        next_probe = clock() + PREFLIGHT_RETRY_SECONDS
        if next_probe > window_end or (deadline is not None and next_probe > deadline):
            return checks
        if on_wait:
            on_wait(checks)
        sleep_fn(PREFLIGHT_RETRY_SECONDS)


def _routing_command_args(routing, journal_path, *, override=False, deadline=None):
    command = ["--routing", routing["policy"], "--model-chain", *routing["chain"]]
    for family in routing["disabled_families"]:
        command.extend(("--disable-family", family))
    command.extend(("--routing-journal", str(journal_path)))
    if deadline is not None:
        command.extend(("--deadline-epoch", str(deadline)))
    if override:
        command.append("--routing-override")
    return command


def _research_command(
    slot,
    run_id,
    ledger_path,
    evidence_root,
    minutes,
    *,
    routing=None,
    journal_path=None,
    routing_override=False,
    deadline=None,
    mission_path=None,
):
    command = [
        sys.executable,
        "-u",
        str(ROOT / "loop.py"),
        "--problem",
        slot["problem"],
        "--provider",
        slot.get("provider", "fable"),
        "--run-id",
        run_id,
        "--ledger",
        str(ledger_path),
        "--call-budget",
        str(slot.get("per_call_budget_usd", 0)),
        "--budget",
        str(slot.get("effective_slot_budget_usd", slot.get("slot_budget_usd", 0))),
        "--seed-count",
        str(slot.get("seed_count", 1)),
        "--development-seeds",
        str(slot.get("development_seeds", DEFAULT_DEVELOPMENT_SEEDS)),
        "--postmortem-limit",
        str(slot.get("postmortem_limit", DEFAULT_POSTMORTEM_LIMIT)),
        "--postmortem-budget",
        str(slot.get("postmortem_budget", DEFAULT_POSTMORTEM_BUDGET)),
        "--min-effect",
        str(slot.get("min_effect", 0.01)),
        "--evidence-root",
        str(evidence_root),
        "--iters",
        str(slot.get("iters", 1)),
        "--time",
        str(slot.get("time_per_target", 60)),
        "--workers",
        str(slot.get("workers", 1)),
        "--wall-minutes",
        str(max(0.01, minutes)),
        "--max-generation-failures",
        str(slot.get("max_generation_failures", 2)),
        "--screen-fraction",
        str(slot.get("screen_fraction", DEFAULT_SCREEN_FRACTION)),
        "--generation-mode",
        str(slot.get("generation_mode", "full")),
        "--no-publish",
    ]
    if routing is not None and journal_path is not None:
        command.extend(_routing_command_args(routing, journal_path, override=routing_override, deadline=deadline))
    if mission_path is not None:
        command.extend(("--mission", str(mission_path)))
    if slot["kind"] == "validation":
        command.append("--eval-only")
    return command


def _retro_command(
    slot, run_id, ledger_path, evidence_root, *, routing=None, journal_path=None, routing_override=False, deadline=None
):
    command = [
        sys.executable,
        "-u",
        str(ROOT / "retro.py"),
        "--problem",
        slot["problem"],
        "--run-id",
        run_id,
        "--evidence-root",
        str(evidence_root),
        "--ledger",
        str(ledger_path),
        "--provider",
        analyst_provider(slot["provider"], run_id),
        "--call-budget",
        str(slot.get("retro_budget_usd", 0)),
    ]
    if routing is not None and journal_path is not None:
        command.extend(_routing_command_args(routing, journal_path, override=routing_override, deadline=deadline))
    return command


def _new_status(
    config, run_id, deadline, ledger_path, routing, routing_override, *, invocation_kind="manual", scheduled_run_id=None
):
    index, assignment = trial_for(config, run_id)
    status = {
        "schema_version": 2,
        "run_id": run_id,
        "status": "running",
        "started_at": _iso(),
        "updated_at": _iso(),
        "deadline": _iso(deadline),
        "budget_limit_api_equivalent": float(config["night"]["budget_usd"]),
        "budget_used_api_equivalent": 0.0,
        "budget_accounting": config["night"].get("budget_accounting"),
        "ledger": str(Path(ledger_path).relative_to(ROOT)).replace("\\", "/"),
        "trial": {"index": index, "assignment": assignment},
        "routing": {**routing, "override": bool(routing_override)},
        "slots": [],
        "limitations": [],
    }
    if invocation_kind == "scheduled":
        status["invocation_kind"] = "scheduled"
        status["scheduled_run_id"] = scheduled_run_id
    return status


def _prepare_arc(config, slots, run_id):
    arc = config.get("arc", {})
    if arc.get("enabled") is not True:
        return {}, {"status": "disabled", "selected_missions": []}
    from arc_catalogue import DEFAULT_STATE, load_control, mission_selection, refresh_catalogue

    source = Path(arc.get("source_checkout", "../arc-agi-n"))
    if not source.is_absolute():
        source = ROOT / source
    refreshed = refresh_catalogue(source, DEFAULT_STATE)
    snapshot = refreshed["snapshot"]
    control = load_control(DEFAULT_STATE, snapshot)
    selection = mission_selection(snapshot, control, slots)
    plan = selection["missions"]
    summary = {
        "status": refreshed["refresh"]["status"],
        "attempted_at": refreshed["refresh"].get("attempted_at"),
        "catalogue_hash": refreshed["refresh"].get("catalogue_hash"),
        "revision": refreshed["refresh"].get("revision"),
        "problem_count": refreshed["refresh"].get("problem_count", 0),
        "refresh_error": refreshed["refresh"].get("error"),
        "selected_missions": [mission["source_problem_id"] for mission in plan.values()],
        "requested_next": control.get("next_id"),
        "disabled_slot_ids": selection["skip_slot_ids"],
        "run_id": run_id,
    }
    return plan, summary


def _promotion_threshold(plugin):
    """The bound plugin's ``PRIZE['promotion_threshold']`` floors, or {} when it declares none."""
    try:
        from problem_loader import load_problem

        prize = getattr(load_problem(plugin), "PRIZE", None)
    except (ImportError, ValueError, AttributeError, SyntaxError):
        return {}
    threshold = prize.get("promotion_threshold") if isinstance(prize, dict) else None
    return threshold if isinstance(threshold, dict) else {}


def _prize_slot(config, block, allocation, binding, prize_id):
    """Build one bounded research slot for a prize, or (None, reason) when a ceiling is exceeded.

    ``PRIZE_BINDINGS`` ceilings are refused rather than clamped: a block asking for more minutes
    or a larger per-call cap than the reviewed binding allows is a configuration error, and
    silently shrinking it would hide that (arc_catalogue's mission_plan drops such slots with no
    trace at all, which is hard to diagnose).
    """
    plugin = binding["plugin"]
    minutes = float(block.get("minutes", 0.0))
    max_minutes = float(binding.get("max_minutes", minutes))
    if minutes > max_minutes:
        return None, f"the block asks for {minutes:g} minutes; the {plugin} binding allows {max_minutes:g}"
    slot_budget = round(float(allocation.get("usd", 0.0)), 2)
    if slot_budget <= 0:
        return None, "the allocation left this prize no allowance"
    max_slot = float(binding.get("max_slot_budget_usd", slot_budget))
    if slot_budget > max_slot:
        return None, f"the allocation of ${slot_budget:.2f} exceeds the {plugin} binding cap of ${max_slot:.2f}"
    requested_call = float(block.get("per_call_budget_usd", 0.0))
    max_call = float(binding.get("max_per_call_budget_usd", requested_call))
    if requested_call > max_call:
        return (
            None,
            f"the block's ${requested_call:.2f} per-call cap exceeds the {plugin} binding cap of ${max_call:.2f}",
        )
    per_call = round(min(requested_call, slot_budget), 2)
    if per_call <= 0:
        return None, "the prize per-call cap resolves to zero"
    threshold = _promotion_threshold(plugin)
    provider = block.get("provider") or "paired"
    slot = {
        "id": f"prize-{prize_id}",
        "problem": plugin,
        "kind": "research",
        "provider": provider,
        "prize_id": prize_id,
        "minutes": minutes,
        "research_minutes": float(block.get("research_minutes", minutes)),
        "retro_minutes": float(block.get("retro_minutes", 0.0)),
        "slot_budget_usd": slot_budget,
        "effective_slot_budget_usd": round(min(slot_budget, float(config["night"]["provider_caps_usd"][provider])), 2),
        "per_call_budget_usd": per_call,
        "retro_budget_usd": float(block.get("retro_budget_usd", 0.0)),
        "iters": int(block.get("iters", 20)),
        # The plugin's promotion threshold is a floor, never a ceiling: a prize claim has to clear
        # the plugin's own paired bar before anything downstream calls it progress.
        "seed_count": max(int(block.get("seed_count", 1)), int(threshold.get("seed_count", 1) or 1)),
        "development_seeds": int(block.get("development_seeds", DEFAULT_DEVELOPMENT_SEEDS)),
        "min_effect": max(float(block.get("min_effect", 0.0)), float(threshold.get("min_effect", 0.0) or 0.0)),
        "time_per_target": float(block.get("time_per_target", 60)),
        "workers": int(block.get("workers", 2)),
        "max_generation_failures": int(block.get("max_generation_failures", 2)),
    }
    return slot, None


def _prepare_prizes(config, slots, run_id, root=None):
    """Pick at most one prize research slot for tonight. Sibling of :func:`_prepare_arc`.

    Returns ``(extra_slots, summary)``. Nothing here spends, fetches or submits: it re-snapshots
    the local registry, asks ``prize_scoring.allocate`` for a plan over the enabled prizes and the
    measured ``prize_economics`` progress, and turns the top allocation into one bounded slot.
    """
    block = _prize_block(config)
    summary = {
        "status": "disabled",
        "prize_id": None,
        "plugin": None,
        "reason": "the nightly prize block is absent or disabled",
        "allocations": [],
        "notes": [],
        "dropped": [],
        "slot": None,
        "mission": None,
        "run_id": run_id,
    }
    if block is None:
        return [], summary

    import prize_economics
    import prize_scoring
    from prize_registry import PRIZE_BINDINGS, refresh_registry, registry_view

    root = ROOT if root is None else Path(root)
    refresh = refresh_registry(root)["refresh"]
    view = registry_view(root)
    summary.update(
        status="none",
        reason="no enabled prize produced a runnable allocation",
        refresh=refresh.get("status"),
        registry_hash=view.get("registry_hash"),
    )
    prizes = [prize for prize in view.get("prizes", []) if isinstance(prize, dict) and prize.get("enabled")]
    progress_by_id = {}
    for prize in prizes:
        binding = PRIZE_BINDINGS.get(prize.get("id"))
        if binding:
            progress_by_id[prize["id"]] = prize_economics.progress(root, binding["plugin"])
    plan = prize_scoring.allocate(
        prizes,
        allowance_usd=float(block.get("slot_budget_usd", 0.0)),
        minutes=float(block.get("research_minutes", block.get("minutes", 0.0))),
        moonshot_share=float(block.get("moonshot_share", 0.2)),
        max_share=float(block.get("max_share", 0.5)),
        progress_by_id=progress_by_id,
    )
    summary["allocations"] = plan["allocations"]
    summary["notes"] = plan["notes"]

    requested_next = (view.get("control") or {}).get("next_id")
    ordered = sorted(plan["allocations"], key=lambda item: item["prize_id"] != requested_next)
    scheduled = {slot.get("problem") for slot in slots}
    for allocation in ordered:
        prize_id = allocation["prize_id"]
        binding = PRIZE_BINDINGS.get(prize_id)
        if not binding:
            summary["dropped"].append({"prize_id": prize_id, "reason": "no reviewed binding names a local plugin"})
            continue
        if binding["plugin"] in scheduled:
            summary["dropped"].append(
                {"prize_id": prize_id, "reason": f"{binding['plugin']} already has a slot tonight"}
            )
            continue
        slot, reason = _prize_slot(config, block, allocation, binding, prize_id)
        if slot is None:
            summary["dropped"].append({"prize_id": prize_id, "reason": reason})
            continue
        summary.update(
            status="selected",
            prize_id=prize_id,
            plugin=binding["plugin"],
            reason=allocation["reason"],
            slot=slot,
            requested_next=prize_id == requested_next,
            mission={
                "schema_version": 1,
                "prize_id": prize_id,
                "plugin": binding["plugin"],
                "run_id": run_id,
                "registry_hash": view.get("registry_hash"),
                "allocation": allocation,
                "success_criterion": binding["success_criterion"],
                "budget": {
                    "minutes": slot["minutes"],
                    "allowance": slot["effective_slot_budget_usd"],
                    "per_call_allowance": slot["per_call_budget_usd"],
                    "seed_count": slot["seed_count"],
                    "minimum_effect": slot["min_effect"],
                },
                "selected_at": _iso(),
                "note": (
                    "Informational record of why this slot was scheduled. The loop reads no prize text, "
                    "nothing is submitted anywhere, and the real challenge instance is never a target."
                ),
            },
        )
        return [slot], summary
    return [], summary


def _with_prize_slots(slots, extra_slots):
    """Insert prize slots ahead of the validation tail so confirmation still runs last."""
    if not extra_slots:
        return slots
    index = next((position for position, slot in enumerate(slots) if slot.get("kind") == "validation"), len(slots))
    return [*slots[:index], *extra_slots, *slots[index:]]


def run_night(
    config,
    run_id,
    *,
    resume=False,
    dry_run=False,
    now=None,
    deadline_cap=None,
    provider_check=None,
    sandbox_check=None,
    routing_override=False,
    invocation_kind="manual",
    scheduled_run_id=None,
):
    """Run or resume one dated night under one lock, deadline and ledger."""
    _logical_run_date(run_id)
    if invocation_kind not in {"manual", "scheduled"}:
        raise ValueError("invocation_kind must be manual or scheduled")
    if invocation_kind == "scheduled":
        if scheduled_run_id != run_id.removesuffix("-scheduled") or not run_id.endswith("-scheduled"):
            raise ValueError("scheduled runs require matching suffixed and logical run ids")
    started_now = time.time() if now is None else now
    configured_root = Path(config["night"].get("evidence_root", "runs/research"))
    evidence_root = configured_root if configured_root.is_absolute() else ROOT / configured_root
    run_root = evidence_root / run_id
    checkpoint = run_root / "night.json"
    ledger_path = run_root / "budget.json"
    slots = planned_slots(config, run_id)
    prize_slots, prize_summary = _prepare_prizes(config, slots, run_id)
    slots = _with_prize_slots(slots, prize_slots)
    planned_order = [slot["id"] for slot in slots]
    schedule_plan = schedule_advice(config, slots)
    arc_plan, arc_summary = _prepare_arc(config, slots, run_id)
    requested_next = arc_summary.get("requested_next")
    chosen_slot = next(
        (slot_id for slot_id, mission in arc_plan.items() if mission["source_problem_id"] == requested_next), None
    )
    if chosen_slot is not None:
        slots = sorted(slots, key=lambda slot: (slot.get("kind") == "validation", slot["id"] != chosen_slot))
    arc_summary["execution_order"] = [slot["id"] for slot in slots]
    arc_summary["execution_order_override"] = arc_summary["execution_order"] != planned_order
    run_routing_override = routing_override or arc_summary["execution_order_override"]
    routing = config["night"]["routing"]
    journal_path = run_root / "routing.json"
    if dry_run:
        return {
            "run_id": run_id,
            "dry_run": True,
            "budget_limit_api_equivalent": float(config["night"]["budget_usd"]),
            "budget_accounting": config["night"].get("budget_accounting"),
            "deadline_minutes": int(config["night"]["deadline_minutes"]),
            "slots": slots,
            "schedule_plan": schedule_plan,
            "routing": {**routing, "override": bool(run_routing_override)},
            "arc": arc_summary,
            "prizes": prize_summary,
        }
    run_root.mkdir(parents=True, exist_ok=True)
    with FileLock(LOCK):
        existing = read_json(checkpoint, None)
        if existing and not resume:
            raise RuntimeError(f"run {run_id} already exists; use --resume")
        if resume and not existing and invocation_kind != "scheduled":
            raise RuntimeError(f"run {run_id} has no checkpoint to resume")
        if existing:
            if existing.get("run_id") != run_id:
                raise ValueError("Checkpoint run identity does not match")
            if existing.get("status") == "completed":
                return existing
            # A resumed night replays the prize choice it checkpointed rather than re-allocating
            # against tonight's registry, so the second half of a slot keeps the first half's budget.
            stored_prizes = existing.get("prizes")
            if isinstance(stored_prizes, dict) and isinstance(stored_prizes.get("slot"), dict):
                slots = _with_prize_slots([slot for slot in slots if not slot.get("prize_id")], [stored_prizes["slot"]])
                prize_summary = {**stored_prizes, "resumed": True}
            run_routing_override = (existing.get("routing") or {}).get("override") is True
            existing_order = (existing.get("arc") or {}).get("execution_order", [])
            if existing_order:
                positions = {slot_id: index for index, slot_id in enumerate(existing_order)}
                slots = sorted(slots, key=lambda slot: positions.get(slot["id"], len(positions)))
            if existing.get("routing") != {**routing, "override": bool(run_routing_override)}:
                raise ValueError("resume must preserve the configured routing policy")
            status = existing
            original_arc = status.get("arc")
            if not isinstance(original_arc, dict):
                original_arc = {}
                status["arc"] = original_arc
            original_arc["resume_control"] = {
                "checked_at": arc_summary.get("attempted_at"),
                "catalogue_status": arc_summary.get("status"),
                "catalogue_hash": arc_summary.get("catalogue_hash"),
                "disabled_slot_ids": list(arc_summary.get("disabled_slot_ids", [])),
            }
            disabled_slot_ids = set(arc_summary.get("disabled_slot_ids", []))
            deadline = datetime.fromisoformat(status["deadline"].replace("Z", "+00:00")).timestamp()
            if deadline_cap is not None:
                deadline = min(deadline, float(deadline_cap))
                status["deadline"] = _iso(deadline)
            status["status"] = "running"
            status.pop("finished_at", None)
        else:
            deadline = started_now + 60 * int(config["night"]["deadline_minutes"])
            if deadline_cap is not None:
                deadline = min(deadline, float(deadline_cap))
            status = _new_status(
                config,
                run_id,
                deadline,
                ledger_path,
                routing,
                run_routing_override,
                invocation_kind=invocation_kind,
                scheduled_run_id=scheduled_run_id,
            )
            status["arc"] = arc_summary
            status["schedule_plan"] = schedule_plan
            disabled_slot_ids = set(arc_summary.get("disabled_slot_ids", []))
            for slot_id, mission in arc_plan.items():
                plugin = mission["plugin"]
                mission_path = run_root / plugin / "mission.json"
                atomic_json(mission_path, mission)
            requested_next = arc_summary.get("requested_next")
            if requested_next and requested_next in arc_summary["selected_missions"]:
                from arc_catalogue import DEFAULT_STATE, consume_next

                consume_next(DEFAULT_STATE, requested_next, run_id)
            if isinstance(prize_summary.get("mission"), dict):
                atomic_json(run_root / prize_summary["plugin"] / "prize-mission.json", prize_summary["mission"])
                if prize_summary.get("requested_next"):
                    from prize_registry import consume_next as consume_prize_next

                    consume_prize_next(ROOT, prize_summary["prize_id"], run_id)
        status["prizes"] = prize_summary
        checks = _preflight_with_retry(
            config,
            slots,
            provider_check=provider_check,
            sandbox_check=sandbox_check,
            deadline=deadline,
            on_wait=lambda check: _write_status(
                {**status, "preflight": check, "status": "preflight_retry"}, checkpoint
            ),
        )
        status["preflight"] = checks
        if not checks["ok"]:
            status["status"] = "failed"
            if checks["sandbox"].get("ok") is not True:
                status["limitations"] = ["Docker preflight failed"]
            else:
                status["limitations"] = ["no enabled subscription routing family is available"]
            status["finished_at"] = _iso()
            _write_status(status, checkpoint)
            return status
        ledger = BudgetLedger(ledger_path, float(config["night"]["budget_usd"]))
        completed_before = {
            entry.get("id") for entry in status.get("slots", []) if entry.get("status") in {"completed", "skipped"}
        }

        def heartbeat():
            status["budget_used_api_equivalent"] = round(float(ledger.spent), 6)
            _write_status(status, checkpoint)

        heartbeat()
        for slot in slots:
            slot_id = slot["id"]
            if slot_id in completed_before:
                continue
            if time.time() >= deadline:
                status["limitations"].append("night deadline reached before all slots started")
                break
            if paused(HERE):
                status["status"] = "paused"
                break
            if slot_id in disabled_slot_ids:
                status.setdefault("slots", []).append(
                    {
                        "id": slot_id,
                        "problem": slot["problem"],
                        "kind": slot["kind"],
                        "provider": slot.get("provider"),
                        "status": "skipped",
                        "reason": "mission_disabled_by_user",
                        "started_at": _iso(),
                        "finished_at": _iso(),
                        "stages": {},
                    }
                )
                status["limitations"].append(
                    f"{slot['problem']} research skipped because its admitted mission is disabled"
                )
                heartbeat()
                continue
            record = {
                "id": slot_id,
                "problem": slot["problem"],
                "kind": slot["kind"],
                "provider": slot.get("provider"),
                "status": "running",
                "started_at": _iso(),
                "stages": {},
            }
            if slot.get("prize_id"):
                record["prize_id"] = slot["prize_id"]
            mission_path = run_root / slot["problem"] / "mission.json"
            if mission_path.is_file():
                mission = read_json(mission_path, {}) or {}
                record["mission"] = {
                    "source_problem_id": mission.get("source_problem_id"),
                    "catalogue_hash": mission.get("catalogue_hash"),
                    "source_revision": mission.get("source_revision"),
                }
            status.setdefault("slots", []).append(record)
            heartbeat()
            slot_deadline = min(deadline, time.time() + 60 * float(slot["minutes"]))
            retro_seconds = 60 * float(slot.get("retro_minutes", 0))
            research_deadline = min(
                slot_deadline - retro_seconds,
                time.time() + 60 * float(slot.get("research_minutes", slot["minutes"])),
            )
            command = _research_command(
                slot,
                run_id,
                ledger_path,
                evidence_root,
                max(0.01, (research_deadline - time.time()) / 60),
                routing=routing,
                journal_path=journal_path,
                routing_override=run_routing_override,
                deadline=research_deadline,
                mission_path=mission_path if mission_path.is_file() else None,
            )
            code, reason = _run_bounded(
                command,
                run_root / slot["problem"] / "night.log",
                research_deadline,
                int(config["night"].get("heartbeat_seconds", 15)),
                heartbeat,
            )
            evidence = read_json(run_root / slot["problem"] / "evidence.json", {}) or {}
            work_count = evidence_work_count(evidence)
            evidence_status = evidence.get("status")
            research_ok = code == 0 and reason == "exited" and evidence_status in SUCCESS_STATUSES and work_count > 0
            research_partial = code == 0 and reason == "exited" and evidence_status == "partial" and work_count > 0
            if research_partial:
                failed_reason = "partial"
            elif evidence_status in {"budget_exhausted", "paused", "interrupted", "error", "provider_unavailable"}:
                failed_reason = evidence_status
            else:
                failed_reason = reason if reason != "exited" else "failed"
            record["stages"]["research"] = {
                "status": "completed" if research_ok else failed_reason,
                "exit_code": code,
                "evidence_status": evidence_status,
                "work_count": work_count,
            }
            if (
                slot["kind"] == "research"
                and reason != "paused"
                and evidence_status != "provider_unavailable"
                and time.time() < slot_deadline
            ):
                retro_code, retro_reason = _run_bounded(
                    _retro_command(
                        slot,
                        run_id,
                        ledger_path,
                        evidence_root,
                        routing=routing,
                        journal_path=journal_path,
                        routing_override=run_routing_override,
                        deadline=slot_deadline,
                    ),
                    run_root / slot["problem"] / "retro.log",
                    slot_deadline,
                    int(config["night"].get("heartbeat_seconds", 15)),
                    heartbeat,
                )
                retro_result = read_json(run_root / slot["problem"] / "retro.json", {}) or {}
                retro_ok = retro_code == 0 and retro_reason == "exited" and retro_result.get("status") == "completed"
                record["stages"]["retro"] = {
                    "status": "completed" if retro_ok else retro_reason if retro_reason != "exited" else "failed",
                    "exit_code": retro_code,
                    "provider": retro_result.get("provider", analyst_provider(slot["provider"], run_id)),
                }
            if reason == "paused":
                record["status"] = "paused"
                status["status"] = "paused"
            elif research_ok and all(stage["status"] == "completed" for stage in record["stages"].values()):
                record["status"] = "completed"
            elif reason == "timed_out":
                record["status"] = "timed_out"
            elif evidence_status == "budget_exhausted":
                record["status"] = "budget_exhausted"
            elif research_partial:
                record["status"] = "partial"
            else:
                record["status"] = "failed"
            record["finished_at"] = _iso()
            heartbeat()
            if status["status"] == "paused":
                break

        expected = {slot["id"] for slot in slots}
        completed = {
            entry.get("id") for entry in status.get("slots", []) if entry.get("status") in {"completed", "skipped"}
        }
        if status.get("status") != "paused":
            if completed == expected:
                status["status"] = "completed"
            elif completed or any(entry.get("status") == "partial" for entry in status.get("slots", [])):
                status["status"] = "partial"
            else:
                status["status"] = "failed"
        status["finished_at"] = _iso()
        heartbeat()
        return status


def scheduled_window(current=None):
    """Permit catch-up only overnight, never as surprise daytime CPU work."""
    local = current or datetime.now().astimezone()
    minutes = local.hour * 60 + local.minute
    return minutes >= 20 * 60 + 50 or minutes < 6 * 60


def scheduled_run_id(current=None):
    """Associate after-midnight continuation with the prior evening's run."""
    local = current or datetime.now().astimezone()
    run_date = local.date()
    if local.hour < 6:
        run_date -= timedelta(days=1)
    return run_date.isoformat()


def scheduled_deadline(current=None):
    """Return the next overnight 06:00 cutoff in the local timezone."""
    local = current or datetime.now().astimezone()
    cutoff_date = local.date() if local.hour < 6 else local.date() + timedelta(days=1)
    return local.replace(
        year=cutoff_date.year,
        month=cutoff_date.month,
        day=cutoff_date.day,
        hour=6,
        minute=0,
        second=0,
        microsecond=0,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--scheduled", action="store_true", help="skip delayed catch-up starts between 06:00 and 20:50")
    ap.add_argument("--run-id", help="dated run id (YYYY-MM-DD); defaults to the local date")
    ap.add_argument("--schedule", default=SCHEDULE)
    ap.add_argument("--routing", choices=sorted(VALID_ROUTING_POLICIES), help="routing policy for this run")
    ap.add_argument("--model-chain", nargs="+", help="ordered aliases, for example: astra sol opus")
    ap.add_argument("--disable-family", action="append", choices=("anthropic", "openai"))
    a = ap.parse_args()
    local_now = datetime.now().astimezone()
    if a.scheduled and not scheduled_window(local_now):
        print(json.dumps({"status": "skipped", "reason": "outside overnight catch-up window"}, indent=2))
        return 0
    logical_scheduled_id = (
        (_logical_run_date(a.run_id).isoformat() if a.scheduled and a.run_id else scheduled_run_id(local_now))
        if a.scheduled
        else None
    )
    run_id = f"{logical_scheduled_id}-scheduled" if a.scheduled else (a.run_id or date.today().isoformat())
    deadline_cap = scheduled_deadline(local_now).timestamp() if a.scheduled else None
    config = load_schedule(a.schedule)
    routing_override = any((a.routing is not None, a.model_chain is not None, a.disable_family is not None))
    if routing_override:
        config = json.loads(json.dumps(config))
        routing = dict(config["night"]["routing"])
        if a.routing is not None:
            routing["policy"] = a.routing
        if a.model_chain is not None:
            routing["chain"] = [alias for value in a.model_chain for alias in value.split(",") if alias]
        if a.disable_family is not None:
            routing["disabled_families"] = a.disable_family
        config["night"]["routing"] = routing
        config["night"]["routing"] = routing_config(config)
    evidence_root = Path(config["night"].get("evidence_root", "runs/research"))
    if not evidence_root.is_absolute():
        evidence_root = ROOT / evidence_root
    resume = a.resume or a.scheduled
    cpu_limit = None
    if not a.dry_run:
        cpu_limit = limit_cpu(float(config["night"].get("cpu_fraction", 0.5)))
        os.environ["DISCOVERY_CPU_LIMIT"] = json.dumps(cpu_limit)
    status = run_night(
        config,
        run_id,
        resume=resume,
        dry_run=a.dry_run,
        deadline_cap=deadline_cap,
        routing_override=routing_override,
        invocation_kind="scheduled" if a.scheduled and run_id.endswith("-scheduled") else "manual",
        scheduled_run_id=logical_scheduled_id if a.scheduled and run_id.endswith("-scheduled") else None,
    )
    if cpu_limit is not None and isinstance(status, dict):
        status["cpu_limit"] = cpu_limit
    print(json.dumps(status, indent=2))
    return 0 if a.dry_run or status.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
