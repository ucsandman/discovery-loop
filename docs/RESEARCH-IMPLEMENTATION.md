# Research pipeline implementation

Status: Implementation verified, 2026-09-05. Windows tasks activated and the dashboard restarted after operator confirmation on 2026-09-05.

This extends loop.py, night.py, the problem plugins, and their existing status pages. No separate research engine.

## Acceptance criteria

1. Per-invocation budgets and iteration counts, including generation, review and retrospective usage. Unknown charges reserve the full configured call allowance.
2. Subscription routes preserve a common response contract across the four canonical model identities. Errors never become successful zero-cost work; requested trial arms, actual execution identity, fallback, and allowance are recorded separately.
3. Candidate and incumbent use identical target/seed matrices, independent feasibility checking, minimum effect and replication gates. Held-out confirmation data never enters generation prompts.
4. Generated programs execute in disposable, network-disabled Docker workers with read-only inputs and bounded CPU, memory, processes and time. No host execution fallback.
5. Night scheduling has one deadline, an exclusive lock, dated checkpoints, resume, heartbeat, pause, partial-failure status and zero-work detection.
6. A localhost dashboard displays real evidence and supports pause/continue, configuration, evidence review and hash-bound release approval. No automatic external publication.
7. Power-grid tolerance exploitation is blocked by stricter independent evaluation; legacy claims are explicitly unvalidated.
8. Documentation, regression tests, browser QA, live provider probes and a real isolated solver run pass before release.

## Runtime components

| Component | Responsibility |
| --- | --- |
| `providers.py` | Subscription authentication, restricted CLI calls, response parsing and accounting |
| `isolation.py` | Allowlisted inputs, immutable Docker image selection and bounded worker execution |
| `evaluation.py` | Comparable target/seed matrices, independent checks and confirmation gates |
| `loop.py` | Development proposals, cross-review, confirmation and incumbent lineage |
| `research_state.py` | Atomic state, file locks, pause controls and budget reservations |
| `night.py` | Counterbalanced schedule, shared deadline, checkpoints and resume |
| `retro.py` | Opposite-provider retrospectives from sanitized development observations |
| `scripts/morning-research.py` | Sanitized morning report and existing-routine integration |
| `dashboard.py` and `web/` | Local evidence review, tuning and exact-file approval |
| `publish.py` | Independent release revalidation and explicit approved bundle publication |

## Provider and accounting contract

The canonical registry is Fable (`claude-fable-5-1`) and Opus (`claude-opus-5`) in the Anthropic family, plus Astra (`gpt-6-astra`) and Sol (`gpt-5.6-sol`) in the OpenAI family. The transport is family-specific subscription CLI authentication, not an API credential. `call_model(...)` returns text, code, idea, provider, family, model, cost, usage and error fields. Accounting includes `billing_mode` and `cost_basis`; failures carry an `error_kind`, including authentication, unavailable, usage_limit or timeout.

`route_call(...)` makes the execution choice explicit. A route policy is one of `scheduled`, `auto`, `openai_only`, `anthropic_only`, `astra_only`, `fable_only`, or `paired`; its chain contains registry aliases only. For a requested single arm, scheduled and paired routing try the requested model, then same-family alternatives, then the other family. The default chain is Fable, Opus, Astra, Sol. Disabled families are removed before preflight and execution. A malformed model candidate remains a candidate failure and never causes a switch.

`BudgetLedger` reserves before a physical attempt and settles using reported API-equivalent usage, or the full reservation when no estimate is available. Failed started attempts are charged; breaker/configuration skips are zero-charge. Unresolved reservations survive a crash. These amounts are not monthly-subscription bills. Equal configured allowances do not normalize provider token usage.

`RoutingJournal` persists one run-scoped record at `runs/research/<run-id>/routing.json`. It is shared by generation, review, retro, and resume. Authentication/unavailable errors break a family for the remainder of the run; quota, usage-limit, model-unavailable, and classified transient errors break or retry the relevant model as recorded. Both enabled families unavailable ends the stage cleanly. Resume validates the routing policy, chain, and disabled-family set instead of silently changing the experiment.

## Worker boundary

Experiments resolve `discovery-loop-worker:local` to an immutable image ID, record it in `worker_environment`, and reuse it for comparisons and resume. Generated programs run without network access, with read-only roots and inputs, a non-root user, dropped capabilities and bounded CPU, memory, process count and time. Selected plugin helpers and instance data are allowlisted; the whole checkout and credentials are never mounted.

Output and logs have separate bounded temporary filesystems. The host also caps process output, so writing directly to process stdout cannot bypass the container's file limits. Timeout and overflow remove the exact experiment container. There is no host execution fallback.

## Experiments and evidence

The supported command line enters `loop.cli_main()` and `run_research()`. Single-provider and paired modes use the same evaluation machinery. Paired mode starts with independent proposals from one frozen development brief and cross-reviews promising candidates before confirmation.

Run-local files live in `runs/research/<run-id>/<problem>/`. `run.json` records progress. `evidence.json` records hashes, comparisons, usage, limitations and worker identity. Confirmed candidates advance the incumbent with hash-bound `confirmation.json`. Generation history stays development-only; previously exposed targets are never relabeled unseen.

The night runner writes status and dated checkpoints. `scripts/morning-research.py`, not the runner, writes `runs/research/morning.json` with requested arm/mode/eligibility, actual model/family counts, fallback reasons, failed research and retro attempts, paired degradation, and retro status. Manual resume is explicit; scheduled catch-up resumes existing checkpoints and does not repeat completed nights. The implemented 14-night cycle gives each research track five Fable, five Astra and four paired requested arms, with seven occurrences of each research order.

The scheduled arm is historical-trial assignment; the actual execution identity is recorded separately. `trial_report.py` puts evidence without routing records in `historical_unverified`, clean eligible records in `clean_formal_trial`, and known routed but ineligible records in `routing_recorded_ineligible`. A fallback, route/model override, paired degradation, or incomplete retro is excluded from formal comparison while retained for operational reporting.

## Development memory and opportunity ranking

`research_memory.py` is a compact development-only helper, not a training or holdout-feedback system. It parses a candidate and fingerprints its position-free AST; exact AST duplicates can be rejected before evaluation. Comments and whitespace do not affect the fingerprint, while docstrings remain because they can affect behavior. Near-similar changed code is retained.

The prompt projection is bounded and sanitized: development provider, actual model, role, algorithmic idea family, idea, development status, median gain, exact fingerprint, and bounded critique. It removes confirmation, promotion and run outcomes, code, hashes, candidate paths, and hidden targets. Idea-family aggregates retain recurring development outcomes without exposing those fields. Operational statistics group only development attempts by problem, actual model, and role, then count valid, novel, promising, cost, and elapsed-time rates.

Auto allocation prioritizes enabled model-role choices with fewer than three attributable development attempts; only after each enabled choice reaches that threshold can it rank a mature primary. It does not change the fixed routing fallback chain and receives no holdout, confirmation, promotion, or reward feedback. This is capacity and attribution work, not evidence that a model is better.

The local evidence scan covered 31 solver candidates across `runs-cvrp`, `runs-miplib_heur`, and `runs`: 0 syntax failures and 0 exact AST duplicates. It found seven structured CVRP development-history records, but none had actual-model, model, or role fields. The immediate rationale is therefore prospective: cheap duplicate prevention and reliable attribution before allocation. It has not demonstrated saved compute or a discovery gain. Consciously deferred: near-similarity suppression, bandit allocation, additional model calls, and any holdout-fed reward.

## Dashboard contract

The server listens on localhost, port 8766 by default. Read routes are `GET /api/status` and `GET /api/evidence`; mutations use `POST /api/control`, `POST /api/schedule` and `POST /api/approve`. Host, Origin, CSRF and payload checks protect mutations. Path and symlink checks constrain file access.

Controls persist in `runs/control.json`. Continue clears a pause request without starting work. Morning review is a persistent human bookmark. Schedule tuning validates the same configuration used by the runner. Approvals bind the exact evidence bytes, solver and solution artifacts; they never send or publish by themselves.

## Verification and delivery

Existing tests are not edited. New regression cases must demonstrate failure before the fix when practical. Use `python scripts/check.py` for the supported separated test suites, Ruff and compilation. Provider, worker and dashboard changes also require the relevant live probes. No secret files are read. Existing uncommitted work is preserved and excluded from this delivery. Scheduled tasks are exported before any installation. No external messages are sent during verification.

## Delivery deviations

- The old imported `loop.main()` remains only for compatibility with the unchanged CVRP test that explicitly requires automatic publisher invocation. The supported command line calls `cli_main()`, which produces local evidence. All legacy model and solver helpers now use the same subscription and isolation boundaries; the publication gate rejects calls without exact approvals. Replacing that obsolete assertion remains a pending operator decision.
- Research email is disabled because the separate governed sender cannot bind immutable attachment bytes. Local bundles and exact-commit Git publication are implemented.
- Windows task registration and the morning integration were applied after confirmation on 2026-09-05, with rollback XML exported and all four registrations verified.
- The earlier dashboard restart restriction was resolved after operator authorization. The current dashboard runs through its registered task; its loopback listener and rendered configuration were verified.

## Live verification evidence

- Direct subscription probes accepted Astra, Sol, and Opus. A real routed request received Fable's explicit usage-exhaustion response, then completed through Opus; it created two settled attempts, charged 0.002638 accounting units, and left no unsettled reservation. The temporary evidence records a fallback and is therefore formally trial-ineligible. This does not show that Fable is healthy, and no further Fable probes were run.
- The tiny night used a deliberately short research window. Routing and power-grid validation completed; the MIP research stage stopped because the allotted window could not reserve confirmation time. Resume preserved the ledger and skipped completed routing.
- A final real routing evaluation completed with zero model allowance, one isolated worker evaluation, and a recorded immutable Docker image identity.
- Generated output overflow was rejected by the host buffer cap, including a same-UID process-output bypass probe. The exact worker container was removed.
- Desktop/mobile rendering, pause/continue, settings, review and hash-bound approval were verified. Positive approval used a clearly synthetic isolated fixture; real benchmark evidence remains unvalidated unless it passes confirmation.
- Frozen working-source verification passed 221 tests with 4 skips (206 main, 5 CVRP, 10 MIP Open); the isolated pinned-dependency Python 3.12 snapshot passed 220 with 5 skips (205 main, 5 CVRP, 10 MIP Open), where the additional skip was an absent private PGLib input. Ruff was clean and 51 Python files compiled in both checks. The separate real Docker isolation suite passed all 10 tests after rebuilding the existing worker image from pinned requirements. The live dashboard restart rendered the routing surface with zero console or network errors. This does not establish a clean formal trial or a stable Fable quota state.

- Both Windows and Ubuntu CI jobs passed for the shipped pipeline commit `1e4152b`. See the [verification workflow](https://github.com/ucsandman/discovery-loop/actions/workflows/verify.yml) for subsequent changes.
