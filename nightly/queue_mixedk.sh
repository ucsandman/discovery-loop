#!/bin/bash
# Queue: when the LNS rank-22 runs drain, launch the first mixed-K R=22 shot.
cd /home/hatch/workspace/discovery-loop/nightly
VENV=/home/hatch/workspace/discovery-loop/.venv/bin/python
echo "mixedk queue armed at $(date)" | tee queue_mixedk.log
while pgrep -f "lns_laderman[.]py" > /dev/null; do sleep 120; done
echo "LNS drained at $(date), launching mixed-K R=22 (Laderman-minus-19 budgets, 90min)" | tee -a queue_mixedk.log
$VENV mixedk_sat.py 22 "7,2,7,3,2,7,3,2,2,7,7,3,2,2,1,1,1,1" 5400 0 > mixedk_r22_2026-09-09.log 2>&1
echo "mixed-K done at $(date)" | tee -a queue_mixedk.log
