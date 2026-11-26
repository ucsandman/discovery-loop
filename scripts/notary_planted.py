"""Planted-cheat corpus for the Claim Notary: 10 bad claims, 5 tampered receipts and 1 honest control.

    python scripts/notary_planted.py [--break none|primary|exact|both] [--out DIR]

Every case is built from best/pck/csqv101.pck. The gate passes only when the honest control holds, every planted
claim is caught and every tampered receipt fails to re-derive. --break swaps in verifiers that accept anything, to
show the gate going red when the thing it watches is broken (docs/notary-prereg.md, day 2).
"""

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import notary  # noqa: E402
import notary_exact  # noqa: E402

BASE = ROOT / "best" / "pck" / "csqv101.pck"
LISTED = ROOT / "best" / "submitted.json"
NUDGE = Decimal("2e-12")


def _rows(path):
    return notary.read_rows(path.read_text(encoding="utf-8"), "pck")


def _fmt(value):
    return f"{Decimal(value):.16f}"


def _write(folder, name, rows):
    text = "\n".join([max(rows, key=lambda r: Decimal(r[2]))[2], "planted"] + [" ".join(r) for r in rows]) + "\n"
    path = folder / f"{name}.pck"
    path.write_text(text, encoding="utf-8")
    return path


def _sum_text(rows):
    return (
        notary._exact_decimal(notary_exact.check_exact(rows)["sum"])
        if all(notary_exact.decimals_of(v) is not None for r in rows for v in r)
        else "0"
    )


def _card(folder, name, artifact, claimed_sum, reference=None, gain=None, sha=None):
    card = {
        "schema": notary.CARD_SCHEMA,
        "claim_id": name,
        "problem": "circle_packing",
        "claimant": "planted corpus",
        "statement": f"Planted case {name}: a packing of 101 circles with sum {claimed_sum}",
        "artifact": {"path": artifact.name, "format": "pck"},
        "n": 101,
        "claimed_sum": claimed_sum,
    }
    if sha:
        card["artifact"]["sha256"] = sha
    if reference:
        card["reference"] = reference
    if gain is not None:
        card["claimed_gain_pct"] = gain
    path = folder / f"{name}.card.json"
    path.write_text(json.dumps(card, indent=1), encoding="utf-8")
    return path


def _tightest(rows):
    """Index and side of the circle closest to a wall, and the closest pair, in exact arithmetic."""
    vals = [tuple(Fraction(Decimal(v)) for v in row) for row in rows]
    half = Fraction(1, 2)
    wall = min(((half - abs(x) - r, i, "x") for i, (x, y, r) in enumerate(vals)), key=lambda t: t[0])
    wall_y = min(((half - abs(y) - r, i, "y") for i, (x, y, r) in enumerate(vals)), key=lambda t: t[0])
    pair = min(
        ((xi - xj) ** 2 + (yi - yj) ** 2 - (ri + rj) ** 2, i, j)
        for i, (xi, yi, ri) in enumerate(vals)
        for j, (xj, yj, rj) in enumerate(vals)
        if j > i
    )
    return min(wall, wall_y, key=lambda t: t[0]), pair


def build_corpus(folder):
    rows = _rows(BASE)
    honest_sum = _sum_text(rows)
    listed = json.loads(LISTED.read_text(encoding="utf-8"))["101"]["listed"]
    reference = {"value": repr(listed), "source": "Packomania list value recorded at submission (best/submitted.json)"}
    gain = (Fraction(Decimal(honest_sum)) / Fraction(Decimal(repr(listed))) - 1) * 100
    honest_artifact = _write(folder, "honest", rows)
    cases = {"honest": _card(folder, "honest", honest_artifact, honest_sum, reference, f"{float(gain):.2f}")}
    planted = {}
    (_, wi, side), (_, pi, _) = _tightest(rows)

    def mutate(name, changed, claimed_sum=None, **card):
        artifact = _write(folder, name, changed)
        planted[name] = _card(folder, name, artifact, claimed_sum or honest_sum, **card)

    breach = [list(r) for r in rows]
    k = 0 if side == "x" else 1
    breach[wi][k] = _fmt(Decimal(breach[wi][k]) + (NUDGE if Decimal(breach[wi][k]) >= 0 else -NUDGE))
    mutate("wall_breach", [tuple(r) for r in breach])
    overlap = [list(r) for r in rows]
    overlap[pi][2] = _fmt(Decimal(overlap[pi][2]) + NUDGE)
    mutate("pair_overlap", [tuple(r) for r in overlap])
    mutate("wrong_count", rows[:-1])
    mutate("inflated_sum", rows, claimed_sum=_fmt(Decimal(honest_sum) + Decimal("1e-6")))
    mutate("inflated_gain", rows, reference=reference, gain="5.41")
    mutate(
        "not_beating_reference",
        rows,
        reference={"value": _fmt(Decimal(honest_sum) + Decimal("0.001")), "source": "planted reference"},
    )
    negative = [list(r) for r in rows]
    negative[0][2] = "-" + negative[0][2]
    mutate("negative_radius", [tuple(r) for r in negative])
    duplicate = [tuple(rows[0])] + list(rows[1:])
    duplicate[1] = tuple(rows[0])
    mutate("duplicate_circle", duplicate, claimed_sum=_sum_text(duplicate))
    swapped = [list(r) for r in rows]
    swapped[0][2] = _fmt(Decimal(swapped[0][2]) - Decimal("1e-12"))
    mutate("swapped_artifact", [tuple(r) for r in swapped], sha=notary.text_sha256(honest_artifact))
    coarse = [tuple(f"{Decimal(v):.4f}" for v in r) for r in rows]
    mutate("low_precision", coarse, claimed_sum=_sum_text(coarse))
    return cases["honest"], planted


def _tampered(honest, breach):
    edits = {}
    t = copy.deepcopy(honest)
    t["measured"]["sum"] = _fmt(Decimal(t["measured"]["sum"]) + Decimal("1e-6"))
    edits["tamper_sum"] = t
    t = copy.deepcopy(honest)
    t["artifact"]["sha256"] = "0" * 64
    edits["tamper_artifact_hash"] = t
    t = copy.deepcopy(honest)
    t["verifiers"]["primary"]["sha256"] = "f" * 64
    edits["tamper_verifier_hash"] = t
    t = copy.deepcopy(honest)
    t["rule"]["tolerance"] = "1e-3"
    edits["tamper_tolerance"] = t
    t = copy.deepcopy(breach)  # a forger who also recomputes the receipt's own hash
    t["verdict"] = "holds"
    for check in t["checks"]:
        check["result"] = "pass"
    body = {k: v for k, v in t.items() if k != "receipt_sha256"}
    t["receipt_sha256"] = hashlib.sha256(notary.canonical(body).encode()).hexdigest()
    edits["forged_verdict_rehashed"] = t
    return edits


def permissive_primary(circles, n=None):
    return {
        "feasible": True,
        "n": len(circles),
        "sum": sum(c[2] for c in circles if len(c) == 3),
        "min_wall_slack": 0.0,
        "min_pair_slack_sq": 0.0,
    }


def permissive_exact(rows, n=None, tolerance=Fraction(0)):
    try:
        total = sum(Fraction(Decimal(r[2])) for r in rows)
    except Exception:
        return {"feasible": False, "error": "unparseable"}
    return {
        "feasible": True,
        "n": len(rows),
        "sum": total,
        "min_wall_slack": Fraction(0),
        "min_pair_slack_sq": Fraction(0),
    }


def run(folder, broken="none", issued_on="2026-11-26"):
    primary = permissive_primary if broken in ("primary", "both") else None
    exact = permissive_exact if broken in ("exact", "both") else None
    honest_card, planted = build_corpus(Path(folder))
    honest = notary.build_receipt(honest_card, issued_on, primary, exact)
    results = {"honest": honest["verdict"], "planted": {}, "why": {}, "tampered": {}}
    receipts = {}
    for name, card in planted.items():
        receipts[name] = notary.build_receipt(card, issued_on, primary, exact)
        results["planted"][name] = receipts[name]["verdict"]
        results["why"][name] = [c["name"] for c in receipts[name]["checks"] if c["result"] in ("fail", "undecided")]
    for name, receipt in _tampered(honest, receipts["wall_breach"]).items():
        card = honest_card if name != "forged_verdict_rehashed" else planted["wall_breach"]
        results["tampered"][name] = notary.verify_receipt(receipt, card, primary, exact)
    results["held"] = int(results["honest"] == "holds")
    results["caught"] = sum(v != "holds" for v in results["planted"].values())
    results["tampered_caught"] = sum(bool(v) for v in results["tampered"].values())
    results["passed"] = (
        results["held"] == 1
        and results["caught"] == len(planted) == 10
        and results["tampered_caught"] == len(results["tampered"]) == 5
    )
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--break", dest="broken", choices=("none", "primary", "exact", "both"), default="none")
    parser.add_argument("--out", help="keep the generated cards, files and receipts in this folder")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(args.out) if args.out else Path(tmp)
        folder.mkdir(parents=True, exist_ok=True)
        r = run(folder, args.broken)
    print(f"{'HELD  ' if r['held'] else 'FAILED'} honest control: {r['honest']}")
    for name, verdict in r["planted"].items():
        why = ", ".join(r["why"][name]) or "no check failed"
        print(f"{'CAUGHT' if verdict != 'holds' else 'MISSED'} {name}: {verdict} ({why})")
    for name, problems in r["tampered"].items():
        print(f"{'CAUGHT' if problems else 'MISSED'} {name}: {'; '.join(problems) or 're-derived as if genuine'}")
    print(
        f"planted={len(r['planted'])} caught={r['caught']}; tampered={len(r['tampered'])} "
        f"caught={r['tampered_caught']}; honest=1 held={r['held']}; verifiers broken={args.broken}"
    )
    print("GATE PASS" if r["passed"] else "GATE FAIL")
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
