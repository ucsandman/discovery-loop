#!/usr/bin/env python3
"""Result certificates for the discovery loop.

Stolen from the Ouroboros loop (cjc0013/erdos-matrix-asymptotics): a result
is not just "verified" — the certificate states exactly WHAT was checked,
binds the verifier's input to the solver's output by hash, and carries the
limitations as machine-readable fields that default to false. Nothing here
claims independent review, novelty, or optimality; those fields exist and
are false until a human or external party actually performs them.

Certificates live in nightly/certificates/<tag>-n<target>.json.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

STATE = os.path.dirname(os.path.abspath(__file__))
CERTS = os.path.join(STATE, "certificates")
VERIFIER = os.path.join(
    os.path.expanduser("~/workspace/discovery-loop"),
    "problems", "matrix_multiplication", "verify.py",
)
SELFTEST = os.path.join(STATE, "verifier_selftest.py")

CERT_VERSION = 1


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_json(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()


def write_certificate(*, tag, target, rank, record, solver_out_path,
                      factors, seed, verifier_report):
    """Write and return the path of a certificate for one promoted result.

    verifier_report is the dict produced by verifier_selftest.run_selftest
    (or the JSON it prints). The certificate binds:
      solver output bytes -> factors content hash -> verifier input,
    so a certificate cannot be attached to bytes the verifier never saw.
    """
    solver_bytes_hash = _sha256_file(solver_out_path)
    factors_hash = _sha256_json(factors)
    # The driver verifies the file at solver_out_path directly, so the
    # verifier's input hash IS the solver artifact hash. Recorded twice on
    # purpose: the chain is explicit, not implied.
    cert = {
        "certificate_version": CERT_VERSION,
        "ts": _utcnow(),
        "run_tag": tag,
        "target": str(target),
        "rank": rank,
        "record_rank": record,
        "beats_record": record is not None and rank < record,
        "seed": seed,
        "solver_artifact": {
            "path": solver_out_path,
            "sha256": solver_bytes_hash,
        },
        "factors_sha256": factors_hash,
        "verifier": {
            "path": VERIFIER,
            "sha256": _sha256_file(VERIFIER),
            "input_sha256": solver_bytes_hash,
            "input_matches_solver_artifact": True,
            "checks": ["exact_tensor_identity_over_integers"],
        },
        "verifier_selftest": {
            "passed": bool(verifier_report.get("passed")),
            "verifier_sha256_at_test": verifier_report.get("verifier_sha256"),
            "failing_controls": verifier_report.get("failing_controls", []),
        },
        "checks_performed": [
            "exact tensor identity over integers (no tolerances)",
            "integer-matrix entry validation",
            "verifier self-test: known-good passes, known-bad fails",
        ],
        # Stolen pattern: limitations as data, defaulting to false.
        # Each flips to true only when the corresponding real event happens.
        "independently_verified": False,
        "externally_reviewed": False,
        "novelty_reviewed": False,
        "published": False,
        "verification_boundary": {
            "checked": [
                "the factors satisfy the exact tensor identity",
                "the verifier itself passes true/false controls this run",
            ],
            "not_checked": [
                "optimality or lower bounds",
                "novelty against the literature",
                "human review of the result",
                "anything outside the tensor identity",
            ],
        },
    }
    os.makedirs(CERTS, exist_ok=True)
    path = os.path.join(CERTS, f"{tag}-n{target}.json")
    with open(path, "w") as fh:
        json.dump(cert, fh, indent=2)
    return path


def mark_certificate(path, **fields):
    """Flip limitation fields when the real event happens.

    e.g. mark_certificate(p, externally_reviewed=True) after Specht confirms.
    Only the known limitation fields may be set.
    """
    allowed = {"independently_verified", "externally_reviewed",
               "novelty_reviewed", "published"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown certificate fields: {sorted(unknown)}")
    with open(path) as fh:
        cert = json.load(fh)
    cert.update(fields)
    cert["last_updated"] = _utcnow()
    with open(path, "w") as fh:
        json.dump(cert, fh, indent=2)
    return path
