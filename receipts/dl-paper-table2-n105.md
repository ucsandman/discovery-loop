# Paper Table 2: for N=105 our best sum of radii is 5.401298, a 5.37% improvement over the prior Packomania record 5.125967 (file best/pck/csqv105.pck at commit 9ec32c0)

Claim Notary receipt, issued 2026-11-26. Claimed by Discovery Loop (Wes Sander, MoltFire), arXiv:2609.05093 ([source](https://arxiv.org/abs/2609.05093)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 105 |
| Claimed sum of radii | 5.401298 |
| Reference it beats | 5.125967 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.125966997427) |
| Claimed gain | 5.37% |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.401298, recomputed 5.4012980394103374, difference 3.941e-08. Agrees with the claim rounded to its printed digits. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 5.125967 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.125966997427). |
| Claimed gain | pass | Claimed 5.37%, recomputed 5.3713% against the reference. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.4012980394103374` |
| Smallest gap to a wall | 1.000e-14 |
| Smallest squared gap between two circles (negative means overlap) | 3.332e-15 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 105 circles, 5460 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/dl-paper-table2-n105.receipt.json claims/dl-paper-table2-n105/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `b04bda56d03ee375653790741f8e29dc6dd5f8fa37bdc05adced9d534fb5b0a0` |
| Claim card | `699d28c031975b9ffb5257420fcc9edbcf83e7d4d61617b1e97d76ddeae50ddd` |
| File `csqv105.pck` | `fb577408e1bc8500def1d651bbc61397cf18c95521b0f0e5cd8cc6a7a4295313` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
