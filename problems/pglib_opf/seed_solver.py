"""Seed AC-OPF solver: PYPOWER's primal-dual interior point method (PIPS), then random multi-start.

Phase 1: solve the case from the file's start point with tight tolerances; re-solve with slightly shrunk limits if
the independent verifier rejects it at 1e-8, and fall back to a tight warm PIPS re-solve without the Newton polish.
Phase 2: until the time budget, restart PIPS from perturbed voltages/dispatch and keep the best verified solution.

    python seed_solver.py --target pglib_opf_case14_ieee --time 60 --seed 1 --out sol.json
writes {"target", "obj", "solution": {"vm", "va", "pg", "qg"}} (pu, radians), saved atomically on every improvement.
"""

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # standalone use; the loop also sets PYTHONPATH
import matpower as mp  # noqa: E402
import verify  # noqa: E402
from records import case_path  # noqa: E402

RELEASE_TOL = (
    1e-8  # the loop verifies at this tolerance (problem.RELEASE_FEASIBILITY_TOL); saving looser is a wasted run
)


def to_ppc(case):
    """MATPOWER dict -> PYPOWER case dict (gen padded to 21 and branch to 17 columns as PYPOWER expects)."""
    gen = np.zeros((case["gen"].shape[0], 21))
    gen[:, : case["gen"].shape[1]] = case["gen"][:, :21]
    branch = np.zeros((case["branch"].shape[0], 17))
    branch[:, : case["branch"].shape[1]] = case["branch"][:, :17]
    return {
        "version": "2",
        "baseMVA": case["baseMVA"],
        "bus": case["bus"].copy(),
        "gen": gen,
        "branch": branch,
        "gencost": case["gencost"].copy(),
    }


def shrink(ppc, eps):
    """Tighten every inequality by eps (pu / MW / MVA) so PIPS's own tolerance lands inside the verifier's."""
    p = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in ppc.items()}
    base = p["baseMVA"]
    p["bus"][:, mp.VMAX] -= eps
    p["bus"][:, mp.VMIN] += eps
    on = p["gen"][:, mp.GEN_STATUS] > 0
    p["gen"][on, mp.PMAX] -= eps * base
    p["gen"][on, mp.PMIN] += eps * base
    p["gen"][on, mp.QMAX] -= eps * base
    p["gen"][on, mp.QMIN] += eps * base
    lim = p["branch"][:, mp.RATE_A] > 0
    p["branch"][lim, mp.RATE_A] -= eps * base
    return p


def _opf(ppc, feastol):
    from pypower.api import ppoption, runopf

    opt = ppoption(
        VERBOSE=0,
        OUT_ALL=0,
        OPF_ALG=560,
        PDIPM_FEASTOL=feastol,
        PDIPM_GRADTOL=min(1e-6, feastol * 100),
        PDIPM_COMPTOL=min(1e-6, feastol * 100),
        PDIPM_MAX_IT=500,
    )
    r = runopf(ppc, opt)
    return r if r["success"] else None


def _polish(r):
    """Newton power flow from the OPF point so nodal balance holds to 1e-10; keeps Pg and gen-bus Vm, so cost is
    unchanged. The mismatch it absorbs lands on the slack generator and the Qg of PV buses, which shrink() covers
    on small cases; on 2,000+ buses that shift can exceed a limit, so the caller also tries the unpolished point."""
    from pypower.api import ppoption, runpf

    pos = {int(b): i for i, b in enumerate(r["bus"][:, mp.BUS_I])}
    r["gen"][:, mp.VG] = [r["bus"][pos[int(b)], mp.VM] for b in r["gen"][:, mp.GEN_BUS]]
    pf, ok = runpf(r, ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=1e-10, PF_MAX_IT=50, ENFORCE_Q_LIMS=0))
    return pf if ok else None


def _sol(r):
    base = r["baseMVA"]
    return {
        "vm": r["bus"][:, mp.VM].tolist(),
        "va": np.deg2rad(r["bus"][:, mp.VA]).tolist(),
        "pg": (r["gen"][:, mp.PG] / base).tolist(),
        "qg": (r["gen"][:, mp.QG] / base).tolist(),
    }


def solve(ppc, feastol=1e-7):
    """PIPS OPF then the Newton polish; None when PIPS does not converge."""
    r = _opf(ppc, feastol)
    if r is None:
        return None
    return _sol(_polish(r) or r)


def solve_both(ppc, feastol):
    """One tight PIPS run, returned as [polished, unpolished] candidates; the caller keeps whichever verifies."""
    r = _opf(ppc, feastol)
    if r is None:
        return []
    pf = _polish(r)
    return ([_sol(pf)] if pf is not None else []) + [_sol(r)]


def warm(ppc, sol):
    """Copy of ppc whose start point is a solution (pu, radians), so PIPS resumes from it."""
    p = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in ppc.items()}
    base = p["baseMVA"]
    p["bus"][:, mp.VM] = sol["vm"]
    p["bus"][:, mp.VA] = np.rad2deg(sol["va"])
    p["gen"][:, mp.PG] = np.asarray(sol["pg"]) * base
    p["gen"][:, mp.QG] = np.asarray(sol["qg"]) * base
    return p


def perturb(ppc, rng, scale):
    p = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in ppc.items()}
    bus, gen = p["bus"], p["gen"]
    bus[:, mp.VM] = np.clip(bus[:, mp.VM] + rng.normal(0, 0.03 * scale, bus.shape[0]), bus[:, mp.VMIN], bus[:, mp.VMAX])
    bus[:, mp.VA] += rng.normal(0, 5.0 * scale, bus.shape[0])
    on = gen[:, mp.GEN_STATUS] > 0
    span = gen[on, mp.PMAX] - gen[on, mp.PMIN]
    gen[on, mp.PG] = np.clip(
        gen[on, mp.PG] + rng.normal(0, 0.3 * scale, on.sum()) * span, gen[on, mp.PMIN], gen[on, mp.PMAX]
    )
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=90)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(a.seed)
    case = mp.load(case_path(a.target))
    ppc = to_ppc(case)
    best = None

    def save(sol, obj):
        tmp = a.out + ".tmp"
        json.dump({"target": a.target, "obj": obj, "solution": sol}, open(tmp, "w"))
        os.replace(tmp, a.out)

    def attempt(p):
        nonlocal best
        for eps in (0.0, 2e-6, 1e-5):
            sol = solve(shrink(p, eps) if eps else p)
            if sol is None:
                continue
            res = verify.check(sol, a.target, tol=RELEASE_TOL)
            if not res["feasible"]:
                # A tight warm PIPS re-solve from the same point. Small cases pass after its polish (case118:
                # 1.9e-9); on 2,000+ buses the polish dumps the mismatch onto the slack and breaks a limit while
                # the unpolished point verifies at 8e-13 (case2000_goc, 2026-09-17, 28 s), so both are tried.
                checked = [
                    (verify.check(c, a.target, tol=RELEASE_TOL), c)
                    for c in solve_both(warm(shrink(p, eps) if eps else p, sol), feastol=1e-9)
                ]
                pick = min((rc for rc in checked if rc[0]["feasible"]), key=lambda rc: rc[0]["obj"], default=None)
                if pick is None:
                    continue
                res, sol = pick
            if res["feasible"]:
                if best is None or res["obj"] < best:
                    best = res["obj"]
                    save(sol, best)
                return res["obj"]
        return None

    attempt(ppc)
    # The worker kills the process at --time + 45 s and keeps nothing it wrote, so an attempt that cannot finish
    # before the budget is never started: on 2,000+ buses one attempt is two to three minutes.
    longest = time.time() - t0
    tries = 0
    while time.time() - t0 + 1.25 * longest < a.time - 5:
        tries += 1
        t1 = time.time()
        attempt(perturb(ppc, rng, scale=1.0 if tries % 3 else 2.5))
        longest = max(longest, time.time() - t1)
        if best is None and tries > 20:
            break
    print(f"best={best} tries={tries} secs={time.time() - t0:.1f} longest_attempt={longest:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
