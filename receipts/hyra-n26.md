# Full-precision sum of radii 2.6359830951068446 for 26 circles in the unit square (sum_s_full in cirRsqu_n26.json)

Claim Notary receipt, issued 2026-11-26. Claimed by Tencent Hunyuan, Hyra (AI4Science packing_records) ([source](https://github.com/Tencent-Hunyuan/Hyra-results/blob/main/AI4Science/packing_records/records/cirRsqu_n26.json)).

> **Does not hold.** At least one check failed. The failed checks are listed below.

## The claim

| | |
| --- | --- |
| Circles | 26 |
| Claimed sum of radii | 2.6359830951068446 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | fail | Both verifiers reject the packing: a circle crosses the square's edge by 7.380e-10 and two circles overlap (squared distance short by 4.878e-10), about 73,802 times what rounding to the printed digits can cause (allowance 1e-14). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.6359830951068446, recomputed 2.63598309510684482, difference 2.200e-16. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.63598309510684482` |
| Smallest gap to a wall | -7.380e-10 |
| Smallest squared gap between two circles (negative means overlap) | -4.878e-10 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 26 circles, 325 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/hyra-n26.receipt.json claims/hyra-n26/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `5ada06b30eaee4040e921f3ea6914a3ac6094d6b32a10ea496204f625f29e4b9` |
| Claim card | `173f65853cd3f9d2ccc98b30cbf290c5346678f68ff1d4e13177220aa48b765e` |
| File `cirRsqu_n26.json` | `c16d2472e9516005195cef7f1f0ed4e7c2e709544bcba5dfcbe52bc3d26ff50e` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
