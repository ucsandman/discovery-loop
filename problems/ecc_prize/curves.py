"""Deterministic generation of the ECDLP research ladder (and the baseline measurement that fills it in).

Every instance is reproducible from its name alone: the byte stream that picks p, a, b, the generator
and the secret scalar is sha256("ecc_prize:<bits>:<tag>") run as a counter-mode expansion, so
``make_instance(24, "dev")`` returns the same curve on every machine and in every checkout.

Curve shape and point counting
  * p is a prime of exactly ``bits`` bits with p % 4 == 3, which makes square roots a single
    exponentiation and keeps this file free of Tonelli-Shanks.
  * a, b are drawn until 4a^3 + 27b^2 != 0 (non-singular).
  * the group order is found by baby-step giant-step on the Hasse interval |#E - (p+1)| <= 2*sqrt(p):
    all M = p + 1 + j with M*P = O are collected in O(p^(1/4)) point operations. If one of them is
    PRIME then ord(P) = M (a prime multiple of ord(P) with P != O leaves no other option), and since
    M is far larger than the width 4*sqrt(p) of the interval, M is the only multiple of itself inside
    it, so #E = M exactly. Curves whose order is not prime are rejected, which gives cofactor 1.
  * anomalous (n == p) and supersingular (n == p + 1) curves are rejected as degenerate.

Nothing secret is written: make_instance returns the public dict and the scalar separately, and
``--write`` stores only the public dict.

    python problems/ecc_prize/curves.py --write            # regenerate records.json and measure baselines
    python problems/ecc_prize/curves.py --write --no-measure
    python problems/ecc_prize/curves.py --measure --seeds 3 --time 60
    python problems/ecc_prize/curves.py --show
"""

import argparse
import hashlib
import json
import math
from math import isqrt
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records, verify
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.ecc_prize import records, verify

# Deterministic for every n < 3.3e24, which covers the whole ladder with room to spare.
_MR_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
CURVE_ATTEMPTS = 4000
LARGE_MEASURE_LIMIT = 120.0  # a large rung whose first seed needs longer than this records a null baseline


class _Rng:
    """Counter-mode sha256 expansion: a reproducible byte stream with no dependency on random.Random."""

    def __init__(self, seed):
        self._seed = seed
        self._counter = 0

    def bits(self, width):
        need = (width + 7) // 8
        buffer = b""
        while len(buffer) < need:
            buffer += hashlib.sha256(self._seed + self._counter.to_bytes(8, "big")).digest()
            self._counter += 1
        return int.from_bytes(buffer[:need], "big") >> (need * 8 - width)

    def below(self, bound):
        width = bound.bit_length()
        while True:
            value = self.bits(width)
            if value < bound:
                return value


def is_probable_prime(value):
    """Deterministic Miller-Rabin over _MR_BASES (valid well beyond the 48-bit ceiling used here)."""
    if value < 2:
        return False
    for small in _MR_BASES:
        if value % small == 0:
            return value == small
    d, r = value - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for base in _MR_BASES:
        witness = pow(base, d, value)
        if witness in (1, value - 1):
            continue
        for _ in range(r - 1):
            witness = witness * witness % value
            if witness == value - 1:
                break
        else:
            return False
    return True


def generate_prime(rng, bits):
    """A prime of exactly ``bits`` bits with p % 4 == 3."""
    while True:
        candidate = rng.bits(bits) | (1 << (bits - 1)) | 3
        if candidate % 4 == 3 and is_probable_prime(candidate):
            return candidate


def random_point(p, a, b, rng, attempts=400):
    """A uniform-ish curve point, using the p % 4 == 3 square-root shortcut. None when unlucky."""
    for _ in range(attempts):
        x = rng.below(p)
        rhs = (x * x * x + a * x + b) % p
        if rhs == 0:
            return (x, 0)
        if pow(rhs, (p - 1) // 2, p) != 1:
            continue
        return (x, pow(rhs, (p + 1) // 4, p))
    return None


def annihilators(point, p, a, hasse, step):
    """{M = p + 1 + j : |j| <= hasse and M*point == O}, by baby-step giant-step."""
    table = {}
    zero_hits = []
    current = None
    for index in range(step):
        if current is None:
            zero_hits.append(index)
        else:
            table.setdefault(verify.negate(current, p), []).append(index)
        current = verify.point_add(current, point, p, a)
    giant = verify.scalar_mult(step, point, p, a)
    window = hasse // step + 2
    walker = verify.point_add(verify.scalar_mult(p + 1, point, p, a), verify.scalar_mult(-window, giant, p, a), p, a)
    found = set()
    for multiple in range(-window, window + 1):
        for index in zero_hits if walker is None else table.get(walker, ()):
            offset = index + step * multiple
            if abs(offset) <= hasse:
                found.add(p + 1 + offset)
        walker = verify.point_add(walker, giant, p, a)
    return found


def curve_order(p, a, b, rng):
    """#E(F_p) when it is prime, else None (the caller rejects the curve)."""
    hasse = 2 * isqrt(p) + 1
    step = isqrt(2 * hasse) + 1
    point = random_point(p, a, b, rng)
    if point is None:
        return None
    primes = sorted(value for value in annihilators(point, p, a, hasse, step) if is_probable_prime(value))
    return primes[0] if primes else None


def expected_iterations(order):
    """Pollard rho / birthday expectation for a cyclic group of prime order n: sqrt(pi*n/2)."""
    return math.sqrt(math.pi * order / 2.0)


def make_instance(bits, tag):
    """(public instance dict, secret scalar k). Deterministic in (bits, tag); the scalar is not stored."""
    if bits < 20:
        raise ValueError("the ladder starts at 20 bits; smaller curves make the point counting degenerate")
    rng = _Rng(hashlib.sha256(f"ecc_prize:{bits}:{tag}".encode("utf-8")).digest())
    p = generate_prime(rng, bits)
    for _ in range(CURVE_ATTEMPTS):
        a = rng.below(p)
        b = rng.below(p)
        if (4 * a * a * a + 27 * b * b) % p == 0:
            continue
        order = curve_order(p, a, b, rng)
        if order is None or order in (p, p + 1):
            continue
        generator = random_point(p, a, b, rng)
        if generator is None or verify.scalar_mult(order, generator, p, a) is not None:
            continue
        secret = 1 + rng.below(order - 1)
        challenge = verify.scalar_mult(secret, generator, p, a)
        instance = {
            "name": f"ecdlp-p{bits}-{tag}",
            "bits": bits,
            "p": p,
            "a": a,
            "b": b,
            "n": order,
            "P": [generator[0], generator[1]],
            "Q": [challenge[0], challenge[1]],
        }
        return instance, secret
    raise RuntimeError(f"no prime-order curve found over the generated {bits}-bit prime")


def build_ladder():
    """Every ladder instance keyed by name, with an unmeasured reference block."""
    built = {}
    for name in records.ALL_TARGETS:
        bits = records.BITS[name]
        tag = name.rsplit("-", 1)[1]
        instance, _secret = make_instance(bits, tag)
        if instance["name"] != name:
            raise RuntimeError(f"generated {instance['name']!r} for target {name!r}")
        instance["reference"] = {
            "baseline_seconds": None,
            "expected_iterations": expected_iterations(instance["n"]),
        }
        built[name] = instance
    return built


DIGESTS_BEGIN = "# DIGESTS-BEGIN"
DIGESTS_END = "# DIGESTS-END"


def digests_for(document):
    """{target: digest} for every declared target of one ladder document, in ALL_TARGETS order."""
    instances = document["instances"]
    return {name: records.digest_for(instances[name]) for name in records.ALL_TARGETS}


def _digest_block(document):
    """The generated ``DIGESTS = {...}`` literal for one ladder document."""
    lines = ["DIGESTS = {"]
    for name, digest in digests_for(document).items():
        lines.append('    "%s": "%s",' % (name, digest))
    lines.append("}")
    return "\n".join(lines)


def write_digests(document, path=None):
    """Rewrite the generated DIGESTS block in records.py from ``document`` and reload it in this process."""
    path = path or os.path.join(HERE, "records.py")
    with open(path, encoding="utf-8") as stream:
        source = stream.read()
    start = source.index("\n", source.index(DIGESTS_BEGIN)) + 1
    end = source.index(DIGESTS_END)
    updated = source[:start] + _digest_block(document) + "\n" + source[end:]
    if updated != source:
        with open(path, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(updated)
    records.DIGESTS = digests_for(document)
    records.fetch()
    return records.DIGESTS


def _write(document):
    with open(records.RECORDS, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=1, allow_nan=False)
        stream.write("\n")


def measure(document, names, *, seeds, budget, large_limit=LARGE_MEASURE_LIMIT):
    """Fill reference.baseline_seconds with the seed solver's median wall time over ``seeds`` seeds."""
    sys.path.insert(0, HERE)
    import seed_solver  # dev-only import; neither problem.py nor verify.py may reach the baseline solver

    for name in names:
        instance = document["instances"][name]
        large = name in records.LARGE_TARGETS
        timings = []
        for seed in range(1, seeds + 1):
            started = time.perf_counter()
            outcome = seed_solver.solve(instance, deadline=started + budget, seed=seed)
            elapsed = time.perf_counter() - started
            if outcome.get("k") is None:
                print(f"  {name} seed {seed}: unsolved in {elapsed:.1f}s")
                timings = []
                break
            print(f"  {name} seed {seed}: {elapsed:.3f}s ({outcome['iterations']} iterations)")
            timings.append(elapsed)
            if large and elapsed > large_limit:
                print(f"  {name}: first seed exceeded {large_limit:.0f}s; recording a null baseline")
                timings = []
                break
        instance["reference"]["baseline_seconds"] = round(statistics.median(timings), 4) if timings else None
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description="generate and measure the ECDLP ladder")
    parser.add_argument("--write", action="store_true", help="regenerate every instance into records.json")
    parser.add_argument("--measure", action="store_true", help="measure baselines into the existing records.json")
    parser.add_argument("--no-measure", action="store_true", help="skip measurement after --write")
    parser.add_argument("--show", action="store_true", help="print the committed ladder")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--time", type=float, default=60.0)
    parser.add_argument("--targets", default="", help="comma separated subset for --measure")
    args = parser.parse_args(argv)

    if args.show or not (args.write or args.measure):
        for name in records.ALL_TARGETS:
            instance = records.load_instance(name)
            print(f"{name:17} bits={instance['bits']:3} n={instance['n']} reference={instance['reference']}")
        return 0

    if args.write:
        document = {
            "schema_version": 1,
            "generated_at": time.strftime("%Y-%m-%d", time.gmtime()),
            "generator": "problems/ecc_prize/curves.py --write",
            "note": "public instance data only; no discrete logarithm is stored",
            "targets": {
                "development": list(records.DEVELOPMENT),
                "holdout": list(records.HOLDOUT),
                "large": list(records.LARGE_TARGETS),
            },
            "instances": build_ladder(),
        }
        _write(document)
        write_digests(document)
        print(f"wrote {len(document['instances'])} instances to {records.RECORDS} (DIGESTS updated in records.py)")
    else:
        records.fetch()
        document = records.table()

    if args.measure or (args.write and not args.no_measure):
        chosen = [name.strip() for name in args.targets.split(",") if name.strip()] or list(records.ALL_TARGETS)
        unknown = [name for name in chosen if name not in document["instances"]]
        if unknown:
            raise SystemExit(f"unknown target(s): {unknown}")
        measure(document, chosen, seeds=args.seeds, budget=args.time)
        _write(document)
        print(f"measured {len(chosen)} target(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
