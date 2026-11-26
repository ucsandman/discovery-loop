# Packomania lists a packing of 109 unequal circles in the unit square with sum of radii 5.507925934200

Claim Notary receipt, issued 2026-11-26. Claimed by Packomania csqv list (fetched 2026-11-26) ([source](https://www.packomania.com/csqv/csqv.html)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 109 |
| Claimed sum of radii | 5.507925934200 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square, by both verifiers. The smallest gaps are slightly negative, within what rounding to 12 printed decimals can cause (tolerance 1e-11). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.507925934200, recomputed 5.5079259342, difference 0.000e+00. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.5079259342` |
| Smallest gap to a wall | 0.000e+00 |
| Smallest squared gap between two circles (negative means overlap) | -2.928e-13 |
| Tolerance, from the file's 12 printed decimals | 1e-11 |
| Work done | 109 circles, 5886 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/packomania-csqv109.receipt.json claims/packomania-csqv109/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `9b4c7a2148b364dcc5108306deeebf6b07c0e6fcac112f42dedf10f75abb334a` |
| Claim card | `1acb4156a60e8002d16a5faab65c409856928fc506814013616fd9ae8320a82a` |
| File `csqv109.txt` | `795dde11a228614e417198a148d722b15c1f6db5ac3cec9186f9a2b4a3cb88d2` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
