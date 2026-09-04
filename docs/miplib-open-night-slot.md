# Proposed night.json change: swap miplib_heur for miplib_open

`night.json` is edited by hand and is **not** changed by this branch. This document proposes the change; a
human applies it after reviewing the miplib_open smoke run.

## What to change

Replace the `miplib_heur` slot with `miplib_open`, keeping the same 160 minutes and the same 22:00 start.
`pglib_opf` and `cvrp` are untouched. The night keeps its total length and three-slot shape.

Current (`night.json`):

```json
{
 "slots": [
  {"problem": "miplib_heur", "minutes": 160, "budget": 15},
  {"problem": "pglib_opf", "minutes": 160, "budget": 15},
  {"problem": "cvrp", "minutes": 160, "budget": 15}
 ]
}
```

Proposed:

```json
{
 "slots": [
  {"problem": "miplib_open", "minutes": 160, "budget": 15},
  {"problem": "pglib_opf", "minutes": 160, "budget": 15},
  {"problem": "cvrp", "minutes": 160, "budget": 15}
 ]
}
```

## Why swap rather than add a fourth slot

A fourth 160-minute slot would push the night past 08:00. The two modules answer overlapping questions
(both evolve a MIP primal heuristic on MIPLIB 2017), so running both every night is redundant. `miplib_open`
is the one whose wins are externally creditable (a verified feasible point below a published best-known,
submitted to `miplibsolutions@zib.de`), while `miplib_heur`'s bar is "HiGHS default on this PC", which means
nothing off this machine. Keeping `miplib_heur` on a branch and promoting `miplib_open` to the night is the
higher-value use of the slot. If both are wanted, run `miplib_heur` manually by day.

## Timing from a 22:00 start

With DEFAULTS `time=600, workers=3` and 10 targets, one iteration is `ceil(10/3) * 600 = 4 * 600 = 2400 s`
(40 min) of solver wall-clock plus model-call latency. The loop's start guard refuses to begin an iteration
that cannot finish `budget + 360 s` before the wall limit, so a 160-minute slot completes about **3**
iterations before the guard stops it (22:00 -> ~00:40). `pglib_opf` then runs 00:40 -> 03:20 and `cvrp`
03:20 -> 06:00, exactly as today. The loop also stops early on plateau or the \$15 model budget.

Publishing stays enabled for a real night slot. During the slot the loop pushes `best-miplib_open/` to GitHub
(`publish.py --push-only`). After the slot, `night.py` runs the full `publish.py`: every re-verified win of the
slot goes to `miplibsolutions@zib.de` in one email with one approval tap (Wes approves on Telegram, up to a
24 hour window, fail closed; a crashed slot still submits). Enabled 2026-09-04, batched the same day. Use
`--no-publish` only for isolated experiments like the smoke run.

## One-line apply (human, after review)

Edit `night.json` on the main checkout and replace the first slot's `"problem": "miplib_heur"` with
`"problem": "miplib_open"`. Nothing else changes.
