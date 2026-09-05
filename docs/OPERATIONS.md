# Operations

Follow the [README setup](../README.md#developer-setup), then use its activated virtual environment. The dashboard runs locally at http://localhost:8766; `dashboard.cmd` is the Windows launcher.

## Before a night

```powershell
python night.py --dry-run
```

Inspect the selected trial modes and limits. Real execution performs provider and Docker preflight. Both CLIs must already be authenticated through their subscriptions. API-key and unknown authentication are rejected; there is no paid API fallback. Build the worker image after changing worker dependencies.

The default [schedule](../night.json) allows 480 minutes and 90 accounting units: two research slots receive 40 units each, with 5 units each for retrospectives. Power-grid validation uses no model allowance. The JSON retains legacy `_usd` field names; the numbers are accounting estimates, not additional subscription charges. Claude reports API-equivalent estimates; unavailable estimates consume the reserved allowance. Provider rate limits still apply and stop affected work.

## Run and review

```powershell
python night.py
python trial_report.py
```

The dashboard shows evidence, partial stages, usage and limitations. Pause requests are honored by the runner. Continue clears the pause flag; it does not launch a process. Settings apply to subsequent work. Mark for morning review saves a bookmark, not a model request. Approval records a decision about exact bytes without publishing them.

A confirmed candidate advances the incumbent with confirmation evidence. Development observations and sanitized lessons can inform later proposals. Reused confirmation targets remain disclosed; they are not a sealed test set.

## Resume and diagnose

```powershell
python night.py --resume
```

Resume preserves the dated checkpoint and ledger and skips completed stages. Do not remove a lock or reset accounting to bypass an active run. Inspect `runs/night-status.json`, the dated checkpoint, and `runs/research/<run-id>/<problem>/run.json` when a stage is partial or failed. `evidence.json` records comparisons and the worker image identity. A zero-work result is not success.

Authentication, unavailable CLI, usage-limit and timeout errors have distinct provider classifications. Restore subscription access or worker availability before starting more research. Workers have no host execution fallback. A small `--targets` probe tests development behavior only and cannot establish a benchmark improvement.

## Windows scheduling

Preview without changing task registration:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-night-tasks.ps1
```

The installer exports existing task XML and prints rollback instructions. Activation with `-Apply` remains pending operator confirmation in this installation.

| Task | Prepared behavior |
| --- | --- |
| `discovery-loop-night` | 22:00 research with `--scheduled`, bounded catch-up and an 8h15m scheduler limit |
| `NightlyMeditation` | 06:40, inject sanitized fresh research context into the existing runner |
| `FleetBriefing7am` | 06:57, require a current meditation artifact before the existing briefing |
| `discovery-loop-dashboard` | Start the localhost dashboard at logon |

`--scheduled` accepts starts only between 21:50 and 06:00 local time. After midnight it uses the preceding night's date and caps execution at 06:00. Existing checkpoints resume automatically; completed nights return without new work.

`scripts/morning-research.py` creates `runs/research/morning.json`. Missing or partial research is reported explicitly. The integration preserves the existing briefing's external delivery behavior; activation is separate from running the local report. The meditation wrapper does not edit harness source files.

## Publication

Normal research never publishes. Use the dashboard to inspect evidence and approve exact evidence, candidate and artifact hashes. Then follow the [publication example](../README.md#evidence-and-publication).

An approved command prepares a local bundle by default. Explicit `--push-only` checks the exact committed files and blob hashes before pushing. Changed files invalidate approval. Fresh references and strict independent validation are required. An incumbent improvement is not automatically a world record.

Research email is disabled because the separate sender cannot bind approved immutable body and attachment bytes. `--send-email` fails before any external action.

## Verification

```powershell
python scripts/check.py
```

This runs three test suites in separate interpreters, Ruff and Python compilation. CI runs on Windows and Ubuntu. Optional real-worker tests require Docker and `RUN_DOCKER_TESTS=1` in the test process; see [contributing](../CONTRIBUTING.md). CI does not prove subscription availability or task activation on an operator's machine.
