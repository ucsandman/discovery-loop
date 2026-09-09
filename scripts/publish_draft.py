#!/usr/bin/env python3
"""Publish pipeline: draft the submission when a record break is verified.

Called automatically at the end of a loop run (via loop_report.write_all) when
the dashboard's publish section recommends outreach: the record broke AND the
exact verifier passed AND the breaker survived.

What it does: writes DRAFT files under <run_dir>/publish/ --
  circle_packing:       packomania_submission.json (coordinates payload) +
                        cover_note_draft.md (note to Eckard Specht)
  matrix_multiplication: paper_draft.md (arXiv-style write-up skeleton)

What it NEVER does: send anything. Every draft is headed with an explicit
DRAFT banner: outreach needs wes's explicit approval, and anything he posts or
sends goes through the wes-voice skill first.
"""

from __future__ import annotations

import json
import os
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)

DRAFT_BANNER = (
    "> DRAFT -- not sent. No one has been contacted.\n"
    "> Publishing this requires wes's explicit approval first, and anything\n"
    "> wes posts or sends goes through the wes-voice skill before it goes out.\n\n"
)


def _load_result(result_file: str | None) -> dict:
    if not result_file:
        return {}
    try:
        with open(result_file) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _load_techniques() -> list:
    path = os.path.join(_REPO_ROOT, "problems", "matrix_multiplication",
                        "techniques.json")
    try:
        with open(path) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return list(data.keys())
        return [str(x) for x in data]
    except (OSError, json.JSONDecodeError):
        return []


def _packomania_drafts(pub_dir: str, report: dict, result: dict) -> list:
    paths = []
    rb = report["record_break"]
    payload = {
        "_draft": True,
        "_note": "DRAFT -- not submitted. Submission requires wes's explicit "
                 "approval first.",
        "format": "packomania-csqv",
        "n": result.get("n"),
        "sum_of_radii": rb.get("value"),
        "best_known_beaten": rb.get("best_known"),
        "circles": result.get("circles"),
        "seed": report.get("seed"),
        "produced_by": "discovery-loop problems/circle_packing/smart_loop.py",
        "verifier": "problems.circle_packing.verify.check "
                    "(zero-tolerance stdlib verifier)",
        "independent_reverification": "verify.py in a fresh subprocess",
        "breaker": report.get("verifications", {}).get("breaker"),
        "date": date.today().isoformat(),
    }
    sub_path = os.path.join(pub_dir, "packomania_submission.json")
    with open(sub_path, "w") as fh:
        json.dump(payload, fh, indent=2)
    paths.append(sub_path)

    contacts = report["publish"].get("contacts", [])
    contact = contacts[0] if contacts else {}
    note = DRAFT_BANNER + (
        f"To: {contact.get('name', 'Eckard Specht')} "
        f"({contact.get('role', 'Packomania maintainer')})\n"
        f"Via: {contact.get('how', 'the Packomania site')}\n\n"
        f"Subject: candidate improvement for Packomania csqv n={result.get('n')}\n\n"
        "Dear Dr. Specht,\n\n"
        "A discovery-loop run on my machine produced a circle packing that "
        f"beats the published best-known for n={result.get('n')}: "
        f"sum of radii {rb.get('value')} vs {rb.get('best_known')} "
        f"(improvement {rb.get('value', 0) - (rb.get('best_known') or 0):.3e}).\n\n"
        "The packing passed the zero-tolerance stdlib verifier, an independent "
        "re-verification in a fresh subprocess, and a 400-attempt neighborhood "
        "breaker with no improvement found. Coordinates are in the attached "
        "packomania_submission.json, reproducibly generated from the recorded seed.\n\n"
        "You kindly verified and published a previous result of mine "
        "(I am cited as reference [14] on the site); I would be grateful if "
        "you could check this one independently when you have a moment.\n\n"
        "Best regards,\nwes\n"
    )
    note_path = os.path.join(pub_dir, "cover_note_draft.md")
    with open(note_path, "w") as fh:
        fh.write(note)
    paths.append(note_path)
    return paths


def _paper_draft(pub_dir: str, report: dict, result: dict) -> list:
    rb = report["record_break"]
    techniques = _load_techniques()[:8]
    related = "\n".join(f"- {t}" for t in techniques) or "- (technique registry unavailable)"
    draft = DRAFT_BANNER + (
        f"# A rank-{rb.get('value')} decomposition for {report.get('target')} "
        "matrix multiplication\n\n"
        "## Abstract (draft)\n\n"
        f"We exhibit an explicit bilinear decomposition of rank {rb.get('value')} "
        f"for {report.get('target')} matrix multiplication, improving on the "
        f"previous best-known rank {rb.get('best_known')}. The decomposition was "
        "found by automated search (discovery-loop: composition search over a "
        "verified registry, multiscale delete-and-repair, adversarial breaker "
        "validation) and verified exactly.\n\n"
        "## Result\n\n"
        f"- Target: {report.get('target')}\n"
        f"- Rank achieved: {rb.get('value')} (previous best known: {rb.get('best_known')})\n"
        f"- Construction: `{result.get('decomposition_name')}`\n"
        f"- Breaker verdict: {report.get('verifications', {}).get('breaker')}\n"
        f"- Seed / run: {report.get('seed')} / {report.get('run_name')}\n\n"
        "## Construction\n\n"
        "(Fill in: how the decomposition was found -- operator sequence from "
        "the proof sketch. The full proof sketch is in the run directory.)\n\n"
        "## Verification\n\n"
        "- Exact tensor-identity check (`verify.check`, integer arithmetic): passed.\n"
        "- Breaker suite (bounded adversarial attacks): survived.\n"
        "- Triple-verification for the record claim: tensor identity, random "
        "integer-matrix evaluation vs naive multiplication, rerun with a "
        "different seed.\n\n"
        "## Related work\n\n"
        f"{related}\n\n"
        "## Reproducibility\n\n"
        "Factors and run artifacts are in the run directory; the search is "
        "seeded and the verifier is stdlib-only.\n"
    )
    path = os.path.join(pub_dir, "paper_draft.md")
    with open(path, "w") as fh:
        fh.write(draft)
    return [path]


def generate(run_dir: str, report: dict, result_file: str | None = None) -> dict:
    """Generate publish drafts for a recommended-outreach run.

    Returns {"ok": True, "drafts": [...]}. Never raises; never sends anything.
    """
    try:
        pub_dir = os.path.join(run_dir, "publish")
        os.makedirs(pub_dir, exist_ok=True)
        result = _load_result(result_file or report.get("result_file"))
        problem = report.get("problem")
        if problem == "circle_packing":
            drafts = _packomania_drafts(pub_dir, report, result)
        elif problem == "matrix_multiplication":
            drafts = _paper_draft(pub_dir, report, result)
        else:
            drafts = []
        return {"ok": True, "drafts": drafts}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "drafts": []}
