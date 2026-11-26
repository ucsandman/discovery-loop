# Reproduces the SOTA of 26 circles packing inside unit square, sum of radii 2.6359830849014761 (certified feasible); file: best_certified.npz

Claim Notary receipt, issued 2026-11-26. Claimed by ocelopus (YOLO ReAct agent on DeepSeek-V4.1-Flash) ([source](https://github.com/ocelopus/reproduce_sota_26_circle_packing)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 26 |
| Claimed sum of radii | 2.6359830849014761 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square, by both verifiers. The smallest gaps are slightly negative, within what rounding to 15 printed decimals can cause (tolerance 1e-14). |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.6359830849014761, recomputed 2.63598308490147614, difference 4.000e-17. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.63598308490147614` |
| Smallest gap to a wall | 1.000e-17 |
| Smallest squared gap between two circles (negative means overlap) | -1.264e-17 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 26 circles, 325 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/ocelopus-n26.receipt.json claims/ocelopus-n26/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `a29df27dab7ff142a8d0a41783e4d5f496af2f18c57e016e57b190ab1b7f531f` |
| Claim card | `c6c5b899b239e942d6ee83bfbd045ce2754c2e5e5bc76f977cb6c9c9794997c0` |
| File `best_certified.txt` | `4b30b2500943668013767856cab31969da54fec7ac490e45446400382c1882cd` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
