"""Every recorded research run in one table, and the audit that keeps the feedback chain closed.

    python scripts/research_ledger.py list [--problem NAME]
    python scripts/research_ledger.py audit
    python scripts/research_ledger.py retro --run-id ID --problem NAME [--call-budget 2.5]
    python scripts/research_ledger.py retro --all-missing [--call-budget 2.5]

The loop already records each run under runs/research/<run_id>/<problem>/ (evidence.json, candidates,
confirmation rows) and appends every candidate to runs/research/development-history/<problem>.jsonl,
which the next generation prompt reads. The retrospective (retro.json, distilled into
<problem>-retro.json and injected as "PRIOR RETROSPECTIVE NOTES") is what turns a night into a lesson,
and only the nightly runner launches it. A run started by hand never gets one unless someone runs
retro.py, so ``audit`` names every finished research run that has no retrospective and prints the
exact command; ``retro`` runs it (an explicit model call, never automatic). ``list`` and ``audit``
read only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_state import read_json  # noqa: E402
from retro import cross_model_provider  # noqa: E402

FINISHED = {"completed", "partial"}
DEFAULT_RETRO_BUDGET = 2.5


def _finite(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def run_rows(root, problem=None) -> list[dict]:
    """One row per evidence.json under runs/research, oldest first."""
    research = Path(root) / "runs" / "research"
    rows = []
    for path in sorted(research.glob("*/*/evidence.json")):
        evidence = read_json(path, None)
        if not isinstance(evidence, dict):
            continue
        run_dir = path.parent
        name = evidence.get("problem") if isinstance(evidence.get("problem"), str) else run_dir.name
        if problem and name != problem:
            continue
        development = evidence.get("development") if isinstance(evidence.get("development"), dict) else {}
        candidates = development.get("candidates") if isinstance(development.get("candidates"), list) else []
        usage = evidence.get("usage") if isinstance(evidence.get("usage"), dict) else {}
        retro = read_json(run_dir / "retro.json", None)
        retro_ok = isinstance(retro, dict) and retro.get("status") == "completed"
        memory = read_json(research / "development-history" / f"{name}-retro.json", None)
        gains = [_finite(c.get("median_gain")) for c in candidates if isinstance(c, dict)]
        gains = [g for g in gains if g is not None]
        rows.append(
            {
                "run_id": evidence.get("run_id") if isinstance(evidence.get("run_id"), str) else run_dir.parent.name,
                "problem": name,
                "provider": evidence.get("provider"),
                "status": evidence.get("status"),
                "iterations": usage.get("iterations"),
                "candidates": len(candidates),
                "best_gain": max(gains) if gains else None,
                "confirmed": evidence.get("confirmed") is True,
                "publishable": evidence.get("publishable") is True,
                "charged_usd": _finite(usage.get("charged")),
                "retro": "completed" if retro_ok else ("failed" if isinstance(retro, dict) else "missing"),
                "next_experiment": (
                    (memory.get("next_experiment") or "")[:120]
                    if isinstance(memory, dict) and memory.get("source_run_id") == evidence.get("run_id")
                    else ""
                ),
                "finished_at": evidence.get("finished_at"),
            }
        )
    return rows


def missing_retros(root, problem=None) -> list[dict]:
    """Finished research runs (completed or partial, at least one candidate) with no completed retro."""
    return [
        row
        for row in run_rows(root, problem)
        if row["status"] in FINISHED and row["candidates"] > 0 and row["retro"] != "completed"
    ]


def retro_command(row, *, call_budget=DEFAULT_RETRO_BUDGET) -> list[str]:
    provider = row.get("provider") if row.get("provider") in ("fable", "astra", "paired") else "paired"
    analyst = cross_model_provider(provider, str(row["run_id"]))
    return [
        sys.executable,
        "-u",
        str(ROOT / "retro.py"),
        "--problem",
        str(row["problem"]),
        "--run-id",
        str(row["run_id"]),
        "--evidence-root",
        "runs/research",
        "--provider",
        analyst,
        "--call-budget",
        str(call_budget),
    ]


def list_runs(root, stream, problem=None) -> int:
    rows = run_rows(root, problem)
    print(
        f"{'run_id':<28} {'problem':<22} {'status':<20} {'cand':>4} {'best gain':>10} {'conf':<5} "
        f"{'charged':>8} {'retro':<9} next experiment",
        file=stream,
    )
    for row in rows:
        gain = f"{row['best_gain'] * 100:+.2f}%" if row["best_gain"] is not None else "-"
        charged = f"${row['charged_usd']:.2f}" if row["charged_usd"] is not None else "-"
        print(
            f"{row['run_id']:<28} {row['problem']:<22} {str(row['status']):<20} {row['candidates']:>4} {gain:>10} "
            f"{str(row['confirmed']):<5} {charged:>8} {row['retro']:<9} {row['next_experiment']}",
            file=stream,
        )
    print(f"{len(rows)} runs on record", file=stream)
    return 0


def audit(root, stream, problem=None) -> int:
    rows = run_rows(root, problem)
    missing = missing_retros(root, problem)
    finished = [row for row in rows if row["status"] in FINISHED and row["candidates"] > 0]
    print(
        f"{len(rows)} runs on record, {len(finished)} finished with candidates, {len(missing)} without a retrospective",
        file=stream,
    )
    for row in missing:
        print(f"  {row['run_id']} {row['problem']}: " + " ".join(retro_command(row)[1:]), file=stream)
    if missing:
        print("A run without a retrospective teaches the next run nothing. Run the commands above, or:", file=stream)
        print("  python scripts/research_ledger.py retro --all-missing", file=stream)
    return 1 if missing else 0


def run_retro(
    root, stream, *, run_id=None, problem=None, all_missing=False, call_budget=DEFAULT_RETRO_BUDGET, runner=None
):
    """Execute retro.py for one run or for every finished run that lacks one. Each call spends allowance."""
    runner = runner or (lambda command: subprocess.run(command, cwd=str(root), check=False).returncode)
    if all_missing:
        targets = missing_retros(root, problem)
    else:
        if not run_id or not problem:
            print("retro needs --run-id and --problem, or --all-missing", file=stream)
            return 2
        targets = [row for row in run_rows(root, problem) if row["run_id"] == run_id]
        if not targets:
            print(f"no recorded run {run_id} for {problem}", file=stream)
            return 2
    failures = 0
    for row in targets:
        command = retro_command(row, call_budget=call_budget)
        print(
            f"retro {row['run_id']} {row['problem']} (analyst {command[command.index('--provider') + 1]})", file=stream
        )
        code = runner(command)
        failures += 0 if code == 0 else 1
        print(f"  exit {code}", file=stream)
    print(f"{len(targets)} retrospectives run, {failures} failed", file=stream)
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="every recorded research run")
    listing.add_argument("--problem")
    checking = sub.add_parser("audit", help="finished runs with no retrospective (exit 1 when any)")
    checking.add_argument("--problem")
    retro = sub.add_parser("retro", help="run the retrospective for one run or every run missing one")
    retro.add_argument("--run-id")
    retro.add_argument("--problem")
    retro.add_argument("--all-missing", action="store_true")
    retro.add_argument("--call-budget", type=float, default=DEFAULT_RETRO_BUDGET)
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.command == "list":
        return list_runs(root, sys.stdout, args.problem)
    if args.command == "audit":
        return audit(root, sys.stdout, args.problem)
    return run_retro(
        root,
        sys.stdout,
        run_id=args.run_id,
        problem=args.problem,
        all_missing=args.all_missing,
        call_budget=args.call_budget,
    )


if __name__ == "__main__":
    raise SystemExit(main())
