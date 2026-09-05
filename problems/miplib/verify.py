"""Independent feasibility check of a MIPLIB solution.

Reads the instance with HiGHS but does all the arithmetic itself: variable bounds, integrality,
every row activity, and the objective (in the instance's own sense). Tolerance 1e-6 absolute-or-relative,
which is stricter than MIPLIB's own solution checker, so anything that passes here should pass there.

    python verify.py candidate.json      # {"target": name, "solution": {var: value}}
"""

import json
import os
import sys

import highspy
import numpy as np
import scipy.sparse as sp

if __package__:
    from .records import instance_path
else:  # direct ``python problems/miplib/verify.py`` compatibility
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from problems.miplib.records import instance_path

TOL = 1e-6


def load(name):
    h = highspy.Highs()
    h.silent()
    if h.readModel(instance_path(name)) != highspy.HighsStatus.kOk:
        raise RuntimeError(f"HiGHS could not read {name}")
    return h


def check(solution, name, tol=TOL):
    if not np.isfinite(tol) or tol < 0:
        raise ValueError("tolerance must be a finite non-negative number")
    if not isinstance(solution, dict):
        raise ValueError("solution must map variable names to numeric values")
    h = load(name)
    lp = h.getLp()
    n, m = lp.num_col_, lp.num_row_
    names = list(lp.col_names_)
    idx = {nm: i for i, nm in enumerate(names)}
    unknown = [k for k in solution if k not in idx]
    converted, nonfinite = {}, []
    for key, value in solution.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            nonfinite.append(key)
            continue
        if isinstance(value, bool) or not np.isfinite(number):
            nonfinite.append(key)
            continue
        converted[key] = number
    x = np.zeros(n)
    for k, v in converted.items():
        if k in idx:
            x[idx[k]] = v

    sense = "min" if h.getObjectiveSense()[1] == highspy.ObjSense.kMinimize else "max"
    if nonfinite:
        return {
            "feasible": False,
            "obj": None,
            "sense": sense,
            "bound_viol": float("inf"),
            "int_viol": float("inf"),
            "row_viol": float("inf"),
            "bound_excess": float("inf"),
            "int_excess": float("inf"),
            "row_excess": float("inf"),
            "unknown_vars": unknown[:5],
            "nonfinite_vars": nonfinite[:5],
            "cols": n,
            "rows": m,
            "tolerance": tol,
        }

    lo, up = np.array(lp.col_lower_), np.array(lp.col_upper_)
    finite_lo = np.where(np.isfinite(lo), np.abs(lo), 0.0)
    finite_up = np.where(np.isfinite(up), np.abs(up), 0.0)
    bound_scale = np.maximum.reduce((np.ones(n), np.abs(x), finite_lo, finite_up))
    bound_raw = np.maximum.reduce((np.zeros(n), lo - x, x - up))
    bound_viol = float(bound_raw.max()) if n else 0.0
    bound_excess = float(np.maximum(0.0, bound_raw - tol * bound_scale).max()) if n else 0.0

    kinds = list(lp.integrality_)
    isint = np.array([k != highspy.HighsVarType.kContinuous for k in kinds], bool) if kinds else np.zeros(n, bool)
    int_viol = float(np.abs(x[isint] - np.round(x[isint])).max()) if isint.any() else 0.0
    int_excess = max(0.0, int_viol - tol)

    A = lp.a_matrix_
    if A.format_ == highspy.MatrixFormat.kColwise:
        M = sp.csc_matrix((A.value_, A.index_, A.start_), shape=(m, n))
    else:
        M = sp.csr_matrix((A.value_, A.index_, A.start_), shape=(m, n))
    ax = M @ x
    rl, ru = np.array(lp.row_lower_), np.array(lp.row_upper_)
    finite_rl = np.where(np.isfinite(rl), np.abs(rl), 0.0)
    finite_ru = np.where(np.isfinite(ru), np.abs(ru), 0.0)
    row_scale = np.maximum.reduce((np.ones(m), np.abs(ax), finite_rl, finite_ru))
    row_raw = np.maximum.reduce((np.zeros(m), rl - ax, ax - ru))
    row_viol = float(row_raw.max()) if m else 0.0
    row_excess = float(np.maximum(0.0, row_raw - tol * row_scale).max()) if m else 0.0

    obj = float(np.dot(np.array(lp.col_cost_), x) + lp.offset_)
    feasible = not unknown and bound_excess <= 0 and int_excess <= 0 and row_excess <= 0 and np.isfinite(obj)
    return {
        "feasible": bool(feasible),
        "obj": obj,
        "sense": sense,
        "bound_viol": bound_viol,
        "int_viol": int_viol,
        "row_viol": row_viol,
        "bound_excess": bound_excess,
        "int_excess": int_excess,
        "row_excess": row_excess,
        "unknown_vars": unknown[:5],
        "nonfinite_vars": [],
        "cols": n,
        "rows": m,
        "tolerance": tol,
    }


def to_sol(solution, obj):
    """MIPLIB / SCIP .sol format: '=obj=' line, then 'name value' for every nonzero variable."""
    lines = [f"=obj= {obj:.15g}"]
    lines += [f"{k} {v:.15g}" for k, v in solution.items() if float(v) != 0.0]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    res = check(d["solution"], d["target"])
    print(json.dumps(res))
    sys.exit(0 if res["feasible"] else 1)
