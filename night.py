"""Bounded, resumable nightly research with local-only evidence output.

The canonical path shares one deadline and budget ledger across research,
review and retrospective stages. It never invokes publication or email.
Legacy ``publish_slot`` and ``retro_slot`` call signatures remain available
for existing callers, but ``main`` does not use the publisher.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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
    night = config.get("night", {})
    # Schema-2 schedules predate routing. Their historical meaning is the
    # scheduled trial policy over the canonical default chain, so normalize in
    # memory without requiring a schedule migration.
    night["routing"] = routing_config(config)
    if not 0 < float(night.get("budget_usd", 0)) <= 90:
        raise ValueError("night API-equivalent allowance must be in (0, 90]")
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
    research = {slot.get("problem") for slot in slots if slot.get("kind") == "research"}
    if research != {"cvrp", "miplib_heur"}:
        raise ValueError("research slots must be exactly cvrp and miplib_heur")
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
    return config


def trial_for(config, run_id):
    anchor = date.fromisoformat(config["trial"]["anchor_date"])
    current = date.fromisoformat(run_id)
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
    # PGLib is confirmation-only and deliberately has no generation provider.
    ordered.append(by_problem["pglib_opf"])
    return ordered


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
    return "fable" if date.fromisoformat(run_id).toordinal() % 2 == 0 else "astra"


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
        "--no-publish",
    ]
    if routing is not None and journal_path is not None:
        command.extend(_routing_command_args(routing, journal_path, override=routing_override, deadline=deadline))
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


def _new_status(config, run_id, deadline, ledger_path, routing, routing_override):
    index, assignment = trial_for(config, run_id)
    return {
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
):
    """Run or resume one dated night under one lock, deadline and ledger."""
    started_now = time.time() if now is None else now
    configured_root = Path(config["night"].get("evidence_root", "runs/research"))
    evidence_root = configured_root if configured_root.is_absolute() else ROOT / configured_root
    run_root = evidence_root / run_id
    checkpoint = run_root / "night.json"
    ledger_path = run_root / "budget.json"
    slots = planned_slots(config, run_id)
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
            "routing": {**routing, "override": bool(routing_override)},
        }
    run_root.mkdir(parents=True, exist_ok=True)
    with FileLock(LOCK):
        existing = read_json(checkpoint, None)
        if existing and not resume:
            raise RuntimeError(f"run {run_id} already exists; use --resume")
        if resume and not existing:
            raise RuntimeError(f"run {run_id} has no checkpoint to resume")
        if existing:
            if existing.get("run_id") != run_id:
                raise ValueError("Checkpoint run identity does not match")
            if existing.get("status") == "completed":
                return existing
            if existing.get("routing") != {**routing, "override": bool(routing_override)}:
                raise ValueError("resume must preserve the configured routing policy")
            status = existing
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
            status = _new_status(config, run_id, deadline, ledger_path, routing, routing_override)
        checks = _preflight(config, slots, provider_check=provider_check, sandbox_check=sandbox_check)
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
        completed_before = {entry.get("id") for entry in status.get("slots", []) if entry.get("status") == "completed"}

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
            record = {
                "id": slot_id,
                "problem": slot["problem"],
                "kind": slot["kind"],
                "provider": slot.get("provider"),
                "status": "running",
                "started_at": _iso(),
                "stages": {},
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
                routing_override=routing_override,
                deadline=research_deadline,
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
                        routing_override=routing_override,
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
        completed = {entry.get("id") for entry in status.get("slots", []) if entry.get("status") == "completed"}
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
    return minutes >= 21 * 60 + 50 or minutes < 6 * 60


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
    ap.add_argument("--scheduled", action="store_true", help="skip delayed catch-up starts between 06:00 and 21:50")
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
    run_id = a.run_id or (scheduled_run_id(local_now) if a.scheduled else date.today().isoformat())
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
    resume = a.resume or (a.scheduled and (evidence_root / run_id / "night.json").is_file())
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
    )
    if cpu_limit is not None and isinstance(status, dict):
        status["cpu_limit"] = cpu_limit
    print(json.dumps(status, indent=2))
    return 0 if a.dry_run or status.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
