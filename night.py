"""Night runner: run several problems back to back, each in its own wall-clock slot, and leave a morning summary.

Schedule lives in night.json (edit by hand):
  {"slots": [{"problem": "miplib_heur", "minutes": 235, "budget": 15},
             {"problem": "pglib_opf",   "minutes": 235, "budget": 15}]}

Each slot runs `python -u loop.py --problem P --wall-minutes M --budget B [extra args]` and appends to
runs-<P>/night-<date>.log. runs/night-status.json holds the per-slot outcome (champion total before/after,
spend, wins, exit code) so a morning check can read one file instead of every log. After each slot (even a
crashed one) `retro.py --problem P` appends the night's retro to docs/retro/P.md (what worked, what didn't,
lessons, five Next directions that tomorrow's prompt reads), then `publish.py --problem P` runs detached: one
maintainer email per slot with every winner in it, one approval tap (the loop itself only pushes to GitHub).

  python night.py                 # run tonight's schedule
  python night.py --dry-run       # print the commands only
Installed as the Windows scheduled task "discovery-loop-night" (daily 22:00), see README.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(HERE, "night.json")
STATUS = os.path.join(HERE, "runs", "night-status.json")


def layout(problem):
    suf = "" if problem == "circle_packing" else "-" + problem
    return os.path.join(HERE, "best" + suf), os.path.join(HERE, "runs" + suf)


def snapshot(problem):
    """(champion total, model spend, record-beating targets) from the problem's log + scores."""
    best, runs = layout(problem)
    log = os.path.join(runs, "log.jsonl")
    hist = [json.loads(l) for l in open(log, encoding="utf-8")] if os.path.exists(log) else []
    champ = max([h["total"] for h in hist if h["status"] in ("champion", "seed")], default=None)
    spend = round(sum(h.get("cost", 0) for h in hist), 2)
    wins = sorted({t for h in hist for t in h.get("wins", [])})
    return {"champion_total": champ, "spend_usd": spend, "wins": wins, "iterations": len(hist)}


def run_slot(slot, dry):
    problem = slot["problem"]
    best, runs = layout(problem)
    os.makedirs(runs, exist_ok=True)
    cmd = [
        sys.executable,
        "-u",
        os.path.join(HERE, "loop.py"),
        "--problem",
        problem,
        "--wall-minutes",
        str(slot["minutes"]),
        "--budget",
        str(slot.get("budget", 15)),
        "--iters",
        str(slot.get("iters", 200)),
        *slot.get("args", []),
    ]
    date = time.strftime("%Y-%m-%d")
    logfile = os.path.join(runs, f"night-{date}.log")
    print(f"[{time.strftime('%H:%M')}] {problem}: {' '.join(cmd)} -> {logfile}", flush=True)
    if dry:
        return {"problem": problem, "dry_run": True, "cmd": cmd}
    env = dict(os.environ, PYTHONUTF8="1")
    env.setdefault("OMP_NUM_THREADS", "2")
    before = snapshot(problem)
    t0 = time.time()
    with open(logfile, "a", encoding="utf-8") as lf:
        lf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n")
        lf.flush()
        p = subprocess.run(cmd, cwd=HERE, stdout=lf, stderr=subprocess.STDOUT, env=env)
    after = snapshot(problem)
    return {
        "problem": problem,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
        "minutes": round((time.time() - t0) / 60, 1),
        "exit_code": p.returncode,
        "before": before,
        "after": after,
        "night_spend_usd": round(after["spend_usd"] - before["spend_usd"], 2),
        "night_iterations": after["iterations"] - before["iterations"],
        "improved": (after["champion_total"] or 0) > (before["champion_total"] or 0)
        if before["champion_total"] is not None
        else after["champion_total"] is not None,
        "new_wins": sorted(set(after["wins"]) - set(before["wins"])),
        "log": logfile,
        "status_html": os.path.join(runs, "status.html"),
    }


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--schedule", default=SCHEDULE)
    a = ap.parse_args()
    slots = json.load(open(a.schedule))["slots"]
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    status = {"night": time.strftime("%Y-%m-%d"), "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "slots": []}
    for slot in slots:
        try:
            result = run_slot(slot, a.dry_run)
            status["slots"].append(result)
            if not a.dry_run:
                try:
                    retro_slot(slot["problem"], result["before"]["iterations"])
                except Exception as e:  # a failed retro must not block the push or the next slot
                    result["retro_error"] = f"{type(e).__name__}: {e}"[:300]
                publish_slot(slot["problem"])
        except Exception as e:  # one broken slot must not cost the other slot its night
            status["slots"].append({"problem": slot.get("problem"), "error": f"{type(e).__name__}: {e}"[:400]})
        if not a.dry_run:
            json.dump(status, open(STATUS, "w"), indent=1)
    status["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if not a.dry_run:
        json.dump(status, open(STATUS, "w"), indent=1)
    print(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()
