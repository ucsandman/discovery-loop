#!/usr/bin/env python3
"""Host stability horizon: should we spend a long compute budget right now?

The host reboots roughly hourly. This script keeps a persistent boot log
(runs/host_boots.jsonl) and recommends whether a compute budget fits inside
the expected stable window.

Usage:
    python3 scripts/host_horizon.py --budget 3600 [--record-only]

Prints JSON on stdout:
    {"decision": "go"|"hold", "budget_cap_s": N, "reason": "...",
     "boot": "<iso>", "since_boot_s": N, "p25_interval_s": N|None, ...}

Exit code is always 0; the decision lives in the JSON, not the exit code.
--record-only just logs the current boot and prints the log stats.

Heuristic (documented, not measured truth):
  - p25 of recent reboot intervals estimates the stable window we can
    count on most of the time.
  - If the requested budget fits inside (p25 - elapsed): go, full budget.
  - If we are still inside p25 but the full budget does not fit:
    go with a cap of (p25 - elapsed), floored at 600s.
  - If we are past p25 (overdue for a reboot): hold; the resumer cron
    relaunches killed runs after the next boot.
  - With fewer than 3 recorded intervals: go with a conservative 1800s cap
    until history accumulates.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_BOOT_LOG = os.path.join(_REPO_ROOT, "runs", "host_boots.jsonl")
_MAX_INTERVALS = 8
_MIN_INTERVALS = 3
_FALLBACK_CAP_S = 1800
_FLOOR_CAP_S = 600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _current_boot() -> datetime | None:
    """Current boot time via `uptime -s` (local time, no tz)."""
    try:
        proc = subprocess.run(["uptime", "-s"], capture_output=True,
                              text=True, timeout=10)
        s = proc.stdout.strip()
        if not s:
            return None
        # `uptime -s` prints local wall time; interpret in the local zone by
        # attaching the local offset via astimezone dance.
        naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        local = naive.astimezone()  # attaches local tz to naive wall time
        return local.astimezone(timezone.utc)
    except Exception:
        return None


def _read_log() -> list[datetime]:
    boots: list[datetime] = []
    try:
        with open(_BOOT_LOG) as fh:
            for line in fh:
                try:
                    ts = json.loads(line).get("boot")
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    boots.append(dt.astimezone(timezone.utc))
                except (ValueError, AttributeError):
                    continue
    except OSError:
        pass
    # dedupe, sorted
    uniq = sorted({b.replace(microsecond=0) for b in boots})
    return uniq


def _record_boot(boot: datetime) -> list[datetime]:
    boots = _read_log()
    mark = boot.replace(microsecond=0)
    if mark not in boots:
        os.makedirs(os.path.dirname(_BOOT_LOG), exist_ok=True)
        with open(_BOOT_LOG, "a") as fh:
            fh.write(json.dumps({
                "boot": mark.isoformat(),
                "recorded_at": _utcnow().isoformat(),
            }) + "\n")
        boots.append(mark)
        boots.sort()
    return boots


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def decide(budget_s: float, boots: list[datetime],
           now: datetime) -> dict:
    boot = boots[-1]
    since_boot = (now - boot).total_seconds()
    intervals = [(b2 - b1).total_seconds()
                 for b1, b2 in zip(boots[-_MAX_INTERVALS - 1:], boots[-_MAX_INTERVALS:])]
    intervals = [i for i in intervals if i > 0]
    # Only trust intervals that look like real reboots (under 24h); a gap of
    # days means logging was off, not that the host was stable.
    intervals = [i for i in intervals if i < 86400]

    base = {
        "boot": boot.isoformat(),
        "since_boot_s": int(since_boot),
        "intervals_recorded": len(intervals),
        "requested_budget_s": int(budget_s),
    }
    if len(intervals) < _MIN_INTERVALS:
        cap = min(int(budget_s), _FALLBACK_CAP_S)
        return {**base, "decision": "go", "budget_cap_s": cap,
                "p25_interval_s": None,
                "reason": (f"only {len(intervals)} reboot intervals on record; "
                           f"conservative cap {cap}s until history accumulates")}
    p25 = _percentile(intervals, 0.25)
    p50 = _percentile(intervals, 0.50)
    base["p25_interval_s"] = int(p25)
    base["p50_interval_s"] = int(p50)
    if since_boot + budget_s <= p25:
        return {**base, "decision": "go", "budget_cap_s": int(budget_s),
                "reason": (f"budget {int(budget_s)}s + {int(since_boot)}s elapsed "
                           f"fits inside p25 reboot interval ({int(p25)}s)")}
    if since_boot < p25:
        cap = max(_FLOOR_CAP_S, int(p25 - since_boot))
        return {**base, "decision": "go", "budget_cap_s": cap,
                "reason": (f"inside p25 interval ({int(p25)}s) but full budget "
                           f"does not fit; capped to {cap}s")}
    return {**base, "decision": "hold", "budget_cap_s": 0,
            "reason": (f"{int(since_boot)}s since boot is past p25 reboot interval "
                       f"({int(p25)}s); a reboot is likely before the budget "
                       f"elapses. Wait for the next boot; the resumer relaunches "
                       f"killed runs.")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--budget", type=float, default=3600,
                    help="seconds of compute you want to spend")
    ap.add_argument("--record-only", action="store_true",
                    help="just log the current boot, print log stats")
    a = ap.parse_args(argv)

    boot = _current_boot()
    if boot is None:
        print(json.dumps({"decision": "go",
                          "budget_cap_s": min(int(a.budget), _FALLBACK_CAP_S),
                          "reason": "could not read boot time; conservative cap",
                          "boot": None}))
        return 0
    boots = _record_boot(boot)
    if a.record_only:
        print(json.dumps({"boot": boot.isoformat(),
                          "boots_recorded": len(boots)}, indent=2))
        return 0
    print(json.dumps(decide(a.budget, boots, _utcnow()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
