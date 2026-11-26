import importlib.util
import json
from fractions import Fraction

import pytest

import notary
import notary_exact
from scripts import notary_planted


def test_exact_verifier_accepts_touching_circles_and_rejects_overlap():
    touching = [("-0.25", "0", "0.25"), ("0.25", "0", "0.25")]
    result = notary_exact.check_exact(touching, 2)
    assert result["feasible"] and result["min_pair_slack_sq"] == 0 and result["min_wall_slack"] == 0
    assert result["sum"] == Fraction(1, 2)
    overlap = [("-0.25", "0", "0.2500000001"), ("0.25", "0", "0.25")]
    assert not notary_exact.check_exact(overlap, 2)["feasible"]
    assert notary_exact.check_exact(overlap, 2, tolerance=Fraction(1, 10**8))["feasible"]


@pytest.mark.parametrize(
    "bad, error",
    [
        ([("0", "0", "nan")], "finite decimal"),
        ([("0", "0", "inf")], "finite decimal"),
        ([("0", "0", "-0.1")], "non-positive"),
        ([("0", "0")], "x y r"),
    ],
)
def test_exact_verifier_rejects_malformed_rows(bad, error):
    assert error in notary_exact.check_exact(bad)["error"]


def test_exact_verifier_checks_the_count():
    assert "expected 2" in notary_exact.check_exact([("0", "0", "0.1")], 2)["error"]


def test_decimals_follow_the_printed_text():
    assert notary_exact.decimals_of("0.120") == 3
    assert notary_exact.decimals_of("5") == 0
    assert notary_exact.decimals_of("1e-12") == 12
    assert notary_exact.decimals_of("nan") is None


def test_both_artifact_formats_read_the_same_rows():
    pck = "0.25\nauthor\n-0.25 0 0.25\n0.25 0 0.25\n"
    txt = "#\n# coordinates\n#\n    1  -0.25  0  0.25\n    2   0.25  0  0.25\n"
    assert (
        notary.read_rows(pck, "pck")
        == notary.read_rows(txt, "packomania_txt")
        == [("-0.25", "0", "0.25"), ("0.25", "0", "0.25")]
    )


def test_pck_reader_inverts_the_research_writer():
    spec = importlib.util.spec_from_file_location("cp_verify_for_test", notary.PRIMARY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    circles = [[0.25, 0.5, 0.25], [0.75, 0.5, 0.25]]
    rows = notary.read_rows(module.to_pck(circles, "test"), "pck")
    assert [[float(x) + 0.5, float(y) + 0.5, float(r)] for x, y, r in rows] == circles


def test_planted_corpus_is_fully_caught(tmp_path):
    result = notary_planted.run(tmp_path)
    assert result["honest"] == "holds"
    assert result["caught"] == len(result["planted"]) == 10, result["planted"]
    assert result["tampered_caught"] == len(result["tampered"]) == 5, result["tampered"]
    assert result["passed"]


def test_corpus_has_teeth_when_both_verifiers_are_broken(tmp_path):
    result = notary_planted.run(tmp_path, broken="both")
    missed = [name for name, verdict in result["planted"].items() if verdict == "holds"]
    assert {"wall_breach", "pair_overlap", "duplicate_circle"} <= set(missed)
    assert not result["passed"]


@pytest.mark.parametrize("broken", ["primary", "exact"])
def test_one_broken_verifier_is_caught_by_disagreement(tmp_path, broken):
    result = notary_planted.run(tmp_path, broken=broken)
    assert result["passed"]
    assert result["planted"]["wall_breach"] == "insufficient_spec"


def _card(folder, **overrides):
    (folder / "p.pck").write_text(
        "0.25\nauthor\n-0.2500000000 0.0000000000 0.2500000000\n0.2500000000 0.0000000000 0.2500000000\n",
        encoding="utf-8",
    )
    card = {
        "schema": "claim-card-v1",
        "claim_id": "two",
        "problem": "circle_packing",
        "claimant": "test",
        "statement": "two touching circles",
        "artifact": {"path": "p.pck", "format": "pck"},
        "n": 2,
        "claimed_sum": "0.5",
    }
    card.update(overrides)
    path = folder / "card.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    return path


def test_other_problems_are_outside_scope(tmp_path):
    receipt = notary.build_receipt(_card(tmp_path, problem="cvrp"), "2026-11-26")
    assert receipt["verdict"] == "cannot_check"


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"artifact": {"path": "../outside.pck", "format": "pck"}}, "inside the claim card's folder"),
        ({"tolerance": "1"}, "unknown"),
        ({"claimed_sum": 0.5}, "string"),
        ({"claimed_gain_pct": "1.0"}, "needs a reference"),
        ({"source_url": "http://example.com"}, "https://"),
    ],
)
def test_claim_cards_are_strict(tmp_path, overrides, message):
    with pytest.raises(notary.CardError, match=message):
        notary.build_receipt(_card(tmp_path, **overrides), "2026-11-26")


def test_cli_issues_a_receipt_that_re_derives(tmp_path, capsys):
    card = _card(tmp_path)
    assert notary.main(["check", str(card), "--out", str(tmp_path), "--date", "2026-11-26"]) == 0
    receipt_path = tmp_path / "two.receipt.json"
    assert "two: holds" in capsys.readouterr().out
    assert "<strong>Holds</strong>" in (tmp_path / "two.receipt.html").read_text(encoding="utf-8")
    assert notary.main(["verify-receipt", str(receipt_path), str(card)]) == 0
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["claim"]["claimed_sum"] = "0.6"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert notary.main(["verify-receipt", str(receipt_path), str(card)]) == 1


def test_line_endings_do_not_change_hashes(tmp_path):
    (tmp_path / "lf").write_bytes(b"a\nb\n")
    (tmp_path / "crlf").write_bytes(b"a\r\nb\r\n")
    assert notary.text_sha256(tmp_path / "lf") == notary.text_sha256(tmp_path / "crlf")


def test_the_committed_registry_reproduces():
    results = notary.reverify_all()
    assert len(results) >= 15
    assert {status for _, status, _ in results} <= {"reproduced", "reworded"}, results


def test_corner_formats_read_the_same_packing_as_pck():
    pck = notary.read_rows("0.25\nauthor\n-0.25 0 0.25\n0.25 0 0.25\n", "pck")
    as_json = notary.read_rows('{"circles": [[0.25, 0.5, 0.25], [0.75, 0.5, 0.25]]}', "json_corner")
    as_txt = notary.read_rows("# x y r\n[0.25, 0.5, 0.25],\n[0.75, 0.5, 0.25]\n", "txt_corner")
    to_numbers = lambda rows: [tuple(Fraction(v) for v in row) for row in rows]
    assert to_numbers(as_json) == to_numbers(as_txt) == to_numbers(pck)


@pytest.mark.parametrize("claimed, verdict", [("0.50", "holds"), ("0.5000000000", "holds"), ("0.51", "does_not_hold")])
def test_a_rounded_claim_agrees_at_its_printed_precision(tmp_path, claimed, verdict):
    assert notary.build_receipt(_card(tmp_path, claimed_sum=claimed), "2026-11-26")["verdict"] == verdict


def _registry(tmp_path):
    claims, receipts = tmp_path / "claims", tmp_path / "receipts"
    (claims / "two").mkdir(parents=True)
    return _card(claims / "two"), receipts


def test_issue_needs_a_logged_correction_to_change_an_outcome(tmp_path):
    card, receipts = _registry(tmp_path)
    data = json.loads(card.read_text(encoding="utf-8"))
    card.write_text(json.dumps(data), encoding="utf-8")
    assert notary.issue(card, "2026-11-26", receipts)["verdict"] == "holds"
    data["claimed_sum"] = "0.6"
    card.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(notary.CardError, match="outcome would change"):
        notary.issue(card, "2026-11-27", receipts)
    notary.issue(card, "2026-11-27", receipts, correction="claimant corrected the sum")
    log = (receipts / notary.CORRECTIONS).read_text(encoding="utf-8")
    assert "| 2026-11-27 | two | holds | does_not_hold | claimant corrected the sum |" in log


def test_reverify_all_reports_tampering_changes_and_unissued_cards(tmp_path):
    card, receipts = _registry(tmp_path)
    claims = card.parent.parent
    notary.issue(card, "2026-11-26", receipts)
    assert notary.reverify_all(claims, receipts) == [("two", "reproduced", "holds")]
    receipt_path = receipts / "two.receipt.json"
    original = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(original)
    receipt["verdict"] = "does_not_hold"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert notary.reverify_all(claims, receipts)[0][1] == "tampered"
    receipt_path.write_text(original, encoding="utf-8")
    (card.parent / "p.pck").write_text(
        "0.3\nauthor\n-0.2 0.0000000000 0.3000000000\n0.2500000000 0.0000000000 0.2500000000\n", encoding="utf-8"
    )
    assert notary.reverify_all(claims, receipts)[0][1] == "changed"
    (claims / "new").mkdir()
    _card(claims / "new")
    assert ("new", "unissued", "card has no receipt yet") in notary.reverify_all(claims, receipts)


def test_index_prints_the_calibration_line(tmp_path):
    card, receipts = _registry(tmp_path)
    notary.issue(card, "2026-11-26", receipts)
    text = notary.render_index(receipts).read_text(encoding="utf-8")
    assert "**Claims checked: 1.** Holds: 1. Does not hold: 0." in text
    assert "[two](two.md)" in text and (receipts / notary.CORRECTIONS).is_file()


def _packing(folder, text, claimed):
    card = _card(folder, claimed_sum=claimed)
    (folder / "p.pck").write_text(text, encoding="utf-8")
    return notary.build_receipt(card, "2026-11-26")


@pytest.mark.parametrize("claimed, verdict", [("0.4", "holds"), ("0.5", "holds"), ("0.47", "does_not_hold")])
def test_a_coarse_claim_agrees_when_rounded_or_truncated(tmp_path, claimed, verdict):
    # two strictly separated circles summing to 0.48: 0.4 truncates it, 0.5 rounds it, 0.47 does neither
    text = "0.24\nauthor\n-0.2500000000 0.0000000000 0.2400000000\n0.2500000000 0.0000000000 0.2400000000\n"
    receipt = _packing(tmp_path, text, claimed)
    assert receipt["verdict"] == verdict
    if claimed == "0.4":
        assert "truncated" in next(c["detail"] for c in receipt["checks"] if c["name"] == "claimed_sum")


def test_low_precision_matters_only_when_the_packing_needs_the_allowance(tmp_path):
    separated = "0.24\nauthor\n-0.25 0.00 0.24\n0.25 0.00 0.24\n"
    assert _packing(tmp_path, separated, "0.48")["verdict"] == "holds"
    overlapping = "0.27\nauthor\n-0.24 0.00 0.27\n0.25 0.00 0.24\n"  # crosses the edge by 0.01, inside a 0.1 allowance
    receipt = _packing(tmp_path, overlapping, "0.51")
    assert receipt["verdict"] == "insufficient_spec"
    assert [c["name"] for c in receipt["checks"] if c["result"] == "undecided"] == ["precision"]


def test_claims_without_coordinates_cannot_be_decided(tmp_path):
    card = _card(tmp_path, artifact={"published": "none", "note": "Only a screenshot."})
    receipt = notary.build_receipt(card, "2026-11-26")
    assert receipt["verdict"] == "insufficient_spec"
    assert receipt["checks"][-1] == {
        "name": "artifact",
        "result": "undecided",
        "detail": "No coordinates were published with this claim. Only a screenshot.",
    }
    assert "Coordinates published" in notary.render_markdown(receipt)
    assert "<strong>Cannot be decided" in notary.render_html(receipt)


def test_centred_json_with_pieces_reads_like_pck():
    rows = notary.read_rows('{"pieces": [[-0.25, 0, 0.25], [0.25, 0, 0.25]]}', "json_centred")
    assert rows == [("-0.25", "0", "0.25"), ("0.25", "0", "0.25")]
