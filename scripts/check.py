"""Run application tests and each legacy plugin suite in a fresh interpreter."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    suites = [
        ["tests", "test_loop.py"],
        ["problems/cvrp/test_cvrp.py"],
        ["problems/miplib_open/test_miplib_open.py"],
    ]
    for number, paths in enumerate(suites, 1):
        print(f"Verification suite {number}/{len(suites)}: {', '.join(paths)}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *paths, "-q", "-p", "no:xonsh"],
            cwd=ROOT,
            timeout=300,
        )
        if result.returncode:
            return result.returncode
    sources = [path.name for path in ROOT.glob("*.py") if path.name != ".vulture_whitelist.py"]
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *sources, "tests", "problems", "scripts"],
        cwd=ROOT,
        timeout=120,
    )
    if result.returncode:
        return result.returncode
    modules = list(ROOT.glob("*.py")) + list((ROOT / "problems").rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))
    for path in modules:
        compile(path.read_bytes(), str(path.relative_to(ROOT)), "exec")
    print(f"Verified {len(suites)} test suites; lint passed; compiled {len(modules)} Python files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
