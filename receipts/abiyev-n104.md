# N=104: 5.312597, one of 11 configurations accepted into the database (README; file results/csqv104.pck)

Claim Notary receipt, issued 2026-11-26. Claimed by Rasim Abiyev (SLSQP and basin hopping, code written by Claude) ([source](https://github.com/RasimAbiyev/circle-packing-explorations)).

> **Does not hold.** At least one check failed. The failed checks are listed below.

## The claim

| | |
| --- | --- |
| Circles | 104 |
| Claimed sum of radii | 5.312597 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | fail | Both verifiers reject the packing: a circle crosses the square's edge by 5.700e-13 and two circles overlap (squared distance short by 2.053e-12), about 21 times what rounding to the printed digits can cause (allowance 1e-13). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.312597, recomputed 5.31259698042292, difference 1.958e-08. Agrees with the claim rounded to its printed digits. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.31259698042292` |
| Smallest gap to a wall | -5.700e-13 |
| Smallest squared gap between two circles (negative means overlap) | -2.053e-12 |
| Tolerance, from the file's 14 printed decimals | 1e-13 |
| Work done | 104 circles, 5356 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/abiyev-n104.receipt.json claims/abiyev-n104/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `9c29b146fcf6855961023951a5fc9489ee1603cf542686193f83dced8032bcf7` |
| Claim card | `01b33cc4b3255fdff52d006e4a75dac04505d82029580e51e4cc11190b79fe6b` |
| File `csqv104.pck` | `75e3002af8aa7d1475547d8a01e058c9dd27c883fd15357bfcf583e77137738b` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
