"""Elliptic-curve discrete logarithm research on a reproducible ladder of prime-field curves.

The ladder mirrors the SHAPE of the Certicom ECCp-131 challenge instance -- y^2 = x^3 + a*x + b over a
prime field F_p, prime group order n, cofactor 1 -- at sizes a laptop can finish: 24 to 40 bits for the
routine rungs and 44/48 bits behind ``--targets``. ECCp-131 itself is METADATA ONLY (see
PRIZE_TARGET_METADATA): it is never a target, nothing here is submitted anywhere, and a ladder result
is a measurement of search machinery, not partial progress on a 131-bit instance.

Value and scoring
  The value of a run is the wall time to a VERIFIED discrete logarithm, so lower is better. The number
  the loop scores is the ``elapsed`` field the worker reports about itself; it is accepted only after
  problems/ecc_prize/verify.py independently recomputes k*P and gets Q, and it is clamped to
  [ELAPSED_FLOOR, ELAPSED_CEILING] so a tampered or absurd stopwatch cannot manufacture a score. That
  self-report is the known weak spot of this plugin (see LIMITATIONS): the loop's own per-row ``secs``
  is the trusted clock and lands in the evidence file beside it for auditing.

There is no record to beat. ``beats`` is always False and ``validate_release`` is unsupported: the
ladder instances are generated in this repository, so no public record exists and no publication or
prize claim can flow from them.
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.ecc_prize import records, verify

TITLE = "ECDLP ladder (prime-field Pollard rho, prize research)"
TARGETS = list(records.TARGETS)
DEVELOPMENT = TARGETS
HOLDOUT = list(records.HOLDOUT)
VALIDATION = HOLDOUT
RELEASE_HOLDOUT = []
LARGE_TARGETS = list(records.LARGE_TARGETS)
DEFAULTS = {"time": 60, "workers": 3}
PATTERN_TAGS = ["number-theory", "collision-search", "random-walk", "batching", "gpu-candidate", "scaling-law"]
MAXIMIZE = False
FAIL_SCORE = -1.0  # a crash, a timeout or an unverified k; equal to the worst finite score (gap clipped at 1.0)
GAP_CLIP = 1.0
CONFIRMATION_ON_DEVELOPMENT = False  # confirmation runs on the hidden holdout rungs
COMPARISON_POLICY = "median"
RELEASE_VALIDATION_SUPPORTED = False
ELAPSED_FLOOR = 1e-4  # a floor only against a zero or negative stopwatch; it stays below every measured baseline
ELAPSED_CEILING = float(DEFAULTS["time"] + 45)  # the sandbox kills the worker at budget + 45 s


def _info():
    out = {}
    for name in records.ALL_TARGETS:
        instance = records.load_instance(name)
        reference = instance.get("reference", {})
        baseline = reference.get("baseline_seconds")
        out[name] = (
            f"{instance['bits']}-bit prime field, group order n = {instance['n']} (prime, cofactor 1), "
            f"expected rho iterations ~{reference.get('expected_iterations', 0):.3g}, "
            f"baseline {'unmeasured' if baseline is None else format(baseline, '.3f') + ' s'}"
        )
    return out


INFO = _info()

FITNESS_METRICS = {
    "iterations": "group operations the walk performed before the collision closed (self-reported)",
    "distinguished_points": "distinguished points stored, i.e. the memory the search actually used",
    "iterations_per_second": "iterations / elapsed; the throughput number a faster field arithmetic moves",
    "expected_iterations": "sqrt(pi*n/2), the rho expectation for this instance (from records.json)",
    "iteration_ratio": "iterations / expected_iterations; below 1.0 means luck or a better-than-rho walk",
    "memory_note": "distinguished points are the whole table; a walk design that stores less is cheaper",
}

PRIZE_TARGET_METADATA = {
    "certicom-eccp-131": {
        "name": "Certicom ECC Challenge ECCp-131",
        "bits": 131,
        "status": "metadata only; never a loop target and never solved or attempted here",
        "curve": "y^2 = x^3 + a*x + b over F_p, cofactor 1",
        "p": "048E1D43F293469E33194C43186B3ABC0B",
        "a": "041CB121CE2B31F608A76FC8F23D73CB66",
        "b": "02F74F717E8DEC90991E5EA9B2FF03DA58",
        "n": "048E1D43F293469E317F7ED728F6B8E6F1",
        "h": 1,
        "P": ["03DF84A96B5688EF574FA91A32E197198A", "014721161917A44FB7B4626F36F0942E71"],
        "Q": ["03AA6F004FC62E2DA1ED0BFB62C3FFB568", "009C21C284BA8A445BB2701BF55E3A67ED"],
        "advertised_prize": "US$20,000",
        "certicom_effort_estimate": "2.3e10 machine days (1997 machines), per the 2009 challenge PDF",
        "source": "https://www.certicom.com/content/dam/certicom/images/pdfs/challenge-2009.pdf",
        "note": (
            "Parameters are reproduced from the public challenge PDF for display and for the scaling "
            "extrapolation. Prize status is uncertain (PDF section 5.1.2 lets Certicom change or withdraw "
            "the challenge without notice); nothing in this repository submits anything."
        ),
    }
}

LIMITATIONS = [
    "The scored value is the worker's own reported elapsed time. Verification is independent, the timing is not; "
    "the loop's per-row secs is the trusted clock and is recorded beside it in evidence.json.",
    "Ladder instances are generated in this repository (problems/ecc_prize/curves.py). They are not a public "
    "benchmark, there is no record to beat, and beats() is always False.",
    "The fastest rungs (24 and 28 bits) finish in hundredths of a second, so their scores carry scheduler noise; "
    "the 36 and 40-bit rungs carry the signal.",
    "A ladder result measures generic collision-search machinery. It is not partial progress toward ECCp-131 or "
    "toward any other real elliptic-curve challenge instance.",
    "The baseline seconds in records.json were measured on one machine (median of three seeds); comparing runs "
    "across machines compares hardware as much as algorithms.",
]

PRIZE = {
    "objective": (
        "Cut the wall time to a verified elliptic-curve discrete logarithm on a ladder of prime-field curves, "
        "and measure how that time scales with the field size."
    ),
    "candidate_artifact": "problems/ecc_prize/solver.py written by the loop (CLI: --target --time --seed --out)",
    "baseline": "problems/ecc_prize/seed_solver.py",
    "development_benchmark": list(DEVELOPMENT),
    "holdout_benchmark": list(HOLDOUT),
    "independent_verifier": "problems/ecc_prize/verify.py",
    "fitness_metrics": dict(FITNESS_METRICS),
    "real_target": "Certicom ECC Challenge ECCp-131 (131-bit prime field; metadata only, never a target here)",
    "prize_registry_id": "certicom-eccp-131",
    "promotion_threshold": {"min_effect": 0.05, "seed_count": 3, "holdout_required": True},
    "estimated_scaling": (
        "Pollard rho costs sqrt(pi*n/2) group operations, so log2(seconds) should rise by about 0.5 per bit of "
        "field size. prize_scaling fits the measured rungs and extrapolates to 131 bits; the honest reading of "
        "that fit is that the real instance needs a change of economics, not tuning."
    ),
    "publication_requirements": (
        "None. A ladder speedup is an internal measurement; any write-up would describe the measured scaling and "
        "say plainly that no challenge instance was attempted."
    ),
    "submission_requirements": (
        "Nothing is submitted. A genuine ECCp-131 solution would be reported by hand per section 5.1.1 of the "
        "Certicom challenge PDF; this plugin has no path to that and no code that touches it."
    ),
}


def records_fetch():
    return records.fetch()


def records_load():
    return records.load()


def solver_argv(t, budget, seed, out):
    return ["--target", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def _metric(payload, key, default=None):
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return value


def evaluate(path, t):
    """Independent re-verification of a solver output file. Returns (seconds, payload) or raises.

    The claim is one integer k. verify.check recomputes k*P from the public instance and compares it
    with Q; only then is the worker's self-reported elapsed time accepted as the value.
    """
    with open(path, encoding="utf-8") as stream:
        d = json.load(stream)
    if d.get("target", t) != t:
        raise ValueError(f"candidate target {d.get('target')!r} does not match {t!r}")
    result = verify.check(d.get("k"), t)
    if not result["feasible"]:
        raise ValueError("unverified: " + (result.get("reason") or "no reason reported"))
    elapsed = _metric(d, "elapsed")
    if elapsed is None or elapsed <= 0:
        raise ValueError("candidate reported no usable elapsed time")
    value = min(max(float(elapsed), ELAPSED_FLOOR), ELAPSED_CEILING)
    iterations = _metric(d, "iterations", 0)
    expected = records.reference(t).get("expected_iterations")
    payload = {
        "k": int(d["k"]),
        "self_reported": True,
        "reported_elapsed": float(elapsed),
        "iterations": iterations,
        "distinguished_points": _metric(d, "distinguished_points", 0),
        "iterations_per_second": (iterations / value) if iterations else 0.0,
        "expected_iterations": expected,
        "iteration_ratio": (iterations / expected) if (iterations and expected) else None,
        "memory_note": "distinguished points stored in the worker's table",
    }
    return value, payload


def score(v, rec):
    """Negative relative gap to the reference baseline seconds, clipped; positive when faster."""
    return 0.0 if rec is None else -min((v - rec) / max(rec, 1e-3), GAP_CLIP)


def better(a, b):
    return a < b


def beats(v, rec):
    """Always False: the ladder instances are generated here, so there is no public record to beat and no
    prize claim can ever be routed through the win gate."""
    return False


def validate_release(path, t, *, record=None):
    """Release validation is not supported: a ladder rung is a benchmark, not a publishable record."""
    metrics = {"target": t, "claim_scope": "ladder_benchmark_only", "reference_seconds": record}
    try:
        with open(path, encoding="utf-8") as stream:
            d = json.load(stream)
        outcome = verify.check(d.get("k"), t)
        metrics["verified"] = bool(outcome["feasible"])
        metrics["reason"] = outcome.get("reason")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        metrics["verified"] = False
        metrics["reason"] = f"invalid candidate: {exc}"
    return {"ok": False, "supported": False, "error": "ladder benchmark; not a public record", "metrics": metrics}


def raw_path(t, best):
    return os.path.join(best, "sol", f"{t}.json")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    with open(raw_path(t, best), "w", encoding="utf-8", newline="\n") as stream:
        json.dump({"target": t, "seconds": value, "author": author, **payload}, stream, allow_nan=False, indent=1)


PROMPT = """You are evolving a Python solver for the elliptic-curve discrete logarithm problem (ECDLP) on a ladder of
generated prime-field curves. Each instance is a short Weierstrass curve y^2 = x^3 + a*x + b over F_p with PRIME group
order n and cofactor 1, a generator P and a challenge point Q = k*P. Your job is to return k, and the score is the WALL
TIME to a verified k: lower is better, and the reference per instance is the seed solver's measured median. The ladder
runs from 24 to 48 bits; it exists so that the same machinery can be measured at several sizes and the scaling read off.

The ladder curves are generated in this repository. There is no record to beat and nothing is submitted anywhere. A real
challenge instance (Certicom ECCp-131) is carried as metadata only and is never a target.

INTERFACE CONTRACT (keep exactly):
  python solver.py --target NAME --time SECONDS --seed S --out PATH
  writes JSON {"target": NAME, "k": int, "iterations": int, "distinguished_points": int, "elapsed": float,
    "notes": str} where k is the discrete logarithm, 1 <= k < n
  must finish within SECONDS (hard kill at SECONDS+45); write the file the moment k is found, atomically
    (write tmp, os.replace), so a later kill still leaves the answer on disk
  print nothing important to stdout; allowed imports: python stdlib and numpy only
  helpers on PYTHONPATH (problems/ecc_prize is on sys.path when the loop runs you; keep the champion's import block):
    from records import load_instance
    load_instance(NAME) -> {"name","bits","p","a","b","n","P":[x,y],"Q":[x,y],"reference":{...}} -- all ints
  k is re-checked independently: the checker recomputes k*P with its own scalar multiplication and compares it with Q,
    and rejects any k outside [1, n). An unverified k, a crash or a timeout scores as the worst case for that target,
    so reliability beats ambition. NEVER read, import or reimplement the checker to shortcut the search.

THE BASELINE YOU ARE REPLACING (problems/ecc_prize/seed_solver.py):
  parallel Pollard rho, 64 walks stepped in lockstep. A walk is a point W = u*P + v*Q carried with the pair (u, v); one
  step is W <- W + S_t where S_t is one of 20 precomputed points and t = x(W) mod 20, so two walks that ever meet stay
  together. A walk publishes (u, v) whenever x(W) ends in `shift` zero bits (a distinguished point); the second walk to
  report the same point closes the collision and k = (u1 - u2) / (v2 - v1) mod n. The 64 affine additions of one batched
  step need ONE modular inverse instead of 64, via Montgomery's simultaneous inversion (prefix products, one
  exponentiation, then a backward pass). u and v are reduced mod n only when a distinguished point is reported.

RESEARCH DIRECTIONS (pick one substantive change or a coherent combination, and say which):
  field arithmetic representation (Montgomery or Barrett reduction instead of Python's %, redundant representations,
    limb-splitting so numpy can carry several walks at once);
  projective or Jacobian coordinates versus affine plus simultaneous inversion, and where the crossover actually is;
  walk design: r-adding walks versus mixed (add/double) walks, the number of partitions, how the partition function is
    computed, and how much bias each choice costs in the expected iteration count;
  the negation map (walking on equivalence classes {W, -W} for a sqrt(2) speedup) WITH explicit fruitless-cycle
    handling, which is the part that usually breaks a naive implementation;
  distinguished-point rate: the trade between table memory, the trailing tail after a collision, and lost work;
  tag tracing and short-cycle detection so a stuck walk is found early rather than at a sweep;
  batch size: the inversion amortises better with more walks, but the per-step Python overhead and cache behaviour do
    not, so the optimum is measurable rather than obvious;
  numpy-vectorised walks over uint32/uint64 limbs, one lane per column, if the per-step overhead can be beaten;
  checkpointing and parallel-walk bookkeeping so the whole budget is used and nothing is recomputed.

INSTANCE NOTES:
""" + "\n".join(f"  {name}: {INFO[name]}" for name in TARGETS)


def prompt_for_targets(targets):
    """Instance notes for exactly the chosen targets; holdout rungs are never named."""
    allowed = set(DEVELOPMENT) | set(LARGE_TARGETS)
    unknown = sorted(set(targets) - allowed)
    if unknown:
        raise ValueError(f"generation prompt requested non-development target(s): {unknown}")
    head = PROMPT.split("INSTANCE NOTES:\n", 1)[0] + "INSTANCE NOTES:\n"
    return head + "\n".join(f"  {name}: {INFO[name]}" for name in targets)


TASK = """TASK: write a complete replacement solver.py that reaches a verified k in less wall time on as many targets as
possible (champion total is the negative relative gap to the reference seconds, summed over targets; a failure counts as
a full gap). Make one substantive algorithmic change rather than a parameter nudge, and make it the kind of change that
would still help two or three rungs further up the ladder: the scaling exponent is what is being measured, so a constant
factor that only helps 24 bits is worth little. State in a comment which direction you took and what you expect it to do
to the iteration count and to the seconds per iteration. Do not repeat an idea that already failed unless you fix its
specific failure."""

TOTAL_DESC = (
    "negative relative gap to the seed solver's reference seconds, summed over targets "
    "(0 = matching the baseline everywhere; a failure = -1 per target)"
)
SUBMIT_NOTE = (
    "Nothing is submitted. The ladder curves are generated in this repository and have no public record; "
    "Certicom ECCp-131 is metadata only (problem.PRIZE_TARGET_METADATA) and is never a target. A real solution "
    "to a Certicom instance would be reported by hand per section 5.1.1 of the 2009 challenge PDF."
)

EMAIL_TO = None  # there is nothing to email: no record, no maintainer, no submission path


def email_subject(cands):
    return f"ECDLP ladder: faster verified solves for {', '.join(t for t, _, _ in cands)}"


def email_body(cands, repo_url):
    rows = "\n".join(f"  {t:<17} ours {v:.3f}s   reference {r:.3f}s" for t, v, r in cands)
    return (
        "Verified ECDLP ladder solves below the recorded reference seconds:\n\n"
        f"{rows}\n\nThese are generated benchmark curves, not a public challenge instance.\n"
        f"Code and checker: {repo_url}\n"
    )
