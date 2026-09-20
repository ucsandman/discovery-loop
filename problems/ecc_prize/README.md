# ecc_prize — elliptic-curve discrete logarithm ladder

Authorized ECDLP research on a reproducible ladder of generated prime-field curves. The ladder has the
same shape as the Certicom ECCp-131 challenge instance (`y² = x³ + ax + b` over `F_p`, prime order `n`,
cofactor 1) at sizes this lab can finish, so the machinery — walk design, field arithmetic, batching,
distinguished-point rate — can be measured at several field sizes and the scaling read off.

**ECCp-131 is metadata only.** It lives in `problem.PRIZE_TARGET_METADATA` for display and for the
scaling extrapolation. It is never a target, nothing is submitted anywhere, and a ladder result is a
measurement of search machinery, not partial progress on a 131-bit instance.

## The ladder

| set | targets |
| --- | --- |
| development (`TARGETS`) | `ecdlp-p24-dev`, `ecdlp-p28-dev`, `ecdlp-p32-dev`, `ecdlp-p36-dev` |
| holdout (`VALIDATION`, hidden from prompts) | `ecdlp-p28-hold`, `ecdlp-p32-hold`, `ecdlp-p36-hold`, `ecdlp-p40-hold` |
| large (opt-in via `--targets`) | `ecdlp-p44-large`, `ecdlp-p48-large` |

Every instance is reproducible from its name: `curves.make_instance(bits, tag)` seeds a counter-mode
sha256 stream with `sha256("ecc_prize:<bits>:<tag>")`, draws a prime `p ≡ 3 (mod 4)` of exactly `bits`
bits, then draws `a, b` until the curve is non-singular and its order — found by baby-step giant-step
over the Hasse interval, `O(p^¼)` point operations — is prime. A prime order gives cofactor 1 and makes
the generator's order equal to the group order.

`records.json` holds **public data only**: `p, a, b, n, P, Q` plus a `reference` block with
`expected_iterations = sqrt(pi*n/2)` and `baseline_seconds` (the seed solver's median over three seeds
on the authoring machine). The discrete logarithm is stored nowhere — the checker only needs to
recompute `k·P` and compare it with `Q`.

## Files

| file | role |
| --- | --- |
| `curves.py` | deterministic generation + baseline measurement; **not** staged into the worker |
| `records.json` | the committed ladder (public instance data + references) |
| `records.py` | reads `records.json`; staged into the worker |
| `verify.py` | the independent checker; staged into the worker; imports nothing from any solver |
| `seed_solver.py` | the trusted baseline: parallel Pollard rho, batched affine additions |
| `problem.py` | the plugin contract (scoring, prompts, `PRIZE` descriptor, `LIMITATIONS`) |

## Regenerating the ladder

```
python problems/ecc_prize/curves.py --write --no-measure
python problems/ecc_prize/curves.py --measure --seeds 3 --time 60 --targets ecdlp-p24-dev,...,ecdlp-p40-hold
python problems/ecc_prize/curves.py --measure --seeds 3 --time 130 --targets ecdlp-p44-large,ecdlp-p48-large
```

Regenerating changes every instance and therefore every baseline; commit `records.json` in the same
change or existing evidence stops being comparable.

## Scoring, and its weak spot

The value of a run is the wall time to a **verified** discrete logarithm (lower is better). Verification
is independent; the timing is not — the value is the worker's own `elapsed` field, accepted only after
`verify.check` passes and clamped to `[1e-4, 105]` seconds so a tampered stopwatch cannot manufacture a
score. The loop's per-row `secs` is the trusted clock and is recorded beside it in `evidence.json`. The
full list is `problem.LIMITATIONS`.

`beats()` is always `False` and `validate_release` reports `supported: False`: these curves are
generated here, so there is no public record and no prize claim can be routed through the win gate.
