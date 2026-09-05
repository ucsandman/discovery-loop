"""Publish verified record-beating results so they never just sit on this machine.

1. git commit + push the problem's best/ dir (GitHub = public, timestamped ledger of every candidate)
2. email new submission files to the benchmark maintainers through the governed invoke-capability seam:
   DashClaw pending approval -> Wes approves on Telegram -> moltfire@ sends, Wes cc'd.

loop.py runs this with --push-only after any iteration that improves a record-beating target (GitHub ledger,
no email). night.py runs the full version once after each slot, so every winner of the slot goes out in ONE
email with ONE approval tap, and a crashed slot still submits what it won (Wes, 2026-09-04). By hand:
  python publish.py --problem miplib            # push + email anything new (12h cooldown between emails)
  python publish.py --problem miplib --push-only  # git commit + push only, never email
  python publish.py --problem miplib --dry-run  # show what would go out; no push, no approval request
  python publish.py --problem miplib --force    # ignore the cooldown
"""

import argparse
import json
import os
import subprocess
import time

from loop import layout, load_problem, value_of

HERE = os.path.dirname(os.path.abspath(__file__))
CLAWD = os.environ.get("CLAWD_ROOT", os.path.expanduser("~/clawd"))
INVOKE = os.path.join(CLAWD, "agent-comms", "team", "bin", "invoke-capability.mjs")
REPO_URL = "https://github.com/ucsandman/discovery-loop"
COOLDOWN = 12 * 3600  # seconds between emails to a human maintainer
APPROVAL_WAIT = 24 * 3600  # seconds to wait for Wes's approval (4h -> 24h, Wes 2026-09-04)
REL_GAIN = 1e-6  # re-submit a target only if it improved by at least this (relative)


def sh(*cmd, cwd=HERE):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def candidates(P, best, rec, ledger):
    """Targets whose re-verified result beats the live best-known and is new since the last submission."""
    path = os.path.join(best, "scores.json")
    scores = json.load(open(path)) if os.path.exists(path) else {}
    out = []
    for t, s in scores.items():
        r = rec.get(t)
        if not P.beats(value_of(s), r):
            continue
        try:
            v, _ = P.evaluate(P.raw_path(t, best), t)
        except Exception as e:
            print(f"skip {t}: stored result failed re-verification ({str(e)[:120]})")
            continue
        prev = value_of(ledger.get(t))
        if prev is not None and (not P.better(v, prev) or abs(v - prev) <= REL_GAIN * max(1.0, abs(prev))):
            continue
        out.append((t, v, r))
    return sorted(out)


def git_push(best, dry):
    if not sh("git", "remote").stdout.strip():
        print("push: no git remote configured")
        return
    if dry:
        print("push: (dry run)")
        return
    sh("git", "add", os.path.relpath(best, HERE))
    if sh("git", "diff", "--cached", "--quiet").returncode != 0:
        sh("git", "commit", "-q", "-m", f"{os.path.basename(best)}: candidates {time.strftime('%Y-%m-%d %H:%M')}")
    p = sh("git", "push", "-q")
    if p.returncode != 0 and "cannot lock ref" in p.stderr:
        # loop.py's end-of-run push and night.py's slot push fire within the same second and race for the
        # branch lock; the loser's commit is already local, so one retry after the winner finishes carries it.
        time.sleep(5)
        p = sh("git", "push", "-q")
    print("push:", "ok" if p.returncode == 0 else p.stderr[-300:])


def email(P, best, cands, ledger, ledger_path, lock, dry, force):
    now = time.time()
    if not force and now - ledger.get("_last_email", 0) < COOLDOWN:
        print(f"email: cooldown, last attempt {(now - ledger['_last_email']) / 3600:.1f}h ago")
        return
    if os.path.exists(lock) and now - os.path.getmtime(lock) < APPROVAL_WAIT + 600:
        print("email: another publish is still waiting for approval")
        return
    names = [t for t, _, _ in cands]
    inp = json.dumps(
        {
            "to": P.EMAIL_TO,
            "subject": P.email_subject(cands),
            "body": P.email_body(cands, REPO_URL),
            "attachments": ",".join(P.sub_path(t, best) for t in names),
        }
    )
    cmd = ["node", INVOKE, "send-email", "--agent", "moltfire", "--input", inp, "--timeout", str(APPROVAL_WAIT)]
    if dry:
        print(P.email_body(cands, REPO_URL))
        p = sh(*cmd, "--dry-run", cwd=CLAWD)
        print(p.stdout or p.stderr)
        return
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    open(lock, "w").write(str(os.getpid()))
    ledger["_last_email"] = now
    json.dump(ledger, open(ledger_path, "w"), indent=1)
    print(f"email: requesting approval for {names} (waits up to {APPROVAL_WAIT // 3600}h)", flush=True)
    try:
        p = sh(*cmd, cwd=CLAWD)
    finally:
        os.remove(lock)
    if p.returncode != 0:
        print("email: NOT sent:", (p.stderr or p.stdout)[-400:])
        return
    action = json.loads(p.stdout).get("action_id")
    sent_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    for t, v, r in cands:
        ledger[t] = {"value": v, "listed": r, "sent_at": sent_at, "action_id": action}
    json.dump(ledger, open(ledger_path, "w"), indent=1)
    print(f"email: sent to {P.EMAIL_TO}, action {action}, {names}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="circle_packing")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--push-only", action="store_true", help="git commit + push only; night.py batches the email per slot"
    )
    a = ap.parse_args()
    P = load_problem(a.problem)
    best, runs = layout(a.problem)
    ledger_path = os.path.join(best, "submitted.json")
    lock = os.path.join(runs, "publish.lock")
    print(f"publish {a.problem} {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        rec = P.records_fetch()
    except Exception as e:  # offline: never claim a win against a stale table without saying so
        rec = P.records_load()
        print(f"records: live fetch failed ({e}), using cached table")
    ledger = json.load(open(ledger_path)) if os.path.exists(ledger_path) else {}
    cands = candidates(P, best, rec, ledger)
    git_push(best, a.dry_run)
    if a.push_only:
        print(f"email: skipped (--push-only); pending for the slot email: {[t for t, _, _ in cands]}")
        return
    if not cands:
        print("email: nothing new beats the live table")
        return
    if not getattr(P, "EMAIL_TO", None):
        print(
            f"email: {a.problem} has no maintainer address; GitHub push is the publication ({[t for t, _, _ in cands]})"
        )
        return
    email(P, best, cands, ledger, ledger_path, lock, a.dry_run, a.force)


if __name__ == "__main__":
    main()
