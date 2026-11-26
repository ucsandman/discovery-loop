# Ours (R1-Qwen3-8B): 2.63598308, against AlphaEvolve's 2.63586276 (README); file: the zero-tolerance entry '8B-w_RL@65-Formal' of Results/CirclePacking/data.json (sha256 c20023f5a4d3e1408a7ec29ee043dea3c2b8d9711dd21c806008b5a48646e7b8), centres and radii re-joined as [x, y, r] with every digit unchanged

Claim Notary receipt, issued 2026-11-26. Claimed by Yiping Wang et al., ThetaEvolve (arXiv:2511.23473) ([source](https://github.com/ypwang61/ThetaEvolve)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 26 |
| Claimed sum of radii | 2.63598308 |
| Reference it beats | 2.63586276 (the ThetaEvolve README's AlphaEvolve figure) |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.63598308, recomputed 2.63598307738811934, difference 2.612e-09. Agrees with the claim rounded to its printed digits. |
| Beats the stated reference | pass | Recomputed sum exceeds the reference 2.63586276 (the ThetaEvolve README's AlphaEvolve figure). |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.63598307738811934` |
| Smallest gap to a wall | 3.101e-10 |
| Smallest squared gap between two circles (negative means overlap) | 4.957e-13 |
| Tolerance, from the file's 15 printed decimals | 1e-14 |
| Work done | 26 circles, 325 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/thetaevolve-8b-formal-n26.receipt.json claims/thetaevolve-8b-formal-n26/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `b0666e669199a9057f2f9172927e95c291b33f617eed49610921d2b7be1e283b` |
| Claim card | `1ba9f84fd9ad680360e504b8d787bf18509ac68f356fdcbff86c2124384528e4` |
| File `thetaevolve-8b-rl65-formal.json` | `ac902091583be1b307b13772c545d38672808cc888a4a83547e61d01f7bbf085` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
