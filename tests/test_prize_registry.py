import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

import prize_registry


REPO = Path(prize_registry.ROOT)
DATA = REPO / "data" / "prizes.json"
EXPECTED_IDS = {
    "certicom-eccp-131",
    "certicom-ecc2k-130",
    "certicom-ecc2-131",
    "certicom-level-ii",
    "todd-sha1-collision",
    "todd-sha256-collision",
    "todd-ripemd160-collision",
    "todd-hash160-collision",
    "todd-hash256-collision",
    "hutter-prize",
    "packomania-csqv-records",
    "matmul-rank-records",
    "cvrplib-x-open",
    "miplib-open-instances",
    "pglib-opf-benchmarks",
    "rsa-factoring-challenge",
    "bitcoin-puzzle-transaction",
}


def _root(tmp_path, *plugins):
    """A throwaway repository root: the real registry plus only the plugins a test asks for."""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    shutil.copy2(DATA, root / "data" / "prizes.json")
    for name in plugins:
        directory = root / "problems" / name
        directory.mkdir(parents=True)
        for filename in ("problem.py", "verify.py"):
            (directory / filename).write_text("", encoding="utf-8", newline="\n")
    return root


def _raw(root=None):
    path = (Path(root) / "data" / "prizes.json") if root else DATA
    return json.loads(path.read_text(encoding="utf-8"))


def _prize(**overrides):
    entry = copy.deepcopy(_raw()["prizes"][0])
    entry.update(overrides)
    return entry


def _at(day):
    return datetime(2026, 9, day, 3, tzinfo=timezone.utc)


def test_committed_registry_validates_and_every_recorded_amount_has_evidence():
    document = prize_registry.load_registry(DATA)
    prizes = {prize["id"]: prize for prize in document["prizes"]}

    assert set(prizes) == EXPECTED_IDS
    assert len(prizes) == 17
    for prize in prizes.values():
        assert prize["content_classification"] == "untrusted_quoted_source"
        assert prize["claim_status"]["independently_checked_by_discovery_loop"] is False
        for row in prize["evidence"]:
            if row["file"]:
                assert (REPO / row["file"]).is_file(), row["file"]
        # A nonzero prize value is never asserted without a dated observation behind it.
        if prize["estimated_usd"]:
            assert prize["evidence"], prize["id"]
        # A "verified active" status is only claimed where something was observed on chain.
        if prize["status"] == "verified_active":
            assert prize["last_verified"] == "2026-09-20"
            assert prize["claim_status"]["verified_on_chain"] is True

    assert prizes["todd-sha256-collision"]["estimated_usd"] == 22272.0
    assert prizes["todd-sha256-collision"]["advertised_prize"] == "0.27734251 BTC (address balance)"
    assert prizes["todd-ripemd160-collision"]["estimated_usd"] == 9297.0
    assert prizes["todd-hash160-collision"]["estimated_usd"] == 8052.0
    assert prizes["todd-hash256-collision"]["estimated_usd"] == 8052.0
    assert prizes["todd-sha1-collision"]["status"] == "solved"
    assert prizes["certicom-eccp-131"]["estimated_usd"] == 20000.0
    assert prizes["certicom-eccp-131"]["status"] == "status_uncertain"
    assert prizes["certicom-eccp-131"]["status_confidence"] == "medium"
    assert prizes["rsa-factoring-challenge"]["status"] == "closed"
    # Unpriced entries say so instead of carrying an invented number.
    for prize_id in ("hutter-prize", "certicom-level-ii", "packomania-csqv-records", "cvrplib-x-open"):
        assert prizes[prize_id]["estimated_usd"] is None
        assert prizes[prize_id]["estimated_usd_basis"]
    assert prizes["hutter-prize"]["status"] == "probably_active"

    puzzle = prizes["bitcoin-puzzle-transaction"]
    assert puzzle["research_priority"] == "excluded"
    assert puzzle["plugin"] is None
    serialized = json.dumps(puzzle)
    for address in ("35Snmmy3uhaer2gTboc81ayCip4m9DT4ko", "3KyiQEGqqdb4nqfhUzGKN6KPhXmQsLNpay"):
        assert address not in serialized


def test_verified_on_chain_needs_a_block_explorer_evidence_row():
    """The claim is derived from evidence, not from the status word alone."""
    row = {"date": "2026-09-20", "url": "https://example.org/rules", "observed": "page still lists it", "file": None}

    off_chain = prize_registry.validate_prize(
        _prize(status="verified_active", status_confidence="high", evidence=[row])
    )
    on_chain = prize_registry.validate_prize(
        _prize(
            status="verified_active",
            status_confidence="high",
            evidence=[row, {**row, "url": "https://mempool.space/api/address/35Snmmy3uhaer2gTboc81ayCip4m9DT4ko"}],
        )
    )
    blockstream = prize_registry.validate_prize(
        _prize(
            status="verified_active",
            status_confidence="high",
            evidence=[{**row, "url": "https://blockstream.info/api/address/35Snmmy3uhaer2gTboc81ayCip4m9DT4ko"}],
        )
    )
    # A chain row under any other status still claims nothing.
    quiet = prize_registry.validate_prize(
        _prize(
            status="status_uncertain",
            status_confidence="low",
            evidence=[{**row, "url": "https://mempool.space/api/address/35Snmmy3uhaer2gTboc81ayCip4m9DT4ko"}],
        )
    )

    assert off_chain["claim_status"]["verified_on_chain"] is False
    assert on_chain["claim_status"]["verified_on_chain"] is True
    assert blockstream["claim_status"]["verified_on_chain"] is True
    assert quiet["claim_status"]["verified_on_chain"] is False


def test_snapshot_is_hash_stable_and_admission_follows_the_local_plugins(tmp_path):
    root = _root(tmp_path, "hash_collision_prize")
    first = prize_registry.snapshot(root, now=_at(20))
    second = prize_registry.snapshot(root, now=_at(21))

    assert first["registry_hash"] == second["registry_hash"]
    assert first["source"]["imported_at"] != second["source"]["imported_at"]
    assert first["source"]["path"] == "data/prizes.json"
    assert first["source"]["prize_count"] == 17

    by_id = {prize["id"]: prize for prize in first["prizes"]}
    assert prize_registry.ready_ids(first) == [
        "todd-hash160-collision",
        "todd-hash256-collision",
        "todd-ripemd160-collision",
        "todd-sha256-collision",
    ]
    assert by_id["todd-sha256-collision"]["binding"]["plugin"] == "hash_collision_prize"
    assert by_id["todd-sha256-collision"]["binding"]["max_slot_budget_usd"] == 12.0
    # Bound but not installed, bound but not a cash prize, and never bound at all.
    assert by_id["certicom-eccp-131"]["admission"] == "needs_setup"
    assert "not installed locally" in by_id["certicom-eccp-131"]["admission_reason"]
    # An active no-cash benchmark stays runnable (its value is credibility); here it is merely not installed.
    assert by_id["matmul-rank-records"]["admission"] == "needs_setup"
    assert "not installed locally" in by_id["matmul-rank-records"]["admission_reason"]
    assert by_id["certicom-level-ii"]["admission_reason"].startswith("No reviewed binding")
    for prize in first["prizes"]:
        assert (prize["binding"] is None) == (prize["admission"] == "needs_setup")


def test_failed_refresh_keeps_a_snapshot_and_a_tampered_binding_drops_it(tmp_path):
    root = _root(tmp_path, "hash_collision_prize")
    fresh = prize_registry.refresh_registry(root, now=_at(20))
    expected = fresh["snapshot"]["registry_hash"]
    assert fresh["refresh"]["status"] == "fresh"
    assert fresh["refresh"]["prize_count"] == 17
    assert fresh["refresh"]["ready_count"] == 4

    (root / "data" / "prizes.json").write_text("{", encoding="utf-8", newline="\n")
    stale = prize_registry.refresh_registry(root, now=_at(21))
    assert stale["refresh"]["status"] == "stale"
    assert stale["snapshot"]["registry_hash"] == expected

    cached = json.loads((root / "runs" / "prizes" / "registry.json").read_text(encoding="utf-8"))
    for prize in cached["prizes"]:
        if prize["id"] == "certicom-eccp-131":
            prize["admission"] = "ready"
            prize["binding"] = dict(prize_registry.PRIZE_BINDINGS["certicom-eccp-131"])
    (root / "runs" / "prizes" / "registry.json").write_text(json.dumps(cached), encoding="utf-8", newline="\n")
    unavailable = prize_registry.refresh_registry(root, now=_at(22))
    assert unavailable["refresh"]["status"] == "unavailable"
    assert unavailable["snapshot"] is None
    assert prize_registry.load_snapshot(root) is None


@pytest.mark.parametrize(
    "change, message",
    [
        ({"id": "../escape"}, "lowercase hyphenated slug"),
        ({"source_url": "file:///private/data"}, "HTTP or HTTPS URL"),
        ({"status": "probably_paid"}, "status is unsupported"),
        ({"estimated_usd": -5}, "finite nonnegative"),
        ({"estimated_usd": "twenty thousand dollars"}, "number or null"),
        ({"last_verified": "September 2026"}, "YYYY-MM-DD"),
        ({"research_priority": "urgent"}, "research_priority is unsupported"),
        ({"plugin": "../../etc"}, "plugin directory name"),
        ({"parallelizable": "yes"}, "must be true or false"),
        (
            {"evidence": [{"date": "2026-09-20", "url": "https://e.org", "observed": "x", "file": "../secrets.json"}]},
            "repository-relative POSIX path",
        ),
        (
            {"evidence": [{"date": "2026-09-20", "url": "https://e.org", "observed": "x", "file": "data/keys.json"}]},
            "under data/prizes/evidence/",
        ),
        (
            {"history": [{"date": "2026-09-20", "field": "status", "from": None, "to": {"x": 1}, "by": "op"}]},
            "must be text, a number, a boolean or null",
        ),
        ({"compute_cost_estimate": {"category": "free", "note": "x"}}, "category is unsupported"),
    ],
)
def test_malformed_or_unsafe_prizes_are_rejected(change, message):
    with pytest.raises(prize_registry.RegistryError, match=message):
        prize_registry.validate_prize(_prize(**change))


def test_a_duplicate_id_or_a_bad_schema_version_is_rejected():
    document = _raw()
    document["prizes"].append(copy.deepcopy(document["prizes"][0]))
    with pytest.raises(prize_registry.RegistryError, match="duplicate prize id"):
        prize_registry.validate_registry(document)
    with pytest.raises(prize_registry.RegistryError, match="schema version"):
        prize_registry.validate_registry({"schema_version": 2, "updated_at": "2026-09-20", "prizes": []})


def test_only_admitted_prizes_can_be_enabled_or_chosen(tmp_path):
    root = _root(tmp_path, "hash_collision_prize")
    prize_registry.refresh_registry(root, now=_at(20))

    control = prize_registry.load_control(root, prize_registry.load_snapshot(root))
    assert control["enabled_ids"] == prize_registry.ready_ids(prize_registry.load_snapshot(root))
    assert control["next_id"] is None

    for keyword in ({"enable": "certicom-eccp-131"}, {"next_id": "hutter-prize"}):
        with pytest.raises(prize_registry.RegistryError, match="not admitted"):
            prize_registry.update_control(root, now=_at(20), **keyword)

    disabled = prize_registry.update_control(root, disable="todd-hash160-collision", now=_at(20))
    assert "todd-hash160-collision" not in disabled["enabled_ids"]
    chosen = prize_registry.update_control(root, next_id="todd-sha256-collision", now=_at(20))
    assert chosen["next_id"] == "todd-sha256-collision"

    same = prize_registry.consume_next(root, "todd-ripemd160-collision", "run-1", now=_at(20))
    assert same["next_id"] == "todd-sha256-collision"
    used = prize_registry.consume_next(root, "todd-sha256-collision", "run-1", now=_at(20))
    assert used["next_id"] is None
    assert used["last_choice"] == {
        "prize_id": "todd-sha256-collision",
        "run_id": "run-1",
        "consumed_at": prize_registry._utc_now(_at(20)),
    }

    view = prize_registry.registry_view(root)
    flags = {prize["id"]: (prize["enabled"], prize["chosen_next"]) for prize in view["prizes"]}
    assert flags["todd-sha256-collision"] == (True, False)
    assert flags["todd-hash160-collision"] == (False, False)
    assert flags["certicom-eccp-131"] == (False, False)
    assert view["registry_hash"] == prize_registry.load_snapshot(root)["registry_hash"]
    assert view["refresh"]["status"] == "fresh"


def test_registry_view_is_empty_but_shaped_when_no_snapshot_exists(tmp_path):
    root = _root(tmp_path)
    view = prize_registry.registry_view(root)
    assert view == {
        "source": None,
        "registry_hash": None,
        "prizes": [],
        "control": {"schema_version": 1, "enabled_ids": [], "next_id": None, "updated_at": None},
        "refresh": {"status": "unavailable", "prize_count": 0, "ready_count": 0},
    }


def test_update_status_appends_evidence_and_history_and_never_drops_a_row(tmp_path):
    root = _root(tmp_path)
    path = root / "data" / "prizes.json"
    before = {prize["id"]: prize for prize in _raw(root)["prizes"]}["hutter-prize"]

    updated = prize_registry.update_status(
        path,
        "hutter-prize",
        status="verified_active",
        status_confidence="high",
        last_verified="2026-09-21",
        observed="Rules page re-read: the 1 percent minimum claim and the 500,000 EUR fund are unchanged.",
        url="http://prize.hutter1.net/",
        by="tester",
        note="quarterly re-check",
    )

    assert updated["status"] == "verified_active"
    assert updated["status_confidence"] == "high"
    assert updated["last_verified"] == "2026-09-21"
    assert updated["evidence"][: len(before["evidence"])] == before["evidence"]
    assert len(updated["evidence"]) == len(before["evidence"]) + 1
    assert updated["evidence"][-1]["observed"].startswith("Rules page re-read")
    changed = [row["field"] for row in updated["history"][len(before["history"]) :]]
    assert changed == ["status", "status_confidence", "last_verified"]
    assert updated["history"][-1]["by"] == "tester"
    assert updated["history"][-1]["note"] == "quarterly re-check"
    assert updated["history"][len(before["history"])]["from"] == "probably_active"

    document = prize_registry.load_registry(path)
    assert document["updated_at"] == "2026-09-21"
    assert len(document["prizes"]) == 17

    # A second write with no field change still records the observation.
    again = prize_registry.update_status(
        path,
        "hutter-prize",
        status="verified_active",
        last_verified="2026-09-21",
        observed="Checked again; nothing changed.",
        url="http://prize.hutter1.net/",
    )
    assert len(again["evidence"]) == len(updated["evidence"]) + 1
    assert len(again["history"]) == len(updated["history"])

    with pytest.raises(prize_registry.RegistryError, match="unknown prize id"):
        prize_registry.update_status(path, "no-such-prize", status="closed", observed="x", url="https://example.org/x")


def test_check_sources_reports_status_offline_and_never_edits_the_registry(tmp_path):
    root = _root(tmp_path)
    path = root / "data" / "prizes.json"
    before = path.read_bytes()
    seen = []

    def opener(url, timeout):
        seen.append((url, timeout))
        return (200, "the page still mentions ECCp-131 somewhere") if "certicom" in url else (404, "")

    report = prize_registry.check_sources(root, opener=opener, timeout=3.0, now=_at(20))
    rows = {row["id"]: row for row in report["results"]}

    assert len(report["results"]) == 17
    assert len(seen) == 17 and {timeout for _, timeout in seen} == {3.0}
    assert rows["certicom-eccp-131"]["http_status"] == 200
    assert rows["certicom-eccp-131"]["keyword"] == "ECCp-131"
    assert rows["certicom-eccp-131"]["keyword_present"] is True
    assert rows["hutter-prize"]["keyword"] == "enwik9"
    assert rows["todd-sha256-collision"]["keyword"] == "SHA-256"
    assert rows["hutter-prize"]["http_status"] == 404
    assert rows["hutter-prize"]["keyword_present"] is False
    assert path.read_bytes() == before
    assert json.loads((root / "runs" / "prizes" / "source-check.json").read_text(encoding="utf-8")) == report


def test_every_binding_names_a_reviewed_plugin_baseline_and_verifier():
    for prize_id, binding in prize_registry.PRIZE_BINDINGS.items():
        assert prize_registry.ID_RE.fullmatch(prize_id), prize_id
        assert set(binding) == {
            "plugin",
            "baseline",
            "verifier",
            "development",
            "holdout",
            "success_criterion",
            "max_minutes",
            "max_slot_budget_usd",
            "max_per_call_budget_usd",
        }
        assert binding["baseline"] == f"problems/{binding['plugin']}/seed_solver.py"
        assert binding["verifier"] == f"problems/{binding['plugin']}/verify.py"
        assert binding["development"] and not set(binding["development"]) & set(binding["holdout"])
        assert 0 < binding["max_per_call_budget_usd"] <= binding["max_slot_budget_usd"]
        assert 0 < binding["max_minutes"] <= 210
    # Every bound id exists in the committed registry.
    known = {prize["id"] for prize in _raw()["prizes"]}
    assert set(prize_registry.PRIZE_BINDINGS) <= known
