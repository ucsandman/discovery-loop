#!/bin/bash
# Retry of the 2026-09-09 morning mixed-K R=22 run whose verdict was lost
# when the repo consolidation moved files mid-run. All paths absolute;
# nothing here depends on cwd or on files that might move.
set -u
NIGHTLY=/home/hatch/workspace/discovery-loop/nightly
VENV=/home/hatch/workspace/discovery-loop/.venv/bin/python
STAMP=$(date +%Y-%m-%d)
LOG=/home/hatch/workspace/discovery-loop/nightly/mixedk_r22_retry_${STAMP}.log
K="7,2,7,3,2,7,3,2,2,7,7,3,2,7,2,3,2,2,1,1,1,1"
{
  echo "=== mixed-K R=22 retry started $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  echo "config: R=22 K=[$K] timeout=5400 seed=0"
  "$VENV" "$NIGHTLY/mixedk_sat.py" 22 "$K" 5400 0
  echo "=== mixed-K R=22 retry finished $(date -u +%Y-%m-%dT%H:%M:%SZ) exit=$? ==="
} >> "$LOG" 2>&1
