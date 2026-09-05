"""Independent AC-OPF feasibility check for a PGLib-OPF case, numpy only.

A solution is {"vm": [pu per bus], "va": [radians per bus], "pg": [pu per gen row], "qg": [pu per gen row]} in the
case file's row order. Every constraint of the PGLib AC-OPF model is re-evaluated here, with MATPOWER conventions
(tap ratio, phase shift, line charging, bus shunts, out-of-service gens/branches). ``check`` defaults to the
legacy TOL = 1e-6; discovery evaluation and release validation explicitly pass 1e-8:

  voltage bounds, generator P/Q bounds (zero output for status 0), nodal P and Q balance at every bus,
  apparent-power thermal limit at both branch ends when rate_a > 0, angle-difference limits, reference angle 0.

The objective is the generator cost polynomial evaluated on MW (gencost model 2), summed over in-service gens.

    python verify.py candidate.json      # {"target": name, "solution": {...}}
"""

import json
import os
import sys

import numpy as np

if __package__:
    from . import matpower as mp
    from .records import case_path
else:  # direct ``python problems/pglib_opf/verify.py`` compatibility
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from problems.pglib_opf import matpower as mp
    from problems.pglib_opf.records import case_path

TOL = 1e-6
_CACHE = {}


def load_case(name):
    if name not in _CACHE:
        _CACHE[name] = mp.load(case_path(name))
    return _CACHE[name]


def admittances(case):
    """Ybus plus per-branch Yff/Yft/Ytf/Ytt (MATPOWER makeYbus) for in-service branches. Returns
    (Ybus, f, t, Yff, Yft, Ytf, Ytt, branch_rows) with f/t as 0-based bus positions."""
    bus, branch = case["bus"], case["branch"]
    base = case["baseMVA"]
    nb = bus.shape[0]
    pos = {int(b): i for i, b in enumerate(bus[:, mp.BUS_I])}
    on = np.flatnonzero(branch[:, mp.BR_STATUS] > 0)
    br = branch[on]
    f = np.array([pos[int(x)] for x in br[:, mp.F_BUS]])
    t = np.array([pos[int(x)] for x in br[:, mp.T_BUS]])
    ys = 1.0 / (br[:, mp.BR_R] + 1j * br[:, mp.BR_X])
    bc = br[:, mp.BR_B]
    tap = np.where(br[:, mp.TAP] == 0, 1.0, br[:, mp.TAP]) * np.exp(1j * np.deg2rad(br[:, mp.SHIFT]))
    ytt = ys + 1j * bc / 2
    yff = ytt / (tap * np.conj(tap))
    yft = -ys / np.conj(tap)
    ytf = -ys / tap
    ysh = (bus[:, mp.GS] + 1j * bus[:, mp.BS]) / base
    Y = np.zeros((nb, nb), dtype=complex)
    np.add.at(Y, (f, f), yff)
    np.add.at(Y, (f, t), yft)
    np.add.at(Y, (t, f), ytf)
    np.add.at(Y, (t, t), ytt)
    Y[np.arange(nb), np.arange(nb)] += ysh
    return Y, f, t, yff, yft, ytf, ytt, on


def objective(case, pg_pu):
    """$/h from gencost polynomials on MW, in-service generators only."""
    gen, cost, base = case["gen"], case["gencost"], case["baseMVA"]
    total = 0.0
    for i in range(gen.shape[0]):
        if gen[i, mp.GEN_STATUS] <= 0:
            continue
        if int(cost[i, mp.MODEL]) != 2:
            raise ValueError(f"gen {i}: only polynomial cost (model 2) is supported")
        n = int(cost[i, mp.NCOST])
        coef = cost[i, mp.COST : mp.COST + n]  # c(n-1) .. c0
        total += float(np.polyval(coef, pg_pu[i] * base))
    return total


def check(solution, name, tol=TOL):
    if not np.isfinite(tol) or tol < 0:
        raise ValueError("tolerance must be a finite non-negative number")
    case = load_case(name)
    bus, gen, branch, base = case["bus"], case["gen"], case["branch"], case["baseMVA"]
    nb, ng = bus.shape[0], gen.shape[0]
    vm, va, pg, qg = (np.asarray(solution[k], dtype=float) for k in ("vm", "va", "pg", "qg"))
    if vm.shape != (nb,) or va.shape != (nb,) or pg.shape != (ng,) or qg.shape != (ng,):
        raise ValueError(f"shape mismatch: need vm/va[{nb}] pg/qg[{ng}]")
    if not (
        np.all(np.isfinite(vm)) and np.all(np.isfinite(va)) and np.all(np.isfinite(pg)) and np.all(np.isfinite(qg))
    ):
        raise ValueError("non-finite values in solution")
    viol = []  # (amount, description)

    def bound(x, lo, hi, label):
        for i in np.flatnonzero((x < lo) | (x > hi)):
            viol.append((max(lo[i] - x[i], x[i] - hi[i]), f"{label}[{i}]={x[i]:.8g} not in [{lo[i]:.8g},{hi[i]:.8g}]"))

    bound(vm, bus[:, mp.VMIN], bus[:, mp.VMAX], "vm")
    on = gen[:, mp.GEN_STATUS] > 0
    bound(pg[on], gen[on, mp.PMIN] / base, gen[on, mp.PMAX] / base, "pg(on)")
    bound(qg[on], gen[on, mp.QMIN] / base, gen[on, mp.QMAX] / base, "qg(on)")
    for i in np.flatnonzero(~on):
        if abs(pg[i]) > 0 or abs(qg[i]) > 0:
            viol.append((max(abs(pg[i]), abs(qg[i])), f"gen[{i}] is out of service but dispatched"))
    ref = np.flatnonzero(bus[:, mp.BUS_TYPE] == 3)
    for i in ref:
        if abs(va[i]) > 0:
            viol.append((abs(va[i]), f"reference bus {int(bus[i, mp.BUS_I])} angle {va[i]:.3g} != 0"))

    Y, f, t, yff, yft, ytf, ytt, rows = admittances(case)
    V = vm * np.exp(1j * va)
    pos = {int(b): i for i, b in enumerate(bus[:, mp.BUS_I])}
    Sg = np.zeros(nb, dtype=complex)
    for i in range(ng):
        if on[i]:
            Sg[pos[int(gen[i, mp.GEN_BUS])]] += pg[i] + 1j * qg[i]
    Sd = (bus[:, mp.PD] + 1j * bus[:, mp.QD]) / base
    mis = Sg - Sd - V * np.conj(Y @ V)
    for i in np.flatnonzero(np.abs(mis.real) > 0):
        viol.append((abs(mis.real[i]), f"P balance at bus {int(bus[i, mp.BUS_I])} off by {mis.real[i]:.3g} pu"))
    for i in np.flatnonzero(np.abs(mis.imag) > 0):
        viol.append((abs(mis.imag[i]), f"Q balance at bus {int(bus[i, mp.BUS_I])} off by {mis.imag[i]:.3g} pu"))

    Vf, Vt = V[f], V[t]
    Sf = Vf * np.conj(yff * Vf + yft * Vt)
    St = Vt * np.conj(ytf * Vf + ytt * Vt)
    br = branch[rows]
    rate = br[:, mp.RATE_A] / base
    lim = rate > 0
    for k in np.flatnonzero(lim & (np.abs(Sf) > rate)):
        viol.append((abs(Sf[k]) - rate[k], f"branch {rows[k]} from-end |S|={abs(Sf[k]):.6g} > {rate[k]:.6g}"))
    for k in np.flatnonzero(lim & (np.abs(St) > rate)):
        viol.append((abs(St[k]) - rate[k], f"branch {rows[k]} to-end |S|={abs(St[k]):.6g} > {rate[k]:.6g}"))
    diff = np.rad2deg(np.angle(Vf * np.conj(Vt)))
    amin, amax = br[:, mp.ANGMIN], br[:, mp.ANGMAX]
    lo = (amin != 0) & (amin > -360)
    hi = (amax != 0) & (amax < 360)
    for k in np.flatnonzero(lo & (diff < amin)):
        viol.append((amin[k] - diff[k], f"branch {rows[k]} angle {diff[k]:.6g} deg < {amin[k]:.6g}"))
    for k in np.flatnonzero(hi & (diff > amax)):
        viol.append((diff[k] - amax[k], f"branch {rows[k]} angle {diff[k]:.6g} deg > {amax[k]:.6g}"))

    viol.sort(key=lambda v: -v[0])
    failures = [v for v in viol if v[0] > tol]
    raw_max = float(viol[0][0]) if viol else 0.0
    return {
        "feasible": not failures,
        "obj": objective(case, pg),
        "max_violation": raw_max,
        "max_excess": max(0.0, raw_max - tol),
        "worst": failures[0][1] if failures else "",
        "n_violations": len(failures),
        "tolerance": tol,
    }


def reference_polish(solution, name, tol=1e-8):
    """Run PYPOWER on the unmodified case, seeded from ``solution``, then independently recheck it."""
    from pypower.api import ppoption, runopf, runpf

    case = load_case(name)
    base = case["baseMVA"]
    gen = np.zeros((case["gen"].shape[0], 21))
    gen[:, : case["gen"].shape[1]] = case["gen"][:, :21]
    branch = np.zeros((case["branch"].shape[0], 17))
    branch[:, : case["branch"].shape[1]] = case["branch"][:, :17]
    ppc = {
        "version": "2",
        "baseMVA": base,
        "bus": case["bus"].copy(),
        "gen": gen,
        "branch": branch,
        "gencost": case["gencost"].copy(),
    }
    ppc["bus"][:, mp.VM] = np.asarray(solution["vm"], dtype=float)
    ppc["bus"][:, mp.VA] = np.rad2deg(np.asarray(solution["va"], dtype=float))
    ppc["gen"][:, mp.PG] = np.asarray(solution["pg"], dtype=float) * base
    ppc["gen"][:, mp.QG] = np.asarray(solution["qg"], dtype=float) * base
    options = ppoption(VERBOSE=0, OUT_ALL=0, OPF_ALG=560, PDIPM_FEASTOL=tol, PDIPM_MAX_IT=500)
    result = runopf(ppc, options)
    if not result.get("success"):
        return {"success": False, "error": "PYPOWER original-problem OPF did not converge"}
    pos = {int(bus): i for i, bus in enumerate(result["bus"][:, mp.BUS_I])}
    result["gen"][:, mp.VG] = [result["bus"][pos[int(bus)], mp.VM] for bus in result["gen"][:, mp.GEN_BUS]]
    result, success = runpf(
        result,
        ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=min(tol, 1e-10), PF_MAX_IT=50, ENFORCE_Q_LIMS=0),
    )
    if not success:
        return {"success": False, "error": "PYPOWER original-problem power-flow polish did not converge"}
    polished = {
        "vm": result["bus"][:, mp.VM].tolist(),
        "va": np.deg2rad(result["bus"][:, mp.VA]).tolist(),
        "pg": (result["gen"][:, mp.PG] / base).tolist(),
        "qg": (result["gen"][:, mp.QG] / base).tolist(),
    }
    checked = check(polished, name, tol=tol)
    return {
        "success": checked["feasible"],
        "solution": polished,
        "check": checked,
        "error": None if checked["feasible"] else "reference polish failed strict verification",
    }


def to_text(solution, value, name):
    case = load_case(name)
    base = case["baseMVA"]
    lines = [
        f"{name}: AC-OPF objective {value:.6f} $/h (verified feasible at {TOL} pu)",
        "",
        "gen  bus  Pg[MW]  Qg[MVAr]",
    ]
    for i, row in enumerate(case["gen"]):
        lines.append(
            f"{i:>3} {int(row[mp.GEN_BUS]):>4} {solution['pg'][i] * base:10.4f} {solution['qg'][i] * base:10.4f}"
        )
    lines += ["", "bus  Vm[pu]  Va[deg]"]
    for i, row in enumerate(case["bus"]):
        lines.append(f"{int(row[mp.BUS_I]):>4} {solution['vm'][i]:8.5f} {np.rad2deg(solution['va'][i]):9.4f}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    print(json.dumps(check(d["solution"], d["target"]), indent=1))
