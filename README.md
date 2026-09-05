# discovery-loop

A local research lab for improving optimization solvers with Fable and Astra. Models propose programs; isolated workers execute them; independent mathematical checks and matched-seed experiments decide what survives. Benchmark progress is kept separate from claims of real-world benefit.

## Morning review

Open **dashboard.cmd** on Windows, or visit **http://localhost:8766** when the dashboard is running.

The dashboard shows completed work, incomplete stages, legacy observations, paired evidence, and the 14-night model comparison. You can request a pause, continue research, tune the next night's allowance, inspect evidence, and queue approval for an exact release. Continue clears a pause request; it does not start a new run. Approval is local and does not send messages or push results.

Historical scores remain visible as **unvalidated**. In particular, the earlier power-grid improvement depended on numerical tolerance and is not treated as a scientific discovery.

“Mark for morning review” saves a human review bookmark and includes the problem in the morning report. It does not launch an extra model call.

## Developer setup

Requires Python 3.12, Docker with Linux containers, and the locally installed Claude and Codex CLIs authenticated through their subscriptions.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
docker build -f worker.Dockerfile -t discovery-loop-worker:local .
.venv\Scripts\python.exe dashboard.py --open
```

Runtime and worker dependencies are pinned. No API key is required. Provider preflight rejects API-key authentication and does not silently fall back to API billing. Research calls use `claude -p` with Fable and `codex exec` with Astra, with tools and external integrations disabled.

The default nightly **research allowance is 90 accounting units**, shared across generation, reviews and retrospectives. This is not a cash budget. Claude's reported API-equivalent cost is an estimate of usage; Codex calls without a dollar estimate conservatively consume their reservation. Calls and token usage are retained. Subscription rate limits still apply.

## Running research

```powershell
python night.py --dry-run
python night.py
python night.py --resume
python loop.py --problem cvrp --provider paired --iters 1 --budget 8 --no-publish
python loop.py --problem cvrp --provider astra --eval-only --no-publish
python trial_report.py
```

All normal research runs stop at local evidence. `--no-publish` remains a compatibility flag and makes that intent explicit. Manual loop runs receive separate run identifiers; `--run-id` and `--ledger` connect scheduled work to a shared night. Per-invocation iteration and allowance limits do not count old runs. Resume preserves the existing night's ledger.

A small development-only probe can select `--targets`, lower `--time`, and set `--wall-minutes`. Such a probe is not a claim of performance at the standard benchmark budget. Confirmation requires at least three distinct matched seeds.

## How an experiment works

1. Freeze the incumbent, inputs, comparison scope and resource limits.
2. Give Fable and Astra the same development brief in paired mode. They do not see each other's initial proposals.
3. Run incumbent and candidates in identical restricted workers; recompute objectives and feasibility outside generated code.
4. Cross-review promising candidates. Model opinions never override mathematical checks.
5. Confirm the best candidate on a separate target/seed matrix, requiring a minimum median effect, zero candidate failures, and no increased failure rate.
6. For general MIP heuristics, compare against a freshly executed HiGHS baseline in the same worker environment before making a baseline-superiority claim.
7. Preserve evidence and confirmed lineage for subsequent nights. Feed only development observations and sanitized lessons into future generation.

Known benchmark targets remain labeled previously exposed. The existing MIP heuristic holdout is reusable confirmation data, not a sealed generalization test. There is currently no sealed release dataset.

## Problems

| Plugin | Purpose | Scientific checks |
| --- | --- | --- |
| cvrp | Capacitated vehicle routing | Exact rounded distances, customer coverage and vehicle capacity |
| miplib_heur | General primal heuristics, 16 development and 10 reusable holdout instances | Original MPS feasibility, proven-optimum gap, fresh worker baseline comparison |
| miplib_open | Open mixed-integer programs | Original bounds, integrality, row activities and objective |
| miplib | Legacy open-instance experiments | Original MPS and uncertainty-aware record comparison |
| pglib_opf | AC power-flow validation | Original-case residuals at 1e-8, baseline rounding uncertainty and reference polishing |
| circle_packing | Geometric optimization | Finite values, containment, separation and an explicit improvement margin |

The default nightly trial focuses on routing and general optimization, with a validation-only power-grid stage. See [research portfolio](docs/RESEARCH-PORTFOLIO.md) for intended beneficiaries, success measures, and evidence needed before claiming practical benefit.

Problem helpers use isolated package namespaces. Legacy solvers can still import their documented local helpers inside workers.

## Nightly integration

`night.json` controls an eight-hour window, per-slot and per-call limits, and a 14-night counterbalanced Fable/Astra/paired trial. The runner uses an exclusive lock, checkpoints, heartbeat, pause handling, process-tree timeouts and explicit zero-work/partial/failure statuses.

On Windows, preview the scheduled-task changes first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-night-tasks.ps1
```

The installer exports existing XML before any change. Its `-Apply` switch updates the 22:00 research task, connects the 06:40 meditation and 06:57 briefing to fresh evidence, and installs the localhost dashboard at logon. Rollback commands are printed with the backup paths. Scheduled catch-up is restricted to the overnight window. The original meditation runner is reused with sanitized research context injected in memory; no harness source file is modified.

A missing or partial research run is explicitly reported to meditation. The briefing requires a current meditation artifact rather than silently reusing yesterday's. The existing briefing's external delivery behavior is unchanged; installation does not send a message.

## Evidence and publication

Per-run files live under `runs/research/<run-id>/<problem>/`. `run.json` records progress; `evidence.json` binds the candidate, solution artifacts, paired comparisons and limitations. The shared ledger records reservations and usage. The morning report is numeric and sanitized.

Publication requires a dashboard approval bound to the exact evidence, solver and solution hashes. Changed files invalidate approval. Current reference retrieval and independent revalidation fail closed.

```powershell
python publish.py --problem cvrp --evidence <evidence.json> --approval <approval.json> --dry-run
```

Without `--push-only`, an approved publication command prepares only a local bundle. `--push-only` explicitly commits and pushes the approved bundle after checking the exact committed file set and blob hashes. No research run invokes it automatically. A paired-incumbent improvement is not labeled a world record; record claims must beat the current reference.

Research email is unavailable: the existing governed sender approves file paths and reads their contents later, so it cannot guarantee that approved body and attachment bytes are the ones sent. `--send-email` stops before creating any external action. Restoring email requires immutable snapshots in that separate sender.

## Verification

```powershell
python scripts/check.py
python -m pytest tests/test_isolation.py -q -p no:xonsh
```

`scripts/check.py` runs application tests, each unchanged legacy plugin suite in its own interpreter, Ruff, and compilation. The legacy test modules use bare helper imports, so combining them in one pytest process is not the supported verification entry point. Production multi-plugin loading is covered by shared-process regression tests.

Optional real Docker tests are enabled by `RUN_DOCKER_TESTS=1` in the test process. They exercise resource restrictions, output limits, input/output path checks, network denial and timeout cleanup. Live CLI probes and browser interaction checks supplement unit tests; a mocked subprocess is not proof that a provider or worker works.

The dashboard is an internal localhost surface, not a public website. No external analytics or frontend dependencies are required.

See [decisions](docs/DECISIONS.md), [lessons](docs/ERRORS.md), and [changelog](CHANGELOG.md).
