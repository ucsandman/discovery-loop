# Research portfolio

The first 14-night trial compares Fable-only, Astra-only and paired research with the same slot allowance and solver resources. Accounting differs between providers and does not normalize tokens or subscription consumption. The comparison is exploratory: the small number of nights does not establish a model ranking.

| Track | Intended beneficiary | Measured now | Evidence required before claiming benefit |
| --- | --- | --- | --- |
| Capacitated routing | Operators of delivery services, including food banks | Verified route length and capacity feasibility at equal compute, repeatability across seeds | New operational instances with consent, delivery windows and service requirements represented, measured route savings without reduced service |
| General primal heuristics | Users of open optimization software | Feasible objective gap, failure rate and runtime against an incumbent on matched cases and seeds | Reproduced gains against a fresh same-worker HiGHS baseline, withheld instance families, reproducible solver code and upstream review |
| AC power flow validation | Researchers evaluating grid optimization | Original-case feasibility residuals, numerical tolerance sensitivity and reference-polish outcomes | Improvements surviving strict original constraints and an independent reference solver; operational validation before any grid deployment |
| Elliptic-curve discrete logarithm ladder (`ecc_prize`) | Researchers measuring generic ECDLP search machinery | Wall time to a verified discrete logarithm on generated 24–48 bit curves, the iteration ratio against the rho estimate, and the fitted scaling exponent | Unvalidated and ladder-only. The instances are generated in this repository, so there is no public record and `beats()` is always false; a claim about any real challenge instance would need a public benchmark, an independent implementation and external review |
| Truncated hash collision ladder (`hash_collision_prize`) | Researchers measuring collision-search machinery | Wall time to a verified collision on salted, truncated digests at 28–44 bits, digests per second against the birthday estimate, and the fitted scaling exponent | Unvalidated and ladder-only. Truncated collisions measure search machinery only; they are not partial progress toward a full collision, and no result is submitted anywhere |

## Morning decisions

Continue a track when experiments test distinct mechanisms and produce useful evidence. Pause it when repeated mechanisms fail, the verifier is suspect, the reference baseline is not comparable, or budget buys no completed experiments. Negative results are valid outputs when they eliminate a concrete hypothesis.

## Trial measures

Report the configured and observed date windows, expected/missing/completed slots, attempted and successful physical generation/critique calls, conservative allowance charged, provider-reported API-equivalent estimates where available, solver evaluations, elapsed compute, candidate failure rate and confirmed effect size. Clean summaries require the scheduled arm, completed research and retro, eligible actual routing and a successful physical generation call. Do not rank providers by unverified wins, partial cycles, summed historical champions, model self-assessment, or estimated dollar charges.

## Release boundary

A known-instance record can be a legitimate benchmark result without establishing algorithmic generality. Reusable holdouts provide limited confirmation and are disclosed as such. No previously exposed target is renamed a sealed test.

The optional CVRP release check freezes one candidate and baseline before generating six fresh synthetic cases, then permits one matched evaluation. It remains separate from routine research, prompts, retrospectives, adaptive allocation and promotion. Its outcome is descriptive synthetic evidence, not proof on unseen public benchmarks, a world record, operational benefit, publication approval or protection from a malicious host. Real-world deployment, outreach and public claims require separate review.
