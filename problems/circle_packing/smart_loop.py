"""Discovery loop for circle packing (Packomania csqv): propose -> exact-verify -> promote.

Problem: pack N variable-radius circles in the unit square, maximize the sum of radii.
Every candidate is checked by the zero-tolerance stdlib verifier before it can be
adopted; only feasible candidates that strictly improve the running best are promoted.

Interface: python smart_loop.py --target N --time SECONDS --seed S --out PATH
Writes PATH (JSON payload) and PATH with suffix replaced by .explanation.md.

This is the second problem port of the discovery-loop architecture (the first is
matrix multiplication): propose candidates with composable operators, verify each
exactly, promote only verified improvements, validate the winner adversarially,
explain the result honestly against the repo's best-known table.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))

if __package__:
    from . import records, seed_solver, verify
    from problems.matrix_multiplication.patterns.library import PatternLibrary
else:
    sys.path.insert(0, REPO_ROOT)
    from problems.circle_packing import records, seed_solver, verify
    from problems.matrix_multiplication.patterns.library import PatternLibrary

WIN_MARGIN = 1e-10  # same margin as problem.py: beats() requires strict improvement
PATTERN_DIR = os.path.join(HERE, "patterns")
MATRIX_PATTERN_DIR = os.path.join(
    REPO_ROOT, "problems", "matrix_multiplication", "patterns"
)


# ---------------------------------------------------------------- propose ---

def _refine_centers(circles, budget):
    """Short penalty L-BFGS-B refinement starting from given circles, then LP radii.

    Reuses seed_solver's real machinery (penalty, lp_radii, make_strict,
    feasible_sum); only the starting point differs from a cold multi-start.
    Returns (sum, circles) with sum = -1.0 if nothing feasible resulted.
    """
    n = len(circles)
    c = np.array([[x, y] for x, y, _ in circles])
    r = np.array([rr for _, _, rr in circles])
    z = np.concatenate([c.ravel(), r])
    bounds = [(0, 1)] * (2 * n) + [(0, 0.5)] * n
    t0 = time.time()
    for mu in (10, 100, 1e3, 1e4):
        res = minimize(
            seed_solver.penalty, z, args=(n, mu), jac=True,
            method="L-BFGS-B", bounds=bounds, options={"maxiter": 200},
        )
        z = res.x
        if time.time() - t0 > budget:
            break
    c = z[: 2 * n].reshape(n, 2)
    r = seed_solver.make_strict(c, seed_solver.lp_radii(c))
    return seed_solver.feasible_sum(c, r)


def propose(n, budget, seed):
    """Yield (sum, circles, provenance) candidates until *budget* seconds elapse.

    Operator: multistart -- cold multi-start penalty optimization via
    seed_solver.solve, one call per seed. Perturb-and-refine runs separately in
    run(), seeded from the multistart winner.
    Every yielded candidate is feasible per seed_solver.feasible_sum, which the
    caller re-checks with the independent stdlib verifier before adoption.
    """
    t0 = time.time()
    k = 0
    while time.time() - t0 < budget:
        remaining = budget - (time.time() - t0)
        s, circ = seed_solver.solve(n, max(1.0, remaining / 3), seed + 1000 * k)
        k += 1
        if circ:
            yield s, circ, {"operator": "multistart-penalty-optimization", "seed": seed + 1000 * (k - 1)}


def perturb_refine(best_circles, budget, seed):
    """Jitter *best_circles* and re-optimize from there. Returns (sum, circles, provenance).

    Runs a few jittered restarts inside *budget* and keeps the best feasible
    refinement. Returns (None, None, None) if nothing was produced.
    """
    rng = np.random.default_rng(seed)
    parent_sum = sum(c[2] for c in best_circles)
    t0 = time.time()
    improved = None
    while time.time() - t0 < budget:
        c = np.array([[x, y] for x, y, _ in best_circles])
        c = np.clip(c + rng.normal(0, 0.015, c.shape), 0.01, 0.99)
        jittered = [[float(x), float(y), float(r)]
                    for (x, y), (_, _, r) in zip(c, best_circles)]
        s, circ = _refine_centers(jittered, max(1.0, budget - (time.time() - t0)))
        if circ and (improved is None or s > improved[0]):
            improved = (s, circ)
    if improved is None:
        return None, None, None
    return improved[0], improved[1], {"operator": "perturb-and-refine", "seed": seed,
                                      "parent_sum": parent_sum}


# ------------------------------------------------------------- adversarial ---

def _independent_reverify(payload_path):
    """Re-verify through verify.py in a fresh interpreter (no shared state)."""
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, "verify.py"), payload_path],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": f"verify.py exited {proc.returncode}: {proc.stderr[:200]}"}
    res = json.loads(proc.stdout)
    return {"ok": bool(res.get("feasible")), "detail": res}


def breaker_suite(circles, n, budget, seed):
    """Adversarial validation of a promoted packing. Returns a verdict dict.

    Attacks:
      1. independent re-verification via verify.py in a fresh subprocess.
      2. neighborhood attack: perturb centers, re-solve LP-optimal radii, and
         check whether any strictly better feasible packing was one small move
         away (bounded by *budget* seconds and a fixed attempt cap).
    Verdict is "survived" (no attack improved on the candidate) or "broken".
    This is bounded evidence of local optimality, not a proof.
    """
    rng = np.random.default_rng(seed)
    tmp = os.path.join(HERE, ".breaker_tmp.json")
    json.dump({"n": n, "circles": circles}, open(tmp, "w"))
    try:
        reverify = _independent_reverify(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    if not reverify["ok"]:
        return {"verdict": "broken", "reason": "independent re-verification failed",
                "reverify": reverify, "attempts": 0}

    base_sum = sum(c[2] for c in circles)
    attempts = 0
    t0 = time.time()
    best_attack = None
    while time.time() - t0 < budget and attempts < 400:
        attempts += 1
        c = np.array([[x, y] for x, y, _ in circles])
        c = np.clip(c + rng.normal(0, 0.01, c.shape), 0.005, 0.995)
        r = seed_solver.make_strict(c, seed_solver.lp_radii(c))
        s, circ = seed_solver.feasible_sum(c, r)
        if s > base_sum + WIN_MARGIN:
            chk = verify.check(circ, n)
            if chk["feasible"] and chk["sum"] > base_sum + WIN_MARGIN:
                best_attack = (s, circ)
                base_sum = s
    if best_attack is not None:
        return {"verdict": "broken",
                "reason": "neighborhood attack found a strictly better feasible packing",
                "reverify": reverify, "attempts": attempts,
                "attack_sum": best_attack[0], "attack_circles": best_attack[1]}
    return {"verdict": "survived",
            "reason": f"{attempts} perturbation attempts found no strict improvement",
            "reverify": reverify, "attempts": attempts}


# ------------------------------------------------------------- explanation ---

def write_explanation(path, *, n, result, record, breaker, patterns_consulted, elapsed):
    """Write a complete, honest explanation of the run. No TODO placeholders."""
    s, circles, prov = result
    gap = None if record is None else s - record
    if record is None:
        novelty = (f"no best-known value for n={n} in the repo's records table; "
                   "this run establishes a verified baseline.")
    elif gap > WIN_MARGIN:
        novelty = (f"BEATS the repo best-known {record:.12f} by {gap:.3e}. "
                   "Calibration only: beating the in-repo table is not a Packomania "
                   "record until independently reproduced and submitted.")
    elif gap < -WIN_MARGIN:
        novelty = (f"{-gap:.3e} BELOW the repo best-known {record:.12f}. "
                   "Calibration run: the loop did not match the known best in the "
                   "time budget; no new-record claim.")
    else:
        novelty = (f"matches the repo best-known {record:.12f} within margin. "
                   "Calibration: the loop rediscovered the known result; not a discovery.")
    lines = [
        f"# Circle packing n={n}: discovery-loop result",
        "",
        f"**Sum of radii:** {s:.12f}  (n={n}, {len(circles)} circles)",
        "",
        "## How it was found",
        f"- Proposing operator: `{prov['operator']}` (seed {prov['seed']})",
    ]
    if "parent_sum" in prov:
        lines.append(f"- Refined from a parent packing with sum {prov['parent_sum']:.12f}")
    lines += [
        f"- Wall-clock for the full run: {elapsed:.1f}s",
        "",
        "## Exact verification",
        "- Every candidate was checked by the zero-tolerance stdlib verifier "
        "(`verify.check`); only feasible candidates could be promoted.",
        f"- Final packing: feasible, sum {s:.12f}.",
        "",
        "## Adversarial validation",
        f"- Breaker verdict: **{breaker['verdict'].upper()}** — {breaker['reason']}.",
        "- Independent re-verification via `verify.py` in a fresh subprocess: "
        f"{'passed' if breaker['reverify']['ok'] else 'FAILED'}.",
        "- This is bounded evidence of local optimality, not a proof.",
        "",
        "## Novelty (honest)",
        f"- {novelty}",
        "",
        "## Cross-problem transfer",
        "- Pattern outcomes for this run were recorded with the shared, "
        "problem-agnostic pattern library (no matrix-specific logic).",
        f"- Consulted {len(patterns_consulted)} transferable pattern(s) from the "
        "matrix-multiplication library before proposing: "
        + (", ".join(f"`{p['name']}`" for p in patterns_consulted) or "none matched"),
        "",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


# ---------------------------------------------------------------- dashboard ---

def _read_previous_suggestions(run_dir):
    """Suggestions from the previous run of this problem, if any.

    Gives manual runs the same cross-night memory the nightly worker has.
    Best-effort: never fails the run.
    """
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import loop_report
        return loop_report.read_previous_suggestions("circle_packing", run_dir)
    except Exception:  # noqa: BLE001
        return []


def _write_dashboard(run_dir, summary):
    """Write the post-loop dashboard. Dashboard I/O must never fail the run."""
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import loop_report
        res = loop_report.write_all(run_dir, summary)
        if not res.get("ok"):
            print(f"dashboard write failed: {res.get('error')}")
            return
        print(f"Dashboard: {res['paths']['dashboard']}")
        rb = res["report"]["record_break"]
        if rb["broke"]:
            print(f"RECORD BREAK: {rb['metric']}={rb['value']} -- {rb['note']}")
        if res["report"]["publish"]["recommended"]:
            print("Publishing recommended -- see dashboard (no one contacted).")
    except Exception as exc:  # noqa: BLE001 -- dashboard is best-effort
        print(f"dashboard unavailable: {exc}")


def _dashboard_summary(n, budget, seed, t_start, best, record, breaker,
                       transferred, operator_promoted, out, expl_path,
                       prev_suggestions):
    """Assemble the loop_summary dict for scripts/loop_report.py."""
    s, _, prov = best
    gap = None if record is None else s - record
    if record is None:
        novelty = "no repo baseline for this n; run establishes a verified baseline."
    elif gap > WIN_MARGIN:
        novelty = (f"beats repo best-known {record:.12f} by {gap:.3e} -- "
                   "calibration only, not a Packomania record until submitted.")
    elif gap < -WIN_MARGIN:
        novelty = (f"{-gap:.3e} below repo best-known {record:.12f}; "
                   "calibration run, no new-record claim.")
    else:
        novelty = (f"matches repo best-known {record:.12f}; "
                   "rediscovery, not a discovery.")
    suggestions = []
    if gap is not None and gap < -WIN_MARGIN:
        suggestions.append(
            "did not match the known best in budget; try a larger time budget "
            "or a different seed before concluding anything.")
    if breaker["verdict"] == "survived":
        suggestions.append(
            f"breaker survived {breaker['attempts']} attacks; the packing looks "
            "locally optimal -- next budget is better spent on a new n.")
    suggestions.append(
        "cross-problem transfer consulted "
        f"{len(transferred)} pattern(s); keep recording outcomes so the "
        "matrix-multiplication library keeps learning from packing runs.")
    tried_notes = [
        f"budget split: {0.8 * budget:.0f}s search / {0.2 * budget:.0f}s breaker",
        f"{len(transferred)} transferable pattern(s) consulted from "
        "the matrix-multiplication library",
        f"winning provenance: {prov['operator']} (seed {prov['seed']})",
    ]
    tried_notes += [f"previous run suggested: {s}" for s in prev_suggestions]
    return {
        "problem": "circle_packing",
        "run_name": None,
        "target": f"n={n}",
        "time_budget_s": budget,
        "seed": seed,
        "status": "success" if breaker["verdict"] == "survived"
                  else "adversarial_failed",
        "started": datetime.fromtimestamp(t_start, timezone.utc).isoformat(
            timespec="seconds"),
        "ended": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.time() - t_start, 2),
        "tried": {
            "operators": [
                "multistart-penalty-optimization (L-BFGS-B over centers+radii, "
                "then LP-optimal radii)",
                "perturb-and-refine (jitter best centers, re-optimize)",
                "neighborhood-breaker (perturb + LP-radii local-optimality attack)",
            ],
            "notes": tried_notes,
        },
        "best": {"metric": "sum_of_radii", "value": s,
                 "higher_is_better": True},
        "best_known": {"value": record, "source": "repo records.json"},
        "win_margin": WIN_MARGIN,
        "verifications": {
            "exact": True,
            "independent": bool(breaker["reverify"]["ok"]),
            "breaker": breaker["verdict"],
        },
        "learned": [
            f"promoted by operator(s): {sorted(operator_promoted)}",
            f"breaker: {breaker['attempts']} perturbation attempts, "
            f"verdict {breaker['verdict']}",
            f"novelty (honest): {novelty}",
        ],
        "recorded": {
            "items": [
                "pattern outcomes recorded in the shared problem-agnostic "
                "pattern library",
                "cross-problem transfer logged (matrix-multiplication "
                "patterns consulted)",
            ],
            "files": [out, expl_path],
        },
        "next_loop": {"suggestions": suggestions},
        "result_file": os.path.abspath(out),
    }


# ------------------------------------------------------------------- loop ---

def run(n, budget, seed, out):
    t_start = time.time()
    run_dir = os.path.dirname(os.path.abspath(out))
    os.makedirs(run_dir, exist_ok=True)
    prev_suggestions = _read_previous_suggestions(run_dir)
    if prev_suggestions:
        print("Previous run's suggestions for this loop:")
        for s in prev_suggestions:
            print(f"  - {s}")
    table = records.load()
    record = table.get(n)

    # Cross-problem transfer: consult the shared library for applicable tricks.
    transferred = []
    try:
        matrix_lib = PatternLibrary.load(MATRIX_PATTERN_DIR)
        transferred = matrix_lib.applicable(["continuous", "fast-verifier", "local-search"])
    except OSError:
        pass  # library absent; loop still works, transfer just reports none

    lib = PatternLibrary.load(PATTERN_DIR) if os.path.isdir(PATTERN_DIR) else PatternLibrary()
    for name, desc, ref in [
        ("multistart-penalty-optimization",
         "Cold multi-start penalty L-BFGS-B over (x, y, r), then LP-optimal radii.",
         "problems.circle_packing.smart_loop:propose"),
        ("perturb-and-refine",
         "Jitter the best packing's centers and re-optimize from there.",
         "problems.circle_packing.smart_loop:_refine_centers"),
        ("neighborhood-breaker",
         "Perturb + LP-radii attack to test local optimality of a candidate.",
         "problems.circle_packing.smart_loop:breaker_suite"),
    ]:
        if name not in lib.names():
            lib.register(name, desc, ["continuous", "fast-verifier", "local-search"], ref)

    search_budget = budget * 0.8
    breaker_budget = budget * 0.2
    multistart_budget = search_budget * 0.6
    refine_budget = search_budget - multistart_budget
    best = None  # (sum, circles, provenance)
    operator_promoted = set()
    for s, circ, prov in propose(n, multistart_budget, seed):
        chk = verify.check(circ, n)
        if not chk["feasible"]:
            continue
        if best is None or chk["sum"] > best[0] + WIN_MARGIN:
            best = (chk["sum"], circ, prov)
            operator_promoted.add(prov["operator"])

    if best is None:
        raise RuntimeError("no feasible candidate found in the time budget")

    # Operator 2: perturb-and-refine around the multistart winner.
    if refine_budget > 2:
        s, circ, prov = perturb_refine(best[1], refine_budget, seed + 1)
        if circ:
            chk = verify.check(circ, n)
            if chk["feasible"] and chk["sum"] > best[0] + WIN_MARGIN:
                best = (chk["sum"], circ, prov)
                operator_promoted.add("perturb-refine")

    breaker = breaker_suite(best[1], n, breaker_budget, seed + 2)
    if breaker["verdict"] == "broken" and "attack_circles" in breaker:
        # The adversary improved on us: adopt its packing honestly.
        best = (breaker["attack_sum"], breaker["attack_circles"],
                {"operator": "neighborhood-breaker", "seed": seed + 2})
        operator_promoted.add("neighborhood-breaker")
        breaker = breaker_suite(best[1], n, max(1.0, breaker_budget / 4), seed + 3)

    for name in lib.names():
        lib.record_outcome(
            name, name in operator_promoted or
            (name == "neighborhood-breaker" and breaker["verdict"] == "survived"),
            note=f"n={n}: {'produced the promoted packing' if name in operator_promoted else 'no promotion'}; "
                 f"breaker {breaker['verdict']}",
        )
    lib.save(PATTERN_DIR)

    payload = {
        "n": n,
        "circles": best[1],
        "sum": best[0],
        "provenance": best[2],
        "verification": {"feasible": True, "checker": "problems.circle_packing.verify.check"},
        "breaker": {k: v for k, v in breaker.items() if k != "attack_circles"},
        "best_known": record,
        "gap_to_best_known": None if record is None else best[0] - record,
        "elapsed_s": time.time() - t_start,
    }
    if "attack_circles" in breaker:
        payload["breaker_attack_circles"] = breaker["attack_circles"]
    with open(out, "w") as fh:
        json.dump(payload, fh)

    expl_path = os.path.splitext(out)[0] + ".explanation.md"
    write_explanation(expl_path, n=n, result=best, record=record,
                      breaker=breaker, patterns_consulted=transferred,
                      elapsed=time.time() - t_start)

    # Post-loop dashboard: tried / learned / recorded / next / record / publish.
    _write_dashboard(os.path.dirname(os.path.abspath(out)),
                     _dashboard_summary(n, budget, seed, t_start, best, record,
                                        breaker, transferred,
                                        operator_promoted, out, expl_path,
                                        prev_suggestions))
    return payload, expl_path


def _failure_summary(n, budget, seed, t_start, out, error):
    return {
        "problem": "circle_packing",
        "run_name": None,
        "target": f"n={n}",
        "time_budget_s": budget,
        "seed": seed,
        "status": "no_candidate",
        "started": datetime.fromtimestamp(t_start, timezone.utc).isoformat(
            timespec="seconds"),
        "ended": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.time() - t_start, 2),
        "tried": {
            "operators": ["multistart-penalty-optimization"],
            "notes": [f"failed: {error}"],
        },
        "best": {"metric": "sum_of_radii", "value": None,
                 "higher_is_better": True},
        "best_known": {"value": records.load().get(n),
                       "source": "repo records.json"},
        "win_margin": WIN_MARGIN,
        "verifications": {"exact": False, "independent": False,
                          "breaker": None},
        "learned": [f"no feasible candidate in the time budget: {error}"],
        "recorded": {"items": [], "files": []},
        "next_loop": {"suggestions": [
            "no feasible candidate found; try a larger time budget or a "
            "different seed."]},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", required=True, help="number of circles, e.g. 8")
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t_start = time.time()
    try:
        payload, expl = run(int(a.target), a.time, a.seed, a.out)
    except RuntimeError as exc:
        _write_dashboard(os.path.dirname(os.path.abspath(a.out)),
                         _failure_summary(int(a.target), a.time, a.seed,
                                          t_start, a.out, str(exc)))
        raise
    print(json.dumps({
        "sum": payload["sum"],
        "best_known": payload["best_known"],
        "gap": payload["gap_to_best_known"],
        "breaker": payload["breaker"]["verdict"],
        "explanation": expl,
    }, indent=2))


if __name__ == "__main__":
    main()
