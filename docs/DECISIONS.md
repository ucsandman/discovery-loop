# Research decisions

## 2026-09-15: Keep solver-program evolution inside the governed run

Enable solver-program islands only through the `matrix_multiplication` plugin's explicit policy. The canonical research loop keeps three run-local islands with at most three distinct, development-verified programs each. It selects one parent for mutation and, on alternating iterations where two are available, two distinct parents for crossover. Admission and ranking use only the frozen development comparison; confirmation, release checks, promotion and publication outcomes are excluded. Other plugins retain the ordinary frozen-incumbent generation path.

Use the existing provider call path for both operators. The crossover module builds a prompt from sanitized canonical loop context and verified parent source, but it does not call a provider or write the loop's candidate. For paired work, choose the island, operator and parents once, persist the rendered prompt and hashes, then give both providers those exact bytes before admitting either peer. A started call with no durable response is recorded as indeterminate on resume and is not reissued.

The population is evidence metadata over solver files already stored in the run. Resume validates its bounds, file containment and hashes, restores the original incumbent development rows, and rejects changed parents or prompts. Deterministic elite sharing moves useful programs between islands without a second database or an extra model call. These islands evolve whole solver programs; internal solver worker processes remain controlled by the existing benchmark setting.

## 2026-09-14: One-use synthetic CVRP release evidence

Keep release evidence inside the existing local dashboard and Docker isolation path. Preparation accepts only server-issued candidate IDs, freezes the selected candidate and seed baseline bytes first, then creates a fixed six-case synthetic cohort under the ignored `runs/sealed-release/` tree. One OS-locked state transition consumes the cohort before any solver starts. A crash or partial result therefore remains consumed and cannot be adapted or retried; the same candidate hash cannot be resealed.

The cohort covers uniform and clustered EUC_2D instances at 50, 100 and 150 customers with capacity 50 and integer demand 1–10. Candidate and baseline receive two identical private seeds per case with two seconds per solver. Every call uses one immutable Docker image ID with networking disabled, and a trusted verifier reads an explicit sealed instance path. Results are descriptive matched objectives and failures only. They do not establish performance on unseen public benchmarks, a world record, operational benefit, publication approval or secrecy from a malicious host.

The trial report is a coverage report before it is a comparison. Its denominator is the configured 14-night, two-track schedule. Clean rows require terminal research, a completed and eligible retro, the scheduled requested arm, and a successful physical generation call routed as requested. Dated duplicates, operational extras, validation, zero-call work, critique-only work, mismatch and fallback stay visible outside clean summaries. No report ranks models or reallocates work automatically.

## 2026-09-14: Governed slot for the matmul frontier

Promote `matrix_multiplication` into `night.json` as a fixed-provider research slot outside the counterbalanced trial: it keeps its configured provider, is ordered by the information-gain heuristic after the trial pair, and runs before pglib validation. The nightly allowance rises from 90 to 105 accounting units and the deadline from 480 to 540 minutes to fund it; trial slot allowances are untouched so the 14-night comparison stays clean.

Confirmation semantics differ from the benchmark plugins: the solver is stochastic and the incumbent already emits verified decompositions for every target, so confirmation re-runs the same development targets under fresh seeds (`CONFIRMATION_ON_DEVELOPMENT`, classification `same_target_fresh_seed_replication`). That measures repeatability, not unseen generalization, and nothing is withheld from prompts; the exact tensor-identity verifier and the incumbent gate remain the primary evidence. Matrix multiplication uses an explicit per-target Pareto gate: at least one target must improve by the minimum effect, no matched target/seed evaluation may regress, candidate evaluations must all succeed, and the required fresh seeds must complete. This lets a real improvement on one open target advance the incumbent without allowing the proven-optimal n=2 calibration to deteriorate.

Incumbent advancement remains separate from publication. The current all-target release gate cannot mark a matrix-multiplication run publishable because n=2 is already proven optimal and therefore cannot beat its record. A confirmed solver can still advance local research, but publication of an individual record-breaking target needs a separately reviewed, target-scoped release path; this change does not broaden publication.

## 2026-09-07: Route execution separately from trial assignment

Keep the historical Fable/Astra/paired arm as the scheduled experiment identity, while recording the exact configured model and provider family that executed each physical call. The registry is Fable/Opus in Anthropic and Astra/Sol in OpenAI. The default route is Fable, Opus, Astra, Sol, with requested-model then same-family then other-family fallback. Policies may restrict the route or preserve the scheduled arm; disabled families are explicit.

The routing journal is run-scoped and shared by research, review, retro, and resume. It records attempts and allowance so unavailable paths never become invisible work. A fallback, explicit routing/model override, paired degradation, or incomplete retro makes a record operationally useful but ineligible for a clean formal-trial comparison. Historical evidence without routing records remains historical and unverified.

## 2026-09-07: Compact development memory before adaptive allocation

Use exact AST deduplication and bounded, sanitized development observations to reduce repeated work and make future operational allocation auditable. Retain docstrings and changed near-similar code. Do not feed confirmation, promotion, holdout results, candidate code, or paths into prompts or allocation. Prioritize every enabled under-sampled model-role until it has three attributable development attempts; only then choose a primary automatically. Do not introduce bandits or reward optimization until the data supports them.

## 2026-09-05: Independent proposals and evidence-based promotion

Extend the existing Python loop and problem interface. Both Fable and Astra can propose independently from the same incumbent; opposite-provider critique is advisory. Matched target/seed experiments and the independent verifier decide promotion. Previously exposed benchmark instances are never described as unseen holdouts.

## 2026-09-05: Separate accounting from billing

The shared ledger reserves allowance before a provider call. Claude's reported total_cost_usd is an API-equivalent accounting estimate, not a bill against the monthly subscription. Unavailable estimates consume the configured reservation. Token usage is not converted to a fabricated dollar price. A crashed call retains its reservation on resume. The default nightly allowance is 90 accounting units; both providers must pass subscription authentication checks before generation, and API-key authentication is rejected.

## 2026-09-05: Isolated experiments and explicit publication

Generated solvers run in restricted Docker workers without network or host credentials. There is no automatic host fallback. The local research pipeline produces evidence; the human dashboard approves exact evidence and code hashes. External publication is a separate action and must revalidate those hashes and current records.

Git publication checks the immutable committed tree against the approved manifest before pushing. Research email fails closed because the existing governed sender approves mutable paths. Restoring email requires a separate sender change that snapshots and binds the body and attachments before approval.

## 2026-09-05: Internal human surface

The dashboard is a localhost-only research control surface. It is deliberately not an indexable public website; external fonts, analytics, SEO pages and account systems would add no value to this workflow.

## 2026-09-17: Opus-first routing and a family-based arm

Every Claude call runs on Opus 5 at `--effort xhigh`; Fable stays in the registry but off the default chain (`opus, astra, sol`). Opus costs half as much per token, and on 2026-09-16 eleven of twenty-four Fable generation calls hit the $2 per-call cap and returned nothing. A trial arm label (`fable`, `astra`, `paired`) names the subscription family, not one model: `arm_alias` resolves it to the first same-family alias on the configured chain, and that alias is the requested model, so a night whose Anthropic arm ran on Opus stays a clean trial row. Restoring the old behaviour is a one-line chain edit, never a code change.

## 2026-09-17: Morning brief as a second page, not a rewrite

The morning brief lives at `/morning` on the same loopback dashboard, with its own module (`morning_brief.py`) and its own HTML/JS, so the review page and its approval flow stay untouched. It reads only files the runner already writes. "Awaiting publication" is derived from history (publishable evidence without approval, approvals without a release bundle, stored beats of a public record with no submission logged); local-baseline plugins (miplib_heur, pglib_opf) are listed under incumbents and never queued, because their stored record is not a public table. A daily 07:00 task opens the page; the dashboard task keeps serving it.

## 2026-09-17: Large PGLib cases are opt-in

`problems/pglib_opf.LARGE_TARGETS` holds the seven 2,000–2,746 bus TYP cases with `LARGE_DEFAULTS` of 600 s and 2 workers. They are deliberately outside `TARGETS`: the nightly validation slot runs `TARGETS` at 60 s per case, and one PIPS solve on 2,000 buses takes about 60 s. Manual runs pass them with `--targets`; the prompt gains a large-case note when any is present. A verified 1% win on one of these is the bar for external credit (handoff note 2026-09-04) and the proof artifact for the DOE SBIR pitch in `C:\Projects\solar`.

## 2026-09-20: Prize Hunt bindings in code, prize slots opt-in, truncated collisions as proxies

Keep the prize registry and the decision to run something strictly separate. `data/prizes.json` is operator-curated intake: amounts, deadlines and "still open" sentences copied from public pages, each with a dated evidence file, each entry stamped as an untrusted quoted source. It can never make work executable. The reviewed bindings that name a plugin, a baseline, an independent verifier, the development and holdout split and the budget ceilings live in `prize_registry.PRIZE_BINDINGS`, in Python, exactly as `arc_catalogue.ADMISSIONS` does, and `validate_snapshot` re-derives every admission from that dict. Editing the JSON changes what is displayed, never what is run. Scores are computed at view time rather than stored, so the file carries only categories, verified numbers and evidence, and a rewritten score cannot outlive the evidence it came from.

Prize research is opt-in everywhere it costs anything. A default `night.json` schedules exactly what it scheduled before; a prize slot exists only when the operator adds and enables the block, and `prize_scoring.allocate` returns a plan rather than spending. The network is touched by two commands a human types: one intake fetch of one URL, and a re-check of URLs already in the registry. Nothing in the loop or the night runner fetches anything, and no code path submits, emails or claims.

The two new ladders are proxies and are labelled as such in their docstrings, prompts, READMEs and every display string. `ecc_prize` solves generated prime-field curves at 24 to 48 bits; ECCp-131 is metadata for display and for the scaling extrapolation only. `hash_collision_prize` finds collisions on salted, truncated digests at 28 to 44 bits: truncated collisions measure search machinery only, they are not partial progress toward a full collision, and the funded bounty addresses are display-only facts that are never targets. Both plugins return `beats() == False` and report release validation as unsupported, because a generated instance has no public record, so no prize claim can travel through the win gate. The honest use of the scaling fit is to show the size of the remaining gap: at the measured exponent the real instances need a change of economics, not tuning.
