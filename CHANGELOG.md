# Changelog

## Feedback loop: replicated development gate, reviewed losers, richer memory, 2026-09-20

Audit of the 40 research runs on disk (200 candidates, 191 with a gain, 808 paired cells): 85 candidates were
ahead, 75 behind and 31 exactly level; the 90th-percentile gain was +0.18% and the best +1.08%; 3 runs confirmed
and none was publishable. The development matrix was one seed per target (`loop.py` built it with a hardcoded
`1`), the gate accepted a median gain of 1e-4, and the replication check was disabled with `min_seeds=1`. On the
three-seed confirmation runs the *same solver on the same target* moved 0.06%-0.57% between seeds on cvrp, so the
label the whole loop learned from -- promising or rejected -- was decided inside its own noise band.

- `loop.py` races every candidate: `race_stages` splits the matrix into the screening prefix, the rest of the
  first seed, then one stage per replication seed, and `race_verdict` stops a candidate that fails a cell, is
  worse on every screening target, is not ahead overall, or whose newest seed did not reproduce its advantage.
  A loser costs one stage; only a candidate still ahead spends replication seconds. The incumbent is evaluated
  lazily, so a night where nothing survives the first seed never pays for seeds two and three.
  `--development-seeds` (default 3, set per slot in `night.json`) is now separate from `--seed-count`, which
  stays the confirmation setting.
- `evaluation.py` reports `median_lower_bound`, the 10th percentile of a bootstrap over the paired cells, and
  requires it above zero to pass. Replayed over the 179 historical candidates that carry paired rows it keeps 16
  of 44 cvrp and 7 of 23 miplib_heur promotions and rescues no rejection: it trades recall for precision on a
  gate whose promotions were not reaching confirmation. The `per_target_pareto` policy bounds the selected
  target's own gains instead, so "improve one target, regress none" stays expressible.
- `postmortem.py` (new) reviews losing candidates. The critic previously ran only on candidates that passed, so
  112 rejections and 4 evaluation failures were recorded with the loop's own verdict and nothing else -- and the
  same idea came back: four near-identical "granular swap* layered on the existing SISR/SA search" proposals
  across four nights. A crash or a near miss now gets one bounded call (`--postmortem-limit`, default 3,
  `--postmortem-budget`, default $0.50) that answers with a MECHANISM and a RETRY line; the mechanism becomes
  that candidate's negative result. A stopped or failed review never stalls the night.
- `loop.py` records the solver's own error text instead of a count: `evaluation_failed` previously reached memory
  as "3 development evaluation failures", which names nothing a model can fix.
- `research_memory.py` keeps each candidate's per-target outcome (`cells`: won, lost, tied, failed and the median
  gain on each target) and rolls the same per-target gains up per algorithm family, so a family that wins on one
  instance class and loses on another is visible in the prompt instead of being averaged away.
- `loop.py` puts this run's measured near misses in the generation prompt: up to two rejected candidates with
  their idea, per-target gains, the reviewed reason they failed, and a bounded unified diff against the file
  being edited. Until now a rejected candidate's code left the loop the moment it was written.
- Solvers may report their own best-so-far curve as `"trace": [[seconds, objective], ...]`; `search_summary`
  validates and bounds it (64 points), and the development profile gains "time to best" and "improvements"
  columns. The interface contract for cvrp, miplib_heur and matrix_multiplication documents it as optional and
  never scored. Nothing about scoring changed: the independent verifier remains the only source of a value.

Expected cost, from the measured cvrp timings (119 s per development cell, 8 targets, 3 workers, so 5.3 minutes
per full-target stage): a candidate that dies on the first seed still costs about one stage, a candidate that
survives to promotion costs three, and the incumbent pays 15.8 minutes once per night instead of 5.3 -- but only
if something reaches the replication seeds. Applying the historical 45% survival rate past the first seed, a
180-minute cvrp slot that fit 18 candidates should now fit roughly 9 to 11. That is the trade for a label that
means something; the screening prefix, the stage rules and the lazy incumbent are what keep it affordable.

## Night reliability and cheaper iterations, 2026-09-20

Audit of the six nights 09-14 to 09-19: three produced no research at all. 09-15 ended with every model at
`usage_limit` within six minutes of the start and $4 charged; 09-18 ended after two 900 s Opus timeouts and a
usage-limited Codex, $8 charged, no candidates; 09-19 failed a single Docker probe at 02:00 with eight hours of
deadline left. Of the three nights that did run, 09-17 lost four generations to `fable CLI exited with status 1`.

- `routing.py`: breakers now carry an expiry. `usage_limit` and `quota_exhausted` reopen after 60 minutes,
  `timeout`, `capacity` and `rate_limited_unclassified` after 20; `authentication` and `model_unavailable` still
  hold for the night. A refused call with no reported cost charges $0 instead of its whole reservation.
  `chain_retry_after` reports when the first route in the chain reopens, and a CLI that exits non-zero with a
  genuine infrastructure error is retried once on the same model.
- `loop.py`: a generation whose whole chain is breaker-blocked waits for the earliest reopen instead of ending
  the slot, at most four times, only while a deadline still leaves ten minutes of margin, in 30 second slices so
  a pause still interrupts it. A critique never waits: it degrades to `promising_unreviewed` as before.
- `providers.py`: a CLI that stops itself at `--max-budget-usd` is classified `call_budget_exceeded`, not
  `infrastructure_error`. The 09-17 losses were this: the same prompt under the same cap fails identically, so
  it must not be retried or routed to another model. Reproduced on 2026-09-20 with a 50 KB cvrp prompt at a
  $0.75 cap (`error_max_budget_usd`, "Reached maximum budget ($0.75)", $0.78 charged).
- `isolation.py`, `night.py`: a missing Docker engine starts Docker Desktop and polls for three minutes, and the
  night re-probes a failed sandbox every five minutes for thirty (`night.preflight_retry_minutes`). A provider
  that is unreachable at the start is an authentication problem and is never re-probed.
- `loop.py --screen-fraction` (default 0.25): the leading quarter of the development targets is evaluated first.
  A candidate that fails any screening cell stops there, because `compare_paired` requires zero candidate
  failures and finishing the matrix cannot change that verdict. A candidate worse than the incumbent on every
  screening target stops as `screened_out`. Replayed over the 77 candidates of 09-14, 09-16 and 09-17, the
  quarter-matrix rule screened 6 of 44 rejected candidates, kept all 33 promising ones, and would have saved
  5.8% of development solver seconds; the lossless failure abort accounts for another 1.2%. A two-target screen
  saved more but discarded a candidate that went on to pass, so the fraction is deliberately conservative.
- Generation prompt: a `DEVELOPMENT PROFILE` block gives each development target its reference, the incumbent's
  value, the seconds it actually used against the seconds it was allowed, and the last candidate's delta. The
  scoreboard said which targets were behind; it never said whether the solver was spending its time budget.
- `patching.py` and `loop.py --generation-mode diff`: a generation may answer with SEARCH/REPLACE edit blocks
  instead of a rewritten file. Every block must match the current file exactly once; a block that matches
  nothing or matches twice fails the proposal as `patch_failed` rather than being applied by guess. Proven on
  2026-09-20 with two real `claude-opus-5` calls: two blocks against a 4,188 character incumbent for $0.20, and
  three blocks against the 49,821 character cvrp incumbent for $0.88, both applying cleanly to a file that still
  compiles. Off by default; `night.json` sets it per slot, and the cvrp slot is the first to use it, because its
  full-file generations average about $1.93 and exhaust the $40 slot cap after roughly ten candidates.
- `scripts/research_ledger.py`: a validation run is labelled `validation:<status>` and reports its evaluation
  count instead of a blank gain and a missing retrospective. The pglib slot has run 17 evaluations a night since
  09-14 while the ledger showed it as a run that did nothing.

## Run ledger, 2026-09-20

- `scripts/research_ledger.py`: `list` every recorded research run (status, candidates, best measured gain, charge, retrospective state, recorded next experiment), `audit` the finished runs whose retrospective never ran (exit 1, exact `retro.py` command per gap), and `retro` to run them one at a time or all at once. The `/prize` page shows the same gap as a notice. Closes the hole where a hand-launched run recorded evidence but never taught the next prompt anything. Audit on 2026-09-20: 40 runs, 15 finished with candidates, 3 without a retrospective, backfilled.

## Prize Hunt, 2026-09-20

- `data/prizes.json`: an operator-curated registry of 17 public challenges, bounties, record tables and benchmarks, every entry quoted from a page read on 2026-09-20 with a dated evidence file beside it. Amounts and availability are unverified quoted wording; nothing is described as won. `prize_registry.py` validates it and exposes `refresh`, `list`, `show`, `set-status` and the network-touching `check-sources`; the reviewed bindings that make a prize executable live in `PRIZE_BINDINGS`, in code, and `validate_snapshot` re-derives every admission from that dict.
- `prize_contract.py`: the 13-field `PRIZE` descriptor a prize plugin must declare, checked structurally with `ast`. `problem.evaluate` may not reference `seed_solver` or a generated `solver`, so measured code can never verify itself. `circle_packing` and `matrix_multiplication` gained descriptors; neither plugin's behaviour changed.
- `prize_scoring.py`, `prize_scaling.py`, `prize_economics.py`: documented categorical maps producing low/mid/high bands with cash and credibility reported separately, a least-squares `log2(seconds) = alpha + beta*bits` fit over the measured ladder with extrapolation to the real target size, and a per-direction cost ledger with stop recommendations and the shared dead-end file. `allocate` returns a plan; it spends nothing.
- `problems/ecc_prize`: generated prime-field ECDLP instances at 24-48 bits with an independent verifier that recomputes `k*P`. ECCp-131 is metadata only. `problems/hash_collision_prize`: salted truncated-digest collisions at 28-44 bits. Truncated collisions measure search machinery only; they are not partial progress toward a full collision. Both plugins report `beats() == False` and unsupported release validation.
- `prize_intake.py`: one operator-typed URL is fetched with a 10 second timeout and a 512 KiB cap into `data/prizes/intake/<slug>.json` as an untrusted quoted source. Nothing from the page is executed, and an operator must approve a candidate before it reaches the registry.
- Docs: `docs/PRIZE-HUNT.md`, a README section, a research-portfolio row per ladder marked unvalidated and ladder-only, and a decisions entry on bindings in code, opt-in prize slots and proxy targets.

## Large PGLib cases, 2026-09-18

- `problems/pglib_opf.LARGE_TARGETS`: the seven 2,000–2,746 bus TYP cases as opt-in targets with `LARGE_DEFAULTS` (600 s, 2 workers). They stay out of the nightly `TARGETS`; `loop.py --targets` may select them, and the prompt gains a large-case note when any is present.
- PGLib seed solver: verifies at 1e-8 (the loop's release tolerance) before saving; when the Newton polish breaks a limit at scale, a tight warm PIPS re-solve (FEASTOL 1e-9) is tried with and without the polish; never starts an attempt that cannot finish before the worker kill (case2000_goc in the worker: 2.8e-9 max violation, 460 s of 600).
- First large-case research run (three cases, 12 Opus generations, 10 candidates): every candidate re-found the IPOPT local optimum; no confirmed win. Codex was usage-limited and a headless Claude call needs a per-call budget above $2 for large prompts (`--call-budget 5`).

## Opus-first routing and the morning brief, 2026-09-17

- The default routing chain is `opus, astra, sol`. Every Claude call runs on Opus 5 with `--effort xhigh`; Fable stays registered but off the chain. On 2026-09-16, 11 of 24 Fable generation calls hit the $2 per-call cap and returned nothing.
- A trial arm names a subscription family. `model_registry.arm_alias` resolves it to the first same-family alias on the chain, so the Fable arm executes on Opus as its requested model; trial reports treat any same-family alias as matching the arm, and `fable_only`/`astra_only` follow the same rule.
- `/morning` on the local dashboard is a morning brief: last night's slots with the mission, every idea tried, median gains, confirmation and release-check results, the analyst verdict, the full run history, incumbents per problem and an *awaiting publication* list derived from the history. `scripts/install-morning-task.ps1 -Apply` registers `discovery-loop-morning` to open it at 07:00 daily.

## Bounded solver-program islands, 2026-09-15

- Matrix-multiplication research now opts into three run-local solver-program islands with at most three development-verified parents per island. Mutation and crossover share the existing governed generation allowance, routing, pause and deadline path; other plugins keep their existing generation behavior.
- Each paired iteration freezes one parent plan and one rendered prompt before either provider starts. Pending records bind the operator, island, parent files and hashes, and prompt hash; resume reuses durable responses and conservatively records an indeterminate lost response instead of issuing a completed call twice.
- The existing crossover prompt builder now accepts the loop's sanitized canonical context. Development evaluations alone admit and rank parents; confirmation, publication and promotion data never enters island selection.
- Morning evidence shows island occupancy and candidate ancestry, including honest disabled and empty states. These islands evolve whole solver programs and are separate from worker processes inside a generated solver.

## Sealed synthetic CVRP check and honest trial coverage, 2026-09-14

- Add a dashboard-controlled, one-use CVRP cohort with six fresh synthetic uniform/clustered cases at 50, 100 and 150 customers. Candidate and baseline bytes are frozen before generation; instances and private seeds stay under the ignored sealed-release tree.
- Run the candidate and seed baseline through the same immutable network-disabled Docker image on two matched seeds per case. Consumption is recorded before the first solver call, so interruption, partial failure and concurrent requests cannot retry the cohort.
- Verify solutions through an explicit trusted instance path, bound output size and route entries, and preserve only sanitized objectives, outcomes, failures and volumes. Result bytes are hash-bound before the dashboard displays them.
- Report the full configured 14-night window, canonical scheduled IDs, missing/completed slots, attempted and successful physical calls, and generation/critique volumes. Extras, validation, zero-call work, mismatches and incomplete stages remain descriptive operational rows.
- Keep every holdout result labeled synthetic and descriptive; it cannot publish, promote, feed prompts or claim unseen public-benchmark performance.

## Matrix multiplication joins the governed night, 2026-09-14

- `night.json` gains a fixed-provider `matrix_multiplication` research slot (90 min, 12+3 units) that runs after the counterbalanced trial pair in information-gain order; night allowance is now 105 units over 540 minutes.
- `load_schedule` accepts extra research slots beyond the trial pair: problems must be unique, required trial problems present, configured providers limited to fable/astra/paired.
- `evaluation.build_manifest` supports `CONFIRMATION_ON_DEVELOPMENT`: confirmation re-runs the development targets under fresh seeds (classification `same_target_fresh_seed_replication`), and the manifest now reports `concealed` targets separately from `confirmation`.
- `matrix_multiplication.prompt_for_targets` keeps the interface contract, strategy notes and honest framing while dropping lines that name withheld targets.
- Dashboard allowance validation matches the scheduler's 130-unit ceiling, so the new 105-unit default can be saved without reducing existing slot allowances.
- The task installer prepares a 21:00 start and 9h15m scheduler limit, with the runner still stopping at 06:00. Existing Windows task registrations require separate activation; morning jobs keep their times.
- Matrix-multiplication workers receive the allowlisted exact verifier, so the incumbent and generated solvers can execute through Docker isolation.
- Matrix multiplication accepts a replicated gain on one target when no matched evaluation regresses. Other plugins retain their median gate; evidence keeps the overall median and reports target gains separately. Local incumbent advancement remains separate from publication.
- Partial research runs no longer count as successful runs in advisory scheduling history.

## Cross-problem prompt context and schedule advice, 2026-09-14

- Generation prompts now carry the repo-wide dead-ends ledger (problem-scoped, sanitized) and a ranked cross-problem pattern digest aggregated from `problems/*/patterns/` and `nightly/patterns/`; injected ids are recorded in `evidence.json` under `prompt_context`.
- Plugins declare structural `PATTERN_TAGS` used to rank transferable patterns.
- `scripts/schedule_night.py` scores governed `runs/research/*/run.json` history alongside legacy loop reports; nightly planning orders non-trial research slots by its heuristic and records the advisory allocation as `schedule_plan` in the night status, without touching the counterbalanced trial assignments.

## ARC-AGI-N local companion, 2026-09-08

- Import a bounded, content-hashed local snapshot of reviewed ARC-AGI-N catalogue records without pulling, executing upstream code, or passing upstream prose into model prompts.
- Admit only the reviewed CVRP and MIP heuristic bindings; retain other cards as visible `needs setup` records that cannot start research or create remote actions.
- Expose local catalogue review and mission ordering controls in the dashboard, while preserving existing allowance, verifier, confirmation, and publication boundaries.
- Keep the companion workbench loopback-only; document sibling checkout setup and preview its optional at-logon task before an explicit task-registration apply.

## Cross-run experiment memory, 2026-09-08

- Reject previously recorded AST-equivalent candidates before evaluation, including experiments outside the bounded prompt window.
- Preserve candidate run lineage, exclude retrospective rows from attempt statistics, and explain history window counts in evidence and prompts.
- Ask related proposals to identify a concrete mechanism change addressing earlier development failures.
- Preserve JSONL record boundaries when appending to files without a final newline.

## Subscription routing and research continuity, 2026-09-08

- Separate provider families, registered models, routing policies and formal trial identity.
- Add durable fallback, bounded retries, run-scoped availability breakers and per-attempt accounting across generation, review, retrospective and resume.
- Preserve proposals across interruptions and exclude fallback-contaminated runs from clean provider comparisons.
- Add exact candidate deduplication, bounded development-only research memory, retrospective feedback and cautious automatic model allocation.
- Expose actual models, fallback transitions and routing controls in the local dashboard and reports. Ordered routing preserves an operator's exact model chain across all roles.
- Preserve subscription authentication, isolated workers, matched-seed confirmation and explicit publication approval.

## Paper published, 2026-09-07

- The circle-packing work went live on arXiv as [2609.05093](https://arxiv.org/abs/2609.05093): *LLM-Guided Program Evolution for Circle Packing: Breaking 10 Packomania Records for $28*.
- Added an arXiv badge, a "Published result: circle packing" section and a Citation section to the README, keeping the other problem domains marked benchmark-only.
- Added `CITATION.cff` so GitHub shows a "Cite this repository" widget.
- Committed the paper source and PDF under `paper/`.

## Operator task activation, 2026-09-05

- Activated the bounded 22:00 research task, morning evidence wrappers and dashboard-at-logon task after confirmation, retaining rollback exports.
- Restarted the dashboard through Task Scheduler and verified the live allowance and deadline settings.
- Verified subscription authentication, Docker readiness, meditation script syntax and fresh/stale artifact decisions. The first full scheduled night remains separate from registration verification.

## Documentation refresh, 2026-09-05

- Rebuilt the README with workflow and stack badges, a real dashboard preview, architecture diagram, nightly resource table and guide navigation.
- Added operations and contribution guides; updated runtime contracts and subscription-accounting terminology.
- Replaced obsolete automatic-publishing instructions and marked baseline measurements and retrospectives as historical.
- Kept task activation, email availability and scientific validation limits explicit.

## Research pipeline, 2026-09-05

- Independent Fable/Astra proposals and cross-review, with explicit provider accounting.
- Run-local budgets and iteration counts, shared night allowance, crash-safe reservations and resume.
- Matched-seed replication and evidence gates instead of single-run champion selection.
- Isolated, offline solver workers and stricter scientific validation.
- Bounded nightly execution and a human research dashboard with hash-bound local approvals.
- Historical results retained as legacy observations rather than retrospectively certified discoveries.
- Subscription-only authentication and a 90-unit nightly accounting allowance.
- Explicit Git publication verifies committed bytes; research email fails closed until the separate governed sender can bind immutable attachments.
- Immutable Docker image identity across paired comparisons and resume, with host-side output caps.
- Usage-limit errors stop affected research without repeated quota retries or API fallback.
- Zero-allowance validation, bounded scheduled catch-up and automatic checkpoint resume.
- Persistent morning-review bookmarks and populated mobile dashboard layout fixes.
- Verification workflow passes on Windows and Ubuntu; real Docker and subscription probes supplement CI.
