# Paper Table 2: for N=108 our best sum of radii is 5.481819, a 5.30% improvement over the prior Packomania record 5.205806 (file best/pck/csqv108.pck at commit 9ec32c0)

Claim Notary receipt, issued 2026-11-26. Claimed by Discovery Loop (Wes Sander, MoltFire), arXiv:2609.05093 ([source](https://arxiv.org/abs/2609.05093)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 108 |
| Claimed sum of radii | 5.481819 |
| Reference it beats | 5.205806 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.205806372160) |
| Claimed gain | 5.30% |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.481819, recomputed 5.4818189198138706, difference 8.019e-08 (allowed 5.000e-07: 1e-9, or half a unit in the claim's last printed digit if larger). |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 5.205806 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.205806372160). |
| Claimed gain | pass | Claimed 5.30%, recomputed 5.3020% against the reference. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.4818189198138706` |
| Smallest gap to a wall | 1.000e-14 |
| Smallest squared gap between two circles (negative means overlap) | 3.316e-15 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 108 circles, 5778 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/dl-paper-table2-n108.receipt.json claims/dl-paper-table2-n108/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `3d64951b2e751800eec533f5bef2f4a4243c8f3ddf51bcef5c851c3dcb5ab9b9` |
| Claim card | `e7b38a36ba52f000808c5f6c0ef52e2c798bbe1b3fe2f8e833ec5a09d9091d38` |
| File `csqv108.pck` | `315172064c815b89c9de8235cba44cd0583022f3f01799d479fce46352f3b9fb` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `e25edf565346f084807c84d06afdd7e642d6a53c0c1ca45de9b0eee19fc1bffe` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
