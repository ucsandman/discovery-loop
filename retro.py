"""Retro: after a slot, one model call turns the run into a written record so the next night does not redo it.

Reads the problem's whole history (every idea ever tried, its verdict and score delta), the scoreboard against the
live records and the champion solver, and appends a dated section to docs/retro/<problem>.md with WHAT WORKED,
WHAT DIDN'T (and why), LESSONS and NEXT: five directions that differ in kind, at least two far from anything tried,
each with why it could beat the best-known and how we would know it failed. The brainstorming rules from the
superpowers brainstorming skill are in the prompt. loop.py feeds the latest LESSONS and NEXT back into every
iteration prompt (read_latest_retro), and the IDEA line tags which NEXT direction it took, so the following retro
sees what was consumed.

night.py runs this after each slot, before publish.py. By hand:
  python retro.py --problem cvrp                  # retro over the last 12 iterations
  python retro.py --problem cvrp --since-iter 5   # retro over iterations 5 and later
  python retro.py --problem cvrp --dry-run        # print the prompt, no model call, no file write
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from loop import Loop, load_problem, retro_path, value_of
from research_state import BudgetLedger, append_event, atomic_json, read_json

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "claude-fable-5-1"
TIMEOUT = 900

BRAINSTORM_RULES = """BRAINSTORMING RULES (from the superpowers brainstorming skill, applied to a solver, not a product):
- Understand before proposing: say in one line what the scoreboard and the tried list actually show about where the
  gap to the best-known lives (which targets, what size, whether it is search, construction, time or numerics).
- Propose directions that differ in KIND, not variations of one theme. Cover at least: a different algorithm family,
  a different allocation of the time budget, a different solution representation or move set, something that
  exploits structure specific to the worst instances, and a robustness/verification change that stops a class of
  wasted iterations. At least two directions must be far from anything in the tried list.
- For each direction give the trade-off and the failure mode up front, not only the upside.
- Lead with the recommendation: NEXT #1 is the one you would run first, and say why in one sentence.
- YAGNI: cut anything that does not serve beating a listed best-known value. No speculative infrastructure.
- Do not repeat an idea from the tried list unless you name the specific failure it fixes and why that fixes it."""


def history_lines(history):
    """One compressed line per iteration, all time, so cross-night repeats are visible in one screen."""
    out = []
    for h in history:
        idea = (h.get("idea") or "").replace("\n", " ")
        line = f"iter {h['iter']} [{h['status']}] total={h['total']:.4f}: {idea[:160]}"
        if h.get("wins"):
            line += f" WINS={h['wins']}"
        if h.get("errors"):
            line += f" ERRORS={h['errors'][:100]}"
        out.append(line)
    return "\n".join(out) or "(none yet)"


def build_retro_prompt(P, name, history, board, champ, since_iter):
    this_run = [h for h in history if h["iter"] >= since_iter]
    champions = [h for h in this_run if h["status"] == "champion"]
    spend = sum(h.get("cost", 0) for h in this_run)
    return f"""You are writing the retro for one night's run of an evolutionary solver loop on the {name} benchmark. An LLM
proposes a solver change each iteration, the loop runs it on every target, an independent checker scores it, and
it is kept only if the total beats the champion. The goal is to beat a published best-known value on at least
one target. Your job is to make sure tomorrow's run does not repeat tonight's, and to hand it creative directions.

PROBLEM CONTEXT:
{P.PROMPT[:3000]}

SCOREBOARD NOW ({"higher" if P.MAXIMIZE else "lower"} is better; champion total = {P.TOTAL_DESC}):
{board}
THIS RUN: iterations {since_iter}+ ({len(this_run)} iterations, {len(champions)} became champion,
reported total_cost_usd API-equivalent {spend:.2f}; subscription billing is not measured here)

EVERY IDEA TRIED ON THIS PROBLEM, ALL TIME (iteration, verdict, total, idea):
{history_lines(history)}

CURRENT CHAMPION solver.py:
```python
{champ}
```

{BRAINSTORM_RULES}

OUTPUT FORMAT, markdown, exactly these four headings and nothing before the first one:
### What worked
- one bullet per change that became champion or improved a target this run, with the mechanism (why it helped)
### What didn't
- one bullet per rejected idea this run, with the most likely reason it failed (timeout, worse search, numerics,
  bug in the change, budget spent on the wrong targets). Group near-duplicates and say they are duplicates.
### Lessons
- three to six one-line lessons a future iteration must respect (what to stop doing, what the instances reward,
  where the time goes). Each must be checkable against the tried list or the scoreboard.
### Next
1. [kind: <algorithm family | time allocation | representation | instance structure | robustness>] <direction in
   two sentences>. Why it could beat best-known: <one sentence>. Failed if: <the observable outcome that says so>.
2. ... five entries total, numbered, in the order you would run them."""


def call_text(prompt, model=MODEL):
    """Legacy text interface through the canonical subscription-only provider."""
    from providers import call_model

    result = call_model(prompt, provider="fable", model=model, timeout=TIMEOUT)
    return result["text"], result["cost"] or 0.0, result["error"] or ""


def section_header(name, history, since_iter, board_wins):
    this_run = [h for h in history if h["iter"] >= since_iter]
    champ = max([h["total"] for h in history if h["status"] in ("champion", "seed")], default=float("nan"))
    spend = sum(h.get("cost", 0) for h in this_run)
    iters = f"iters {this_run[0]['iter']}-{this_run[-1]['iter']}" if this_run else "no iterations"
    wins = ", ".join(board_wins) if board_wins else "none"
    return (
        f"## {time.strftime('%Y-%m-%d %H:%M')} {name}: {iters}, reported total_cost_usd API-equivalent "
        f"{spend:.2f}, champion {champ:.4f}, beating best-known: {wins}"
    )


def append_section(path, header, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            title = os.path.splitext(os.path.basename(path))[0]
            f.write(f"# Retro: {title}\n\nAppended by retro.py after every night slot, newest at the bottom. ")
            f.write("loop.py reads the last section's Lessons and Next into every iteration prompt.\n")
        f.write(f"\n{header}\n\n{body.strip()}\n")


def _iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def cross_model_provider(generation_provider, run_id):
    """Return an independent analyst for a single or paired generation run."""
    if generation_provider == "fable":
        return "astra"
    if generation_provider == "astra":
        return "fable"
    try:
        ordinal = datetime.strptime(run_id, "%Y-%m-%d").date().toordinal()
    except ValueError:
        ordinal = sum(ord(char) for char in run_id)
    return "fable" if ordinal % 2 == 0 else "astra"


def build_research_retro_prompt(evidence, development_history=None):
    """Build an analyst prompt without confirmation data, code or local paths."""
    summary = {
        key: evidence.get(key)
        for key in (
            "run_id",
            "problem",
            "provider",
            "status",
            "candidate_hash",
            "usage",
        )
    }
    history = development_history or []
    return f"""Act as an independent optimization research analyst. Review the structured evidence below. The
generation provider was {evidence.get("provider")}; do not trust its interpretation. Use development evidence only.
No held-out target, confirmation metric, candidate code, or local path is present. Identify missing work and failed
stages, and do not recommend publication.

RUN METADATA:
{json.dumps(summary, indent=2, sort_keys=True)}

SANITIZED CROSS-NIGHT DEVELOPMENT HISTORY:
{json.dumps(history[-200:], indent=2, sort_keys=True)}

Return markdown with exactly these headings:
### Evidence assessment
State what completed and whether the evidence supports a real effect.
### Failure analysis
List model, evaluation, replication, budget, or data gaps. If none, say none observed.
### Next experiment
Give one bounded next experiment with a falsifiable stop condition.
### Limitations
List what this run cannot establish."""


def run_research_retro(problem, run_id, evidence_root, ledger_path, call_budget, provider=None):
    """Write a local retrospective record even when the analyst call fails."""
    from providers import call_model

    root = Path(evidence_root)
    if not root.is_absolute():
        root = Path(HERE) / root
    problem_root = root / run_id / problem
    evidence = read_json(problem_root / "evidence.json", {}) or {}
    history_path = root / "development-history" / f"{problem}.jsonl"
    history = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines()[-200:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                critique = item.get("critique") if isinstance(item.get("critique"), dict) else {}
                history.append(
                    {
                        "run_id": item.get("run_id"),
                        "iteration": item.get("iteration"),
                        "provider": item.get("provider"),
                        "idea": item.get("idea"),
                        "status": item.get("status"),
                        "median_gain": item.get("median_gain"),
                        "candidate_hash": item.get("candidate_hash"),
                        "critique": {
                            "provider": critique.get("provider"),
                            "text": critique.get("text"),
                            "error": critique.get("error"),
                        },
                    }
                )
    generated_by = evidence.get("provider") or "paired"
    analyst = provider or cross_model_provider(generated_by, run_id)
    if generated_by in {"fable", "astra"} and analyst == generated_by:
        raise ValueError("retrospective analyst must differ from the generation provider")
    started = _iso()
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "problem": problem,
        "status": "failed",
        "provider": analyst,
        "model": None,
        "reported_total_cost_usd_api_equivalent": None,
        "usage": {},
        "analysis": "",
        "limitations": [],
        "started_at": started,
    }
    if not evidence:
        result["limitations"].append("research evidence is missing")
    elif evidence.get("status") not in {"completed", "partial"}:
        result["limitations"].append("research stage did not complete successfully")
    try:
        ledger_state = read_json(ledger_path, {}) or {}
        ledger_limit = float(ledger_state.get("limit", 90.0))
        ledger = BudgetLedger(ledger_path, ledger_limit)
        response = call_model(
            build_research_retro_prompt(evidence, history),
            provider=analyst,
            timeout=900,
            max_cost=float(call_budget),
            ledger=ledger,
            purpose=f"retro:{problem}",
        )
        result.update(
            model=response.get("model"),
            reported_total_cost_usd_api_equivalent=response.get("cost"),
            usage=response.get("usage") or {},
            analysis=(response.get("text") or "").strip(),
        )
        if response.get("error"):
            result["limitations"].append("analyst model call failed")
        elif not result["analysis"]:
            result["limitations"].append("analyst returned no text")
        else:
            result["status"] = "completed"
    except Exception as exc:
        result["limitations"].append(f"analyst stage failed: {type(exc).__name__}")
    result["finished_at"] = _iso()
    atomic_json(problem_root / "retro.json", result)
    append_event(
        history_path,
        {
            "run_id": run_id,
            "iteration": "retro",
            "provider": analyst,
            "idea": "",
            "status": "retrospective",
            "median_gain": None,
            "candidate_hash": evidence.get("candidate_hash"),
            "critique": {
                "provider": analyst,
                "text": result["analysis"][:2000],
                "error": None if result["status"] == "completed" else "; ".join(result["limitations"]),
            },
        },
    )
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", required=True)
    ap.add_argument("--since-iter", type=int, default=None, help="first iteration of the run being reviewed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--run-id", help="dated research run; enables the bounded run-local retro")
    ap.add_argument("--evidence-root", default="runs/research")
    ap.add_argument("--ledger")
    ap.add_argument("--provider", choices=("fable", "astra"))
    ap.add_argument("--call-budget", type=float, default=2.5)
    a = ap.parse_args()
    if a.run_id:
        configured_root = Path(a.evidence_root)
        evidence_root = configured_root if configured_root.is_absolute() else Path(HERE) / configured_root
        ledger_path = Path(a.ledger) if a.ledger else evidence_root / a.run_id / "budget.json"
        evidence = read_json(evidence_root / a.run_id / a.problem / "evidence.json", {}) or {}
        if a.dry_run:
            print(build_research_retro_prompt(evidence))
            return 0
        result = run_research_retro(
            a.problem,
            a.run_id,
            evidence_root,
            ledger_path,
            a.call_budget,
            provider=a.provider,
        )
        print(json.dumps({key: value for key, value in result.items() if key != "analysis"}, indent=2))
        return 0 if result["status"] == "completed" else 1
    P = load_problem(a.problem)
    L = Loop(a.problem)
    history = [json.loads(l) for l in open(L.log_path, encoding="utf-8")] if os.path.exists(L.log_path) else []
    if not history:
        print("retro: no history, nothing to review")
        return 1
    since = a.since_iter if a.since_iter is not None else max(0, history[-1]["iter"] - 11)
    try:
        rec = P.records_fetch()
    except Exception as e:
        rec = P.records_load()
        print(f"records: live fetch failed ({e}), using cached table")
    targets = list(P.TARGETS) if hasattr(P, "TARGETS") else list(L.load_scores().keys())
    rows = L.scoreboard(targets, rec, None)
    board = "target | best known | ours | ours - best known\n" + "\n".join(
        f"{t} | {r if r is not None else '(none known)'} | {b if b is not None else '-'} | {('%+.6g' % d) if d is not None else '-'}"
        for t, r, b, _l, d in rows
    )
    scores = L.load_scores()
    wins = sorted(t for t in targets if P.beats(value_of(scores.get(t)), rec.get(t)))
    champ = open(L.champ, encoding="utf-8").read()
    prompt = build_retro_prompt(P, a.problem, history, board, champ, since)
    if a.dry_run:
        print(prompt)
        return 0
    print(f"retro {a.problem} {time.strftime('%Y-%m-%d %H:%M:%S')}: iterations {since}+ of {len(history)}", flush=True)
    text, cost, err = call_text(prompt, a.model)
    if err or "### Next" not in text:
        print(f"retro: NOT written ({err or 'model output lacks the Next heading'}): {text[-300:]}")
        return 1
    path = retro_path(a.problem)
    append_section(path, section_header(a.problem, history, since, wins), text)
    print(
        f"retro: appended to {os.path.relpath(path, HERE)} "
        f"(reported total_cost_usd API-equivalent {cost:.2f}; subscription billing not measured)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
