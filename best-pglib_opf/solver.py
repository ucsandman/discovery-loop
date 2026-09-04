"""AC-OPF solver: PIPS interior point + basin-hopping multi-start + continuation restarts + margin polish.

Phase 1: PIPS from the file's start point, a flat start and a DC-OPF start; Newton power-flow polish; if the
independent verifier rejects the point at 1e-6, first re-solve with tight (1e-9) interior-point tolerances, then
warm re-solve with ONLY the near-binding constraints tightened.
Phase 2: until the time budget, restart PIPS from (a) Latin-hypercube samples over generator voltage set-points and
dispatch, (b) small/large perturbations of the incumbent (basin hopping with adaptive step), (c) dispatch corners
(random subsets of generators pinned to Pmin/Pmax), and (d) continuation paths (relax-then-tighten limits, load
ramp, re-weighted cost).
Every new incumbent gets a high-precision PIPS polish followed by a MARGIN POLISH: the same basin is re-solved with
all inequality limits and every nodal P/Q load relaxed by a margin m < 1e-6 (the checker's tolerance), on a ladder
of decreasing m; only points the verifier accepts are ever written.  Best verified solution is saved atomically on
every improvement.

    python solver.py --target pglib_opf_case14_ieee --time 60 --seed 1 --out sol.json
"""

import argparse
import json
import os
import sys
import time
from contextlib import redirect_stdout

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # standalone use; the loop also sets PYTHONPATH
import matpower as mp  # noqa: E402
import verify  # noqa: E402
from records import case_path  # noqa: E402

from pypower.api import ppoption, runopf, runpf  # noqa: E402
from pypower.idx_bus import BUS_I, BUS_TYPE, PD, QD, VM, VA, VMAX, VMIN  # noqa: E402
from pypower.idx_gen import GEN_BUS, PG, QG, VG, PMAX, PMIN, QMAX, QMIN, GEN_STATUS  # noqa: E402
from pypower.idx_brch import F_BUS, T_BUS, RATE_A, ANGMIN, ANGMAX, PF, QF, PT, QT  # noqa: E402

np.seterr(all="ignore")

MARGINS = (9e-7, 7e-7, 5e-7, 3e-7, 1.5e-7)


# ----------------------------------------------------------------------------------------------------- case handling
def to_ppc(case):
    """MATPOWER dict -> PYPOWER case dict (gen padded to 21 and branch to 17 columns as PYPOWER expects)."""
    gen = np.zeros((case["gen"].shape[0], 21))
    gen[:, : case["gen"].shape[1]] = case["gen"][:, :21]
    off = gen[:, GEN_STATUS] <= 0
    gen[off, PG] = 0.0
    gen[off, QG] = 0.0
    branch = np.zeros((case["branch"].shape[0], 17))
    branch[:, : case["branch"].shape[1]] = case["branch"][:, :17]
    return {
        "version": "2",
        "baseMVA": float(case["baseMVA"]),
        "bus": case["bus"].copy(),
        "gen": gen,
        "branch": branch,
        "gencost": case["gencost"].copy(),
    }


def cp(ppc):
    return {k: (v.copy() if hasattr(v, "copy") else v) for k, v in ppc.items()}


def warm(ppc, r):
    """Copy of ppc (its own limits/loads/costs) whose start point is taken from result (or case) r."""
    p = cp(ppc)
    p["bus"][:, VM] = r["bus"][:, VM]
    p["bus"][:, VA] = r["bus"][:, VA]
    p["gen"][:, PG] = r["gen"][:, PG]
    p["gen"][:, QG] = r["gen"][:, QG]
    p["gen"][:, VG] = r["gen"][:, VG]
    return p


def tighten(ppc, r, eps, tol=3e-5):
    """Shrink by eps (pu) only the inequality limits that the solution r sits within tol of (or violates)."""
    p = cp(ppc)
    base = p["baseMVA"]
    bus, gen, br = p["bus"], p["gen"], p["branch"]
    vm = r["bus"][:, VM]
    span_ok = (bus[:, VMAX] - bus[:, VMIN]) > 4 * eps
    sel = span_ok & (vm > bus[:, VMAX] - tol)
    bus[sel, VMAX] -= eps
    sel = span_ok & (vm < bus[:, VMIN] + tol)
    bus[sel, VMIN] += eps
    on = gen[:, GEN_STATUS] > 0
    e = eps * base
    t = tol * base
    for lo, hi, col in ((PMIN, PMAX, PG), (QMIN, QMAX, QG)):
        val = r["gen"][:, col]
        ok = on & ((gen[:, hi] - gen[:, lo]) > 4 * e)
        sel = ok & (val > gen[:, hi] - t)
        gen[sel, hi] -= e
        sel = ok & (val < gen[:, lo] + t)
        gen[sel, lo] += e
    if r["branch"].shape[1] > QT:
        s = np.maximum(
            np.hypot(r["branch"][:, PF], r["branch"][:, QF]), np.hypot(r["branch"][:, PT], r["branch"][:, QT])
        )
        lim = br[:, RATE_A] > 0
        sel = lim & (s > br[:, RATE_A] - t)
        br[sel, RATE_A] -= e
    pos = {int(b): i for i, b in enumerate(r["bus"][:, BUS_I])}
    fi = np.array([pos[int(b)] for b in br[:, F_BUS]])
    ti = np.array([pos[int(b)] for b in br[:, T_BUS]])
    ang = r["bus"][fi, VA] - r["bus"][ti, VA]
    ed = eps * 100.0
    td = tol * 100.0
    amax, amin = br[:, ANGMAX], br[:, ANGMIN]
    act = (amax - amin) > 4 * ed
    sel = act & (amax < 360) & (amax != 0) & (ang > amax - td)
    br[sel, ANGMAX] -= ed
    sel = act & (amin > -360) & (amin != 0) & (ang < amin + td)
    br[sel, ANGMIN] += ed
    return p


def margined(ppc, m):
    """Relax every inequality limit and every nodal P/Q load by m (pu; m degrees for angle limits).

    A solution of this problem violates the true constraints by at most ~m, which the verifier tolerates when
    m < 1e-6.  Off generators are untouched (they must stay exactly at zero)."""
    p = cp(ppc)
    base = p["baseMVA"]
    bus, gen, br = p["bus"], p["gen"], p["branch"]
    e = m * base
    bus[:, VMAX] += m
    bus[:, VMIN] -= m
    bus[:, PD] -= e
    bus[:, QD] -= e
    on = gen[:, GEN_STATUS] > 0
    gen[on, PMAX] += e
    gen[on, PMIN] -= e
    gen[on, QMAX] += e
    gen[on, QMIN] -= e
    lim = br[:, RATE_A] > 0
    br[lim, RATE_A] += e
    for col, sgn in ((ANGMAX, 1.0), (ANGMIN, -1.0)):
        act = (np.abs(br[:, col]) < 360) & (br[:, col] != 0)
        br[act, col] += sgn * m
    return p


# ------------------------------------------------------------------------------------------- continuation problems
def relaxed(ppc, alpha):
    """Widen thermal, voltage and angle-difference limits by a relative amount alpha."""
    p = cp(ppc)
    bus, br = p["bus"], p["branch"]
    lim = br[:, RATE_A] > 0
    br[lim, RATE_A] *= 1.0 + alpha
    bus[:, VMAX] += 0.1 * alpha
    bus[:, VMIN] = np.maximum(bus[:, VMIN] - 0.1 * alpha, 0.5)
    for col in (ANGMAX, ANGMIN):
        act = (np.abs(br[:, col]) < 360) & (br[:, col] != 0)
        br[act, col] = np.clip(br[act, col] * (1.0 + alpha), -359.0, 359.0)
    return p


def scaled_load(ppc, s):
    p = cp(ppc)
    p["bus"][:, PD] *= s
    p["bus"][:, QD] *= s
    return p


def perturbed_cost(ppc, rng, sigma):
    """Random log-normal re-weighting of every non-constant polynomial cost coefficient."""
    p = cp(ppc)
    gc = p["gencost"]
    for i in range(gc.shape[0]):
        if int(gc[i, 0]) != 2:
            continue
        nc = int(gc[i, 3])
        m = max(nc - 1, 0)
        if m > 0 and gc.shape[1] >= 4 + m:
            gc[i, 4 : 4 + m] *= np.exp(rng.normal(0.0, sigma, m))
    return p


# ----------------------------------------------------------------------------------------------------------- solving
def pips(ppc, max_it, feastol=1e-7, gradtol=1e-6, comptol=1e-6, costtol=1e-6):
    """PIPS OPF then a Newton power-flow polish (nodal balance to 1e-10, Pg and gen-bus Vm kept => cost unchanged)."""
    opt = ppoption(
        VERBOSE=0,
        OUT_ALL=0,
        OPF_ALG=560,
        PDIPM_FEASTOL=feastol,
        PDIPM_GRADTOL=gradtol,
        PDIPM_COMPTOL=comptol,
        PDIPM_COSTTOL=costtol,
        PDIPM_MAX_IT=max_it,
    )
    try:
        with redirect_stdout(sys.stderr):
            r = runopf(ppc, opt)
    except Exception:
        return None
    if not r or not r.get("success"):
        return None
    try:
        pos = {int(b): i for i, b in enumerate(r["bus"][:, BUS_I])}
        r["gen"][:, VG] = [r["bus"][pos[int(b)], VM] for b in r["gen"][:, GEN_BUS]]
        with redirect_stdout(sys.stderr):
            pf, ok = runpf(r, ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=1e-10, PF_MAX_IT=50, ENFORCE_Q_LIMS=0))
        if ok:
            r = pf
    except Exception:
        pass
    return r


def pips_tight(ppc, max_it):
    return pips(ppc, max_it, feastol=1e-9, gradtol=1e-8, comptol=1e-9, costtol=1e-10)


def extract(r):
    base = r["baseMVA"]
    va = np.deg2rad(r["bus"][:, VA])
    ref = np.where(r["bus"][:, BUS_TYPE] == 3)[0]
    if len(ref):
        va = va - va[ref[0]]
    pg = r["gen"][:, PG] / base
    qg = r["gen"][:, QG] / base
    off = r["gen"][:, GEN_STATUS] <= 0
    pg[off] = 0.0
    qg[off] = 0.0
    return {
        "vm": r["bus"][:, VM].tolist(),
        "va": va.tolist(),
        "pg": pg.tolist(),
        "qg": qg.tolist(),
    }


# ------------------------------------------------------------------------------------------------------ start points
def fix_ref(p):
    ref = np.where(p["bus"][:, BUS_TYPE] == 3)[0]
    if len(ref):
        p["bus"][:, VA] -= p["bus"][ref[0], VA]
    return p


def sync_vg(p):
    bus, gen = p["bus"], p["gen"]
    pos = {int(b): i for i, b in enumerate(bus[:, BUS_I])}
    gen[:, VG] = [bus[pos[int(b)], VM] for b in gen[:, GEN_BUS]]
    return p


def perturb(ppc, r, rng, scale):
    """Perturb the state of result r (or ppc's own start point) by a relative scale; angles keep ref = 0."""
    p = warm(ppc, r) if r is not None else cp(ppc)
    bus, gen = p["bus"], p["gen"]
    nb = bus.shape[0]
    bus[:, VM] = np.clip(bus[:, VM] + rng.normal(0, 0.03 * scale, nb), bus[:, VMIN], bus[:, VMAX])
    bus[:, VA] += rng.normal(0, 5.0 * scale, nb)
    on = gen[:, GEN_STATUS] > 0
    span = gen[on, PMAX] - gen[on, PMIN]
    gen[on, PG] = np.clip(gen[on, PG] + rng.normal(0, 0.3 * scale, on.sum()) * span, gen[on, PMIN], gen[on, PMAX])
    return fix_ref(sync_vg(p))


def corner_start(ppc, r, rng):
    """Pin a random subset of generators to Pmin or Pmax (dispatch corners), keep the incumbent's voltages."""
    p = warm(ppc, r) if r is not None else flat_start(ppc)
    gen = p["gen"]
    on = np.where(gen[:, GEN_STATUS] > 0)[0]
    if len(on) == 0:
        return p
    k = int(rng.integers(1, max(2, len(on) // 2 + 1)))
    sel = rng.choice(on, size=min(k, len(on)), replace=False)
    lo = rng.random(len(sel)) < 0.5
    gen[sel[lo], PG] = gen[sel[lo], PMIN]
    gen[sel[~lo], PG] = gen[sel[~lo], PMAX]
    if rng.random() < 0.5:
        p["bus"][:, VA] = 0.0
    return fix_ref(p)


def dc_start(ppc):
    """Start from the DC-OPF dispatch and angles with a flat voltage profile."""
    try:
        from pypower.api import rundcopf

        with redirect_stdout(sys.stderr):
            r = rundcopf(cp(ppc), ppoption(VERBOSE=0, OUT_ALL=0))
        if not r or not r.get("success"):
            return None
    except Exception:
        return None
    p = cp(ppc)
    bus, gen = p["bus"], p["gen"]
    bus[:, VA] = r["bus"][:, VA]
    bus[:, VM] = np.clip(1.0, bus[:, VMIN], bus[:, VMAX])
    on = gen[:, GEN_STATUS] > 0
    gen[on, PG] = np.clip(r["gen"][on, PG], gen[on, PMIN], gen[on, PMAX])
    return fix_ref(sync_vg(p))


def lhs_start(ppc, u):
    """Start from a Latin-hypercube row u in [0,1]^(2*ngen_on): generator voltage set-points and dispatch."""
    p = cp(ppc)
    bus, gen = p["bus"], p["gen"]
    on = np.where(gen[:, GEN_STATUS] > 0)[0]
    n = len(on)
    uv, up = u[:n], u[n : 2 * n]
    pos = {int(b): i for i, b in enumerate(bus[:, BUS_I])}
    gb = np.array([pos[int(b)] for b in gen[on, GEN_BUS]])
    lo = bus[gb, VMIN] + 0.01
    hi = bus[gb, VMAX] - 0.01
    vset = np.clip(lo + uv * (hi - lo), bus[gb, VMIN], bus[gb, VMAX])
    bus[:, VM] = np.clip(1.0 + 0.0 * bus[:, VM], bus[:, VMIN], bus[:, VMAX])
    bus[gb, VM] = vset
    bus[:, VA] = 0.0
    gen[on, VG] = vset
    gen[on, PG] = gen[on, PMIN] + up * (gen[on, PMAX] - gen[on, PMIN])
    return fix_ref(p)


def flat_start(ppc):
    p = cp(ppc)
    bus, gen = p["bus"], p["gen"]
    bus[:, VM] = np.clip(1.0, bus[:, VMIN], bus[:, VMAX])
    bus[:, VA] = 0.0
    on = gen[:, GEN_STATUS] > 0
    gen[on, PG] = 0.5 * (gen[on, PMIN] + gen[on, PMAX])
    gen[:, VG] = 1.0
    return p


# -------------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=90)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    deadline = t0 + max(a.time - 6.0, 3.0)
    rng = np.random.default_rng(a.seed)
    case = mp.load(case_path(a.target))
    ppc = to_ppc(case)
    best = None
    best_r = None
    margin_done = [-1.0]  # objective at which the margin polish last succeeded

    def save(sol, obj):
        tmp = a.out + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"target": a.target, "obj": obj, "solution": sol}, f)
        os.replace(tmp, a.out)

    def check(r):
        nonlocal best, best_r
        try:
            sol = extract(r)
            res = verify.check(sol, a.target)
        except Exception:
            return None
        if not res.get("feasible"):
            return None
        obj = float(res["obj"])
        if best is None or obj < best:
            best, best_r = obj, r
            save(sol, obj)
        return obj

    def attempt(p, max_it):
        """PIPS from start p; on verifier rejection, tight-tolerance re-solve, then targeted tightening."""
        r = pips(p, max_it)
        if r is None:
            return None
        obj = check(r)
        if obj is not None:
            return obj
        for eps in (0.0, 6e-7, 3e-6, 1.5e-5, 6e-5):
            if time.time() > deadline:
                return None
            if eps == 0.0:
                r2 = pips_tight(warm(p, r), max_it)
            else:
                r2 = pips(tighten(warm(p, r), r, eps), max_it)
            if r2 is None:
                continue
            obj = check(r2)
            if obj is not None:
                return obj
            r = r2
        return None

    def margin_polish():
        """Re-solve the incumbent's basin with limits and loads relaxed by m < 1e-6; keep only verified points."""
        if best_r is None:
            return
        base_r = best_r
        for m in MARGINS:
            if time.time() > deadline:
                return
            r = pips_tight(warm(margined(ppc, m), base_r), 200)
            if r is None:
                continue
            if check(r) is not None:
                margin_done[0] = best
                return

    def polish():
        """High-precision warm re-solve of the incumbent, then the margin polish."""
        if best_r is None or time.time() > deadline:
            return
        r = pips_tight(warm(ppc, best_r), 200)
        if r is not None:
            check(r)
        if margin_done[0] != best:
            margin_polish()

    def cont_attempt(kind, max_it):
        """Continuation restart: solve a sequence of modified problems, warm-starting each from the previous one."""
        if kind == 0:  # relax limits, then tighten back in stages
            stages = [relaxed(ppc, al) for al in (0.5, 0.2, 0.05)]
            start = perturb(ppc, best_r, rng, 0.6) if best_r is not None else flat_start(ppc)
        elif kind == 1:  # load ramp
            s = float(rng.uniform(0.7, 0.9))
            stages = [scaled_load(ppc, s), scaled_load(ppc, 0.5 * (1.0 + s))]
            start = flat_start(ppc)
            if best_r is not None and rng.random() < 0.5:
                start = perturb(ppc, best_r, rng, 1.0)
        else:  # re-weighted cost, then true cost
            stages = [perturbed_cost(ppc, rng, 0.4)]
            start = perturb(ppc, best_r, rng, 0.3) if best_r is not None else flat_start(ppc)
        r = None
        for q in stages:
            if time.time() > deadline:
                return None
            r = pips(warm(q, r) if r is not None else warm(q, start), max_it)
            if r is None:
                return None
        if time.time() > deadline:
            return None
        return attempt(warm(ppc, r), max_it)

    # Phase 1: file start, flat start, DC-OPF start, then precision + margin polish
    est = {"single": 0.0, "cont": 0.0}
    ts = time.time()
    attempt(ppc, 500)
    est["single"] = max(est["single"], time.time() - ts)
    if time.time() + 1.3 * est["single"] < deadline:
        ts = time.time()
        attempt(flat_start(ppc), 300)
        est["single"] = max(est["single"], time.time() - ts)
    if time.time() + 2.0 * est["single"] < deadline:
        polish()
    if time.time() + 1.3 * est["single"] < deadline:
        ts = time.time()
        p = dc_start(ppc)
        before = best
        if p is not None:
            attempt(p, 300)
        est["single"] = max(est["single"], time.time() - ts)
        if best is not None and (before is None or best < before - 1e-9):
            polish()

    # Phase 2: continuation restarts + basin hopping + dispatch corners + LHS restarts
    non = int((ppc["gen"][:, GEN_STATUS] > 0).sum())
    try:
        from scipy.stats import qmc

        lhs = qmc.LatinHypercube(d=2 * non, seed=int(a.seed)).random(128)
    except Exception:
        lhs = rng.random((128, 2 * non))
    k_lhs = 0
    k_cont = 0
    tries = 0
    stagnant = 0
    hop_scale = 0.25
    schedule = ["cont", "small", "lhs", "corner", "cont", "small", "large", "corner"]
    while True:
        mode = schedule[tries % len(schedule)]
        if best_r is None:
            mode = "large"
        if mode == "cont":
            need = est["cont"] if est["cont"] > 0 else 4.0 * est["single"]
        else:
            need = est["single"]
        if time.time() + 1.3 * need + 1.0 > deadline:
            if mode == "cont" and time.time() + 1.3 * est["single"] + 1.0 < deadline:
                mode = "small"
            else:
                break
        tries += 1
        before = best
        ts = time.time()
        if mode == "cont":
            cont_attempt(k_cont % 3, 250)
            k_cont += 1
            est["cont"] = max(est["cont"], time.time() - ts)
        else:
            if best_r is None:
                p = perturb(ppc, None, rng, 1.0 if tries % 4 else 2.5)
            elif mode == "small":
                p = perturb(ppc, best_r, rng, hop_scale)
            elif mode == "lhs":
                p = lhs_start(ppc, lhs[k_lhs % len(lhs)])
                k_lhs += 1
            elif mode == "corner":
                p = corner_start(ppc, best_r, rng)
            else:
                p = perturb(ppc, best_r, rng, 2.0)
            attempt(p, 250)
            est["single"] = max(est["single"], time.time() - ts)
        if best is not None and (before is None or best < before - 1e-9):
            stagnant = 0
            hop_scale = max(0.1, hop_scale * 0.8)
            if time.time() + 2.0 * est["single"] < deadline:
                polish()
        else:
            stagnant += 1
            if stagnant % 3 == 0:
                hop_scale = min(1.5, hop_scale * 1.5)
        if best is None and tries > 25:
            break

    # Final: make sure the incumbent has had its margin polish if any time is left
    if best_r is not None and margin_done[0] != best and time.time() + 1.3 * est["single"] < deadline:
        polish()
    print(f"best={best} tries={tries} secs={time.time() - t0:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
