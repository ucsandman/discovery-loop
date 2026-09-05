# CVRP seed baseline (CVRPLIB X, open instances)

> Historical baseline provenance. Tables retain their original measurements and tolerances; they are not current confirmation certificates. Fresh comparisons use the current verifier and pinned worker environment. See [operations](../../docs/OPERATIONS.md).

The value to beat per target is the **best known solution (BKS)** from the live CVRPLIB table
(`records.py` fetches it from <https://galgos.inf.puc-rio.br/cvrplib/en/instances> and caches it in
`records.json`). All ten targets are X instances with 200–500 nodes whose BKS is **not proven optimal**
("Optimal" column = no), so a lower feasible cost is a genuine result.

Unlike `pglib_opf`, whose `records.py` parses its `BASELINE.md`, here the record values come from the live
table; this file only documents the seed solver's gaps and the night slot.

## Targets and seed gaps

Seed = `seed_solver.py` (Clarke-Wright savings + 2-opt / relocate / swap local search, pure python + numpy),
measured through the real loop: `python -u loop.py --problem cvrp --iters 1 --time 60 --workers 2 --no-publish`
(60 s per target, 2 in parallel, on this machine). `n` is the node count in the instance name (customers = n − 1).

| Instance | customers | routes (BKS) | capacity | BKS | proven optimal | seed cost (60 s) | gap to BKS |
| --- | ---: | ---: | ---: | ---: | :---: | ---: | ---: |
| X-n280-k17 | 279 | 17 | 192 | 33503 | no | 35970 | 7.36% |
| X-n303-k21 | 302 | 21 | 794 | 21736 | no | 23546 | 8.33% |
| X-n327-k20 | 326 | 20 | 128 | 27532 | no | 29502 | 7.16% |
| X-n336-k84 | 335 | 84 | 203 | 139111 | no | 145331 | 4.47% |
| X-n401-k29 | 400 | 29 | 745 | 66154 | no | 68480 | 3.52% |
| X-n411-k19 | 410 | 19 | 216 | 19712 | no | 21405 | 8.59% |
| X-n429-k61 | 428 | 61 | 536 | 65449 | no | 68375 | 4.47% |
| X-n459-k26 | 458 | 26 | 1106 | 24139 | no | 26161 | 8.38% |
| X-n480-k70 | 479 | 70 | 52 | 89449 | no | 92643 | 3.57% |
| X-n491-k59 | 490 | 59 | 428 | 66483 | no | 69149 | 4.01% |

Mean seed gap **5.98%**; champion total at the seed = **−0.5985** (negative relative gap summed over targets,
each clipped at −0.5). The loop's job is to close these gaps; a champion total above −0.5985 is progress, a
positive per-target contribution means that instance beat its best known.

The seed solver is **deterministic** (no random moves) and its local search **converges well within 60 s** and
then idles (it has no restart), so these 60 s numbers are what it produces at any larger budget too — checked on
the worst-gap target X-n411-k19, which gives 21405 at both 60 s and 120 s. The module's `DEFAULTS` are
`time=120, workers=3`; the extra per-target time is headroom for the *evolved* solvers (LNS / restarts /
simulated annealing), not the seed, so a night run reproduces exactly this seed table. `workers` is parallelism
only and does not change any per-target result.

## Verifier ground truth

`verify.py` parses the TSPLIB `.vrp` (NODE_COORD / DEMAND / DEPOT sections, CAPACITY, EUC_2D) and rounds each
edge to the nearest integer (`nint(x) = floor(x + 0.5)`). Downloading each target's **official** best-known
`.sol` and re-checking it reproduces the published cost **exactly** on all ten:

```
X-n280-k17 33503  X-n303-k21 21736  X-n327-k20 27532  X-n336-k84 139111  X-n401-k29 66154
X-n411-k19 19712  X-n429-k61 65449  X-n459-k26 24139  X-n480-k70 89449   X-n491-k59 66483
```

The checker is also proven to reject bad solutions: a customer visited twice, a route over capacity, a missing
customer, and a customer number out of range are each returned as `feasible: false`. See
`python problems/cvrp/test_cvrp.py` (offline verifier + `--no-publish` tests) and the ground-truth test inside it.

## Current nightly operation

The historical 160-minute schedule and automatic pushes have been replaced. Routing now receives 180 research minutes plus 30 retrospective minutes in the counterbalanced trial. Research produces local evidence; publication requires separate exact-file approval. See [operations](../../docs/OPERATIONS.md).
