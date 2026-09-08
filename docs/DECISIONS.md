# Research decisions

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
