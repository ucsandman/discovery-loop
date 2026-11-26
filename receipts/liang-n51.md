# N=51: 3.729658093746 against the reference 3.727021028707 fetched on 2026-08-10, a WIN (sota/sm-radical-v6-n54/comparison.md; file pck/csqv51.pck)

Claim Notary receipt, issued 2026-11-26. Claimed by Jason Liang, Cognizant AI Lab (self-improving AI agent) ([source](https://github.com/jasonzliang/circle-packing-sota)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 51 |
| Claimed sum of radii | 3.729658093746 |
| Reference it beats | 3.727021028707 (comparison.md: Packomania table fetched 2026-08-10) |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 3.729658093746, recomputed 3.7296580937464982, difference 4.982e-13. Agrees to 1e-9. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 3.727021028707 (comparison.md: Packomania table fetched 2026-08-10). |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `3.7296580937464982` |
| Smallest gap to a wall | 1.000e-12 |
| Smallest squared gap between two circles (negative means overlap) | 2.384e-13 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 51 circles, 1275 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/liang-n51.receipt.json claims/liang-n51/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `81cacaa83496f2ebdcb8439303ea9c69977f39bdfd6a358eca3ef609bbfa06e5` |
| Claim card | `670ad993e31826b7aaa684368c140489d2c4440cde7fed087ee2f96b5672e63a` |
| File `csqv51.pck` | `54259e1d2ae9b0f61d1fbbe873e173e253c472cb32c6b5efaae36a994da962b0` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
