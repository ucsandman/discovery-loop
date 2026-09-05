"""Records for the primal-heuristic problem.

The "record" per instance is NOT a published number: it is the relative primal gap that plain HiGHS (default
options, 2 threads, 1e-7 tolerances) reaches on THIS machine in the same 60 s / 3-parallel setting the loop uses.
`baseline.json` holds it, produced by baseline.py. Proven optima come from the official MIPLIB .solu file and
instances are shared with problems/miplib (download on first use).
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MIPLIB = os.path.join(os.path.dirname(HERE), "miplib")
BASELINE = os.path.join(HERE, "baseline.json")
TABLE = os.path.join(HERE, "benchmark_table.json")


if not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from problems.miplib import records as _R

instance_path = _R.instance_path  # solvers: from records import instance_path


def optima():
    """{instance: proven optimum} for every =opt= line of the newest local .solu file (instance's own sense)."""
    out = {}
    for line in open(_R.solu_path()):
        p = line.split()
        if len(p) >= 3 and p[0] == "=opt=":
            out[p[1]] = float(p[2])
    return out


def opt(name):
    v = optima().get(name)
    if v is None:
        raise KeyError(f"{name} has no proven optimum in the .solu file")
    return v


def load():
    """{instance: HiGHS-default relative gap at 60 s, or None when HiGHS found no feasible point}."""
    if not os.path.exists(BASELINE):
        return {}
    return {k: v["gap"] for k, v in json.load(open(BASELINE)).items()}


def fetch():
    """No live table exists for a same-machine baseline; re-measure with baseline.py instead."""
    return load()


def benchmark_table(html_path=None):
    """Parse MIPLIB's tag_benchmark.html into {instance: {status, vars, bin, int, cont, rows, nonz, group, tags}}."""
    if os.path.exists(TABLE) and html_path is None:
        return json.load(open(TABLE))
    text = open(html_path, encoding="utf-8").read()
    rows = {}
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
        if len(cells) < 12 or not cells[2].isdigit():
            continue
        tags = sorted(set(re.findall(r"tag_([a-z_0-9]+)\.html", block)) - {"benchmark", "easy", "hard", "open"})
        rows[cells[0]] = {
            "status": cells[1],
            "vars": int(cells[2]),
            "bin": int(cells[3]),
            "int": int(cells[4]),
            "cont": int(cells[5]),
            "rows": int(cells[6]),
            "nonz": int(cells[7]),
            "group": cells[9],
            "tags": tags,
        }
    json.dump(rows, open(TABLE, "w"), indent=1)
    return rows


if __name__ == "__main__":
    import sys

    t = benchmark_table(sys.argv[1] if len(sys.argv) > 1 else None)
    o = optima()
    print(f"{len(t)} benchmark rows, {sum(k in o for k in t)} with proven optimum, baseline for {len(load())}")
