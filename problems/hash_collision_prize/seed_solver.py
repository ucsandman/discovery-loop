"""Seed collision solver: van Oorschot-Wiener distinguished-point search on the truncated salted function.

Truncated collisions measure search machinery only; they are not partial progress toward a full collision.

The walk is x -> truncate(H(salt || prefix || x), bits), i.e. every state is itself a legal message body, so a
merge of two walks IS a collision of the truncated function. Chains start at random states and run until they
reach a distinguished point (the low DP_BITS bits are zero) or hit the chain-length cap; only the (start,
length) of each distinguished point is stored. When a second chain reaches a stored distinguished point the two
chains are re-walked from their starts to the step before they merge, which yields two distinct messages with
the same truncated digest. Chains that merge without a collision (equal starts, or a start lying on the other
chain) are discarded, which is the classic Robin-Hood case.

    python seed_solver.py --target sha256-t32-dev --time 60 --seed 1 --out result.json
writes {"target", "m1", "m2", "hashes", "elapsed", "distinguished_points", ...}; nothing is written when no
collision is found inside the budget, because a partial walk is not a result.
"""

import argparse
import hashlib
import json
import os
import random
import sys
import time

if __package__:  # imported as problems.hash_collision_prize.seed_solver (tests): package-qualified helpers
    from . import verify
    from .records import load_target
else:  # standalone use inside the worker; the loop also sets PYTHONPATH
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import verify  # noqa: E402
    from records import load_target  # noqa: E402


CHAIN_CAP_FACTOR = 20  # abandon a chain at 20x the expected distinguished-point distance (cycles, long tails)
DEADLINE_CHECK_MASK = 0x3FF


def dp_bits(bits):
    """Distinguished-point width: chains of ~2^(bits/4) steps keep the stored table small and retraces cheap."""
    return max(4, bits // 4)


def _stepper(spec, prefix):
    """Closure computing one walk step, plus the byte width of a message body."""
    salt = bytes.fromhex(spec["salt"])
    bits = spec["bits"]
    width = (bits + 7) // 8
    shift = 8 * width - bits
    function = spec["function"]
    rounds = spec.get("rounds")
    head = salt + prefix

    if function == "sha256":
        sha256 = hashlib.sha256

        def step(x):
            return int.from_bytes(sha256(head + x.to_bytes(width, "big")).digest()[:width], "big") >> shift

    else:

        def step(x):
            raw = verify.digest(function, rounds, head + x.to_bytes(width, "big"))
            return int.from_bytes(raw[:width], "big") >> shift

    return step, width


def _retrace(step, first, second):
    """Walk two chains that share a distinguished point back to the colliding pair. Returns (pair, steps)."""
    (start_a, len_a), (start_b, len_b) = first, second
    work = 0
    if start_a == start_b:
        return None, work
    xa, xb = start_a, start_b
    while len_a > len_b:
        xa = step(xa)
        len_a -= 1
        work += 1
    while len_b > len_a:
        xb = step(xb)
        len_b -= 1
        work += 1
    if xa == xb:
        return None, work
    for _ in range(len_a):
        na, nb = step(xa), step(xb)
        work += 2
        if na == nb:
            return (xa, xb), work
        xa, xb = na, nb
    return None, work


def solve(spec, budget, seed):
    """Search for a collision within ``budget`` wall seconds. Returns the result dict, or None on a timeout."""
    started = time.time()
    deadline = started + float(budget)
    prefix = b"dl" + (int(seed) & 0xFFFFFFFF).to_bytes(4, "big")
    step, width = _stepper(spec, prefix)
    bits = spec["bits"]
    distinguished = dp_bits(bits)
    dp_mask = (1 << distinguished) - 1
    chain_cap = CHAIN_CAP_FACTOR << distinguished
    rng = random.Random(f"hash_collision_prize:{spec['name']}:{seed}")
    space = 1 << bits
    seen = {}
    hashes = 0
    points = 0
    chains = 0
    abandoned = 0
    found = None

    while found is None and time.time() < deadline:
        start = rng.randrange(space)
        x = start
        length = 0
        chains += 1
        while True:
            x = step(x)
            hashes += 1
            length += 1
            if not x & dp_mask:
                points += 1
                prior = seen.get(x)
                if prior is None:
                    seen[x] = (start, length)
                else:
                    pair, work = _retrace(step, prior, (start, length))
                    hashes += work
                    if pair is not None:
                        found = pair
                break
            if length >= chain_cap:
                abandoned += 1
                break
            if not length & DEADLINE_CHECK_MASK and time.time() >= deadline:
                break

    if found is None:
        return None
    x1, x2 = found
    m1 = (prefix + x1.to_bytes(width, "big")).hex()
    m2 = (prefix + x2.to_bytes(width, "big")).hex()
    checked = verify.check(m1, m2, spec)
    if not checked["feasible"]:
        raise RuntimeError(f"seed solver produced a non-collision: {checked['reason']}")
    elapsed = max(time.time() - started, 1e-6)
    return {
        "target": spec["name"],
        "m1": m1,
        "m2": m2,
        "hashes": hashes,
        "elapsed": elapsed,
        "distinguished_points": points,
        "chains": chains,
        "abandoned_chains": abandoned,
        "dp_bits": distinguished,
        "time_budget": float(budget),
        "digest_prefix": checked["digest_prefix"],
        "notes": "van Oorschot-Wiener distinguished-point search, single process, hashlib",
    }


def write_result(path, payload):
    """Atomic write so a killed worker never leaves a half-written result behind."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, allow_nan=False)
    os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="distinguished-point collision search on a truncated target")
    parser.add_argument("--target", required=True)
    parser.add_argument("--time", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    result = solve(load_target(args.target), budget=args.time, seed=args.seed)
    if result is None:
        print(json.dumps({"target": args.target, "found": False}))
        return 1
    write_result(args.out, result)
    print(json.dumps({k: result[k] for k in ("target", "hashes", "elapsed", "distinguished_points")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
