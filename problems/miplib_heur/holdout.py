"""Overfitting check: run a solver on the HOLDOUT instances (never shown to the model) and compare with HiGHS default.

    python holdout.py best-miplib_heur/solver.py [--time 60] [--workers 3]
Prints per-instance gap vs baseline and the number of holdout wins; writes runs-miplib_heur/holdout.json.
A champion that wins on the train set but loses on holdout is tuned to instance names or signatures, not general.
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
from problems.miplib_heur import problem  # noqa: E402


def run(solver, t, secs, seed, out):
    env = dict(os.environ, PYTHONPATH=HERE + os.pathsep + os.environ.get("PYTHONPATH", ""))
    if os.path.exists(out):
        os.remove(out)
    try:
        subprocess.run(
            [sys.executable, solver, *problem.solver_argv(t, secs, seed, out)],
            capture_output=True,
            timeout=secs + 45,
            env=env,
        )
        v, _ = problem.evaluate(out, t)
        return t, v, ""
    except Exception as e:
        return t, None, f"{type(e).__name__}: {e}"[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("solver")
    ap.add_argument("--time", type=float, default=problem.DEFAULTS["time"])
    ap.add_argument("--workers", type=int, default=problem.DEFAULTS["workers"])
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rec = problem.records_load()
    wd = os.path.join(ROOT, "runs-miplib_heur", "holdout")
    os.makedirs(wd, exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda t: run(a.solver, t, a.time, a.seed, os.path.join(wd, t + ".json")), problem.HOLDOUT))
    wins, rows = [], {}
    for t, v, err in res:
        r = rec.get(t)
        win = v is not None and problem.beats(v, r)
        wins += [t] if win else []
        rows[t] = {"gap": v, "baseline": r, "win": win, "error": err}
        print(
            f"  {t:<28} ours={'FAIL ' + err if v is None else f'{v:.4%}':<14} highs={'none' if r is None else f'{r:.4%}':<10} {'WIN' if win else ''}"
        )
    out = {"solver": a.solver, "time": a.time, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "wins": wins, "rows": rows}
    json.dump(out, open(os.path.join(ROOT, "runs-miplib_heur", "holdout.json"), "w"), indent=1)
    print(f"holdout wins {len(wins)}/{len(problem.HOLDOUT)}: {' '.join(wins)}")


if __name__ == "__main__":
    main()
