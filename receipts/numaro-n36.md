# n=36: 3.1210039084, the largest margin in the set

Claim Notary receipt, issued 2026-11-26. Claimed by Numaro AI Autoresearch Team (report NUMARO-2026-004) ([source](https://numaro.tech/research/circle-packing-unit-square-2026/)).

> **Cannot be decided from what was given.** The verifiers disagree or the file lacks the precision to decide. Nothing was guessed.

## The claim

| | |
| --- | --- |
| Circles | 36 |
| Claimed sum of radii | 3.1210039084 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| Coordinates published | undecided | No coordinates were published with this claim. The page draws the layout but offers no coordinate file. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `none` |
| Smallest gap to a wall | none |
| Smallest squared gap between two circles (negative means overlap) | none |
| Tolerance, from the file's None printed decimals | None |
| Work done | 0 circles, 0 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/numaro-n36.receipt.json claims/numaro-n36/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `0637536ac4bf840951fa1c144dea84ccf8ffd29e42616038ed774a1babd26dc7` |
| Claim card | `34e275332b61c73c279ff638b1bd495614d579724224e01730e631883af94e63` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
