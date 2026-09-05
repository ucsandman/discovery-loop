import hashlib
import http.client
import json
import threading
import urllib.error
import urllib.request

import pytest

import dashboard
import night


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def dashboard_server(tmp_path):
    server = dashboard.create_server(root=tmp_path, port=0, csrf_token="test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield tmp_path, f"http://127.0.0.1:{port}", port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(base, path, *, method="GET", payload=None, csrf="test-token", origin=True):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    if origin:
        headers["Origin"] = base
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _schedule():
    cycle = []
    modes = ["fable", "astra", "paired"]
    for index in range(14):
        cycle.append(
            {
                "cvrp": modes[index % 3],
                "miplib_heur": modes[(index + 1) % 3],
                "order": ["cvrp", "miplib_heur"] if index % 2 == 0 else ["miplib_heur", "cvrp"],
            }
        )
    return {
        "schema_version": 2,
        "night": {
            "deadline_minutes": 500,
            "budget_usd": 45,
            "heartbeat_seconds": 15,
            "provider_caps_usd": {"fable": 20, "astra": 20, "paired": 20},
            "evidence_root": "runs/research",
            "keep": "unchanged",
        },
        "trial": {"anchor_date": "2026-09-05", "cycle": cycle},
        "slots": [
            {
                "id": "cvrp",
                "problem": "cvrp",
                "kind": "research",
                "minutes": 100,
                "research_minutes": 80,
                "retro_minutes": 20,
                "slot_budget_usd": 10,
                "per_call_budget_usd": 2,
                "retro_budget_usd": 2.5,
            },
            {
                "id": "miplib-heur",
                "problem": "miplib_heur",
                "kind": "research",
                "minutes": 100,
                "research_minutes": 80,
                "retro_minutes": 20,
                "slot_budget_usd": 10,
                "per_call_budget_usd": 2,
                "retro_budget_usd": 2.5,
            },
            {
                "id": "pglib-validation",
                "problem": "pglib_opf",
                "kind": "validation",
                "minutes": 30,
                "slot_budget_usd": 0,
                "per_call_budget_usd": 0,
                "retro_budget_usd": 0,
            },
        ],
    }


def test_status_reads_real_night_control_schedule_and_legacy_counts(dashboard_server):
    root, base, _ = dashboard_server
    _write_json(root / "runs" / "control.json", {"paused": True})
    _write_json(root / "runs" / "night-status.json", {"status": "paused", "slots": [{"status": "completed"}]})
    _write_json(root / "night.json", _schedule())
    (root / "runs-cvrp").mkdir()
    (root / "runs-cvrp" / "log.jsonl").write_text(
        '{"status":"seed"}\n{"status":"champion","wins":["A"]}\n', encoding="utf-8"
    )

    status, body = _request(base, "/api/status", origin=False, csrf=None)

    assert status == 200
    assert body["csrf_token"] == "test-token"
    assert body["control"]["paused"] is True
    assert body["night_status"]["status"] == "paused"
    assert body["schedule"]["duration_minutes"] == 500
    assert body["legacy"] == [
        {"problem": "cvrp", "iterations": 2, "champions": 1, "wins": 1, "classification": "historical_unvalidated"}
    ]


def test_evidence_returns_hash_and_preserves_raw_fields(dashboard_server):
    root, base, _ = dashboard_server
    evidence = {
        "run_id": "run-1",
        "problem": "cvrp",
        "provider": "paired",
        "status": "completed",
        "confirmed": True,
        "publishable": True,
        "candidate_path": "problems/cvrp/candidate.py",
        "candidate_hash": "a" * 64,
        "confirmation": {"median_gain": 0.03, "custom": [1, 2]},
    }
    evidence_path = root / "runs" / "research" / "run-1" / "cvrp" / "evidence.json"
    _write_json(evidence_path, evidence)

    status, body = _request(base, "/api/evidence", origin=False, csrf=None)

    assert status == 200
    assert body["evidence"][0]["evidence_path"] == "runs/research/run-1/cvrp/evidence.json"
    assert body["evidence"][0]["evidence_hash"] == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    assert body["evidence"][0]["raw"]["confirmation"]["custom"] == [1, 2]


def test_evidence_raw_and_hash_come_from_the_same_file_read(tmp_path, monkeypatch):
    path = tmp_path / "runs" / "research" / "run-1" / "cvrp" / "evidence.json"
    first = {"run_id": "run-1", "problem": "cvrp", "provider": "fable", "claim": "first"}
    second = {"run_id": "run-1", "problem": "cvrp", "provider": "fable", "claim": "second"}
    _write_json(path, first)
    stable_bytes = dashboard._stable_bytes

    def replace_before_read(target, maximum=None):
        _write_json(target, second)
        return stable_bytes(target, maximum)

    monkeypatch.setattr(dashboard, "_stable_bytes", replace_before_read)
    item = dashboard.DashboardApp(tmp_path, csrf_token="test-token").evidence()["evidence"][0]
    expected = path.read_bytes()

    assert item["raw"]["claim"] == "second"
    assert item["evidence_hash"] == hashlib.sha256(expected).hexdigest()


def test_status_includes_equal_budget_trial_summary(dashboard_server):
    root, base, _ = dashboard_server
    _write_json(
        root / "runs" / "research" / "2026-09-05" / "cvrp" / "evidence.json",
        {
            "run_id": "2026-09-05",
            "problem": "cvrp",
            "provider": "fable",
            "status": "completed",
            "confirmed": True,
            "usage": {"calls": 4, "charged": 3.5},
            "solver_seconds": 3600,
            "solver_evaluations": 24,
            "confirmation": {"median_gain": 0.02},
        },
    )

    status, body = _request(base, "/api/status", origin=False, csrf=None)

    assert status == 200
    assert body["trial"]["runs"] == 1
    assert body["trial"]["rows"][0]["provider"] == "fable"
    assert body["trial"]["rows"][0]["allowance_charged"] == 3.5
    assert body["trial"]["rows"][0]["solver_hours"] == 1.0


def test_posts_require_same_origin_and_csrf(dashboard_server):
    root, base, _ = dashboard_server

    status, body = _request(base, "/api/control", method="POST", payload={"action": "pause"}, origin=False)
    assert (status, body["error"]) == (403, "same_origin_required")

    status, body = _request(base, "/api/control", method="POST", payload={"action": "pause"}, csrf="wrong-token")
    assert (status, body["error"]) == (403, "csrf_failed")
    assert not (root / "runs" / "control.json").exists()


def test_rejects_untrusted_host(dashboard_server):
    _, _, port = dashboard_server
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.putrequest("GET", "/api/status", skip_host=True)
    connection.putheader("Host", "attacker.example")
    connection.endheaders()
    response = connection.getresponse()
    body = json.loads(response.read())
    connection.close()

    assert response.status == 403
    assert body["error"] == "untrusted_host"


def test_pause_continue_and_review_request_are_local_state(dashboard_server):
    root, base, _ = dashboard_server
    status, body = _request(base, "/api/control", method="POST", payload={"action": "pause"})
    assert status == 200
    assert body["control"]["paused"] is True

    status, body = _request(
        base,
        "/api/control",
        method="POST",
        payload={"action": "request_review", "evidence_path": "runs/research/run-1/cvrp/evidence.json"},
    )
    assert status == 200
    assert body["control"]["review_request"]["evidence_path"].endswith("evidence.json")

    status, body = _request(base, "/api/control", method="POST", payload={"action": "continue"})
    assert status == 200
    assert body["control"]["paused"] is False
    assert "publish" not in (root / "runs" / "control.json").read_text(encoding="utf-8")


def test_schedule_updates_safe_fields_and_preserves_the_rest(dashboard_server):
    root, base, _ = dashboard_server
    _write_json(root / "night.json", _schedule())
    payload = {
        "duration_minutes": 360,
        "nightly_budget_usd": 30,
        "provider_caps_usd": {"fable": 10, "astra": 12.5, "paired": 15},
    }

    status, body = _request(base, "/api/schedule", method="POST", payload=payload)

    assert status == 200
    assert body["schedule"] == payload
    saved = json.loads((root / "night.json").read_text(encoding="utf-8"))
    assert saved["night"]["keep"] == "unchanged"
    assert saved["slots"] == _schedule()["slots"]


def test_lower_allowance_scales_allocations_and_remains_runnable(dashboard_server):
    root, base, _ = dashboard_server
    _write_json(root / "night.json", _schedule())
    payload = {
        "duration_minutes": 180,
        "nightly_budget_usd": 10,
        "provider_caps_usd": {"fable": 8, "astra": 8, "paired": 8},
    }

    status, _ = _request(base, "/api/schedule", method="POST", payload=payload)

    assert status == 200
    saved = night.load_schedule(root / "night.json")
    allocated = sum(slot["slot_budget_usd"] + slot["retro_budget_usd"] for slot in saved["slots"])
    assert allocated == pytest.approx(10)
    assert sum(slot["minutes"] for slot in saved["slots"]) == pytest.approx(180)
    assert all(
        0 < slot["per_call_budget_usd"] <= slot["slot_budget_usd"]
        for slot in saved["slots"]
        if slot["kind"] == "research"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"duration_minutes": 59, "nightly_budget_usd": 30, "provider_caps_usd": {"fable": 1, "astra": 1, "paired": 1}},
        {"duration_minutes": 360, "nightly_budget_usd": 91, "provider_caps_usd": {"fable": 1, "astra": 1, "paired": 1}},
        {"duration_minutes": 360, "nightly_budget_usd": 30, "provider_caps_usd": {"fable": 1, "astra": 1}},
        {
            "duration_minutes": 360,
            "nightly_budget_usd": 30,
            "provider_caps_usd": {"fable": -1, "astra": 1, "paired": 1},
        },
    ],
)
def test_schedule_rejects_unsafe_values(dashboard_server, payload):
    root, base, _ = dashboard_server
    _write_json(root / "night.json", _schedule())
    status, body = _request(base, "/api/schedule", method="POST", payload=payload)
    assert status == 400
    assert body["error"] == "invalid_payload"


def test_approval_is_bound_to_exact_candidate_and_evidence_hashes(dashboard_server):
    root, base, _ = dashboard_server
    candidate = root / "problems" / "cvrp" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("print('candidate')\n", encoding="utf-8")
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    evidence_path = root / "runs" / "research" / "run-1" / "cvrp" / "evidence.json"
    _write_json(
        evidence_path,
        {
            "run_id": "run-1",
            "problem": "cvrp",
            "provider": "paired",
            "status": "completed",
            "confirmed": True,
            "publishable": True,
            "candidate_path": "problems/cvrp/candidate.py",
            "candidate_hash": candidate_hash,
        },
    )
    evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    payload = {
        "evidence_path": "runs/research/run-1/cvrp/evidence.json",
        "evidence_hash": evidence_hash,
        "candidate_path": "problems/cvrp/candidate.py",
        "candidate_hash": candidate_hash,
        "confirmed": True,
    }

    status, body = _request(base, "/api/approve", method="POST", payload=payload)

    assert status == 201
    approval = json.loads(
        (root / "runs" / "research" / "approvals" / f"{candidate_hash}.json").read_text(encoding="utf-8")
    )
    assert approval["approved"] is True
    assert approval["candidate_hash"] == candidate_hash
    assert approval["evidence_hash"] == evidence_hash
    assert approval["candidate_path"] == "problems/cvrp/candidate.py"
    assert body["message"] == "Approval queued locally. No publication occurred."


@pytest.mark.parametrize("changed", ["candidate", "evidence"])
def test_approval_rejects_mutated_files(dashboard_server, changed):
    root, base, _ = dashboard_server
    candidate = root / "problems" / "cvrp" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("original\n", encoding="utf-8")
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    evidence_path = root / "runs" / "research" / "run-1" / "cvrp" / "evidence.json"
    _write_json(
        evidence_path,
        {
            "run_id": "run-1",
            "problem": "cvrp",
            "provider": "paired",
            "status": "completed",
            "confirmed": True,
            "publishable": True,
            "candidate_path": "problems/cvrp/candidate.py",
            "candidate_hash": candidate_hash,
        },
    )
    payload = {
        "evidence_path": "runs/research/run-1/cvrp/evidence.json",
        "evidence_hash": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "candidate_path": "problems/cvrp/candidate.py",
        "candidate_hash": candidate_hash,
        "confirmed": True,
    }
    if changed == "candidate":
        candidate.write_text("mutated\n", encoding="utf-8")
    else:
        evidence_path.write_text(evidence_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    status, body = _request(base, "/api/approve", method="POST", payload=payload)

    assert status == 409
    assert body["error"] == "artifact_changed"
    assert not (root / "runs" / "research" / "approvals").exists()


def test_approval_rejects_unconfirmed_or_path_traversal(dashboard_server):
    root, base, _ = dashboard_server
    evidence_path = root / "runs" / "research" / "run-1" / "cvrp" / "evidence.json"
    _write_json(evidence_path, {"confirmed": False, "publishable": True})
    payload = {
        "evidence_path": "runs/research/run-1/cvrp/evidence.json",
        "evidence_hash": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "candidate_path": "../outside.py",
        "candidate_hash": "a" * 64,
        "confirmed": True,
    }

    status, body = _request(base, "/api/approve", method="POST", payload=payload)

    assert status == 400
    assert body["error"] == "invalid_payload"


def test_static_routes_are_allowlisted(dashboard_server):
    _, base, _ = dashboard_server
    request = urllib.request.Request(base + "/../../dashboard.py")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=3)
    assert caught.value.code == 404


def test_page_has_keyboard_landmarks_and_named_controls(dashboard_server):
    _, base, _ = dashboard_server
    with urllib.request.urlopen(base + "/", timeout=3) as response:
        page = response.read().decode("utf-8")

    assert '<a class="skip" href="#main">Skip to research ledger</a>' in page
    assert '<main class="shell" id="main">' in page
    assert 'aria-live="polite"' in page
    assert 'type="button">Pause after checkpoint</button>' in page
    assert 'type="button">Continue research</button>' in page
    assert 'id="approval-check" type="checkbox"' in page
    assert 'tabindex="-1"' not in page


def test_rejects_oversized_json_before_reading_body(dashboard_server):
    _, _, port = dashboard_server
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(
        "POST",
        "/api/control",
        body=b"{}",
        headers={
            "Host": f"127.0.0.1:{port}",
            "Origin": f"http://127.0.0.1:{port}",
            "X-CSRF-Token": "test-token",
            "Content-Type": "application/json",
            "Content-Length": str(dashboard.MAX_BODY_BYTES + 1),
        },
    )
    response = connection.getresponse()
    body = json.loads(response.read())
    connection.close()
    assert response.status == 413
    assert body["error"] == "body_too_large"
