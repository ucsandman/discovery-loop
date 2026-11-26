# The adjustment from the relaxed to exact formulation reduces the sum of radii for our discovered solution by a negligible amount, from 2.635983099011548 to 2.6359828390115476 (ShinkaEvolve paper)

Claim Notary receipt, issued 2026-11-26. Claimed by Sakana AI, ShinkaEvolve (arXiv:2509.19349) ([source](https://arxiv.org/abs/2509.19349)).

> **Cannot be decided from what was given.** The verifiers disagree or the file lacks the precision to decide. Nothing was guessed.

## The claim

| | |
| --- | --- |
| Circles | 26 |
| Claimed sum of radii | 2.6359828390115476 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| Coordinates published | undecided | No coordinates were published with this claim. No coordinate file from Sakana was found. A third-party copy in the ThetaEvolve repository (Results/CirclePacking/data.json, entry 'ShinkaEvolve') is a valid packing whose sum is 2.63598282664580639, 1.2e-8 below the claimed value, so it is not the packing this claim describes. |

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

From a clone of this repository: `python notary.py verify-receipt receipts/shinkaevolve-n26.receipt.json claims/shinkaevolve-n26/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `d76d54d145fa6cdec63ca7238ab3b4ce7bbbe4191d7db953cd7475a933fd5774` |
| Claim card | `ee46811e801cb957651cf825fb2d1aedb37150736d8f645edc142130d376760a` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
