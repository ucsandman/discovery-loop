# Full-precision sum of radii 3.0297992386878443 for 34 circles in the unit square (sum_s_full in cirRsqu_n34.json)

Claim Notary receipt, issued 2026-11-26. Claimed by Tencent Hunyuan, Hyra (AI4Science packing_records) ([source](https://github.com/Tencent-Hunyuan/Hyra-results/blob/main/AI4Science/packing_records/records/cirRsqu_n34.json)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 34 |
| Claimed sum of radii | 3.0297992386878443 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square, by both verifiers. The smallest gaps are slightly negative, within what rounding to 15 printed decimals can cause (tolerance 1e-14). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 3.0297992386878443, recomputed 3.02979923868784447, difference 1.700e-16. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `3.02979923868784447` |
| Smallest gap to a wall | 1.300e-09 |
| Smallest squared gap between two circles (negative means overlap) | -1.591e-16 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 34 circles, 561 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/hyra-n34.receipt.json claims/hyra-n34/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `9bf12b74c735924219b78530d8c5bf34eec63e653e44e6fe76bdcc8ddba27ca3` |
| Claim card | `d64eef9f975e21799981374c087f5f9e0c178f15cd51ada2baf33fcbf160b3f5` |
| File `cirRsqu_n34.json` | `cacb213366878a3b59521e28406023c5e497d2459aac4304b8fe272784e78a8d` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
