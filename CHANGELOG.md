# Changelog

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
