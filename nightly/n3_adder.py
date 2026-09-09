import sys, time
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
from satenc2_adder import solve_sat_adder
from verify import check

t0 = time.time()
print("n=3 R=26 K=2 ADDER encoding, budget 600s", flush=True)
fac = solve_sat_adder(3, 26, 2, timeout=600)
dt = time.time() - t0
if fac:
    print(f"n=3 ADDER: feasible={check(fac, 3)['feasible']} in {dt:.1f}s", flush=True)
else:
    print(f"n=3 ADDER: no solution in {dt:.1f}s", flush=True)
