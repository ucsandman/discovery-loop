import json
import shutil
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

import prize_intake
import prize_registry


NOW = datetime(2026, 9, 20, 7, 30, tzinfo=timezone.utc)
REPO = Path(prize_registry.ROOT)

PAGE = """
<html><head><title>Example Collision Bounty</title></head>
<body>
<!-- hidden comment with $9,999,999 -->
<script>var quoted = "US$1";</script>
<style>.prize { color: $2; }</style>
<h1>Bounty</h1>
<p>The bounty pays US$20,000 plus 0.27734251 BTC and &euro;5,000 for a SHA-256 collision.</p>
<p>Submission deadline 2027-01-31 for all entries.</p>
</body></html>
"""


def _fetcher(html=PAGE, *, status=200, url="https://example.org/bounty"):
    def fetch(requested):
        assert requested == url
        return {"url": url, "http_status": status, "html": html}

    return fetch


def _registry(tmp_path):
    """The real data/prizes.json in a throwaway root, so approve() faces the real validator."""
    path = tmp_path / "data" / "prizes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "data" / "prizes.json", path)
    return path


def _added(tmp_path, **kwargs):
    return prize_intake.add(
        "https://example.org/bounty",
        kind=kwargs.pop("kind", "bounty"),
        root=tmp_path,
        fetcher=kwargs.pop("fetcher", _fetcher()),
        now=NOW,
        **kwargs,
    )


def test_extract_quotes_title_amounts_and_deadline_without_script_text():
    extracted = prize_intake.extract(PAGE, "https://example.org/bounty")
    assert extracted["title"] == "Example Collision Bounty"
    assert extracted["amounts"] == ["US$20,000", "0.27734251 BTC", "€5,000"]
    assert extracted["category_guess"] == "hash-collision"
    assert any("2027-01-31" in hint for hint in extracted["deadline_hints"])
    assert "quoted" not in extracted["excerpt"]
    assert "color" not in extracted["excerpt"]
    assert "9,999,999" not in json.dumps(extracted)


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Projects/discovery-loop/README.md",
        "javascript:alert(1)",
        "ftp://example.org/x",
        "https://user:secret@example.org/x",
        "not a url",
        123,
    ],
)
def test_unsafe_urls_are_rejected(url):
    with pytest.raises(prize_intake.IntakeError):
        prize_intake.validate_url(url)


def test_add_rejects_an_unsafe_url_before_fetching(tmp_path):
    def fetch(_url):  # pragma: no cover - must never run
        raise AssertionError("add fetched an unsafe url")

    with pytest.raises(prize_intake.IntakeError):
        prize_intake.add("file:///etc/passwd", root=tmp_path, fetcher=fetch, now=NOW)
    assert not prize_intake.intake_dir(tmp_path).exists()


def test_add_writes_a_candidate_file_that_admits_nothing(tmp_path):
    result = _added(tmp_path)
    assert result["slug"] == "example-collision-bounty"
    assert result["path"] == "data/prizes/intake/example-collision-bounty.json"
    written = json.loads((tmp_path / result["path"]).read_text(encoding="utf-8"))
    assert written["status"] == "candidate"
    assert written["content_classification"] == "untrusted_quoted_source"
    assert written["kind"] == "bounty"
    assert written["http_status"] == 200
    assert written["fetched_at"] == "2026-09-20T07:30:00Z"
    assert "C:" not in json.dumps(written) and str(tmp_path) not in json.dumps(written)
    assert prize_intake.list_candidates(tmp_path) == [
        {
            "slug": "example-collision-bounty",
            "status": "candidate",
            "url": "https://example.org/bounty",
            "title": "Example Collision Bounty",
            "kind": "bounty",
            "fetched_at": "2026-09-20T07:30:00Z",
            "path": "data/prizes/intake/example-collision-bounty.json",
        }
    ]


def test_propose_marks_every_field_uncertain():
    entry = prize_intake.propose(prize_intake.extract(PAGE, "https://example.org/bounty"), "bounty", now=NOW)
    assert entry["status"] == "status_uncertain"
    assert entry["status_confidence"] == "low"
    assert entry["plugin"] is None
    assert entry["research_priority"] == "watch"
    assert entry["estimated_usd"] is None
    assert entry["last_verified"] is None
    assert entry["currency"] == "USD"
    assert entry["advertised_prize"] == "US$20,000"
    assert entry["evidence"] == [
        {
            "date": "2026-09-20",
            "url": "https://example.org/bounty",
            "observed": (
                "intake fetch of https://example.org/bounty; page title Example Collision Bounty; "
                "amounts quoted: US$20,000, 0.27734251 BTC, €5,000"
            ),
            "file": None,
        }
    ]
    assert entry["history"] == []


def test_propose_rejects_an_unknown_kind():
    with pytest.raises(prize_intake.IntakeError):
        prize_intake.propose(prize_intake.extract(PAGE, "https://example.org/bounty"), "wishlist")


def test_approve_moves_the_entry_into_the_registry_and_marks_the_intake(tmp_path):
    registry_path = _registry(tmp_path)
    before = len(json.loads(registry_path.read_text(encoding="utf-8"))["prizes"])
    _added(tmp_path)

    result = prize_intake.approve("example-collision-bounty", root=tmp_path, priority="queued", now=NOW)

    assert result == {
        "slug": "example-collision-bounty",
        "prize_id": "example-collision-bounty",
        "registry": "data/prizes.json",
        "prizes": before + 1,
    }
    document = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = document["prizes"][-1]
    # The merged document passed the real validator, not just this one entry.
    assert len(prize_registry.load_registry(registry_path)["prizes"]) == before + 1
    assert entry["id"] == "example-collision-bounty"
    assert entry["research_priority"] == "queued"
    assert entry["history"] == [
        {
            "date": "2026-09-20",
            "field": "research_priority",
            "from": None,
            "to": "queued",
            "by": "operator",
            "note": "approved from intake candidate example-collision-bounty",
        }
    ]
    assert not list(registry_path.parent.glob(".prizes-candidate*"))
    intake = prize_intake.load_intake("example-collision-bounty", tmp_path)
    assert intake["status"] == "approved"
    assert intake["approved_by"] == "operator"
    with pytest.raises(prize_intake.IntakeError):
        prize_intake.approve("example-collision-bounty", root=tmp_path, now=NOW)


def test_approve_refuses_an_entry_the_registry_rejects(tmp_path):
    registry_path = _registry(tmp_path)
    untouched = registry_path.read_bytes()
    _added(tmp_path)
    path = prize_intake.intake_path("example-collision-bounty", tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    # "probably_paid" is not one of prize_registry.STATUSES, so the real validator refuses the
    # merged document and nothing is written.
    record["proposed_entry"]["status"] = "probably_paid"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(prize_intake.IntakeError, match="fails registry validation"):
        prize_intake.approve("example-collision-bounty", root=tmp_path, now=NOW)

    assert registry_path.read_bytes() == untouched
    assert not list((tmp_path / "data").glob(".prizes-candidate*"))
    assert prize_intake.load_intake("example-collision-bounty", tmp_path)["status"] == "candidate"


def test_approve_refuses_a_duplicate_prize_id(tmp_path):
    registry_path = _registry(tmp_path)
    untouched = registry_path.read_bytes()
    _added(tmp_path)
    path = prize_intake.intake_path("example-collision-bounty", tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["proposed_entry"]["id"] = "hutter-prize"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(prize_intake.IntakeError, match="already in the registry"):
        prize_intake.approve("example-collision-bounty", root=tmp_path, now=NOW)
    assert registry_path.read_bytes() == untouched


def test_approve_and_reject_need_an_existing_candidate(tmp_path):
    with pytest.raises(prize_intake.IntakeError):
        prize_intake.load_intake("missing-slug", tmp_path)
    with pytest.raises(prize_intake.IntakeError):
        prize_intake.intake_path("../escape", tmp_path)


def test_reject_records_the_reason_and_needs_one(tmp_path):
    _added(tmp_path)
    result = prize_intake.reject("example-collision-bounty", reason="anonymous sponsor", root=tmp_path, now=NOW)
    assert result["status"] == "rejected"
    record = prize_intake.load_intake("example-collision-bounty", tmp_path)
    assert record["reject_reason"] == "anonymous sponsor"
    assert record["rejected_at"] == "2026-09-20T07:30:00Z"
    with pytest.raises(prize_intake.IntakeError):
        prize_intake.reject("example-collision-bounty", reason="already rejected", root=tmp_path, now=NOW)


def test_fetch_sends_the_user_agent_and_enforces_the_byte_cap(monkeypatch):
    captured = {}

    class _Response:
        def __init__(self, payload):
            self.payload = payload
            self.status = 200
            self.headers = types.SimpleNamespace(get_content_charset=lambda: "utf-8")

        def read(self, size):
            return self.payload[:size]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return _Response(captured["payload"])

    monkeypatch.setattr(prize_intake.urllib.request, "urlopen", fake_urlopen)

    captured["payload"] = b"<title>Small</title>"
    fetched = prize_intake.fetch("https://example.org/bounty")
    assert fetched["http_status"] == 200
    assert fetched["html"] == "<title>Small</title>"
    assert captured["agent"] == prize_intake.USER_AGENT
    assert captured["timeout"] == prize_intake.FETCH_TIMEOUT_SECONDS

    captured["payload"] = b"x" * (prize_intake.MAX_FETCH_BYTES + 1)
    with pytest.raises(prize_intake.IntakeError, match="byte cap"):
        prize_intake.fetch("https://example.org/bounty")


def test_cli_add_prints_the_path_and_the_non_admission_notice(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(prize_intake, "ROOT", tmp_path)
    monkeypatch.setattr(prize_intake, "fetch", lambda url, **_kwargs: _fetcher()(url))
    assert prize_intake.main(["add", "https://example.org/bounty", "--kind", "bounty"]) == 0
    output = capsys.readouterr().out
    assert "data/prizes/intake/example-collision-bounty.json" in output
    assert "not admitted: run approve to add it to data/prizes.json" in output
    assert (tmp_path / "data" / "prizes" / "intake" / "example-collision-bounty.json").exists()


def test_cli_reports_an_intake_error_without_a_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(prize_intake, "ROOT", tmp_path)
    assert prize_intake.main(["reject", "missing-slug", "--reason", "no"]) == 1
    assert "intake error" in capsys.readouterr().out
