# data/ — operator-curated prize intake

`data/` is a new top-level directory and it holds one kind of thing: intake that a human curated
and can edit by hand. That is why it is not `runs/` (machine-written run state, safe to delete) and
not `problems/` (plugin code and instance data that the workers read). Deleting `data/` loses
operator work; deleting `runs/prizes/` loses nothing but a cache.

## Files

- `data/prizes.json` — the prize registry. One `prizes[]` entry per challenge, bounty, benchmark or
  record table the lab tracks. Schema version 1; see `prize_registry.validate_prize` for the exact
  field list and the allowed value of every enum.
- `data/prizes/evidence/<date>-<source>.json` — a frozen copy of what was actually observed on that
  date (HTTP status, page wording, address balances, the PDF prize table, the conversion rate used).
  Registry `evidence[].file` points at these.
- `data/prizes/intake/<slug>.json` — candidate entries fetched by `prize_intake.py`. Candidates are
  never part of the registry until an operator approves them.

## What this file is not

Everything in `data/prizes.json` is **untrusted quoted display data**. Prize amounts, deadlines and
"still open" claims are copied from public pages; `prize_registry` stamps every entry
`content_classification: "untrusted_quoted_source"` and a `claim_status` saying the sponsor was not
contacted. Nothing in this directory can make a prize executable: the reviewed bindings that name a
plugin, a baseline, a verifier and the budget ceilings live in `prize_registry.PRIZE_BINDINGS`, in
code. `prize_registry.validate_snapshot` re-derives every admission from that dict, so editing this
JSON can change what is *displayed* but never what is *run*.

No amount here was invented. An entry whose value was not observed carries `estimated_usd: null`
and says why in `estimated_usd_basis`. An entry whose availability was not confirmed carries
`status: "status_uncertain"` or `"probably_active"`, never `"verified_active"`.

## Updating a status

Never hand-edit `status` — it loses the audit trail. Use the CLI, which appends one evidence row and
one history row per changed field and rewrites the file atomically:

```
python prize_registry.py set-status todd-sha256-collision --status verified_active \
  --confidence high --url https://mempool.space/api/address/35Snmmy3uhaer2gTboc81ayCip4m9DT4ko \
  --observed "Address balance 0.27734251 BTC across 10 transactions." --by operator
python prize_registry.py refresh
```

`refresh` re-snapshots into `runs/prizes/registry.json`; it does not fetch anything.
`python prize_registry.py check-sources` is the only command that touches the network: it fetches
the `source_url` already stored in each entry, prints the HTTP status and whether the page still
contains the entry's keyword, writes `runs/prizes/source-check.json`, and never edits this file.

## Safety

No code path submits, claims, emails or spends anything. Bounty addresses appear here only as
quoted public facts; the lab never connects to a wallet, a key or a node. Entries that are not
explicitly authorized public challenges stay `research_priority: "excluded"` with the reason in
`authorization_notes`.
