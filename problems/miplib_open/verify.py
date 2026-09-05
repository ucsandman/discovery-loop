"""Independent check of a solution for a MIPLIB 2017 OPEN instance.

Feasibility and the exact objective come from the shared engine problems/miplib/verify.check (bounds,
integrality, every row within 1e-6, objective in the instance's own sense) -- the same engine miplib_heur
verifies with. The only thing this module adds is the VALUE against the published best-known:

    value = (obj - best_known)/max(1,|best_known|)   for a minimisation instance
            (best_known - obj)/max(1,|best_known|)   for a maximisation instance

so value is in min-sense (lower is better): 0 ties the best-known and NEGATIVE beats it. Unlike
miplib_heur (whose gap is to a proven optimum and is clamped >= 0), here a feasible point may legitimately
beat the reference, so value is not clamped.

DEVIATION from the brief's literal "reuse miplib_heur's verify.check": that wrapper looks up an ``=opt=``
optimum and would KeyError on an open instance (which has none). The reuse is therefore of the shared
engine miplib_heur itself wraps, which is the same code path with no fork.

    python verify.py candidate.json      # {"target": name, "solution": {var: value}}
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from . import records
    from problems.miplib import verify as _V
else:  # direct ``python problems/miplib_open/verify.py`` compatibility
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    sys.path.insert(0, HERE)
    import records  # noqa: E402

    from problems.miplib import verify as _V

MIPLIB = records.MIPLIB
to_sol = _V.to_sol


def value(obj, best, sense):
    """Relative gap to best-known in min-sense (0 ties, negative beats). No clamp."""
    d = (obj - best) if sense == "min" else (best - obj)
    return d / max(1.0, abs(best))


def check(solution, name, tol=_V.TOL):
    """{feasible, obj, sense, value, best_known, bound_viol, int_viol, row_viol, ...}."""
    res = _V.check(solution, name, tol=tol)
    res["best_known"] = records.best_known(name)
    res["value"] = value(res["obj"], res["best_known"], res["sense"]) if res["feasible"] else None
    return res


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    res = check(d["solution"], d["target"])
    print(json.dumps(res))
    sys.exit(0 if res["feasible"] else 1)
