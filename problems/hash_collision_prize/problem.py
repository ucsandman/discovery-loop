"""Collision-search research on truncated, salted proxy targets -- a ladder, never a bounty target.

Truncated collisions measure search machinery only; they are not partial progress toward a full collision.

Every target is a synthetic instance: a fixed 16-byte salt, a digest function (SHA-256, RIPEMD-160, or
SHA-256 reduced to a stated number of compression rounds) and a truncation width of 28..44 bits. A candidate
solver must produce two distinct messages m1 != m2 of 1..64 bytes whose salted digests agree on the first
`bits` bits; problems/hash_collision_prize/verify.py recomputes that claim from the public target data alone.
The research question is the machinery -- walk design, distinguished-point rate, batching, memory tradeoffs --
measured as wall seconds to a verified collision against the seed solver's recorded baseline.

The four funded Peter Todd bounty scripts are carried in PRIZE_TARGET_METADATA for display only. They are
never targets, nothing here is submitted anywhere, and no code path takes a hash, address, or key from a
user-supplied source.

VALUE IS SELF-TIMED, AND THAT IS A LIMITATION: `evaluate` reads the wall seconds the worker reported in its
own output file, because the plugin API hands the verifier only a path and a target name. The loop's own
`secs` per row is the trusted clock and lands in evidence beside every value, so an inflated or deflated
self-report is auditable after the fact; the reported number is clamped to a sane band before it is scored.
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
    from problems.hash_collision_prize import records, verify

NON_CLAIM = "Truncated collisions measure search machinery only; they are not partial progress toward a full collision."

TITLE = "Truncated-digest collision search ladder (salted synthetic targets)"
TARGETS = list(records.DEVELOPMENT)
DEVELOPMENT = TARGETS
HOLDOUT = list(records.HOLDOUT)
VALIDATION = HOLDOUT
RELEASE_HOLDOUT = []
LARGE_TARGETS = list(records.LARGE_TARGETS)
DEFAULTS = {"time": 60, "workers": 3}
PATTERN_TAGS = [
    "collision-search",
    "random-walk",
    "distinguished-points",
    "simd-candidate",
    "gpu-candidate",
    "scaling-law",
]
MAXIMIZE = False
FAIL_SCORE = -1.0  # no verified collision inside the budget: strictly worse than any verified solve
CONFIRMATION_ON_DEVELOPMENT = False  # confirmation runs on the concealed holdout ladder
COMPARISON_POLICY = "median"
RELEASE_VALIDATION_SUPPORTED = False
VALUE_FLOOR_SECONDS = 1e-4  # a floor only against a zero or negative stopwatch; it stays below every measured baseline
VALUE_CEILING_MARGIN_SECONDS = 45.0  # the sandbox kills a worker at budget + 45 s
MAX_TIME_BUDGET_SECONDS = 3600.0

FITNESS_METRICS = {
    "hashes": "digest evaluations the solver counted, including retrace steps (self-reported)",
    "hashes_per_second": "hashes divided by the solver's own elapsed seconds (self-reported)",
    "expected_hashes": "birthday expectation sqrt(pi/2) * 2^(bits/2) for this target, from records.json",
    "ratio": "hashes / expected_hashes; below 1.0 means the walk got lucky, not that it beat the bound",
    "distinguished_points": "distinguished points stored before the collision (memory proxy, self-reported)",
}

LIMITATIONS = [
    NON_CLAIM,
    "Value is the worker's self-reported wall time to a verified collision; the loop's own per-row secs is the "
    "trusted clock and is recorded beside it in evidence.",
    "Baselines are single-machine medians of three seed-solver runs (records.json reference.note), not published "
    "records; nothing here is comparable to another lab's hardware.",
    "Collision search is a birthday process, so per-seed times vary by an order of magnitude; only a replicated "
    "median across seeds is evidence of a real speedup.",
    "The short targets take well under a second on this machine, so measurement noise dominates there; the 36-44 "
    "bit rungs carry the signal.",
    "Reduced-round SHA-256 targets exercise the search machinery against a weakened permutation; a result there "
    "says nothing about full SHA-256.",
]


def _info():
    table = records.table()
    out = {}
    for name in records.ALL_TARGETS:
        spec = table[name]
        reference = spec["reference"]
        rounds = "full" if spec["rounds"] is None else f"{spec['rounds']} rounds"
        baseline = reference.get("baseline_seconds")
        out[name] = (
            f"{spec['function']} ({rounds}), truncated to {spec['bits']} bits, 16-byte salt; "
            f"expected hashes {reference['expected_hashes']:.3g}; "
            f"seed-solver baseline {'unmeasured' if baseline is None else f'{baseline:.3f}s'}"
        )
    return out


INFO = _info()

PRIZE_TARGET_METADATA = {
    "non_claim": NON_CLAIM,
    "observed_on": "2026-09-20",
    "source": "https://bitcointalk.org/index.php?topic=293382.0",
    "balances_observed_via": "https://mempool.space/api/address/<address>",
    "btc_usd_observed": 80304,
    "bounties": {
        "todd-sha256-collision": {
            "bits": 256,
            "function": "SHA-256",
            "address": "35Snmmy3uhaer2gTboc81ayCip4m9DT4ko",
            "balance_btc": 0.27734251,
            "script": "OP_2DUP OP_EQUAL OP_NOT OP_VERIFY OP_SHA256 OP_SWAP OP_SHA256 OP_EQUAL",
            "script_provenance": "transcribed from the bounty thread",
            "claim_requirements": "two distinct preimages under 521 bytes that the P2SH redeem script accepts",
            "non_claim": NON_CLAIM,
        },
        "todd-ripemd160-collision": {
            "bits": 160,
            "function": "RIPEMD-160",
            "address": "3KyiQEGqqdb4nqfhUzGKN6KPhXmQsLNpay",
            "balance_btc": 0.11576888,
            "script": "OP_2DUP OP_EQUAL OP_NOT OP_VERIFY OP_RIPEMD160 OP_SWAP OP_RIPEMD160 OP_EQUAL",
            "script_provenance": "opcode sequence by analogy with the SHA-256 bounty; read the on-chain redeem "
            "script before relying on it",
            "claim_requirements": "two distinct preimages under 521 bytes that the P2SH redeem script accepts",
            "non_claim": NON_CLAIM,
        },
        "todd-hash160-collision": {
            "bits": 160,
            "function": "HASH160 = RIPEMD-160(SHA-256(x))",
            "address": "39VXyuoc6SXYKp9TcAhoiN1mb4ns6z3Yu6",
            "balance_btc": 0.10026873,
            "script": "OP_2DUP OP_EQUAL OP_NOT OP_VERIFY OP_HASH160 OP_SWAP OP_HASH160 OP_EQUAL",
            "script_provenance": "opcode sequence by analogy with the SHA-256 bounty; read the on-chain redeem "
            "script before relying on it",
            "claim_requirements": "two distinct preimages under 521 bytes that the P2SH redeem script accepts",
            "non_claim": NON_CLAIM,
        },
        "todd-hash256-collision": {
            "bits": 256,
            "function": "HASH256 = SHA-256(SHA-256(x))",
            "address": "3DUQQvz4t57Jy7jxE86kyFcNpKtURNf1VW",
            "balance_btc": 0.10026873,
            "script": "OP_2DUP OP_EQUAL OP_NOT OP_VERIFY OP_HASH256 OP_SWAP OP_HASH256 OP_EQUAL",
            "script_provenance": "opcode sequence by analogy with the SHA-256 bounty; read the on-chain redeem "
            "script before relying on it",
            "claim_requirements": "two distinct preimages under 521 bytes that the P2SH redeem script accepts",
            "non_claim": NON_CLAIM,
        },
    },
}

PRIZE = {
    "objective": "Lower the verified wall time to a truncated-digest collision on the salted ladder targets.",
    "candidate_artifact": (
        "solver.py writing {'target', 'm1': hex, 'm2': hex, 'hashes', 'elapsed', 'distinguished_points'} "
        "to the --out path"
    ),
    "baseline": "problems/hash_collision_prize/seed_solver.py",
    "development_benchmark": list(DEVELOPMENT),
    "holdout_benchmark": list(HOLDOUT),
    "independent_verifier": "problems/hash_collision_prize/verify.py",
    "fitness_metrics": dict(FITNESS_METRICS),
    "real_target": (
        "Peter Todd's funded hash-collision bounties (full SHA-256, RIPEMD-160, HASH160, HASH256). " + NON_CLAIM
    ),
    "prize_registry_id": "todd-sha256-collision",
    "promotion_threshold": {"min_effect": 0.05, "seed_count": 5, "holdout_required": True},
    "estimated_scaling": (
        "A generic birthday search costs sqrt(pi/2) * 2^(bits/2) digests, so the measured ladder extrapolates as "
        "log2(seconds) = alpha + 0.5 * bits. At 160 bits that is ~2^80 digests and at 256 bits ~2^128; no amount "
        "of engineering on this ladder closes that gap."
    ),
    "publication_requirements": (
        "A measured speedup on the ladder is a solver-engineering result: it needs the paired confirmation rows, "
        "the seeds, the machine, and the scaling fit, and it must carry the non-claim sentence."
    ),
    "submission_requirements": (
        "Nothing is submitted. The bounties are spendable scripts, not a submission process; no code path here "
        "touches a wallet, a key, or an address."
    ),
}


def records_fetch():
    return records.fetch()


def records_load():
    return records.load()


def solver_argv(t, budget, seed, out):
    return ["--target", t, "--time", str(budget), "--seed", str(seed), "--out", out]


def _value_ceiling(payload):
    """Upper clamp for a self-reported solve time: the worker's own budget plus the sandbox kill margin."""
    try:
        budget = float(payload.get("time_budget"))
    except (TypeError, ValueError):
        budget = float(DEFAULTS["time"])
    if not math.isfinite(budget) or budget <= 0:
        budget = float(DEFAULTS["time"])
    return min(budget, MAX_TIME_BUDGET_SECONDS) + VALUE_CEILING_MARGIN_SECONDS


def evaluate(path, t):
    """Independent re-verification. Value = wall seconds to a VERIFIED collision (lower is better)."""
    d = json.load(open(path))
    if d.get("target", t) != t:
        raise ValueError(f"candidate target {d.get('target')!r} does not match {t!r}")
    res = verify.check(d.get("m1"), d.get("m2"), t)
    if not res["feasible"]:
        raise ValueError("no verified collision: " + (res.get("reason") or "unknown reason"))
    try:
        elapsed = float(d["elapsed"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("candidate did not report a finite elapsed time")
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError(f"candidate reported a non-positive elapsed time: {d.get('elapsed')!r}")
    value = min(max(elapsed, VALUE_FLOOR_SECONDS), _value_ceiling(d))

    spec = records.load_target(t)
    expected = spec["reference"]["expected_hashes"]
    hashes = d.get("hashes")
    hashes = float(hashes) if isinstance(hashes, (int, float)) and not isinstance(hashes, bool) else None
    payload = {
        "m1": d["m1"],
        "m2": d["m2"],
        "digest_prefix": res["digest_prefix"],
        "bits": spec["bits"],
        "hashes": hashes,
        "hashes_per_second": (hashes / elapsed) if hashes else None,
        "expected_hashes": expected,
        "ratio": (hashes / expected) if hashes else None,
        "distinguished_points": d.get("distinguished_points"),
        "reported_elapsed": elapsed,
        "self_reported": True,
    }
    return value, payload


def score(v, rec):
    """Negative relative gap to the seed-solver baseline seconds; +1 at instant, -1 at twice the baseline."""
    if rec is None:
        return 0.0  # no measured baseline for this target: a verified solve is neutral, a failure is still -1
    return -min((v - rec) / max(rec, 1e-3), 1.0)


def better(a, b):
    return a < b


def beats(v, rec):
    """Always False: the ladder targets are synthetic proxies, so there is no public record to beat and no
    prize claim ever travels through this gate."""
    return False


def validate_release(path, t, *, record=None):
    """Release validation is not supported: a ladder time is a benchmark, never a publishable record."""
    metrics = {"target": t, "claim_scope": "ladder_benchmark_only", "non_claim": NON_CLAIM}
    return {
        "ok": False,
        "supported": False,
        "error": "ladder benchmark; not a public record",
        "metrics": metrics,
    }


def raw_path(t, best):
    return os.path.join(best, "sol", f"{t}.json")


def save(t, payload, value, best, author):
    os.makedirs(os.path.join(best, "sol"), exist_ok=True)
    json.dump(
        {"target": t, "elapsed": value, "m1": payload["m1"], "m2": payload["m2"], "author": author},
        open(raw_path(t, best), "w"),
    )


PROMPT = (
    """You are evolving a Python collision-search program for TRUNCATED, SALTED digest targets. """
    + NON_CLAIM
    + """
The bounty-sized functions are out of reach by many orders of magnitude; what is being measured here is the
machinery -- how many digests per second a walk sustains, how cheaply distinguished points are stored and
retraced, and how the wall time scales with the truncation width.

Each target fixes a digest function, an optional reduced round count, a truncation width in bits, and a fixed
16-byte salt. A solution is two DISTINCT messages m1 != m2, each 1 to 64 bytes, such that the first `bits` bits
of digest(salt || m) agree. Value is the wall seconds to a verified collision, lower is better; the record per
target is the seed solver's own measured median on this machine.

INTERFACE CONTRACT (keep exactly):
  python solver.py --target NAME --time SECONDS --seed S --out PATH
  writes JSON {"target": NAME, "m1": hex, "m2": hex, "hashes": int, "elapsed": float,
               "distinguished_points": int, "time_budget": float}
  m1 and m2 are hex strings of 1..64 bytes each and must be different messages
  must finish within SECONDS (hard kill at SECONDS+45); write the result the moment a collision is verified,
    atomically (write tmp, os.replace) -- no file at all is scored as a failure, so never write a partial walk
  allowed imports: python stdlib and numpy only; no network, no subprocesses, no extra packages
  helpers on PYTHONPATH (problems/hash_collision_prize is on sys.path when the loop runs you; keep the
    champion's import block):
      from records import load_target   -> {"name","function","rounds","bits","salt" (hex), "reference": {...}}
      from verify import digest, truncated_int, check
      digest(function, rounds, data) -> full digest bytes; truncated_int(data, bits) -> the first `bits` bits
      check(m1_hex, m2_hex, target) -> the exact independent check the loop runs; call it before writing
  the same verifier re-runs on the output file: a wrong prefix, an oversized message, equal messages, or a
    missing file all score as a failure, so verify before you write
  seeds differ between runs; make the search actually depend on --seed or every seed repeats one walk

TARGET NOTES:
"""
    + "\n".join(f"  {k}: {INFO[k]}" for k in DEVELOPMENT)
)


def prompt_for_targets(targets):
    selectable = set(DEVELOPMENT) | set(LARGE_TARGETS)
    unknown = sorted(set(targets) - selectable)
    if unknown:
        raise ValueError(f"generation prompt requested non-development target(s): {unknown}")
    head = PROMPT.split("TARGET NOTES:\n", 1)[0] + "TARGET NOTES:\n"
    return head + "\n".join(f"  {name}: {INFO[name]}" for name in targets)


TASK = """TASK: write a complete replacement solver.py that reaches a verified collision faster on as many targets
as possible (champion total is the negative relative gap to the seed-solver baseline, summed over targets).
Make one substantive algorithmic or engineering improvement, not a parameter nudge. Candidates: tune the
distinguished-point rate against chain-retrace cost and memory; replace the scalar walk with a batched or
numpy-vectorised one so many walks advance per interpreter step; pack the walk state so the hashed buffer is
built once and mutated in place instead of re-concatenated; exploit hashlib's copy() to reuse a pre-fed salt
prefix; cut the per-step object churn (int.to_bytes, slicing, dict lookups); parallel walks with a shared
distinguished-point table and proper Robin-Hood handling (chains that merge without colliding); memory/DP
tradeoffs for the wider targets where the table stops fitting comfortably; a cycle-aware chain cap. For the
reduced-round target, differential characteristics of the weakened compression function are a separate and
legitimate line of study -- treat any result there as a statement about the reduced permutation only. A GPU
walk is the obvious future path but is out of scope here; document it rather than pretend to ship it.
Do not repeat an idea that already failed unless you fix its specific failure."""

TOTAL_DESC = (
    "negative relative gap to the seed-solver baseline seconds, summed over targets "
    "(0 = matching the baseline everywhere; a failed or unverified target = -1)"
)
SUBMIT_NOTE = (
    "Nothing is submitted. The ladder targets are salted synthetic proxies with no public record and no prize. "
    + NON_CLAIM
    + " The funded bounty scripts in PRIZE_TARGET_METADATA are display metadata only."
)

EMAIL_TO = None  # there is no submission address and no claim to make


def email_subject(cands):
    return "hash_collision_prize ladder timings (no claim)"


def email_body(cands, repo_url):
    rows = "\n".join(f"  {t:<20} {v:.3f}s   baseline {r}" for t, v, r in cands)
    return f"Verified truncated-collision ladder times:\n\n{rows}\n\n{NON_CLAIM}\n\nCode and checker: {repo_url}\n"
