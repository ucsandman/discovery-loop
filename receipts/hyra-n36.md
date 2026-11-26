# Full-precision sum of radii 3.1217544985781105 for 36 circles in the unit square (sum_s_full in cirRsqu_n36.json)

Claim Notary receipt, issued 2026-11-26. Claimed by Tencent Hunyuan, Hyra (AI4Science packing_records) ([source](https://github.com/Tencent-Hunyuan/Hyra-results/blob/main/AI4Science/packing_records/records/cirRsqu_n36.json)).

> **Does not hold.** At least one check failed. The failed checks are listed below.

## The claim

| | |
| --- | --- |
| Circles | 36 |
| Claimed sum of radii | 3.1217544985781105 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | fail | Both verifiers reject the packing: a circle crosses the square's edge by 6.141e-10 and two circles overlap (squared distance short by 3.736e-10), about 614,097 times what rounding to the printed digits can cause (allowance 1e-15). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 3.1217544985781105, recomputed 3.12175449857811012, difference 3.800e-16. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `3.12175449857811012` |
| Smallest gap to a wall | -6.141e-10 |
| Smallest squared gap between two circles (negative means overlap) | -3.736e-10 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 36 circles, 630 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/hyra-n36.receipt.json claims/hyra-n36/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `0e7b137d2e88b14b6dc18cbbffa14a00c445c51ff8291b71a1421ecfa7a5ed7c` |
| Claim card | `d82a7a7b24e62bca3ff35bdceae98b3416924d9a122e2fea162f32cadd0a3921` |
| File `cirRsqu_n36.json` | `86c7c082b949f71b92fcdceb2f4b9553b092455fa52ffcaf60edbffab9af38fc` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
