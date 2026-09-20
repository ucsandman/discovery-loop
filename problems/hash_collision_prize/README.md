# hash_collision_prize

Collision-search research on **truncated, salted, synthetic** targets.

> Truncated collisions measure search machinery only; they are not partial progress toward a full collision.

## What a target is

`records.json` holds twelve instances. Each is a digest function (`sha256`, `ripemd160`, or `sha256-reduced` with a
stated round count), a truncation width in bits, and a fixed 16-byte salt derived deterministically from the
target name (`sha256("hash_collision_prize:salt:<name>")[:16]`). A solution is two distinct messages
`m1 != m2` of 1..64 bytes each whose salted digests agree on the first `bits` bits.

| set | targets |
| --- | --- |
| development (`TARGETS`) | `sha256-t28-dev`, `sha256-t32-dev`, `sha256-t36-dev`, `ripemd160-t32-dev` |
| holdout (`VALIDATION`, concealed from prompts) | `sha256-t32-hold`, `sha256-t36-hold`, `ripemd160-t32-hold`, `sha256r24-t32-hold` |
| opt-in large (`--targets` only) | `sha256-t40-large`, `sha256-t44-large`, `ripemd160-t36-large`, `ripemd160-t40-large` |

`reference.baseline_seconds` is the median of three seed-solver runs (seeds 1/2/3) on the authoring machine;
`reference.expected_hashes` is the birthday estimate `sqrt(pi/2) * 2^(bits/2)`. Regenerate both with:

```
python problems/hash_collision_prize/records.py --write
```

## Value and scoring

`evaluate` verifies the collision with `verify.py` and then takes the solver's **self-reported** wall seconds as
the value (lower is better), clamped to `[1e-4, budget + 45]`. The loop's own `secs` per row is the trusted
clock and sits beside every value in evidence. `score` is the negative relative gap to the baseline seconds,
clipped to `[-1, +1]`. `beats()` is always `False`: these are proxies, not records, so no claim can travel
through the win gate, and `validate_release` reports `supported: False`.

## Files

- `verify.py` — `digest`, `truncated_int`, `check`; pure-Python `sha256_rounds` (equals hashlib at 64 rounds)
  and `ripemd160_python` (used automatically when OpenSSL drops RIPEMD-160).
- `records.py` — target specs, deterministic salts, `--write` regenerator.
- `seed_solver.py` — van Oorschot-Wiener distinguished-point search; the trusted baseline.
- `problem.py` — plugin contract, `PRIZE` descriptor, `PRIZE_TARGET_METADATA` (display-only bounty facts).

```
python problems/hash_collision_prize/seed_solver.py --target sha256-t32-dev --time 60 --seed 1 --out result.json
python problems/hash_collision_prize/verify.py result.json
```

## Relationship to the funded bounties

`PRIZE_TARGET_METADATA` records the four funded Peter Todd bounty addresses and scripts observed on
2026-09-20, for display only. They are never targets. Nothing here is submitted anywhere and no code path
accepts a hash, address, or key from a user-supplied source. A generic collision on any of those functions
costs about `2^80` (RIPEMD-160/HASH160) or `2^128` (SHA-256/HASH256) digests; the ladder measures the machinery
at 28..44 bits and nothing more.
