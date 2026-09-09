#!/bin/bash
# Queue: wait for the random-subset LNS runs to finish, then launch the
# targeted W-coverage subsets (see laderman-2026-09-09.md + morning analysis).
# Run A: remove triple 19 (0-based 18); subset = covering {6,14} + dense {1,3,10,11}
#        -> 0-based filtered indices 0,2,5,9,10,13
# Run B: remove triple 21 (0-based 20); subset = covering {14,16,17,18} + dense {1,3}
#        -> 0-based filtered indices 0,2,13,15,16,17
cd /home/hatch/workspace/discovery-loop/nightly
VENV=/home/hatch/workspace/discovery-loop/.venv/bin/python
echo "Queue armed at $(date). Waiting for running LNS jobs to drain..." | tee queue.log
while pgrep -f "lns_laderman.py 18 6 5400 42" > /dev/null || pgrep -f "lns_laderman.py 20 6 5400 123" > /dev/null; do
  sleep 120
done
echo "Launching targeted runs at $(date)" | tee -a queue.log
$VENV lns_laderman.py 18 6 5400 0 0,2,5,9,10,13 > lns_rank22_targeted_A.log 2>&1 &
$VENV lns_laderman.py 20 6 5400 0 0,2,13,15,16,17 > lns_rank22_targeted_B.log 2>&1 &
wait
echo "Targeted runs done at $(date)" | tee -a queue.log
