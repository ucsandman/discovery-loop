"""The value to beat: plain HiGHS, default options except threads=2 and 1e-7 tolerances, saving the incumbent on exit.

    python baseline_solver.py --target air05 --time 60 --seed 1 --out sol.json
Same interface and output format as every evolved solver so the loop's evaluator can score it unchanged.
"""

import argparse
import json
import os
import sys

import highspy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from records import instance_path  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    h = highspy.Highs()
    h.silent()
    h.readModel(instance_path(a.target))
    lp = h.getLp()
    names = list(lp.col_names_)
    isint = (
        np.array([k != highspy.HighsVarType.kContinuous for k in lp.integrality_], bool)
        if len(lp.integrality_)
        else np.zeros(lp.num_col_, bool)
    )
    h.setOptionValue("threads", 2)
    h.setOptionValue("random_seed", int(a.seed) % (2**31 - 1))
    h.setOptionValue("mip_feasibility_tolerance", 1e-7)
    h.setOptionValue("primal_feasibility_tolerance", 1e-7)
    h.setOptionValue("time_limit", float(a.time))
    h.run()
    status = str(h.getModelStatus()).split(".")[-1]  # kOptimal here on a gap-0 instance means it is effectively closed
    if h.getInfo().primal_solution_status != highspy.SolutionStatus.kSolutionStatusFeasible:
        return
    x = np.array(h.getSolution().col_value)
    xr = np.where(isint, np.round(x), x)
    d = {
        "target": a.target,
        "obj": float(h.getInfo().objective_function_value),
        "status": status,
        "solution": {names[i]: (int(xr[i]) if isint[i] else float(xr[i])) for i in np.nonzero(xr)[0]},
    }
    tmp = a.out + ".tmp"
    json.dump(d, open(tmp, "w"))
    os.replace(tmp, a.out)


if __name__ == "__main__":
    main()
