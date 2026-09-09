import sys, time
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, 'problems/matrix_multiplication')
from satenc2 import solve_sat
from verify import check

# n=3, R=26, K=2, 10 min budget
t0 = time.time()
print("FRESH CYCLE n=3 R=26 K=2, budget 600s", flush=True)
fac = solve_sat(3, 26, 2, timeout=600, seed=7)
dt = time.time() - t0
if fac:
    print(f"FOUND n=3: feasible={check(fac, 3)['feasible']} in {dt:.1f}s", flush=True)
else:
    print(f"n=3: no solution in {dt:.1f}s", flush=True)
