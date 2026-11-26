# Paper Table 2: for N=114 our best sum of radii is 5.624188, a 5.39% improvement over the prior Packomania record 5.336683 (file best/pck/csqv114.pck at commit e160602)

Claim Notary receipt, issued 2026-11-26. Claimed by Discovery Loop (Wes Sander, MoltFire), arXiv:2609.05093 ([source](https://arxiv.org/abs/2609.05093)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 114 |
| Claimed sum of radii | 5.624188 |
| Reference it beats | 5.336683 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.336683004720) |
| Claimed gain | 5.39% |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.624188, recomputed 5.6241880558870823, difference 5.589e-08 (allowed 5.000e-07: 1e-9, or half a unit in the claim's last printed digit if larger). |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 5.336683 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.336683004720). |
| Claimed gain | pass | Claimed 5.39%, recomputed 5.3873% against the reference. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.6241880558870823` |
| Smallest gap to a wall | 1.000e-14 |
| Smallest squared gap between two circles (negative means overlap) | 2.955e-15 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 114 circles, 6441 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/dl-paper-table2-n114.receipt.json claims/dl-paper-table2-n114/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `6edc8dd8efd742a0a910b8ea4ec3fd9f9b140c3e3f8a9461854a81d199f52da6` |
| Claim card | `558da6cdbf44666c2d0f186175f10015bf7dddfd8b6cc665fdaa81699774bdb3` |
| File `csqv114.pck` | `fb0b2587e8a8a2fa88553ccb8d06def585fb0f6c2e4e247cf8b71ba06284a485` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `e25edf565346f084807c84d06afdd7e642d6a53c0c1ca45de9b0eee19fc1bffe` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
