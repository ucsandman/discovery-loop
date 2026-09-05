"""Standalone verifier for circle packings in the unit square. Stdlib only, zero tolerance.
Input JSON: {"n": N, "circles": [[x, y, r], ...]} with the square as [0,1]^2 (corner convention).
Feasible = every circle inside (wall slack >= 0), no pair overlapping (d^2 >= (ri+rj)^2), all r > 0.
"""

import json
import math
import sys


def check(circles, n=None):
    if n is not None and len(circles) != n:
        return {"feasible": False, "error": f"expected {n} circles, got {len(circles)}"}
    if any(len(c) != 3 for c in circles):
        return {"feasible": False, "error": "each circle must be [x, y, r]"}
    if any(not all(isinstance(v, (int, float)) and math.isfinite(v) for v in c) for c in circles):
        return {"feasible": False, "error": "every x, y, and radius must be finite numbers"}
    if any(not (c[2] > 0) for c in circles):
        return {"feasible": False, "error": "non-positive radius"}
    wall = min(min(x - r, 1 - x - r, y - r, 1 - y - r) for x, y, r in circles)
    pair2 = float("inf")
    for i in range(len(circles)):
        xi, yi, ri = circles[i]
        for j in range(i + 1, len(circles)):
            xj, yj, rj = circles[j]
            s = (xi - xj) ** 2 + (yi - yj) ** 2 - (ri + rj) ** 2
            if s < pair2:
                pair2 = s
    ok = wall >= 0 and pair2 >= 0
    return {
        "feasible": ok,
        "n": len(circles),
        "sum": sum(c[2] for c in circles),
        "min_wall_slack": wall,
        "min_pair_slack_sq": pair2,
    }


def to_pck(circles, author):
    """Packomania .pck: largest radius, author, then 'x y r' sorted by radius, square centred at origin."""
    cs = sorted(circles, key=lambda c: c[2])
    lines = [f"{cs[-1][2]:.16f}", author]
    lines += [f"{x - 0.5:.16f} {y - 0.5:.16f} {r:.16f}" for x, y, r in cs]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    res = check(d["circles"], d.get("n"))
    print(json.dumps(res))
    sys.exit(0 if res["feasible"] else 1)
