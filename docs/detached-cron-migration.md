# Migrating `nightly-matmul-discovery-loop` to detached runs

## Why
The cron job currently launches the smart loop as a child of the cron worker
process. Twice overnight, long search batches died when the spawning
agent/worker exited. `scripts/detached.py` launches the search in its own
session (setsid) with stdio redirected to a per-run log, so the search
survives any parent death.

## What the parent must change (via cron tools — do NOT edit by hand)

1. Fetch the current job body first:
   `cron.list` → find `nightly-matmul-discovery-loop` → `cron.show` it.
   Keep the existing schedule (02:43 America/New_York) and all existing
   instructions/goals text unchanged.

2. In the job's command/instructions, replace the direct smart-loop
   invocation with the detached launcher. The exact new command line is:

   ```
   cd ~/workspace/discovery-loop && .venv/bin/python problems/matrix_multiplication/smart_loop.py \
     --detached \
     --run-name "nightly-n3-$(date -u +%Y%m%d)" \
     --target 3 --time 1200 --seed 0 \
     --out nightly-results/n3-$(date -u +%Y%m%d).json
   ```

   Notes for the edit:
   - `--detached` re-launches the identical search under
     `scripts/detached.py launch` and exits immediately (exit 0 on success).
   - The detached run writes to `runs/nightly-n3-YYYYMMDD/`:
     `child.log` (full smart-loop output), `heartbeat` (touched every 15s
     while the search runs), `run.json` (pid, exit code, timestamps).
   - The cron job body should tell the worker to verify the run with:
     `python3 scripts/detached.py status --name nightly-n3-YYYYMMDD`
     and to check heartbeat age (< 60s means alive) rather than assuming
     the search is still attached to its own process.

3. Add a follow-up instruction to the job body: if a previous night's run
   record still shows `running` with a stale heartbeat (> 5 min), the worker
   should `kill --name <old>` it before launching (kills by recorded PID
   only), then launch the new run. Never launch a second run with the same
   name while one is alive.

4. Keep the existing result-collection steps (reading the `--out` JSON,
   proof sketch, pattern outcomes) — they work unchanged because the
   detached child writes the same `--out` files.

## Rollback
If detached runs misbehave, revert to the direct invocation (remove
`--detached --run-name ...`); everything else is identical.

## Verified
- `scripts/detached.py` survival test 2026-09-09: 90s task launched at
  09:03:00Z (wrapper PID 14365, PPID 1, own session), launcher exited, new
  shell observed finish at 09:04:30Z with exit_code 0 and correct log output.
- `smart_loop.py --detached` smoke test: n=2 run finished detached with
  rank 7, breaker SURVIVED, `--out` JSON written.
