"""Independent verification of an ECDLP answer on a discovery-loop ladder curve.

A ladder instance is a short Weierstrass curve y^2 = x^3 + a*x + b over a prime field F_p with prime
group order n and cofactor 1 (problems/ecc_prize/curves.py generates them; records.json carries the
public data and the discrete logarithm is stored nowhere). A claim is one integer k and it is accepted
only when 1 <= k < n and k*P equals Q on the stated curve.

This module is the trusted checker. It recomputes k*P with its own left-to-right double-and-add over
affine coordinates and imports nothing from seed_solver.py or from a candidate solver, so generated
code can never verify itself. The arithmetic here is deliberately plain: correctness first, speed is
the solver's problem.

    python verify.py candidate.json      # {"target": name, "k": int}
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from .records import load_instance
else:  # direct ``python problems/ecc_prize/verify.py`` and the sandboxed worker
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from problems.ecc_prize.records import load_instance


def _inverse(value, p):
    """Modular inverse via Fermat; p is prime for every ladder instance."""
    return pow(value % p, p - 2, p)


def negate(point, p):
    return None if point is None else (point[0], (-point[1]) % p)


def point_add(first, second, p, a):
    """Affine group law on y^2 = x^3 + a*x + b over F_p, with ``None`` as the point at infinity."""
    if first is None:
        return second
    if second is None:
        return first
    x1, y1 = first
    x2, y2 = second
    if x1 == x2:
        if (y1 + y2) % p == 0:
            return None
        lam = (3 * x1 * x1 + a) * _inverse(2 * y1, p) % p
    else:
        lam = (y2 - y1) * _inverse(x2 - x1, p) % p
    x3 = (lam * lam - x1 - x2) % p
    return (x3, (lam * (x1 - x3) - y1) % p)


def scalar_mult(k, point, p, a):
    """k*point by left-to-right double-and-add; negative k multiplies the negated point."""
    if k < 0:
        k, point = -k, negate(point, p)
    result = None
    if k:
        for bit in bin(k)[2:]:
            result = point_add(result, result, p, a)
            if bit == "1":
                result = point_add(result, point, p, a)
    return result


def is_on_curve(point, p, a, b):
    if point is None:
        return True
    x, y = point
    return (y * y - x * x * x - a * x - b) % p == 0


def _int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer, got {type(value).__name__}")
    return value


def _point(value, label, p):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must be a two-element [x, y]")
    x, y = _int(value[0], f"{label}.x"), _int(value[1], f"{label}.y")
    if not (0 <= x < p and 0 <= y < p):
        raise ValueError(f"{label} is outside F_p")
    return (x, y)


def instance_fields(instance):
    """Validate the public instance data and return (p, a, b, n, P, Q); raises ValueError otherwise."""
    if not isinstance(instance, dict):
        raise ValueError("instance must be an object")
    p = _int(instance.get("p"), "p")
    if p < 5 or p % 2 == 0:
        raise ValueError("p must be an odd prime field characteristic")
    a = _int(instance.get("a"), "a") % p
    b = _int(instance.get("b"), "b") % p
    n = _int(instance.get("n"), "n")
    if n < 2:
        raise ValueError("n must be the (prime) group order")
    if (4 * a * a * a + 27 * b * b) % p == 0:
        raise ValueError("singular curve: 4a^3 + 27b^2 == 0")
    generator = _point(instance.get("P"), "P", p)
    target = _point(instance.get("Q"), "Q", p)
    if not is_on_curve(generator, p, a, b):
        raise ValueError("P is not on the curve")
    if not is_on_curve(target, p, a, b):
        raise ValueError("Q is not on the curve")
    return p, a, b, n, generator, target


def check_instance(k, instance):
    """Check one claim against already-loaded public instance data."""
    result = {"feasible": False, "reason": None, "verified_ops": None}
    try:
        p, a, _b, n, generator, target = instance_fields(instance)
    except (ValueError, TypeError) as exc:
        result["reason"] = f"invalid instance: {exc}"
        return result
    if isinstance(k, bool) or not isinstance(k, int):
        result["reason"] = f"k must be an integer, got {type(k).__name__}"
        return result
    if not 1 <= k < n:
        result["reason"] = f"k must lie in [1, n) with n = {n}"
        return result
    if scalar_mult(k, generator, p, a) != target:
        result["reason"] = "k*P does not equal Q on the stated curve"
        return result
    result["feasible"] = True
    return result


def check(k, target):
    """Check one claim against the named ladder instance in records.json."""
    return check_instance(k, load_instance(target))


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as stream:
        claim = json.load(stream)
    outcome = check(claim.get("k"), claim["target"])
    print(json.dumps(outcome))
    sys.exit(0 if outcome["feasible"] else 1)
