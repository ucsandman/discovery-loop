# For circle packings, we improve the best known lower bounds, surpassing the LLM-based system AlphaEvolve (abstract); the paper reports 2.939349 for n=32

Claim Notary receipt, issued 2026-11-26. Claimed by Berczig et al., FlowBoost (arXiv:2601.18005) ([source](https://arxiv.org/abs/2601.18005)).

> **Cannot be decided from what was given.** The verifiers disagree or the file lacks the precision to decide. Nothing was guessed.

## The claim

| | |
| --- | --- |
| Circles | 32 |
| Claimed sum of radii | 2.939349 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| Coordinates published | undecided | No coordinates were published with this claim. The repository has code and no coordinate files. |

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

From a clone of this repository: `python notary.py verify-receipt receipts/flowboost-n32.receipt.json claims/flowboost-n32/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `8c786229188c551a37c682aa13919960ae65d837641139a381e5131c4a766925` |
| Claim card | `0db11d82c7c1ebd1854cc4eb63734eac056f76d78489b1b49485557947d62d1b` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
