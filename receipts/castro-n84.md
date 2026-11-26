# N=84: 4.816500878221, published on Packomania and credited (README table; file discoveries/2026-09-23-00-csqv-84/csqv84.pck)

Claim Notary receipt, issued 2026-11-26. Claimed by Arnold Castro (C++ solver written by Claude Code, human-directed) ([source](https://github.com/arnoldcastro5000/csqv-circle-packing)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 84 |
| Claimed sum of radii | 4.816500878221 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 4.816500878221, recomputed 4.816500878221172, difference 1.720e-13. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `4.816500878221172` |
| Smallest gap to a wall | 4.210e-12 |
| Smallest squared gap between two circles (negative means overlap) | 4.744e-13 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 84 circles, 3486 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/castro-n84.receipt.json claims/castro-n84/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `02a51e42bd6200f54fc5b8caa5068c6043be030adf71e4dc7cd152a4b3cad2b6` |
| Claim card | `75ff72c9dfe0394dae0cfd7a904c00df1d7d572fdfc03f045e57c956029e48d5` |
| File `csqv84.pck` | `5c7a6bef362b4c1b2b43e4c3f8fae631cbd76e618562914b39e95477fba8d68b` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
