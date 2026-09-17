"""Open the morning brief in the default browser, starting the local dashboard first if it is down.

Scheduled by ``scripts/install-morning-task.ps1`` as ``discovery-loop-morning``. It reads the loopback
status endpoint, launches ``dashboard.py`` detached when nothing answers, then opens ``/morning``.
Nothing is sent anywhere; the page itself is served only on 127.0.0.1.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DASHBOARD = REPO / "dashboard.py"


def is_up(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_dashboard(port: int) -> int:
    """Launch the dashboard as its own detached process; it survives this script and any console."""
    executable = Path(sys.executable)
    windowless = executable.with_name("pythonw.exe")
    python = str(windowless if os.name == "nt" and windowless.is_file() else executable)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
    process = subprocess.Popen(
        [python, str(DASHBOARD), "--port", str(port)],
        cwd=REPO,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )
    return process.pid


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Open the discovery-loop morning brief")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--wait", type=float, default=20.0, help="seconds to wait for a freshly started dashboard")
    parser.add_argument("--no-browser", action="store_true", help="only make sure the dashboard is serving")
    args = parser.parse_args(argv)
    url = f"http://localhost:{args.port}/morning"
    started = None
    if not is_up(args.port):
        started = start_dashboard(args.port)
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline and not is_up(args.port, timeout=1.0):
            time.sleep(0.5)
    if not is_up(args.port):
        print(f"dashboard did not answer on port {args.port} (started pid {started})", file=sys.stderr)
        return 1
    if not args.no_browser:
        webbrowser.open(url)
    print(f"morning brief: {url}" + (f" (dashboard started, pid {started})" if started else ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
