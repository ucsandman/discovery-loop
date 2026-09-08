"""Run the local ARC Atlas production server without a shell or inherited secrets.

This is an at-logon helper.  It does not open a browser, install dependencies,
build ARC, or make network requests itself.  The launcher does not read dotenv
files; the already-built Next application retains its own documented behavior.
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ARC_REPO = REPO.parent / "arc-agi-n"
STATUS_PATH = REPO / "runs" / "arc-local-server-status.json"
LOG_PATH = REPO / "runs" / "arc-local-server.log"


def _record(state: str, *, exit_code: int | None = None, error: str | None = None) -> None:
    """Record only bounded local lifecycle facts; never child output or env."""
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    if exit_code is not None:
        payload["exit_code"] = exit_code
    if error is not None:
        payload["error"] = error
    STATUS_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _runtime_environment() -> dict[str, str]:
    """Keep only Windows runtime variables required to locate and run Node."""
    allowed = (
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "PATH",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
    )
    return {key: os.environ[key] for key in allowed if os.environ.get(key)}


def launch_command(arc_repo: Path = ARC_REPO) -> list[str]:
    """Return a concrete production command only when ARC is already built."""
    arc_repo = arc_repo.resolve()
    next_cli = arc_repo / "node_modules" / "next" / "dist" / "bin" / "next"
    build_id = arc_repo / ".next" / "BUILD_ID"
    node = shutil.which("node")
    if not build_id.is_file():
        raise RuntimeError("ARC production build is unavailable (.next/BUILD_ID is missing)")
    if not next_cli.is_file():
        raise RuntimeError("ARC dependencies are unavailable (Next executable is missing)")
    if not node or not Path(node).is_file():
        raise RuntimeError("A concrete Node executable could not be resolved")
    return [str(Path(node).resolve()), str(next_cli), "start", "--hostname", "127.0.0.1", "--port", "3100"]


def main() -> int:
    child: subprocess.Popen[bytes] | None = None
    try:
        command = launch_command()
        child = subprocess.Popen(
            command,
            cwd=ARC_REPO,
            env=_runtime_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _record("running")
        exit_code = child.wait()
        _record("exited", exit_code=exit_code)
        return exit_code
    except KeyboardInterrupt:
        _record("interrupted")
        return 130
    except RuntimeError as error:
        _record("startup_failed", error=str(error))
        return 2
    except OSError:
        _record("startup_failed", error="process launch failed")
        return 2
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            _record("terminated")


if __name__ == "__main__":
    raise SystemExit(main())
