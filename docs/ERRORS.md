# Errors and lessons

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
