# Full-precision sum of radii 3.0740363770828374 for 35 circles in the unit square (sum_s_full in cirRsqu_n35.json)

Claim Notary receipt, issued 2026-11-26. Claimed by Tencent Hunyuan, Hyra (AI4Science packing_records) ([source](https://github.com/Tencent-Hunyuan/Hyra-results/blob/main/AI4Science/packing_records/records/cirRsqu_n35.json)).

> **Does not hold.** At least one check failed. The failed checks are listed below.

## The claim

| | |
| --- | --- |
| Circles | 35 |
| Claimed sum of radii | 3.0740363770828374 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | fail | Both verifiers reject the packing: a circle crosses the square's edge by 7.350e-10 and two circles overlap (squared distance short by 3.940e-10), about 73,500 times what rounding to the printed digits can cause (allowance 1e-14). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 3.0740363770828374, recomputed 3.07403637708283705, difference 3.500e-16. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `3.07403637708283705` |
| Smallest gap to a wall | -7.350e-10 |
| Smallest squared gap between two circles (negative means overlap) | -3.940e-10 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 35 circles, 595 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/hyra-n35.receipt.json claims/hyra-n35/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `c0b196455ff7c422a5ddd22e6723d6851821b38387104f1addab7b217e706176` |
| Claim card | `6299916e689102c5f14974a2b2b361eba1dd5dc1a3f22b4f29674c0d68644519` |
| File `cirRsqu_n35.json` | `3c12493fffefacc975630465d194592c1da407953047896c6d680c90940c312d` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
