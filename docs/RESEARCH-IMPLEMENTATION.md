# Research pipeline implementation

Status: Implementation verified, 2026-09-05. Windows task activation awaits the requested operator confirmation.

This extends loop.py, night.py, the problem plugins, and their existing status pages. No separate research engine.

## Acceptance criteria

1. Per-invocation budgets and iteration counts, including generation, review and retrospective usage. Unknown charges reserve the full configured call allowance.
2. Fable and Astra providers return the same response contract; errors never become successful zero-cost work. Single-provider and paired experiments use configured accounting allowances.
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

`call_model(prompt, provider='fable', model=None, timeout=900, max_cost=2.0, ledger=None, purpose='generation')` returns text, code, idea, provider, model, cost, usage and error fields. Accounting includes `billing_mode` and `cost_basis`; failures carry an `error_kind`, including authentication, unavailable, usage_limit or timeout. Defaults are `claude-fable-5-1` and `gpt-6-astra`. Provider selection never silently falls back.

`BudgetLedger` reserves before a call and settles using reported API-equivalent usage, or the full reservation when no estimate is available. Unresolved reservations survive a crash. These amounts are not monthly-subscription bills. Equal configured allowances do not normalize provider token usage.

## Worker boundary

Experiments resolve `discovery-loop-worker:local` to an immutable image ID, record it in `worker_environment`, and reuse it for comparisons and resume. Generated programs run without network access, with read-only roots and inputs, a non-root user, dropped capabilities and bounded CPU, memory, process count and time. Selected plugin helpers and instance data are allowlisted; the whole checkout and credentials are never mounted.

Output and logs have separate bounded temporary filesystems. The host also caps process output, so writing directly to process stdout cannot bypass the container's file limits. Timeout and overflow remove the exact experiment container. There is no host execution fallback.

## Experiments and evidence

The supported command line enters `loop.cli_main()` and `run_research()`. Single-provider and paired modes use the same evaluation machinery. Paired mode starts with independent proposals from one frozen development brief and cross-reviews promising candidates before confirmation.

Run-local files live in `runs/research/<run-id>/<problem>/`. `run.json` records progress. `evidence.json` records hashes, comparisons, usage, limitations and worker identity. Confirmed candidates advance the incumbent with hash-bound `confirmation.json`. Generation history stays development-only; previously exposed targets are never relabeled unseen.

The night runner writes status and dated checkpoints. `scripts/morning-research.py`, not the runner, writes `runs/research/morning.json`. Manual resume is explicit; scheduled catch-up resumes existing checkpoints and does not repeat completed nights. The implemented 14-night cycle gives each research track five Fable, five Astra and four paired nights, with seven occurrences of each research order.

## Dashboard contract

The server listens on localhost, port 8766 by default. Read routes are `GET /api/status` and `GET /api/evidence`; mutations use `POST /api/control`, `POST /api/schedule` and `POST /api/approve`. Host, Origin, CSRF and payload checks protect mutations. Path and symlink checks constrain file access.

Controls persist in `runs/control.json`. Continue clears a pause request without starting work. Morning review is a persistent human bookmark. Schedule tuning validates the same configuration used by the runner. Approvals bind the exact evidence bytes, solver and solution artifacts; they never send or publish by themselves.

## Verification and delivery

Existing tests are not edited. New regression cases must demonstrate failure before the fix when practical. Use `python scripts/check.py` for the supported separated test suites, Ruff and compilation. Provider, worker and dashboard changes also require the relevant live probes. No secret files are read. Existing uncommitted work is preserved and excluded from this delivery. Scheduled tasks are exported before any installation. No external messages are sent during verification.

## Delivery deviations

- The old imported `loop.main()` remains only for compatibility with the unchanged CVRP test that explicitly requires automatic publisher invocation. The supported command line calls `cli_main()`, which produces local evidence. All legacy model and solver helpers now use the same subscription and isolation boundaries; the publication gate rejects calls without exact approvals. Replacing that obsolete assertion remains a pending operator decision.
- Research email is disabled because the separate governed sender cannot bind immutable attachment bytes. Local bundles and exact-commit Git publication are implemented.
- The installed Windows tasks were previewed and backed up, not changed. Their activation and the existing morning delivery integration require the pending explicit confirmation.
- A dashboard restart was rejected by automatic approval review with only 'blocked by policy'. Its currently running instance remains available.

## Live verification evidence

- Both CLI authentication probes confirmed subscription mode, and real Fable generation plus Astra retrospective output completed in an isolated copied checkout.
- The tiny night used a deliberately short research window. Routing and power-grid validation completed; the MIP research stage stopped because the allotted window could not reserve confirmation time. Resume preserved the ledger and skipped completed routing.
- A final real routing evaluation completed with zero model allowance, one isolated worker evaluation, and a recorded immutable Docker image identity.
- Generated output overflow was rejected by the host buffer cap, including a same-UID process-output bypass probe. The exact worker container was removed.
- Desktop/mobile rendering, pause/continue, settings, review and hash-bound approval were verified. Positive approval used a clearly synthetic isolated fixture; real benchmark evidence remains unvalidated unless it passes confirmation.
- Final clean Windows environment: 151 tests passed, 5 optional or unavailable-data checks skipped; Ruff and 48 Python compilations passed. The separate real Docker suite passed all 10 tests.

- Both Windows and Ubuntu CI jobs passed for the shipped pipeline commit `1e4152b`. See the [verification workflow](https://github.com/ucsandman/discovery-loop/actions/workflows/verify.yml) for subsequent changes.
