"""Second, independent circle-packing verifier for the Claim Notary. Exact arithmetic, stdlib only.

It reads the decimal strings exactly as printed, in the centred square [-1/2, 1/2]^2, scales every value to one
integer grid and checks containment and separation with integer arithmetic, so nothing is rounded before it is
checked. It deliberately does not import problems/circle_packing/verify.py: the notary trusts a verdict only when
two implementations that share no code agree.
"""

from decimal import Decimal, InvalidOperation
from fractions import Fraction


def decimals_of(text):
    """Digits after the decimal point as printed, or None when the text is not a finite decimal number."""
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError):
        return None
    if not value.is_finite():
        return None
    return max(0, -value.as_tuple().exponent)


def check_exact(rows, n=None, tolerance=Fraction(0)):
    """Check rows of (x, y, r) decimal strings, centre-origin coordinates.

    Returns feasible at the given tolerance, the exact sum, and the exact minimum wall slack and minimum squared
    pair slack (d^2 - (ri + rj)^2) as Fractions. The tolerance applies to both slacks.
    """
    if n is not None and len(rows) != n:
        return {"feasible": False, "error": f"expected {n} circles, got {len(rows)}"}
    if not rows:
        return {"feasible": False, "error": "no circles"}
    if any(len(row) != 3 for row in rows):
        return {"feasible": False, "error": "each circle must be x y r"}
    places = [decimals_of(value) for row in rows for value in row]
    if any(p is None for p in places):
        return {"feasible": False, "error": "every x, y, and radius must be a finite decimal number"}
    scale = 2 * 10 ** max(places)  # even, so the half-width of the square is an integer on this grid
    grid = [tuple(int(Fraction(Decimal(v.strip())) * scale) for v in row) for row in rows]
    if any(r <= 0 for _, _, r in grid):
        return {"feasible": False, "error": "non-positive radius"}
    half = scale // 2
    wall = min(min(half - abs(x) - r, half - abs(y) - r) for x, y, r in grid)
    pair = None
    for i, (xi, yi, ri) in enumerate(grid):
        for xj, yj, rj in grid[i + 1 :]:
            slack = (xi - xj) ** 2 + (yi - yj) ** 2 - (ri + rj) ** 2
            if pair is None or slack < pair:
                pair = slack
    wall_slack = Fraction(wall, scale)
    pair_slack = Fraction(pair, scale * scale) if pair is not None else None
    feasible = wall_slack >= -tolerance and (pair_slack is None or pair_slack >= -tolerance)
    return {
        "feasible": feasible,
        "n": len(grid),
        "sum": Fraction(sum(r for _, _, r in grid), scale),
        "min_wall_slack": wall_slack,
        "min_pair_slack_sq": pair_slack,
    }
