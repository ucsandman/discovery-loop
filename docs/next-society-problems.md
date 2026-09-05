# Future problem candidates

These are prospective research directions, not implemented modules or a committed roadmap. The current priority is the [routing, general optimization and power-grid validation portfolio](RESEARCH-PORTFOLIO.md).

| Candidate | Research question | Required work before adoption |
| --- | --- | --- |
| Unit commitment | Can a solver find better feasible schedules under a fixed resource budget? | Verify dataset access and licensing, pin formulation and references, independently check every constraint, establish a reproducible baseline. |
| Water-network design | Can candidate pipe designs improve a defined cost objective while satisfying hydraulic constraints? | Curate instance and cost provenance, validate the numerical hydraulic checker, quantify uncertainty, establish independent comparison results. |
| Staff rostering | Can search improve a stated scheduling objective while preserving coverage and rest constraints? | Choose and verify a benchmark specification, implement and cross-check its validator, document fairness limitations and distinguish benchmark scores from staff outcomes. |

The earlier estimates of implementation effort and societal savings were not established by experiments. They are not used to prioritize work or claim impact. Dataset availability, reference values, maintenance status and licensing must be checked again before adding a module.

Admission requires an independent verifier, a reproducible baseline, disclosed development and confirmation splits, bounded worker execution and a concrete beneficiary-facing success measure. Operational use requires separate domain validation and human review.
