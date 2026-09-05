# Contributing

Use the [development setup](README.md#developer-setup). Keep changes focused on the existing pipeline and include documentation for changed behavior. No additional frontend framework or service is required for the localhost dashboard.

## Verify a change

```powershell
python scripts/check.py
```

The runner separates legacy plugin tests into fresh interpreters to avoid their bare helper imports colliding. Do not combine those suites in one pytest process or weaken assertions to hide a failure.

For worker changes, build the Docker image and run the optional real-worker checks:

```powershell
python -c "import os, subprocess, sys; env = dict(os.environ, RUN_DOCKER_TESTS='1'); sys.exit(subprocess.call([sys.executable, '-m', 'pytest', 'tests/test_isolation.py', '-q', '-p', 'no:xonsh'], env=env))"
```

For dashboard changes, inspect populated desktop and mobile views and exercise the affected controls. For provider changes, unit mocks supplement a real subscription probe; they do not replace it.

## Preserve the research contract

- Keep candidate and incumbent resources, targets and seeds comparable.
- Recompute feasibility and objectives independently of generated programs.
- Keep confirmation observations out of generation and retrospective feedback.
- Preserve reservations, image identity and evidence lineage on resume.
- Keep generated code inside restricted workers and publication separate from research.
- Label known targets, historical scores and accounting estimates accurately.

Document a concrete failure and its prevention in [errors and lessons](docs/ERRORS.md). Update the [changelog](CHANGELOG.md) when behavior changes. Review staged files for credentials, private data and unrelated work before committing. Use synthetic data for approval fixtures and never send real messages during tests.

This repository currently has no license file. Do not infer an open-source license from public visibility.
