"""Evidence-first solver discovery with paired, isolated confirmation.

The command-line path snapshots the historical champion, generates candidates,
evaluates them in disposable workers, and writes local evidence.  Fully
confirmed candidates advance the canonical solver with hash-bound provenance;
publication remains a separate approval-gated action.  Legacy ``Loop`` helpers
remain for older library callers.

Usage:
  python loop.py --problem cvrp --targets X-n280-k17 --eval-only
  python loop.py --problem miplib_heur --provider paired --iters 4 --budget 20
"""

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from datetime import datetime, timezone
from pathlib import Path

import evaluation

HERE = os.path.dirname(os.path.abspath(__file__))
AUTHOR = "Wes Sander, MoltFire"


def load_problem(name):
    from problem_loader import load_problem as safe_load_problem

    return safe_load_problem(name)


def layout(name):
    """(best_dir, runs_dir). ponytail: circle_packing keeps the original flat layout because a run is in flight;
    unify to best/<name> after it ends."""
    suf = "" if name == "circle_packing" else "-" + name
    return os.path.join(HERE, "best" + suf), os.path.join(HERE, "runs" + suf)


def value_of(entry):
    return None if entry is None else entry.get("value", entry.get("sum"))


def retro_path(name):
    return os.path.join(HERE, "docs", "retro", f"{name}.md")


def read_latest_retro(path):
    """The Lessons and Next blocks of the newest section of a retro file written by retro.py, or "" if none."""
    if not os.path.exists(path):
        return ""
    text = open(path, encoding="utf-8").read()
    sections = re.split(r"^## ", text, flags=re.M)
    if len(sections) < 2:
        return ""
    last = sections[-1]
    keep = []
    for heading in ("### Lessons", "### Next"):
        m = re.search(re.escape(heading) + r"\n(.*?)(?=^### |\Z)", last, re.S | re.M)
        if m:
            keep.append(f"{heading}\n{m.group(1).strip()}")
    return "\n".join(keep)


def compress_history(history, keep_full=12, cap=80):
    """Ideas older than the last keep_full iterations, one short line each, newest first, at most cap lines.
    The full block already shows the recent ones; this stops a repeat of something tried nights ago."""
    old = history[:-keep_full] if len(history) > keep_full else []
    lines = [f"iter {h['iter']} ({h['status']}): {(h.get('idea') or '')[:110]}" for h in reversed(old)]
    return "\n".join(lines[:cap])


class Loop:
    def __init__(self, problem, root=None, problem_module=None, initialize_best=True):
        self.root = os.path.abspath(root or HERE)
        self.P = problem_module or load_problem(problem)
        self.name = problem
        if root is None:
            self.best, self.runs = layout(problem)
        else:
            suffix = "" if problem == "circle_packing" else "-" + problem
            self.best = os.path.join(self.root, "best" + suffix)
            self.runs = os.path.join(self.root, "runs" + suffix)
        self.champ = os.path.join(self.best, "solver.py")
        self.scores = os.path.join(self.best, "scores.json")
        self.log_path = os.path.join(self.runs, "log.jsonl")
        self.status = os.path.join(self.runs, "status.html")
        self.solver_evaluations = 0
        self.solver_seconds = 0.0
        if initialize_best:
            os.makedirs(self.best, exist_ok=True)
            os.makedirs(self.runs, exist_ok=True)
            if not os.path.exists(self.champ):
                shutil.copy(os.path.join(self.root, "problems", problem, "seed_solver.py"), self.champ)

    # ── evaluation ──
    def run_solver(self, solver, target, budget, seed, out):
        t0 = time.time()
        try:
            from isolation import run_solver as isolated_run_solver

            p = isolated_run_solver(self.name, solver, target, budget, seed, out, root=self.root)
            if p.returncode != 0:
                detail = p.stderr or p.stdout or f"solver exited with status {p.returncode}"
                return {"target": target, "error": detail[-600:]}
            value, payload = self.P.evaluate(out, target)
            return {"target": target, "value": value, "payload": payload, "secs": round(time.time() - t0, 1)}
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
        older = compress_history(history)
        if older:
            hist += f"\n\nPREVIOUSLY TRIED, EARLIER NIGHTS (do not repeat unless you fix the named failure):\n{older}"
        retro = read_latest_retro(retro_path(self.name))
        retro_block = (
            f"""
LAST RETRO (written after the previous run; follow it):
{retro}

Take the lowest-numbered Next direction whose tag [NEXT #k] does not yet appear in IDEAS TRIED and start your IDEA
line with that tag. If every direction is used, or the scoreboard now argues against all of them, start the IDEA
line with [NEXT none] and say why in the same sentence.
"""
            if retro
            else ""
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
{retro_block}
{self.P.TASK}

OUTPUT FORMAT: first line "IDEA: <one sentence>", then exactly one ```python block with the full file. Nothing else."""

    @staticmethod
    def call_model(prompt, model):
        """Compatibility triple through the canonical subscription-only provider."""
        from providers import call_model

        result = call_model(prompt, provider="fable", model=model, timeout=900)
        if result.get("error"):
            if result.get("error_kind") == "timeout":
                return None, 0.0, "cli timeout after 900s"
            return None, 0.0, "cli error: " + result["error"]
        return result["code"], result["cost"] or 0.0, result["idea"] or "(no idea line)"

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
        """Fire-and-forget: push candidates to GitHub via publish.py --push-only. The maintainer email is batched
        per slot by night.py (one email, one approval tap for every winner of the slot); by hand: python publish.py."""
        os.makedirs(self.runs, exist_ok=True)
        with open(os.path.join(self.runs, "publish.log"), "a") as log:
            subprocess.Popen(
                [sys.executable, os.path.join(HERE, "publish.py"), "--problem", self.name, "--push-only"],
                cwd=HERE,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

    # ── governed research pipeline ──
    def evaluate_matrix(self, solver, matrix, budget, workdir, workers, runner, deadline=None):
        """Run an exact target/seed matrix and independently verify every output."""
        os.makedirs(workdir, exist_ok=True)

        def one(cell):
            target, seed = cell["target"], cell["seed"]
            safe_target = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(target))
            output = os.path.join(workdir, f"{safe_target}-seed{seed}.json")
            started = time.time()
            try:
                result = runner(
                    self.name,
                    solver,
                    target,
                    budget,
                    seed,
                    output,
                    root=self.root,
                    deadline=deadline,
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or f"solver exited with status {result.returncode}")[-600:]
                    return {
                        "target": target,
                        "seed": seed,
                        "error": detail,
                        "returncode": result.returncode,
                        "secs": time.time() - started,
                    }
                value, payload = self.P.evaluate(output, target)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                    raise ValueError("verifier returned a non-finite value")
                return {
                    "target": target,
                    "seed": seed,
                    "value": float(value),
                    "payload": payload,
                    "output_path": output,
                    "secs": round(time.time() - started, 3),
                }
            except Exception as exc:
                return {
                    "target": target,
                    "seed": seed,
                    "error": f"{type(exc).__name__}: {exc}"[:600],
                    "secs": round(time.time() - started, 3),
                }

        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(one, matrix))
        self.solver_evaluations += len(results)
        self.solver_seconds += sum(float(result.get("secs", 0.0)) for result in results)
        return results

    def build_research_prompt(self, incumbent, targets, records, history, hidden_targets=()):
        """Build a prompt from development data only."""
        if hasattr(self.P, "prompt_for_targets"):
            context = self.P.prompt_for_targets(list(targets))
        else:
            hidden = tuple(str(target) for target in hidden_targets)
            context = "\n".join(
                line for line in self.P.PROMPT.splitlines() if not any(target in line for target in hidden)
            )
        board = "\n".join(f"{target}: reference={records.get(target)}" for target in targets)
        prior = (
            "\n".join(
                f"iter {entry['iteration']} {entry['provider']}: median development gain="
                f"{entry.get('median_gain')} idea={entry.get('idea', '')} "
                f"review={entry.get('critique', {}).get('text', '')[:600]}"
                for entry in history[-20:]
            )
            or "(none in this invocation)"
        )
        prompt = f"""{context}

CURRENT INCUMBENT solver.py:
```python
{incumbent}
```

DEVELOPMENT REFERENCES ONLY:
{board}

DEVELOPMENT HISTORY ONLY:
{prior}

{self.P.TASK}

OUTPUT FORMAT: first line "IDEA: <one sentence>", then exactly one ```python block with the full file. Nothing else."""
        leaked = [str(target) for target in hidden_targets if str(target) in prompt]
        if leaked:
            raise ValueError(f"generation prompt exposes withheld targets: {leaked}")
        return prompt


class _ResearchStop(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".solver-", suffix=".tmp", dir=destination.parent)
    os.close(handle)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _repo_relative(path, root):
    root_path = Path(root).resolve()
    path_obj = Path(path).resolve()
    try:
        return path_obj.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise ValueError(f"evidence path is outside the checkout: {path_obj.name}") from exc


def _evidence_rows(rows, root):
    """Drop bulky solution payloads and normalize local paths before serialization."""
    allowed = ("target", "seed", "value", "score", "failed", "error", "returncode", "secs")
    clean = []
    for row in rows:
        item = {key: row[key] for key in allowed if key in row}
        if row.get("output_path"):
            item["output_path"] = _repo_relative(row["output_path"], root)
        clean.append(item)
    return clean


def _read_development_history(path):
    if not os.path.exists(path):
        return []
    history = []
    with open(path, encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid development history line {number}") from exc
            if not isinstance(entry, dict):
                raise ValueError(f"invalid development history line {number}")
            history.append(entry)
    return history[-80:]


def _history_entry(record, run_id, hidden_targets):
    def filtered(value, limit):
        value = str(value or "")[:limit]
        for target in hidden_targets:
            value = value.replace(str(target), "[withheld reference removed]")
        return value

    critique = record.get("critique") or {}
    return {
        "run_id": run_id,
        "iteration": record["iteration"],
        "provider": record["provider"],
        "idea": filtered(record.get("idea"), 500),
        "status": record.get("status"),
        "median_gain": record.get("median_gain"),
        "candidate_hash": record.get("candidate_hash"),
        "critique": {
            "provider": critique.get("provider"),
            "text": filtered(critique.get("text"), 2000),
            "error": filtered(critique.get("error"), 300),
        },
    }


def _incumbent_provenance(loop, root, read_json):
    provenance_path = os.path.join(loop.best, "confirmation.json")
    provenance = read_json(provenance_path)
    if provenance is None:
        return {"classification": "historical_best_unvalidated"}
    if not isinstance(provenance, dict) or provenance.get("problem") != loop.name:
        raise ValueError("invalid confirmed incumbent provenance")
    if provenance.get("candidate_hash") != _sha256(loop.champ):
        raise ValueError("confirmed incumbent solver hash does not match provenance")
    evidence_rel = provenance.get("evidence_path")
    if not isinstance(evidence_rel, str):
        raise ValueError("confirmed incumbent provenance lacks evidence path")
    evidence_path = Path(root, evidence_rel).resolve()
    _repo_relative(evidence_path, root)
    if provenance.get("evidence_hash") != _sha256(evidence_path):
        raise ValueError("confirmed incumbent evidence hash does not match provenance")
    evidence = read_json(evidence_path)
    if (
        not isinstance(evidence, dict)
        or evidence.get("problem") != loop.name
        or evidence.get("status") != "completed"
        or evidence.get("confirmed") is not True
        or evidence.get("candidate_hash") != provenance.get("candidate_hash")
    ):
        raise ValueError("confirmed incumbent provenance points to incompatible evidence")
    return {
        "classification": "confirmed_prior_candidate",
        "provenance_path": _repo_relative(provenance_path, root),
        "evidence_path": evidence_rel,
        "evidence_hash": provenance["evidence_hash"],
    }


def _validate_completed_evidence(evidence, root, problem, provider, model):
    if evidence.get("problem") != problem or evidence.get("provider") != provider or evidence.get("model") != model:
        raise ValueError("completed run id belongs to different problem or provider settings")
    candidate_path = evidence.get("candidate_path")
    if candidate_path:
        candidate = Path(root, candidate_path).resolve()
        _repo_relative(candidate, root)
        if not candidate.is_file() or _sha256(candidate) != evidence.get("candidate_hash"):
            raise ValueError("completed candidate does not match recorded hash")
    artifacts = evidence.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        raise ValueError("completed evidence artifacts are invalid")
    for relative, expected_hash in artifacts.items():
        artifact = Path(root, relative).resolve()
        _repo_relative(artifact, root)
        if not artifact.is_file() or _sha256(artifact) != expected_hash:
            raise ValueError("completed artifact does not match recorded hash")


def _provider_names(mode):
    return ("fable", "astra") if mode == "paired" else (mode,)


def _opposite_provider(provider):
    return "astra" if provider == "fable" else "fable"


def _call_with_budget(call_model_fn, prompt, provider, ledger, call_budget, purpose, usage, deadline=None, model=None):
    before = ledger.snapshot()
    timeout = 900.0 if deadline is None else min(900.0, deadline - time.time())
    if timeout <= 0:
        raise _ResearchStop("timeout", "research deadline reached before model call")
    response = call_model_fn(
        prompt,
        provider=provider,
        model=model,
        timeout=timeout,
        max_cost=call_budget,
        ledger=ledger,
        purpose=purpose,
    )
    after = ledger.snapshot()
    usage["calls"] += 1
    usage["by_purpose"][purpose] = usage["by_purpose"].get(purpose, 0) + 1
    usage["by_provider"][provider] = usage["by_provider"].get(provider, 0) + 1
    usage["charged"] = round(usage["charged"] + max(0.0, after["spent"] - before["spent"]), 8)
    if response.get("error_kind") in ("usage_limit", "authentication", "unavailable"):
        raise _ResearchStop("provider_unavailable", response.get("error") or "subscription provider unavailable")
    return response


def _check_research_control(root, deadline, paused_fn):
    if paused_fn(root):
        raise _ResearchStop("paused", "research paused by runs/control.json")
    if deadline is not None and time.time() >= deadline:
        raise _ResearchStop("timeout", "research deadline reached")


def _confirmation_reserve_seconds(problem, targets, seed_count, workers, solver_budget):
    solver_count = 3 if problem == "miplib_heur" else 2
    batches = math.ceil(len(targets) * max(3, seed_count) / workers)
    return solver_count * batches * (solver_budget + 60.0)  # solver grace plus Docker preflight allowance


def _load_problem_for_research(name, root):
    try:
        from problem_loader import load_problem as safe_load_problem
    except ImportError:
        return load_problem(name)
    try:
        return safe_load_problem(name, root=root)
    except TypeError:
        return safe_load_problem(name)


def run_research(
    problem,
    provider="paired",
    model=None,
    run_id=None,
    ledger_path=None,
    call_budget=2.0,
    seed_count=3,
    min_effect=1e-4,
    evidence_root=None,
    iters=40,
    invocation_budget=30.0,
    time_budget=None,
    workers=None,
    deadline=None,
    root=None,
    problem_module=None,
    call_model_fn=None,
    solver_runner=None,
    ledger=None,
    paused_fn=None,
    targets=None,
    refresh_records=False,
):
    """Run isolated discovery and write reviewable evidence without publishing.

    Optional dependency arguments exist for deterministic regression tests.  The
    command-line path uses the shared provider, isolation and state modules.
    """
    if not isinstance(problem, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", problem):
        raise ValueError("problem must be a simple plugin name")
    if provider not in ("fable", "astra", "paired"):
        raise ValueError("provider must be fable, astra or paired")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("model must be a nonempty string")
    if provider == "paired" and model is not None:
        raise ValueError("an explicit model is only valid for a single-provider run")
    if isinstance(iters, bool) or not isinstance(iters, int) or iters < 0:
        raise ValueError("iters must be a non-negative integer")
    numeric = (call_budget, invocation_budget, min_effect)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric
    ):
        raise ValueError("budgets and min_effect must be finite numbers")
    if call_budget < 0 or invocation_budget < 0 or min_effect <= 0:
        raise ValueError("model budgets must be non-negative and min_effect must be positive")
    if iters > 0 and (call_budget == 0 or invocation_budget == 0):
        raise ValueError("generation requires positive call and invocation budgets")
    if isinstance(seed_count, bool) or not isinstance(seed_count, int) or seed_count < 1:
        raise ValueError("seed_count must be a positive integer")
    root = os.path.abspath(root or HERE)
    if deadline is not None and (
        isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)
    ):
        raise ValueError("deadline must be a finite epoch timestamp")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("run_id must use letters, numbers, dot, underscore or hyphen")

    from research_state import BudgetExceeded, BudgetLedger, FileLock, append_event, atomic_json, paused, read_json

    if call_model_fn is None:
        from providers import call_model as call_model_fn
    paused_fn = paused_fn or paused
    evidence_base = os.fspath(evidence_root) if evidence_root is not None else os.path.join("runs", "research")
    if not os.path.isabs(evidence_base):
        evidence_base = os.path.join(root, evidence_base)
    evidence_base = os.path.abspath(evidence_base)
    _repo_relative(evidence_base, root)
    run_dir = os.path.join(evidence_base, run_id, problem)
    os.makedirs(run_dir, exist_ok=True)
    run_path = os.path.join(run_dir, "run.json")
    evidence_path = os.path.join(run_dir, "evidence.json")
    ledger_path = (
        os.fspath(ledger_path) if ledger_path is not None else os.path.join(evidence_base, run_id, "budget.json")
    )
    if not os.path.isabs(ledger_path):
        ledger_path = os.path.join(root, ledger_path)
    ledger_path = os.path.abspath(ledger_path)
    if ledger is None:
        previous = read_json(ledger_path)
        ledger_limit = previous["limit"] if previous is not None else invocation_budget
        ledger = BudgetLedger(ledger_path, ledger_limit)
    starting_ledger = ledger.snapshot()
    prior_evidence = read_json(evidence_path)
    if isinstance(prior_evidence, dict) and prior_evidence.get("status") in ("completed", "partial"):
        _validate_completed_evidence(prior_evidence, root, problem, provider, model)
        return prior_evidence

    worker_environment = {"mode": "injected verification runner"}
    if solver_runner is None:
        from isolation import preflight, run_solver

        previous_image = (
            (prior_evidence.get("worker_environment") or {}).get("image_id")
            if isinstance(prior_evidence, dict)
            else None
        )
        ready = preflight(root=root, image=previous_image)
        image_id = ready.get("details", {}).get("image_id", "")
        if not ready.get("ok") or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise RuntimeError("Cannot freeze a verified Docker image for this experiment")
        worker_environment = ready["details"]
        solver_runner = partial(run_solver, image=image_id)

    plugin = problem_module or _load_problem_for_research(problem, root)
    loop = Loop(problem, root=root, problem_module=plugin, initialize_best=False)
    manifest = evaluation.build_manifest(plugin, problem)
    development_targets = manifest["development"]
    if targets is not None:
        requested = list(dict.fromkeys(targets))
        invalid = sorted(set(requested) - set(development_targets))
        if invalid:
            raise ValueError(f"--targets may select development targets only; rejected {invalid}")
        if not requested:
            raise ValueError("--targets must select at least one development target")
        development_targets = requested
    confirmation_targets = manifest["confirmation"]
    hidden_targets = manifest["validation"] + manifest["confirmation"] + manifest["release_holdout"]
    if not development_targets:
        raise ValueError("problem manifest has no development targets")
    incumbent_source = loop.champ
    if not os.path.exists(incumbent_source):
        incumbent_source = os.path.join(root, "problems", problem, "seed_solver.py")
    if not os.path.exists(incumbent_source):
        raise FileNotFoundError("no historical champion or seed solver exists")
    if incumbent_source == loop.champ:
        with FileLock(os.path.join(loop.best, ".promotion.lock")):
            incumbent_provenance = _incumbent_provenance(loop, root, read_json)
    else:
        incumbent_provenance = {"classification": "seed_baseline_unvalidated"}
    incumbent_snapshot = os.path.join(run_dir, "legacy_incumbent.py")
    shutil.copyfile(incumbent_source, incumbent_snapshot)
    if isinstance(prior_evidence, dict):
        prior_incumbent = prior_evidence.get("legacy_incumbent") or {}
        if prior_incumbent.get("sha256") not in (None, _sha256(incumbent_snapshot)):
            raise ValueError("resume incumbent does not match the recorded snapshot")
    incumbent_text = open(incumbent_snapshot, encoding="utf-8").read()
    records = plugin.records_fetch() if refresh_records else plugin.records_load()
    budget = plugin.DEFAULTS["time"] if time_budget is None else time_budget
    workers = plugin.DEFAULTS["workers"] if workers is None else workers
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
        raise ValueError("time budget must be a finite positive number")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    invocation_limit = min(float(invocation_budget), float(starting_ledger["remaining"]))
    usage = {"calls": 0, "charged": 0.0, "by_purpose": {}, "by_provider": {}}
    development_history_path = os.path.join(evidence_base, "development-history", f"{problem}.jsonl")
    development_history = _read_development_history(development_history_path)
    candidate_records = []
    if isinstance(prior_evidence, dict):
        if (
            prior_evidence.get("problem") != problem
            or prior_evidence.get("provider") != provider
            or prior_evidence.get("model") != model
        ):
            raise ValueError("resume run id belongs to different problem or provider settings")
        prior_development = prior_evidence.get("development") or {}
        if prior_development.get("targets") not in (None, development_targets):
            raise ValueError("resume must preserve its development target scope")
        for prior in prior_development.get("candidates", []):
            record = dict(prior)
            comparison = record.get("comparison") or {}
            if comparison and comparison.get("min_effect") != float(min_effect):
                raise ValueError("resume must preserve its minimum-effect threshold")
            relative = record.get("candidate_path")
            if relative:
                candidate_file = Path(root, relative).resolve()
                _repo_relative(candidate_file, root)
                if not candidate_file.is_file() or _sha256(candidate_file) != record.get("candidate_hash"):
                    raise ValueError("resume candidate does not match recorded hash")
                record["_candidate_file"] = os.fspath(candidate_file)
            candidate_records.append(record)
    numeric_iterations = [
        record["iteration"]
        for record in candidate_records
        if isinstance(record.get("iteration"), int) and not isinstance(record.get("iteration"), bool)
    ]
    iteration_offset = max(numeric_iterations, default=-1) + 1
    promotion_candidate = None
    development_matrix = []
    incumbent_rows = []
    generation_stop = None
    started_at = _utc_now()
    state = {
        "run_id": run_id,
        "problem": problem,
        "provider": provider,
        "model": model,
        "status": "running",
        "iterations": 0,
        "usage": usage,
        "manifest": manifest,
        "development_targets": development_targets,
        "development_history_path": _repo_relative(development_history_path, root),
        "development_history_entries": len(development_history),
        "started_at": prior_evidence.get("started_at", started_at) if isinstance(prior_evidence, dict) else started_at,
        "resumed_at": started_at if prior_evidence else None,
        "updated_at": started_at,
    }
    atomic_json(run_path, state)
    evidence = {
        "run_id": run_id,
        "problem": problem,
        "provider": provider,
        "model": model,
        "status": "running",
        "candidate_hash": None,
        "candidate_path": None,
        "artifacts": {},
        "artifact_targets": {},
        "confirmed": False,
        "publishable": False,
        "publishable_reason": "No candidate has passed confirmation and plugin release validation.",
        "claim_type": "benchmark_tuning",
        "worker_environment": worker_environment,
        "development": {},
        "confirmation": {},
        "usage": usage,
        "limitations": list(manifest["limitations"]),
        "legacy_incumbent": {
            "path": _repo_relative(incumbent_snapshot, root),
            "sha256": _sha256(incumbent_snapshot),
            **incumbent_provenance,
        },
        "started_at": prior_evidence.get("started_at", started_at) if isinstance(prior_evidence, dict) else started_at,
        "resumed_at": started_at if prior_evidence else None,
        "finished_at": None,
    }

    try:
        _check_research_control(root, deadline, paused_fn)
        development_matrix = evaluation.build_matrix(development_targets, 1, base_seed=10_000)
        incumbent_rows = loop.evaluate_matrix(
            incumbent_snapshot,
            development_matrix,
            budget,
            os.path.join(run_dir, "development", "incumbent"),
            workers,
            solver_runner,
            deadline,
        )
        incumbent_rows = evaluation.score_rows(plugin, records, incumbent_rows)
        _check_research_control(root, deadline, paused_fn)
        for local_iteration in range(iters):
            iteration = iteration_offset + local_iteration
            _check_research_control(root, deadline, paused_fn)
            confirmation_reserve = _confirmation_reserve_seconds(
                problem, confirmation_targets, seed_count, workers, budget
            )
            if deadline is not None and time.time() + confirmation_reserve >= deadline:
                generation_stop = {
                    "reason": "confirmation_time_reserved",
                    "reserved_seconds": confirmation_reserve,
                }
                break
            names = _provider_names(provider)
            required = call_budget * len(names)
            if usage["charged"] + required > invocation_limit + 1e-9 or ledger.remaining + 1e-9 < required:
                generation_stop = {
                    "reason": "budget_exhausted",
                    "required_call_allowance": required,
                }
                break
            prompt = loop.build_research_prompt(
                incumbent_text, development_targets, records, development_history, hidden_targets
            )
            responses = [
                (
                    name,
                    _call_with_budget(
                        call_model_fn,
                        prompt,
                        name,
                        ledger,
                        call_budget,
                        "generation",
                        usage,
                        deadline,
                        model,
                    ),
                )
                for name in names
            ]
            for name, response in responses:
                record = {
                    "iteration": iteration,
                    "provider": name,
                    "idea": response.get("idea") or "",
                    "model": response.get("model"),
                    "generation_error": response.get("error"),
                }
                code = response.get("code")
                if response.get("error") or not code:
                    record.update(status="generation_failed", median_gain=None)
                    history_entry = _history_entry(record, run_id, hidden_targets)
                    append_event(development_history_path, history_entry)
                    development_history.append(history_entry)
                    candidate_records.append(record)
                    continue
                candidate_dir = os.path.join(run_dir, "candidates", f"iter{iteration:03d}-{name}")
                os.makedirs(candidate_dir, exist_ok=True)
                candidate_path = os.path.join(candidate_dir, "solver.py")
                with open(candidate_path, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(code)
                candidate_rows = loop.evaluate_matrix(
                    candidate_path,
                    development_matrix,
                    budget,
                    os.path.join(candidate_dir, "development"),
                    workers,
                    solver_runner,
                    deadline,
                )
                candidate_rows = evaluation.score_rows(plugin, records, candidate_rows)
                comparison = evaluation.compare_paired(incumbent_rows, candidate_rows, min_effect, min_seeds=1)
                record.update(
                    status="promising" if comparison["passes"] else "rejected",
                    candidate_path=_repo_relative(candidate_path, root),
                    _candidate_file=candidate_path,
                    candidate_hash=_sha256(candidate_path),
                    median_gain=comparison["median_gain"],
                    comparison=comparison,
                )
                if comparison["passes"]:
                    _check_research_control(root, deadline, paused_fn)
                    if (
                        usage["charged"] + call_budget <= invocation_limit + 1e-9
                        and ledger.remaining + 1e-9 >= call_budget
                    ):
                        critic = _opposite_provider(name)
                        critique_prompt = (
                            "Review this promising solver change for correctness, benchmark-specific tuning, and likely "
                            "failure modes. Do not write replacement code.\n\n" + code
                        )
                        critique = _call_with_budget(
                            call_model_fn,
                            critique_prompt,
                            critic,
                            ledger,
                            call_budget,
                            "critique",
                            usage,
                            deadline,
                            None,
                        )
                        record["critique"] = {
                            "provider": critic,
                            "model": critique.get("model"),
                            "text": critique.get("text") or critique.get("idea") or "",
                            "error": critique.get("error"),
                        }
                        if critique.get("error"):
                            record["status"] = "promising_unreviewed"
                    else:
                        record["critique"] = {"provider": _opposite_provider(name), "error": "budget_exhausted"}
                        record["status"] = "promising_unreviewed"
                history_entry = _history_entry(record, run_id, hidden_targets)
                append_event(development_history_path, history_entry)
                development_history.append(history_entry)
                candidate_records.append(record)
            state.update(
                iterations=local_iteration + 1,
                usage=usage,
                development_candidates=[
                    {key: value for key, value in record.items() if key != "_candidate_file"}
                    for record in candidate_records
                ],
                updated_at=_utc_now(),
            )
            atomic_json(run_path, state)

        eligible = [record for record in candidate_records if record.get("status") == "promising"]
        best = max(eligible, key=lambda record: record["median_gain"], default=None)
        evidence_candidates = [
            {key: value for key, value in record.items() if key != "_candidate_file"} for record in candidate_records
        ]
        evidence["development"] = {
            "targets": development_targets,
            "matrix": development_matrix,
            "incumbent": _evidence_rows(incumbent_rows, root),
            "candidates": evidence_candidates,
            "best_median_gain": best["median_gain"] if best else None,
        }
        if generation_stop:
            evidence["generation_stop"] = generation_stop
        if best is not None and confirmation_targets:
            _check_research_control(root, deadline, paused_fn)
            confirmation_matrix = evaluation.build_matrix(confirmation_targets, seed_count, base_seed=100_000)
            confirmation_incumbent = loop.evaluate_matrix(
                incumbent_snapshot,
                confirmation_matrix,
                budget,
                os.path.join(run_dir, "confirmation", "incumbent"),
                workers,
                solver_runner,
                deadline,
            )
            confirmation_candidate = loop.evaluate_matrix(
                best["_candidate_file"],
                confirmation_matrix,
                budget,
                os.path.join(run_dir, "confirmation", "candidate"),
                workers,
                solver_runner,
                deadline,
            )
            confirmation_incumbent = evaluation.score_rows(plugin, records, confirmation_incumbent)
            confirmation_candidate = evaluation.score_rows(plugin, records, confirmation_candidate)
            confirmation = evaluation.compare_paired(confirmation_incumbent, confirmation_candidate, min_effect)
            confirmation.update(
                classification=manifest["classification"],
                targets=confirmation_targets,
                matrix=confirmation_matrix,
            )
            evidence["confirmation"] = confirmation
            evidence["confirmed"] = confirmation["passes"]
            evidence["candidate_path"] = best["candidate_path"]
            evidence["candidate_hash"] = best["candidate_hash"]
            artifacts = {}
            artifact_targets = {}
            for row in confirmation_candidate:
                if row.get("failed") or not row.get("output_path"):
                    continue
                relative = _repo_relative(row["output_path"], root)
                artifacts[relative] = _sha256(row["output_path"])
                artifact_targets[relative] = row["target"]
            evidence["artifacts"] = artifacts
            evidence["artifact_targets"] = artifact_targets

            baseline_passes = True
            if problem == "miplib_heur":
                baseline_solver = os.path.join(root, "problems", problem, "baseline_solver.py")
                if not os.path.exists(baseline_solver):
                    baseline_passes = False
                    evidence["baseline"] = {"required": True, "error": "baseline_solver.py is unavailable"}
                else:
                    baseline_rows = loop.evaluate_matrix(
                        baseline_solver,
                        confirmation_matrix,
                        budget,
                        os.path.join(run_dir, "confirmation", "fresh-baseline"),
                        workers,
                        solver_runner,
                        deadline,
                    )
                    baseline_rows = evaluation.score_rows(plugin, records, baseline_rows)
                    baseline_comparison = evaluation.compare_paired(baseline_rows, confirmation_candidate, min_effect)
                    baseline_passes = baseline_comparison["passes"]
                    evidence["baseline"] = {
                        "required": True,
                        "solver_path": _repo_relative(baseline_solver, root),
                        "solver_hash": _sha256(baseline_solver),
                        "rows": _evidence_rows(baseline_rows, root),
                        "comparison": baseline_comparison,
                    }

            release_checks = []
            validate_release = getattr(plugin, "validate_release", None)
            if (
                confirmation["passes"]
                and baseline_passes
                and callable(validate_release)
                and len(artifacts) == len(confirmation_matrix)
            ):
                for row in confirmation_candidate:
                    _check_research_control(root, deadline, paused_fn)
                    check = validate_release(row["output_path"], row["target"], record=records.get(row["target"]))
                    release_checks.append({"target": row["target"], "seed": row["seed"], **check})
            evidence["release_checks"] = release_checks
            release_scopes = sorted(
                {
                    check.get("metrics", {}).get("claim_scope")
                    for check in release_checks
                    if check.get("metrics", {}).get("claim_scope")
                }
            )
            evidence["release_scopes"] = release_scopes
            evidence["publishable"] = bool(
                confirmation["passes"]
                and baseline_passes
                and release_checks
                and all(check.get("ok") is True and check.get("supported") is True for check in release_checks)
            )
            if evidence["publishable"]:
                evidence["publishable_reason"] = "Paired confirmation and every plugin release validation passed."
                evidence["claim_type"] = (
                    "same_machine_benchmark_only"
                    if problem == "miplib_heur" or "same_machine_benchmark_only" in release_scopes
                    else "benchmark_record"
                )
            elif confirmation["passes"]:
                evidence["publishable_reason"] = (
                    "Candidate passed incumbent confirmation, but the same-worker baseline or plugin release validation did not pass."
                )
            else:
                evidence["publishable_reason"] = "Candidate did not pass paired replicated confirmation."
            if evidence["confirmed"]:
                promotion_candidate = best["_candidate_file"]
        elif best is not None:
            evidence["candidate_path"] = best["candidate_path"]
            evidence["candidate_hash"] = best["candidate_hash"]
            evidence["publishable_reason"] = "No separate confirmation targets are available."

        if not candidate_records and generation_stop:
            evidence["status"] = "budget_exhausted" if generation_stop["reason"] == "budget_exhausted" else "timeout"
        else:
            evidence["status"] = (
                "partial"
                if candidate_records
                and all(record.get("status") == "generation_failed" for record in candidate_records)
                else "completed"
            )
    except BudgetExceeded as exc:
        evidence["status"] = "budget_exhausted"
        evidence["error"] = str(exc)
    except _ResearchStop as exc:
        evidence["status"] = exc.status
        evidence["error"] = str(exc)
    except KeyboardInterrupt:
        evidence["status"] = "interrupted"
        evidence["error"] = "KeyboardInterrupt"
    except Exception as exc:
        evidence["status"] = "error"
        evidence["error"] = f"{type(exc).__name__}: {exc}"[:800]

    if not evidence["development"] and incumbent_rows:
        evidence_candidates = [
            {key: value for key, value in record.items() if key != "_candidate_file"} for record in candidate_records
        ]
        evidence["development"] = {
            "targets": development_targets,
            "matrix": development_matrix,
            "incumbent": _evidence_rows(incumbent_rows, root),
            "candidates": evidence_candidates,
            "best_median_gain": max(
                (record["median_gain"] for record in candidate_records if record.get("status") == "promising"),
                default=None,
            ),
        }
    if generation_stop and "generation_stop" not in evidence:
        evidence["generation_stop"] = generation_stop

    finished = _utc_now()
    ending_ledger = ledger.snapshot()
    usage.update(
        charged=round(max(usage["charged"], ending_ledger["spent"] - starting_ledger["spent"]), 8),
        shared_ledger_spent=ending_ledger["spent"],
        shared_ledger_remaining=ending_ledger["remaining"],
        iterations=state.get("iterations", 0),
        solver_evaluations=loop.solver_evaluations,
        solver_seconds=round(loop.solver_seconds, 3),
    )
    evidence["solver_evaluations"] = loop.solver_evaluations
    evidence["solver_seconds"] = round(loop.solver_seconds, 3)
    evidence.update(usage=usage, finished_at=finished)
    state.update(status=evidence["status"], usage=usage, updated_at=finished, finished_at=finished)
    atomic_json(run_path, state)
    atomic_json(evidence_path, evidence)
    if evidence["status"] == "completed" and evidence["confirmed"] and promotion_candidate:
        if _sha256(promotion_candidate) != evidence["candidate_hash"]:
            evidence.update(
                status="error",
                confirmed=False,
                publishable=False,
                error="confirmed candidate changed before promotion",
            )
            state.update(status="error", updated_at=_utc_now())
            atomic_json(run_path, state)
            atomic_json(evidence_path, evidence)
            return evidence
        evidence_hash = _sha256(evidence_path)
        provenance = {
            "version": 1,
            "problem": problem,
            "candidate_hash": evidence["candidate_hash"],
            "evidence_path": _repo_relative(evidence_path, root),
            "evidence_hash": evidence_hash,
            "confirmed_at": finished,
            "claim_type": evidence["claim_type"],
            "publishable": evidence["publishable"],
        }
        with FileLock(os.path.join(loop.best, ".promotion.lock")):
            _atomic_copy(promotion_candidate, loop.champ)
            atomic_json(os.path.join(loop.best, "confirmation.json"), provenance)
    return evidence


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
    """Legacy in-process entry point retained for existing callers and tests."""
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


def cli_main(argv=None):
    """Canonical command-line research path: isolated, evidenced and local-only."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", default="circle_packing")
    parser.add_argument("--provider", choices=("fable", "astra", "paired"))
    parser.add_argument("--model", help="legacy explicit model; implies its matching single provider")
    parser.add_argument("--run-id")
    parser.add_argument("--ledger")
    parser.add_argument("--call-budget", type=float, default=2.0)
    parser.add_argument("--seed-count", type=int, default=3)
    parser.add_argument("--min-effect", type=float, default=1e-4)
    parser.add_argument("--evidence-root")
    parser.add_argument("--iters", type=int, default=40)
    parser.add_argument("--budget", type=float, default=30.0, help="per-invocation model allowance")
    parser.add_argument("--time", type=float, help="seconds per target per solver run")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--wall-minutes", type=float)
    parser.add_argument("--targets", help="comma-separated development targets for a bounded smoke run")
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--refresh-records", action="store_true")
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="compatibility flag; research runs always stop at local evidence",
    )
    args = parser.parse_args(argv)
    provider = args.provider
    if args.model:
        inferred = "fable" if args.model.startswith("claude-") else "astra" if args.model.startswith("gpt-") else None
        if inferred is None:
            parser.error("--model must identify a claude-* (fable) or gpt-* (astra) model")
        if provider is not None and provider != inferred:
            parser.error("--model conflicts with --provider")
        provider = inferred
    provider = provider or "paired"
    deadline = time.time() + args.wall_minutes * 60 if args.wall_minutes else None
    evidence = run_research(
        args.problem,
        provider=provider,
        model=args.model,
        run_id=args.run_id,
        ledger_path=args.ledger,
        call_budget=args.call_budget,
        seed_count=args.seed_count,
        min_effect=args.min_effect,
        evidence_root=args.evidence_root,
        iters=0 if args.eval_only else args.iters,
        invocation_budget=args.budget,
        time_budget=args.time,
        workers=args.workers,
        deadline=deadline,
        targets=args.targets.split(",") if args.targets else None,
        refresh_records=args.refresh_records,
    )
    print(json.dumps({key: evidence.get(key) for key in ("run_id", "problem", "status", "confirmed", "publishable")}))
    return 0 if evidence["status"] in ("completed", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(cli_main())
