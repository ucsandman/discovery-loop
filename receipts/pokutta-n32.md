# Circle packing, square n = 32: 2.93957 against 2.93794 (AlphaEvolve 2025)

Claim Notary receipt, issued 2026-11-26. Claimed by Pokutta et al. (Xpress and SCIP global solvers, arXiv:2601.05943) ([source](https://www.pokutta.com/blog/not-every-discovery-needs-an-llm/)).

> **Cannot be decided from what was given.** The verifiers disagree or the file lacks the precision to decide. Nothing was guessed.

## The claim

| | |
| --- | --- |
| Circles | 32 |
| Claimed sum of radii | 2.93957 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| Coordinates published | undecided | No coordinates were published with this claim. No coordinate file was found. |

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

From a clone of this repository: `python notary.py verify-receipt receipts/pokutta-n32.receipt.json claims/pokutta-n32/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `27aebae5945abc9c3480aa63db5c2217b2967b5543f1b0c50e43e43989f2ea22` |
| Claim card | `7d98e557f3b62bb9855fca6d2a4d080dc7bd2e55d1c9c04b9f8d57ec2b771c50` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
