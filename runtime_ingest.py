"""Runtime OBSERVATION ingest for Claude Code Function Hooks.

This module is one stage of a longer pipeline:

    runtime.emit -> observation ingest (this module) -> screening (also here)
    -> hypothesis -> investigation -> experiment -> validation -> promotion

What this module does: read the runtime event log a Claude Code session
writes (plus the shadow-guard comparison rows and the measured-subagent
ledger), screen them for a fixed list of signal families, and shape any hits
into OBSERVATION rows for the research memory this repo already gates.

What this module deliberately does NOT do: it never confirms or promotes an
observation, never changes routing or guard policy, never modifies its own
code, and never calls a model. Every row it writes carries no development
status recognized by ``research_memory`` (see ``OBSERVATION_ROLE`` below), so
it can never be miscounted as a valid, promising, or negative development
result -- those verdicts require a human or the existing gated pipeline.
"""

import argparse
import json
import os

from research_memory import summarize_development
from research_state import append_event

HERE = os.path.dirname(os.path.abspath(__file__))

# The synthetic "problem" this module files its observations under. Runtime
# hook signals are about the harness itself, not any one solver problem.
PROBLEM = "runtime_hooks"

# research_memory's development_status vocabulary has no OBSERVATION member,
# so an observation row is marked through ``role`` instead (a free-form,
# redacted field with no bearing on the valid/novel/promising flags).
OBSERVATION_ROLE = "OBSERVATION"

FAMILY_CLASSIC_VS_MOD_DISAGREEMENT = "classic_vs_mod_disagreement"
FAMILY_GUARD_FALSE_POSITIVE_NEGATIVE = "guard_false_positive_negative"
FAMILY_CACHE_INTERVENTION_OUTCOME = "cache_intervention_outcome"
FAMILY_REPEATED_RETRIES = "repeated_retries"
FAMILY_ROUTING_PREDICTION_ERROR = "routing_prediction_error"
FAMILY_SUBAGENT_ESTIMATE_ERROR = "subagent_estimate_error"
FAMILY_UNEXPECTED_CONTEXT_GROWTH = "unexpected_context_growth"
FAMILY_TOOL_THRASHING = "tool_thrashing"
FAMILY_CAPABILITY_REGRESSION = "capability_regression"

ALL_FAMILIES = (
    FAMILY_CLASSIC_VS_MOD_DISAGREEMENT,
    FAMILY_GUARD_FALSE_POSITIVE_NEGATIVE,
    FAMILY_CACHE_INTERVENTION_OUTCOME,
    FAMILY_REPEATED_RETRIES,
    FAMILY_ROUTING_PREDICTION_ERROR,
    FAMILY_SUBAGENT_ESTIMATE_ERROR,
    FAMILY_UNEXPECTED_CONTEXT_GROWTH,
    FAMILY_TOOL_THRASHING,
    FAMILY_CAPABILITY_REGRESSION,
)

_RETRY_MIN_COUNT = 3
_THRASH_MIN_COUNT = 5
_CONTEXT_GROWTH_RATIO = 0.30
_ESTIMATE_ERROR_RATIO = 0.50
_CAPABILITY_FLAGS = ("toolInterception", "toolResultMutation", "usageSignals")
_AGREEING_DECISIONS = {"deny", "rewrite"}
_OPPOSITE_DECISIONS = {"allow", "deny"}


def read_jsonl(path):
    """Read newline-delimited JSON objects, skipping blank or malformed lines."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _candidate(family, kind, evidence, count, first_seen, last_seen, session, source_path):
    return {
        "family": family,
        "kind": kind,
        "evidence": evidence,
        "count": count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "session": session,
        "source_path": source_path,
    }


def _extent(values):
    present = [value for value in values if value is not None]
    return (min(present), max(present)) if present else (None, None)


def _screen_retries(events, session, source_path):
    groups = {}
    for event in events:
        if not isinstance(event, dict) or event.get("kind") != "ToolRequested":
            continue
        data = event.get("data")
        tool = data.get("tool") if isinstance(data, dict) else None
        if not tool:
            continue
        args_key = json.dumps(data.get("args"), sort_keys=True, default=str)
        group = groups.setdefault((tool, args_key), [])
        group.append(event.get("t"))
    candidates = []
    for (tool, args_key), timestamps in groups.items():
        if len(timestamps) < _RETRY_MIN_COUNT:
            continue
        first_seen, last_seen = _extent(timestamps)
        candidates.append(
            _candidate(
                FAMILY_REPEATED_RETRIES,
                "ToolRequested",
                f"tool={tool} args={args_key} requested {len(timestamps)} times",
                len(timestamps),
                first_seen,
                last_seen,
                session,
                source_path,
            )
        )
    return candidates


def _same_model(requested, actual):
    """A requested alias ("haiku", "opus") names the actual model ("claude-haiku-4-5-20251001")
    when the alias is a token of it; only a real rung change is a prediction error."""
    r = str(requested).lower().strip()
    a = str(actual).lower()
    return r == a or (r and r in a)


def _screen_routing_prediction_error(events, session, source_path):
    groups = {}
    for event in events:
        if not isinstance(event, dict) or event.get("kind") != "SubagentStarted":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        requested = data.get("requestedModel")
        model = data.get("model")
        if not requested or not model or _same_model(requested, model):
            continue
        groups.setdefault((requested, model), []).append(event.get("t"))
    candidates = []
    for (requested, model), timestamps in groups.items():
        first_seen, last_seen = _extent(timestamps)
        candidates.append(
            _candidate(
                FAMILY_ROUTING_PREDICTION_ERROR,
                "SubagentStarted",
                f"requestedModel={requested} actualModel={model}",
                len(timestamps),
                first_seen,
                last_seen,
                session,
                source_path,
            )
        )
    return candidates


def _screen_context_growth(events, session, source_path):
    main_loop = [
        event
        for event in events
        if isinstance(event, dict) and event.get("kind") == "ContextChanged" and not event.get("agentId")
    ]
    jumps = []
    previous = None
    for event in main_loop:
        data = event.get("data")
        tokens = data.get("contextTokens") if isinstance(data, dict) else None
        if not isinstance(tokens, (int, float)) or isinstance(tokens, bool):
            continue
        if previous is not None and previous > 0:
            ratio = (tokens - previous) / previous
            if ratio > _CONTEXT_GROWTH_RATIO:
                jumps.append((event.get("t"), previous, tokens, ratio))
        previous = tokens
    if not jumps:
        return []
    first_seen, last_seen = _extent(item[0] for item in jumps)
    _, before, after, ratio = jumps[0]
    evidence = f"contextTokens jumped from {before} to {after} (+{ratio * 100:.1f}%)"
    return [
        _candidate(
            FAMILY_UNEXPECTED_CONTEXT_GROWTH,
            "ContextChanged",
            evidence,
            len(jumps),
            first_seen,
            last_seen,
            session,
            source_path,
        )
    ]


def _screen_tool_thrashing(events, session, source_path):
    groups = {}
    for event in events:
        if not isinstance(event, dict) or event.get("kind") != "FileObserved":
            continue
        data = event.get("data")
        path = data.get("path") if isinstance(data, dict) else None
        if not path:
            continue
        groups.setdefault(path, []).append(event.get("t"))
    candidates = []
    for path, timestamps in groups.items():
        if len(timestamps) < _THRASH_MIN_COUNT:
            continue
        first_seen, last_seen = _extent(timestamps)
        candidates.append(
            _candidate(
                FAMILY_TOOL_THRASHING,
                "FileObserved",
                f"path={path} observed {len(timestamps)} times",
                len(timestamps),
                first_seen,
                last_seen,
                session,
                source_path,
            )
        )
    return candidates


def _screen_capability_regressions(events, session, source_path):
    hits = {flag: [] for flag in _CAPABILITY_FLAGS}
    for event in events:
        if not isinstance(event, dict) or event.get("kind") != "SessionStarted":
            continue
        data = event.get("data")
        supports = data.get("supports") if isinstance(data, dict) else None
        if not isinstance(supports, dict):
            continue
        for flag in _CAPABILITY_FLAGS:
            if supports.get(flag) is False:
                hits[flag].append(event.get("t"))
    candidates = []
    for flag, timestamps in hits.items():
        if not timestamps:
            continue
        first_seen, last_seen = _extent(timestamps)
        candidates.append(
            _candidate(
                FAMILY_CAPABILITY_REGRESSION,
                "SessionStarted",
                f"supports.{flag} reported false",
                len(timestamps),
                first_seen,
                last_seen,
                session,
                source_path,
            )
        )
    return candidates


def screen_events(events, *, session=None, source_path=None):
    """Screen one session's runtime event log for the event-schema signal families.

    Covers repeated retries, routing prediction error, unexpected context
    growth, tool thrashing, and runtime capability regressions. Shadow-pair
    and measured-subagent families live in ``screen_shadow_pairs``,
    ``screen_cache_interventions``, and ``screen_subagent_estimates`` because
    they read a different row shape than the session event log.
    """
    candidates = []
    candidates.extend(_screen_retries(events, session, source_path))
    candidates.extend(_screen_routing_prediction_error(events, session, source_path))
    candidates.extend(_screen_context_growth(events, session, source_path))
    candidates.extend(_screen_tool_thrashing(events, session, source_path))
    candidates.extend(_screen_capability_regressions(events, session, source_path))
    return candidates


def _last_by_key(rows):
    """Keep only the most recent row per (session, subsystem, key)."""
    latest = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (row.get("session"), row.get("subsystem"), row.get("key"))
        if any(part is None for part in key):
            continue
        latest[key] = row
    return latest


def screen_shadow_pairs(classic_rows, mod_rows, *, source_path=None):
    """Screen classic-guard vs Mod shadow rows joined on (session, subsystem, key).

    A classic 'deny' paired with a mod 'rewrite' agree that a violation
    exists (deny vs rewrite is a remedy choice, not a disagreement) and is
    excluded. Any other decision mismatch is a disagreement candidate; the
    specific case of one side allowing and the other denying is additionally
    flagged as a guard false positive/negative candidate.
    """
    classic_latest = _last_by_key(classic_rows)
    mod_latest = _last_by_key(mod_rows)
    candidates = []
    for key in sorted(set(classic_latest) & set(mod_latest)):
        session, subsystem, row_key = key
        classic_row = classic_latest[key]
        mod_row = mod_latest[key]
        classic_decision = classic_row.get("decision")
        mod_decision = mod_row.get("decision")
        if classic_decision == mod_decision:
            continue
        if {classic_decision, mod_decision} == _AGREEING_DECISIONS:
            continue
        first_seen, last_seen = _extent([classic_row.get("ts"), mod_row.get("ts")])
        evidence = f"subsystem={subsystem} key={row_key} classic={classic_decision} mod={mod_decision}"
        candidates.append(
            _candidate(
                FAMILY_CLASSIC_VS_MOD_DISAGREEMENT,
                "ShadowPair",
                evidence,
                1,
                first_seen,
                last_seen,
                session,
                source_path,
            )
        )
        if {classic_decision, mod_decision} == _OPPOSITE_DECISIONS:
            candidates.append(
                _candidate(
                    FAMILY_GUARD_FALSE_POSITIVE_NEGATIVE,
                    "ShadowPair",
                    evidence,
                    1,
                    first_seen,
                    last_seen,
                    session,
                    source_path,
                )
            )
    return candidates


def screen_cache_interventions(mod_rows, *, source_path=None):
    """Screen mod-side shadow rows for cache-served outcomes (decision == 'serve')."""
    groups = {}
    for row in mod_rows:
        if not isinstance(row, dict) or row.get("side") != "mod" or row.get("decision") != "serve":
            continue
        key = (row.get("session"), row.get("subsystem"), row.get("key"))
        groups.setdefault(key, []).append(row.get("ts"))
    candidates = []
    for (session, subsystem, row_key), timestamps in groups.items():
        first_seen, last_seen = _extent(timestamps)
        candidates.append(
            _candidate(
                FAMILY_CACHE_INTERVENTION_OUTCOME,
                "ShadowMod",
                f"subsystem={subsystem} key={row_key} served from cache {len(timestamps)} times",
                len(timestamps),
                first_seen,
                last_seen,
                session,
                source_path,
            )
        )
    return candidates


def screen_subagent_estimates(rows, *, source_path=None):
    """Screen measured-subagent rows where |predictionError| exceeds half of declared."""
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or row.get("decision") != "measured":
            continue
        declared = row.get("declared")
        prediction_error = row.get("predictionError")
        if not isinstance(declared, (int, float)) or isinstance(declared, bool) or declared <= 0:
            continue
        if not isinstance(prediction_error, (int, float)) or isinstance(prediction_error, bool):
            continue
        if abs(prediction_error) <= _ESTIMATE_ERROR_RATIO * declared:
            continue
        timestamp = row.get("ts")
        candidates.append(
            _candidate(
                FAMILY_SUBAGENT_ESTIMATE_ERROR,
                "SubagentMeasured",
                f"type={row.get('type')} declared={declared} predictionError={prediction_error}",
                1,
                timestamp,
                timestamp,
                row.get("session"),
                source_path,
            )
        )
    return candidates


def to_observation_rows(observations):
    """Shape screened candidates into research_memory's ``_development_entry`` rows.

    Each row goes through ``summarize_development`` -- the same bounding and
    redaction path ``loop.py`` uses for every development record -- so any
    local path or hidden-target text in the evidence is stripped uniformly.
    ``idea_family`` carries the family so a recurring signal survives
    research_memory's 20-row recent window through its family rollup.
    ``role`` is set to ``OBSERVATION_ROLE``: development_status is left unset
    (research_memory then defaults it to "", which is not a valid or
    promising status), so these rows can never read as confirmed or
    promoted.
    """
    rows = []
    for observation in observations:
        idea = (
            f"family={observation['family']} kind={observation['kind']} "
            f"count={observation['count']} session={observation.get('session')} "
            f"first_seen={observation.get('first_seen')} last_seen={observation.get('last_seen')} "
            f"evidence={observation['evidence']} source_path={observation.get('source_path')}"
        )
        record = {
            "problem": PROBLEM,
            "run_id": observation.get("session") or "",
            "idea_family": observation["family"],
            "idea": idea,
            "role": OBSERVATION_ROLE,
        }
        shaped = summarize_development([record], limit=1, family_limit=1)["entries"][0]
        rows.append(shaped)
    return rows


def write_observations(rows, path):
    """Persist shaped observation rows through the repo's existing append-event gate."""
    for row in rows:
        append_event(path, row)


def _default_history_path():
    return os.path.join(HERE, "runs", "research", "development-history", f"{PROBLEM}.jsonl")


def _scan(events_path, shadow_dir, subagents_path):
    events = read_jsonl(events_path) if events_path else []
    session = os.path.splitext(os.path.basename(events_path))[0] if events_path else None
    candidates = list(screen_events(events, session=session, source_path=events_path))

    scanned = {"events": len(events), "shadow_classic": 0, "shadow_mod": 0, "subagents": 0}

    if shadow_dir and os.path.isdir(shadow_dir):
        sessions = set()
        for name in os.listdir(shadow_dir):
            if name.endswith(".classic.jsonl"):
                sessions.add(name[: -len(".classic.jsonl")])
            elif name.endswith(".mod.jsonl"):
                sessions.add(name[: -len(".mod.jsonl")])
        for shadow_session in sorted(sessions):
            classic_path = os.path.join(shadow_dir, f"{shadow_session}.classic.jsonl")
            mod_path = os.path.join(shadow_dir, f"{shadow_session}.mod.jsonl")
            classic_rows = read_jsonl(classic_path)
            mod_rows = read_jsonl(mod_path)
            scanned["shadow_classic"] += len(classic_rows)
            scanned["shadow_mod"] += len(mod_rows)
            candidates.extend(screen_shadow_pairs(classic_rows, mod_rows, source_path=shadow_dir))
            candidates.extend(screen_cache_interventions(mod_rows, source_path=mod_path))

    if subagents_path:
        subagent_rows = read_jsonl(subagents_path)
        scanned["subagents"] = len(subagent_rows)
        candidates.extend(screen_subagent_estimates(subagent_rows, source_path=subagents_path))

    return candidates, scanned


def main(argv=None):
    parser = argparse.ArgumentParser(description="Screen Claude Code runtime hook logs into OBSERVATION rows")
    parser.add_argument("--events", help="path to a session's runtime events JSONL")
    parser.add_argument("--shadow-dir", help="directory of <session>.classic.jsonl / <session>.mod.jsonl pairs")
    parser.add_argument("--subagents", help="path to subagents.jsonl")
    parser.add_argument("--history-path", default=_default_history_path())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    candidates, scanned = _scan(args.events, args.shadow_dir, args.subagents)
    families = {family: 0 for family in ALL_FAMILIES}
    for candidate in candidates:
        families[candidate["family"]] = families.get(candidate["family"], 0) + 1

    written = 0
    if args.write and candidates:
        rows = to_observation_rows(candidates)
        write_observations(rows, args.history_path)
        written = len(rows)

    print(
        json.dumps(
            {
                "scanned": scanned,
                "candidates": len(candidates),
                "families": families,
                "mode": "write" if args.write else "dry-run",
                "written": written,
                "history_path": args.history_path,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
