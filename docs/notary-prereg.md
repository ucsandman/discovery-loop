# Claim Notary: preregistration for the 14-day first proof

Written 2026-11-26, before the notary existed and before any claim was checked. This file is committed alone, and
its commit is the timestamp. A later change to any number below is a new preregistration with its own date, and the
original stays in Git history.

## What is being tested

Whether an independent re-check of someone else's AI-found optimization claim, returned as a receipt anyone can
re-run, is (1) correct, (2) able to find claims that do not hold, and (3) wanted by the people it is sent to.
Phase 1 checks circle-packing claims only (Packomania csqv: unequal circles in the unit square, maximise the sum of
radii). Packings are data. No program from outside runs on this machine in phase 1.

## Rules fixed in advance

1. Two verifiers. The primary is the existing `problems/circle_packing/verify.py` `check()` (floats). The second is a
   separate implementation in exact rational arithmetic that does not import the first. If they disagree on any
   verdict, the receipt says `insufficient_spec`, never a guess.
2. Feasibility tolerance comes only from the artifact's printed precision. With `d` the fewest decimals printed in
   any coordinate or radius, the tolerance is `10^-(d-1)`, applied to the minimum wall slack and to the minimum
   squared pair slack `d^2 - (ri + rj)^2`. Rounding each value to `d` decimals moves a wall slack by at most `10^-d`
   and a squared pair slack by at most `6 * 10^-d` in the unit square, so the rule covers rounding and nothing
   more. Artifacts with full floating-point values (JSON) get tolerance 0. A claimant cannot choose a tolerance.
3. A claimed sum agrees when it is within `1e-9` of the exactly recomputed sum.
4. A claimed gain in percent agrees when it is within `0.01` percentage points of the gain recomputed from the
   recomputed sum and the stated reference value.
5. Verdicts: `holds` (every check passed and the verifiers agree), `does_not_hold` (any check failed),
   `insufficient_spec` (the verifiers disagree), `cannot_check` (outside the problems the notary has a verifier for).

## Gates, in order

| Day | Gate | Pass | Stop |
| --- | --- | --- | --- |
| 2 | Planted cheats | 10 of 10 planted bad claims and 5 of 5 tampered receipts are caught, and 1 of 1 honest control holds | Any planted cheat passes as `holds` |
| 2 | The cheat corpus has teeth (L1) | With both verifiers deliberately broken to accept anything, at least 1 planted cheat is missed | A broken verifier still catches everything, meaning the corpus tests nothing |
| 3 | Second verifier | The exact verifier agrees with the primary on every planted case | Any disagreement left unexplained |
| 3 | Agreement with the keeper | Recomputed sums of 3 packings published by Packomania match the published sum to `1e-9` | 2 or more unexplained gaps: the mechanism is false |
| 7 | Correctness | At least 9 of 10 checked packings agree with the keeper's published value to `1e-9`, every gap explained | 2 or more unexplained gaps |
| 7 | Discrimination | At least 1 of 13 real outside claims does not hold as stated | 0 findings: the notary is a rubber stamp |
| 7 | Breadth | 8 or fewer of 13 real claims land in `cannot_check` | More than 8: too narrow for now |
| 21 | Demand (the deciding number) | At least 2 written "this was useful" replies from 5 distinct recipients | Fewer than 1 reply: nobody wants it, stop |

Every gate prints the volume it processed (for example `planted=10 caught=10`). A gate that processed nothing has
not passed.

## Fixed boundaries

- Nothing is sent by the notary. Wes reads the exact text of every message before it goes, and nothing goes to
  Reddit or X.
- A receipt is not a benefit. A Benefit Ledger row needs a written reply from the recipient, tested against the
  ledger's own rules.
- Our own result is checked first: the README's 2.4% to 5.4% (against `best/scores.json` `record`) and the 0.28% to
  0.73% against `best/submitted.json` `listed` must be reconciled before either number is repeated anywhere new.
