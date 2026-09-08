import importlib.util
from pathlib import Path

import pytest


def arc_launcher():
    path = Path(__file__).resolve().parents[1] / "scripts" / "arc-local-server.py"
    spec = importlib.util.spec_from_file_location("arc_local_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_arc_task_refuses_an_unbuilt_or_dependency_free_checkout(tmp_path):
    launcher = arc_launcher()

    with pytest.raises(RuntimeError, match="production build"):
        launcher.launch_command(tmp_path)

    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("built", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dependencies"):
        launcher.launch_command(tmp_path)


def test_arc_task_uses_concrete_node_and_direct_next_cli(tmp_path, monkeypatch):
    launcher = arc_launcher()
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("built", encoding="utf-8")
    next_cli = tmp_path / "node_modules" / "next" / "dist" / "bin" / "next"
    next_cli.parent.mkdir(parents=True)
    next_cli.write_text("", encoding="utf-8")
    node = tmp_path / "node.exe"
    node.write_text("", encoding="utf-8")
    monkeypatch.setattr(launcher.shutil, "which", lambda _: str(node))

    command = launcher.launch_command(tmp_path)

    assert command == [
        str(node.resolve()),
        str(next_cli),
        "start",
        "--hostname",
        "127.0.0.1",
        "--port",
        "3100",
    ]


def test_arc_task_does_not_pass_an_inherited_secret_environment(monkeypatch):
    launcher = arc_launcher()
    monkeypatch.setenv("ARC_TEST_SECRET", "must-not-reach-next")
    monkeypatch.setenv("PATH", "C:\\Windows\\System32")

    environment = launcher._runtime_environment()

    assert environment["PATH"] == "C:\\Windows\\System32"
    assert "ARC_TEST_SECRET" not in environment


def test_task_installer_keeps_arc_registration_behind_preconditions():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "install-night-tasks.ps1").read_text(encoding="utf-8")

    assert '$arcTaskName = "discovery-loop-arc-atlas"' in source
    assert "$arcPreconditions" in source
    assert "if ($arcReady) {" in source
    assert "-RunLevel Limited" in source
