import sys, time
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/nightly')
sys.path.insert(0, 'problems/matrix_multiplication')
from satenc2 import solve_sat
from verify import check
t0 = time.time()
print("CYCLE n=3 R=26 K=2 direct SAT, budget 600s", flush=True)
fac = solve_sat(3, 26, 2, timeout=600, seed=7)
dt = time.time() - t0
if fac:
    feas = check(fac, 3)["feasible"]
    print(f"CYCLE-RESULT n=3 direct: feasible={feas} in {dt:.1f}s", flush=True)
else:
    print(f"CYCLE-RESULT n=3 direct: TIMEOUT/UNSAT in {dt:.1f}s", flush=True)
