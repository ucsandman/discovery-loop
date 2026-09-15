"""One-use synthetic CVRP holdout evaluation for the local review dashboard.

The cohort is deliberately modest and synthetic. It is not evidence of an
unseen public-benchmark result or a world record. Candidate programs execute
only through the existing network-disabled Docker isolation boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import string
import tempfile
import time
from typing import Any

import isolation
from problems.cvrp import verify as cvrp_verify
from research_state import FileLock, atomic_json, read_json


SCHEMA_VERSION = 1
CASE_SPECS = tuple(
    (distribution, customers) for customers in (50, 100, 150) for distribution in ("uniform", "clustered")
)
SEEDS_PER_CASE = 2
SOLVER_SECONDS = 2.0
MAX_EVALUATION_SECONDS = 240.0
BASELINE_RELATIVE = "problems/cvrp/seed_solver.py"
INCUMBENT_RELATIVE = "best-cvrp/solver.py"
ACTIVE_STATES = {"preparing", "ready", "running"}


class HoldoutError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _is_linklike(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_bytes(path: Path, maximum: int = 16 * 1024 * 1024) -> bytes:
    if _is_linklike(path):
        raise HoldoutError("unsafe_artifact", "Sealed release files must not be symbolic links.")
    try:
        before = path.stat()
        if not path.is_file() or before.st_size > maximum:
            raise HoldoutError("unsafe_artifact", "Sealed release files must be bounded regular files.")
        data = path.read_bytes()
        after = path.stat()
    except HoldoutError:
        raise
    except OSError as exc:
        raise HoldoutError("artifact_unavailable", "A sealed release file could not be read.") from exc
    before_key = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_key = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_key != after_key or len(data) != after.st_size:
        raise HoldoutError("artifact_changed", "A sealed release file changed while it was being read.")
    return data


def _private_root(root: Path | str, *, create: bool) -> tuple[Path, Path]:
    supplied = Path(root)
    if _is_linklike(supplied):
        raise HoldoutError("unsafe_root", "Repository root must not be a symbolic link.")
    try:
        repo = supplied.resolve(strict=True)
    except OSError as exc:
        raise HoldoutError("unsafe_root", "Repository root is unavailable.") from exc
    if not repo.is_dir():
        raise HoldoutError("unsafe_root", "Repository root must be a directory.")
    runs = repo / "runs"
    sealed = runs / "sealed-release"
    for path in (runs, sealed):
        if path.exists():
            if _is_linklike(path):
                raise HoldoutError("unsafe_root", "The sealed release root must not contain links or junctions.")
            try:
                path.resolve(strict=True).relative_to(repo)
            except (OSError, ValueError) as exc:
                raise HoldoutError("unsafe_root", "The sealed release root leaves the repository.") from exc
    if create:
        sealed.mkdir(parents=True, exist_ok=True)
        try:
            sealed.chmod(0o700)
        except OSError:
            pass
    return repo, sealed


def _repo_file(repo: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise HoldoutError("unsafe_candidate", "Candidate evidence points outside the repository.")
    current = repo
    for part in pure.parts:
        current = current / part
        if _is_linklike(current):
            raise HoldoutError("unsafe_candidate", "Candidate files must not use links or junctions.")
    try:
        current.resolve(strict=True).relative_to(repo)
    except (OSError, ValueError) as exc:
        raise HoldoutError("unsafe_candidate", "Candidate evidence points outside the repository.") from exc
    if not current.is_file():
        raise HoldoutError("unsafe_candidate", "Candidate evidence does not name a regular file.")
    return current


def _cohort_file(cohort: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise HoldoutError("seal_tampered", "A sealed artifact path is invalid.")
    current = cohort
    for part in pure.parts:
        current = current / part
        if _is_linklike(current):
            raise HoldoutError("seal_tampered", "A sealed artifact uses a link or junction.")
    try:
        current.resolve(strict=True).relative_to(cohort.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise HoldoutError("seal_tampered", "A sealed artifact leaves its cohort.") from exc
    if not current.is_file():
        raise HoldoutError("seal_tampered", "A sealed artifact is not a regular file.")
    return current


def _candidate_catalog(root: Path | str) -> tuple[Path, list[dict[str, Any]]]:
    repo, _ = _private_root(root, create=False)
    options: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    incumbent = _repo_file(repo, INCUMBENT_RELATIVE)
    incumbent_hash = _digest(_stable_bytes(incumbent))
    options.append(
        {
            "id": "incumbent",
            "label": "Current CVRP incumbent",
            "sha256": incumbent_hash,
            "source": "current incumbent",
            "_path": incumbent,
        }
    )
    seen_hashes.add(incumbent_hash)
    research = repo / "runs" / "research"
    if _is_linklike(research):
        raise HoldoutError("unsafe_root", "Research evidence root must not be a link or junction.")
    for evidence_path in sorted(research.glob("*/cvrp/evidence.json")) if research.is_dir() else ():
        try:
            relative_evidence = evidence_path.relative_to(repo).as_posix()
            checked_evidence = _repo_file(repo, relative_evidence)
            evidence = json.loads(_stable_bytes(checked_evidence, 1024 * 1024).decode("utf-8"))
            if not isinstance(evidence, dict):
                continue
            if (
                evidence.get("problem") != "cvrp"
                or evidence.get("status") != "completed"
                or evidence.get("confirmed") is not True
                or evidence.get("publishable") is not True
            ):
                continue
            relative = evidence.get("candidate_path")
            expected_hash = evidence.get("candidate_hash")
            if not isinstance(relative, str) or not isinstance(expected_hash, str):
                continue
            candidate = _repo_file(repo, relative)
            candidate_hash = _digest(_stable_bytes(candidate))
            if candidate_hash != expected_hash or candidate_hash in seen_hashes:
                continue
            evidence_hash = _digest(_stable_bytes(checked_evidence, 1024 * 1024))
            run_id = evidence_path.parent.parent.name
            options.append(
                {
                    "id": f"validated-{evidence_hash[:16]}",
                    "label": f"Validated CVRP candidate from {run_id}",
                    "sha256": candidate_hash,
                    "source": "validated local evidence",
                    "_path": candidate,
                }
            )
            seen_hashes.add(candidate_hash)
        except (HoldoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
    return repo, options


def candidate_options(root: Path | str) -> list[dict[str, str]]:
    """Return server-issued candidate identifiers with no filesystem paths."""
    _, options = _candidate_catalog(root)
    return [{key: option[key] for key in ("id", "label", "sha256", "source")} for option in options]


def _manifests(sealed: Path):
    if not sealed.is_dir():
        return
    for directory in sorted(sealed.iterdir()):
        if _is_linklike(directory) or not directory.is_dir():
            continue
        try:
            directory.resolve(strict=True).relative_to(sealed.resolve(strict=True))
        except (OSError, ValueError):
            continue
        path = directory / "manifest.json"
        if _is_linklike(path) or not path.is_file():
            continue
        try:
            data = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(data, dict):
            yield directory, data


def _manifest_state(manifest: dict[str, Any], now: float | None = None) -> str:
    state = manifest.get("state")
    if state == "running" and manifest.get("consumed") is True:
        deadline = manifest.get("evaluation_deadline_epoch")
        current = time.time() if now is None else now
        if isinstance(deadline, (int, float)) and not isinstance(deadline, bool) and math.isfinite(deadline):
            if current > deadline:
                return "invalid"
    return state if isinstance(state, str) else "invalid"


def _active_manifest(sealed: Path) -> tuple[Path, dict[str, Any]] | None:
    active = [(directory, data) for directory, data in _manifests(sealed) if _manifest_state(data) in ACTIVE_STATES]
    if len(active) > 1:
        raise HoldoutError("invalid_state", "Multiple active sealed cohorts exist; evaluation is blocked.")
    return active[0] if active else None


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o600)
    except FileExistsError as exc:
        raise HoldoutError("artifact_exists", "A sealed release artifact already exists.") from exc


def _instance_bytes(case_id: str, distribution: str, customers: int, rng) -> bytes:
    if distribution == "uniform":
        points = [(rng.randrange(0, 10001), rng.randrange(0, 10001)) for _ in range(customers)]
    else:
        centers = [(rng.randrange(1000, 9001), rng.randrange(1000, 9001)) for _ in range(4)]
        points = []
        for _ in range(customers):
            center_x, center_y = centers[rng.randrange(len(centers))]
            points.append(
                (
                    max(0, min(10000, center_x + rng.randrange(-900, 901))),
                    max(0, min(10000, center_y + rng.randrange(-900, 901))),
                )
            )
    demands = [rng.randrange(1, 11) for _ in range(customers)]
    lines = [
        f"NAME : {case_id}",
        "COMMENT : Fresh synthetic sealed-release cohort; not a public benchmark",
        "TYPE : CVRP",
        f"DIMENSION : {customers + 1}",
        "EDGE_WEIGHT_TYPE : EUC_2D",
        "CAPACITY : 50",
        "NODE_COORD_SECTION",
        "1 5000 5000",
    ]
    lines.extend(f"{index} {x} {y}" for index, (x, y) in enumerate(points, 2))
    lines.append("DEMAND_SECTION")
    lines.append("1 0")
    lines.extend(f"{index} {demand}" for index, demand in enumerate(demands, 2))
    lines.extend(("DEPOT_SECTION", "1", "-1", "EOF"))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _new_cohort_id(rng) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    return f"{stamp}-{suffix}"


def prepare(root: Path | str, candidate_id: str) -> dict[str, Any]:
    """Freeze one approved candidate/baseline pair, then generate six cases."""
    repo, sealed = _private_root(root, create=True)
    if not isinstance(candidate_id, str):
        raise HoldoutError("invalid_candidate", "Select a candidate offered by this dashboard.")
    rng = secrets.SystemRandom()
    with FileLock(sealed / ".holdout.lock"):
        if _active_manifest(sealed):
            raise HoldoutError("active_cohort", "A sealed cohort is already prepared or running.")
        _, options = _candidate_catalog(repo)
        selected = next((option for option in options if option["id"] == candidate_id), None)
        if selected is None:
            raise HoldoutError("invalid_candidate", "Select a candidate offered by this dashboard.")
        if any(data.get("candidate", {}).get("sha256") == selected["sha256"] for _, data in _manifests(sealed)):
            raise HoldoutError("candidate_already_sealed", "This exact candidate has already used a sealed cohort.")

        baseline_path = _repo_file(repo, BASELINE_RELATIVE)
        candidate_bytes = _stable_bytes(selected["_path"])
        baseline_bytes = _stable_bytes(baseline_path)
        candidate_hash = _digest(candidate_bytes)
        baseline_hash = _digest(baseline_bytes)
        if candidate_hash != selected["sha256"]:
            raise HoldoutError("candidate_changed", "The selected candidate changed before it could be frozen.")

        cohort_id = _new_cohort_id(rng)
        cohort = sealed / cohort_id
        cohort.mkdir(parents=False, exist_ok=False)
        try:
            cohort.chmod(0o700)
        except OSError:
            pass
        _write_private(cohort / "candidate.py", candidate_bytes)
        _write_private(cohort / "baseline.py", baseline_bytes)
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "cohort_id": cohort_id,
            "state": "preparing",
            "prepared_at": _utc_now(),
            "candidate": {
                "id": selected["id"],
                "label": selected["label"],
                "sha256": candidate_hash,
            },
            "baseline": {"label": "Seed baseline", "sha256": baseline_hash},
            "limits": {
                "case_count": len(CASE_SPECS),
                "seeds_per_case": SEEDS_PER_CASE,
                "solver_seconds_each": SOLVER_SECONDS,
                "planned_solver_runs": len(CASE_SPECS) * SEEDS_PER_CASE * 2,
                "solver_seconds_total": len(CASE_SPECS) * SEEDS_PER_CASE * 2 * SOLVER_SECONDS,
                "evaluation_deadline_seconds": MAX_EVALUATION_SECONDS,
            },
            "classification": "fresh synthetic CVRP holdout; not unseen public-benchmark proof",
        }
        atomic_json(cohort / "manifest.json", manifest)

        instance_manifest = []
        instances = cohort / "instances"
        for distribution, customers in CASE_SPECS:
            case_id = f"sealed-{distribution}-{customers:03d}"
            data = _instance_bytes(case_id, distribution, customers, rng)
            _write_private(instances / f"{case_id}.vrp", data)
            instance_manifest.append(
                {
                    "id": case_id,
                    "distribution": distribution,
                    "customers": customers,
                    "sha256": _digest(data),
                }
            )
        secret_data = json.dumps(
            {"solver_seeds": [rng.randrange(1, 2**31) for _ in range(SEEDS_PER_CASE)]},
            separators=(",", ":"),
        ).encode("utf-8")
        _write_private(cohort / "secrets.json", secret_data)
        instance_manifest_bytes = json.dumps(instance_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest.update(
            {
                "state": "ready",
                "instances": instance_manifest,
                "instance_manifest_hash": _digest(instance_manifest_bytes),
                "secrets_sha256": _digest(secret_data),
            }
        )
        atomic_json(cohort / "manifest.json", manifest)
    return public_status(repo)


def _invalidate(cohort: Path, manifest: dict[str, Any], message: str) -> None:
    manifest.update({"state": "invalid", "invalidated_at": _utc_now(), "failure": message})
    atomic_json(cohort / "manifest.json", manifest)


def _validate_seal(cohort: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("cohort_id") != cohort.name:
            raise HoldoutError("seal_tampered", "The sealed cohort manifest is invalid.")
        if _digest(_stable_bytes(_cohort_file(cohort, "candidate.py"))) != manifest.get("candidate", {}).get("sha256"):
            raise HoldoutError("seal_tampered", "The frozen candidate no longer matches its seal.")
        if _digest(_stable_bytes(_cohort_file(cohort, "baseline.py"))) != manifest.get("baseline", {}).get("sha256"):
            raise HoldoutError("seal_tampered", "The frozen baseline no longer matches its seal.")
        instances = manifest.get("instances")
        if not isinstance(instances, list) or len(instances) != len(CASE_SPECS):
            raise HoldoutError("seal_tampered", "The sealed instance manifest is invalid.")
        canonical = json.dumps(instances, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if _digest(canonical) != manifest.get("instance_manifest_hash"):
            raise HoldoutError("seal_tampered", "The sealed instance manifest hash does not match.")
        for item in instances:
            expected_keys = {"id", "distribution", "customers", "sha256"}
            if not isinstance(item, dict) or set(item) != expected_keys:
                raise HoldoutError("seal_tampered", "The sealed instance manifest is invalid.")
            instance = _cohort_file(cohort, f"instances/{item['id']}.vrp")
            if _digest(_stable_bytes(instance)) != item["sha256"]:
                raise HoldoutError("seal_tampered", "A sealed synthetic instance no longer matches its seal.")
        secret_bytes = _stable_bytes(_cohort_file(cohort, "secrets.json"), 4096)
        if _digest(secret_bytes) != manifest.get("secrets_sha256"):
            raise HoldoutError("seal_tampered", "The private evaluation seeds no longer match their seal.")
        secret_data = json.loads(secret_bytes.decode("utf-8"))
        seeds = secret_data.get("solver_seeds") if isinstance(secret_data, dict) else None
        if (
            not isinstance(seeds, list)
            or len(seeds) != SEEDS_PER_CASE
            or any(isinstance(seed, bool) or not isinstance(seed, int) or seed <= 0 for seed in seeds)
        ):
            raise HoldoutError("seal_tampered", "The private evaluation seeds are invalid.")
        return {"solver_seeds": seeds}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise HoldoutError("seal_tampered", "The sealed cohort could not be verified.") from exc


def _stage_private_root(
    repo: Path,
    instance_item: dict[str, Any],
    destination: Path,
    instance_bytes: bytes,
    solver_bytes: bytes,
) -> tuple[Path, Path]:
    problem = destination / "problems" / "cvrp"
    problem.mkdir(parents=True)
    for name in ("records.py", "verify.py", "records.json"):
        source = _repo_file(repo, f"problems/cvrp/{name}")
        shutil.copyfile(source, problem / name)
    staged_instances = problem / "instances"
    staged_instances.mkdir()
    instance = staged_instances / f"{instance_item['id']}.vrp"
    solver = destination / "frozen-solver.py"
    _write_private(instance, instance_bytes)
    _write_private(solver, solver_bytes)
    return instance, solver


def _run_one(
    repo: Path,
    cohort: Path,
    manifest: dict[str, Any],
    instance_item: dict[str, Any],
    solver_name: str,
    seed: int,
    runner,
    deadline: float,
    worker_image_id: str,
) -> dict[str, Any]:
    if time.time() >= deadline:
        return {"status": "deadline", "reason": "The sealed evaluation deadline was reached."}
    solver = _cohort_file(cohort, "candidate.py" if solver_name == "candidate" else "baseline.py")
    expected_solver_hash = manifest[solver_name]["sha256"]
    solver_bytes = _stable_bytes(solver)
    if _digest(solver_bytes) != expected_solver_hash:
        raise HoldoutError("seal_tampered", f"The frozen {solver_name} changed during evaluation.")
    source_instance = _cohort_file(cohort, f"instances/{instance_item['id']}.vrp")
    instance_bytes = _stable_bytes(source_instance)
    if _digest(instance_bytes) != instance_item["sha256"]:
        raise HoldoutError("seal_tampered", "A sealed synthetic instance changed during evaluation.")
    private_temp = cohort / "private-tmp"
    private_temp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=private_temp) as temporary:
        work_root = Path(temporary)
        trusted_instance, staged_solver = _stage_private_root(
            repo, instance_item, work_root, instance_bytes, solver_bytes
        )
        output = work_root / "result.json"
        try:
            completed = runner(
                "cvrp",
                staged_solver,
                instance_item["id"],
                SOLVER_SECONDS,
                seed,
                output,
                root=work_root,
                image=worker_image_id,
                deadline=deadline,
            )
        except Exception as exc:
            return {"status": "failed", "reason": f"Isolated solver failed: {type(exc).__name__}."}
        if getattr(completed, "returncode", 1) != 0:
            return {"status": "failed", "reason": "Isolated solver exited without a usable result."}
        try:
            payload = json.loads(_stable_bytes(output).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("target") != instance_item["id"]:
                raise ValueError("unexpected target")
            solution = payload.get("solution")
            if not isinstance(solution, dict):
                raise ValueError("missing solution")
            if _digest(_stable_bytes(trusted_instance)) != instance_item["sha256"]:
                raise HoldoutError("seal_tampered", "The staged synthetic instance changed during evaluation.")
            verified = cvrp_verify.check_instance_path(solution, trusted_instance, instance_item["id"])
        except HoldoutError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
            return {"status": "invalid_output", "reason": "Independent verifier rejected the solver output."}
        if verified.get("feasible") is not True:
            return {"status": "infeasible", "reason": "Independent verifier found an infeasible route set."}
        objective = verified.get("obj")
        if isinstance(objective, bool) or not isinstance(objective, (int, float)) or not math.isfinite(objective):
            return {"status": "invalid_output", "reason": "Independent verifier returned no finite objective."}
        return {"status": "completed", "objective": int(objective)}


def _matched_row(instance_item: dict[str, Any], repetition: int, baseline: dict[str, Any], candidate: dict[str, Any]):
    row = {
        "case": instance_item["id"],
        "distribution": instance_item["distribution"],
        "customers": instance_item["customers"],
        "repetition": repetition,
        "baseline": baseline,
        "candidate": candidate,
    }
    if baseline["status"] != "completed" or candidate["status"] != "completed":
        row.update({"outcome": "not_comparable", "relative_gain": None})
        return row
    baseline_obj, candidate_obj = baseline["objective"], candidate["objective"]
    gain = (baseline_obj - candidate_obj) / baseline_obj if baseline_obj else 0.0
    outcome = (
        "improved"
        if candidate_obj < baseline_obj
        else "worse"
        if candidate_obj > baseline_obj
        else "equal_no_improvement"
    )
    row.update({"outcome": outcome, "relative_gain": round(gain, 8)})
    return row


def _resolve_worker_image(repo: Path) -> str:
    ready = isolation.preflight(root=repo)
    details = ready.get("details") if isinstance(ready, dict) else None
    image_id = details.get("image_id") if isinstance(details, dict) else None
    if ready.get("ok") is not True or not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise HoldoutError("sandbox_unavailable", "The immutable Docker worker image could not be resolved.")
    return image_id


def evaluate(root: Path | str, *, runner=None, image_resolver=None) -> dict[str, Any]:
    """Consume the active cohort before executing its first isolated solver."""
    repo, sealed = _private_root(root, create=False)
    runner = runner or isolation.run_solver
    image_resolver = image_resolver or (lambda: _resolve_worker_image(repo))
    with FileLock(sealed / ".holdout.lock"):
        active = _active_manifest(sealed)
        if active is None:
            if any(True for _ in _manifests(sealed)):
                raise HoldoutError("cohort_consumed", "The sealed cohort has already been consumed.")
            raise HoldoutError("no_ready_cohort", "Prepare a sealed cohort before evaluation.")
        cohort, manifest = active
        if manifest.get("state") != "ready":
            raise HoldoutError("cohort_consumed", "This sealed cohort has already been consumed.")
        try:
            secret_data = _validate_seal(cohort, manifest)
        except HoldoutError as exc:
            _invalidate(cohort, manifest, exc.args[0])
            raise
        worker_image_id = image_resolver()
        if not isinstance(worker_image_id, str) or not worker_image_id.startswith("sha256:"):
            raise HoldoutError("sandbox_unavailable", "The immutable Docker worker image could not be resolved.")
        deadline = time.time() + MAX_EVALUATION_SECONDS
        manifest.update(
            {
                "state": "running",
                "consumed": True,
                "consumed_at": _utc_now(),
                "worker_image_id": worker_image_id,
                "evaluation_deadline_epoch": deadline,
            }
        )
        atomic_json(cohort / "manifest.json", manifest)

    rows = []
    for instance_item in manifest["instances"]:
        for repetition, seed in enumerate(secret_data["solver_seeds"], 1):
            baseline = _run_one(
                repo, cohort, manifest, instance_item, "baseline", seed, runner, deadline, worker_image_id
            )
            candidate = _run_one(
                repo, cohort, manifest, instance_item, "candidate", seed, runner, deadline, worker_image_id
            )
            rows.append(_matched_row(instance_item, repetition, baseline, candidate))

    completed_solver_runs = sum(
        result["status"] == "completed" for row in rows for result in (row["baseline"], row["candidate"])
    )
    matched_pairs = sum(row["outcome"] != "not_comparable" for row in rows)
    planned_solver_runs = len(CASE_SPECS) * SEEDS_PER_CASE * 2
    outcome_counts = {
        name: sum(row["outcome"] == name for row in rows)
        for name in ("improved", "equal_no_improvement", "worse", "not_comparable")
    }
    state = (
        "completed"
        if completed_solver_runs == planned_solver_runs
        else "partial"
        if completed_solver_runs
        else "failed"
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "cohort_id": manifest["cohort_id"],
        "state": state,
        "finished_at": _utc_now(),
        "classification": (
            "descriptive synthetic holdout; no public-benchmark, world-record, publication, or promotion claim"
            if state == "completed"
            else "nonclaim partial or failed synthetic holdout"
        ),
        "candidate": manifest["candidate"],
        "baseline": manifest["baseline"],
        "instance_manifest_hash": manifest["instance_manifest_hash"],
        "worker_image_id": worker_image_id,
        "volumes": {
            "cases": len(CASE_SPECS),
            "seeds_per_case": SEEDS_PER_CASE,
            "planned_solver_runs": planned_solver_runs,
            "completed_solver_runs": completed_solver_runs,
            "failed_solver_runs": planned_solver_runs - completed_solver_runs,
            "matched_pairs": matched_pairs,
            "solver_seconds_limit": len(CASE_SPECS) * SEEDS_PER_CASE * 2 * SOLVER_SECONDS,
        },
        "outcomes": outcome_counts,
        "rows": rows,
    }
    atomic_json(cohort / "result.json", result)
    with FileLock(sealed / ".holdout.lock"):
        current = read_json(cohort / "manifest.json")
        if not isinstance(current, dict) or current.get("state") != "running" or current.get("consumed") is not True:
            raise HoldoutError("invalid_state", "The consumed cohort state changed during evaluation.")
        current.update(
            {
                "state": state,
                "finished_at": result["finished_at"],
                "result_sha256": _digest(_stable_bytes(cohort / "result.json")),
            }
        )
        atomic_json(cohort / "manifest.json", current)
    return public_status(repo)


def _public_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    rows = []
    for row in result.get("rows", []):
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "case": row.get("case"),
                "distribution": row.get("distribution"),
                "customers": row.get("customers"),
                "repetition": row.get("repetition"),
                "baseline": row.get("baseline"),
                "candidate": row.get("candidate"),
                "outcome": row.get("outcome"),
                "relative_gain": row.get("relative_gain"),
            }
        )
    return {
        "state": result.get("state"),
        "classification": result.get("classification"),
        "volumes": result.get("volumes"),
        "outcomes": result.get("outcomes"),
        "worker_image_id": result.get("worker_image_id"),
        "rows": rows,
    }


def public_status(root: Path | str) -> dict[str, Any]:
    """Return the dashboard-safe view. It excludes paths, seeds, instances, and raw output."""
    repo, sealed = _private_root(root, create=False)
    manifests = list(_manifests(sealed))
    latest = manifests[-1] if manifests else None
    active = _active_manifest(sealed)
    selected = active or latest
    cohort_view = None
    if selected:
        cohort, manifest = selected
        result = None
        public_state = _manifest_state(manifest)
        public_failure = manifest.get("failure")
        if public_state == "invalid" and manifest.get("state") == "running":
            public_failure = "The consumed evaluation passed its deadline and cannot be retried."
        result_path = cohort / "result.json"
        expects_result = manifest.get("state") in {"completed", "partial", "failed"} or "result_sha256" in manifest
        if result_path.exists() and not _is_linklike(result_path):
            try:
                result_bytes = _stable_bytes(_cohort_file(cohort, "result.json"))
                candidate_result = json.loads(result_bytes.decode("utf-8"))
                if (
                    _digest(result_bytes) != manifest.get("result_sha256")
                    or not isinstance(candidate_result, dict)
                    or candidate_result.get("schema_version") != SCHEMA_VERSION
                    or candidate_result.get("cohort_id") != manifest.get("cohort_id")
                    or candidate_result.get("state") != manifest.get("state")
                ):
                    public_state = "invalid"
                    public_failure = "The stored evaluation result no longer matches its seal."
                else:
                    result = candidate_result
            except (HoldoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                public_state = "invalid"
                public_failure = "The stored evaluation result could not be verified."
                result = None
        elif expects_result:
            public_state = "invalid"
            public_failure = "The stored evaluation result is missing or is not a regular sealed file."
        cohort_view = {
            "id": manifest.get("cohort_id"),
            "state": public_state,
            "consumed": manifest.get("consumed") is True,
            "prepared_at": manifest.get("prepared_at"),
            "consumed_at": manifest.get("consumed_at"),
            "finished_at": manifest.get("finished_at"),
            "candidate": manifest.get("candidate"),
            "baseline": manifest.get("baseline"),
            "instance_manifest_hash": manifest.get("instance_manifest_hash"),
            "limits": manifest.get("limits"),
            "classification": manifest.get("classification"),
            "failure": public_failure,
            "result": _public_result(result),
        }
    used_hashes = {
        data.get("candidate", {}).get("sha256") for _, data in manifests if isinstance(data.get("candidate"), dict)
    }
    available = [candidate for candidate in candidate_options(repo) if candidate.get("sha256") not in used_hashes]
    return {
        "cohort": cohort_view,
        "can_prepare": active is None and bool(available),
        "can_evaluate": bool(active and active[1].get("state") == "ready"),
        "candidates": available if active is None else [],
        "notice": (
            "Fresh synthetic CVRP cohort only. This is not unseen public-benchmark proof, a world record, or publication approval."
        ),
    }
