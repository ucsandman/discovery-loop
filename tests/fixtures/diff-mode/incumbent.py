"""Seed primal heuristic: HiGHS incumbent, then adaptive LNS. Same shape as problems/miplib but tuned for a 60 s slot.

Phase 1: plain HiGHS for ~40% of the budget (default heuristics find the first incumbent fastest).
Phase 2: fix a random subset of the integer variables at the incumbent, re-solve the sub-MIP with a short time
limit, keep improvements; the fixed fraction adapts (widen when a sub-MIP is solved to optimality, tighten when
it times out).

    python seed_solver.py --target air05 --time 60 --seed 1 --out sol.json
writes {"target", "obj", "solution": {name: value}} (nonzeros only, integers rounded), atomically on every improvement.
"""

import argparse
import json
import os
import sys
import time

import highspy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # standalone use; the loop also sets PYTHONPATH
from records import instance_path  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    deadline = t0 + a.time
    rng = np.random.default_rng(a.seed)

    h = highspy.Highs()
    h.silent()
    h.readModel(instance_path(a.target))
    lp = h.getLp()
    n = lp.num_col_
    names = list(lp.col_names_)
    isint = (
        np.array([k != highspy.HighsVarType.kContinuous for k in lp.integrality_], bool)
        if len(lp.integrality_)
        else np.zeros(n, bool)
    )
    int_idx = np.nonzero(isint)[0].astype(np.int32)
    lo0, up0 = np.array(lp.col_lower_), np.array(lp.col_upper_)
    sense = 1.0 if h.getObjectiveSense()[1] == highspy.ObjSense.kMinimize else -1.0
    h.setOptionValue("threads", 2)
    h.setOptionValue("random_seed", int(a.seed) % (2**31 - 1))
    h.setOptionValue("mip_feasibility_tolerance", 1e-7)
    h.setOptionValue("primal_feasibility_tolerance", 1e-7)

    best = {"x": None, "obj": None}

    def save(x, obj):
        xr = np.where(isint, np.round(x), x)
        d = {
            "target": a.target,
            "obj": float(obj),
            "solution": {names[i]: (int(xr[i]) if isint[i] else float(xr[i])) for i in np.nonzero(xr)[0]},
        }
        tmp = a.out + ".tmp"
        json.dump(d, open(tmp, "w"))
        os.replace(tmp, a.out)

    def take():
        info = h.getInfo()
        if info.primal_solution_status != highspy.SolutionStatus.kSolutionStatusFeasible:
            return False
        obj = info.objective_function_value
        if best["obj"] is None or sense * obj < sense * best["obj"] - 1e-9:
            best["x"] = np.array(h.getSolution().col_value)
            best["obj"] = obj
            save(best["x"], obj)
            return True
        return False

    # phase 1: plain solve
    h.setOptionValue("time_limit", max(5.0, 0.4 * a.time))
    h.run()
    take()
    if h.getModelStatus() == highspy.HighsModelStatus.kOptimal or best["x"] is None or len(int_idx) == 0:
        return

    # phase 2: adaptive LNS around the incumbent
    fix = 0.8
    while time.time() < deadline - 2:
        k = int(fix * len(int_idx))
        chosen = rng.choice(int_idx, size=k, replace=False).astype(np.int32)
        vals = np.round(best["x"][chosen])
        h.changeColsBounds(len(chosen), chosen, vals, vals)
        remaining = deadline - time.time()
        h.setOptionValue("time_limit", float(max(1.0, min(10.0, remaining - 1))))
        try:
            s = highspy.HighsSolution()
            s.col_value = list(best["x"])
            h.setSolution(s)
        except Exception:
            pass
        h.run()
        improved = take()
        status = h.getModelStatus()
        h.changeColsBounds(len(chosen), chosen, lo0[chosen], up0[chosen])
        if improved:
            continue
        if status == highspy.HighsModelStatus.kOptimal or status == highspy.HighsModelStatus.kInfeasible:
            fix = max(0.2, fix - 0.05)  # neighbourhood exhausted: widen it
        else:
            fix = min(0.95, fix + 0.05)  # timed out: tighten it


if __name__ == "__main__":
    main()
