"""Independent feasibility check of a CVRP solution against a CVRPLIB X instance.

Parses the TSPLIB .vrp (NODE_COORD_SECTION, DEMAND_SECTION, DEPOT_SECTION, CAPACITY, EUC_2D) itself and
does all the arithmetic in numpy. Distances are rounded to the nearest integer per the CVRPLIB / TSPLIB
EUC_2D convention (nint(x) = floor(x + 0.5)); the route cost is the sum of the rounded edge costs.

A solution is {"routes": [[c, c, ...], ...]}: each route is a list of customer numbers, the depot is
implicit at the start and end of every route. Customers are numbered 1..(DIMENSION-1) exactly as in the
official .sol file (customer c is the (c+1)-th node in NODE_COORD_SECTION; the depot is node 1). Feasible
requires: every customer served exactly once, no customer out of range or repeated, and every route's total
demand within the vehicle capacity. The number of routes is unlimited (the .vrp names no vehicle limit).

    python verify.py candidate.json      # {"target": name, "solution": {"routes": [[...], ...]}}
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

if __package__:
    from .records import instance_path
else:  # direct ``python problems/cvrp/verify.py`` compatibility
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from problems.cvrp.records import instance_path


def _section(lines, header):
    """Indices of the data lines belonging to a TSPLIB section (header line -> next UPPERCASE header / EOF)."""
    try:
        start = next(i for i, l in enumerate(lines) if l.upper().startswith(header))
    except StopIteration:
        raise ValueError(f"missing {header}")
    out = []
    for l in lines[start + 1 :]:
        s = l.strip()
        if not s:
            continue
        head = s.split(":")[0].strip().upper()
        if head in ("NODE_COORD_SECTION", "DEMAND_SECTION", "DEPOT_SECTION", "EDGE_WEIGHT_SECTION", "EOF"):
            break
        out.append(s)
    return out


def load_instance_path(path, name=None):
    """Parse one explicitly selected trusted instance path.

    This seam is used by the sealed evaluator so verification never relies on
    the global CVRPLIB cache or imports code from a candidate directory.
    """
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("instance path must be a regular file, not a symlink")
    lines = path.read_text(encoding="utf-8").splitlines()
    instance_name = str(name) if name is not None else path.stem
    return _parse_instance(lines, instance_name)


def _parse_instance(lines, name):
    """Parse the .vrp into arrays indexed 0..DIMENSION-1 (index 0 = depot, index c = customer c).

    Returns {"coords": (N,2) float, "demand": (N,) float, "capacity": float, "n": customers, "name": name}.
    """
    hdr = {}
    for l in lines:
        m = l.split(":", 1)
        if len(m) == 2 and m[0].strip().upper() in ("DIMENSION", "CAPACITY", "EDGE_WEIGHT_TYPE"):
            hdr[m[0].strip().upper()] = m[1].strip()
    if hdr.get("EDGE_WEIGHT_TYPE", "EUC_2D") != "EUC_2D":
        raise ValueError(f"{name}: EDGE_WEIGHT_TYPE {hdr.get('EDGE_WEIGHT_TYPE')} not supported (EUC_2D only)")
    dim = int(hdr["DIMENSION"])
    capacity = float(hdr["CAPACITY"])

    coords = np.zeros((dim, 2))
    for row in _section(lines, "NODE_COORD_SECTION"):
        p = row.split()
        coords[int(p[0]) - 1] = (float(p[1]), float(p[2]))  # node ids are 1-based in the file
    demand = np.zeros(dim)
    for row in _section(lines, "DEMAND_SECTION"):
        p = row.split()
        demand[int(p[0]) - 1] = float(p[1])
    depots = [int(x.split()[0]) for x in _section(lines, "DEPOT_SECTION") if x.split()[0] != "-1"]
    if depots != [1]:
        raise ValueError(f"{name}: expected a single depot at node 1, got {depots}")
    return {"coords": coords, "demand": demand, "capacity": capacity, "n": dim - 1, "name": name}


def load_instance(name):
    """Load a named instance through the existing CVRPLIB cache."""
    return load_instance_path(instance_path(name), name)


def dist_matrix(coords):
    """Rounded EUC_2D distance matrix (int), nint(x) = floor(x + 0.5)."""
    d = coords[:, None, :] - coords[None, :, :]
    return np.floor(np.sqrt((d * d).sum(-1)) + 0.5).astype(np.int64)


def route_cost(route, D):
    """Cost of one route depot(0) -> customers -> depot(0), using the rounded distance matrix."""
    if not route:
        return 0
    path = [0, *route, 0]
    return int(sum(D[path[i], path[i + 1]] for i in range(len(path) - 1)))


def check_instance(solution, inst):
    """Check a solution against an already parsed trusted instance."""
    n, cap = inst["n"], inst["capacity"]
    routes = solution.get("routes")
    if not isinstance(routes, list) or not all(isinstance(r, list) for r in routes):
        return {"feasible": False, "reason": "solution.routes must be a list of lists of customer numbers"}
    if len(routes) > n:
        return {
            "feasible": False,
            "obj": None,
            "n_routes": None,
            "capacity": cap,
            "duplicate_customers": [],
            "missing_customers": [],
            "over_capacity": None,
            "reason": f"solution contains more than the {n} available routes",
        }

    seen, bad_route = Counter(), None
    total_entries = 0
    for r in routes:
        for c in r:
            if not isinstance(c, int) or isinstance(c, bool) or c < 1 or c > n:
                return {"feasible": False, "reason": f"customer {c!r} out of range 1..{n}"}
            seen[c] += 1
            total_entries += 1
            if total_entries > n:
                dup = sorted(customer for customer, count in seen.items() if count > 1)
                missing = sorted(set(range(1, n + 1)) - set(seen))
                return {
                    "feasible": False,
                    "obj": None,
                    "n_routes": sum(1 for route in routes if route),
                    "capacity": cap,
                    "duplicate_customers": dup[:8],
                    "missing_customers": missing[:8],
                    "over_capacity": bad_route,
                    "reason": f"solution contains more than the {n} available customers",
                }
        load = float(inst["demand"][r].sum()) if r else 0.0
        if load > cap:
            bad_route = {"load": load, "capacity": cap, "customers": len(r)}

    dup = sorted(c for c, count in seen.items() if count > 1)
    missing = sorted(set(range(1, n + 1)) - set(seen))
    D = dist_matrix(inst["coords"])
    obj = sum(route_cost(r, D) for r in routes)
    feasible = not dup and not missing and bad_route is None
    return {
        "feasible": bool(feasible),
        "obj": int(obj),
        "n_routes": sum(1 for r in routes if r),
        "capacity": cap,
        "duplicate_customers": dup[:8],
        "missing_customers": missing[:8],
        "over_capacity": bad_route,
        "reason": (
            ""
            if feasible
            else (f"{len(dup)} duplicate customer(s) {dup[:4]}" if dup else "")
            + (f" {len(missing)} missing customer(s) {missing[:4]}" if missing else "")
            + (f" route over capacity {bad_route}" if bad_route else "")
        ).strip(),
    }


def check_instance_path(solution, path, name=None):
    """Check a solution against one explicit trusted instance file."""
    return check_instance(solution, load_instance_path(path, name))


def check(solution, name):
    return check_instance(solution, load_instance(name))


def to_sol(solution, obj):
    """Official CVRPLIB .sol format: one 'Route #i: c c c' line per non-empty route, then 'Cost N'."""
    lines = [f"Route #{i + 1}: " + " ".join(str(c) for c in r) for i, r in enumerate(solution["routes"]) if r]
    lines.append(f"Cost {int(obj)}")
    return "\n".join(lines) + "\n"


def parse_sol(text):
    """Read an official / candidate .sol into {"routes": [[...], ...]}."""
    routes = []
    for line in text.splitlines():
        if line.strip().lower().startswith("route"):
            routes.append([int(x) for x in line.split(":", 1)[1].split()])
    return {"routes": routes}


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    res = check(d["solution"], d["target"])
    print(json.dumps(res))
    sys.exit(0 if res["feasible"] else 1)
