# For n=26, the SOTA was 2.634, and AlphaEvolve improved it to 2.635 (Construction 1 in the results notebook, section B.12)

Claim Notary receipt, issued 2026-11-26. Claimed by Google DeepMind, AlphaEvolve (arXiv:2506.13131) ([source](https://github.com/google-deepmind/alphaevolve_results/blob/main/mathematical_results.ipynb)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 26 |
| Claimed sum of radii | 2.635 |
| Reference it beats | 2.634 (the same notebook: 'the SOTA was 2.634') |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.635, recomputed 2.63586275641369812, difference 8.628e-04. Agrees with the claim truncated to its printed digits. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 2.634 (the same notebook: 'the SOTA was 2.634'). |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.63586275641369812` |
| Smallest gap to a wall | 7.852e-09 |
| Smallest squared gap between two circles (negative means overlap) | 2.375e-09 |
| Tolerance, from the file's 7 printed decimals | 1e-6 |
| Work done | 26 circles, 325 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/alphaevolve-n26.receipt.json claims/alphaevolve-n26/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `1d3aafc7a9693df8b6474ee9020331fe939740a03ac7e0ce01684ef8d79d5f9a` |
| Claim card | `b2b709f54c600e50175056e8c1a8822f9d89df990d3420f11098be4823ee303d` |
| File `alphaevolve-n26.txt` | `acb476e262e3b276d2a1ae2869bf00de0997fd2aae95abf3b55b4496fd728a96` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
