import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import types

import pytest

import sealed_holdout
from problems.cvrp import verify


REPO = Path(__file__).resolve().parents[1]
IMAGE_ID = "sha256:" + "a" * 64
IMAGE_RESOLVER = lambda: IMAGE_ID


def _repo(tmp_path):
    for relative in (
        "best-cvrp/solver.py",
        "problems/cvrp/seed_solver.py",
        "problems/cvrp/records.py",
        "problems/cvrp/records.json",
        "problems/cvrp/verify.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith("solver.py"):
            target.write_text(f"# frozen {relative}\n", encoding="utf-8")
        else:
            shutil.copyfile(REPO / relative, target)
    return tmp_path


def _active(root):
    cohorts = list((root / "runs" / "sealed-release").glob("*/manifest.json"))
    assert len(cohorts) == 1
    return cohorts[0].parent, json.loads(cohorts[0].read_text(encoding="utf-8"))


def _feasible_runner(_problem, solver, target, _budget, _seed, out, *, root, image, deadline, **_kwargs):
    assert image == IMAGE_ID
    assert deadline > time.time()
    assert Path(solver).parent == root and Path(solver).name == "frozen-solver.py"
    instance = root / "problems" / "cvrp" / "instances" / f"{target}.vrp"
    parsed = verify.load_instance_path(instance, target)
    solution = {"routes": [[customer] for customer in range(1, parsed["n"] + 1)]}
    out.write_text(json.dumps({"target": target, "solution": solution}), encoding="utf-8")
    return types.SimpleNamespace(returncode=0)


def _all_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_keys(child)


def test_prepare_freezes_fixed_synthetic_cohort_before_generation_and_keeps_secrets_private(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    original = sealed_holdout._instance_bytes
    observed = []

    def inspect_freeze(*args):
        cohort, manifest = _active(root)
        observed.append(
            manifest["state"] == "preparing"
            and (cohort / "candidate.py").is_file()
            and (cohort / "baseline.py").is_file()
        )
        return original(*args)

    monkeypatch.setattr(sealed_holdout, "_instance_bytes", inspect_freeze)
    view = sealed_holdout.prepare(root, "incumbent")
    cohort, manifest = _active(root)

    assert observed == [True] * 6
    assert [(item["distribution"], item["customers"]) for item in manifest["instances"]] == [
        ("uniform", 50),
        ("clustered", 50),
        ("uniform", 100),
        ("clustered", 100),
        ("uniform", 150),
        ("clustered", 150),
    ]
    assert manifest["limits"]["planned_solver_runs"] == 24
    assert manifest["limits"]["solver_seconds_total"] == 48.0
    assert manifest["classification"].startswith("fresh synthetic")
    assert len(manifest["instance_manifest_hash"]) == 64
    assert (cohort / "secrets.json").is_file()
    serialized = json.dumps(view)
    assert "solver_seeds" not in serialized and "secrets.json" not in serialized
    assert not ({"stdout", "stderr", "candidate_path", "instance_path"} & set(_all_keys(view)))


def test_evaluate_once_uses_matched_runs_and_equality_is_no_improvement(tmp_path):
    root = _repo(tmp_path)
    sealed_holdout.prepare(root, "incumbent")

    view = sealed_holdout.evaluate(root, runner=_feasible_runner, image_resolver=IMAGE_RESOLVER)

    result = view["cohort"]["result"]
    assert result["state"] == "completed"
    assert result["volumes"] == {
        "cases": 6,
        "seeds_per_case": 2,
        "planned_solver_runs": 24,
        "completed_solver_runs": 24,
        "failed_solver_runs": 0,
        "matched_pairs": 12,
        "solver_seconds_limit": 48.0,
    }
    assert result["outcomes"] == {
        "improved": 0,
        "equal_no_improvement": 12,
        "worse": 0,
        "not_comparable": 0,
    }
    assert all(row["relative_gain"] == 0.0 for row in result["rows"])
    assert "world-record" in result["classification"]
    with pytest.raises(sealed_holdout.HoldoutError, match="already been consumed") as error:
        sealed_holdout.evaluate(root, runner=_feasible_runner, image_resolver=IMAGE_RESOLVER)
    assert error.value.code == "cohort_consumed"
    with pytest.raises(sealed_holdout.HoldoutError, match="already used"):
        sealed_holdout.prepare(root, "incumbent")


def test_tamper_invalidates_cohort_before_any_solver_executes(tmp_path):
    root = _repo(tmp_path)
    sealed_holdout.prepare(root, "incumbent")
    cohort, _ = _active(root)
    (cohort / "candidate.py").write_text("# changed\n", encoding="utf-8")
    calls = []

    with pytest.raises(sealed_holdout.HoldoutError) as error:
        sealed_holdout.evaluate(
            root,
            runner=lambda *args, **kwargs: calls.append((args, kwargs)),
            image_resolver=IMAGE_RESOLVER,
        )

    assert error.value.code == "seal_tampered"
    assert calls == []
    assert _active(root)[1]["state"] == "invalid"


def test_interruption_consumes_cohort_and_blocks_retry(tmp_path):
    root = _repo(tmp_path)
    sealed_holdout.prepare(root, "incumbent")

    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        sealed_holdout.evaluate(root, runner=interrupted, image_resolver=IMAGE_RESOLVER)
    assert _active(root)[1]["state"] == "running"
    assert _active(root)[1]["consumed"] is True
    with pytest.raises(sealed_holdout.HoldoutError) as error:
        sealed_holdout.evaluate(root, runner=_feasible_runner, image_resolver=IMAGE_RESOLVER)
    assert error.value.code == "cohort_consumed"


def test_concurrent_evaluation_is_rejected_after_atomic_consumption(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(sealed_holdout, "CASE_SPECS", (("uniform", 50),))
    sealed_holdout.prepare(root, "incumbent")
    entered = threading.Event()
    release = threading.Event()
    failures = []

    def blocking_runner(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return _feasible_runner(*args, **kwargs)

    def first_evaluation():
        try:
            sealed_holdout.evaluate(root, runner=blocking_runner, image_resolver=IMAGE_RESOLVER)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=first_evaluation)
    thread.start()
    assert entered.wait(5)
    try:
        with pytest.raises(sealed_holdout.HoldoutError) as error:
            sealed_holdout.evaluate(root, runner=_feasible_runner, image_resolver=IMAGE_RESOLVER)
        assert error.value.code == "cohort_consumed"
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and failures == []


def test_infeasible_untrusted_output_is_a_nonclaim_failure(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(sealed_holdout, "CASE_SPECS", (("uniform", 50),))
    sealed_holdout.prepare(root, "incumbent")

    def infeasible(_problem, _solver, target, _budget, _seed, out, **_kwargs):
        out.write_text(json.dumps({"target": target, "solution": {"routes": []}}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    view = sealed_holdout.evaluate(root, runner=infeasible, image_resolver=IMAGE_RESOLVER)
    result = view["cohort"]["result"]
    assert result["state"] == "failed"
    assert result["volumes"]["completed_solver_runs"] == 0
    assert result["outcomes"]["not_comparable"] == 2
    assert result["classification"].startswith("nonclaim")
    assert all(row["candidate"]["status"] == "infeasible" for row in result["rows"])


def test_symlinked_private_root_and_candidate_are_rejected(tmp_path):
    root = _repo(tmp_path / "root")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "runs").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable on this Windows host")
    with pytest.raises(sealed_holdout.HoldoutError) as error:
        sealed_holdout.prepare(root, "incumbent")
    assert error.value.code == "unsafe_root"

    (root / "runs").unlink()
    candidate = root / "best-cvrp" / "solver.py"
    candidate.unlink()
    candidate.symlink_to(outside / "solver.py")
    with pytest.raises(sealed_holdout.HoldoutError) as error:
        sealed_holdout.candidate_options(root)
    assert error.value.code == "unsafe_candidate"


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction regression")
def test_junctioned_private_root_is_rejected(tmp_path):
    root = _repo(tmp_path / "root")
    outside = tmp_path / "outside"
    outside.mkdir()
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "runs"), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode:
        pytest.skip("NTFS junction creation is unavailable on this host")

    with pytest.raises(sealed_holdout.HoldoutError) as error:
        sealed_holdout.prepare(root, "incumbent")

    assert error.value.code == "unsafe_root"


def test_explicit_instance_verifier_does_not_use_global_instance_lookup(tmp_path, monkeypatch):
    data = sealed_holdout._instance_bytes("trusted", "uniform", 50, sealed_holdout.secrets.SystemRandom())
    instance = tmp_path / "trusted.vrp"
    instance.write_bytes(data)
    monkeypatch.setattr(verify, "instance_path", lambda _name: pytest.fail("global instance lookup used"))

    parsed = verify.load_instance_path(instance, "trusted")
    solution = {"routes": [[customer] for customer in range(1, parsed["n"] + 1)]}
    result = verify.check_instance_path(solution, instance, "trusted")

    assert result["feasible"] is True
    assert result["n_routes"] == 50


def test_verifier_rejects_million_entry_route_before_distance_work(tmp_path, monkeypatch):
    data = sealed_holdout._instance_bytes("trusted", "uniform", 50, sealed_holdout.secrets.SystemRandom())
    instance = tmp_path / "trusted.vrp"
    instance.write_bytes(data)
    parsed = verify.load_instance_path(instance, "trusted")
    monkeypatch.setattr(verify, "dist_matrix", lambda _coords: pytest.fail("distance work should not start"))

    result = verify.check_instance({"routes": [[1] * 1_000_000]}, parsed)

    assert result["feasible"] is False
    assert result["reason"] == "solution contains more than the 50 available customers"
    assert result["duplicate_customers"] == [1]


def test_public_status_never_surfaces_a_tampered_completed_result(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(sealed_holdout, "CASE_SPECS", (("uniform", 50),))
    sealed_holdout.prepare(root, "incumbent")
    sealed_holdout.evaluate(root, runner=_feasible_runner, image_resolver=IMAGE_RESOLVER)
    cohort, manifest = _active(root)
    assert manifest["state"] == "completed"
    result_path = cohort / "result.json"
    changed = json.loads(result_path.read_text(encoding="utf-8"))
    changed["outcomes"]["improved"] = 999
    result_path.write_text(json.dumps(changed), encoding="utf-8")

    view = sealed_holdout.public_status(root)

    assert view["cohort"]["state"] == "invalid"
    assert view["cohort"]["result"] is None
    assert "no longer matches its seal" in view["cohort"]["failure"]


def test_public_status_marks_a_missing_completed_result_invalid(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(sealed_holdout, "CASE_SPECS", (("uniform", 50),))
    sealed_holdout.prepare(root, "incumbent")
    sealed_holdout.evaluate(root, runner=_feasible_runner, image_resolver=IMAGE_RESOLVER)
    cohort, _ = _active(root)
    (cohort / "result.json").unlink()

    view = sealed_holdout.public_status(root)

    assert view["cohort"]["state"] == "invalid"
    assert view["cohort"]["result"] is None
    assert "missing" in view["cohort"]["failure"]


def test_instance_change_between_matched_runs_stays_consumed_and_cannot_complete(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(sealed_holdout, "CASE_SPECS", (("uniform", 50),))
    sealed_holdout.prepare(root, "incumbent")
    cohort, _ = _active(root)
    instance = next((cohort / "instances").glob("*.vrp"))
    calls = 0

    def mutate_after_first_run(*args, **kwargs):
        nonlocal calls
        completed = _feasible_runner(*args, **kwargs)
        calls += 1
        if calls == 1:
            instance.write_bytes(instance.read_bytes() + b"\n")
        return completed

    with pytest.raises(sealed_holdout.HoldoutError) as error:
        sealed_holdout.evaluate(root, runner=mutate_after_first_run, image_resolver=IMAGE_RESOLVER)

    assert error.value.code == "seal_tampered"
    manifest = _active(root)[1]
    assert manifest["state"] == "running" and manifest["consumed"] is True
    assert not (cohort / "result.json").exists()


def test_expired_consumed_run_is_invalid_and_allows_only_a_different_candidate(tmp_path):
    root = _repo(tmp_path)
    sealed_holdout.prepare(root, "incumbent")
    _, manifest = _active(root)
    manifest_path = root / "runs" / "sealed-release" / manifest["cohort_id"] / "manifest.json"
    manifest.update({"state": "running", "consumed": True, "evaluation_deadline_epoch": time.time() - 1})
    atomic_json = sealed_holdout.atomic_json
    atomic_json(manifest_path, manifest)

    candidate = root / "runs" / "research" / "new" / "cvrp" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("# different candidate\n", encoding="utf-8")
    candidate_hash = sealed_holdout._digest(candidate.read_bytes())
    atomic_json(
        candidate.with_name("evidence.json"),
        {
            "problem": "cvrp",
            "status": "completed",
            "confirmed": True,
            "publishable": True,
            "candidate_path": candidate.relative_to(root).as_posix(),
            "candidate_hash": candidate_hash,
        },
    )

    view = sealed_holdout.public_status(root)
    assert view["cohort"]["state"] == "invalid"
    assert "passed its deadline" in view["cohort"]["failure"]
    assert view["can_prepare"] is True
    assert [option["sha256"] for option in view["candidates"]] == [candidate_hash]
    with pytest.raises(sealed_holdout.HoldoutError) as error:
        sealed_holdout.evaluate(root, runner=_feasible_runner, image_resolver=IMAGE_RESOLVER)
    assert error.value.code == "cohort_consumed"

    prepared = sealed_holdout.prepare(root, view["candidates"][0]["id"])
    assert prepared["cohort"]["candidate"]["sha256"] == candidate_hash
