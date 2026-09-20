import json
from pathlib import Path
import shutil
import threading
import urllib.error
import urllib.request

import pytest

import dashboard
import night
import prize_report


REPO = Path(__file__).resolve().parents[1]


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _repo(tmp_path):
    """A checkout with the real registry and the two prize plugins, and nothing else."""
    shutil.copyfile(REPO / "data" / "prizes.json", _mkdir(tmp_path / "data") / "prizes.json")
    for plugin in ("ecc_prize", "hash_collision_prize"):
        for name in ("problem.py", "records.py", "records.json", "verify.py", "seed_solver.py"):
            source = REPO / "problems" / plugin / name
            if source.is_file():
                target = tmp_path / "problems" / plugin / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    return tmp_path


def _mkdir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def dashboard_server(tmp_path):
    server = dashboard.create_server(root=_repo(tmp_path), port=0, csrf_token="test-token")
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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _evidence(run_id, problem, *, candidates, confirmed=False, publishable=False, confirmation=None):
    return {
        "run_id": run_id,
        "problem": problem,
        "status": "completed",
        "confirmed": confirmed,
        "publishable": publishable,
        "solver_seconds": 120.0,
        "development": {"candidates": candidates},
        "confirmation": confirmation or {},
        "finished_at": f"{run_id}T06:00:00Z",
    }


def test_build_prize_never_raises_on_an_empty_checkout(tmp_path):
    summary = prize_report.build_prize(tmp_path)

    assert summary["board"] == []
    assert summary["registry"]["prizes"] == []
    assert summary["queue"]["allocations"] == []
    assert summary["nightly"] == {"enabled": False, "block": None}
    assert summary["notices"] and isinstance(summary["notices"][0], str)
    assert set(summary["money_board"]) == {key for key, _ in prize_report.MONEY_BOARD_RULES}
    assert all(card["id"] is None and card["rule"] for card in summary["money_board"].values())
    # The footnote sentences come from the installed plugins, not from the run tree.
    assert [row["plugin"] for row in summary["non_claims"]] == ["hash_collision_prize", "ecc_prize"]


def test_build_prize_scores_every_registry_prize_and_reads_the_recorded_runs(tmp_path):
    root = _repo(tmp_path)
    _write_json(
        root / "runs" / "research" / "2026-09-21" / "hash_collision_prize" / "evidence.json",
        _evidence(
            "2026-09-21",
            "hash_collision_prize",
            candidates=[
                {
                    "iteration": 1,
                    "idea": "batched compression",
                    "cost_usd": 0.5,
                    "median_gain": 0.21,
                    "development_status": "promising",
                },
                # Three rejected attempts in one idea family are what a stop recommendation is made of.
                {
                    "iteration": 2,
                    "idea": "wider distinguished points",
                    "cost_usd": 0.25,
                    "median_gain": None,
                    "development_status": "rejected",
                },
                {
                    "iteration": 3,
                    "idea": "wider distinguished points at a 2^-20 rate",
                    "cost_usd": 0.25,
                    "median_gain": None,
                    "development_status": "rejected",
                },
                {
                    "iteration": 4,
                    "idea": "wider distinguished points with a shorter tail",
                    "cost_usd": 0.25,
                    "median_gain": 0.0,
                    "development_status": "rejected",
                },
            ],
        ),
    )
    _write_json(
        root / "data" / "prizes" / "intake" / "example-open-challenge.json",
        {
            "schema_version": 1,
            "status": "candidate",
            "url": "https://example.org/challenge",
            "kind": "challenge",
            "fetched_at": "2026-09-20T00:00:00Z",
            "title": "Example open challenge",
            "content_classification": "untrusted_quoted_source",
        },
    )
    _write_json(
        root / "runs" / "research" / "development-history" / "hash_collision_prize-retro.json",
        {"schema_version": 1, "next_experiment": "Re-run the batched walk with 4x the batch size."},
    )

    summary = prize_report.build_prize(root)
    board = {row["id"]: row for row in summary["board"]}

    assert len(board) == 17
    assert all(isinstance(row["score"]["priority_score"], float) for row in summary["board"])

    hashed = board["todd-sha256-collision"]
    assert hashed["admission"] == "ready"
    assert hashed["attempts"] == 4
    assert hashed["best_candidate"]["iteration"] == 1
    assert hashed["performance_improvement_pct"] == pytest.approx(21.0)
    # The measured 21 percent gain is translated into a scaling-impact sentence; no verdict changes.
    assert "speedup" in hashed["ev_impact"] and "percent" in hashed["ev_impact"]
    assert hashed["research_state"] == "ready-for-confirmation"
    assert hashed["ready_for_confirmation"] is True
    assert hashed["ready_for_human_review"] is False
    assert hashed["next_experiment"] == "Re-run the batched walk with 4x the batch size."
    assert hashed["scaling"]["target_bits"] == 256
    assert hashed["scaling"]["supported"] is True
    assert hashed["scaling"]["verdict"] == "infeasible"

    # A prize with no bound plugin still gets a row, a score and an honest empty state.
    hutter = board["hutter-prize"]
    assert hutter["plugin"] is None
    assert hutter["admission"] == "needs_setup"
    assert hutter["research_state"] == "not-started"
    assert hutter["scaling"] is None

    assert summary["money_board"]["strongest_measurable_progress"]["id"] == "todd-sha256-collision"
    assert "21.00 percent" in summary["money_board"]["strongest_measurable_progress"]["why"]
    assert summary["money_board"]["largest_legitimate_prize"]["id"] == "todd-sha256-collision"
    assert summary["queue"]["label"] == prize_report.DISABLED_QUEUE_LABEL
    assert summary["queue"]["allowance_usd"] == prize_report.DEFAULT_ALLOWANCE_USD
    assert summary["nightly"]["enabled"] is False

    # Every money-board card answers its question from this evidence tree; none is left blank.
    assert set(summary["money_board"]) == {key for key, _ in prize_report.MONEY_BOARD_RULES}
    assert all(card["id"] and card["why"] and card["rule"] for card in summary["money_board"].values())

    # The three rejected attempts in one family become a dead-end-shaped stop recommendation.
    stop = summary["stop_recommendations"][0]
    assert set(stop) == {"problem", "approach", "why_failed", "evidence", "tags"}
    assert stop["problem"] == "hash_collision_prize"
    assert stop["approach"].startswith("wider distinguished points")
    assert "3 attempts" in stop["why_failed"]
    assert stop["evidence"] == "runs/research/2026-09-21/hash_collision_prize/evidence.json"
    assert "hash_collision_prize" in stop["tags"] and "distinguished" in stop["tags"]

    # The economics ledger carries the full totals block for each bound plugin.
    ledger = summary["economics"]["hash_collision_prize"]
    assert set(ledger["totals"]) == {
        "model_usd",
        "reported_usd",
        "local_compute_usd",
        "solver_seconds",
        "best_gain",
        "candidates",
    }
    assert ledger["totals"]["candidates"] == 4
    assert ledger["totals"]["best_gain"] == pytest.approx(0.21)
    assert ledger["totals"]["model_usd"] == pytest.approx(1.25)
    assert ledger["directions_total"] == len(ledger["directions"]) == 2

    # The intake candidate is listed before anyone approves it, and it is still only a candidate.
    assert summary["intake"] == [
        {
            "slug": "example-open-challenge",
            "status": "candidate",
            "url": "https://example.org/challenge",
            "title": "Example open challenge",
            "kind": "challenge",
            "fetched_at": "2026-09-20T00:00:00Z",
            "path": "data/prizes/intake/example-open-challenge.json",
        }
    ]
    assert not any(row["id"] == "example-open-challenge" for row in summary["board"])


def test_build_prize_reads_the_nightly_block_and_flags_evidence_waiting_on_a_person(tmp_path):
    root = _repo(tmp_path)
    _write_json(
        root / "night.json",
        {"schema_version": 1, "prizes": {"enabled": True, "slot_budget_usd": 8.0, "research_minutes": 45}},
    )
    _write_json(
        root / "runs" / "research" / "2026-09-22" / "ecc_prize" / "evidence.json",
        _evidence(
            "2026-09-22",
            "ecc_prize",
            candidates=[{"iteration": 3, "idea": "simultaneous inversion", "cost_usd": 1.0, "median_gain": 0.3}],
            confirmed=True,
            publishable=True,
            confirmation={"median_gain": 0.3},
        ),
    )

    summary = prize_report.build_prize(root)
    row = next(item for item in summary["board"] if item["id"] == "certicom-eccp-131")

    assert summary["nightly"]["enabled"] is True
    assert summary["queue"]["allowance_usd"] == 8.0
    assert summary["queue"]["minutes"] == 45
    assert summary["queue"]["source"] == "night.json prizes block"
    assert row["research_state"] == "ready-for-review"
    assert row["ready_for_human_review"] is True
    assert row["ready_for_confirmation"] is False


def test_update_schedule_scales_an_enabled_prizes_block_with_the_slots(tmp_path):
    """night.load_schedule charges an enabled prizes block, so the dashboard has to scale it too."""
    schedule = json.loads((REPO / "night.json").read_text(encoding="utf-8"))
    schedule["prizes"]["enabled"] = True
    # The room documented in docs/PRIZE-HUNT.md: cvrp-research at 150 minutes and a $30 slot budget.
    schedule["slots"][0].update(minutes=150, research_minutes=120, retro_minutes=30, slot_budget_usd=30.0)
    _write_json(tmp_path / "night.json", schedule)
    app = dashboard.DashboardApp(tmp_path, csrf_token="test-token")
    caps = {"fable": 40, "astra": 40, "paired": 40}

    app.update_schedule({"duration_minutes": 540, "nightly_budget_usd": 90, "provider_caps_usd": caps})
    money = json.loads((tmp_path / "night.json").read_text(encoding="utf-8"))

    app.update_schedule({"duration_minutes": 400, "nightly_budget_usd": 90, "provider_caps_usd": caps})
    shorter = json.loads((tmp_path / "night.json").read_text(encoding="utf-8"))

    budget_scale = 90 / 105
    assert money["prizes"]["slot_budget_usd"] == pytest.approx(8.0 * budget_scale)
    assert money["prizes"]["retro_budget_usd"] == pytest.approx(2.0 * budget_scale)
    assert money["prizes"]["per_call_budget_usd"] <= money["prizes"]["slot_budget_usd"]
    assert money["prizes"]["minutes"] == 60

    minute_scale = 400 / 540
    assert shorter["prizes"]["minutes"] == pytest.approx(60 * minute_scale)
    assert shorter["prizes"]["research_minutes"] == pytest.approx(45 * minute_scale)
    assert shorter["prizes"]["retro_minutes"] == pytest.approx(15 * minute_scale)
    assert shorter["slots"][0]["minutes"] == pytest.approx(150 * minute_scale)
    assert shorter["prizes"]["enabled"] is True
    # Both saved files are schedules the night runner accepts with the block still enabled.
    for saved in (money, shorter):
        _write_json(tmp_path / "check.json", saved)
        assert night.load_schedule(tmp_path / "check.json")["prizes"]["enabled"] is True


def test_app_prize_payload_is_sanitized_and_survives_a_missing_registry(tmp_path):
    app = dashboard.DashboardApp(tmp_path, csrf_token="test-token")

    summary = app.prize()

    assert summary["generated_at"].endswith("Z")
    assert summary["board"] == []
    assert summary["notices"]


def test_prize_routes_serve_the_board_the_page_and_the_renderers(dashboard_server):
    _root, base, _port = dashboard_server

    status, payload = _request(base, "/api/prizes", origin=False, csrf=None)
    assert status == 200
    assert len(payload["board"]) == 17
    assert all(isinstance(row["score"]["priority_score"], float) for row in payload["board"])

    alias_status, alias_payload = _request(base, "/api/prize", origin=False, csrf=None)
    assert alias_status == 200
    assert len(alias_payload["board"]) == 17

    with urllib.request.urlopen(base + "/prize", timeout=10) as response:
        page = response.read().decode("utf-8")
    assert response.status == 200
    for title in ("Money board", "Prize board", "Research queue", "Economics &amp; dead ends", "Intake"):
        assert title in page
    assert 'id="main"' in page and 'class="skip"' in page and 'aria-live="polite"' in page
    # The lede counts the registry from the payload instead of hardcoding it, and stays CSP-clean.
    assert 'id="lede-count"' in page and "Seventeen" not in page and "<script>" not in page
    for column in ("Est. solve cost", "Best candidate", "Scaling estimate", "Next experiment"):
        assert f"<th>{column}</th>" in page

    with urllib.request.urlopen(base + "/prize.js", timeout=10) as response:
        script = response.read().decode("utf-8")
    for renderer in ("renderMoneyBoard", "renderBoard", "renderQueue", "renderStops", "renderIntake", "renderFootnote"):
        assert renderer in script
    assert 'byId("lede-count").textContent' in script


def test_prize_page_footnote_carries_the_plugins_verbatim_non_claim_sentences(dashboard_server):
    from problem_loader import load_problem

    _root, base, _port = dashboard_server
    status, payload = _request(base, "/api/prizes", origin=False, csrf=None)
    sentences = {row["plugin"]: row["sentence"] for row in payload["non_claims"]}

    assert status == 200
    assert sentences["hash_collision_prize"] == load_problem("hash_collision_prize").NON_CLAIM
    assert sentences["ecc_prize"] == load_problem("ecc_prize").SUBMIT_NOTE
    assert "not partial progress toward a full collision" in sentences["hash_collision_prize"]
    assert "Nothing is submitted." in sentences["ecc_prize"]


def test_prize_posts_require_origin_and_csrf_and_write_nothing_without_them(dashboard_server):
    root, base, _port = dashboard_server
    payload = {"action": "disable", "prize_id": "todd-sha256-collision"}

    no_origin = _request(base, "/api/prizes/control", method="POST", payload=payload, origin=False)
    bad_csrf = _request(base, "/api/prizes/control", method="POST", payload=payload, csrf="wrong")

    assert no_origin[0] == 403 and no_origin[1]["error"] == "same_origin_required"
    assert bad_csrf[0] == 403 and bad_csrf[1]["error"] == "csrf_failed"
    assert not (root / "runs" / "prizes" / "control.json").exists()


def test_prize_control_disable_and_choose_next_round_trip_through_the_refreshed_payload(dashboard_server):
    root, base, _port = dashboard_server

    status, payload = _request(
        base, "/api/prizes/control", method="POST", payload={"action": "disable", "prize_id": "certicom-eccp-131"}
    )
    board = {row["id"]: row for row in payload["prize"]["board"]}
    assert status == 200
    assert board["certicom-eccp-131"]["enabled"] is False

    status, payload = _request(
        base,
        "/api/prizes/control",
        method="POST",
        payload={"action": "choose_next", "prize_id": "todd-sha256-collision"},
    )
    board = {row["id"]: row for row in payload["prize"]["board"]}
    assert status == 200
    assert board["todd-sha256-collision"]["chosen_next"] is True

    control = json.loads((root / "runs" / "prizes" / "control.json").read_text(encoding="utf-8"))
    assert control["next_id"] == "todd-sha256-collision"
    assert "certicom-eccp-131" not in control["enabled_ids"]

    rejected = _request(
        base, "/api/prizes/control", method="POST", payload={"action": "enable", "prize_id": "hutter-prize"}
    )
    assert rejected[0] == 400 and rejected[1]["error"] == "invalid_payload"

    extra = _request(
        base,
        "/api/prizes/control",
        method="POST",
        payload={"action": "clear_next", "prize_id": "todd-sha256-collision"},
    )
    assert extra[0] == 400 and extra[1]["error"] == "invalid_payload"


def test_prize_status_post_appends_evidence_and_history_without_losing_the_old_rows(dashboard_server):
    root, base, _port = dashboard_server
    before = json.loads((root / "data" / "prizes.json").read_text(encoding="utf-8"))
    original = next(item for item in before["prizes"] if item["id"] == "hutter-prize")
    # Caches runs/prizes/registry.json first, so the status write has a stale snapshot to beat.
    _request(base, "/api/prizes/control", method="POST", payload={"action": "disable", "prize_id": "cvrplib-x-open"})

    status, payload = _request(
        base,
        "/api/prizes/status",
        method="POST",
        payload={
            "prize_id": "hutter-prize",
            "status": "verified_active",
            "status_confidence": "high",
            "observed": "The rules page still lists the 500,000 EUR fund and the 5,000 EUR minimum claim.",
            "url": "http://prize.hutter1.net/",
        },
    )
    after = json.loads((root / "data" / "prizes.json").read_text(encoding="utf-8"))
    updated = next(item for item in after["prizes"] if item["id"] == "hutter-prize")

    assert status == 200
    assert updated["status"] == "verified_active"
    assert len(updated["evidence"]) == len(original["evidence"]) + 1
    assert len(updated["history"]) > len(original["history"])
    assert updated["evidence"][: len(original["evidence"])] == original["evidence"]
    assert any(row["by"] == "dashboard" for row in updated["history"])
    board = {row["id"]: row for row in payload["prize"]["board"]}
    assert board["hutter-prize"]["status"] == "verified_active"


def test_prize_dead_end_post_appends_one_record_and_rejects_a_malformed_body(dashboard_server):
    root, base, _port = dashboard_server

    status, payload = _request(
        base,
        "/api/prizes/dead-end",
        method="POST",
        payload={
            "approach": "wider distinguished points: raise the DP rate to 2^-20",
            "why_failed": "This research branch consumed $3 across 3 attempts with no scaling improvement.",
            "evidence": "runs/research/2026-09-21/hash_collision_prize/evidence.json",
            "tags": ["hash_collision_prize", "distinguished-points"],
            "problem": "hash_collision_prize",
        },
    )
    entries = json.loads((root / "problems" / "_dead_ends.json").read_text(encoding="utf-8"))

    assert status == 200
    assert len(entries) == 1
    assert entries[0]["id"] == "de-001"
    assert entries[0]["recorded_by"] == "dashboard"
    assert isinstance(payload["prize"]["board"], list)

    bad = _request(
        base,
        "/api/prizes/dead-end",
        method="POST",
        payload={
            "approach": "no tags",
            "why_failed": "nothing",
            "evidence": "",
            "tags": "distinguished-points",
            "problem": "hash_collision_prize",
        },
    )
    assert bad[0] == 400 and bad[1]["error"] == "invalid_payload"
    assert len(json.loads((root / "problems" / "_dead_ends.json").read_text(encoding="utf-8"))) == 1


def test_prize_intake_post_approves_a_candidate_and_rejects_an_unknown_slug(dashboard_server):
    import prize_intake

    root, base, _port = dashboard_server
    extracted = prize_intake.extract(
        "<html><head><title>Example research challenge</title></head>"
        "<body><p>A US$1,000 award for a measured improvement.</p></body></html>",
        "https://example.org/challenge",
    )
    entry = prize_intake.propose(extracted, "challenge", "Example research challenge")
    _write_json(
        root / "data" / "prizes" / "intake" / f"{entry['id']}.json",
        {
            "schema_version": 1,
            "status": "candidate",
            "url": "https://example.org/challenge",
            "kind": "challenge",
            "fetched_at": "2026-09-20T00:00:00Z",
            "http_status": 200,
            "title": "Example research challenge",
            "excerpt": "A US$1,000 award for a measured improvement.",
            "amounts": ["US$1,000"],
            "deadline_hints": [],
            "category_guess": "other",
            "proposed_entry": entry,
            "content_classification": "untrusted_quoted_source",
        },
    )

    status, payload = _request(
        base, "/api/prizes/intake", method="POST", payload={"action": "approve", "slug": entry["id"]}
    )
    registry = json.loads((root / "data" / "prizes.json").read_text(encoding="utf-8"))

    assert status == 200
    assert any(item["id"] == entry["id"] for item in registry["prizes"])
    assert len(payload["prize"]["board"]) == 18

    missing = _request(
        base, "/api/prizes/intake", method="POST", payload={"action": "reject", "slug": "not-here", "reason": "no"}
    )
    assert missing[0] == 400 and missing[1]["error"] == "invalid_payload"
