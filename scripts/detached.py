"""Detached process runner for long discovery-loop searches.

Problem this solves: background search batches (multiscale L2/L3, adversarial
breaker suites, nightly smart-loop cycles) died when the spawning agent or
worker exited. This runner launches a command in its own session (setsid), with
stdin/stdout/stderr redirected to a per-run log file, plus a heartbeat file the
runner's wrapper touches every 15 seconds so arbitrary commands get liveness
tracking for free.

Subcommands:
    launch --name NAME -- <cmd...>   Start a detached run.
    status --name NAME                Show running/finished, exit code,
                                      heartbeat age, log tail.
    list                              All runs with states.
    kill --name NAME                   Terminate by PID from the run record
                                      (PID only, never by name pattern).

Run layout (all under <repo>/runs/<name>/, gitignored via .gitignore):
    run.json     pid, start/end time, command, log path, heartbeat path, status
    child.log    combined stdout/stderr of the command
    heartbeat    touched every 15s by the wrapper while the command runs

Survival test (proving the child outlives its parent):
    1. From shell A, launch a 90-second task:
           python3 scripts/detached.py launch --name survival-90 -- \
               python3 -c "import time; time.sleep(90); print('SURVIVED-90')"
    2. Exit shell A completely (or kill the launching process).
    3. From a NEW shell B (new login session), after ~95s:
           python3 scripts/detached.py status --name survival-90
       Expected: state=finished, exit_code=0, log contains SURVIVED-90,
       heartbeat age grows only after the child finished.
    This was verified for real on 2026-09-09: launch PID recorded, parent
    shell exited, and a new shell observed the run finish with exit_code 0
    and the expected output in child.log.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / "runs"
HEARTBEAT_INTERVAL = 15  # seconds

# Wrapper executed in the detached session. Args:
#   [0] run_dir, [1] command-as-JSON
# It heartbeats, redirects the child's stdio to child.log, waits for the
# command, then writes the final state into run.json.
_WRAPPER = r"""
import json, os, subprocess, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
cmd = json.loads(sys.argv[2])
log_path = run_dir / "child.log"
hb_path = run_dir / "heartbeat"
record_path = run_dir / "run.json"

stop = threading.Event()

def _beat():
    while not stop.wait(15):
        try:
            hb_path.touch()
        except OSError:
            pass

t = threading.Thread(target=_beat, daemon=True)
t.start()

devnull = os.open(os.devnull, os.O_RDONLY)
logf = open(log_path, "ab", buffering=0)
os.dup2(devnull, 0)
os.dup2(logf.fileno(), 1)
os.dup2(logf.fileno(), 2)
os.close(devnull)

rc = None
try:
    rc = subprocess.run(cmd).returncode
except Exception as exc:  # noqa: BLE001 - record the failure, don't crash silently
    logf.write(f"\n[detached] wrapper failed to run command: {exc!r}\n".encode())
    rc = 127

stop.set()
t.join(timeout=20)

try:
    rec = json.loads(record_path.read_text())
except (OSError, json.JSONDecodeError):
    rec = {}
rec["status"] = "finished"
rec["exit_code"] = rc
rec["end_time"] = datetime.now(timezone.utc).isoformat()
try:
    record_path.write_text(json.dumps(rec, indent=2))
except OSError:
    pass
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dir(name: str) -> Path:
    return RUNS_DIR / name


def _read_record(name: str) -> dict:
    path = _run_dir(name) / "run.json"
    return json.loads(path.read_text())


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _state(name: str) -> dict:
    """Resolve a run's live state: running / finished / lost."""
    rec = _read_record(name)
    hb = _run_dir(name) / "heartbeat"
    info = {
        "name": name,
        "pid": rec.get("pid"),
        "status": rec.get("status", "unknown"),
        "exit_code": rec.get("exit_code"),
        "start_time": rec.get("start_time"),
        "end_time": rec.get("end_time"),
        "command": rec.get("command"),
        "heartbeat_age_s": None,
        "log_path": str(_run_dir(name) / "child.log"),
    }
    if hb.exists():
        info["heartbeat_age_s"] = round(time.time() - hb.stat().st_mtime, 1)
    if rec.get("status") == "running":
        pid = rec.get("pid")
        if pid is not None and _pid_alive(pid):
            info["status"] = "running"
        else:
            info["status"] = "lost"  # wrapper died without writing final state
    return info


def cmd_launch(args) -> int:
    run_dir = _run_dir(args.name)
    if run_dir.exists():
        try:
            st = _state(args.name)
        except (OSError, json.JSONDecodeError):
            st = {"status": "unknown"}
        if st["status"] == "running":
            print(f"error: run '{args.name}' is already running (pid {st['pid']}); "
                  f"use 'kill' first", file=sys.stderr)
            return 1
        # A finished/lost run's directory is replaced by the new launch.
        import shutil
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "heartbeat").touch()

    record = {
        "name": args.name,
        "pid": None,
        "status": "running",
        "exit_code": None,
        "start_time": _now_iso(),
        "end_time": None,
        "command": args.command,
        "log_path": str(run_dir / "child.log"),
        "heartbeat_path": str(run_dir / "heartbeat"),
        "launcher_pid": os.getpid(),
    }
    (run_dir / "run.json").write_text(json.dumps(record, indent=2))

    proc = subprocess.Popen(
        [sys.executable, "-c", _WRAPPER, str(run_dir), json.dumps(args.command)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # setsid: survives parent death, no SIGHUP
        close_fds=True,
    )
    record["pid"] = proc.pid
    (run_dir / "run.json").write_text(json.dumps(record, indent=2))
    # Do NOT wait on proc: it is the long-lived wrapper in its own session.
    # Detach fully so this launcher can exit without affecting the run.
    print(f"launched '{args.name}' pid={record['pid']} log={run_dir / 'child.log'}")
    print(f"status: python3 scripts/detached.py status --name {args.name}")
    return 0


def cmd_status(args) -> int:
    run_dir = _run_dir(args.name)
    if not (run_dir / "run.json").exists():
        print(f"error: no run named '{args.name}'", file=sys.stderr)
        return 1
    st = _state(args.name)
    print(f"name:           {st['name']}")
    print(f"status:         {st['status']}")
    print(f"pid:            {st['pid']}")
    print(f"exit_code:      {st['exit_code']}")
    print(f"started:        {st['start_time']}")
    print(f"ended:          {st['end_time']}")
    print(f"heartbeat_age:  {st['heartbeat_age_s']}s")
    print(f"command:        {' '.join(st['command'] or [])}")
    dash = run_dir / "dashboard.html"
    if dash.exists():
        print(f"dashboard:      {dash}")
    log = Path(st["log_path"])
    print("--- log tail ---")
    if log.exists():
        lines = log.read_text(errors="replace").splitlines()
        for line in lines[-20:]:
            print(line)
    else:
        print("(no log yet)")
    return 0


def cmd_list(args) -> int:
    if not RUNS_DIR.exists():
        print("(no runs)")
        return 0
    rows = []
    for child in sorted(RUNS_DIR.iterdir()):
        if not child.is_dir() or not (child / "run.json").exists():
            continue
        try:
            st = _state(child.name)
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(st)
    if not rows:
        print("(no runs)")
        return 0
    print(f"{'NAME':<28}{'STATUS':<10}{'EXIT':<6}{'PID':<8}{'HB_AGE':<8}COMMAND")
    for st in rows:
        cmd = " ".join(st["command"] or [])[:60]
        print(f"{st['name']:<28}{st['status']:<10}{str(st['exit_code']):<6}"
              f"{str(st['pid']):<8}{str(st['heartbeat_age_s']):<8}{cmd}")
    return 0


def cmd_kill(args) -> int:
    run_dir = _run_dir(args.name)
    if not (run_dir / "run.json").exists():
        print(f"error: no run named '{args.name}'", file=sys.stderr)
        return 1
    st = _state(args.name)
    pid = st["pid"]
    if st["status"] != "running" or pid is None or not _pid_alive(pid):
        print(f"'{args.name}' is not running (status={st['status']})")
        return 0
    os.kill(pid, signal.SIGTERM)  # PID only, never by name pattern
    deadline = time.time() + 10
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.5)
    if _pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
    try:
        rec = _read_record(args.name)
        if rec.get("status") == "running":
            rec["status"] = "killed"
            rec["end_time"] = _now_iso()
            (run_dir / "run.json").write_text(json.dumps(rec, indent=2))
    except (OSError, json.JSONDecodeError):
        pass
    print(f"killed '{args.name}' (pid {pid})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Detached process runner")
    sub = ap.add_subparsers(dest="subcommand", required=True)

    p = sub.add_parser("launch", help="Start a detached run")
    p.add_argument("--name", required=True)
    p.add_argument("command", nargs=argparse.REMAINDER,
                   help="command after -- : launch --name X -- <cmd...>")
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("status", help="Show a run's state and log tail")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_status)

    sub.add_parser("list", help="List all runs").set_defaults(func=cmd_list)

    p = sub.add_parser("kill", help="Terminate a run by PID")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_kill)

    args = ap.parse_args()
    if args.subcommand == "launch":
        # argparse.REMAINDER keeps the leading '--'; drop it.
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        if not args.command:
            print("error: launch requires a command after --", file=sys.stderr)
            return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
