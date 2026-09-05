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
import subprocess
import time

from loop import Loop, load_problem, retro_path, value_of

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
THIS RUN: iterations {since_iter}+ ({len(this_run)} iterations, {len(champions)} became champion, spend ${spend:.2f})

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
    """One claude -p turn, tools off, returns (text, cost_usd, error)."""
    env = {k: v for k, v in os.environ.items() if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC_"))}
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--max-turns", "1", "--setting-sources", ""]
    cmd += ["--tools", "", "--no-session-persistence", "--system-prompt"]
    cmd += ["You are an expert in numerical and combinatorial optimisation writing a terse engineering retro."]
    try:
        p = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=TIMEOUT,
            shell=(os.name == "nt"),
        )
    except subprocess.TimeoutExpired:
        return "", 0.0, f"cli timeout after {TIMEOUT}s"
    except OSError as e:
        return "", 0.0, f"cli error: {e}"
    try:
        j = json.loads(p.stdout)
    except json.JSONDecodeError:
        return "", 0.0, f"bad cli output: {p.stdout[-300:]} {p.stderr[-300:]}"
    return (j.get("result") or "").strip(), float(j.get("total_cost_usd") or 0), ""


def section_header(name, history, since_iter, board_wins):
    this_run = [h for h in history if h["iter"] >= since_iter]
    champ = max([h["total"] for h in history if h["status"] in ("champion", "seed")], default=float("nan"))
    spend = sum(h.get("cost", 0) for h in this_run)
    iters = f"iters {this_run[0]['iter']}-{this_run[-1]['iter']}" if this_run else "no iterations"
    wins = ", ".join(board_wins) if board_wins else "none"
    return f"## {time.strftime('%Y-%m-%d %H:%M')} {name}: {iters}, spend ${spend:.2f}, champion {champ:.4f}, beating best-known: {wins}"


def append_section(path, header, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            title = os.path.splitext(os.path.basename(path))[0]
            f.write(f"# Retro: {title}\n\nAppended by retro.py after every night slot, newest at the bottom. ")
            f.write("loop.py reads the last section's Lessons and Next into every iteration prompt.\n")
        f.write(f"\n{header}\n\n{body.strip()}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", required=True)
    ap.add_argument("--since-iter", type=int, default=None, help="first iteration of the run being reviewed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    P = load_problem(a.problem)
    L = Loop(a.problem)
    history = [json.loads(l) for l in open(L.log_path, encoding="utf-8")] if os.path.exists(L.log_path) else []
    if not history:
        print("retro: no history, nothing to review")
        return
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
        return
    print(f"retro {a.problem} {time.strftime('%Y-%m-%d %H:%M:%S')}: iterations {since}+ of {len(history)}", flush=True)
    text, cost, err = call_text(prompt, a.model)
    if err or "### Next" not in text:
        print(f"retro: NOT written ({err or 'model output lacks the Next heading'}): {text[-300:]}")
        return
    path = retro_path(a.problem)
    append_section(path, section_header(a.problem, history, since, wins), text)
    print(f"retro: appended to {os.path.relpath(path, HERE)} (${cost:.2f})")


if __name__ == "__main__":
    main()
