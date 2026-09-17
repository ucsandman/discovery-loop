# Errors and lessons

## 2026-09-15: Freeze the complete island iteration across a crash

Review found that restoring parent hashes alone could still rebuild a paired prompt from changed development history, repeat a call whose response was lost, or compare persisted fitness against a newly evaluated incumbent. The repaired path freezes the full prompt and development baseline, records a call as started before execution, and validates run-scoped files on resume. Future population changes must exercise interruption between paired calls and resume after the incumbent has been evicted from the breeding population. Synthetic regressions and a real 15-evaluation Docker probe verified these boundaries without live provider calls.

## 2026-09-14: A sealed label needs executable and display-time integrity

The first evaluator draft passed a monotonic-clock deadline into an isolation API that expects epoch time, which made every real worker immediately expired. It also relied on the mutable worker tag even though candidate and baseline comparisons must share one environment. The evaluator now resolves one immutable image ID before consumption, records it, passes it to every call, and uses epoch deadlines end to end. A regression requires every runner deadline to be in the future relative to `time.time()`.

An untrusted solver could also return a million repeated route entries. The trusted verifier's duplicate scan was quadratic, allowing host-side verification to exceed the evaluation deadline after Docker exited. It now rejects route counts and total customer entries above the trusted instance size before distance work and uses a linear counter for duplicates.

Finally, a completed manifest could display edited or missing `result.json` bytes. Dashboard reads now require a regular non-symlink result whose SHA-256, cohort ID, schema and final state match the sealed manifest. Tampered or missing results display as invalid and are never surfaced as completed evidence. The prevention tests cover deadline basis, immutable image reuse, million-entry output, result tamper and missing results.

A disposable real-Docker proof then completed all 24 planned solver runs and all 12 matched pairs with zero failures, using one immutable worker image. Identical frozen seed solvers produced 12 equality outcomes, correctly labeled no improvement, and a second evaluation request was rejected as consumed. This proves the bounded execution and one-use mechanism; it is not scientific evidence for a candidate.

## 2026-09-14: Nightly allowance exceeded dashboard validation

The matrix-multiplication slot raised the default allowance to 105 units while the dashboard form and API still capped it at 90. Saving the unchanged schedule failed despite the scheduler accepting it. Aligning both dashboard limits with the scheduler's 130-unit ceiling restores settings saves. Schedule changes now receive an unchanged-default save check through the human control surface as well as the runner's dry run.

The same review found that a 540-minute plan was still constrained by a 22:00 task start and the runner's 06:00 cutoff. The prepared installer now starts at 21:00 with a 9h15m task limit, preserving the morning jobs. Verification covers the catch-up boundary and actual installer values; existing task activation remains separate from code delivery. Historical activation evidence retains the values actually checked at that time.

A real worker probe rejected `matrix_multiplication` before execution because the Docker input allowlist omitted the plugin. Adding its trusted `verify.py` helper enables the existing worker path without mounting other repository files. New governed slots receive one real isolated incumbent evaluation before their schedule is considered runnable.

The default median across all three matrix sizes also rejected a single-target improvement when the other sizes tied. Matrix multiplication now opts into a target-aware gate requiring a replicated improvement and no matched-case regressions. Synthetic tests cover both acceptance and rejection, and keep local promotion distinct from the existing all-target release gate. Future plugin admission checks include an achievable improvement case and a regression case, alongside real worker execution.

The incremental commit hook omitted callers in unstaged files and flagged the worker mount test helper, dynamic pattern tags, and plugin capability marker. Their callers were verified before adding these names to the existing Vulture whitelist; the hook remains enabled.

## 2026-09-08: Real catalogue and scheduler probes caught fixture-shaped assumptions

The first ARC import rejected a valid 40-character Git commit because its validator incorrectly reused the 64-character SHA-256 pattern. Splitting Git object validation from content-hash validation fixed the real import. The same review found that a cached snapshot could have been edited after validation and that its normalized hash changed with every import timestamp. Cache loads now recompute a timestamp-independent normalized hash, compare executable admissions to the local reviewed bindings, and retain a raw hash over every source byte. The live checkout also records `worktree_dirty` because its two integration cards were local additions beyond the cited commit.

A completed manual `2026-09-08` checkpoint would also have caused the installed scheduled task to return without running. Canonical scheduled checkpoints now use `2026-09-08-scheduled` and record the logical date separately. Finally, the browser exposed two misleading readings: UTC timestamps rendered as the prior local day and absent per-slot usage fields rendered as zero. The dashboard now uses the logical run date, the night ledger total, and explicit “not reported” text. The prevention change is one real source import, one real scheduled-state comparison, and one populated browser read before accepting fixture-only checks.

Follow-up review found two namespace and resume gaps. An explicit `--scheduled --run-id YYYY-MM-DD` still reused an existing unsuffixed manual checkpoint, and a paused run retained its old disabled-slot list even after the operator disabled a pending mission. Scheduled invocations now normalize every date argument before checkpoint lookup and use idempotent create-or-resume behavior in the scheduled namespace. Resume rechecks current mission control for pending slots while leaving the checkpoint's original catalogue and mission provenance unchanged.

## 2026-09-08: Cross-night memory dropped old exact candidates and counted retrospectives as attempts

The proposal prompt used only the last 80 JSONL rows, while duplicate detection knew only the current run. An old candidate could therefore be proposed and evaluated again, and the retrospective row appended to each problem history inflated attempt and family counts. The runner now scans every recorded candidate fingerprint for exact AST duplicate detection, keeps the existing 80-candidate aggregate window and 20-candidate prompt window, excludes retrospective rows, and records those scopes explicitly. New observations retain their run ID. Related algorithm families remain available when a proposal names a concrete changed mechanism and why it addresses the prior failure. A regression fixture also exposed that appending to a valid JSON object without a trailing newline could concatenate the next event; the locked append helper now inserts the missing separator.

## 2026-09-08: Fixed routing must survive the operator interface

A requested Astra, Sol, Opus sequence could not be represented faithfully by adaptive or role-based routing. Added an ordered policy and tested all three research roles. A real CLI dry-run then exposed parsed overrides being validated without installing them into the runtime configuration; the corrected assignment now has a CLI regression. Future routing changes must verify the effective dry-run configuration as well as the routing helper.

## 2026-09-07: Two provider labels hid the executed route

The prior documentation and evidence vocabulary reduced execution to Fable and Astra even though subscription availability can differ by model and family. The routing registry now records requested arm, actual model/family, physical attempts, fallback reason, and allowance in a run-scoped journal shared with retro and resume. A real routed request classified Fable's explicit usage-exhaustion response, then completed through Opus; the corrected provider pattern recognizes that wording while preserving the earlier journal's original infrastructure-error classification. Reports separate historical unverified rows from clean and operationally degraded routed rows.

## 2026-09-07: Integration interruptions exposed missing routing and memory distinctions

The paired-generation crash and evaluation-validity regression stopped the final integration pass until their core paths were corrected. Development-memory integration also initially conflated algorithmic idea families with provider-family provenance and allowed mature selection before all enabled choices reached the minimum sample count. The repaired path keeps those fields separate, prioritizes every under-sampled enabled model-role through three attributable development attempts, and excludes promotion and holdout data from those statistics. Final verification ran only after those interruptions were resolved.

## 2026-09-05: Baseline and implementation review

- Lifetime spend and iteration counters were reused as invocation limits. Separate historical totals from each run's allowance and preserve the shared ledger only when explicitly resuming that run.
- A power-grid solver optimized numerical tolerance rather than the original physical constraints. Record feasibility residuals against original inputs and require stricter release validation; do not promote tolerance-sensitive gains as scientific discoveries.
- Bare problem helper imports contaminated a combined test run (20 passed, 8 failed). Give each plugin an independent import namespace.
- The command wrapper summarized a collection error as 'No tests collected'. Read raw output and require a positive collected-test count; set pytest's root import path explicitly.
- The first allowance description treated CLI estimates as API bills. Subscription authentication is now enforced, the allowance is doubled to 90, and every surface labels API-equivalent estimates separately from subscription billing.
- Review found evidence parsed from one read and approved using another read's hash. Parse and hash the same byte snapshot, then bind the candidate and every artifact.
- A shared checkout can change release files between approval and commit. Require the exact approved file set and hashes from the immutable commit before pushing; unrelated staged files remain excluded.
- Windows newline translation broke the new exact-byte manifest test. Atomic JSON uses explicit LF, and release artifacts disable Git text conversion so approvals survive cross-platform storage.
- The governed sender approves paths but reads body and attachments after approval. Research email now fails closed before creating an action; restoring it requires immutable snapshots in the sender rather than a local filename convention.
- Clean-clone verification exposed a publisher log directory assumption masked by local run history. The compatibility helper now creates its log directory and closes the parent log handle.
- A real night rejected validation-only work with zero model allowance. Zero is now valid when no generation is requested; a real worker evaluation verified the fix.
- Subscription limits must stop work, not burn the remaining allowance on repeated rejections. Provider-limit errors are sanitized and stop the affected research invocation without API fallback.
- A mutable Docker tag could change the worker between paired evaluations. Each experiment now resolves and records an immutable image ID and uses it throughout the comparison and resume.
- The mobile empty state fit, but real evidence expanded the grid to 622px on a 390px screen. Zero-minimum grid tracks and children now contain the table scroll area; populated mobile rendering measured 390px with no page overflow.
- The release hook identified obsolete runner code and dynamically dispatched HTTP/pytest names. Removed the obsolete runner and unused send options; the existing whitelist now names only verified dynamic entry points. Existing test assertions were preserved.
- A review button originally saved a request with no worker consuming it. It now explicitly marks a human-review bookmark, shows that state persistently, and includes the selected problem in the morning report without implying an extra model run.
- Linux CI has no Claude executable. An eager executable check bypassed the existing subprocess timeout regression and changed its reported failure. Missing-executable handling now occurs at the subprocess boundary on every platform; CI runs both OS jobs independently so one failure does not hide the other result.

## 2026-09-05: Documentation refresh

The main README reflected the new pipeline, but older slot proposals and baseline footers still instructed automatic publishing. Centralized current procedures in the operations guide, replaced obsolete instructions with links, and labeled preserved measurements as historical. Future behavior changes must search historical guide introductions and operational footers as well as the README.

Live GitHub rendering loaded the diagram only after it entered the viewport and exposed unreadably small horizontal labels. Changed the flow to vertical and verified the rendered diagram, not just the Markdown source. The repository About description was also updated to remove its obsolete automatic-publication claim.

## 2026-09-05: Task activation

Preview and live task state were kept separate until operator authorization. Applied the exported plan, read back all four registrations, and restarted the dashboard through the task rather than leaving an old process serving imported code. An overly strict compound process check stopped the initial restart without killing anything; re-read the exact PID and command line before retrying. Future activation checks must include the running listener, effective UI values and both positive and negative freshness cases, not just a successful installer exit.

## 2026-09-17: Opus routing and morning brief

- `DISABLE_PROMPT_CACHING=1` in the `claude -p` environment does nothing on CLI 2.1.274: a warm identical prefix read 11,596 cached tokens with and without it (three-call probe). Removed before shipping; do not re-add without a probe that shows `cache_read_input_tokens` dropping to 0.
- The long-lived `discovery-loop-dashboard` task kept serving the old code after `dashboard.py` changed; `/api/morning` returned 404 until the old `pythonw` process was killed and the task started again. `schtasks /Run` from Git Bash mangles `/Run` into a path; use PowerShell `Start-ScheduledTask`.
- Removing `fable` from the default chain made `fable_only` select nothing, which surfaced as `provider_unavailable` in loop tests that use the legacy callback path. Single-arm policies now resolve through `arm_alias` like every other route.
- `scripts/resume_killed.py` carried an unused import that failed Ruff in `check.py` before this session touched it; fixed in passing.
