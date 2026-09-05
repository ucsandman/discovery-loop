# Research decisions

## 2026-09-05: Independent proposals and evidence-based promotion

Extend the existing Python loop and problem interface. Both Fable and Astra can propose independently from the same incumbent; opposite-provider critique is advisory. Matched target/seed experiments and the independent verifier decide promotion. Previously exposed benchmark instances are never described as unseen holdouts.

## 2026-09-05: Separate accounting from billing

The shared ledger reserves allowance before a provider call. Claude's reported total_cost_usd is an API-equivalent accounting estimate, not a bill against the monthly subscription. Unavailable estimates consume the configured reservation. Token usage is not converted to a fabricated dollar price. A crashed call retains its reservation on resume. The default nightly allowance is 90 accounting units; both providers must pass subscription authentication checks before generation, and API-key authentication is rejected.

## 2026-09-05: Isolated experiments and explicit publication

Generated solvers run in restricted Docker workers without network or host credentials. There is no automatic host fallback. The local research pipeline produces evidence; the human dashboard approves exact evidence and code hashes. External publication is a separate action and must revalidate those hashes and current records.

Git publication checks the immutable committed tree against the approved manifest before pushing. Research email fails closed because the existing governed sender approves mutable paths. Restoring email requires a separate sender change that snapshots and binds the body and attachments before approval.

## 2026-09-05: Internal human surface

The dashboard is a localhost-only research control surface. It is deliberately not an indexable public website; external fonts, analytics, SEO pages and account systems would add no value to this workflow.
