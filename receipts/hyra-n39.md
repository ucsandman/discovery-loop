# Full-precision sum of radii 3.2481108110444517 for 39 circles in the unit square (sum_s_full in cirRsqu_n39.json)

Claim Notary receipt, issued 2026-11-26. Claimed by Tencent Hunyuan, Hyra (AI4Science packing_records) ([source](https://github.com/Tencent-Hunyuan/Hyra-results/blob/main/AI4Science/packing_records/records/cirRsqu_n39.json)).

> **Does not hold.** At least one check failed. The failed checks are listed below.

## The claim

| | |
| --- | --- |
| Circles | 39 |
| Claimed sum of radii | 3.2481108110444517 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | fail | Both verifiers reject the packing: a circle crosses the square's edge by 7.575e-10 and two circles overlap (squared distance short by 3.714e-10), about 75,755 times what rounding to the printed digits can cause (allowance 1e-14). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 3.2481108110444517, recomputed 3.24811081104445174, difference 4.000e-17. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `3.24811081104445174` |
| Smallest gap to a wall | -7.575e-10 |
| Smallest squared gap between two circles (negative means overlap) | -3.714e-10 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 39 circles, 741 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/hyra-n39.receipt.json claims/hyra-n39/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `571895296b94bf43058a7ef313a5df0ff4bca5bb751ba72c6f5281d8dee37fe4` |
| Claim card | `cae5d8de5bc5725e0f13778010f58431f3225a6d11543ee35a8ba6adbd70755a` |
| File `cirRsqu_n39.json` | `742ea5f23b9b4e570b811a7ee12a3ad72b53c61ba768f15fda3cad1f55de59cd` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
