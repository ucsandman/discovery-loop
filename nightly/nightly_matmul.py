#!/usr/bin/env python3
"""Nightly driver for the matrix-multiplication discovery loop.

Sparrow (the agent) is the proposer: each night it writes one candidate
solver.py evolving from the champion, then runs:

    python nightly_matmul.py run <candidate.py> [--targets 2,3,4] [--time 300] [--seed S]

The driver executes the candidate per target with a hard timeout, evaluates
the output through the plugin's independent verifier, promotes champions via
problem.save, and appends every outcome to a JSONL run log. Nothing is
published automatically; SUBMIT_NOTE in the plugin requires hand review.

    python nightly_matmul.py status
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

REPO = os.path.expanduser("~/workspace/discovery-loop")
VENV_PYTHON = os.path.join(REPO, ".venv", "bin", "python")
STATE = os.path.dirname(os.path.abspath(__file__))
CHAMPIONS = os.path.join(STATE, "champions")
CANDIDATES = os.path.join(STATE, "candidates")
RUNLOG = os.path.join(STATE, "runs.jsonl")

sys.path.insert(0, REPO)
from problem_loader import load_problem  # noqa: E402


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_champions(problem):
    sol = os.path.join(CHAMPIONS, "sol")
    os.makedirs(CHAMPIONS, exist_ok=True)
    champs = {}
    for t in problem.TARGETS:
        path = problem.raw_path(t, CHAMPIONS)
        if os.path.exists(path):
            with open(path) as fh:
                d = json.load(fh)
            champs[t] = {"target": t, "rank": d["rank"], "author": d.get("author")}
    return champs


def _clean_env():
    allowed = {
        "HOME", "LANG", "LC_ALL", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP",
        "USER", "USERNAME", "VIRTUAL_ENV",
    }
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


def run_candidate(candidate, targets, budget, seed):
    problem = load_problem("matrix_multiplication")
    records = problem.records_load()
    champions = _load_champions(problem)
    plugin_dir = os.path.join(REPO, "problems", "matrix_multiplication")
    os.makedirs(CANDIDATES, exist_ok=True)

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tag = f"{date}-seed{seed}"
    staged = os.path.join(CANDIDATES, f"{tag}.py")
    shutil.copy(candidate, staged)

    results = []
    for t in targets:
        entry = {"ts": _utcnow(), "candidate": staged, "target": t,
                 "budget": budget, "seed": seed}
        out = os.path.join(tempfile.mkdtemp(prefix="matmul-"), "out.json")
        py = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
        argv = [py, staged, *problem.solver_argv(t, budget, seed, out)]
        env = _clean_env()
        env["PYTHONPATH"] = plugin_dir + os.pathsep + env.get("PYTHONPATH", "")
        start = time.time()
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=budget + 45,
                env=env, cwd=plugin_dir,
            )
            entry["wall_s"] = round(time.time() - start, 1)
            entry["returncode"] = proc.returncode
            entry["stdout_tail"] = proc.stdout[-500:]
            entry["stderr_tail"] = proc.stderr[-500:]
            if proc.returncode != 0 or not os.path.exists(out):
                entry["outcome"] = "crash"
                entry["score"] = problem.FAIL_SCORE
            else:
                try:
                    value, payload = problem.evaluate(out, t)
                except Exception as exc:  # noqa: BLE001 - candidate output is untrusted
                    entry["outcome"] = "infeasible"
                    entry["detail"] = str(exc)[:300]
                    entry["score"] = problem.FAIL_SCORE
                else:
                    rec = records.get(t)
                    entry["outcome"] = "ok"
                    entry["rank"] = value
                    entry["record"] = rec
                    entry["score"] = problem.score(value, rec)
                    champ = champions.get(t)
                    champ_rank = champ["rank"] if champ else None
                    if champ_rank is None or problem.better(value, champ_rank):
                        problem.save(t, payload, value, CHAMPIONS, f"sparrow-nightly/{tag}")
                        champions[t] = {"target": t, "rank": value, "author": f"sparrow-nightly/{tag}"}
                        entry["promoted"] = True
                        entry["prev_champion"] = champ_rank
        except subprocess.TimeoutExpired:
            entry["outcome"] = "timeout"
            entry["wall_s"] = round(time.time() - start, 1)
            entry["score"] = problem.FAIL_SCORE
        results.append(entry)
        with open(RUNLOG, "a") as fh:
            fh.write(json.dumps(entry) + "\n")
        print(json.dumps({k: entry.get(k) for k in
              ("target", "outcome", "rank", "record", "score", "promoted", "wall_s")}))
    return results


def status():
    problem = load_problem("matrix_multiplication")
    records = problem.records_load()
    champions = _load_champions(problem)
    print("matrix-multiplication nightly status")
    print(f"  records:  {records}")
    for t in problem.TARGETS:
        c = champions.get(t)
        if c:
            print(f"  n={t}: champion rank {c['rank']} (record {records[t]}) by {c['author']}")
        else:
            print(f"  n={t}: no champion yet (record {records[t]})")
    if os.path.exists(RUNLOG):
        with open(RUNLOG) as fh:
            lines = fh.readlines()
        print(f"  logged runs: {len(lines)}")
        for line in lines[-5:]:
            e = json.loads(line)
            print(f"    {e['ts'][:10]} n={e['target']} {e['outcome']} "
                  f"rank={e.get('rank')} score={e.get('score')}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("candidate")
    r.add_argument("--targets", default="2,3,4")
    r.add_argument("--time", type=float, default=300)
    r.add_argument("--seed", type=int, default=0)
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        run_candidate(args.candidate, args.targets.split(","), args.time, args.seed)
    else:
        status()


if __name__ == "__main__":
    main()
