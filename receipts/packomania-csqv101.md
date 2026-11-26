# Packomania lists a packing of 101 unequal circles in the unit square with sum of radii 5.291939042347

Claim Notary receipt, issued 2026-11-26. Claimed by Packomania csqv list (fetched 2026-11-26) ([source](https://www.packomania.com/csqv/csqv.html)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 101 |
| Claimed sum of radii | 5.291939042347 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square, by both verifiers. The smallest gaps are slightly negative, within what rounding to 12 printed decimals can cause (tolerance 1e-11). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.291939042347, recomputed 5.291939042347, difference 0.000e+00 (allowed 1.000e-09: 1e-9, or half a unit in the claim's last printed digit if larger). |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.291939042347` |
| Smallest gap to a wall | 0.000e+00 |
| Smallest squared gap between two circles (negative means overlap) | -3.363e-13 |
| Tolerance, from the file's 12 printed decimals | 1e-11 |
| Work done | 101 circles, 5050 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/packomania-csqv101.receipt.json claims/packomania-csqv101/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `27a17c51baa4724c31ead1a99d37220112696d3fe972b67565c38b03e4fabe4a` |
| Claim card | `b767fe58c73dcd7f7a16fb3da00a7f2bcd1281a9073d430e739ba29cea502100` |
| File `csqv101.txt` | `9ed17c6d850ac61e68ee48630ee6da49bda605faff98e3522199ea6a93997573` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `e25edf565346f084807c84d06afdd7e642d6a53c0c1ca45de9b0eee19fc1bffe` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
