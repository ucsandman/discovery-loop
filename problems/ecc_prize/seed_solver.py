"""Seed ECDLP solver: parallel Pollard rho with an r-adding walk, distinguished points and batched
affine additions.

The search runs BATCH independent walks at once. Every walk is a point W = u*P + v*Q together with the
pair (u, v); one step replaces W by W + S_t where S_t is one of R_STEPS precomputed points and t is a
function of W's x coordinate alone, so two walks that ever meet stay together. A walk stores (u, v)
whenever its x coordinate ends in ``shift`` zero bits (a distinguished point); the second walk to
report the same distinguished point closes a collision and

    u1 + v1*k == u2 + v2*k  (mod n)   =>   k = (u1 - u2) / (v2 - v1)  (mod n)

The batching is the point of the baseline: an affine addition needs one modular inverse, and BATCH of
them need only ONE inverse plus 3*(BATCH-1) multiplications through Montgomery's simultaneous
inversion trick, which is why the lanes step in lockstep. The accumulators u and v are reduced modulo
n only when a distinguished point is reported, not on every step.

Pure Python integers, no numpy, no imports from verify.py: the checker stays an independent code path.

    python seed_solver.py --target ecdlp-p32-dev --time 60 --seed 1 --out result.json
writes {"target", "k", "iterations", "distinguished_points", "elapsed", "notes"} with k null when the
budget ran out before a collision closed.
"""

import argparse
import json
import os
import random
import sys
import time

if __package__:  # imported as problems.ecc_prize.seed_solver (tests): keep the package-qualified helper
    from .records import load_instance
else:  # standalone use inside the worker; the loop also sets PYTHONPATH
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from records import load_instance  # noqa: E402

R_STEPS = 20  # size of the r-adding step table
BATCH = 64  # walks stepped per simultaneous inversion
CLOCK_EVERY = 8  # batched steps between wall-clock reads
SWEEP_EVERY = 512  # batched steps between fruitless-walk sweeps


def _point_add(first, second, p, a):
    """Affine addition on y^2 = x^3 + a*x + b over F_p; ``None`` is the point at infinity."""
    if first is None:
        return second
    if second is None:
        return first
    x1, y1 = first
    x2, y2 = second
    if x1 == x2:
        if (y1 + y2) % p == 0:
            return None
        lam = (3 * x1 * x1 + a) * pow(2 * y1 % p, p - 2, p) % p
    else:
        lam = (y2 - y1) * pow(x2 - x1, p - 2, p) % p
    x3 = (lam * lam - x1 - x2) % p
    return (x3, (lam * (x1 - x3) - y1) % p)


def _scalar_mult(k, point, p, a):
    """k*point by right-to-left add-and-double (the setup path; the walk itself never doubles)."""
    result = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend, p, a)
        addend = _point_add(addend, addend, p, a)
        k >>= 1
    return result


def distinguished_shift(bits):
    """Trailing-zero width for a distinguished point: about 1250 stored points at the rho expectation."""
    return max(2, bits // 2 - 10)


def solve(instance, *, deadline, seed, batch=BATCH, steps=R_STEPS, shift=None):
    """Search for the discrete logarithm of Q base P. Returns the result fields without timing."""
    p = int(instance["p"])
    a = int(instance["a"])
    n = int(instance["n"])
    generator = (int(instance["P"][0]), int(instance["P"][1]))
    challenge = (int(instance["Q"][0]), int(instance["Q"][1]))
    bits = int(instance.get("bits") or p.bit_length())
    shift = distinguished_shift(bits) if shift is None else shift
    mask = (1 << shift) - 1
    fruitless = 24 << shift  # batched steps a walk may run without a distinguished point
    rng = random.Random(f"ecc_prize:{instance.get('name')}:{seed}")

    def combine():
        """A random u*P + v*Q with the pair that produced it."""
        while True:
            u = rng.randrange(1, n)
            v = rng.randrange(1, n)
            point = _point_add(_scalar_mult(u, generator, p, a), _scalar_mult(v, challenge, p, a), p, a)
            if point is not None:
                return u, v, point

    step_a, step_b, step_x, step_y = [], [], [], []
    for _ in range(steps):
        u, v, point = combine()
        step_a.append(u)
        step_b.append(v)
        step_x.append(point[0])
        step_y.append(point[1])

    xs, ys, us, vs, seen_at = [], [], [], [], []
    for _ in range(batch):
        u, v, point = combine()
        xs.append(point[0])
        ys.append(point[1])
        us.append(u)
        vs.append(v)
        seen_at.append(0)

    def respawn(lane, step_no):
        u, v, point = combine()
        xs[lane], ys[lane] = point
        us[lane], vs[lane] = u, v
        seen_at[lane] = step_no

    table = {}
    lanes = range(batch)
    iterations = 0
    collisions = 0
    step_no = 0
    found = None
    notes = "budget exhausted before a collision closed"

    while found is None and time.perf_counter() < deadline:
        for _ in range(CLOCK_EVERY):
            step_no += 1
            picks = []
            dens = []
            blocked = []
            for lane in lanes:
                x = xs[lane]
                t = x % steps
                picks.append(t)
                gap = step_x[t] - x
                if gap:
                    dens.append(gap)
                else:  # W equals the step point: doubling or the identity, both rare
                    dens.append(1)
                    blocked.append(lane)
            prefix = []
            acc = 1
            for gap in dens:
                prefix.append(acc)
                acc = acc * gap % p
            running = pow(acc, p - 2, p)
            invs = [0] * batch
            for lane in range(batch - 1, -1, -1):
                invs[lane] = running * prefix[lane] % p
                running = running * dens[lane] % p

            for lane in lanes:
                t = picks[lane]
                x1 = xs[lane]
                x2 = step_x[t]
                if x1 == x2:  # blocked lane, respawned below
                    continue
                y1 = ys[lane]
                lam = (step_y[t] - y1) * invs[lane] % p
                x3 = (lam * lam - x1 - x2) % p
                xs[lane] = x3
                ys[lane] = (lam * (x1 - x3) - y1) % p
                us[lane] += step_a[t]
                vs[lane] += step_b[t]
                iterations += 1
                if x3 & mask:
                    continue
                u2 = us[lane] % n
                v2 = vs[lane] % n
                previous = table.get(x3)
                if previous is None:
                    table[x3] = (u2, v2)
                    seen_at[lane] = step_no
                    continue
                collisions += 1
                u1, v1 = previous
                delta = (v2 - v1) % n
                if delta:
                    candidate = (u1 - u2) * pow(delta, -1, n) % n
                    if candidate and _scalar_mult(candidate, generator, p, a) == challenge:
                        found = candidate
                        notes = f"collision at distinguished point after {iterations} iterations"
                        break
                respawn(lane, step_no)
            if found is not None:
                break
            for lane in blocked:
                respawn(lane, step_no)
            if step_no % SWEEP_EVERY == 0:
                for lane in lanes:
                    if step_no - seen_at[lane] > fruitless:
                        respawn(lane, step_no)

    return {
        "k": found,
        "iterations": iterations,
        "distinguished_points": len(table),
        "collisions": collisions,
        "walks": batch,
        "distinguished_shift": shift,
        "notes": notes,
    }


def solve_target(target, *, budget, seed, batch=BATCH, steps=R_STEPS):
    """Solve one named ladder target and return the on-disk result shape."""
    instance = load_instance(target)
    started = time.perf_counter()
    outcome = solve(instance, deadline=started + budget, seed=seed, batch=batch, steps=steps)
    elapsed = time.perf_counter() - started
    result = {"target": target, "k": outcome["k"], "iterations": outcome["iterations"]}
    result["distinguished_points"] = outcome["distinguished_points"]
    result["elapsed"] = elapsed
    result["notes"] = outcome["notes"]
    result["collisions"] = outcome["collisions"]
    result["walks"] = outcome["walks"]
    result["distinguished_shift"] = outcome["distinguished_shift"]
    return result


def write_result(path, result):
    """Atomic write so a kill at the budget still leaves whatever was found on disk."""
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, allow_nan=False)
    os.replace(temporary, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pollard rho baseline for the ECDLP ladder")
    parser.add_argument("--target", required=True)
    parser.add_argument("--time", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    result = solve_target(args.target, budget=args.time, seed=args.seed)
    write_result(args.out, result)
    return 0 if result["k"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
