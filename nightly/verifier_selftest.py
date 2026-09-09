#!/usr/bin/env python3
"""Self-test for the matrix-multiplication exact verifier.

Stolen from the Ouroboros loop (cjc0013/erdos-matrix-asymptotics): before
trusting a check, prove it can still fail. A known-good decomposition must
PASS and several deliberately broken ones must FAIL. If any control
misbehaves, the verifier itself is untrusted and the nightly driver halts.

Usage:
    python verifier_selftest.py [--verifier PATH]

Prints a JSON report to stdout; exits 0 iff every control behaves as expected.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys

DEFAULT_VERIFIER = os.path.join(
    os.path.expanduser("~/workspace/discovery-loop"),
    "problems", "matrix_multiplication", "verify.py",
)


def _load_verifier(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _naive(n):
    """The trivial n^3 algorithm: rank n^3, always correct."""
    factors = []
    for e in range(n):
        for b in range(n):
            for f in range(n):
                u = [[0] * n for _ in range(n)]
                v = [[0] * n for _ in range(n)]
                w = [[0] * n for _ in range(n)]
                u[e][b] = 1
                v[b][f] = 1
                w[e][f] = 1
                factors.append((u, v, w))
    return factors


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_selftest(verifier_path):
    verify = _load_verifier(verifier_path)
    controls = []

    def check_control(name, factors, n, expect_feasible):
        try:
            res = verify.check(factors, n)
            got = bool(res.get("feasible"))
        except Exception as exc:  # noqa: BLE001 - a crashing verifier is a failed control
            got = f"raised: {type(exc).__name__}"
        ok = got is True and expect_feasible or got is False and not expect_feasible
        controls.append({
            "name": name,
            "expect_feasible": expect_feasible,
            "got_feasible": got,
            "passed": bool(ok),
        })

    # True controls: the naive algorithm is correct by construction.
    check_control("true/naive-n2", _naive(2), 2, True)
    check_control("true/naive-n3", _naive(3), 3, True)

    # False-statement controls: each weakens/breaks the input one way.
    broken = _naive(2)
    corrupted = copy.deepcopy(broken)
    corrupted[0][0][0][0] = 999  # single flipped entry
    check_control("false/corrupted-entry", corrupted, 2, False)

    nonint = copy.deepcopy(broken)
    nonint[0][0][0][0] = 1.0  # floats are not valid integer matrices
    check_control("false/noninteger-entry", nonint, 2, False)

    bools = copy.deepcopy(broken)
    bools[1][1][1][1] = True  # bools are explicitly rejected
    check_control("false/bool-entry", bools, 2, False)

    misshapen = copy.deepcopy(broken)
    u2, v2, _w2 = misshapen[2]
    misshapen[2] = (u2, v2, [[0, 0, 0], [0, 0, 0]])  # 2x3 instead of 2x2
    check_control("false/wrong-shape", misshapen, 2, False)

    check_control("false/empty-factors", [], 2, False)
    check_control("false/bad-n", _naive(2), 1, False)

    failing = [c["name"] for c in controls if not c["passed"]]
    return {
        "verifier_path": verifier_path,
        "verifier_sha256": _sha256_file(verifier_path),
        "controls": controls,
        "failing_controls": failing,
        "passed": not failing,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", default=DEFAULT_VERIFIER)
    args = ap.parse_args(argv)
    report = run_selftest(args.verifier)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
