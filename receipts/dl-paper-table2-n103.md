# Paper Table 2: for N=103 our best sum of radii is 5.345481, a 5.11% improvement over the prior Packomania record 5.085509 (file best/pck/csqv103.pck at commit 9ec32c0)

Claim Notary receipt, issued 2026-11-26. Claimed by Discovery Loop (Wes Sander, MoltFire), arXiv:2609.05093 ([source](https://arxiv.org/abs/2609.05093)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 103 |
| Claimed sum of radii | 5.345481 |
| Reference it beats | 5.085509 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.085509313239) |
| Claimed gain | 5.11% |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.345481, recomputed 5.3454809759973976, difference 2.400e-08 (allowed 5.000e-07: 1e-9, or half a unit in the claim's last printed digit if larger). |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 5.085509 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.085509313239). |
| Claimed gain | pass | Claimed 5.11%, recomputed 5.1120% against the reference. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.3454809759973976` |
| Smallest gap to a wall | 1.000e-12 |
| Smallest squared gap between two circles (negative means overlap) | 3.384e-13 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 103 circles, 5253 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/dl-paper-table2-n103.receipt.json claims/dl-paper-table2-n103/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `18d7950a0070c7067be64641c267889f2a07379c0dc67d5e0a8284fa40f948f0` |
| Claim card | `b74b165919bfb3427d3a83cf1f765d9b749c1af8a87b3e6139f2719b18bb04fb` |
| File `csqv103.pck` | `593fbd396c281cec8e1044f9994ff93508a38ed54fb7bc6557a8b59139295725` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `e25edf565346f084807c84d06afdd7e642d6a53c0c1ca45de9b0eee19fc1bffe` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
