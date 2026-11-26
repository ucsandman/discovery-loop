# Paper Table 2: for N=107 our best sum of radii is 5.453952, a 5.29% improvement over the prior Packomania record 5.180124 (file best/pck/csqv107.pck at commit 9ec32c0)

Claim Notary receipt, issued 2026-11-26. Claimed by Discovery Loop (Wes Sander, MoltFire), arXiv:2609.05093 ([source](https://arxiv.org/abs/2609.05093)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 107 |
| Claimed sum of radii | 5.453952 |
| Reference it beats | 5.180124 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.180123548981) |
| Claimed gain | 5.29% |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.453952, recomputed 5.4539520679174088, difference 6.792e-08. Agrees with the claim rounded to its printed digits. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 5.180124 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.180123548981). |
| Claimed gain | pass | Claimed 5.29%, recomputed 5.2861% against the reference. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.4539520679174088` |
| Smallest gap to a wall | 1.010e-14 |
| Smallest squared gap between two circles (negative means overlap) | 3.295e-15 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 107 circles, 5671 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/dl-paper-table2-n107.receipt.json claims/dl-paper-table2-n107/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `d21f56e60f8a45e15452b95caa3956afd44e2ce0e77f79259756f04cb4e06bbe` |
| Claim card | `e73838a20b609a443b5ef043f0aefa495fbaf2d657b63fd7c40d4eef34dfbc18` |
| File `csqv107.pck` | `96302a97dcc8b0b83dcbcfbd4d2d7cc5266d482170d315288790482e14bc174b` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
