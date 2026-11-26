# Claim Notary

The Claim Notary re-checks an optimization result that someone else claims, and returns a receipt anyone can re-run.
It is the first piece of the Discovery Loop and Practical Systems combination chosen on 2026-11-26: AI makes claims
cheap, and maintainers and benchmark keepers now spend their time checking them. Phase 1 checks circle-packing claims
(Packomania csqv) only, and only data. No program from outside runs on this machine.

The pass/fail numbers were fixed before any check ran, in [notary-prereg.md](notary-prereg.md) (commit `7336406`).

## Use

```powershell
python notary.py check runs/notary/day3/packomania-csqv106.card.json --out runs/notary/day3
python notary.py verify-receipt runs/notary/day3/packomania-csqv106.receipt.json runs/notary/day3/packomania-csqv106.card.json
python scripts/notary_planted.py                 # the planted-cheat gate
python scripts/notary_planted.py --break both    # the same gate with both verifiers broken: must go red
```

`check` writes `<claim_id>.receipt.json` and a self-contained `<claim_id>.receipt.html`, and exits 0 only when the
claim holds. `verify-receipt` re-runs every check from the claim card and lists every field that differs.

## Claim card

A JSON file beside the artifact it names. Unknown fields are rejected, so a claimant cannot add a tolerance or any
other rule.

| Field | Meaning |
| --- | --- |
| `schema` | `claim-card-v1` |
| `claim_id` | 1-80 letters, digits, dots, dashes, underscores; names the receipt files |
| `problem` | `circle_packing`; anything else gets `cannot_check` |
| `claimant`, `statement` | Who claims what, in plain words |
| `source_url` | Optional, `https://` only |
| `artifact` | `{path, format, sha256?}`: a file inside the card's folder, format `pck` (ours) or `packomania_txt` |
| `n` | Number of circles |
| `claimed_sum` | The claimed sum of radii, as a decimal string |
| `reference` | Optional `{value, source}`: the value the claim says it beats |
| `claimed_gain_pct` | Optional, needs `reference`: the claimed gain in percent |

## Rules

1. Two verifiers that share no code: `problems/circle_packing/verify.py` (floats) and `notary_exact.py` (exact
   integer arithmetic on the printed decimals). If they disagree, the verdict is `insufficient_spec`.
2. Tolerance comes from the file's printed precision only: `10^-(d-1)` for `d` decimals, on the minimum wall slack and
   the minimum squared pair slack. Packomania prints 12 decimals (tolerance `1e-11`); our `.pck` files print 16
   (`1e-15`).
3. A claimed sum agrees within `1e-9`; a claimed gain within `0.01` percentage points.
4. Hashes are SHA-256 of text with line endings normalised to LF, so a receipt re-derives on every OS.
5. A receipt binds the claim card, the artifact and the source of all three programs. Changing any of them, or any
   field of the receipt, makes `verify-receipt` fail.
6. A receipt is not a benefit. Nothing here sends, posts or publishes anything.

## First proof, days 0 to 3 (2026-11-26)

| Gate | Result |
| --- | --- |
| Day 0: preregistration committed before any check | `7336406`, sha256 `09966a3b...02743` |
| Day 2: planted cheats | `planted=10 caught=10; tampered=5 caught=5; honest=1 held=1` |
| Day 2: the gate goes red when the verifiers are broken | `--break both`: 3 planted cheats and the re-hashed forged verdict pass, `GATE FAIL`. With one verifier broken, every cheat is still caught as `insufficient_spec` |
| Day 3: agreement with the keeper | Packomania N=101, 106, 109: recomputed sums equal the published sums (difference 0); our N=106 and 109 files match the list to 1.2e-12 and 4.2e-12 |

A finding from day 3: Packomania's published 12-decimal files overlap by up to about `3e-13` in squared distance,
which rounding to 12 decimals causes. A zero-tolerance checker would wrongly reject the keeper's own files. Our
16-decimal files have strictly positive gaps.

## Deviation from the preregistration

The preregistration lets a file's printed precision set its tolerance, which would let a claimant print few decimals
to get a loose tolerance. The notary therefore also requires at least 10 printed decimals and returns
`insufficient_spec` below that (planted case `low_precision`). This is stricter than the preregistered rule, not
looser.
