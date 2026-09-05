# discovery-loop

An LLM evolves a solver program; a zero-tolerance checker scores it; winners survive. AlphaEvolve shape, one file.

Problems are plug-ins under `problems/<name>/problem.py` (targets, live records, independent verifier, submission format, prompt):

- **circle_packing**: Packomania csqv, pack N variable-radius circles in the unit square maximising the sum of radii.
  Records fetched live from packomania.com; zero-tolerance stdlib checker; `.pck` submissions emailed to the maintainer.
- **miplib**: MIPLIB 2017 *open* instances (real-world mixed-integer programs with no proven optimum). Best-known values from the
  official `.solu` file; independent checker re-evaluates bounds, integrality and every row at 1e-6; `.sol` files emailed to
  miplibsolutions@zib.de. Seed solver = HiGHS + adaptive LNS (`pip install highspy`).

```powershell
python loop.py --problem miplib --eval-only               # score the champion solver, no model calls
python loop.py --problem miplib --iters 20 --budget 30    # evolve (claude -p, Fable 5.1) until 20 iterations or $30
start runs-miplib\status.html                             # human view: standings, iterations, ideas tried
start runs\status.html                                    # same for circle_packing (legacy flat layout)
```

Outputs per problem: `best*/solver.py` (champion), `best*/<sub>/` (candidates in the benchmark's submission format),
`runs*/log.jsonl`, `runs*/status.html`. Verify any candidate with the problem's own `verify.py`.

## Publishing (nothing sits on this machine)

`publish.py` runs in two layers:

1. `loop.py` fires `publish.py --push-only` after any iteration that improves a record-beating target and at the
   end of a run: commit and push `best*/` to GitHub (public, timestamped ledger of every candidate). Never emails.
2. `night.py` runs the full `publish.py` once after each slot (crashed slots included): every winner of the slot
   goes to the maintainer in ONE email with ONE approval tap, through the governed `invoke-capability send-email`
   seam. DashClaw opens a pending approval, Wes approves on Telegram (24h window, fail closed),
   `moltfire@practicalsystems.io` sends with Wes cc'd. Every candidate is re-verified against the live table first;
   `best*/submitted.json` records what went out; one email per 12h per problem.

```powershell
python publish.py --dry-run   # show what would go out
python publish.py             # push + request approval for anything new
```

## Retro (so tomorrow does not redo tonight)

`retro.py` runs once after every night slot (before the publish) and appends a dated section to `docs/retro/<problem>.md`:
what worked (with the mechanism), what didn't (with the likely reason, duplicates grouped), three to six checkable
lessons, and five **Next** directions that must differ in kind (algorithm family, time allocation, representation,
instance structure, robustness), at least two far from anything tried, each with why it could beat the best-known and
how we would know it failed. The brainstorming rules from the superpowers brainstorming skill are in the prompt.
`loop.py` reads the newest section's Lessons and Next into every iteration prompt, shows a compressed list of every
idea from earlier nights (not only the last 12), and asks the model to start its IDEA line with `[NEXT #k]` for the
direction it takes, so the next retro sees what was consumed. One model call, about $0.50 to $1.30 per slot.

```powershell
python retro.py --problem cvrp --dry-run       # the prompt, no model call
python retro.py --problem cvrp --since-iter 5  # review iterations 5 and later, append to docs/retro/cvrp.md
```

## pglib_opf: AC optimal power flow on the PGLib-OPF benchmark

IEEE PES PGLib-OPF v23.07 "typical operating conditions" cases, 3 to 793 buses. The value to beat per case is the
AC-OPF objective PowerModels.jl + IPOPT reached (BASELINE.md, 5 significant figures, so a win must clear 1e-4
relative). `problems/pglib_opf/verify.py` re-checks every constraint of the AC-OPF model with numpy at 1e-6 pu
(voltage and P/Q bounds, nodal balance, apparent-power limits at both ends, angle limits, reference angle).
Seed solver = PYPOWER PIPS interior point + Newton polish + random multi-start (`pip install PYPOWER`).
Case files download on first use from the pinned tag. Nothing is emailed; wins go to the pglib-opf issue tracker by hand.

```powershell
python loop.py --problem pglib_opf --eval-only              # seed solver on all 21 cases, no model calls
python loop.py --problem pglib_opf --wall-minutes 235 --budget 15
python problems/pglib_opf/verify.py best-pglib_opf/sol/pglib_opf_case14_ieee.json
```

## miplib_heur: a general primal heuristic vs HiGHS default

Instead of chasing open instances, this problem evolves a GENERAL primal heuristic (Python on highspy) and scores it by
relative primal gap at 60 s on MIPLIB 2017 benchmark instances with PROVEN optima, so the checker is exact. The value to
beat per instance is what plain HiGHS (default options, 2 threads) reaches on this machine in the same slot
(`problems/miplib_heur/baseline.py --measure --assign` builds `baseline.json`: 20 train + 10 holdout instances).
`holdout.py` scores a champion on instances the model never saw; name- or signature-keyed tricks are disqualified.
Nothing is emailed; the champion solver.py is the deliverable and upstreaming to HiGHS is a human decision.

```powershell
python loop.py --problem miplib_heur --eval-only               # seed heuristic on the train set, no model calls
python loop.py --problem miplib_heur --wall-minutes 235 --budget 15
python problems/miplib_heur/holdout.py best-miplib_heur/solver.py
```

## cvrp: capacitated vehicle routing on the CVRPLIB X benchmark

Vehicle routing is fuel, miles and delivery cost for every fleet. Targets are ten CVRPLIB X instances
(Uchoa et al., 2017; 200–500 nodes) whose best known solution is **not proven optimal**, so a lower feasible
cost is a genuine result. `problems/cvrp/records.py` fetches the best-known cost and optimality flag live from
the CVRPLIB table and caches them; `verify.py` parses the TSPLIB `.vrp` and re-checks every customer served
once, every route within capacity, and the rounded-EUC_2D cost — it reproduces all ten official best-known
`.sol` costs exactly. Seed solver = Clarke-Wright savings + 2-opt / relocate / swap local search (pure python +
numpy, no external solver). Instances download on first use. Nothing is emailed; the GitHub push of `best-cvrp/`
is the publication and a verified improvement goes to CVRPLIB by hand. See `problems/cvrp/BASELINE.md` for seed
gaps and the proposed night slot.

```powershell
python loop.py --problem cvrp --eval-only                      # seed solver on all 10 targets, no model calls
python loop.py --problem cvrp --iters 1 --time 60 --workers 2 --no-publish   # smoke run, publishing disabled
python loop.py --problem cvrp --wall-minutes 180 --budget 15
python problems/cvrp/verify.py best-cvrp/sol/X-n280-k17.json
python problems/cvrp/test_cvrp.py                             # verifier + --no-publish tests
```

`--no-publish` (on any problem) suppresses every `publish.py` call — no git commit/push, no maintainer email —
for isolated experiments; the default behaviour is unchanged.
