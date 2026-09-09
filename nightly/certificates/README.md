# Result certificates

Every promoted champion gets a machine-readable certificate here:
`nightly/certificates/<date>-seed<seed>-n<target>.json`.

## What a certificate says

- **What was checked**: the exact tensor identity over integers, plus the
  verifier's own self-test (known-good passes, known-bad fails) from the
  same run.
- **Hash binding**: the solver output's sha256, the factors' content hash,
  and the verifier input hash are all recorded. The verifier reads the
  solver's output file directly, so the chain is explicit: a certificate
  cannot be attached to bytes the verifier never saw.
- **Verifier identity**: sha256 of `verify.py` at promotion time. A
  weakened verifier is detectable.

## What a certificate does NOT say

Four fields default to `false` and flip only when the real event happens
(use `certificate.mark_certificate`):

| field | flips true when |
|---|---|
| `independently_verified` | a second, independent implementation confirms the identity |
| `externally_reviewed` | a domain expert (e.g. Specht for packings) checks it |
| `novelty_reviewed` | literature/prior-art search is done and recorded |
| `published` | the result is actually published somewhere |

## Publish checklist (verification boundary)

Any public claim built on a certificate must state, in words:

1. **Checked**: exact tensor identity over integers; verifier self-test
   green on this run (cite the certificate file).
2. **Not checked**: optimality/lower bounds, novelty vs literature,
   human review — unless the corresponding certificate field is true.
3. **Reproduce**: run `nightly/verifier_selftest.py`, then re-verify the
   champion with `problems/matrix_multiplication/verify.py`.

Pattern stolen from the Ouroboros loop (cjc0013/erdos-matrix-asymptotics):
limitations as machine-readable data, not prose caveats.
