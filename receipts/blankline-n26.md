# sum of radii 2.635917599028, max violation 2.776e-17, valid at 1e-9 (README); explicitly not a record

Claim Notary receipt, issued 2026-11-26. Claimed by blankline-org (frozen LLM with an external memory loop) ([source](https://github.com/blankline-org/extrapolation-n26)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 26 |
| Claimed sum of radii | 2.635917599028 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square, by both verifiers. The smallest gaps are slightly negative, within what rounding to 14 printed decimals can cause (tolerance 1e-13). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.635917599028, recomputed 2.63591759902818436, difference 1.844e-13. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.63591759902818436` |
| Smallest gap to a wall | -4.000e-17 |
| Smallest squared gap between two circles (negative means overlap) | -2.237e-17 |
| Tolerance, from the file's 14 printed decimals | 1e-13 |
| Work done | 26 circles, 325 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/blankline-n26.receipt.json claims/blankline-n26/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `0e615392af3a6cf2ba807e09a1dbb374190df99aafed12985f2c103ab3c6d727` |
| Claim card | `fcb47cbe453c7a86d8d95bab135231923d0c0ac10d8b78ba466b848372c03a7a` |
| File `gen3b-best.json` | `88937e4b6e0eb96f673937fec2f4861406890933f005ff9af188a49a4baf720b` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
