# Paper Table 2: for N=102 our best sum of radii is 5.318238, a 5.20% improvement over the prior Packomania record 5.055187 (file best/pck/csqv102.pck at commit 9ec32c0)

Claim Notary receipt, issued 2026-11-26. Claimed by Discovery Loop (Wes Sander, MoltFire), arXiv:2609.05093 ([source](https://arxiv.org/abs/2609.05093)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 102 |
| Claimed sum of radii | 5.318238 |
| Reference it beats | 5.055187 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.055187230279) |
| Claimed gain | 5.20% |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.318238, recomputed 5.3182376714014294, difference 3.286e-07. Agrees with the claim rounded to its printed digits. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 5.055187 (paper Table 2 Prior Record; the Wayback Machine copy of Packomania sumradii.txt from 2026-08-09 lists 5.055187230279). |
| Claimed gain | pass | Claimed 5.20%, recomputed 5.2036% against the reference. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.3182376714014294` |
| Smallest gap to a wall | 1.000e-12 |
| Smallest squared gap between two circles (negative means overlap) | 3.329e-13 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 102 circles, 5151 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/dl-paper-table2-n102.receipt.json claims/dl-paper-table2-n102/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `197b114d45065734ff15ac03422bf02b752702fd8568a69424dfe90d6c01d7db` |
| Claim card | `2c4ed6ec7788a4f408cb17865c91caac242948bc75493e9b41ae545ca8a16890` |
| File `csqv102.pck` | `aef9650d0e6cd41cebfffcffb6c29b6d606ee6b57652200ca47d94663e74f006` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
