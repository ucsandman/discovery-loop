"""One bounded model call that turns a losing candidate into a mechanism-level negative result.

Rejections are the majority of what a night produces: of the 200 candidates recorded between 2026-08-31 and
2026-09-20, 112 were rejected and 4 failed evaluation outright, and none of them was ever reviewed -- the
critic only ran on candidates that passed.  What reached the next prompt was the loop's own one-line verdict
("rejected", "N development evaluation failures"), which names no mechanism, so the same family came back:
four near-identical "granular swap* layered on the existing SISR/SA search" proposals across four nights.

This module asks the reviewing model, once per losing candidate worth the call, what specifically failed.
Its answer is recorded as that candidate's negative result, which is what the next generation prompt reads.
"""

from __future__ import annotations

import difflib
import re

from research_memory import redact_targets, strip_local_paths

MECHANISM = re.compile(r"^\s*MECHANISM\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
RETRY = re.compile(r"^\s*RETRY\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
DIFF_LINES = 120
DIFF_CHARS = 6000


def worth_reviewing(record):
    """Whether a losing candidate carries enough signal to be worth one call.

    A crash names a mechanism nobody has read yet.  A near miss -- ahead on the median but short of the
    gate, or ahead on some targets and behind on others -- is the case where the next proposal is most
    likely to be a blind repeat.  A candidate that never cleared the screen, or that never parsed, already
    has its whole story in the status.
    """
    status = record.get("status")
    if status == "evaluation_failed":
        return True
    if status != "rejected":
        return False
    comparison = record.get("comparison")
    if not isinstance(comparison, dict):
        return False
    gains = [pair.get("gain") for pair in comparison.get("pairs") or []]
    gains = [gain for gain in gains if isinstance(gain, (int, float))]
    if not gains:
        return False
    return comparison.get("median_gain", 0.0) > 0 or (any(g > 0 for g in gains) and any(g < 0 for g in gains))


def candidate_diff(parent, code, *, max_lines=DIFF_LINES, max_chars=DIFF_CHARS):
    """A bounded unified diff of the candidate against the file it was written from."""
    lines = list(
        difflib.unified_diff(
            (parent or "").splitlines(),
            (code or "").splitlines(),
            fromfile="parent/solver.py",
            tofile="candidate/solver.py",
            lineterm="",
            n=2,
        )
    )
    truncated = len(lines) > max_lines
    text = "\n".join(lines[:max_lines])
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    if truncated:
        text += "\n... diff truncated ..."
    return text


def build_prompt(record, diff, cells, error, hidden_targets=()):
    """Ask for the failed mechanism in two lines. No incumbent code, no targets beyond development."""
    outcome = [f"status: {record.get('status')}", f"loop verdict: {record.get('negative_result') or '(none)'}"]
    comparison = record.get("comparison") if isinstance(record.get("comparison"), dict) else {}
    if isinstance(comparison.get("median_gain"), (int, float)):
        outcome.append(
            f"median gain across {len(comparison.get('pairs') or [])} paired cells: {comparison['median_gain'] * 100:+.3f}%"
        )
    if isinstance(comparison.get("median_lower_bound"), (int, float)):
        outcome.append(f"10th-percentile bound on that median: {comparison['median_lower_bound'] * 100:+.3f}%")
    if cells:
        outcome.append(f"per-target median gain: {cells}")
    if error:
        outcome.append(f"solver error: {error}")
    prompt = f"""You are reviewing one solver candidate that did not beat its incumbent. Development evidence only; do
not recommend publication and do not propose a whole new algorithm.

IDEA AS PROPOSED:
{record.get("idea") or "(none recorded)"}

WHAT IT CHANGED (unified diff against the solver it was written from):
```diff
{diff or "(no diff available)"}
```

MEASURED OUTCOME:
{chr(10).join(outcome)}

Name what actually failed, at the level of the mechanism in the diff, not the label on the idea. Answer in
exactly two lines and nothing else:
MECHANISM: <one sentence: the specific mechanism that failed and the evidence above that shows it>
RETRY: <"no" plus why, or one concrete change to that mechanism that would address the observed failure>"""
    return strip_local_paths(redact_targets(prompt, hidden_targets))


def parse(text, hidden_targets=(), limit=200):
    """The two allowlisted lines, sanitized and bounded. Anything else the model wrote is dropped."""
    text = text or ""
    mechanism = MECHANISM.search(text)
    retry = RETRY.search(text)

    def clean(match):
        if not match:
            return ""
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        return strip_local_paths(redact_targets(value, hidden_targets))[:limit]

    return {"mechanism": clean(mechanism), "retry": clean(retry)}


def negative_result(reason, mechanism, limit=240):
    """The loop's own verdict, then the reviewed mechanism, inside the memory field's budget."""
    if not mechanism:
        return (reason or "")[:limit]
    combined = f"{reason} -- reviewed: {mechanism}" if reason else f"reviewed: {mechanism}"
    return combined[:limit]
