import sys, time
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
from satenc2_sym import solve_sat_sym
from verify import check
t0 = time.time()
print("n=3 R=26 K=3 WITH symmetry breaking, budget 300s", flush=True)
fac = solve_sat_sym(3, 26, 3, timeout=300)
dt = time.time() - t0
if fac:
    print(f"FOUND: feasible={check(fac, 3)['feasible']} in {dt:.1f}s", flush=True)
else:
    print(f"no solution in {dt:.1f}s", flush=True)
