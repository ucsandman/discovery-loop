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
