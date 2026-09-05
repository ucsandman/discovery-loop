"""Disposable Docker execution for generated solver programs."""

import base64
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid


HERE = Path(__file__).resolve().parent
DEFAULT_IMAGE = "discovery-loop-worker:local"
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_HELPERS = {
    "circle_packing": ("records.py", "verify.py"),
    "cvrp": ("records.py", "verify.py"),
    "miplib": ("records.py", "verify.py"),
    "miplib_open": ("records.py", "verify.py"),
    "miplib_heur": ("records.py", "verify.py"),
    "pglib_opf": ("records.py", "verify.py", "matpower.py"),
}
_METADATA = {
    "cvrp": ("records.json",),
    "miplib_open": ("records.json",),
    "miplib_heur": ("baseline.json", "benchmark_table.json"),
    "pglib_opf": ("BASELINE.md",),
}
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_LOG_CHARS = 16 * 1024
_MAX_DOCKER_OUTPUT_BYTES = 24 * 1024 * 1024
_WORKER_SCRIPT = r"""import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

MAX_OUTPUT = 16 * 1024 * 1024
MAX_LOG = 16 * 1024

def tail(path):
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - MAX_LOG))
            return stream.read().decode("utf-8", "replace")
    except OSError:
        return ""

stdout_path = Path("/tmp/solver.stdout")
stderr_path = Path("/tmp/solver.stderr")
with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
    try:
        returncode = subprocess.run(sys.argv[1:], stdout=stdout, stderr=stderr, check=False).returncode
    except OSError:
        returncode = 127
output = Path("/output/result.json")
result = None
output_error = None
if output.exists() or output.is_symlink():
    try:
        mode = output.lstat().st_mode
        if output.is_symlink() or not stat.S_ISREG(mode):
            output_error = "result.json must be a regular file, not a symlink"
        elif output.stat().st_size > MAX_OUTPUT:
            output_error = "result.json exceeds 16 MiB"
        else:
            result = base64.b64encode(output.read_bytes()).decode("ascii")
    except OSError:
        output_error = "result.json could not be read"
print(json.dumps({
    "returncode": returncode,
    "stdout": tail(stdout_path),
    "stderr": tail(stderr_path),
    "result": result,
    "output_error": output_error,
}, separators=(",", ":")))
"""


def _safe_component(value, label):
    value = str(value)
    if not _NAME.fullmatch(value) or value in (".", ".."):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _regular_source(path, label):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        raise FileNotFoundError(f"{label} not found: {path}") from None
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular file")
    return path


def _copy(source, destination, label):
    source = _regular_source(source, label)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    try:
        destination.chmod(0o444)
    except OSError:
        pass


def _stage_inputs(root, problem, solver, target, stage):
    source_problem = root / "problems" / problem
    staged_problem = stage / "problems" / problem
    if problem not in _HELPERS or not source_problem.is_dir():
        raise ValueError(f"unsupported problem {problem!r}")
    _copy(solver, stage / "solver.py", "candidate solver")
    wrapper = stage / "worker_entry.py"
    wrapper.write_text(_WORKER_SCRIPT, encoding="utf-8")
    wrapper.chmod(0o444)
    for name in _HELPERS[problem]:
        _copy(source_problem / name, staged_problem / name, f"trusted helper {name}")
    for name in _METADATA.get(problem, ()):
        source = source_problem / name
        if source.exists():
            _copy(source, staged_problem / name, f"trusted data {name}")

    if problem in ("miplib_open", "miplib_heur"):
        sibling = root / "problems" / "miplib"
        for name in ("records.py", "verify.py"):
            _copy(sibling / name, stage / "problems" / "miplib" / name, f"trusted MIPLIB helper {name}")
        for source in sibling.glob("miplib2017-v*.solu"):
            _copy(source, stage / "problems" / "miplib" / source.name, "trusted MIPLIB objective data")
        instance_source = sibling / "instances" / f"{target}.mps"
        instance_destination = stage / "problems" / "miplib" / "instances" / f"{target}.mps"
    elif problem == "miplib":
        instance_source = source_problem / "instances" / f"{target}.mps"
        instance_destination = staged_problem / "instances" / f"{target}.mps"
    elif problem == "cvrp":
        instance_source = source_problem / "instances" / f"{target}.vrp"
        instance_destination = staged_problem / "instances" / f"{target}.vrp"
    elif problem == "pglib_opf":
        instance_source = source_problem / "instances" / f"{target}.m"
        instance_destination = staged_problem / "instances" / f"{target}.m"
    else:
        instance_source = instance_destination = None
    if instance_source is not None:
        _copy(instance_source, instance_destination, f"cached instance {target}")


def _solver_arguments(problem, target, budget, seed):
    selector = ["--n", target] if problem == "circle_packing" else ["--target", target]
    return [*selector, "--time", str(budget), "--seed", str(seed), "--out", "/output/result.json"]


def _docker_command(stage, problem, target, budget, seed, image, name):
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--init",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65532:65532",
        "--pids-limit",
        "64",
        "--memory",
        "2g",
        "--cpus",
        "4",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--tmpfs",
        "/output:rw,noexec,nosuid,nodev,size=32m",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        f"PYTHONPATH=/workspace:/workspace/problems/{problem}",
        "--workdir",
        f"/workspace/problems/{problem}",
        "--mount",
        f"type=bind,source={stage},target=/workspace,readonly",
        image,
        "python",
        "/workspace/worker_entry.py",
        "python",
        "/workspace/solver.py",
        *_solver_arguments(problem, target, budget, seed),
    ]


def _mount_source(command, target):
    for index, value in enumerate(command[:-1]):
        if value != "--mount":
            continue
        fields = dict(part.split("=", 1) for part in command[index + 1].split(",") if "=" in part)
        if fields.get("target") == target:
            return fields["source"]
    raise KeyError(target)


def _kill_process_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def _remove_container(name):
    try:
        removal = subprocess.run(
            ["docker", "rm", "--force", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"sandbox container {name} could not be removed") from error
    if removal.returncode == 0:
        return
    inspect = subprocess.run(
        ["docker", "container", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=15,
    )
    if inspect.returncode == 0:
        raise RuntimeError(f"sandbox container {name} could not be removed")


def _execute_container(command, timeout, name, output_cap=_MAX_DOCKER_OUTPUT_BYTES):
    if not isinstance(output_cap, int) or isinstance(output_cap, bool) or output_cap <= 0:
        raise ValueError("output_cap must be a positive integer")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
    except OSError as error:
        raise RuntimeError("Docker sandbox unavailable") from error
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    total = [0]
    lock = threading.Lock()
    overflow = threading.Event()

    def read_stream(stream, key):
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            with lock:
                remaining = max(0, output_cap - total[0])
                if remaining:
                    buffers[key].extend(chunk[:remaining])
                total[0] += len(chunk)
                if total[0] > output_cap:
                    overflow.set()

    readers = [
        threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True),
    ]
    for reader in readers:
        reader.start()
    expires = time.monotonic() + timeout
    reason = None
    while process.poll() is None:
        if overflow.is_set():
            reason = "overflow"
            break
        if time.monotonic() >= expires:
            reason = "timeout"
            break
        time.sleep(0.01)
    if reason:
        _kill_process_tree(process)
        _remove_container(name)
    process.wait()
    for reader in readers:
        reader.join(timeout=5)
    if reason == "overflow" or overflow.is_set():
        if reason != "overflow":
            _remove_container(name)
        raise ValueError(f"sandbox output exceeded {output_cap} byte host limit")
    if reason == "timeout":
        raise TimeoutError(f"solver exceeded isolated timeout of {timeout:.1f}s")
    stdout = bytes(buffers["stdout"]).decode("utf-8", "replace")
    stderr = bytes(buffers["stderr"]).decode("utf-8", "replace")
    # stdout is the trusted wrapper envelope. Candidate stdout/stderr never reach this pipe and are bounded in /tmp.
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr[-_MAX_LOG_CHARS:])


def _bounded_output_path(root, out):
    requested = Path(out)
    if not requested.is_absolute():
        requested = root / requested
    root = root.resolve()
    resolved = requested.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("solver output must stay inside root") from None
    current = requested
    while current != root and current.parent != current:
        if current.exists() and current.is_symlink():
            raise ValueError("solver output path must not contain symlinks")
        current = current.parent
    return requested


def _write_result(data, destination):
    if data is None:
        return
    if len(data) > _MAX_OUTPUT_BYTES:
        raise ValueError("solver output exceeds 16 MiB limit")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".solver-", suffix=".tmp", dir=destination.parent)
    os.close(handle)
    try:
        Path(temporary).write_bytes(data)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _worker_result(completed):
    if completed.returncode != 0:
        return subprocess.CompletedProcess(completed.args, completed.returncode, "", completed.stderr), None
    try:
        envelope = json.loads(completed.stdout)
        returncode = int(envelope["returncode"])
        stdout = str(envelope.get("stdout", ""))[-_MAX_LOG_CHARS:]
        stderr = str(envelope.get("stderr", ""))[-_MAX_LOG_CHARS:]
        output_error = envelope.get("output_error")
        encoded = envelope.get("result")
        data = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("sandbox worker returned an invalid result envelope") from error
    if output_error:
        raise ValueError(f"invalid solver output: {output_error}")
    if data is not None and len(data) > _MAX_OUTPUT_BYTES:
        raise ValueError("solver output exceeds 16 MiB limit")
    return subprocess.CompletedProcess(completed.args, returncode, stdout, stderr), data


def preflight(root=None, image=None):
    """Check that Docker is reachable and the configured worker image exists."""
    del root
    image = image or DEFAULT_IMAGE
    details = {"image": image}
    try:
        version = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        details["docker"] = "unavailable"
        return {"ok": False, "details": details}
    if version.returncode != 0 or not version.stdout.strip():
        details["docker"] = "unavailable"
        return {"ok": False, "details": details}
    details["docker"] = version.stdout.strip()
    inspect = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    details["worker_image"] = "ready" if inspect.returncode == 0 else "missing"
    if inspect.returncode == 0:
        details["image_id"] = inspect.stdout.strip()
    return {"ok": inspect.returncode == 0, "details": details}


def run_solver(problem, solver, target, budget, seed, out, root=None, image=None, deadline=None):
    """Run one candidate in a locked-down worker and copy back only its bounded result file."""
    root = Path(root or HERE).resolve()
    problem = _safe_component(problem, "problem")
    target = _safe_component(target, "target")
    solver = Path(solver)
    if not solver.is_absolute():
        solver = root / solver
    _regular_source(solver, "candidate solver")
    destination = _bounded_output_path(root, out)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
        raise ValueError("budget must be a finite positive number")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    image = image or DEFAULT_IMAGE
    ready = preflight(root=root, image=image)
    if not ready.get("ok"):
        raise RuntimeError(f"Docker sandbox unavailable: {ready.get('details', {}).get('worker_image', 'unavailable')}")

    timeout = float(budget) + 45.0
    if deadline is not None:
        timeout = min(timeout, float(deadline) - time.time())
    if timeout <= 0:
        raise TimeoutError("solver deadline already expired")

    with tempfile.TemporaryDirectory(prefix="discovery-input-") as stage_name:
        stage = Path(stage_name)
        _stage_inputs(root, problem, solver, target, stage)
        name = f"discovery-solver-{uuid.uuid4().hex[:20]}"
        command = _docker_command(stage, problem, target, budget, seed, image, name)
        docker_result = _execute_container(command, timeout, name)
        completed, data = _worker_result(docker_result)
        _write_result(data, destination)
        return completed
