"""Measure the value to beat, on this machine, under the loop's own conditions (3 solvers in parallel, 2 threads each).

    python baseline.py --screen --max-vars 20000 --max-rows 20000 --limit 60   # pick candidates from the MIPLIB table
    python baseline.py --measure                                              # run baseline_solver on every candidate
    python baseline.py --assign --train 20 --holdout 10                       # choose train/holdout, write baseline.json

baseline.json: {instance: {"obj", "gap", "opt", "sense", "secs", "set": "train"|"holdout"|"reject", "note"}}
A candidate is useful when HiGHS finds a feasible point within the slot but does not prove optimality (gap > 0):
that is exactly the room a better primal heuristic can claim. Instances HiGHS solves to optimality carry no
signal; instances where it finds nothing are kept only as holdout material.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from problems.miplib_heur import records, verify  # noqa: E402

CAND = os.path.join(HERE, "candidates.json")
WORK = os.path.join(os.path.dirname(os.path.dirname(HERE)), "tmp", "miplib_heur_baseline")


def screen(a):
    table = records.benchmark_table()
    opt = records.optima()
    keep = {}
    for name, s in table.items():
        if name not in opt or s["vars"] > a.max_vars or s["rows"] > a.max_rows or s["nonz"] > a.max_nonz:
            continue
        keep[name] = s
    names = sorted(keep, key=lambda k: keep[k]["nonz"])[: a.limit]
    json.dump(names, open(CAND, "w"), indent=1)
    print(f"{len(keep)} instances fit the size filter; kept the {len(names)} smallest by nonzeros -> {CAND}")


def run_one(name, secs, seed):
    out = os.path.join(WORK, f"{name}.json")
    if os.path.exists(out):
        os.remove(out)
    records.instance_path(name)  # download before the clock starts
    t0 = time.time()
    try:
        subprocess.run(
            [
                sys.executable,
                os.path.join(HERE, "baseline_solver.py"),
                "--target",
                name,
                "--time",
                str(secs),
                "--seed",
                str(seed),
                "--out",
                out,
            ],
            capture_output=True,
            timeout=secs + 45,
        )
    except subprocess.TimeoutExpired:
        return name, {"obj": None, "gap": None, "note": "baseline_solver hung past the hard kill"}
    if not os.path.exists(out):
        return name, {
            "obj": None,
            "gap": None,
            "opt": opt_of(name),
            "secs": round(time.time() - t0, 1),
            "note": "HiGHS found no feasible point in the slot",
        }
    d = json.load(open(out))
    r = verify.check(d["solution"], name)
    if not r["feasible"]:
        return name, {
            "obj": r["obj"],
            "gap": None,
            "opt": r["optimum"],
            "secs": round(time.time() - t0, 1),
            "note": "HiGHS incumbent failed the 1e-6 checker: " + json.dumps(r)[:160],
        }
    return name, {
        "obj": r["obj"],
        "gap": r["gap"],
        "opt": r["optimum"],
        "sense": r["sense"],
        "secs": round(time.time() - t0, 1),
        "note": "",
    }


def opt_of(name):
    try:
        return records.opt(name)
    except KeyError:
        return None


def measure(a):
    os.makedirs(WORK, exist_ok=True)
    names = json.load(open(CAND))
    res_path = os.path.join(WORK, "measured.json")
    res = json.load(open(res_path)) if os.path.exists(res_path) else {}
    todo = [n for n in names if n not in res]
    print(f"measuring {len(todo)} of {len(names)} candidates, {a.secs}s each, {a.workers} in parallel", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for name, r in ex.map(lambda n: run_one(n, a.secs, a.seed), todo):
            res[name] = r
            json.dump(res, open(res_path, "w"), indent=1)  # incremental: a crash keeps what was measured
            gap = "none" if r["gap"] is None else f"{r['gap']:.4%}"
            print(f"  {name:<28} gap={gap:<10} {r['note']}", flush=True)
    print(f"-> {res_path}")


def assign(a):
    res = json.load(open(os.path.join(WORK, "measured.json")))
    useful = sorted(
        (n for n, r in res.items() if r["gap"] is not None and r["gap"] > a.min_gap), key=lambda n: -res[n]["gap"]
    )
    none = [n for n, r in res.items() if r["gap"] is None and r.get("opt") is not None and "checker" not in r["note"]]
    train = useful[0::2][: a.train] if len(useful) >= a.train + a.holdout else useful[: a.train]
    rest = [n for n in useful if n not in train]
    holdout = (rest + none)[: a.holdout]
    out = {}
    for n, r in res.items():
        out[n] = dict(r, set="train" if n in train else "holdout" if n in holdout else "reject")
    json.dump(out, open(records.BASELINE, "w"), indent=1)
    print(f"train {len(train)}: {' '.join(train)}\nholdout {len(holdout)}: {' '.join(holdout)}\n-> {records.BASELINE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--assign", action="store_true")
    ap.add_argument("--max-vars", type=int, default=20000)
    ap.add_argument("--max-rows", type=int, default=20000)
    ap.add_argument("--max-nonz", type=int, default=200000)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--secs", type=float, default=60)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--min-gap", type=float, default=1e-3)
    ap.add_argument("--train", type=int, default=20)
    ap.add_argument("--holdout", type=int, default=10)
    a = ap.parse_args()
    if a.screen:
        screen(a)
    if a.measure:
        measure(a)
    if a.assign:
        assign(a)


if __name__ == "__main__":
    main()
