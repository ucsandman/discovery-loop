# ARC integration deviations

This bridge extends the existing Discovery Loop runner and dashboard. It deliberately does not turn the ARC-AGI-N atlas into a general autonomous solver.

- The upstream catalogue did not initially contain an honest path to the existing CVRP and MIP heuristic plugins. Two benchmark-scoped companion cards were added in the ARC checkout and are the only admitted IDs. Famous conjectures and lab-dependent questions remain visible but non-executable.
- Catalogue refresh reads a sibling checkout instead of pulling from Git. New upstream data enters only after it is present locally, then passes the same bounded schema and hash validation. This avoids executing or trusting fetched repository content during the night.
- Upstream `starterPrompt` and freeform card prose are excluded from model prompts. The executable brief is a small local reviewed mapping; the source card remains quoted display data with uncertain current literature status.
- Disabling a mission skips its existing matching research slot. Choosing a mission moves that slot first and makes the night operationally useful but ineligible for the clean counterbalanced comparison. No new slot, plugin, runner, provider route, verifier, publication path, or allowance was added.
- Scheduled checkpoint IDs gained a `-scheduled` suffix after a real completed manual date-named run exposed an identity collision. Every scheduled date argument is normalized to that namespace before lookup, and the logical evening date is preserved for trial assignment and morning reporting.
- A resumed run preserves the mission file and source hashes captured at its start, but current enable/disable control still governs slots that have not begun. This lets an operator stop a pending mission after pausing without rewriting provenance for work already recorded.
- The dashboard defaults to the two ready missions so morning evidence remains visible. Direct ARC links automatically expose and focus an unsupported requested card without accepting any query payload beyond its validated ID.
