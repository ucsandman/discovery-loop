# Research pipeline implementation

Status: Implementation verified, 2026-09-05. Windows task activation awaits the requested operator confirmation.

This extends loop.py, night.py, the problem plugins, and their existing status pages. No separate research engine.

## Acceptance criteria

1. Per-invocation budgets and iteration counts, including generation, review and retrospective usage. Unknown charges reserve the full configured call allowance.
2. Fable and Astra providers return the same response contract; errors never become successful zero-cost work. Equal-budget single-provider and paired experiments are available.
3. Candidate and incumbent use identical target/seed matrices, independent feasibility checking, minimum effect and replication gates. Held-out confirmation data never enters generation prompts.
4. Generated programs execute in disposable, network-disabled Docker workers with read-only inputs and bounded CPU, memory, processes and time. No host execution fallback.
5. Night scheduling has one deadline, an exclusive lock, dated checkpoints, resume, heartbeat, pause, partial-failure status and zero-work detection.
6. A localhost dashboard displays real evidence and supports pause/continue, configuration, evidence review and hash-bound release approval. No automatic external publication.
7. Power-grid tolerance exploitation is blocked by stricter independent evaluation; legacy claims are explicitly unvalidated.
8. Documentation, regression tests, browser QA, live provider probes and a real isolated solver run pass before release.

## Shared integration contracts

Parent owns research_state.py, publish.py, documentation, packaging and final integration.

research_state.py exposes atomic_json(path, data), read_json(path, default=None), append_event(path, data), FileLock(path), BudgetLedger(path, limit), BudgetExceeded, and paused(root).
BudgetLedger.remaining is available allowance; .spent is charged accounting usage; reserve(amount, label) returns reservation id (raises BudgetExceeded); settle(id, cost=None, usage=None) records the reported API-equivalent estimate, otherwise the full reserved amount. These are not monthly-subscription bills. Constructors and writes lock atomically.

providers.py exposes call_model(prompt, provider='fable', model=None, timeout=900, max_cost=2.0, ledger=None, purpose='generation') returning a dict: text, code, idea, provider, model, cost (number or null), usage (dict), error (string or null). Probe uses the same callable. Models default to claude-fable-5-1 and gpt-6-astra. Provider selection never silently falls back. CLI-only, no new API billing.

isolation.py exposes run_solver(problem, solver, target, budget, seed, out, root=None, image=None, deadline=None) returning subprocess-like returncode/stdout/stderr; raises on timeout/unavailable sandbox. Inputs are allowlisted plugin files and instance data, never the entire checkout/home. Container writes only its dedicated output directory. Parent plugin evaluation remains outside the generated process. preflight(root=None) returns a dict with ok and details. Docker image discovery-loop-worker:local.

loop.py retains legacy helper signatures used by existing tests. New arguments: --provider fable|astra|paired, --run-id ID, --ledger PATH, --call-budget NUMBER, --seed-count NUMBER, --min-effect NUMBER, --no-publish, --evidence-root PATH. Its default canonical execution is isolated. Run-local evidence lives under runs/research/<run-id>/<problem>/, with run.json and evidence.json; paths recorded in evidence are repo-relative. Evidence includes run_id, problem, provider, status, candidate_hash, candidate_path, confirmed, publishable, development/confirmation metrics, usage, limitations and timestamps. Confirmation gating must distinguish known benchmark tuning from generalization; old visible targets are never relabeled unseen. Generation history remains development-only. The loop must stop for runs/control.json paused=true and share the night ledger.

night.py preserves callable publish_slot and retro_slot compatibility but never invokes publishing automatically in the new pipeline. Schedule includes global minutes/budget, slot limits and provider modes; execution defaults local-only. Writes runs/night-status.json and a sanitized runs/research/morning.json for the existing briefing. CLI --resume resumes the same run without resetting its ledger. Plans a 14-night balanced fable/astra/paired trial.

dashboard.py serves localhost only, default port 8766, with GET /api/status, GET /api/evidence, POST /api/control, POST /api/schedule, POST /api/approve. Same-origin/Host checks, CSRF token and strict payload validation are mandatory. Controls write runs/control.json and approvals store exact evidence and candidate hashes; approval is not external sending. The page explains that approved evidence is ready for separate publication. UI files under web/; no framework or CDN dependencies. Dashboard reads the existing night/status/evidence outputs.

## Ownership

- Core agent: loop.py, evaluation.py, new tests/test_evaluation.py and tests/test_research_loop.py.
- Providers agent: providers.py, isolation.py, worker.Dockerfile, worker-requirements.txt, tests/test_providers.py, tests/test_isolation.py.
- Night agent: night.py, night.json, retro.py, tests/test_night.py, tests/test_retro.py, scripts/install-night-tasks.ps1, scripts/morning-research.py.
- Science agent: problems/** source files, problem_loader.py, tests/test_problem_integrity.py. Do not edit existing tests or saved best solvers.
- UI agent: dashboard.py, web/**, tests/test_dashboard.py.

## Verification and delivery

Existing tests are not edited. New regression cases must demonstrate failure before the fix when practical. Run full pytest, Ruff, compilation, provider probes, a sandbox escape negative test, real solver evaluation and browser interaction tests. No secret files are read. Existing uncommitted work is preserved and excluded from this delivery. Scheduled tasks are exported before any installation. No external messages are sent during verification.

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
