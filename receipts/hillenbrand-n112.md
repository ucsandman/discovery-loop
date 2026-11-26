# N=112: radius sum 5.579854618221 against Packomania's posted 5.579811038411 as of its 2026-11-01 table (data/RESULTS.csv; file packings/csqv112.pck)

Claim Notary receipt, issued 2026-11-26. Claimed by Audrey Hillenbrand (search code built with an OpenAI model) ([source](https://github.com/Audrey-makes/Circles-in-a-Square)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 112 |
| Claimed sum of radii | 5.579854618221 |
| Reference it beats | 5.579811038411 (RESULTS.csv: Packomania table of 2026-11-01) |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.579854618221, recomputed 5.579854618220678140192165, difference 3.219e-13. Agrees to 1e-9. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 5.579811038411 (RESULTS.csv: Packomania table of 2026-11-01). |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.579854618220678140192165` |
| Smallest gap to a wall | 0.000e+00 |
| Smallest squared gap between two circles (negative means overlap) | 3.450e-24 |
| Tolerance, from the file's 24 printed decimals | 1e-23 |
| Work done | 112 circles, 6216 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/hillenbrand-n112.receipt.json claims/hillenbrand-n112/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `b39e10d739fe2a75b944a1580efb9df6ddfe2ee212bdbc0f049a0ec8c7f89bab` |
| Claim card | `0b0dd9fceb6b028fcbd7153136f2d9c0691f01d9896eeed4b708d4dc54ec4648` |
| File `csqv112.pck` | `93e3c898049e03c00b89838d5c1c7b58a3b2650ecf5b5376aadb3587d97137c4` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
