# ARC scheduled integration

The nightly discovery-loop run prepares a local ARC catalogue snapshot. The
morning report may expose only fixed ARC state: catalogue freshness, numeric
source and mission counts, and admitted mission IDs. It never includes ARC
prose, URLs, evidence contents, filesystem paths, or model output.

`runs/arc/catalogue.json` is the current local snapshot. Its `source.file_count`
and `problems` provide numeric counts. `runs/arc/refresh-status.json` has the
fixed `fresh`, `stale`, or `unavailable` status plus `attempted_at` and
`problem_count`. `runs/arc/control.json` provides the explicit `enabled_ids`
allowlist and optional `next_id` selection. Only catalogue cards marked
`admission.status: ready` can be counted or selected.

When no persisted control exists, the canonical ARC control loader enables all
reviewed-ready IDs. The morning report calls those IDs admitted, but still
requires expected-run evidence before it exposes a selected ID.

For a selected ID to appear in a morning report, its expected-run
`runs/research/<run_id>/<plugin>/evidence.json` must contain loop's `mission`
binding with the local reviewed plugin, catalogue hash, and source revision.
Missing, stale, malformed, or failed ARC files leave the normal morning flow intact and produce zero
selected IDs. The report never copies card titles, URLs, evidence contents,
source prose, or model output.

`scripts/install-night-tasks.ps1` previews an optional
`discovery-loop-arc-atlas` at-logon task. It is eligible only when the sibling
`arc-agi-n` checkout already has Node dependencies and a production `.next`
build. With `-Apply`, the task runs at limited user level, ignores concurrent
starts, binds ARC to `127.0.0.1:3100`, opens no browser, and uses no installer,
build, paid service, or outbound action. Existing task XML is backed up and is
the rollback source; a newly created ARC task can be unregistered during a
failed apply.
