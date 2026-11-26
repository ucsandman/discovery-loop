# Claim Notary

The Claim Notary re-checks an optimization result that someone else claims, and returns a receipt anyone can re-run.
It is the first piece of the Discovery Loop and Practical Systems combination chosen on 2026-11-26: AI makes claims
cheap, and maintainers and benchmark keepers now spend their time checking them. Phase 1 checks circle-packing claims
(Packomania csqv) only, and only data. No program from outside runs on this machine.

The pass/fail numbers were fixed before any check ran, in [notary-prereg.md](notary-prereg.md) (commit `7336406`).

## The registry

The public list of receipts is [receipts/README.md](../receipts/README.md). Each claim lives in `claims/<claim_id>/`
(the card and the exact file it names). Each receipt is in `receipts/` as JSON, a self-contained HTML page and a
Markdown page that GitHub renders. [receipts/CORRECTIONS.md](../receipts/CORRECTIONS.md) logs every receipt whose
outcome changed after it was issued.

Every receipt is re-derived from its card by the test suite on every push and by
`.github/workflows/notary.yml` every night at 07:17 UTC. A receipt whose outcome no longer reproduces fails the run.
A new wording or program version that leaves every outcome unchanged is reported as `reworded`, not as a failure.

## Use

```powershell
python notary.py issue claims/<claim_id>/card.json          # add or refresh a registry receipt and the index
python notary.py issue claims/<claim_id>/card.json --correction "why"   # needed when an issued outcome changes
python notary.py reverify-all                               # re-derive every receipt; prints the volume
python notary.py check CARD.json --out DIR                  # one-off check outside the registry
python notary.py verify-receipt RECEIPT.json CARD.json      # re-run one receipt field by field
python scripts/notary_planted.py                            # the planted-cheat gate
python scripts/notary_planted.py --break both               # the same gate with both verifiers broken: must go red
```

## Claim card

A JSON file beside the artifact it names. Unknown fields are rejected, so a claimant cannot add a tolerance or any
other rule.

| Field | Meaning |
| --- | --- |
| `schema` | `claim-card-v1` |
| `claim_id` | 1-80 letters, digits, dots, dashes, underscores; names the receipt files |
| `problem` | `circle_packing`; anything else gets `cannot_check` |
| `claimant`, `statement` | Who claims what, in plain words |
| `source_url` | Optional, `https://` only |
| `artifact` | `{path, format, sha256?}`: a file inside the card's folder. Formats: `pck` (ours), `packomania_txt`, `json_corner` (`[[x, y, r], ...]` or `{"circles": [...]}` in [0, 1]^2) and `txt_corner` (one `x y r` per line in [0, 1]^2; commas and brackets allowed). Numbers are read as printed, never through floats |
| `n` | Number of circles |
| `claimed_sum` | The claimed sum of radii, as a decimal string |
| `reference` | Optional `{value, source}`: the value the claim says it beats |
| `claimed_gain_pct` | Optional, needs `reference`: the claimed gain in percent |

## Rules

1. Two verifiers that share no code: `problems/circle_packing/verify.py` (floats) and `notary_exact.py` (exact
   integer arithmetic on the printed decimals). If they disagree, the verdict is `insufficient_spec`.
2. Tolerance comes from the file's printed precision only: `10^-(d-1)` for `d` decimals, on the minimum wall slack and
   the minimum squared pair slack. Packomania prints 12 decimals (tolerance `1e-11`); our `.pck` files print 16
   (`1e-15`).
3. A claimed sum agrees within `1e-9`, or within half a unit in its last printed digit when the claim is rounded
   more coarsely (see the deviations). A claimed gain agrees within `0.01` percentage points.
4. Hashes are SHA-256 of text with line endings normalised to LF, so a receipt re-derives on every OS.
5. A receipt binds the claim card, the artifact and the source of all three programs. Changing any of them, or any
   field of the receipt, makes `verify-receipt` fail.
6. A receipt is not a benefit. Nothing here sends, posts or publishes anything.

## First proof, days 0 to 3 (2026-11-26)

| Gate | Result |
| --- | --- |
| Day 0: preregistration committed before any check | `7336406`, sha256 `09966a3b...02743` |
| Day 2: planted cheats | `planted=10 caught=10; tampered=5 caught=5; honest=1 held=1` |
| Day 2: the gate goes red when the verifiers are broken | `--break both`: 3 planted cheats and the re-hashed forged verdict pass, `GATE FAIL`. With one verifier broken, every cheat is still caught as `insufficient_spec` |
| Day 3: agreement with the keeper | Packomania N=101, 106, 109: recomputed sums equal the published sums (difference 0); our N=106 and 109 files match the list to 1.2e-12 and 4.2e-12 |

A finding from day 3: Packomania's published 12-decimal files overlap by up to about `3e-13` in squared distance,
which rounding to 12 decimals causes. A zero-tolerance checker would wrongly reject the keeper's own files. Our
16-decimal files have strictly positive gaps.

## Our own claim, checked first (days 4 and 5)

Before checking anyone else, the notary checked the Discovery Loop paper. On 2026-11-26 we suspected that its
"2.4% to 5.4% over prior records" was overstated, because `best/submitted.json` compares our final values with much
closer list values (0.28% to 0.73%). The history settles it:

| Submission | Our N=101 | Packomania's value at that moment |
| --- | --- | --- |
| 2026-09-02 06:42 | 5.259794 | 5.163845, the list before us |
| 2026-09-03 11:56 | 5.291095 | 5.259794, our own entry from the day before |

The 0.28% to 0.73% is our second submission beating our first. The Wayback Machine copy of Packomania's
`sumradii.txt` from 2026-08-09 lists the prior values in the paper's table exactly (N=101: 5.163845225266). All 10
rows of the paper's Table 2 hold against the files in Git: N=101 and N=114 match the 2026-09-02 versions, the other
eight the final files (`claims/dl-paper-table2-n*`). The README stays as it is.

## The first outside claims (days 6 and 7, 2026-11-26)

23 public claims about this problem, made in 2025 and 2026 mostly by or about AI systems, were collected from
papers, READMEs, issue threads and Packomania. Each card quotes the claim as written, and every quote and number was
checked against its source the same day. 15 published coordinates; 8 published only a program, a screenshot or
nothing.

| Gate (preregistered) | Result |
| --- | --- |
| Correctness: agreement with the keeper's published value | 8 of 8 comparisons of the same packing agree (exactly, or within 4.2e-12 for our 16-decimal files). Two more rows compare different packings: Packomania has since listed a better N=84 than Arnold Castro's, and Hyra's N=26 claims 1.0e-8 more than the list's N=26, the amount its overlaps buy. No gap is a verifier disagreement |
| Discrimination: at least 1 real claim does not hold | 9 do not hold: 8 of Hyra's 9 records (N=26, 33, 35-40), whose circles cross the square's edge and each other by up to 7.7e-10, about 50,000 to 77,000 times what rounding their 15-16 printed decimals can cause, and Rasim Abiyev's N=104, which overlaps by up to 2.1e-12, about 21 times its rounding allowance |
| Breadth: at most 8 of 13 in `cannot_check` | 0 out of scope. 9 claims are `insufficient_spec` because the claimant published no coordinates (OpenEvolve, two OpenEvolve issue comments, HELIX, FlowBoost, Pokutta et al., Numaro twice, ShinkaEvolve) |
| Demand: 2 useful replies from 5 recipients | Not started. Nothing has been sent |

Claims that hold include AlphaEvolve's N=26 and N=32, ThetaEvolve's zero-tolerance N=26, Jason Liang's N=27 and N=51,
Arnold Castro's N=84, Audrey Hillenbrand's N=112, ocelopus, blankline and Hyra's N=34. The ShinkaEvolve claim has no
Sakana coordinate file; the copy in the ThetaEvolve repository is a valid packing 1.2e-8 below the claimed sum, so
it was not used as Sakana's.

## Deviations from the preregistration

The preregistration lets a file's printed precision set its tolerance, which would let a claimant print few decimals
to get a loose tolerance. The notary therefore also requires at least 10 printed decimals and returns
`insufficient_spec` below that (planted case `low_precision`). This is stricter than the preregistered rule, not
looser.

A rounded claim, such as a paper table printing six decimals, cannot agree with an exact sum to `1e-9`. Rule 3 as
preregistered would reject every honestly rounded claim. A claimed sum therefore agrees within `1e-9` or half a unit
in its last printed digit, whichever is larger. This loosens rule 3 only for claims printed with fewer than nine
decimals, and only by the rounding the claim itself states.

Three more rules changed after the first run on outside claims. Each is listed with the receipts it changed, so the
change can be judged by the cases that prompted it.

1. A claimed sum printed with few digits also agrees when it is the recomputed sum truncated to those digits.
   AlphaEvolve writes 2.635 for 2.6358627564; under rounding alone that claim failed. Truncation is a common
   convention (Hyra and Packomania write values like "2.634+"). Changed: `alphaevolve-n26`, `alphaevolve-n32`.
2. The 10-decimal minimum applies only when a packing fits because of the rounding allowance. AlphaEvolve's files
   print 7 decimals but fit with no allowance at all in exact arithmetic, so their precision decides nothing. Both
   verifiers must see the strict fit; with either one broken, the planted `low_precision` cheat is still caught.
   Changed: `alphaevolve-n26`, `alphaevolve-n32`.
3. The float verifier cannot resolve slacks below about 1e-14, so it is never held to a tighter tolerance than that;
   the exact verifier still applies the file's own allowance. Audrey Hillenbrand's file prints 24 decimals, and the
   float verifier rejected a contact that the exact verifier measured at 0. Changed: `hillenbrand-n112`.

None of the three changed a `does_not_hold` into `holds` for a packing with an overlap or a wall crossing.
