#!/usr/bin/env python3
"""Post-loop dashboard: what was tried, learned, recorded, and what's next.

Every discovery-loop run ends by writing ``loop_summary.json`` (facts the loop
itself knows). This module turns it into three artifacts, all written next to
the summary:

  loop_report.json  - machine-readable report (tried / learned / recorded /
                      next / record_break / publish)
  next_loop.json    - suggestions the next run (or the nightly worker) reads
                      before planning
  dashboard.html    - self-contained human-readable dashboard, no external assets

The publish section only *recommends* outreach. Nothing here contacts anyone:
any email, post, or submission needs wes's explicit approval first.

Usage:
    python3 scripts/loop_report.py --dir RUN_DIR     # RUN_DIR/loop_summary.json exists
    # or, from a loop:  from loop_report import write_all; write_all(run_dir, summary)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)


# ------------------------------------------------------------------ inputs ---

def load_contacts(problem: str) -> dict:
    """Load problems/<problem>/contacts.json; empty shell when absent."""
    path = os.path.join(_REPO_ROOT, "problems", problem, "contacts.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"problem": problem, "clearinghouse": "unknown",
                "contacts": [], "bar": "unset", "checklist": []}


# ---------------------------------------------------------------- analysis ---

def assess_record(summary: dict) -> dict:
    """Decide whether the run broke the best-known record. Honest margins."""
    best = summary.get("best") or {}
    known = summary.get("best_known") or {}
    value = best.get("value")
    known_value = known.get("value")
    higher = bool(best.get("higher_is_better"))
    margin = float(summary.get("win_margin", 0.0))
    out = {
        "metric": best.get("metric"),
        "value": value,
        "best_known": known_value,
        "best_known_source": known.get("source"),
        "higher_is_better": higher,
        "broke": False,
        "note": "",
    }
    if value is None:
        out["note"] = "no candidate produced; nothing to compare."
        return out
    if known_value is None:
        out["note"] = ("no best-known baseline in the repo; this run establishes "
                       "a verified baseline, not a record break.")
        return out
    if higher:
        out["broke"] = value > known_value + margin
    else:
        out["broke"] = value < known_value - margin
    if out["broke"]:
        delta = value - known_value
        out["note"] = (f"BEATS best-known {known_value} by {delta:+.6g} "
                       f"({known.get('source', 'repo table')}).")
    else:
        out["note"] = "did not beat the best-known value."
    return out


def assess_publish(summary: dict, record: dict, contacts: dict) -> dict:
    """Recommend publication outreach only on a fully verified record break.

    Bar: broke the record AND exact verification passed AND the breaker
    survived. Never contacts anyone; the dashboard states that explicitly.
    """
    ver = summary.get("verifications") or {}
    checklist = contacts.get("checklist") or []
    checks = {
        "record_broken": bool(record.get("broke")),
        "exact_verification_passed": bool(ver.get("exact")),
        "breaker_survived": ver.get("breaker") == "survived",
    }
    recommended = all(checks.values())
    if recommended:
        reason = ("Record broken with exact verification and a survived breaker: "
                  "candidate for publication outreach.")
    elif not checks["record_broken"]:
        reason = "No record break, so no publication outreach is warranted."
    else:
        failed = [k for k, v in checks.items() if not v]
        reason = ("Record-level result but verification bar not fully met "
                  f"({', '.join(failed)}); do not contact anyone until it is.")
    return {
        "recommended": recommended,
        "reason": reason,
        "checks": checks,
        "checklist": checklist,
        "bar": contacts.get("bar", "unset"),
        "clearinghouse": contacts.get("clearinghouse", "unknown"),
        "contacts": contacts.get("contacts", []),
        "contact_made": False,
        "note": ("No one has been contacted. Outreach requires wes's explicit "
                 "approval first; this dashboard never sends anything itself."),
    }


def build_report(summary: dict) -> dict:
    """Assemble the full report dict from a loop summary."""
    problem = summary.get("problem", "unknown")
    contacts = load_contacts(problem)
    record = assess_record(summary)
    publish = assess_publish(summary, record, contacts)
    return {
        "problem": problem,
        "run_name": summary.get("run_name"),
        "target": summary.get("target"),
        "seed": summary.get("seed"),
        "status": summary.get("status"),
        "started": summary.get("started"),
        "ended": summary.get("ended"),
        "duration_s": summary.get("duration_s"),
        "tried": summary.get("tried", {}),
        "learned": summary.get("learned", []),
        "verifications": summary.get("verifications", {}),
        "recorded": summary.get("recorded", {}),
        "next_loop": summary.get("next_loop", {"suggestions": []}),
        "record_break": record,
        "publish": publish,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ------------------------------------------------------------------ render ---

_CSS = """
body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;max-width:860px;
margin:2rem auto;padding:0 1.2rem;color:#1c1c1e;background:#fff;line-height:1.55}
.badge{display:inline-block;padding:.25rem .8rem;border-radius:999px;font-weight:600;
font-size:.85rem;margin-right:.5rem}
.ok{background:#e6f4ea;color:#137333}.bad{background:#fce8e6;color:#a50e0e}
.warn{background:#fef7e0;color:#b06000}.muted{background:#f1f3f4;color:#5f6368}
.card{border:1px solid #dadce0;border-radius:12px;padding:1rem 1.2rem;margin:1rem 0}
.card h2{margin:.2rem 0 .6rem;font-size:1.05rem}
.banner{border-radius:12px;padding:1rem 1.2rem;margin:1rem 0;font-weight:600}
.banner.break{background:#e6f4ea;border:2px solid #137333;color:#137333}
.banner.nobreak{background:#f8f9fa;border:1px solid #dadce0;color:#5f6368}
.banner.publish{background:#fef7e0;border:2px solid #b06000;color:#7a4a00}
ul{margin:.4rem 0;padding-left:1.3rem}li{margin:.3rem 0}
.kv{display:grid;grid-template-columns:180px 1fr;gap:.25rem .8rem;font-size:.95rem}
.kv dt{color:#5f6368}.kv dd{margin:0}
code{background:#f1f3f4;padding:.1rem .35rem;border-radius:6px;font-size:.88em}
pre{background:#f8f9fa;border:1px solid #dadce0;border-radius:8px;padding:.8rem;
overflow:auto;font-size:.82rem}
.small{font-size:.85rem;color:#5f6368}
"""


def _esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _badge(text: str, kind: str) -> str:
    return f'<span class="badge {kind}">{_esc(text)}</span>'


def render_dashboard(report: dict) -> str:
    """Render the report as a self-contained HTML page."""
    r = report
    rb = r["record_break"]
    pub = r["publish"]

    status = r.get("status") or "unknown"
    status_kind = "ok" if status == "success" else (
        "warn" if status in ("no_candidate", "adversarial_failed") else "bad")

    if rb["broke"]:
        banner = (f'<div class="banner break">RECORD BREAK: {_esc(rb["metric"])} = '
                  f'{_esc(rb["value"])} {_esc(rb["note"])}</div>')
    else:
        banner = f'<div class="banner nobreak">No record break. {_esc(rb["note"])}</div>'

    if pub["recommended"]:
        contacts = "".join(
            f"<li><b>{_esc(c.get('name', '?'))}</b> — {_esc(c.get('role', ''))}. "
            f"{_esc(c.get('how', ''))} <span class='small'>{_esc(c.get('note', ''))}</span></li>"
            for c in pub["contacts"]
        ) or "<li class='small'>no specific contact on file</li>"
        checklist = "".join(f"<li>{_esc(i)}</li>" for i in pub["checklist"])
        pub_banner = (
            '<div class="banner publish">PUBLISHING RECOMMENDED — '
            f'{_esc(pub["reason"])}</div>'
            '<div class="card"><h2>Publishing</h2>'
            f"<p>Clearinghouse: {_esc(pub['clearinghouse'])}<br>"
            f"Bar: {_esc(pub['bar'])}</p>"
            f"<ul>{contacts}</ul>"
            f"<p><b>Pre-outreach checklist:</b></p><ul>{checklist}</ul>"
            f"<p class='small'>{_esc(pub['note'])}</p></div>"
        )
    else:
        pub_banner = (
            '<div class="card"><h2>Publishing</h2>'
            f"<p>{_esc(pub['reason'])}</p>"
            f"<p class='small'>{_esc(pub['note'])}</p></div>"
        )

    tried = r.get("tried") or {}
    tried_ops = "".join(f"<li><code>{_esc(o)}</code></li>"
                        for o in tried.get("operators", []))
    tried_extra = "".join(f"<li>{_esc(x)}</li>" for x in tried.get("notes", []))
    learned = "".join(f"<li>{_esc(x)}</li>" for x in r.get("learned", []))
    rec = r.get("recorded") or {}
    recorded_items = "".join(f"<li>{_esc(x)}</li>" for x in rec.get("items", []))
    rec_files = "".join(f"<li><code>{_esc(x)}</code></li>" for x in rec.get("files", []))
    suggestions = "".join(f"<li>{_esc(x)}</li>"
                          for x in (r.get("next_loop") or {}).get("suggestions", []))

    ver = r.get("verifications") or {}
    ver_html = ""
    if isinstance(ver, dict):
        ver_html = "<ul>" + "".join(
            f"<li><code>{_esc(k)}</code>: {_esc(v)}</li>" for k, v in ver.items()
        ) + "</ul>"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Loop dashboard — {_esc(r['problem'])} {_esc(r.get('target'))}</title>
<style>{_CSS}</style></head>
<body>
<h1>Discovery-loop dashboard</h1>
<p>{_badge(r['problem'], 'muted')} {_badge('target ' + str(r.get('target')), 'muted')}
{_badge(status, status_kind)}</p>
{banner}
<div class="card"><h2>Run</h2><dl class="kv">
<dt>Run name</dt><dd>{_esc(r.get('run_name') or 'direct (not detached)')}</dd>
<dt>Seed</dt><dd>{_esc(r.get('seed'))}</dd>
<dt>Duration</dt><dd>{_esc(r.get('duration_s'))}s</dd>
<dt>Started</dt><dd>{_esc(r.get('started'))}</dd>
<dt>Report generated</dt><dd>{_esc(r.get('generated_at'))}</dd>
</dl></div>
<div class="card"><h2>What was tried</h2><ul>{tried_ops}{tried_extra}</ul>{ver_html}</div>
<div class="card"><h2>What was learned</h2><ul>{learned or '<li class="small">nothing recorded</li>'}</ul></div>
<div class="card"><h2>What was recorded / updated for next loop</h2>
<ul>{recorded_items or '<li class="small">nothing recorded</li>'}</ul>
{"<p><b>Files:</b></p><ul>" + rec_files + "</ul>" if rec_files else ""}</div>
<div class="card"><h2>Next loop</h2><ul>{suggestions or '<li class="small">no suggestions</li>'}</ul>
<p class="small">Machine-readable: <code>next_loop.json</code> next to this dashboard.</p></div>
{pub_banner}
<p class="small">Generated by <code>scripts/loop_report.py</code>. This dashboard
never sends anything anywhere; publishing outreach needs wes's approval.</p>
</body></html>
"""


# ------------------------------------------------------------------- write ---

def write_all(run_dir: str, summary: dict) -> dict:
    """Write loop_summary.json, loop_report.json, next_loop.json, dashboard.html.

    Returns the report dict. Never raises: dashboard I/O must not fail a run.
    """
    paths = {}
    try:
        os.makedirs(run_dir, exist_ok=True)
        summary_path = os.path.join(run_dir, "loop_summary.json")
        with open(summary_path, "w") as fh:
            json.dump(summary, fh, indent=2, default=str)
        paths["summary"] = summary_path

        report = build_report(summary)
        report_path = os.path.join(run_dir, "loop_report.json")
        with open(report_path, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        paths["report"] = report_path

        next_path = os.path.join(run_dir, "next_loop.json")
        with open(next_path, "w") as fh:
            json.dump(report["next_loop"], fh, indent=2, default=str)
        paths["next_loop"] = next_path

        dash_path = os.path.join(run_dir, "dashboard.html")
        with open(dash_path, "w") as fh:
            fh.write(render_dashboard(report))
        paths["dashboard"] = dash_path
        return {"ok": True, "report": report, "paths": paths}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "paths": paths}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the post-loop dashboard from RUN_DIR/loop_summary.json")
    ap.add_argument("--dir", required=True, help="run directory")
    a = ap.parse_args(argv)
    summary_path = os.path.join(a.dir, "loop_summary.json")
    try:
        with open(summary_path) as fh:
            summary = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {summary_path}: {exc}", file=sys.stderr)
        return 1
    res = write_all(a.dir, summary)
    if not res["ok"]:
        print(f"error: {res['error']}", file=sys.stderr)
        return 1
    rep = res["report"]
    print(f"dashboard: {res['paths']['dashboard']}")
    print(f"record break: {rep['record_break']['broke']}")
    print(f"publish recommended: {rep['publish']['recommended']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
