import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import publish

from publish import approved_evidence, candidates, prepare_release, scan_export
from research_state import atomic_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(root):
    directory = root / "runs/research/test/cvrp"
    directory.mkdir(parents=True)
    solver = directory / "solver.py"
    solver.write_text("print('solver')\n", encoding="utf-8")
    solution = directory / "target.json"
    solution.write_text('{"solution": {"routes": [[1]]}}', encoding="utf-8")
    evidence_path = directory / "evidence.json"
    evidence = {
        "problem": "cvrp",
        "confirmed": True,
        "publishable": True,
        "candidate_path": solver.relative_to(root).as_posix(),
        "candidate_hash": digest(solver),
        "artifacts": {solution.relative_to(root).as_posix(): digest(solution)},
    }
    atomic_json(evidence_path, evidence)
    approval_path = root / "runs/research/approvals/approval.json"
    atomic_json(
        approval_path,
        {
            "approved": True,
            "evidence_path": evidence_path.relative_to(root).as_posix(),
            "evidence_hash": digest(evidence_path),
            "candidate_path": evidence["candidate_path"],
            "candidate_hash": evidence["candidate_hash"],
        },
    )
    return evidence_path, approval_path, solver, solution


def test_matching_approval_and_artifacts_are_accepted(tmp_path):
    evidence, approval, _, _ = bundle(tmp_path)
    result = approved_evidence(evidence, approval, root=tmp_path)
    release = Path(prepare_release(result, root=tmp_path))
    assert (release / "solver.py").exists()
    assert len(list((release / "solutions").glob("*-target.json"))) == 1
    assert str(tmp_path) not in (release / "manifest.json").read_text()


@pytest.mark.parametrize("changed", ["evidence", "solver", "solution"])
def test_changed_evidence_code_or_solution_invalidates_approval(tmp_path, changed):
    evidence, approval, solver, solution = bundle(tmp_path)
    target = {"evidence": evidence, "solver": solver, "solution": solution}[changed]
    target.write_text(target.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        approved_evidence(evidence, approval, root=tmp_path)


def test_unconfirmed_evidence_cannot_be_approved(tmp_path):
    evidence, approval, _, _ = bundle(tmp_path)
    import json

    data = json.loads(evidence.read_text())
    data["confirmed"] = False
    atomic_json(evidence, data)
    with pytest.raises(ValueError, match="confirmation"):
        approved_evidence(evidence, approval, root=tmp_path)


@pytest.mark.parametrize("text", ["sk-" + "X" * 24, "C:/Users/private/file", "password = 'long-secret'"])
def test_export_scan_has_positive_detection(text):
    with pytest.raises(ValueError, match="Export scan"):
        scan_export(text)


def test_reverified_value_must_still_beat_reference(tmp_path):
    atomic_json(tmp_path / "scores.json", {"target": {"value": 1}})
    plugin = SimpleNamespace(
        beats=lambda value, reference: value < reference,
        evaluate=lambda *_: (10, {}),
        raw_path=lambda *_: "unused",
    )
    assert candidates(plugin, str(tmp_path), {"target": 5}, {}) == []


def test_release_identity_includes_evidence_and_rejects_unapproved_files(tmp_path):
    evidence_path, approval, _, _ = bundle(tmp_path)
    evidence = approved_evidence(evidence_path, approval, root=tmp_path)
    first = Path(prepare_release(evidence, root=tmp_path))
    changed = dict(evidence, claim_type="paired_incumbent_improvement")
    second = Path(prepare_release(changed, root=tmp_path))
    assert first != second
    (first / "unapproved.txt").write_text("historical output", encoding="utf-8")
    with pytest.raises(ValueError, match="outside this approval"):
        prepare_release(evidence, root=tmp_path)


def test_release_checks_source_hash_again_before_copy(tmp_path):
    evidence_path, approval, _, solution = bundle(tmp_path)
    evidence = approved_evidence(evidence_path, approval, root=tmp_path)
    solution.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after confirmation"):
        prepare_release(evidence, root=tmp_path)


@pytest.mark.parametrize("mutation", [None, "extra_file", "changed_solver"])
def test_committed_tree_must_match_exact_approved_bytes(tmp_path, monkeypatch, mutation):
    evidence_path, approval, _, _ = bundle(tmp_path)
    evidence = approved_evidence(evidence_path, approval, root=tmp_path)
    release = Path(prepare_release(evidence, root=tmp_path))
    relative = release.relative_to(tmp_path).as_posix()
    blobs = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in release.rglob("*") if p.is_file()}
    if mutation == "extra_file":
        blobs[relative + "/unapproved.txt"] = b"not approved"
    elif mutation == "changed_solver":
        blobs[relative + "/solver.py"] = b"print('changed')"
    monkeypatch.setattr(publish, "sh", lambda *args: SimpleNamespace(returncode=0, stdout="\n".join(blobs)))
    monkeypatch.setattr(
        publish.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=blobs[args[2].split(":", 1)[1]],
        ),
    )
    if mutation:
        with pytest.raises(RuntimeError, match="differs|differ"):
            publish._verify_committed_release("commit", relative, evidence)
    else:
        publish._verify_committed_release("commit", relative, evidence)


def test_research_email_fails_closed_before_any_external_action(monkeypatch):
    monkeypatch.setattr(publish, "sh", lambda *args, **kwargs: pytest.fail("external action must not be created"))
    with pytest.raises(RuntimeError, match="immutable"):
        publish.email(None, None, None, None, None, None, False, False)
