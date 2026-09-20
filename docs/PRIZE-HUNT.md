# Prize Hunt

Prize Hunt is the bookkeeping layer that decides which public challenge, bounty or record table is
worth spending research allowance on, and what a result there would actually mean. It tracks the
prizes, scores them against each other, measures how the lab's solvers scale toward the real target
sizes, and records what each research direction cost.

It does not submit anything, claim anything, email anyone or spend anything. Two plugins
(`ecc_prize`, `hash_collision_prize`) were added so that the two hardest categories have a local,
authorized ladder to measure. The real challenge instances are metadata.

## What the words mean here

- **Compared** and **measured**: a number this lab produced under its own verifier, on its own
  ladder or benchmark.
- **Unverified** / **status uncertain**: copied from a public page on a stated date and not
  confirmed with the sponsor.
- No result in this subsystem is ever described as *won*. A prize amount in `data/prizes.json` is
  quoted wording, not expected income.

## Pieces

| File | Role |
| --- | --- |
| `data/prizes.json` | Operator-curated registry of prizes. Untrusted quoted display data. |
| `data/prizes/evidence/<date>-<source>.json` | What was observed on that date: HTTP status, page wording, balances, rates. |
| `data/prizes/intake/<slug>.json` | Candidates fetched by `prize_intake.py`. Not part of the registry until approved. |
| `prize_registry.py` | Validation, the reviewed `PRIZE_BINDINGS`, snapshots, control state, status updates. |
| `prize_contract.py` | The structural contract a prize research plugin's `PRIZE` descriptor must satisfy. |
| `prize_scoring.py` | Categorical scoring, ranking and a deterministic allowance plan. |
| `prize_scaling.py` | Least-squares scaling fit over the measured ladder, and extrapolation to the real target size. |
| `prize_economics.py` | What each research direction cost, which ones to stop, and the dead-end ledger. |
| `prize_intake.py` | Fetch one operator-typed URL into a candidate file; approve or reject by hand. |
| `problems/ecc_prize/` | Generated prime-field ECDLP ladder (24..48 bits). |
| `problems/hash_collision_prize/` | Salted truncated-digest collision ladder (28..44 bits). |

## Safety rules the code enforces

1. Only explicitly public, authorized challenges. A curve, address, script or hash never enters a
   code path from a user-supplied source: the reviewed bindings live in
   `prize_registry.PRIZE_BINDINGS`, in Python, and `validate_snapshot` re-derives every admission
   from that dict. Editing `data/prizes.json` changes what is displayed, never what is run.
2. Generated code never verifies itself. Every verifier is `problems/<name>/verify.py`, called by
   `problem.evaluate` on the worker's output file, recomputing the claim from public instance data.
   `prize_contract` scans `problem.py` with `ast` and fails any plugin whose `evaluate` reaches for
   `seed_solver` or a generated `solver`.
3. No automatic submission, email, cloud spend or external message. Two commands touch the network,
   both typed by a human: `prize_intake.py add <url>` fetches that one URL, and
   `prize_registry.py check-sources` re-checks URLs already in the registry. Neither the loop nor
   the night runner fetches anything.
4. The hash plugin hashes salted synthetic messages only. It never connects to a wallet, a key or a
   third-party system.
5. Prize status is data with provenance. A verified fact carries an `evidence` row (URL, date, what
   was observed); everything else is `status_uncertain`. No prize value is invented: an unobserved
   amount is `estimated_usd: null` with the reason in `estimated_usd_basis`.

## The registry

`data/prizes.json` is schema version 1: `{"schema_version": 1, "updated_at": "YYYY-MM-DD",
"prizes": [...]}`. `prize_registry.validate_prize` is the exact field list; the enums are module
constants in the same file. The fields that drive everything downstream:

| Field | Values |
| --- | --- |
| `category` | `ecdlp`, `hash-collision`, `compression`, `benchmark-record`, `publication`, `other` |
| `status` | `verified_active`, `probably_active`, `status_uncertain`, `historical`, `closed`, `solved`, `not_prize_eligible` |
| `status_confidence` | `high`, `medium`, `low` |
| `computational_difficulty` | `trivial`, `small`, `moderate`, `large`, `infeasible_today` |
| `research_difficulty` | `engineering`, `incremental`, `open_problem`, `breakthrough_required` |
| `probability_category` | `likely`, `possible`, `unlikely`, `remote`, `negligible` |
| `compute_cost_estimate` / `model_cost_estimate` | `{"category": negligible\|cheap\|moderate\|expensive\|prohibitive, "note": str}` |
| `publication_value`, `commercial_value`, `transfer_value` | `none`, `low`, `medium`, `high` |
| `research_priority` | `active`, `queued`, `watch`, `parked`, `excluded` |

`expected_value_score` is deliberately not stored. Scores are computed at view time by
`prize_scoring` so the file carries only categories, verified numbers and evidence.

### Admission

`prize_registry.admission(prize)` returns `ready` or `needs_setup`. A prize is `ready` only when a
reviewed binding names its plugin, baseline and verifier, `problems/<plugin>/problem.py` and
`verify.py` both exist locally, the operator has not set `research_priority: excluded`, and the
status is runnable. `closed`, `solved` and `not_prize_eligible` are not runnable, with one
deliberate exception: a `not_prize_eligible` benchmark the operator keeps at
`research_priority: active` stays ready, because its value is publication or commercial and the
scorer reports it under credibility rather than cash.

The bindings that exist today:

| Prize id | Plugin | Admission |
| --- | --- | --- |
| `certicom-eccp-131` | `ecc_prize` | ready |
| `todd-sha256-collision`, `todd-ripemd160-collision`, `todd-hash160-collision`, `todd-hash256-collision` | `hash_collision_prize` | ready |
| `packomania-csqv-records` | `circle_packing` | ready |
| `matmul-rank-records` | `matrix_multiplication` | ready |
| `cvrplib-x-open` | `cvrp` | ready |
| `miplib-open-instances`, `pglib-opf-benchmarks` | none | needs setup |

Everything else in the registry has no binding and is display data.

### Commands

```powershell
python prize_registry.py refresh
python prize_registry.py list
python prize_registry.py show certicom-eccp-131
python prize_registry.py check-sources
python prize_registry.py set-status todd-sha256-collision --status verified_active --confidence high --url "https://example.org/page" --observed "what the page said on this date" --by operator --note "optional"
```

`refresh` re-validates `data/prizes.json` and writes the snapshot `runs/prizes/registry.json` plus
`runs/prizes/refresh-status.json` (`fresh`, `stale` or `unavailable`). It fetches nothing. `list`
and `show` read that snapshot, so run `refresh` first after editing the registry, or they report an
empty board.

`check-sources` is the only registry command that uses the network: it fetches each `source_url`
with a 10 second timeout, reports the HTTP status and whether the page still contains the prize's
target keyword, prints the result and writes `runs/prizes/source-check.json`. It never edits
`data/prizes.json`.

`set-status` is how a re-check is recorded. It appends one `evidence` row and one `history` row per
changed field and rewrites the file atomically under a lock. Prior evidence is never deleted, so the
history of a status is readable after the fact.

### Prize Hunt CLI

`scripts/prize_hunt.py` is the read-only terminal view of the same data the dashboard shows. It never
runs a solver, calls a model or fetches a page.

```powershell
python scripts/prize_hunt.py board                                  # every prize with status, admission, bucket, cash EV, cost and priority
python scripts/prize_hunt.py contracts                              # every installed prize plugin against the prize contract (exit 1 on a failure)
python scripts/prize_hunt.py allocate --allowance 10 --minutes 60   # a portfolio plan for a hypothetical allowance
python scripts/prize_hunt.py scaling --prize certicom-eccp-131      # ladder fit and extrapolation to the real target
python scripts/prize_hunt.py economics --problem ecc_prize          # per-direction spend, gain and keep/stop verdicts
python scripts/prize_hunt.py next                                   # the exact loop.py command for the top-ranked ready prize
```

### Intake

```powershell
python prize_intake.py add https://example.org/challenge --kind challenge --name "Optional name"
python prize_intake.py list
python prize_intake.py approve <slug> --priority queued
python prize_intake.py reject <slug> --reason "not an authorized challenge"
```

`add` validates the URL (`http` or `https`, no userinfo), fetches it with a 10 second timeout and a
512 KiB cap, strips scripts and tags, and writes `data/prizes/intake/<slug>.json` with the title, a
600 character excerpt, every currency mention, deadline phrases, a category guess and a
PRIZE-shaped `proposed_entry` marked `status_uncertain` / confidence `low` / plugin `null`. The
whole record is stamped `content_classification: "untrusted_quoted_source"` and nothing from the
page is executed. The command prints the path and `not admitted: run approve to add it to
data/prizes.json`. `approve` moves the proposed entry into `data/prizes.json` through the
registry's validated writer with a `by: "operator"` history row; an entry that fails registry
validation is refused. `extract(html, url)` and `propose(extracted, kind, name)` are pure functions
and are what the tests exercise; no test touches the network.

## Scoring

`prize_scoring.score_prize(prize, progress=None)` returns three-point bands, never a single number:
`cash_ev_usd`, `credibility_ev_usd`, `cost_usd`, `ev_per_dollar`, plus `information_gain` (0..1),
`priority_score`, a `bucket` and a `rationale` list. Cash and credibility are reported separately
and are never summed.

- Probability bands by `probability_category`: likely `(0.3, 0.5, 0.7)`, possible
  `(0.05, 0.15, 0.3)`, unlikely `(0.01, 0.03, 0.08)`, remote `(1e-4, 1e-3, 5e-3)`, negligible
  `(0, 1e-6, 1e-4)`.
- Status factor, "would it actually be paid": verified_active 1.0, probably_active 0.7,
  status_uncertain 0.35, historical 0.1, closed / solved / not_prize_eligible 0.
- Credibility-equivalent dollars per value field: none 0, low 500, medium 3,000, high 15,000. These
  are a comparison axis, not money.
- Cost bands per attempt, USD: negligible `(0, 0.5, 1)`, cheap `(1, 5, 10)`, moderate
  `(10, 50, 100)`, expensive `(100, 500, 1000)`, prohibitive `(1000, 3000, 10000)`.
- Multipliers: dense feedback 1.5; independent verification strong 1.2 / partial 1.0 / weak 0.6;
  competition high 0.6 / medium 0.8; parallelizable 1.1; time horizon years or open-ended 0.7.
- Information gain weights, summing to 1: dense feedback 0.35, verification 0.25, transfer 0.25,
  measured progress 0.15. A measured relative gain of 0.1 counts as a full progress payout.

`bucket` is `excluded` when `research_priority` is `excluded` or the status is closed or solved;
`moonshot` when the prize is `infeasible_today`, needs a breakthrough, or has a remote or negligible
probability; otherwise `measurable-progress`.

`rank(prizes, progress_by_id=None)` sorts by `priority_score` with excluded entries last.
`allocate(prizes, allowance_usd=..., minutes=..., moonshot_share=0.2, max_share=0.5,
progress_by_id=None)` splits the allowance 80/20 between the two buckets, shares each pool in
proportion to `priority_score * information_gain`, caps any single prize at `max_share` of the whole
allowance, skips anything not `ready`, and leaves the rest in `unallocated_usd` rather than pushing
it at a weak candidate. It is deterministic and it spends nothing: the return value is a plan.

## Scaling

`prize_scaling` fits `log2(seconds) = alpha + beta * bits` by least squares over the measured ladder
and extrapolates to the real target size.

- `fit_scaling(points)` needs at least 3 points of `{"bits": int, "seconds": float}` and returns
  `alpha`, `beta`, `r2`, `n_points`, `residual_sd` and `beta_vs_theory`. The theory value is 0.5:
  both Pollard rho and a birthday search cost about `2^(bits/2)` operations.
- `ladder_points(root, problem)` reads the incumbent rows from
  `runs/research/*/<problem>/evidence.json` and maps each target name to its bit size through the
  plugin's `records.json`. With no runs it falls back to the committed `reference.baseline_seconds`
  and labels the points `"source": "baseline_reference"`.
- `extrapolate(fit, target_bits, cpu_cost_per_hour=0.05, gpu_speedup=None, gpu_cost_per_hour=1.0)`
  returns `seconds`, `cpu_years`, `usd` as low/mid/high bands, an optional `gpu_years` band that is
  labelled as an assumed speedup, a `verdict` (`feasible`, `expensive`, `infeasible`; infeasible
  above 1e6 USD or 100 CPU-years at the mid estimate), the `assumptions` list and a one-line
  `summary`.
- `analysis(root, prize, plugin_module)` combines them for the prize's real target: 131 bits for
  ECCp-131, the full digest width for the hash bounties. It degrades to `supported: False` with a
  reason rather than raising.

The extrapolation is there to make infeasibility visible, not to hide it. At the theoretical
scaling, a 131-bit ECDLP and a 160- or 256-bit collision are out of reach by many orders of
magnitude; that gap closes only through a change of economics, not through tuning.

## Economics

`prize_economics.ledger(root, problem)` reads `evidence.json` and `routing.json` under
`runs/research/*/<problem>/` and returns per-candidate rows (`cost_usd`, `elapsed_seconds`,
`solver_seconds`, `median_gain`, `selection_gain`, the idea trimmed to 200 characters,
`development_status`, `iteration`, `run_id`, `provider`, `family`, `actual_model`), the direction
summaries, totals and the assumptions. Local electricity is estimated, not metered:
`local_compute_usd = solver_seconds / 3600 * 0.15 kWh * 0.15 USD/kWh`, with both constants exposed
as `LOCAL_KWH_PER_HOUR` and `USD_PER_KWH`.

`direction_summary(candidates)` groups candidates by idea family and writes one plain sentence per
direction, for example *"This research branch consumed $12 across 5 attempts with no scaling
improvement. Stop exploring it."* A direction is marked `stop` after at least 3 attempts whose best
gain never cleared the minimum effect.

`stop_recommendations(ledger)` proposes dead ends; a human confirms them, and
`record_dead_end(root, entry, by)` appends to `problems/_dead_ends.json` under a lock, using the
same schema as `scripts/dead_ends.py`, so matching entries are injected into later candidate
prompts. `progress(root, problem)` is the measured-gain input that raises a prize's information
gain in the scorer. `ev_impact(prize_score, gain)` says in one sentence how a measured gain moves
the scaling verdict, with no invented precision.

## The plugin contract

A prize research plugin declares a `PRIZE` dict in its `problem.py` with 13 fields: `objective`,
`candidate_artifact`, `baseline`, `development_benchmark`, `holdout_benchmark`,
`independent_verifier`, `fitness_metrics`, `real_target`, `prize_registry_id`,
`promotion_threshold`, `estimated_scaling`, `publication_requirements`, `submission_requirements`.

`prize_contract.validate_prize_plugin(module)` returns `{"ok", "missing", "errors"}`. It checks that
every field is present and non-empty, that the benchmark lists are subsets of `TARGETS | HOLDOUT`,
that `promotion_threshold` is `{"min_effect": 0 < x < 1, "seed_count": >= 1, "holdout_required":
True}`, that `independent_verifier` names this plugin's `verify.py` and the file exists, that the
ordinary plugin members (`TARGETS`, `evaluate`, `score`, `beats`, `validate_release`, `DEFAULTS`)
are present, and that `evaluate` does not reference `seed_solver` or `solver`.
`prize_contract.prize_plugins(root)` lists the plugin directories that declare a descriptor without
importing any of them. `tests/test_prize_contract.py` validates every installed prize plugin, so a
descriptor that drifts from its plugin fails the suite.

`circle_packing` and `matrix_multiplication` carry descriptors as well. Neither withholds targets:
their confirmation re-runs the development set under fresh seeds, so their `holdout_benchmark` is
that same set and measures repeatability rather than generalization, and their descriptors say so.

## The two research ladders

Both plugins measure search machinery at sizes this lab can finish. Neither is partial progress
toward the real instance, and both say that in their module docstring, their prompt and their
README.

### `ecc_prize`

Generated prime-field curves with the same shape as ECCp-131 (`y^2 = x^3 + ax + b` over `F_p`,
prime order, cofactor 1). Development targets `ecdlp-p24-dev`, `ecdlp-p28-dev`, `ecdlp-p32-dev`,
`ecdlp-p36-dev`; holdout `ecdlp-p28-hold`, `ecdlp-p32-hold`, `ecdlp-p36-hold`, `ecdlp-p40-hold`;
opt-in large `ecdlp-p44-large`, `ecdlp-p48-large`. The baseline is a parallel Pollard rho with
batched affine additions. The value of a run is the wall time to a verified discrete logarithm;
`verify.py` recomputes `k*P` with its own scalar multiplication and compares it with `Q`.
`beats()` is always `False` and `validate_release` reports `supported: False`: these curves are
generated here, so there is no public record and no claim can travel through the win gate. ECCp-131
lives in `problem.PRIZE_TARGET_METADATA` for display and for the scaling extrapolation only.

### `hash_collision_prize`

Salted truncated-digest collisions. Development `sha256-t28-dev`, `sha256-t32-dev`,
`sha256-t36-dev`, `ripemd160-t32-dev`; holdout `sha256-t32-hold`, `sha256-t36-hold`,
`ripemd160-t32-hold`, `sha256r24-t32-hold`; opt-in large `sha256-t40-large`, `sha256-t44-large`, `ripemd160-t36-large`, `ripemd160-t40-large`. A
solution is two distinct messages of 1..64 bytes whose salted digests agree on the first `bits`
bits. The baseline is a van Oorschot-Wiener distinguished-point search.

> Truncated collisions measure search machinery only; they are not partial progress toward a full
> collision.

The four funded Peter Todd bounties are recorded in `problem.PRIZE_TARGET_METADATA` for display
only, with the addresses and scripts observed on 2026-09-20. They are never targets, and no code
path accepts a hash, an address or a key from a user-supplied source.

In both plugins the scored value is the worker's own reported elapsed time, accepted only after the
independent verifier passes and clamped to a bounded range. Verification is independent; the timing
is not. The loop's own per-row `secs` is the trusted clock and is recorded beside every value in
`evidence.json`. Each plugin's `LIMITATIONS` list carries this and the rest.

## Running the first experiment

The ladders run through the ordinary research path, so nothing new is needed to start one. The
descriptor's promotion threshold for `ecc_prize` is a 5 percent minimum effect over 3 matched seeds
with the holdout required, and its defaults are 60 solver seconds and 3 workers.

```powershell
python loop.py --problem ecc_prize --provider fable --run-id prize-ecc-2026-09-20 --iters 6 --budget 6 --call-budget 1.0 --seed-count 3 --min-effect 0.05 --time 60 --workers 2 --wall-minutes 90 --no-publish
```

The hash ladder is the same command with its own plugin; its descriptor asks for 5 seeds:

```powershell
python loop.py --problem hash_collision_prize --provider fable --run-id prize-hash-2026-09-20 --iters 6 --budget 6 --call-budget 1.0 --seed-count 5 --min-effect 0.05 --time 60 --workers 2 --wall-minutes 90 --no-publish
```

`--provider fable` names the Anthropic subscription family; the configured routing chain decides
which model actually executes the call, and the routing journal records it. `--no-publish` is a
compatibility flag: every research run stops at local evidence either way. Add `--targets` with the
`-large` names for an opt-in run at 44 or 48 bits, and expect it to take much longer than the
committed baselines.

Afterwards, `prize_economics.ledger(root, "ecc_prize")` shows what each direction cost and
`prize_scaling.analysis(root, prize)` re-fits the ladder with the new rows.

## The nightly prize slot is opt-in

`night.json` carries a top-level `prizes` block that ships **disabled**:

```json
"prizes": {
  "enabled": false, "minutes": 60, "research_minutes": 45, "retro_minutes": 15,
  "slot_budget_usd": 8.0, "per_call_budget_usd": 1.0, "retro_budget_usd": 2.0,
  "moonshot_share": 0.2, "max_share": 0.5, "provider": "paired",
  "iters": 20, "time_per_target": 60, "workers": 2
}
```

While `enabled` is false the block's numbers are not even validated and the night's plan, budget and
commands are exactly what they were before. Setting `enabled` to true makes `load_schedule` validate
it like any other slot: research and retro minutes must be positive and fit inside the slot, the
per-call budget must be positive and within the slot cap, the provider must be `fable`, `astra` or
`paired`, the shares must be fractions, the slot must fit inside `deadline_minutes`, and the slot
plus retro caps must fit inside the night's `budget_usd`. When it does not fit, the `ValueError`
names the exact shortfall (how many minutes over the deadline, how many dollars over the budget).

The committed schedule ships with **no headroom**: its four slots already fill all 540 minutes and
all $105 of the allowance, so flipping `enabled` to true refuses the whole night - 60 minutes over
the deadline and $10 over the budget, exactly what the block asks for. Make room first by shrinking
one research slot. The smallest edit that fits the shipped block is `cvrp-research` at **150
minutes** (120 research + 30 retro) and a **$30** slot budget: that leaves precisely the prize
block's 60 minutes and its $8 + $2, and the night still totals 540 minutes and $105.

The dashboard route to the same room, without editing JSON: open **http://localhost:8766**, set a
smaller night duration and nightly research allowance, and save. `update_schedule` counts the
enabled prizes block in both sums and scales the slots and the block together by one factor, then
refuses to save anything `night.load_schedule` would reject. Use it when the whole night should
shrink; edit `cvrp-research` by hand when only that slot should give up its time.

When it is enabled, `night.py` re-snapshots the registry, asks `prize_scoring.allocate` for a plan
over the enabled prizes with the measured `prize_economics.progress`, and turns at most one
allocation into one bounded research slot named `prize-<prize_id>`. A prize whose plugin already has
a slot tonight is dropped with a reason, as is one whose allocation leaves no usable allowance. The
chosen slot writes `runs/research/<run-id>/<plugin>/prize-mission.json`, an informational record of
why it was scheduled: the prize id, the registry hash, the allocation, the success criterion from
the binding and the budget. The loop reads no prize text from it.

Check the plan without running anything:

```powershell
python night.py --dry-run
```

Which prizes are eligible at all is control state, not registry data:
`prize_registry.load_control`, `update_control(root, enable=..., disable=..., next_id=...)` and
`consume_next` read and write `runs/prizes/control.json`. All ready prizes are enabled by default.

## Dashboard

`prize_report.build_prize(root)` assembles the prize board, the money board, the allocation queue,
the economics ledgers and the stop recommendations into one JSON payload. The local dashboard serves
it at **http://localhost:8766/prize** when the dashboard is running, alongside the existing review
and morning pages. Its buttons enable or disable a prize, choose which one runs first next night,
record a dead end, approve or reject an intake candidate, and record a re-checked status. Every one
of those is local state; the page never fetches a prize source, because the only two commands that
use the network are the ones named under the safety rules. A checkout without `prize_report.py`
reports the modules as unavailable rather than failing the dashboard.

## Verification

```powershell
python -m pytest -q -p no:cacheprovider tests/test_prize_registry.py tests/test_prize_contract.py tests/test_prize_scoring.py tests/test_prize_scaling.py tests/test_prize_economics.py tests/test_prize_intake.py tests/test_prize_night.py tests/test_prize_dashboard.py tests/test_ecc_prize.py tests/test_hash_collision_prize.py
```
