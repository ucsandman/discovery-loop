# Packomania lists a packing of 27 unequal circles in the unit square with sum of radii 2.685978684198

Claim Notary receipt, issued 2026-11-26. Claimed by Packomania csqv list (fetched 2026-11-26) ([source](https://www.packomania.com/csqv/csqv.html)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 27 |
| Claimed sum of radii | 2.685978684198 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 2.685978684198, recomputed 2.685978684198, difference 0.000e+00. Agrees to 1e-9. |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `2.685978684198` |
| Smallest gap to a wall | 1.000e-12 |
| Smallest squared gap between two circles (negative means overlap) | 2.762e-13 |
| Tolerance, from the file's 12 printed decimals | 1e-11 |
| Work done | 27 circles, 351 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/packomania-csqv27.receipt.json claims/packomania-csqv27/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `7275093e7fec2451e17644dde7e0c6532a409706ce68975077cebab35caa8aad` |
| Claim card | `39b471b124979e0a299d5cde55a2dba4e4635791473dd939837c141376c6d575` |
| File `csqv27.txt` | `067f44a3892fc7dc25f7b2632d4145dda313ea23d8c85c311c4d08f5b04245d9` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `951d1e3640ac749955d9a12adc22ee4f34d3dec7fe8d2544a1df525a28906c74` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
