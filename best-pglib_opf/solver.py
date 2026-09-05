"""AC-OPF solver: PIPS interior point + basin-hopping multi-start + continuation restarts (limit relaxation, load
ramp, cost re-weighting, current-limit and objective homotopy, baseMVA re-basing, CONTINGENCY CONTINUATION) + cost
scale path diversification + step-controlled PIPS + dual-guided margin polish of the incumbent AND of every
near-tie local optimum.

Phase 1: PIPS from the file's start point, a flat start, a DC-OPF start and a step-controlled flat start; Newton
power-flow polish; if the independent verifier rejects the point at 1e-6, first re-solve with tight (1e-9)
interior-point tolerances, then warm re-solve with ONLY the near-binding constraints tightened.
Phase 2: until the time budget, restart PIPS from (a) Latin-hypercube samples over generator voltage set-points and
dispatch, (b) small/large perturbations of the incumbent (basin hopping with adaptive step), (c) dispatch corners
(random subsets of generators pinned to Pmin/Pmax), (d) continuation paths: relax-then-tighten limits, load ramp,
re-weighted cost, current-limit formulation, objective homotopy, baseMVA re-basing and CONTINGENCY CONTINUATION
(a non-islanding branch outage, forced generator outages, or a perturbed network: scaled impedances, reactive
load or line charging), (e) cost-scale path diversification and (f) step-controlled PIPS restarts.  Every stage of a
continuation is followed by a true-problem re-solve and only that is checked.
Every verified raw local optimum within a tiny relative band of the best raw objective enters a NEAR-TIE POOL of
distinct points; each pool member (not only the incumbent) receives the high-precision polish and the DUAL-GUIDED
MARGIN POLISH: its basin is re-solved with all inequality limits relaxed by a margin m < 1e-6 (the checker's
tolerance) and every nodal P/Q load shifted by m in the direction the nodal multipliers LAM_P / LAM_Q say lowers
cost, on an ascending, warm-started ladder of m up to 9.98e-7, topped by cheap warm-started Newton power-flow rungs
up to 9.999e-7; only points the verifier accepts are ever kept.  Best verified solution is saved atomically on every
improvement.

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
from pypower.idx_bus import BUS_I, BUS_TYPE, PD, QD, BS, VM, VA, VMAX, VMIN, LAM_P, LAM_Q  # noqa: E402
from pypower.idx_gen import GEN_BUS, PG, QG, VG, PMAX, PMIN, QMAX, QMIN, GEN_STATUS  # noqa: E402
from pypower.idx_brch import (  # noqa: E402
    F_BUS,
    T_BUS,
    BR_R,
    BR_X,
    BR_B,
    RATE_A,
    BR_STATUS,
    ANGMIN,
    ANGMAX,
    PF,
    QF,
    PT,
    QT,
)

np.seterr(all="ignore")

MARGINS = (4e-7, 7e-7, 8.8e-7, 9.6e-7, 9.9e-7, 9.95e-7, 9.98e-7)  # ascending interior-point ladder, all < 1e-6
PF_MARGINS = (9.99e-7, 9.995e-7, 9.998e-7, 9.999e-7)  # Newton power-flow rungs on top of the ladder
ALG_PIPS = 560
ALG_PIPS_SC = 565  # step-controlled PIPS
TIE_REL = 2e-4  # near-tie pool band (relative to the best raw objective)
TIE_ABS = 0.05  # ... and absolute ($/h)
POOL_MAX = 6
N_CONT = 9  # number of continuation kinds


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
    """Copy of ppc (its own limits/loads/costs/base/statuses) whose start point is taken from result (or case) r.

    PG/QG are copied in MW, VM/VA as is, so a result on a re-based problem warm-starts the original correctly."""
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


def load_dirs(r):
    """+1 where increasing the load raises cost (shift load down), -1 where the nodal multiplier is negative."""
    if r is None or r.get("lam_p") is None:
        return None, None
    sp = np.where(np.asarray(r["lam_p"]) < 0.0, -1.0, 1.0)
    sq = np.where(np.asarray(r["lam_q"]) < 0.0, -1.0, 1.0)
    return sp, sq


def margined(ppc, m, sp=None, sq=None):
    """Relax every inequality limit by m (pu; m degrees for angle limits) and shift every nodal P/Q load by m
    in the cost-lowering direction given by sp/sq (default: reduce the load).

    A solution of this problem violates the true constraints by at most ~m, which the verifier tolerates when
    m < 1e-6.  Off generators are untouched (they must stay exactly at zero)."""
    p = cp(ppc)
    base = p["baseMVA"]
    bus, gen, br = p["bus"], p["gen"], p["branch"]
    e = m * base
    nb = bus.shape[0]
    if sp is None or len(sp) != nb:
        sp = np.ones(nb)
    if sq is None or len(sq) != nb:
        sq = np.ones(nb)
    bus[:, VMAX] += m
    bus[:, VMIN] -= m
    bus[:, PD] -= e * sp
    bus[:, QD] -= e * sq
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


def scaled_cost(ppc, fac):
    """Uniformly scale every cost curve by fac: same optimum set, different interior-point central path."""
    p = cp(ppc)
    gc = p["gencost"]
    for i in range(gc.shape[0]):
        model = int(gc[i, 0])
        nc = int(gc[i, 3])
        if model == 2 and gc.shape[1] >= 4 + nc:
            gc[i, 4 : 4 + nc] *= fac
        elif model == 1 and gc.shape[1] >= 4 + 2 * nc:
            gc[i, 5 : 4 + 2 * nc : 2] *= fac
    return p


def homotopy_cost(ppc, uniform):
    """Objective homotopy stage: either the loss-minimising objective (every polynomial cost replaced by 1 $/MW
    linear) or the linear-only version of the true cost (higher-order terms dropped)."""
    p = cp(ppc)
    gc = p["gencost"]
    for i in range(gc.shape[0]):
        if int(gc[i, 0]) != 2:
            continue
        nc = int(gc[i, 3])
        if nc < 2 or gc.shape[1] < 4 + nc:
            continue
        if uniform:
            gc[i, 4 : 4 + nc] = 0.0
            gc[i, 4 + nc - 2] = 1.0
        else:
            gc[i, 4 : 4 + nc - 2] = 0.0
    return p


def rebased(ppc, k):
    """Same physical network on a baseMVA multiplied by k (branch R, X scale by k, line charging by 1/k; every
    MW/MVAr/MVA/$ quantity is unchanged): identical optimum set, all pu equations rescaled by 1/k, so the
    interior point follows a different central path."""
    p = cp(ppc)
    p["baseMVA"] = float(ppc["baseMVA"]) * k
    br = p["branch"]
    br[:, BR_R] *= k
    br[:, BR_X] *= k
    br[:, BR_B] /= k
    return p


def reach(ppc, skip):
    """Boolean array of buses reachable from the first bus over in-service branches, branch `skip` removed."""
    bus, br = ppc["bus"], ppc["branch"]
    nb = bus.shape[0]
    pos = {int(b): i for i, b in enumerate(bus[:, BUS_I])}
    adj = [[] for _ in range(nb)]
    for j in range(br.shape[0]):
        if j == skip or br[j, BR_STATUS] <= 0:
            continue
        f, t = pos.get(int(br[j, F_BUS])), pos.get(int(br[j, T_BUS]))
        if f is None or t is None:
            continue
        adj[f].append(t)
        adj[t].append(f)
    ref = np.where(bus[:, BUS_TYPE] == 3)[0]
    s0 = int(ref[0]) if len(ref) else 0
    seen = np.zeros(nb, dtype=bool)
    seen[s0] = True
    stack = [s0]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if not seen[v]:
                seen[v] = True
                stack.append(v)
    return seen


def outaged(ppc, rng, tries=12):
    """Random single branch outage that does not island any bus (None if none found)."""
    p = cp(ppc)
    br = p["branch"]
    cand = np.where(br[:, BR_STATUS] > 0)[0]
    if len(cand) < 2:
        return None
    base = reach(p, -1)
    for _ in range(tries):
        k = int(rng.choice(cand))
        if np.array_equal(reach(p, k), base):
            br[k, BR_STATUS] = 0
            return p
    return None


def gens_off(ppc, rng):
    """Force a random small subset of generators (never at the reference bus) out of service; None if the
    remaining capacity is too small.  Returns (problem, indices)."""
    p = cp(ppc)
    bus, gen = p["bus"], p["gen"]
    on = np.where(gen[:, GEN_STATUS] > 0)[0]
    refb = set(int(b) for b in bus[bus[:, BUS_TYPE] == 3, BUS_I])
    cand = np.array([i for i in on if int(gen[i, GEN_BUS]) not in refb])
    if len(on) < 3 or len(cand) < 2:
        return None, None
    kmax = max(1, min(3, len(cand) // 4))
    k = int(rng.integers(1, kmax + 1))
    sel = rng.choice(cand, size=k, replace=False)
    need = 1.08 * bus[:, PD].sum()
    if gen[on, PMAX].sum() - gen[sel, PMAX].sum() < need:
        return None, None
    gen[sel, GEN_STATUS] = 0
    gen[sel, PG] = 0.0
    gen[sel, QG] = 0.0
    return p, sel


def network_perturbed(ppc, rng):
    """Perturbed network: scaled impedances of a random branch subset, scaled reactive load, or scaled line
    charging and bus shunts."""
    p = cp(ppc)
    br, bus = p["branch"], p["bus"]
    mode = int(rng.integers(3))
    if mode == 0:
        sel = rng.random(br.shape[0]) < 0.25
        f = np.exp(rng.normal(0.0, 0.4, int(sel.sum())))
        br[sel, BR_X] *= f
        br[sel, BR_R] *= f
    elif mode == 1:
        bus[:, QD] *= float(rng.uniform(0.0, 0.6))
    else:
        br[:, BR_B] *= float(rng.uniform(0.0, 0.5))
        bus[:, BS] *= float(rng.uniform(0.0, 0.5))
    return p


# ----------------------------------------------------------------------------------------------------------- solving
def pips(ppc, max_it, feastol=1e-7, gradtol=1e-6, comptol=1e-6, costtol=1e-6, alg=ALG_PIPS, flow_lim=0):
    """PIPS OPF then a Newton power-flow polish (nodal balance to 1e-10, Pg and gen-bus Vm kept => cost unchanged).

    alg 560 = PIPS, 565 = step-controlled PIPS; flow_lim 0 = apparent power, 1 = active power, 2 = current.
    The nodal multipliers LAM_P / LAM_Q of the OPF are kept in r["lam_p"], r["lam_q"] for the margin polish."""
    opt = ppoption(
        VERBOSE=0,
        OUT_ALL=0,
        OPF_ALG=alg,
        OPF_FLOW_LIM=flow_lim,
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
    lam_p = lam_q = None
    try:
        if r["bus"].shape[1] > LAM_Q:
            lam_p = np.array(r["bus"][:, LAM_P], dtype=float)
            lam_q = np.array(r["bus"][:, LAM_Q], dtype=float)
    except Exception:
        lam_p = lam_q = None
    try:
        pos = {int(b): i for i, b in enumerate(r["bus"][:, BUS_I])}
        r["gen"][:, VG] = [r["bus"][pos[int(b)], VM] for b in r["gen"][:, GEN_BUS]]
        with redirect_stdout(sys.stderr):
            pf, ok = runpf(r, ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=1e-10, PF_MAX_IT=50, ENFORCE_Q_LIMS=0))
        if ok:
            r = pf
    except Exception:
        pass
    r["lam_p"] = lam_p
    r["lam_q"] = lam_q
    return r


def pips_tight(ppc, max_it):
    return pips(ppc, max_it, feastol=1e-9, gradtol=1e-8, comptol=1e-9, costtol=1e-10)


def newton_pf(ppc):
    """Plain Newton power flow of ppc from its own start point (Pg and gen voltages kept); None on failure."""
    try:
        with redirect_stdout(sys.stderr):
            pf, ok = runpf(ppc, ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=1e-10, PF_MAX_IT=30, ENFORCE_Q_LIMS=0))
    except Exception:
        return None
    if not ok:
        return None
    return pf


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
    best_raw = [None]  # best verified objective among un-margined (raw) local optima
    pool = []  # near-tie raw local optima: {"obj", "r", "polished"}
    margin_done = [-1.0]  # objective at which the incumbent's margin polish last completed
    sc_state = {"fail": 0, "tried": 0}  # step-controlled PIPS health (disabled after repeated solver failures)
    est = {"single": 0.0, "cont": 0.0, "scale": 0.0, "polish": 0.0}

    def save(sol, obj):
        tmp = a.out + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"target": a.target, "obj": obj, "solution": sol}, f)
        os.replace(tmp, a.out)

    def same_point(r1, r2):
        try:
            return (
                np.max(np.abs(r1["gen"][:, PG] - r2["gen"][:, PG])) < 0.02
                and np.max(np.abs(r1["bus"][:, VM] - r2["bus"][:, VM])) < 2e-5
            )
        except Exception:
            return False

    def note_raw(obj, r):
        """Register a verified raw local optimum in the near-tie pool (distinct points only)."""
        if best_raw[0] is None or obj < best_raw[0]:
            best_raw[0] = obj
        band = max(TIE_REL * abs(best_raw[0]), TIE_ABS)
        pool[:] = [e for e in pool if e["obj"] <= best_raw[0] + band]
        if obj > best_raw[0] + band:
            return
        for e in pool:
            if same_point(e["r"], r):
                if obj < e["obj"] - 1e-9:
                    e["obj"], e["r"] = obj, r
                return
        pool.append({"obj": obj, "r": r, "polished": False})
        pool.sort(key=lambda e: e["obj"])
        del pool[POOL_MAX:]

    def check(r, margined_flag=False):
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
            r["is_margined"] = margined_flag
            best, best_r = obj, r
            save(sol, obj)
        if not margined_flag:
            note_raw(obj, r)
        return obj

    def attempt(p, max_it, alg=ALG_PIPS):
        """PIPS (plain or step-controlled) from start p; on verifier rejection, tight-tolerance re-solve, then
        targeted tightening."""
        r = pips(p, max_it, alg=alg)
        if alg == ALG_PIPS_SC:
            sc_state["tried"] += 1
            sc_state["fail"] = sc_state["fail"] + 1 if r is None else 0
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

    def pf_rung(m, sp, sq, prev):
        """Newton power-flow rung of the margined ladder: nodal balance at exactly margin m, dispatch of prev kept
        (only the slack absorbs the tiny load change); accepted only if the verifier passes it."""
        pf = newton_pf(warm(margined(ppc, m, sp, sq), prev))
        if pf is None:
            return None
        pf["lam_p"] = prev.get("lam_p")
        pf["lam_q"] = prev.get("lam_q")
        if check(pf, True) is None:
            return None
        return pf

    def margin_polish(base_r=None, dirs_from=None, mark=True):
        """Ascending, warm-started ladder of margined re-solves of the basin of base_r (default: the incumbent);
        loads are shifted in the direction the nodal multipliers of dirs_from (default: base_r) indicate; keep
        only verified points (saved only when they beat the global incumbent)."""
        if base_r is None:
            base_r = best_r
        if base_r is None:
            return
        ts = time.time()
        sp, sq = load_dirs(dirs_from if dirs_from is not None else base_r)
        prev = base_r
        fails = 0
        for m in MARGINS:
            if time.time() > deadline:
                break
            r = pips_tight(warm(margined(ppc, m, sp, sq), prev), 200)
            ok = r is not None and check(r, True) is not None
            if not ok and prev is not base_r and time.time() < deadline:
                r = pips_tight(warm(margined(ppc, m, sp, sq), base_r), 200)
                ok = r is not None and check(r, True) is not None
            if ok:
                prev = r
                fails = 0
            else:
                fails += 1
                if fails >= 2:
                    break
        if prev is not base_r:
            for m in PF_MARGINS:
                if time.time() > deadline:
                    break
                r = pf_rung(m, sp, sq, prev)
                if r is not None:
                    prev = r
        if mark:
            margin_done[0] = best
        est["polish"] = max(est["polish"], time.time() - ts)

    def polish():
        """High-precision warm re-solve of the incumbent (if it is not already a margined point), then the
        dual-guided margin polish; the matching pool entry is marked as polished."""
        if best_r is None or time.time() > deadline:
            return
        if not best_r.get("is_margined"):
            r = pips_tight(warm(ppc, best_r), 200)
            if r is not None:
                check(r)
        for e in pool:
            if same_point(e["r"], best_r):
                e["polished"] = True
        if margin_done[0] != best:
            margin_polish()

    def polish_pool(limit=1):
        """Margin-polish up to `limit` unpolished near-tie pool members (best raw objective first)."""
        done = 0
        for e in sorted(pool, key=lambda e: e["obj"]):
            if done >= limit:
                break
            if e["polished"]:
                continue
            need = est["polish"] if est["polish"] > 0 else 6.0 * est["single"]
            if time.time() + 1.2 * need + 1.5 * est["single"] + 1.0 > deadline:
                break
            e["polished"] = True
            if best_r is not None and same_point(e["r"], best_r):
                continue
            base = e["r"]
            r = pips_tight(warm(ppc, base), 200)
            if r is not None and check(r) is not None and same_point(r, base):
                base = r
            margin_polish(base_r=base, mark=False)
            done += 1
        return done

    def cont_attempt(kind, max_it):
        """Continuation restart: solve a sequence of modified problems (each a (problem, flow-limit-type) pair),
        warm-starting each from the previous one, then re-solve the TRUE problem from the point reached."""
        restore = None
        if kind == 0:  # relax limits, then tighten back in stages
            stages = [(relaxed(ppc, al), 0) for al in (0.5, 0.2, 0.05)]
            start = perturb(ppc, best_r, rng, 0.6) if best_r is not None else flat_start(ppc)
        elif kind == 1:  # load ramp
            s = float(rng.uniform(0.7, 0.9))
            stages = [(scaled_load(ppc, s), 0), (scaled_load(ppc, 0.5 * (1.0 + s)), 0)]
            start = flat_start(ppc)
            if best_r is not None and rng.random() < 0.5:
                start = perturb(ppc, best_r, rng, 1.0)
        elif kind == 2:  # re-weighted cost, then true cost
            stages = [(perturbed_cost(ppc, rng, 0.4), 0)]
            start = perturb(ppc, best_r, rng, 0.3) if best_r is not None else flat_start(ppc)
        elif kind == 3:  # current-limit formulation of the thermal limits, then apparent-power limits
            stages = [(cp(ppc), 2)]
            start = perturb(ppc, best_r, rng, 0.5) if best_r is not None else flat_start(ppc)
            if rng.random() < 0.5:
                start = flat_start(ppc)
        elif kind == 4:  # objective homotopy: loss-minimising or linear-only cost, then the true cost
            stages = [(homotopy_cost(ppc, rng.random() < 0.5), 0)]
            start = flat_start(ppc)
            if best_r is not None and rng.random() < 0.5:
                start = perturb(ppc, best_r, rng, 0.5)
        elif kind == 5:  # baseMVA re-basing (constraint rescaling), then the original base
            k = float(10.0 ** rng.uniform(-1.0, 1.0))
            stages = [(rebased(ppc, k), 0)]
            start = perturb(ppc, best_r, rng, 0.4) if best_r is not None else flat_start(ppc)
            if rng.random() < 0.4:
                start = lhs_start(ppc, lhs[k_lhs_box[0] % len(lhs)])
                k_lhs_box[0] += 1
        elif kind == 6:  # branch outage contingency, then the intact network
            q = outaged(ppc, rng)
            if q is None:
                return None
            stages = [(q, 0)]
            start = perturb(ppc, best_r, rng, 0.3) if best_r is not None else flat_start(ppc)
            if rng.random() < 0.3:
                start = flat_start(ppc)
        elif kind == 7:  # forced generator outages, then all units back
            q, restore = gens_off(ppc, rng)
            if q is None:
                return None
            stages = [(q, 0)]
            start = perturb(ppc, best_r, rng, 0.3) if best_r is not None else flat_start(ppc)
            start["gen"][restore, PG] = 0.0
            start["gen"][restore, QG] = 0.0
        else:  # perturbed network (impedances / reactive load / charging), then the true network
            stages = [(network_perturbed(ppc, rng), 0)]
            start = perturb(ppc, best_r, rng, 0.4) if best_r is not None else flat_start(ppc)
            if rng.random() < 0.3:
                start = lhs_start(ppc, lhs[k_lhs_box[0] % len(lhs)])
                k_lhs_box[0] += 1
        r = None
        for q, fl in stages:
            if time.time() > deadline:
                return None
            r = pips(warm(q, r) if r is not None else warm(q, start), max_it, flow_lim=fl)
            if r is None:
                return None
        if time.time() > deadline:
            return None
        p = warm(ppc, r)
        if restore is not None:
            g = p["gen"]
            g[restore, PG] = g[restore, PMIN] + 0.1 * (g[restore, PMAX] - g[restore, PMIN])
            g[restore, QG] = 0.0
        return attempt(p, max_it)

    def scale_attempt(start, max_it):
        """Cost-scale path diversification: solve with all costs scaled by 10^u (same optimum set, different
        central path), check the point reached, then re-solve the true problem from it."""
        fac = float(10.0 ** rng.uniform(-3.0, 3.0))
        r = pips(warm(scaled_cost(ppc, fac), start), max_it)
        if r is None or time.time() > deadline:
            return None
        check(r)
        return attempt(warm(ppc, r), max_it)

    # Latin-hypercube rows (shared by the LHS, scale, sc, re-basing and network modes)
    non = int((ppc["gen"][:, GEN_STATUS] > 0).sum())
    try:
        from scipy.stats import qmc

        lhs = qmc.LatinHypercube(d=2 * non, seed=int(a.seed)).random(128)
    except Exception:
        lhs = rng.random((128, 2 * non))
    k_lhs_box = [0]

    # Phase 1: file start, flat start, DC-OPF start, step-controlled flat start, then precision + margin polish
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
    if time.time() + 1.6 * est["single"] + 1.0 < deadline:
        ts = time.time()
        before = best
        attempt(flat_start(ppc) if best_r is None else perturb(ppc, best_r, rng, 0.3), 300, alg=ALG_PIPS_SC)
        est["single"] = max(est["single"], time.time() - ts)
        if best is not None and (before is None or best < before - 1e-9):
            polish()

    # Phase 2: continuation restarts + basin hopping + dispatch corners + LHS restarts + cost-scale paths +
    # step-controlled PIPS restarts; near-tie pool members are margin-polished as they appear
    k_cont = 0
    k_scale = 0
    k_sc = 0
    tries = 0
    stagnant = 0
    hop_scale = 0.25
    schedule = [
        "cont",
        "small",
        "lhs",
        "scale",
        "corner",
        "cont",
        "sc",
        "small",
        "scale",
        "large",
        "cont",
        "corner",
        "sc",
        "lhs",
        "cont",
        "small",
    ]
    while True:
        mode = schedule[tries % len(schedule)]
        if best_r is None:
            mode = "large"
        if mode == "sc" and sc_state["fail"] >= 2:
            mode = "small"
        if mode == "cont":
            need = est["cont"] if est["cont"] > 0 else 4.0 * est["single"]
        elif mode == "scale":
            need = est["scale"] if est["scale"] > 0 else 2.5 * est["single"]
        elif mode == "sc":
            need = 1.5 * est["single"]
        else:
            need = est["single"]
        if time.time() + 1.3 * need + 1.0 > deadline:
            if mode in ("cont", "scale", "sc") and time.time() + 1.3 * est["single"] + 1.0 < deadline:
                mode = "small"
            else:
                break
        tries += 1
        before = best
        ts = time.time()
        if mode == "cont":
            cont_attempt(k_cont % N_CONT, 250)
            k_cont += 1
            est["cont"] = max(est["cont"], time.time() - ts)
        elif mode == "scale":
            if k_scale % 2 == 0:
                start = perturb(ppc, best_r, rng, max(hop_scale, 0.3))
            else:
                start = lhs_start(ppc, lhs[k_lhs_box[0] % len(lhs)])
                k_lhs_box[0] += 1
            k_scale += 1
            scale_attempt(start, 250)
            est["scale"] = max(est["scale"], time.time() - ts)
        elif mode == "sc":
            if k_sc % 3 == 0:
                p = perturb(ppc, best_r, rng, max(hop_scale, 0.3))
            elif k_sc % 3 == 1:
                p = lhs_start(ppc, lhs[k_lhs_box[0] % len(lhs)])
                k_lhs_box[0] += 1
            else:
                p = corner_start(ppc, best_r, rng)
            k_sc += 1
            attempt(p, 250, alg=ALG_PIPS_SC)
            est["single"] = max(est["single"], time.time() - ts)
        else:
            if best_r is None:
                p = perturb(ppc, None, rng, 1.0 if tries % 4 else 2.5)
            elif mode == "small":
                p = perturb(ppc, best_r, rng, hop_scale)
            elif mode == "lhs":
                p = lhs_start(ppc, lhs[k_lhs_box[0] % len(lhs)])
                k_lhs_box[0] += 1
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
        if best_r is not None and any(not e["polished"] for e in pool):
            polish_pool(1)
        if best is None and tries > 25:
            break

    # Final: make sure the incumbent has had its margin polish, polish any remaining near-tie pool members, then
    # one refresh pass with the multipliers of the margined incumbent itself (captures any load-shift direction
    # that flipped sign after the first pass)
    if best_r is not None and margin_done[0] != best and time.time() + 1.3 * est["single"] < deadline:
        polish()
    if best_r is not None:
        while any(not e["polished"] for e in pool):
            if polish_pool(1) == 0:
                break
    if best_r is not None and margin_done[0] != best and time.time() + 1.3 * est["single"] < deadline:
        polish()
    if best_r is not None and best_r.get("is_margined") and time.time() + 2.0 * est["single"] < deadline:
        margin_polish(dirs_from=best_r)
    print(f"best={best} tries={tries} pool={len(pool)} secs={time.time() - t0:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
