import base64
import io
import json
import os
import subprocess
from pathlib import Path
import time

import pytest

import isolation


def _write_problem(root, name="circle_packing"):
    problem = root / "problems" / name
    problem.mkdir(parents=True)
    (problem / "records.py").write_text("# trusted helper\n", encoding="utf-8")
    (problem / "verify.py").write_text("# trusted verifier\n", encoding="utf-8")
    return problem


def test_run_solver_mounts_only_staged_inputs_and_dedicated_output(tmp_path, monkeypatch):
    _write_problem(tmp_path)
    solver = tmp_path / "candidate.py"
    solver.write_text("print('candidate')\n", encoding="utf-8")
    secret = tmp_path / "not-allowlisted.txt"
    secret.write_text("must not enter worker", encoding="utf-8")
    out = tmp_path / "runs" / "case.json"
    seen = {}

    monkeypatch.setattr(isolation, "preflight", lambda root=None, image=None: {"ok": True, "details": {}})

    def fake_container(command, timeout, name):
        seen.update(command=command, timeout=timeout, name=name)
        stage = Path(isolation._mount_source(command, "/workspace"))
        seen["stage_files"] = sorted(
            str(p.relative_to(stage)).replace("\\", "/") for p in stage.rglob("*") if p.is_file()
        )
        envelope = {
            "returncode": 0,
            "stdout": "bounded stdout",
            "stderr": "",
            "result": base64.b64encode(b'{"ok": true}').decode("ascii"),
            "output_error": None,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")

    monkeypatch.setattr(isolation, "_execute_container", fake_container)
    result = isolation.run_solver("circle_packing", solver, "26", 3, 7, out, root=tmp_path)

    assert result.returncode == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"ok": True}
    assert seen["stage_files"] == [
        "problems/circle_packing/records.py",
        "problems/circle_packing/verify.py",
        "solver.py",
        "worker_entry.py",
    ]
    assert "not-allowlisted.txt" not in " ".join(seen["command"])
    for required in ("none", "ALL", "no-new-privileges", "65532:65532", "64", "2g", "4"):
        assert required in seen["command"]
    assert "--read-only" in seen["command"]
    assert "/output:rw,noexec,nosuid,nodev,size=32m" in seen["command"]
    with pytest.raises(KeyError):
        isolation._mount_source(seen["command"], "/output")
    assert "PYTHONPATH=/workspace:/workspace/problems/circle_packing" in seen["command"]
    assert seen["timeout"] <= 48


def test_cached_cvrp_input_is_the_only_instance_staged(tmp_path, monkeypatch):
    problem = _write_problem(tmp_path, "cvrp")
    instances = problem / "instances"
    instances.mkdir()
    (instances / "wanted.vrp").write_text("NAME: wanted\n", encoding="utf-8")
    (instances / "other.vrp").write_text("NAME: other\n", encoding="utf-8")
    solver = tmp_path / "solver.py"
    solver.write_text("pass\n", encoding="utf-8")
    out = tmp_path / "runs" / "out.json"
    staged = []

    monkeypatch.setattr(isolation, "preflight", lambda root=None, image=None: {"ok": True, "details": {}})

    def fake_container(command, timeout, name):
        stage = Path(isolation._mount_source(command, "/workspace"))
        staged.extend(str(p.relative_to(stage)).replace("\\", "/") for p in stage.rglob("*") if p.is_file())
        envelope = {"returncode": 0, "stdout": "", "stderr": "", "result": None, "output_error": None}
        return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")

    monkeypatch.setattr(isolation, "_execute_container", fake_container)
    isolation.run_solver("cvrp", solver, "wanted", 1, 1, out, root=tmp_path)

    assert "problems/cvrp/instances/wanted.vrp" in staged
    assert "problems/cvrp/instances/other.vrp" not in staged


def test_unavailable_docker_raises_without_host_fallback(tmp_path, monkeypatch):
    _write_problem(tmp_path)
    solver = tmp_path / "solver.py"
    solver.write_text("raise SystemExit('must never run on host')\n", encoding="utf-8")
    monkeypatch.setattr(
        isolation, "preflight", lambda root=None, image=None: {"ok": False, "details": {"docker": "unavailable"}}
    )

    with pytest.raises(RuntimeError, match="Docker sandbox unavailable"):
        isolation.run_solver("circle_packing", solver, "26", 1, 1, tmp_path / "runs" / "out.json", root=tmp_path)


def test_rejects_candidate_symlink_and_output_escape(tmp_path):
    _write_problem(tmp_path)
    real = tmp_path / "real.py"
    real.write_text("pass\n", encoding="utf-8")
    link = tmp_path / "solver.py"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(ValueError, match="symlink"):
        isolation.run_solver("circle_packing", link, "26", 1, 1, tmp_path / "runs" / "out.json", root=tmp_path)
    with pytest.raises(ValueError, match="inside root"):
        isolation.run_solver("circle_packing", real, "26", 1, 1, tmp_path.parent / "escape.json", root=tmp_path)


def test_target_path_traversal_is_rejected(tmp_path):
    _write_problem(tmp_path)
    solver = tmp_path / "solver.py"
    solver.write_text("pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="target"):
        isolation.run_solver("circle_packing", solver, "../escape", 1, 1, tmp_path / "runs" / "out.json", root=tmp_path)


def test_host_docker_output_is_incrementally_capped_and_container_removed(monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.stdout = io.BytesIO(b"x" * 65)
            self.stderr = io.BytesIO(b"")
            self.pid = 123
            self.returncode = None
            self.killed = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self):
            self.returncode = self.returncode if self.returncode is not None else 0
            return self.returncode

    process = FakeProcess()
    commands = []
    monkeypatch.setattr(isolation.subprocess, "Popen", lambda *args, **kwargs: process)

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(isolation.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="32 byte host limit"):
        isolation._execute_container(["docker", "run"], 5, "only-this-container", output_cap=32)
    assert process.killed
    assert ["docker", "rm", "--force", "only-this-container"] in commands


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_TESTS") != "1", reason="explicit real-Docker probe")
def test_real_sandbox_blocks_network_and_host_writes(tmp_path):
    root = Path(isolation.__file__).resolve().parent
    solver = tmp_path / "security_probe.py"
    solver.write_text(
        """import argparse
import json
import os
from pathlib import Path
import socket

parser = argparse.ArgumentParser()
parser.add_argument('--n')
parser.add_argument('--time')
parser.add_argument('--seed')
parser.add_argument('--out')
args = parser.parse_args()

def denied_write(path):
    try:
        Path(path).write_text('escape', encoding='utf-8')
        return False
    except OSError:
        return True

sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect(('1.1.1.1', 53))
    network_blocked = False
except OSError:
    network_blocked = True
finally:
    sock.close()

status = Path('/proc/self/status').read_text(encoding='utf-8')
fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
def first(*paths):
    for path in paths:
        if Path(path).exists():
            return Path(path).read_text().strip()
    return 'missing'
result = {
    'uid': os.getuid(),
    'workspace_read_only': denied_write('/workspace/problems/circle_packing/escape'),
    'root_read_only': denied_write('/etc/escape'),
    'network_blocked': network_blocked,
    'cap_eff': fields['CapEff'].strip(),
    'no_new_privs': fields['NoNewPrivs'].strip(),
    'pids_max': first('/sys/fs/cgroup/pids.max', '/sys/fs/cgroup/pids/pids.max'),
    'memory_max': first('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'),
    'cpu_max': first('/sys/fs/cgroup/cpu.max'),
    'cpu_quota': first('/sys/fs/cgroup/cpu/cpu.cfs_quota_us'),
    'cpu_period': first('/sys/fs/cgroup/cpu/cpu.cfs_period_us'),
    'workspace_files': sorted(str(p.relative_to('/workspace')) for p in Path('/workspace').rglob('*') if p.is_file()),
}
Path(args.out).write_text(json.dumps(result), encoding='utf-8')
""",
        encoding="utf-8",
    )
    output = root / "tmp" / "sandbox-security-probe.json"
    completed = isolation.run_solver("circle_packing", solver, "3", 2, 1, output, root=root)
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["uid"] == 65532
    assert evidence["workspace_read_only"] and evidence["root_read_only"] and evidence["network_blocked"]
    assert evidence["cap_eff"] == "0000000000000000"
    assert evidence["no_new_privs"] == "1"
    assert evidence["pids_max"] == "64"
    assert evidence["memory_max"] == str(2 * 1024**3)
    assert evidence["cpu_max"] == "400000 100000" or (
        evidence["cpu_quota"] == "400000" and evidence["cpu_period"] == "100000"
    )
    assert evidence["workspace_files"] == [
        "problems/circle_packing/records.py",
        "problems/circle_packing/verify.py",
        "solver.py",
        "worker_entry.py",
    ]


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_TESTS") != "1", reason="explicit real-Docker probe")
def test_real_sandbox_rejects_symlink_result(tmp_path):
    root = Path(isolation.__file__).resolve().parent
    solver = tmp_path / "symlink_probe.py"
    solver.write_text(
        """import argparse
import os
parser = argparse.ArgumentParser()
parser.add_argument('--n')
parser.add_argument('--time')
parser.add_argument('--seed')
parser.add_argument('--out')
args = parser.parse_args()
os.symlink('/etc/passwd', args.out)
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="symlink"):
        isolation.run_solver("circle_packing", solver, "3", 1, 1, root / "tmp" / "symlink.json", root=root)


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_TESTS") != "1", reason="explicit real-Docker probe")
def test_real_timeout_removes_only_named_container_tree(tmp_path, monkeypatch):
    root = Path(isolation.__file__).resolve().parent
    solver = tmp_path / "timeout_probe.py"
    solver.write_text(
        """import subprocess
import sys
import time
subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
time.sleep(60)
""",
        encoding="utf-8",
    )
    fixed = "a" * 32
    monkeypatch.setattr(isolation.uuid, "uuid4", lambda: type("Id", (), {"hex": fixed})())
    name = f"discovery-solver-{fixed[:20]}"

    with pytest.raises(TimeoutError, match="isolated timeout"):
        isolation.run_solver(
            "circle_packing",
            solver,
            "3",
            10,
            1,
            root / "tmp" / "timeout.json",
            root=root,
            deadline=time.time() + 5,
        )
    inspect = subprocess.run(
        ["docker", "container", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert inspect.returncode != 0


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_TESTS") != "1", reason="explicit real-Docker probe")
def test_real_parent_fd_output_bypass_hits_host_cap_and_removes_container(tmp_path, monkeypatch):
    root = Path(isolation.__file__).resolve().parent
    solver = tmp_path / "parent_fd_probe.py"
    solver.write_text(
        """import os
import time
fd = os.open(f'/proc/{os.getppid()}/fd/1', os.O_WRONLY)
os.write(fd, b'x' * 8192)
os.close(fd)
time.sleep(60)
""",
        encoding="utf-8",
    )
    fixed = "b" * 32
    monkeypatch.setattr(isolation.uuid, "uuid4", lambda: type("Id", (), {"hex": fixed})())
    original_execute = isolation._execute_container
    monkeypatch.setattr(
        isolation,
        "_execute_container",
        lambda command, timeout, name: original_execute(command, timeout, name, output_cap=4096),
    )
    name = f"discovery-solver-{fixed[:20]}"

    with pytest.raises(ValueError, match="4096 byte host limit"):
        isolation.run_solver(
            "circle_packing",
            solver,
            "3",
            10,
            1,
            root / "tmp" / "parent-fd.json",
            root=root,
        )
    inspect = subprocess.run(
        ["docker", "container", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert inspect.returncode != 0
