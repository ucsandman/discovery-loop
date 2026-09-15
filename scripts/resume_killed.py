#!/usr/bin/env python3
"""Relaunch discovery-loop runs killed by host reboots.

Scans runs/*/run.json for detached runs that died without writing a final
state ('lost', or 'running' with a dead PID). For each candidate:

  1. --auto restricts to nightly-* runs (the cron always passes --auto).
  2. Skips runs lost more than --max-age-h hours ago (default 12): stale
     losses belong to old nights, not to tonight's resume.
  3. Consults host_horizon.py with the run's original budget; on 'hold'
     the run is left alone (the next tick tries again).
  4. Circle smart_loop runs relaunch with --resume (and --cap from the
     horizon gate): the loop picks up its checkpoint, continues the seed
     stream, and honors the remaining budget.
  5. Matmul driver runs relaunch as-is (full restart; the driver has no
     checkpoint support). Champion promotion is idempotent (strict
     improvement only), so a restart is safe. The horizon cap rewrites
     --time when it is smaller than the recorded budget.
  6. The killed run's directory is moved aside to <name>.killed-<ts>
     (evidence preserved) before the fresh launch reuses the name.

Idempotent: a run that is alive is never touched. Safe to run every 30 min.

Usage:
    python3 scripts/resume_killed.py [--auto] [--dry-run] [--max-age-h 12]
Exit 0 always; prints JSON lines describing each decision.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_RUNS_DIR = os.path.join(_REPO_ROOT, "runs")

sys.path.insert(0, _HERE)
from detached import _state  # noqa: E402
import host_horizon  # noqa: E402


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _budget_of(command: list) -> float | None:
    """Original --time budget from a recorded command line."""
    for i, tok in enumerate(command):
        if tok == "--time" and i + 1 < len(command):
            try:
                return float(command[i + 1])
            except ValueError:
                return None
    return None


def _kind_of(command: list) -> str:
    joined = " ".join(command)
    if "smart_loop.py" in joined and "circle_packing" in joined:
        return "circle"
    if "nightly_matmul.py" in joined:
        return "matmul"
    return "other"


def _rewrite_time(command: list, cap: float) -> list:
    """Return a copy of command with --time replaced by cap (matmul path)."""
    out = list(command)
    for i, tok in enumerate(out):
        if tok == "--time" and i + 1 < len(out):
            out[i + 1] = str(int(cap))
            return out
    return out


def _candidates(auto: bool, max_age_h: float):
    """Yield (name, state) for detached runs that look reboot-killed."""
    now = _utcnow()
    if not os.path.isdir(_RUNS_DIR):
        return
    for child in sorted(os.listdir(_RUNS_DIR)):
        run_dir = os.path.join(_RUNS_DIR, child)
        if not os.path.isdir(run_dir):
            continue
        if not os.path.exists(os.path.join(run_dir, "run.json")):
            continue
        if auto and not child.startswith("nightly-"):
            continue
        try:
            st = _state(child)
        except (OSError, json.JSONDecodeError):
            continue
        if st["status"] not in ("lost", "running"):
            continue
        if st["status"] == "running":
            # 'running' with a live PID is not our business. _state already
            # marks dead-PID runs as lost; a truly stale heartbeat with a
            # live PID is a stuck run for the nightly worker, not the resumer.
            continue
        started = _parse_iso(st.get("start_time"))
        if started and (now - started).total_seconds() > max_age_h * 3600:
            continue
        yield child, st


def _horizon(budget: float) -> dict:
    boot = host_horizon._current_boot()
    if boot is None:
        return {"decision": "go", "budget_cap_s": int(budget),
                "reason": "boot time unreadable; proceeding"}
    boots = host_horizon._record_boot(boot)
    return host_horizon.decide(budget, boots, _utcnow())


def resume_run(name: str, st: dict, dry_run: bool) -> dict:
    command = st.get("command") or []
    kind = _kind_of(command)
    result = {"name": name, "kind": kind, "prev_start": st.get("start_time")}
    if kind == "other" or not command:
        result["action"] = "skip"
        result["reason"] = "not a known discovery-loop command"
        return result

    budget = _budget_of(command) or 3600.0
    horizon = _horizon(budget)
    result["horizon"] = horizon["decision"]
    result["horizon_reason"] = horizon["reason"]
    if horizon["decision"] == "hold":
        result["action"] = "deferred"
        result["reason"] = "horizon gate says hold; will retry next tick"
        return result
    cap = float(horizon["budget_cap_s"]) or budget

    if kind == "circle":
        new_cmd = command + ["--resume", "--cap", str(int(cap))]
        result["action"] = "resume"
        result["detail"] = f"relaunch with --resume --cap {int(cap)}"
    else:  # matmul: full restart, honoring the cap via --time
        new_cmd = _rewrite_time(command, cap) if cap < budget else command
        result["action"] = "restart"
        result["detail"] = ("full restart (no checkpoint support); "
                            f"--time {int(cap)}" if cap < budget
                            else "full restart (no checkpoint support)")
    result["command"] = new_cmd
    if dry_run:
        return result

    # Preserve the killed run's evidence before the fresh launch reuses
    # the name (detached.launch wipes the directory).
    run_dir = os.path.join(_RUNS_DIR, name)
    ts = _utcnow().strftime("%Y%m%dT%H%M%SZ")
    aside = os.path.join(_RUNS_DIR, f"{name}.killed-{ts}")
    try:
        shutil.move(run_dir, aside)
        result["evidence_moved_to"] = aside
    except OSError as exc:
        result["action"] = "failed"
        result["reason"] = f"could not move killed run dir aside: {exc}"
        return result

    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, "detached.py"),
         "launch", "--name", name, "--", *new_cmd],
        capture_output=True, text=True, timeout=60, cwd=_REPO_ROOT)
    result["launch_rc"] = proc.returncode
    result["launch_out"] = (proc.stdout.strip() + " " +
                            proc.stderr.strip()).strip()[:200]
    if proc.returncode != 0:
        result["action"] = "failed"
        return result
    # Annotate the new record with where it came from.
    try:
        rec_path = os.path.join(_RUNS_DIR, name, "run.json")
        rec = json.loads(open(rec_path).read())
        rec["resumed_from"] = {"prev_start": st.get("start_time"),
                               "prev_command": command,
                               "resumed_at": _utcnow().isoformat(),
                               "mode": result["action"]}
        open(rec_path, "w").write(json.dumps(rec, indent=2))
    except (OSError, json.JSONDecodeError):
        pass
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--auto", action="store_true",
                    help="only consider nightly-* runs")
    ap.add_argument("--dry-run", action="store_true",
                    help="report decisions, change nothing")
    ap.add_argument("--max-age-h", type=float, default=12,
                    help="ignore runs lost longer ago (default 12h)")
    a = ap.parse_args(argv)

    found = False
    for name, st in _candidates(a.auto, a.max_age_h):
        found = True
        print(json.dumps(resume_run(name, st, a.dry_run)))
    if not found:
        print(json.dumps({"action": "none",
                          "reason": "no reboot-killed nightly runs found"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
