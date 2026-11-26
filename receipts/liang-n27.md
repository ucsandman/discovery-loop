# The original n27 solver found N=27 sum of radii 2.685978684198, beating the 2011/12 entry 2.685350025228 (README; file sota/sm-radical-v6-n27/pck/csqv27.pck)

Claim Notary receipt, issued 2026-11-26. Claimed by Jason Liang, Cognizant AI Lab (self-improving AI agent) ([source](https://github.com/jasonzliang/circle-packing-sota)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 27 |
| Claimed sum of radii | 2.685978684198 |
| Reference it beats | 2.685350025228 (README: the 2011/12 entry by D. W. Cantrell) |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.685978684198, recomputed 2.685978684198, difference 0.000e+00. Agrees to 1e-9. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 2.685350025228 (README: the 2011/12 entry by D. W. Cantrell). |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.685978684198` |
| Smallest gap to a wall | 1.000e-12 |
| Smallest squared gap between two circles (negative means overlap) | 2.762e-13 |
| Tolerance, from the file's 12 printed decimals | 1e-11 |
| Work done | 27 circles, 351 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/liang-n27.receipt.json claims/liang-n27/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `dd9be4dc92146d33e575d01acfa5ff19c422f416f9a7e621e7ce714f2406cb08` |
| Claim card | `41ff90c2d1fa89d9ec094c04e98415f312cb0b0edafa2be1544c6517863cfb6b` |
| File `csqv27.pck` | `c3bc7255e6215a8244e42a31ea24662ade340b92f11e822b4fd87ad62ea4db8e` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
