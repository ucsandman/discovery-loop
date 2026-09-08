# Changelog

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
