#!/usr/bin/env python3
"""Read-only prize hunt console: board, allocation plan, scaling, economics, next command.

Nothing here spends, fetches, submits or mutates state. Every subcommand reads the local
registry file and the evidence already on disk and prints. ``next`` prints the exact
``loop.py`` invocation for the top-ranked admitted prize, derived from the reviewed
``prize_registry.PRIZE_BINDINGS`` ceilings and the bound plugin's own ``PRIZE`` promotion
threshold; every flag is checked against loop.py's ``cli_main`` parser before it is printed,
so a stale flag fails here rather than at 3am. Running that command is a separate, deliberate
act: this script never launches it.

Usage:
    python scripts/prize_hunt.py board
    python scripts/prize_hunt.py allocate --allowance 10 --minutes 60
    python scripts/prize_hunt.py scaling --prize certicom-eccp-131
    python scripts/prize_hunt.py economics --problem ecc_prize
    python scripts/prize_hunt.py next
"""

from __future__ import annotations
import argparse
import ast
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import prize_contract  # noqa: E402
import prize_economics  # noqa: E402
import prize_registry  # noqa: E402
import prize_scaling  # noqa: E402
import prize_scoring  # noqa: E402

EVIDENCE_ROOT = "runs/research"
DEFAULT_SEED_COUNT = 3
DEFAULT_MIN_EFFECT = 0.02
MAX_ITERS = 40


def contracts(root, stream):
    """Print the prize-contract verdict for every installed prize plugin; exit 1 when one fails."""
    from problem_loader import load_problem

    failed = 0
    for plugin in prize_contract.prize_plugins(root):
        verdict = prize_contract.validate_prize_plugin(load_problem(plugin), root)
        state = "ok" if verdict["ok"] else "FAIL"
        failed += 0 if verdict["ok"] else 1
        detail = "; ".join([*verdict["missing"], *verdict["errors"]])
        print(f"  {plugin:<26} {state}  {detail}", file=stream)
    print(f"{failed} of {len(prize_contract.prize_plugins(root))} prize plugins fail the contract", file=stream)
    return 1 if failed else 0


def _board_rows(root):
    """Snapshot prizes joined with their enable state, measured progress and score."""
    snapshot = prize_registry.snapshot(root)
    control = prize_registry.load_control(root, snapshot)
    enabled = set(control.get("enabled_ids", []))
    progress_by_id = {}
    for prize in prize_scoring.load_prizes(root):
        binding = prize_registry.PRIZE_BINDINGS.get(prize.get("id"))
        if binding:
            progress_by_id[prize["id"]] = prize_economics.progress(root, binding["plugin"])
    scores = {row["prize_id"]: row for row in prize_scoring.rank(snapshot["prizes"], progress_by_id)}
    rows = []
    for prize in snapshot["prizes"]:
        score = scores.get(prize["id"], {})
        rows.append(
            {
                "id": prize["id"],
                "name": prize["name"],
                "status": prize["status"],
                "confidence": prize["status_confidence"],
                "admission": prize["admission"],
                "plugin": prize.get("plugin"),
                "advertised": prize["advertised_prize"],
                "enabled": prize["id"] in enabled,
                "bucket": score.get("bucket", "excluded"),
                "cash_ev_mid": (score.get("cash_ev_usd") or {}).get("mid", 0.0),
                "credibility_ev_mid": (score.get("credibility_ev_usd") or {}).get("mid", 0.0),
                "cost_mid": (score.get("cost_usd") or {}).get("mid", 0.0),
                "priority": score.get("priority_score", 0.0),
            }
        )
    rows.sort(key=lambda row: (row["admission"] != "ready", -row["priority"], row["id"]))
    return snapshot, control, rows


def board(root, stream):
    snapshot, control, rows = _board_rows(root)
    print(f"Prize board  registry_hash {snapshot['registry_hash'][:12]}  {len(rows)} prizes", file=stream)
    print(
        f"{'prize':<28} {'status':<25} {'adm':<11} {'bucket':<20} {'cash EV':>10} {'cost':>9} {'prio':>9}", file=stream
    )
    for row in rows:
        mark = "*" if row["enabled"] else " "
        print(
            f"{mark}{row['id']:<27} {row['status'] + '/' + row['confidence']:<25} {row['admission']:<11} "
            f"{row['bucket']:<20} {row['cash_ev_mid']:>10,.2f} {row['cost_mid']:>9,.2f} {row['priority']:>9.4g}",
            file=stream,
        )
    print(f"\n* = enabled for the nightly slot ({len(control.get('enabled_ids', []))} enabled)", file=stream)
    print(prize_registry.CLAIM_NOTE, file=stream)
    return 0


def allocation_plan(root, *, allowance, minutes, moonshot_share, max_share):
    snapshot = prize_registry.snapshot(root)
    control = prize_registry.load_control(root, snapshot)
    enabled = set(control.get("enabled_ids", []))
    prizes = [prize for prize in snapshot["prizes"] if prize["id"] in enabled]
    progress_by_id = {}
    for prize in prizes:
        binding = prize_registry.PRIZE_BINDINGS.get(prize["id"])
        if binding:
            progress_by_id[prize["id"]] = prize_economics.progress(root, binding["plugin"])
    return prize_scoring.allocate(
        prizes,
        allowance_usd=allowance,
        minutes=minutes,
        moonshot_share=moonshot_share,
        max_share=max_share,
        progress_by_id=progress_by_id,
    )


def allocate(root, stream, *, allowance, minutes, moonshot_share, max_share):
    plan = allocation_plan(
        root, allowance=allowance, minutes=minutes, moonshot_share=moonshot_share, max_share=max_share
    )
    print(f"Plan for ${allowance:,.2f} over {minutes:g} minutes (nothing is spent by this command)", file=stream)
    for item in plan["allocations"]:
        print(
            f"- {item['prize_id']:<28} ${item['usd']:>7,.2f}  {item['minutes']:>4} min  {item['bucket']}\n"
            f"    {item['reason']}",
            file=stream,
        )
    if not plan["allocations"]:
        print("- nothing allocated", file=stream)
    print(f"unallocated: ${plan['unallocated_usd']:,.2f}", file=stream)
    for note in plan["notes"]:
        print(f"note: {note}", file=stream)
    return 0


def _plugin_module(plugin):
    if not plugin:
        return None
    try:
        from problem_loader import load_problem

        return load_problem(plugin)
    except (ImportError, ValueError, AttributeError, SyntaxError):
        return None


def scaling(root, stream, *, prize_id):
    snapshot = prize_registry.snapshot(root)
    prize = next((item for item in snapshot["prizes"] if item["id"] == prize_id), None)
    if prize is None:
        print(f"unknown prize id: {prize_id}", file=stream)
        return 1
    result = prize_scaling.analysis(root, prize, _plugin_module(prize.get("plugin")))
    print(f"Scaling for {prize_id} ({prize['name']})", file=stream)
    print(f"real target: {result['real_target']}", file=stream)
    print(f"target bits: {result['target_bits']}  ladder points: {len(result['points'])}", file=stream)
    if not result["supported"]:
        print(f"not supported: {result['reason']}", file=stream)
        return 0
    fit = result["fit"]
    print(
        f"fit: {fit['model']}  alpha {fit['alpha']:.4g}  beta {fit['beta']:.4g}  "
        f"r2 {fit['r2']:.4g}  n {fit['n_points']}",
        file=stream,
    )
    print(result["summary"], file=stream)
    for assumption in result["extrapolation"]["assumptions"]:
        print(f"assumption: {assumption}", file=stream)
    return 0


def economics(root, stream, *, problem):
    book = prize_economics.ledger(root, problem)
    totals = book["totals"]
    print(
        f"Economics for {problem}: {totals['candidates']} candidates across {len(book['runs'])} runs, "
        f"${totals['model_usd']:,.2f} charged allowance, ${totals['local_compute_usd']:,.4f} local compute",
        file=stream,
    )
    print(f"best measured gain: {totals['best_gain']}", file=stream)
    for direction in book["directions"]:
        print(f"- [{direction['verdict']}] {direction['sentence']}", file=stream)
    if not book["directions"]:
        print("- no research directions recorded yet", file=stream)
    for recommendation in prize_economics.stop_recommendations(book):
        print(f"stop: {recommendation['approach']} ({recommendation['why_failed']})", file=stream)
    for assumption in book["assumptions"]:
        print(f"assumption: {assumption}", file=stream)
    return 0


def loop_cli_flags(root=REPO):
    """Every long flag ``loop.py``'s ``cli_main`` parser accepts, read from its source."""
    tree = ast.parse((Path(root) / "loop.py").read_text(encoding="utf-8"))
    function = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "cli_main"),
        None,
    )
    if function is None:
        raise ValueError("loop.py defines no cli_main parser")
    flags = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                flags.add(argument.value)
    return flags


def next_command(root, *, prize_id=None, provider="paired", run_id=None, flags=None):
    """The exact loop.py invocation for one admitted prize, with every flag verified."""
    snapshot = prize_registry.snapshot(root)
    ranked = prize_scoring.rank(snapshot["prizes"])
    by_id = {prize["id"]: prize for prize in snapshot["prizes"]}
    if prize_id is not None:
        candidates = [row for row in ranked if row["prize_id"] == prize_id]
    else:
        candidates = [row for row in ranked if row["admission"] == "ready" and row["bucket"] != "excluded"]
    chosen = next((row for row in candidates if prize_registry.PRIZE_BINDINGS.get(row["prize_id"])), None)
    if chosen is None:
        raise ValueError("no admitted prize has a reviewed binding to run")
    binding = prize_registry.PRIZE_BINDINGS[chosen["prize_id"]]
    plugin = binding["plugin"]
    module = _plugin_module(plugin)
    prize = getattr(module, "PRIZE", {}) if module is not None else {}
    threshold = prize.get("promotion_threshold", {}) if isinstance(prize, dict) else {}
    defaults = getattr(module, "DEFAULTS", {}) if module is not None else {}
    budget = float(binding["max_slot_budget_usd"])
    call_budget = float(binding["max_per_call_budget_usd"])
    pairs = [
        ("--problem", plugin),
        ("--provider", provider),
        ("--run-id", run_id or date.today().isoformat()),
        ("--evidence-root", EVIDENCE_ROOT),
        ("--iters", str(max(1, min(MAX_ITERS, int(budget // call_budget) if call_budget > 0 else 1)))),
        ("--budget", f"{budget:g}"),
        ("--call-budget", f"{call_budget:g}"),
        ("--seed-count", str(int(threshold.get("seed_count", DEFAULT_SEED_COUNT) or DEFAULT_SEED_COUNT))),
        ("--min-effect", f"{float(threshold.get('min_effect', DEFAULT_MIN_EFFECT) or DEFAULT_MIN_EFFECT):g}"),
        ("--time", f"{float(defaults.get('time', 60)):g}"),
        ("--workers", str(int(defaults.get("workers", 2)))),
        ("--wall-minutes", f"{float(binding['max_minutes']):g}"),
    ]
    known = loop_cli_flags(root if (Path(root) / "loop.py").is_file() else REPO) if flags is None else set(flags)
    command = ["python", "loop.py"]
    for flag, value in pairs:
        if flag not in known:
            raise ValueError(f"loop.py cli_main does not accept {flag}")
        command.extend((flag, value))
    if "--no-publish" not in known:
        raise ValueError("loop.py cli_main does not accept --no-publish")
    command.append("--no-publish")
    return {
        "prize_id": chosen["prize_id"],
        "name": by_id[chosen["prize_id"]]["name"],
        "plugin": plugin,
        "bucket": chosen["bucket"],
        "success_criterion": binding["success_criterion"],
        "command": command,
    }


def next_experiment(root, stream, *, prize_id, provider, run_id):
    try:
        result = next_command(root, prize_id=prize_id, provider=provider, run_id=run_id)
    except ValueError as error:
        print(str(error), file=stream)
        return 1
    print(f"Next experiment: {result['prize_id']} ({result['name']}) via {result['plugin']}", file=stream)
    print(f"success criterion: {result['success_criterion']}", file=stream)
    print(" ".join(result["command"]), file=stream)
    print("This command is not run here. It spends model allowance; nothing is submitted anywhere.", file=stream)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO), help="repository root to read (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("board", help="print the prize board")
    sub.add_parser("contracts", help="check every installed prize plugin against the prize contract")
    plan = sub.add_parser("allocate", help="print an allocation plan for a hypothetical allowance")
    plan.add_argument("--allowance", type=float, default=10.0)
    plan.add_argument("--minutes", type=float, default=60.0)
    plan.add_argument("--moonshot-share", type=float, default=0.2)
    plan.add_argument("--max-share", type=float, default=0.5)
    scale = sub.add_parser("scaling", help="print the measured scaling fit for one prize")
    scale.add_argument("--prize", required=True)
    money = sub.add_parser("economics", help="print the research ledger for one prize plugin")
    money.add_argument("--problem", required=True)
    upcoming = sub.add_parser("next", help="print the exact loop.py command for the top-ranked prize")
    upcoming.add_argument("--prize", default=None)
    upcoming.add_argument("--provider", default="paired", choices=("fable", "astra", "paired"))
    upcoming.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "board":
            return board(root, sys.stdout)
        if args.command == "contracts":
            return contracts(root, sys.stdout)
        if args.command == "allocate":
            return allocate(
                root,
                sys.stdout,
                allowance=args.allowance,
                minutes=args.minutes,
                moonshot_share=args.moonshot_share,
                max_share=args.max_share,
            )
        if args.command == "scaling":
            return scaling(root, sys.stdout, prize_id=args.prize)
        if args.command == "economics":
            return economics(root, sys.stdout, problem=args.problem)
        return next_experiment(root, sys.stdout, prize_id=args.prize, provider=args.provider, run_id=args.run_id)
    except prize_registry.RegistryError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
