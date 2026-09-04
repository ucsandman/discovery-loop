"""Discovery loop: an LLM evolves a solver program; a code checker scores it; winners survive.

Problems live in problems/<name>/problem.py (targets, records, independent verifier, submission format, prompt).
Each iteration: prompt the model with the champion solver + scoreboard + ideas tried -> new solver.py
-> run it on every target in parallel (hard timeout) -> verify independently -> keep if better.
Per-target bests are saved in submission format regardless of which solver produced them, and publish.py
is fired whenever a record-beating target improves.

Usage:
  python loop.py --problem circle_packing --eval-only          # score the champion, no model calls
  python loop.py --problem miplib --iters 20 --budget 30       # evolve until 20 iterations or $30 of model usage
"""

import argparse
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
AUTHOR = "Wes Sander, MoltFire"


def load_problem(name):
    path = os.path.join(HERE, "problems", name, "problem.py")
    spec = importlib.util.spec_from_file_location(f"problem_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def layout(name):
    """(best_dir, runs_dir). ponytail: circle_packing keeps the original flat layout because a run is in flight;
    unify to best/<name> after it ends."""
    suf = "" if name == "circle_packing" else "-" + name
    return os.path.join(HERE, "best" + suf), os.path.join(HERE, "runs" + suf)


def value_of(entry):
    return None if entry is None else entry.get("value", entry.get("sum"))


class Loop:
    def __init__(self, problem):
        self.P = load_problem(problem)
        self.name = problem
        self.best, self.runs = layout(problem)
        self.champ = os.path.join(self.best, "solver.py")
        self.scores = os.path.join(self.best, "scores.json")
        self.log_path = os.path.join(self.runs, "log.jsonl")
        self.status = os.path.join(self.runs, "status.html")
        os.makedirs(self.best, exist_ok=True)
        os.makedirs(self.runs, exist_ok=True)
        if not os.path.exists(self.champ):
            shutil.copy(os.path.join(HERE, "problems", problem, "seed_solver.py"), self.champ)

    # ── evaluation ──
    def run_solver(self, solver, target, budget, seed, out):
        t0 = time.time()
        try:
            env = dict(os.environ)  # solvers can import the problem's helpers (records.py, verify.py) from anywhere
            env["PYTHONPATH"] = os.path.join(HERE, "problems", self.name) + os.pathsep + env.get("PYTHONPATH", "")
            p = subprocess.run(
                [sys.executable, solver, *self.P.solver_argv(target, budget, seed, out)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=budget + 45,
                env=env,
            )
            if p.returncode != 0 and not os.path.exists(out):
                return {"target": target, "error": (p.stderr or p.stdout)[-600:]}
            value, payload = self.P.evaluate(out, target)
            return {"target": target, "value": value, "payload": payload, "secs": round(time.time() - t0, 1)}
        except subprocess.TimeoutExpired:
            return {"target": target, "error": f"timeout after {budget + 45}s"}
        except Exception as e:  # infeasible, bad JSON, missing file, ...
            return {"target": target, "error": f"{type(e).__name__}: {e}"[:300]}

    def evaluate(self, solver, targets, budget, seed, workdir, workers):
        os.makedirs(workdir, exist_ok=True)
        with ThreadPoolExecutor(workers) as ex:
            futs = [
                ex.submit(self.run_solver, solver, t, budget, seed + i, os.path.join(workdir, f"{t}.json"))
                for i, t in enumerate(targets)
            ]
            return [f.result() for f in futs]

    def total(self, results, rec):
        return sum(
            self.P.score(r["value"], rec.get(r["target"])) if "value" in r else self.P.FAIL_SCORE for r in results
        )

    def load_scores(self):
        return json.load(open(self.scores)) if os.path.exists(self.scores) else {}

    def update_bests(self, results, iteration, rec):
        """Persist per-target bests + submission files. Returns (improved targets, targets beating the record)."""
        scores = self.load_scores()
        improved, wins = [], []
        for r in results:
            if "value" not in r:
                continue
            t = r["target"]
            prev = value_of(scores.get(t))
            if prev is None or self.P.better(r["value"], prev):
                scores[t] = {"value": r["value"], "iter": iteration, "record": rec.get(t)}
                self.P.save(t, r["payload"], r["value"], self.best, AUTHOR)
                improved.append(t)
            if self.P.beats(r["value"], rec.get(t)):
                wins.append(t)
        json.dump(scores, open(self.scores, "w"), indent=1)
        return improved, wins

    # ── model ──
    def scoreboard(self, targets, rec, last=None):
        scores = self.load_scores()
        rows = []
        for t in targets:
            b = value_of(scores.get(t))
            r = rec.get(t)
            l = next((x["value"] for x in (last or []) if x["target"] == t and "value" in x), None)
            rows.append((t, r, b, l, (b - r) if (b is not None and r is not None) else None))
        return rows

    def build_prompt(self, targets, rec, last_results, history):
        champ = open(self.champ, encoding="utf-8").read()
        board = "target | best known | ours | champion last run | ours - best known\n"
        for t, r, b, l, d in self.scoreboard(targets, rec, last_results):
            board += f"{t} | {r if r is not None else '(none known)'} | {b if b is not None else '-'} | {l if l is not None else '-'} | {('%+.6g' % d) if d is not None else '-'}\n"
        hist = (
            "\n".join(
                f"iter {h['iter']}: total={h['total']:.4f} ({h['status']}) IDEA: {h['idea']}"
                + (f" ERRORS: {h['errors']}" if h.get("errors") else "")
                for h in history[-12:]
            )
            or "(none yet)"
        )
        return f"""{self.P.PROMPT}

CURRENT CHAMPION solver.py:
```python
{champ}
```

SCOREBOARD ({"higher" if self.P.MAXIMIZE else "lower"} is better; champion total = {self.P.TOTAL_DESC}):
{board}
IDEAS TRIED SO FAR:
{hist}

{self.P.TASK}

OUTPUT FORMAT: first line "IDEA: <one sentence>", then exactly one ```python block with the full file. Nothing else."""

    @staticmethod
    def call_model(prompt, model):
        env = {k: v for k, v in os.environ.items() if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC_"))}
        cmd = [
            "claude",
            "-p",
            "--model",
            model,
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--setting-sources",
            "",
            "--tools",
            "",
            "--no-session-persistence",
            "--system-prompt",
            "You are an expert in numerical and combinatorial optimisation. Output only what is asked.",
        ]
        try:
            p = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=900,
                shell=(os.name == "nt"),
            )
        except subprocess.TimeoutExpired:
            return None, 0.0, "cli timeout after 900s"
        except OSError as e:
            return None, 0.0, f"cli error: {e}"
        if p.returncode != 0 and not p.stdout.strip():
            return None, 0.0, f"cli error (exit {p.returncode}): {p.stderr[-300:]}"
        try:
            j = json.loads(p.stdout)
        except json.JSONDecodeError:
            return None, 0.0, f"bad cli output: {p.stdout[-300:]} {p.stderr[-300:]}"
        text, cost = j.get("result") or "", float(j.get("total_cost_usd") or 0)
        m = re.search(r"```python\s*\n(.*?)```", text, re.S)
        idea = re.search(r"IDEA:\s*(.+)", text)
        return (m.group(1) if m else None), cost, (idea.group(1).strip() if idea else "(no idea line)")

    # ── reporting ──
    def write_status(self, targets, rec, history, cost_total, champ_total):
        tr = ""
        for t, r, b, l, d in self.scoreboard(targets, rec):
            cls = "win" if (b is not None and self.P.beats(b, r)) else ""
            tr += (
                f"<tr class='{cls}'><td>{t}</td><td>{r if r is not None else '(none known)'}</td><td>{b if b is not None else '-'}</td>"
                f"<td>{('%+.6g' % d) if d is not None else '-'}</td></tr>"
            )
        hist = "".join(
            f"<tr><td>{h['iter']}</td><td>{h['total']:.4f}</td><td>{h['status']}</td>"
            f"<td>${h['cost']:.2f}</td><td>{html.escape(h['idea'])}</td></tr>"
            for h in reversed(history)
        )
        open(
            self.status, "w", encoding="utf-8"
        ).write(f"""<!doctype html><meta charset=utf-8><title>discovery-loop: {self.P.TITLE}</title>
<style>body{{font:14px system-ui;margin:2em;max-width:60em}}table{{border-collapse:collapse;margin:1em 0}}td,th{{border:1px solid #ccc;padding:4px 8px;text-align:right}}
th{{background:#eee}}.win{{background:#c8f7c5}}h1{{margin:0}}</style>
<h1>discovery-loop: {self.P.TITLE}</h1>
<p>Updated {time.strftime("%Y-%m-%d %H:%M")} · champion total {champ_total:.4f} · model spend ${cost_total:.2f} · green = beats best known</p>
<table><tr><th>target</th><th>best known</th><th>ours</th><th>ours - best known</th></tr>{tr}</table>
<h3>Iterations</h3><table><tr><th>#</th><th>total</th><th>status</th><th>cost</th><th style='text-align:left'>idea</th></tr>{hist}</table>
<p>{html.escape(self.P.SUBMIT_NOTE)}</p>""")

    def publish(self):
        """Fire-and-forget: push candidates to GitHub and email the maintainers (approval-gated) via publish.py."""
        subprocess.Popen(
            [sys.executable, os.path.join(HERE, "publish.py"), "--problem", self.name],
            cwd=HERE,
            stdout=open(os.path.join(self.runs, "publish.log"), "a"),
            stderr=subprocess.STDOUT,
        )


def check_plateau(history, window, threshold):
    """Return True if the last `window` iterations show no meaningful relative progress.

    Three independent signals (any one triggers). No-code entries (including CLI timeouts) are
    excluded from the window entirely, so a model timeout does not count as a non-improving
    iteration. A window of 0 disables the plateau stop.
    1. All remaining entries in the window are rejected (nothing worked).
    2. No champion in the window (model is spinning).
    3. Relative improvement across the window < threshold: improvement is measured against
       max(abs(best_before), abs(best_in_window), 1e-12), since totals sit on very different
       absolute scales per problem.
    """
    if window == 0:
        return False
    recent = [h for h in history if h["status"] not in ("seed", "no-code")]
    if len(recent) < window:
        return False
    tail = recent[-window:]
    # Signal 1: all rejected
    if all(h["status"] == "rejected" for h in tail):
        return True
    # Signal 2: no champions at all
    champ_totals = [h["total"] for h in tail if h["status"] == "champion"]
    if not champ_totals:
        return True
    # Signal 3: improvement too small (relative)
    cutoff = tail[0]["iter"]
    best_before = max(
        (h["total"] for h in history if h["status"] in ("champion", "seed") and h["iter"] < cutoff),
        default=0.0,
    )
    best_in_window = max(champ_totals)
    improvement = best_in_window - best_before
    if improvement / max(abs(best_before), abs(best_in_window), 1e-12) < threshold:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="circle_packing")
    ap.add_argument("--targets", help="comma-separated; default = the problem's target list")
    ap.add_argument("--time", type=float, help="seconds per target per solver run")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--iters", type=int, default=40)
    ap.add_argument("--budget", type=float, default=30.0, help="max model spend in USD")
    ap.add_argument("--model", default="claude-fable-5-1")
    ap.add_argument(
        "--plateau-window",
        type=int,
        default=6,
        help="consecutive non-improving iters before plateau stop (no-code entries excluded); 0 disables",
    )
    ap.add_argument(
        "--plateau-threshold",
        type=float,
        default=0.01,
        help="min relative total improvement across window to count as progress",
    )
    ap.add_argument(
        "--wall-minutes",
        type=float,
        help="stop before starting an iteration that cannot finish by this wall-clock limit",
    )
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--refresh-records", action="store_true")
    ap.add_argument(
        "--no-publish",
        action="store_true",
        help="never fire publish.py (no git commit/push, no maintainer email); for isolated experiments",
    )
    a = ap.parse_args()
    deadline = time.time() + 60 * a.wall_minutes if a.wall_minutes else None
    L = Loop(a.problem)
    P = L.P
    targets = a.targets.split(",") if a.targets else list(P.TARGETS)
    budget = a.time or P.DEFAULTS["time"]
    workers = a.workers or P.DEFAULTS["workers"]
    rec = P.records_fetch() if a.refresh_records else P.records_load()
    history = [json.loads(l) for l in open(L.log_path)] if os.path.exists(L.log_path) else []
    cost_total = sum(h["cost"] for h in history)
    champ_total = max([h["total"] for h in history if h["status"] in ("champion", "seed")], default=None)
    it = (history[-1]["iter"] + 1) if history else 0

    def log(entry):
        history.append(entry)
        open(L.log_path, "a").write(json.dumps(entry) + "\n")
        L.write_status(targets, rec, history, cost_total, champ_total if champ_total is not None else 0.0)

    if a.eval_only or not history:
        res = L.evaluate(L.champ, targets, budget, 1000 * it, os.path.join(L.runs, f"iter{it:03d}"), workers)
        total = L.total(res, rec)
        improved, wins = L.update_bests(res, it, rec)
        champ_total = total if champ_total is None else max(champ_total, total)
        log(
            {
                "iter": it,
                "total": total,
                "status": "seed",
                "cost": 0.0,
                "idea": "seed solver",
                "errors": "; ".join(f"{r['target']}: {r['error']}" for r in res if "error" in r),
                "wins": wins,
                "improved": improved,
            }
        )
        print(f"[iter {it}] seed total={total:.4f} wins={wins} improved={improved}")
        if not a.no_publish and set(wins) & set(improved):
            L.publish()
        it += 1
        if a.eval_only:
            return

    last_results = None
    while it < a.iters and cost_total < a.budget:
        if deadline is not None and time.time() + budget + 360 > deadline:
            print(
                f"[wall] {a.wall_minutes:.0f} min limit reached; champion total={champ_total:.4f} spend=${cost_total:.2f}"
            )
            break
        prompt = L.build_prompt(targets, rec, last_results, history)
        code, cost, idea = L.call_model(prompt, a.model)
        cost_total += cost
        if not code:
            log(
                {
                    "iter": it,
                    "total": P.FAIL_SCORE * len(targets),
                    "status": "no-code",
                    "cost": cost,
                    "idea": idea,
                    "errors": "",
                }
            )
            print(f"[iter {it}] model returned no code ({idea})")
            it += 1
            continue
        wd = os.path.join(L.runs, f"iter{it:03d}")
        os.makedirs(wd, exist_ok=True)
        cand = os.path.join(wd, "solver.py")
        open(cand, "w", encoding="utf-8").write(code)
        res = L.evaluate(cand, targets, budget, 1000 * it, wd, workers)
        total = L.total(res, rec)
        improved, wins = L.update_bests(res, it, rec)
        errors = "; ".join(f"{r['target']}: {r['error']}" for r in res if "error" in r)
        if total > champ_total:
            champ_total = total
            status = "champion"
            open(L.champ, "w", encoding="utf-8").write(code)
        else:
            status = "rejected"
        last_results = res
        log(
            {
                "iter": it,
                "total": total,
                "status": status,
                "cost": cost,
                "idea": idea,
                "errors": errors[:800],
                "wins": wins,
                "improved": improved,
            }
        )
        print(
            f"[iter {it}] {status} total={total:.4f} champ={champ_total:.4f} cost=${cost_total:.2f} wins={wins} improved={improved} | {idea}"
        )
        if not a.no_publish and set(wins) & set(improved):
            L.publish()
        it += 1
        if check_plateau(history, a.plateau_window, a.plateau_threshold):
            print(
                f"[plateau] no meaningful improvement in last {a.plateau_window} iterations "
                f"(threshold={a.plateau_threshold}). Stopping early to save budget. "
                f"champion total={champ_total:.4f} spend=${cost_total:.2f}"
            )
            break
    else:
        print(f"done. champion total={champ_total:.4f} spend=${cost_total:.2f}")
    if not a.no_publish:
        L.publish()


if __name__ == "__main__":
    main()
