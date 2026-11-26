# Full-precision sum of radii 2.9872850198249474 for 33 circles in the unit square (sum_s_full in cirRsqu_n33.json)

Claim Notary receipt, issued 2026-11-26. Claimed by Tencent Hunyuan, Hyra (AI4Science packing_records) ([source](https://github.com/Tencent-Hunyuan/Hyra-results/blob/main/AI4Science/packing_records/records/cirRsqu_n33.json)).

> **Does not hold.** At least one check failed. The failed checks are listed below.

## The claim

| | |
| --- | --- |
| Circles | 33 |
| Claimed sum of radii | 2.9872850198249474 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | fail | Both verifiers reject the packing: a circle crosses the square's edge by 7.667e-10 and two circles overlap (squared distance short by 3.756e-10), about 76,674 times what rounding to the printed digits can cause (allowance 1e-14). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.9872850198249474, recomputed 2.987285019824947726, difference 3.260e-16. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.987285019824947726` |
| Smallest gap to a wall | -7.667e-10 |
| Smallest squared gap between two circles (negative means overlap) | -3.756e-10 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 33 circles, 528 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/hyra-n33.receipt.json claims/hyra-n33/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `45d349158d7b138e27928adbfc5bd6ec4827db5d819cb9f2b976d89c06bda2ee` |
| Claim card | `a1e8848a30ba98d6406278dd3926457831f3be45ef9cb7124d5c9ab5e8811ef2` |
| File `cirRsqu_n33.json` | `eceb3e35987456541751fab807d6018354d15a1a412735a7b439e43d084f1f3c` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
