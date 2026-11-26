# Our submitted file for N=109 is the packing Packomania lists at 5.507925934200

Claim Notary receipt, issued 2026-11-26. Claimed by Discovery Loop (Wes Sander, MoltFire) ([source](https://www.packomania.com/csqv/csqv.html)).

> **Holds.** Every check passed and two independent verifiers agree.

## The claim

| | |
| --- | --- |
| Circles | 109 |
| Claimed sum of radii | 5.507925934200 |

## What was checked

| Check | Result | Detail |
| --- | --- | --- |
| Within what the notary can check | pass | Circle packing in the unit square, maximise the sum of radii. |
| File matches the claim | pass | The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself. |
| Valid packing (inside the square, no overlaps) | pass | Inside the square with no overlaps, by both verifiers. |
| Two independent verifiers agree | pass | Primary and exact sums differ by 0.0e+00. |
| Claimed sum of radii | pass | Claimed 5.507925934200, recomputed 5.5079259342042162, difference 4.216e-12 (allowed 1.000e-09: 1e-9, or half a unit in the claim's last printed digit if larger). |

## What was measured

| | |
| --- | --- |
| Recomputed sum of radii (exact) | `5.5079259342042162` |
| Smallest gap to a wall | 1.010e-14 |
| Smallest squared gap between two circles (negative means overlap) | 3.394e-15 |
| Tolerance, from the file's 16 printed decimals | 1e-15 |
| Work done | 109 circles, 5886 pairs |

## What this receipt does not show

- That this packing is the best possible. Only that it is valid and has the sum printed here.
- That the reference value is the best known today. It is taken from the claim as stated, with its source.
- Who found the packing or how. The notary checks the file, not its history.
- Anything about a file other than the one whose hash is printed on this receipt.

## Check it yourself

From a clone of this repository: `python notary.py verify-receipt receipts/discovery-loop-csqv109.receipt.json claims/discovery-loop-csqv109/card.json`. It re-runs every check and lists any difference.

| | sha256 |
| --- | --- |
| Receipt | `03b67785364e94d9d2059df523fb5c707b47194ad8fca0a21e485097e6e143e9` |
| Claim card | `c2111fc5cbe2358b982366a3577d8aacd5892cf88ebe26fa3ccd706ab68d5e9b` |
| File `csqv109.pck` | `4a9544663a72b5346fd9b8fb43736d625e08d038cdbdd58bb3aaba56456a406b` |
| Verifier `problems/circle_packing/verify.py` | `0c482cc699f04511e99ba825399c9d336331798ee7b86d0466023aebb1c68e65` |
| Verifier `notary_exact.py` | `53cb37ba4c5dfa98de586836b7c467fb90d34bf4f56e5f90951a30580f95ab9e` |
| Verifier `notary.py` | `e25edf565346f084807c84d06afdd7e642d6a53c0c1ca45de9b0eee19fc1bffe` |

Rules fixed in advance in [docs/notary-prereg.md](../docs/notary-prereg.md).
