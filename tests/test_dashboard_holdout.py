import json
import hashlib
from pathlib import Path
import shutil
import threading
import urllib.error
import urllib.request

import dashboard
import sealed_holdout
from research_state import atomic_json


REPO = Path(__file__).resolve().parents[1]


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
        shutil.copyfile(REPO / relative, target)
    return tmp_path


def _request(base, path, *, payload=None, csrf="holdout-token", origin=True):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["X-CSRF-Token"] = csrf
    if origin:
        headers["Origin"] = base
    request = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_holdout_http_preparation_uses_server_candidate_ids_and_existing_request_guards(tmp_path):
    root = _repo(tmp_path)
    server = dashboard.create_server(root=root, port=0, csrf_token="holdout-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, initial = _request(base, "/api/status")
        assert status == 200
        assert initial["holdout"]["candidates"][0]["id"] == "incumbent"
        assert "path" not in json.dumps(initial["holdout"]["candidates"]).lower()

        status, body = _request(base, "/api/holdout/prepare", payload={"candidate_id": "incumbent"}, origin=False)
        assert status == 403 and body["error"] == "same_origin_required"
        status, body = _request(
            base,
            "/api/holdout/prepare",
            payload={"candidate_id": "incumbent"},
            csrf="wrong",
        )
        assert status == 403 and body["error"] == "csrf_failed"
        status, body = _request(base, "/api/holdout/prepare", payload={"candidate_id": "../../solver.py"})
        assert status == 400 and body["error"] == "invalid_candidate"

        status, body = _request(base, "/api/holdout/prepare", payload={"candidate_id": "incumbent"})
        assert status == 201
        holdout = body["holdout"]
        assert holdout["cohort"]["state"] == "ready"
        assert holdout["can_evaluate"] is True
        assert "solver_seeds" not in json.dumps(holdout)
        assert "candidate_path" not in json.dumps(holdout)
        status, body = _request(base, "/api/holdout/prepare", payload={"candidate_id": "incumbent"})
        assert status == 409 and body["error"] == "active_cohort"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dashboard_html_exposes_named_prepare_and_evaluate_once_controls(tmp_path):
    root = _repo(tmp_path)
    app = dashboard.DashboardApp(root)

    page = (app.web_root / "index.html").read_text(encoding="utf-8")

    assert 'id="holdout-prepare">Prepare sealed cohort</button>' in page
    assert 'id="holdout-evaluate" disabled>Evaluate once</button>' in page
    assert "not unseen public-benchmark proof" in page


def test_completed_candidate_is_replaced_by_new_validated_candidate_for_next_prepare(tmp_path):
    root = _repo(tmp_path)
    sealed_holdout.prepare(root, "incumbent")
    manifest_path = next((root / "runs" / "sealed-release").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"state": "invalid", "consumed": True})
    atomic_json(manifest_path, manifest)

    candidate = root / "runs" / "research" / "validated" / "cvrp" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("# new validated candidate\n", encoding="utf-8")
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
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
    available = sealed_holdout.public_status(root)
    assert available["can_prepare"] is True
    assert [item["sha256"] for item in available["candidates"]] == [candidate_hash]

    server = dashboard.create_server(root=root, port=0, csrf_token="holdout-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body = _request(
            base,
            "/api/holdout/prepare",
            payload={"candidate_id": available["candidates"][0]["id"]},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status == 201
    assert body["holdout"]["cohort"]["candidate"]["sha256"] == candidate_hash
    assert body["holdout"]["cohort"]["state"] == "ready"
