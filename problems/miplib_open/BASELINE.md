# miplib_open seed baseline (MIPLIB 2017 OPEN instances)

The value to beat per target is the **published best-known objective** on the MIPLIB 2017 site
(`records.py` reads it from the newest official `.solu` file's `=best=` line and caches provenance in
`records.json`). All ten targets are OPEN instances: a feasible solution is known but optimality has never
been proven, so a verified feasible point **below** the best-known (for a min instance) is a genuine,
externally creditable result that ZIB lists. Per-target value = `(obj - best_known)/max(1,|best_known|)` in
min-sense (max-sense instances converted): **0 ties the best-known, negative beats it.** A win is push-only;
a human submits the `.sol` by hand (see "Submission" below); nothing is emailed automatically.

## Selection procedure (run for real on this machine)

`baseline.py` size-filters the open set to the 40 smallest by nonzeros (`--screen`), runs plain HiGHS
(default options, 2 threads, 1e-7 tolerances) for 120 s on each (`--measure`), then ranks (`--select`). The
screen ran all 40 at 120 s, 3 in parallel. **27 of 40 were feasible in 120 s**; the rest either found no
feasible point or their HiGHS incumbent failed the independent 1e-6 checker.

`select()` is a mechanical cascade (movability = how far HiGHS's 120 s incumbent lands from best-known):

- **T1**: feasible and `1e-6 < gap <= 0.10` (real, small, movable) &mdash; 14 candidates
- **T2**: `0.10 < gap <= 0.30` &mdash; 3 candidates (used only to backfill if T1 < 10)
- **T3**: `gap <= 1e-6` and HiGHS did **not** prove optimality (ties best-known; only a record beat scores) &mdash; 1
- **excluded**: `gap > 0.30` (a permanent clipped -1.0 that would drown the champion total) and any instance
  HiGHS solved to `kOptimal` within 120 s (effectively closed, e.g. `neos-5045105-creuse` at +0.0009%)

Within each tier: oldest best-known first (looser, more movable), then smallest by nonzeros. **All ten
targets came from T1**, so no T2/T3 backfill was needed.

## The ten targets

`bks` = published best-known (all min-sense). `HiGHS 120s` = plain-HiGHS gap from the screen (the movability
signal). `seed` = `seed_solver.py` gap, measured through the real loop (see next section).

| Instance | vars | rows | best-known | age | HiGHS 120s | seed | submitter (best-known) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| assign1-10-4 | 572 | 582 | 422.0 | 7.9y | +1.90% | +0.24% | (unattributed) 2018-10-13 |
| n3707 | 10000 | 5150 | 1186691.0 | 6.4y | +8.34% | +7.16% | Edward Rothberg 2020-04-22 |
| neos-1423785 | 21506 | 25721 | 21893.26 | 6.1y | +1.38% | +1.74%\* | Edward Rothberg 2020-07-17 |
| n3705 | 10000 | 5150 | 1212657.0 | 6.0y | +9.53% | +6.54% | Edward Rothberg 2020-09-14 |
| milo-v12-6-r1-75-1 | 5698 | 12243 | 1153756.40 | 5.9y | +3.99% | +0.02% | DeepMind 2020-10-07 |
| n3700 | 10000 | 5150 | 1218975.0 | 4.4y | +7.53% | +7.90%\* | Michael Winkler 2022-04-22 |
| ger50-17-ptp-pop-3t | 4892 | 545 | 5224.5144 | 3.3y | +2.36% | +1.75% | Ed Rothberg 2023-05-19 |
| n370b | 10000 | 5150 | 1220708.0 | 2.7y | +7.23% | +5.65% | Mou Sun, Tao Li, Wotao Yin 2023-12-22 |
| n3709 | 10000 | 5150 | 1205801.0 | 2.4y | +9.53% | +7.09% | Davletshin Mars 2024-04-20 |
| r4l4-02-tree-bounds-50 | 11468 | 4768 | 499132179.0 | 2.1y | +4.65% | +3.13% | Mars Davletshin 2024-07-17 |

Mean seed gap **+4.12%** (at the 240 s measurement budget). No target beats its best-known yet; the loop's
job is to close these gaps, and a negative per-target value would be a genuine open-instance win.

**Known limitation (target concentration):** five of the ten (`n3707`, `n3705`, `n3700`, `n370b`, `n3709`)
are the `n37xx` network-design family &mdash; near-identical 10000-var / 5150-row instances differing mostly by
seed. They dominate because the small-and-old open set is small and this family fills it. They are legitimate
old T1 open instances, but a single algorithmic idea tends to move all five together, so treat the family as
roughly one signal, not five, when reading the scoreboard. A per-family cap in `select()` is a reasonable
future refinement; the current selection is left purely mechanical for reproducibility.

## Seed solver and gaps

Seed = `seed_solver.py` (pure python + numpy + highspy): plain HiGHS for a budget-scaled warm-start slice
(`phase1 = clamp(0.25 * time, 20 s, 150 s)`), then adaptive large-neighbourhood search &mdash; fix a random
subset of the integer variables at the incumbent, re-solve the sub-MIP under a scaling time limit, keep
improvements, widen the neighbourhood when a sub-MIP is solved to optimality/infeasibility and tighten it
when it times out. It saves atomically on every improvement (a hard kill still leaves the best) and records
an `[elapsed, obj]` improvement trace.

Measured through the real loop in two chunks (so each foreground run finished inside the 10-min window):

```
python -u loop.py --problem miplib_open --eval-only --targets <5 targets> --time 240 --workers 3 --no-publish
```

The seed improved the HiGHS-120s screen incumbent on **8 of 10** targets. The two marked `*`
(`neos-1423785`, `n3700`) regressed **only at the 240 s measurement budget**, because the seed's warm-start
slice is budget-scaled: at `time=240` phase 1 gets `0.25*240 = 60 s` of plain HiGHS, weaker than the 120 s
screen. Re-run at `time=560` (phase 1 = 140 s), both recover and beat the screen:
`neos-1423785 +1.74% -> +1.01%`, `n3700 +7.90% -> +5.50%`.

### Why DEFAULTS = {time: 600, workers: 3}

The improvement trace decides it, not a guess:

- **The curve has not flattened.** At the 240 s budget, 9 of 10 targets were still recording improvements in
  the final third (last improvement clustered at 218-238 s; e.g. `n3709` improved 7 times after 160 s). More
  budget still buys progress. Confirmed again at 560 s (last improvements at 518 s and 558 s on the two
  re-runs). Only `assign1-10-4` (572 vars) converges early (~82 s) and idles.
- **Phase 1 reaches its full 150 s cap only at `time >= 600`.** So the DEFAULT budget gives the seed a
  stronger warm start than the 120 s screen on every target, which is why the two 240 s regressors turn into
  clear improvements at the real budget.
- **Night math.** With `time=600, workers=3` and 10 targets, one iteration is `ceil(10/3) * 600 = 2400 s`
  (40 min) of solver wall-clock. A 160-minute night slot fits about **3** evolution iterations before the
  loop's start guard (`budget + 360 s` before the wall) stops it. `workers` is parallelism only and does not
  change any per-target result. See `docs/miplib-open-night-slot.md`.

## Verifier ground truth

`verify.check` reuses the shared engine `problems/miplib/verify.py` (the same code `miplib_heur` verifies
with, no fork): bounds, integrality, every row activity, and the objective in the instance's own sense, all
to a 1e-6 absolute-or-relative tolerance. Downloading each target's **official** best-known `.sol` from the
MIPLIB site and re-checking it reproduces the published objective on **all ten** targets (value `<= 1.7e-7`,
i.e. inside 1e-6):

```
assign1-10-4 422        n3707 1186691    neos-1423785 21893.264  n3705 1212657
milo-v12-6-r1-75-1 1153756.4            n3700 1218975            ger50-17-ptp-pop-3t 5224.5144
n370b 1220708           n3709 1205801    r4l4-02-tree-bounds-50 4.9913218e8
```

The checker is also proven to reject bad solutions (`test_miplib_open.py`): on a synthetic MILP, a solution
that violates a **bound**, one that violates **integrality**, and one that violates a **row** are each
returned `feasible: false` with exactly the corresponding `*_viol` field tripped and the other two clean.

**Finding (verifier is deliberately stricter than MIPLIB's own checker).** Two screened *candidates* that are
not targets, `neos-1420790` and `liu`, have official `.sol` files whose objective equals the published
best-known exactly but whose maximum row activity is `8.4e-6` and `4.8e-3` over the bound, so our 1e-6 row
tolerance marks them `feasible: false`. The shared engine's docstring states this on purpose ("stricter than
MIPLIB's own solution checker"). It is the safe direction: we never falsely credit a win, and HiGHS
incumbents away from the constraint boundary (the 120 s screen values) pass fine. It does mean a would-be win
that only clears best-known by riding a row to the tolerance boundary would be rejected here and must be
re-checked by ZIB's exact checker before submission.

## Submission (push-only)

ZIB accepts improved open-instance solutions by email; the loop never sends one. Verified off the live home
page (2026-09-04): *"Contributions of new solutions to open instances are always welcome ... Please send your
submissions to miplibsolutions@zib.de."* So `problem.EMAIL_TO` is `None`, `publish.py` only does the GitHub
push of `best-miplib_open/`, and a human submits a win by hand: attach `best-miplib_open/sol/NAME.sol`
(MIPLIB `.sol` format, written by `problem.save`) in an email to `miplibsolutions@zib.de`. Re-verify first:
`python problems/miplib_open/verify.py best-miplib_open/sol/NAME.json`.

## night.json slot

Proposed in `docs/miplib-open-night-slot.md` (not applied by this branch): swap the `miplib_heur` slot for
`miplib_open`, same 160 minutes from 22:00, keeping `pglib_opf` and `cvrp`. `miplib_open`'s wins are
externally creditable; `miplib_heur`'s bar ("HiGHS default on this PC") is not.
