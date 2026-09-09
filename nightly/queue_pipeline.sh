#!/bin/bash
# Full rank-22 pipeline, 2026-09-09 morning.
# Phase 1: glue-triple LNS experiments (k=4, fast verdicts) from laderman-structure.md
# Phase 2: mixed-K R=22 direct search (90 min)
cd /home/hatch/workspace/discovery-loop/nightly
VENV=/home/hatch/workspace/discovery-loop/.venv/bin/python
echo "pipeline armed at $(date)" | tee queue_pipeline.log
while pgrep -f "^/home/hatch/workspace/discovery-loop/.venv/bin/python lns_laderman" > /dev/null; do sleep 120; done
echo "=== LNS drained at $(date); phase 1: glue experiments ===" | tee -a queue_pipeline.log
$VENV lns_laderman.py 7 4 5400 0 5,6,7,21 > lns_glue_A.log 2>&1
echo "glue A done at $(date): $(tail -1 lns_glue_A.log)" | tee -a queue_pipeline.log
$VENV lns_laderman.py 1 4 5400 0 0,1,2,3 > lns_glue_B.log 2>&1
echo "glue B done at $(date): $(tail -1 lns_glue_B.log)" | tee -a queue_pipeline.log
$VENV lns_laderman.py 16 4 5400 0 2,13,15,16 > lns_glue_C.log 2>&1
echo "glue C done at $(date): $(tail -1 lns_glue_C.log)" | tee -a queue_pipeline.log
echo "=== phase 2: mixed-K R=22 at $(date) ===" | tee -a queue_pipeline.log
$VENV mixedk_sat.py 22 "7,2,7,3,2,7,3,2,2,7,7,3,2,7,2,3,2,2,1,1,1,1" 5400 0 > mixedk_r22_2026-09-09.log 2>&1
echo "pipeline done at $(date)" | tee -a queue_pipeline.log
