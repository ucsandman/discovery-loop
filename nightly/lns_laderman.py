#!/usr/bin/env python3
"""LNS from Laderman-23 minus 1 triple: try to find rank 22.

Strategy: remove 1 triple from Laderman's feasible rank-23, then use SAT
to re-optimize a subset of the remaining 22 triples. If SAT, we have rank 22.
"""
import sys, time, random
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
from laderman import laderman
from lns_sat import lns_sat
from verify import check


def try_rank22(remove_idx, var_idx, max_nz=7, timeout=300, seed=0):
    """Remove triple remove_idx, re-optimize var_idx subset. Returns (feasible, new_triples)."""
    fac = laderman()
    # Remove one triple
    triples = [t for i, t in enumerate(fac) if i != remove_idx]
    print(f"Removed triple {remove_idx+1}, {len(triples)} triples remain", flush=True)
    print(f"Re-optimizing indices {sorted(var_idx)} with K={max_nz}", flush=True)

    t0 = time.time()
    res = lns_sat(3, triples, var_idx=var_idx, max_nz=max_nz, timeout=timeout, seed=seed)
    dt = time.time() - t0
    if res:
        feas = check(res, 3)["feasible"]
        print(f"Result: feasible={feas} in {dt:.1f}s", flush=True)
        return feas, res
    else:
        print(f"Result: no solution (UNSAT or timeout) in {dt:.1f}s", flush=True)
        return False, None


if __name__ == '__main__':
    # Try removing a sparse triple (P19: K=1, contributes only to c11)
    # and re-optimizing a subset that includes dense triples
    remove_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 18  # 0-based: triple 19
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    fac = laderman()
    triples = [t for i, t in enumerate(fac) if i != remove_idx]
    if len(sys.argv) > 5 and sys.argv[5] != '-':
        # Explicit subset: comma-separated indices into the filtered triple list
        var_idx = set(int(x) for x in sys.argv[5].split(','))
        print(f"Using explicit subset {sorted(var_idx)}", flush=True)
    else:
        # Pick k triples to re-optimize: random subset
        random.seed(seed)
        var_idx = set(random.sample(range(len(triples)), k))

    feas, res = try_rank22(remove_idx, var_idx, max_nz=7, timeout=timeout, seed=seed)
    if feas:
        print("BREAKTHROUGH: found feasible rank-22!", flush=True)
        # Save it
        import json
        with open('/home/hatch/workspace/discovery-loop/nightly/rank22.json', 'w') as f:
            json.dump(res, f)
        print("Saved to rank22.json", flush=True)
