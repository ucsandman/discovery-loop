"""Prepare independently verified, hash-approved evidence for explicit publication.

The default creates a local bundle. Git publication requires --push-only,
exact evidence/approval paths, and fresh record verification. Email is blocked
until the governed sender binds the approved body and attachment bytes.
Neither the research loop nor the night scheduler invokes publication.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from loop import load_problem, value_of
from research_state import FileLock, atomic_json, read_json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_URL = "https://github.com/ucsandman/discovery-loop"
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
        if not P.beats(v, r):
            continue
        release_check = getattr(P, "validate_release", None)
        if release_check is not None:
            validation = release_check(P.raw_path(t, best), t, record=r)
            if not isinstance(validation, dict) or validation.get("ok") is not True:
                continue
        prev = value_of(ledger.get(t))
        if prev is not None and (not P.better(v, prev) or abs(v - prev) <= REL_GAIN * max(1.0, abs(prev))):
            continue
        out.append((t, v, r))
    return sorted(out)


def git_push(best, dry, *, evidence=None):
    if not sh("git", "remote").stdout.strip():
        print("push: no git remote configured")
        return
    if dry:
        print("push: (dry run)")
        return
    if evidence is None:
        raise ValueError("Publication requires the approved evidence manifest")
    with FileLock(os.path.join(HERE, "runs", "publish-git.lock"), timeout=0):
        remote = sh("git", "remote", "get-url", "origin")
        if remote.returncode or remote.stdout.strip().removesuffix(".git") != REPO_URL:
            raise RuntimeError("Publication remote does not match the configured research repository")
        branch = sh("git", "symbolic-ref", "--short", "HEAD")
        if branch.returncode:
            raise RuntimeError("Publication requires a branch with an origin upstream")
        branch = branch.stdout.strip()
        fetched = sh("git", "fetch", "--no-tags", "origin", branch)
        if fetched.returncode:
            raise RuntimeError("Could not verify remote branch before publication")
        before = sh("git", "rev-parse", "HEAD").stdout.strip()
        upstream = sh("git", "rev-parse", "FETCH_HEAD")
        if upstream.returncode or upstream.stdout.strip() != before:
            raise RuntimeError("Local and remote branch differ; publication must not carry unrelated commits")
        staged = sh("git", "diff", "--cached", "--name-only")
        if staged.returncode or staged.stdout.strip():
            raise RuntimeError("Publication requires an empty staging area; existing staged work was preserved")
        added = sh("git", "add", "--", os.path.relpath(best, HERE))
        if added.returncode:
            raise RuntimeError("Could not stage the approved release")
        relative = os.path.relpath(best, HERE)
        if sh("git", "diff", "--cached", "--quiet", "--", relative).returncode != 0:
            committed = sh(
                "git",
                "commit",
                "--only",
                "-q",
                "-m",
                f"Codex: [RESEARCH] approved {os.path.basename(best)}",
                "--",
                relative,
            )
            if committed.returncode:
                raise RuntimeError("Release commit failed; publication stopped")
        else:
            print("push: approved release is already present; no new commit")
            return
        commit = sh("git", "rev-parse", "HEAD").stdout.strip()
        parent = sh("git", "rev-parse", f"{commit}^").stdout.strip()
        changed = sh("git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
        prefix = Path(relative).as_posix().rstrip("/") + "/"
        if (
            parent != before
            or changed.returncode
            or any(not name.startswith(prefix) for name in changed.stdout.splitlines())
        ):
            raise RuntimeError("Concurrent commit or unexpected release files detected; nothing pushed")
        _verify_committed_release(commit, relative, evidence)
        # Pin the push to this verified commit, not a HEAD another agent can advance.
        pushed = sh("git", "push", "-q", "origin", f"{commit}:refs/heads/{branch}")
        if pushed.returncode:
            raise RuntimeError("Release push failed; local approved release is preserved")
    print("push: ok")


def _release_manifest(evidence):
    artifacts = {"solver.py": evidence["candidate_hash"]}
    for relative, expected in evidence["artifacts"].items():
        name = f"solutions/{hashlib.sha256(relative.encode()).hexdigest()[:12]}-{Path(relative).name}"
        if name in artifacts:
            raise ValueError("Ambiguous release artifact filenames")
        artifacts[name] = expected
    return {
        "problem": evidence["problem"],
        "candidate_hash": evidence["candidate_hash"],
        "claim_type": evidence.get("claim_type", "paired_incumbent_improvement"),
        "claim": "Improvement against the measured incumbent on the disclosed benchmark. No world-record or operational-benefit claim is implied.",
        "artifacts": artifacts,
    }


def _verify_committed_release(commit, relative, evidence):
    """Verify immutable commit bytes, including files added concurrently before staging."""
    manifest = _release_manifest(evidence)
    expected = dict(manifest["artifacts"])
    expected["manifest.json"] = hashlib.sha256(
        (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode()
    ).hexdigest()
    prefix = Path(relative).as_posix().rstrip("/") + "/"
    listing = sh("git", "ls-tree", "-r", "--name-only", commit, "--", relative)
    if listing.returncode or set(listing.stdout.splitlines()) != {prefix + name for name in expected}:
        raise RuntimeError("Committed release file set differs from approval; nothing pushed")
    for name, expected_hash in expected.items():
        blob = subprocess.run(
            ["git", "show", f"{commit}:{prefix}{name}"],
            cwd=HERE,
            capture_output=True,
            check=False,
        )
        if blob.returncode or hashlib.sha256(blob.stdout).hexdigest() != expected_hash:
            raise RuntimeError("Committed release bytes differ from approval; nothing pushed")


def _inside(root, relative):
    root = Path(root).resolve()
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or Path(relative).drive
        or "\\" in relative
    ):
        raise ValueError("Release paths must be repository-relative POSIX paths")
    path = root / relative
    if any(part in ("..", ".git") for part in Path(relative).parts):
        raise ValueError("Invalid release path")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("Symlinks are not release artifacts")
        current = current.parent
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Release artifact escapes repository")
    return resolved


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def approved_evidence(evidence_path, approval_path, root=HERE):
    """Bind approval to exact evidence, generated code, and every submitted solution."""
    root = Path(root).resolve()
    evidence_path = Path(evidence_path).resolve()
    approval_path = Path(approval_path).resolve()
    for path in (evidence_path, approval_path):
        if not path.is_relative_to(root / "runs" / "research"):
            raise ValueError("Evidence and approval must be under runs/research")
    evidence_relative = evidence_path.relative_to(root).as_posix()
    _inside(root, evidence_relative)
    _inside(root, approval_path.relative_to(root).as_posix())
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    approval = read_json(approval_path)
    if not isinstance(evidence, dict) or not isinstance(approval, dict):
        raise ValueError("Evidence and approval are required")
    if evidence.get("confirmed") is not True or evidence.get("publishable") is not True:
        raise ValueError("Evidence has not passed release confirmation")
    if approval.get("approved") is not True:
        raise ValueError("Human release approval is required")
    if (
        approval.get("evidence_path") != evidence_relative
        or approval.get("evidence_hash") != hashlib.sha256(evidence_bytes).hexdigest()
    ):
        raise ValueError("Evidence changed after approval")
    candidate = _inside(root, evidence.get("candidate_path"))
    candidate_hash = _digest(candidate)
    if candidate_hash != evidence.get("candidate_hash") or candidate_hash != approval.get("candidate_hash"):
        raise ValueError("Candidate changed after confirmation or approval")
    if approval.get("candidate_path") != evidence.get("candidate_path"):
        raise ValueError("Approved candidate path does not match")
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("Release needs a nonempty verified artifact manifest")
    for relative, expected in artifacts.items():
        if _digest(_inside(root, relative)) != expected:
            raise ValueError("A solution artifact changed after confirmation")
    return evidence


def scan_export(content):
    """Reject common credential and machine-path leaks before release staging."""
    patterns = (
        r"(?i)(?:sk-[a-z0-9_-]{20,}|gh[pousr]_[a-z0-9]{20,}|AKIA[A-Z0-9]{16})",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)[a-z]:[\\/](?:Users|Projects)[\\/]",
        r"(?i)(?:api_key|password|auth_token)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    )
    if any(re.search(pattern, content) for pattern in patterns):
        raise ValueError("Export scan rejected possible credentials or private machine paths")


def prepare_release(evidence, root=HERE):
    """Create a public bundle with no prompts, local paths, or unchecked historical files."""
    root = Path(root).resolve()
    problem = evidence.get("problem")
    if not isinstance(problem, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", problem):
        raise ValueError("Invalid problem")
    if not re.fullmatch(r"[a-f0-9]{64}", evidence.get("candidate_hash", "")):
        raise ValueError("Invalid candidate hash")
    bundle_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True, allow_nan=False).encode()).hexdigest()
    release_id = evidence["candidate_hash"][:12] + "-" + bundle_hash[:12]
    destination = _inside(root, f"releases/{problem}/{release_id}")
    sources = {"solver.py": _inside(root, evidence["candidate_path"])}
    for relative in evidence["artifacts"]:
        path = _inside(root, relative)
        if path.suffix not in (".json", ".sol", ".pck", ".txt"):
            raise ValueError("Unsupported release artifact type")
        name = f"solutions/{hashlib.sha256(relative.encode()).hexdigest()[:12]}-{path.name}"
        if name in sources:
            raise ValueError("Ambiguous release artifact filenames")
        sources[name] = path
    snapshots = {}
    for name, source in sources.items():
        content = source.read_bytes()
        expected = (
            evidence["candidate_hash"]
            if name == "solver.py"
            else evidence["artifacts"][source.relative_to(root).as_posix()]
        )
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Release source changed after confirmation")
        scan_export(content.decode("utf-8"))
        snapshots[name] = content
    if destination.exists():
        existing = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
        if existing - (set(snapshots) | {"manifest.json"}):
            raise ValueError("Existing release contains artifacts outside this approval")
    for relative, content in snapshots.items():
        target = _inside(root, destination.relative_to(root).as_posix() + "/" + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != content:
            raise ValueError("Existing release differs; refusing to overwrite it")
        if not target.exists():
            with open(target, "xb") as stream:
                stream.write(content)
    atomic_json(
        _inside(root, destination.relative_to(root).as_posix() + "/manifest.json"),
        _release_manifest(evidence),
    )
    return str(destination)


def email(*_args, **_kwargs):
    raise RuntimeError(
        "Research email is unavailable: the governed sender approves paths, not immutable body and attachment bytes. "
        "Use the local verified bundle; no send action was created."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="circle_packing")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--evidence", help="Confirmed evidence.json under runs/research")
    ap.add_argument("--approval", help="Hash-bound dashboard approval under runs/research/approvals")
    ap.add_argument(
        "--send-email", action="store_true", help="Unavailable until the governed sender binds exact attachment bytes"
    )
    ap.add_argument(
        "--push-only", action="store_true", help="explicitly commit and push only the approved evidence bundle"
    )
    a = ap.parse_args()
    if a.send_email and a.push_only:
        ap.error("--send-email and --push-only are mutually exclusive")
    if a.send_email:
        ap.error(
            "Research email is unavailable until the governed sender binds immutable body and attachment bytes. No send action was created."
        )
    if not a.evidence or not a.approval:
        if a.dry_run:
            print("Publication requires confirmed evidence and a hash-bound dashboard approval. Nothing was sent.")
            return
        ap.error("Review evidence in the dashboard, then provide --evidence and --approval")
    evidence = approved_evidence(a.evidence, a.approval)
    if evidence.get("problem") != a.problem:
        ap.error("Evidence problem does not match --problem")
    P = load_problem(a.problem)
    print(f"publish {a.problem} {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        rec = P.records_fetch()
    except Exception:
        raise RuntimeError("Current reference records unavailable; publication stopped") from None
    targets = evidence.get("artifact_targets", {})
    verified = []
    for relative in evidence["artifacts"]:
        if Path(relative).suffix != ".json":
            continue
        target = targets.get(relative)
        if target not in set(P.TARGETS) | set(getattr(P, "HOLDOUT", [])):
            raise ValueError("Approved artifact has no recognized target mapping")
        source = _inside(HERE, relative)
        value, payload = P.evaluate(str(source), target)
        validation = getattr(P, "validate_release", None)
        if validation:
            result = validation(str(source), target, record=rec.get(target))
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise ValueError("Approved artifact failed current release validation")
        verified.append((target, value, payload))
    if not verified:
        raise ValueError("No independently verified solution artifacts")
    if evidence.get("claim_type") == "benchmark_record" and any(not P.beats(v, rec.get(t)) for t, v, _ in verified):
        raise ValueError("A claimed record no longer beats the current public reference")
    approved_evidence(a.evidence, a.approval)  # Detect concurrent mutation during verification.
    if a.dry_run:
        print(f"Verified {len(verified)} approved artifacts; no files published and no messages sent")
        return
    best = prepare_release(evidence)
    for path in Path(best).rglob("*"):
        if path.is_file():
            scan_export(path.read_text(encoding="utf-8"))
    if a.push_only:
        git_push(best, False, evidence=evidence)
        return
    print(f"Prepared {len(verified)} verified artifacts locally; external publication requires an explicit action")


if __name__ == "__main__":
    main()
