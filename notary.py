"""Claim Notary: re-check someone else's circle-packing claim and issue a receipt anyone can re-run.

    python notary.py check CARD.json [--out DIR] [--date YYYY-MM-DD]
    python notary.py verify-receipt RECEIPT.json CARD.json

Phase 1 checks circle-packing claims only, and only data: no program from outside runs here. The rules are fixed
in docs/notary-prereg.md and described in docs/NOTARY.md. Nothing here fetches, sends or publishes anything.
"""

import argparse
import datetime
import hashlib
import html
import importlib.util
import json
import re
import sys
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path

import notary_exact

HERE = Path(__file__).resolve().parent
PRIMARY_PATH = HERE / "problems" / "circle_packing" / "verify.py"
EXACT_PATH = HERE / "notary_exact.py"
CARD_SCHEMA = "claim-card-v1"
RECEIPT_SCHEMA = "claim-receipt-v1"
PROBLEMS = ("circle_packing",)
FORMATS = ("pck", "packomania_txt")
MIN_DECIMALS = 10
SUM_AGREEMENT = Fraction(1, 10**9)
GAIN_AGREEMENT_PP = Fraction(1, 100)
VERIFIER_SUM_AGREEMENT = 1e-12
CARD_FIELDS = {
    "schema",
    "claim_id",
    "problem",
    "claimant",
    "statement",
    "source_url",
    "artifact",
    "n",
    "claimed_sum",
    "reference",
    "claimed_gain_pct",
}
REQUIRED_FIELDS = {"schema", "claim_id", "problem", "claimant", "statement", "artifact", "n", "claimed_sum"}
CLAIM_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DOES_NOT_SHOW = (
    "That this packing is the best possible. Only that it is valid and has the sum printed here.",
    "That the reference value is the best known today. It is taken from the claim as stated, with its source.",
    "Who found the packing or how. The notary checks the file, not its history.",
    "Anything about a file other than the one whose hash is printed on this receipt.",
)
LABELS = {
    "scope": "Within what the notary can check",
    "artifact_hash": "File matches the claim",
    "precision": "Enough printed precision to check",
    "feasibility": "Valid packing (inside the square, no overlaps)",
    "verifiers_agree_on_sum": "Two independent verifiers agree",
    "claimed_sum": "Claimed sum of radii",
    "beats_reference": "Beats the stated reference",
    "claimed_gain": "Claimed gain",
}
VERDICT_TEXT = {
    "holds": ("Holds", "Every check passed and two independent verifiers agree."),
    "does_not_hold": ("Does not hold", "At least one check failed. The failed checks are listed below."),
    "insufficient_spec": (
        "Cannot be decided from what was given",
        "The verifiers disagree or the file lacks the precision to decide. Nothing was guessed.",
    ),
    "cannot_check": ("Outside what the notary can check", "No independent verifier exists here for this claim."),
}


class CardError(ValueError):
    pass


def text_sha256(path):
    """SHA-256 of a text file with line endings normalised to LF, so the hash is the same on every OS."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _decimal(text, field):
    try:
        value = Decimal(str(text).strip())
    except InvalidOperation:
        raise CardError(f"{field} must be a decimal number written as a string") from None
    if not isinstance(text, str) or not value.is_finite():
        raise CardError(f"{field} must be a finite decimal number written as a string")
    return Fraction(value)


def load_card(path):
    path = Path(path)
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CardError(f"cannot read claim card {path.name}: {exc}") from None
    if not isinstance(card, dict):
        raise CardError("a claim card is a JSON object")
    unknown = set(card) - CARD_FIELDS
    missing = REQUIRED_FIELDS - set(card)
    if unknown or missing:
        raise CardError(f"claim card fields: unknown {sorted(unknown)}, missing {sorted(missing)}")
    if card["schema"] != CARD_SCHEMA:
        raise CardError(f"schema must be {CARD_SCHEMA}")
    if not isinstance(card["claim_id"], str) or not CLAIM_ID.match(card["claim_id"]):
        raise CardError("claim_id must be 1-80 letters, digits, dots, dashes or underscores")
    for field in ("problem", "claimant", "statement"):
        if not isinstance(card[field], str) or not card[field].strip():
            raise CardError(f"{field} must be a non-empty string")
    if "source_url" in card and not (isinstance(card["source_url"], str) and card["source_url"].startswith("https://")):
        raise CardError("source_url must be an https:// address")
    artifact = card["artifact"]
    if (
        not isinstance(artifact, dict)
        or set(artifact) - {"path", "format", "sha256"}
        or not {"path", "format"} <= set(artifact)
    ):
        raise CardError("artifact must be {path, format, optional sha256}")
    target = (path.parent / str(artifact["path"])).resolve()
    if path.parent.resolve() not in target.parents or not target.is_file():
        raise CardError("artifact path must name a file inside the claim card's folder")
    if "sha256" in artifact and not re.fullmatch(r"[0-9a-f]{64}", str(artifact["sha256"])):
        raise CardError("artifact sha256 must be 64 lowercase hex characters")
    if not isinstance(card["n"], int) or isinstance(card["n"], bool) or card["n"] < 1:
        raise CardError("n must be a positive integer")
    _decimal(card["claimed_sum"], "claimed_sum")
    if "reference" in card:
        ref = card["reference"]
        if not isinstance(ref, dict) or set(ref) != {"value", "source"} or not str(ref["source"]).strip():
            raise CardError("reference must be {value, source}")
        _decimal(ref["value"], "reference value")
    if "claimed_gain_pct" in card:
        if "reference" not in card:
            raise CardError("claimed_gain_pct needs a reference")
        _decimal(card["claimed_gain_pct"], "claimed_gain_pct")
    return card, target


def read_rows(text, fmt):
    """Rows of (x, y, r) decimal strings, centre-origin, exactly as printed."""
    lines = [line.strip() for line in text.splitlines()]
    if fmt == "pck":  # largest radius, author, then 'x y r'
        return [tuple(line.split()) for line in lines[2:] if line]
    # packomania_txt: '#' comment lines, then 'index x y r'
    return [tuple(line.split()[1:]) for line in lines if line and not line.startswith("#")]


_PRIMARY = None


def primary_check():
    global _PRIMARY
    if _PRIMARY is None:
        spec = importlib.util.spec_from_file_location("notary_primary_verify", PRIMARY_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PRIMARY = module.check
    return _PRIMARY


def run_primary(check, rows, n):
    """The primary verifier works on floats in the corner-origin unit square."""
    try:
        circles = [[float(v) for v in row] for row in rows]
    except ValueError:
        return {"feasible": False, "error": "every x, y, and radius must be a number"}
    circles = [[c[0] + 0.5, c[1] + 0.5, c[2]] if len(c) == 3 else c for c in circles]
    return check(circles, n)


def _exact_decimal(fraction):
    with localcontext(prec=60):
        return format(Decimal(fraction.numerator) / Decimal(fraction.denominator), "f")


def _power_text(fraction):
    if fraction == 0:
        return "0"
    return f"1e-{len(str(fraction.denominator)) - 1}"


def _sci(value):
    return "none" if value is None else f"{float(value):.3e}"


def canonical(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_receipt(card_path, issued_on, primary=None, exact=None):
    if not isinstance(issued_on, str) or not DATE.match(issued_on):
        raise CardError("issued_on must be YYYY-MM-DD")
    card, artifact_path = load_card(card_path)
    primary = primary or primary_check()
    exact = exact or notary_exact.check_exact
    n = card["n"]
    fmt = card["artifact"]["format"]
    checks = []

    def add(name, result, detail):
        checks.append({"name": name, "result": result, "detail": detail})

    artifact_sha = text_sha256(artifact_path)
    body = {
        "schema": RECEIPT_SCHEMA,
        "claim_id": card["claim_id"],
        "issued_on": issued_on,
        "claim": {
            key: card[key]
            for key in (
                "problem",
                "claimant",
                "statement",
                "source_url",
                "n",
                "claimed_sum",
                "reference",
                "claimed_gain_pct",
            )
            if key in card
        },
        "card_sha256": text_sha256(card_path),
        "artifact": {"path": card["artifact"]["path"], "format": fmt, "sha256": artifact_sha, "decimals": None},
        "verifiers": {
            "primary": {"path": "problems/circle_packing/verify.py", "sha256": text_sha256(PRIMARY_PATH)},
            "exact": {"path": "notary_exact.py", "sha256": text_sha256(EXACT_PATH)},
            "notary": {"path": "notary.py", "sha256": text_sha256(Path(__file__))},
        },
        "rule": {
            "tolerance": None,
            "sum_agreement": "1e-9",
            "gain_agreement_pp": "0.01",
            "min_decimals": MIN_DECIMALS,
            "prereg": "docs/notary-prereg.md",
        },
        "measured": {},
        "volume": {"circles": 0, "pairs_checked": 0},
        "does_not_show": list(DOES_NOT_SHOW),
    }
    if card["problem"] not in PROBLEMS or fmt not in FORMATS:
        add("scope", "fail", f"No verifier for problem {card['problem']!r} in format {fmt!r}.")
        return _seal(body, checks, "cannot_check")
    add("scope", "pass", "Circle packing in the unit square, maximise the sum of radii.")
    claimed_sha = card["artifact"].get("sha256")
    if claimed_sha and claimed_sha != artifact_sha:
        add("artifact_hash", "fail", f"The file's sha256 is {artifact_sha}; the claim names {claimed_sha}.")
    else:
        add(
            "artifact_hash",
            "pass",
            "The file's sha256 matches the claim."
            if claimed_sha
            else "The claim names no hash; this receipt binds to the file's sha256 listed under Check it yourself.",
        )
    rows = read_rows(artifact_path.read_text(encoding="utf-8", errors="replace"), fmt)
    places = [notary_exact.decimals_of(v) for row in rows for v in row]
    decimals = min(places) if places and None not in places else None
    tolerance = Fraction(1, 10 ** (decimals - 1)) if decimals else Fraction(0)
    body["artifact"]["decimals"] = decimals
    body["rule"]["tolerance"] = _power_text(tolerance)
    if decimals is not None and decimals < MIN_DECIMALS:
        add(
            "precision",
            "undecided",
            f"Values are printed to {decimals} decimals; at least {MIN_DECIMALS} are needed to check a sum to 1e-9.",
        )
    p = run_primary(primary, rows, n)
    e = exact(rows, n, tolerance)
    p_ok = "error" not in p and p["min_wall_slack"] >= -float(tolerance) and p["min_pair_slack_sq"] >= -float(tolerance)
    e_ok = bool(e.get("feasible")) and "error" not in e
    if p_ok and e_ok and "error" not in e and min(e["min_wall_slack"], e["min_pair_slack_sq"] or 0) < 0:
        add(
            "feasibility",
            "pass",
            f"Inside the square, by both verifiers. The smallest gaps are slightly negative, "
            f"within what rounding to {decimals} printed decimals can cause (tolerance {_power_text(tolerance)}).",
        )
    elif p_ok and e_ok:
        add("feasibility", "pass", "Inside the square with no overlaps, by both verifiers.")
    elif not p_ok and not e_ok:
        reason = (
            e.get("error")
            or p.get("error")
            or (
                f"minimum wall slack {_sci(e['min_wall_slack'])}, minimum squared pair slack "
                f"{_sci(e['min_pair_slack_sq'])}, tolerance {_power_text(tolerance)}"
            )
        )
        add("feasibility", "fail", f"Both verifiers reject the packing: {reason}.")
    else:
        add(
            "feasibility",
            "undecided",
            f"The verifiers disagree: primary says {'valid' if p_ok else 'invalid'}, "
            f"exact says {'valid' if e_ok else 'invalid'}. Nothing was guessed.",
        )
    if "error" in e or "error" in p:
        add("claimed_sum", "skip", "No sum: the file did not pass the basic checks.")
        return _seal(body, checks, _verdict(checks))
    total = e["sum"]
    body["measured"] = {
        "sum": _exact_decimal(total),
        "min_wall_slack": _sci(e["min_wall_slack"]),
        "min_pair_slack_sq": _sci(e["min_pair_slack_sq"]),
    }
    body["volume"] = {"circles": len(rows), "pairs_checked": len(rows) * (len(rows) - 1) // 2}
    gap = abs(p["sum"] - float(total))
    add(
        "verifiers_agree_on_sum",
        "pass" if gap <= VERIFIER_SUM_AGREEMENT else "undecided",
        f"Primary and exact sums differ by {gap:.1e}.",
    )
    claimed = _decimal(card["claimed_sum"], "claimed_sum")
    diff = abs(claimed - total)
    add(
        "claimed_sum",
        "pass" if diff <= SUM_AGREEMENT else "fail",
        f"Claimed {card['claimed_sum']}, recomputed {_exact_decimal(total)}, difference {_sci(diff)}.",
    )
    if "reference" in card:
        ref = _decimal(card["reference"]["value"], "reference value")
        add(
            "beats_reference",
            "pass" if total > ref else "fail",
            f"Recomputed sum {'exceeds' if total > ref else 'does not exceed'} the reference "
            f"{card['reference']['value']} ({card['reference']['source']}).",
        )
        if "claimed_gain_pct" in card:
            gain = (total / ref - 1) * 100
            claimed_gain = _decimal(card["claimed_gain_pct"], "claimed_gain_pct")
            add(
                "claimed_gain",
                "pass" if abs(claimed_gain - gain) <= GAIN_AGREEMENT_PP else "fail",
                f"Claimed {card['claimed_gain_pct']}%, recomputed {float(gain):.4f}% against the reference.",
            )
    return _seal(body, checks, _verdict(checks))


def _verdict(checks):
    results = {c["result"] for c in checks}
    if "fail" in results:
        return "does_not_hold"
    if "undecided" in results:
        return "insufficient_spec"
    return "holds"


def _seal(body, checks, verdict):
    body["checks"] = checks
    body["verdict"] = verdict
    body["receipt_sha256"] = hashlib.sha256(canonical(body).encode()).hexdigest()
    return body


def verify_receipt(receipt, card_path, primary=None, exact=None):
    """Problems found when a receipt is re-derived from its claim card; an empty list means it re-derives exactly."""
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    problems = []
    if hashlib.sha256(canonical(body).encode()).hexdigest() != receipt.get("receipt_sha256"):
        problems.append("receipt_sha256 does not match the receipt's contents")
    fresh = build_receipt(card_path, receipt.get("issued_on"), primary, exact)
    for key in sorted((set(fresh) | set(receipt)) - {"receipt_sha256"}):
        if fresh.get(key) != receipt.get(key):
            problems.append(f"{key} differs from a fresh check")
    return problems


def render_html(receipt):
    e = html.escape
    title, sentence = VERDICT_TEXT[receipt["verdict"]]
    claim = receipt["claim"]
    source = claim.get("source_url")
    rows = "".join(
        f"<tr class='{e(c['result'])}'><td>{e(LABELS.get(c['name'], c['name']))}</td><td>{e(c['result'])}</td>"
        f"<td>{e(c['detail'])}</td></tr>"
        for c in receipt["checks"]
    )
    measured = receipt["measured"]
    ref = claim.get("reference")
    hashes = [
        ("Receipt", receipt["receipt_sha256"]),
        ("Claim card", receipt["card_sha256"]),
        (f"File ({receipt['artifact']['path']})", receipt["artifact"]["sha256"]),
    ]
    hashes += [(f"Verifier {v['path']}", v["sha256"]) for v in receipt["verifiers"].values()]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claim receipt: {e(receipt["claim_id"])}</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#1d1d1b;background:#fbfaf7}}
h1{{font-size:1.5rem;margin:0 0 .25rem}} h2{{font-size:1.05rem;margin:2rem 0 .5rem}}
.verdict{{padding:1rem 1.25rem;border-radius:6px;margin:1rem 0;border:2px solid}}
.verdict strong{{font-size:1.4rem;display:block}}
.holds{{border-color:#2f6b3a;background:#eef6ef}} .does_not_hold{{border-color:#9b2c2c;background:#faeeee}}
.insufficient_spec,.cannot_check{{border-color:#8a6d1d;background:#faf5e6}}
table{{border-collapse:collapse;width:100%;font-size:.95rem}} td,th{{text-align:left;padding:.4rem .5rem;
border-bottom:1px solid #ddd;vertical-align:top}} tr.fail td:nth-child(2){{color:#9b2c2c;font-weight:600}}
tr.pass td:nth-child(2){{color:#2f6b3a;font-weight:600}} tr.undecided td:nth-child(2){{color:#8a6d1d;font-weight:600}}
code{{font-size:.85rem;word-break:break-all}} .muted{{color:#5d5d57}}
</style></head><body>
<p class="muted">Claim Notary receipt, issued {e(receipt["issued_on"])}</p>
<h1>{e(claim["statement"])}</h1>
<p class="muted">Claimed by {e(claim["claimant"])}{f" &middot; <a href='{e(source)}'>source</a>" if source else ""}</p>
<div class="verdict {e(receipt["verdict"])}"><strong>{e(title)}</strong>{e(sentence)}</div>
<h2>The claim</h2>
<table><tr><td>Circles</td><td>{claim["n"]}</td></tr>
<tr><td>Claimed sum of radii</td><td>{e(claim["claimed_sum"])}</td></tr>
{f"<tr><td>Reference it beats</td><td>{e(ref['value'])} ({e(ref['source'])})</td></tr>" if ref else ""}
{f"<tr><td>Claimed gain</td><td>{e(claim['claimed_gain_pct'])}%</td></tr>" if "claimed_gain_pct" in claim else ""}
</table>
<h2>What was checked</h2>
<table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>{rows}</table>
<h2>What was measured</h2>
<table><tr><td>Recomputed sum of radii (exact)</td><td><code>{e(measured.get("sum", "none"))}</code></td></tr>
<tr><td>Smallest gap to a wall</td><td>{e(measured.get("min_wall_slack", "none"))}</td></tr>
<tr><td>Smallest squared gap between two circles (negative means overlap)</td><td>{
        e(measured.get("min_pair_slack_sq", "none"))
    }</td></tr>
<tr><td>Tolerance, from the file's {e(str(receipt["artifact"]["decimals"]))} printed decimals</td>
<td>{e(str(receipt["rule"]["tolerance"]))}</td></tr>
<tr><td>Work done</td><td>{receipt["volume"]["circles"]} circles, {
        receipt["volume"]["pairs_checked"]
    } pairs</td></tr></table>
<h2>What this receipt does not show</h2>
<ul>{"".join(f"<li>{e(item)}</li>" for item in receipt["does_not_show"])}</ul>
<h2>Check it yourself</h2>
<p>With the claim card and the file, run <code>python notary.py verify-receipt RECEIPT.json CARD.json</code> from
the Discovery Loop repository. It re-runs every check and reports any difference from this receipt.</p>
<table>{"".join(f"<tr><td>{e(name)}</td><td><code>{e(value)}</code></td></tr>" for name, value in hashes)}</table>
<p class="muted">Two verifiers that share no code. Rules fixed in advance in {e(receipt["rule"]["prereg"])}.
Nothing was sent or published by issuing this receipt.</p>
</body></html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check a claim card and write its receipt")
    check.add_argument("card")
    check.add_argument("--out", default=str(HERE / "runs" / "notary"))
    check.add_argument("--date", default=datetime.date.today().isoformat())
    verify = sub.add_parser("verify-receipt", help="re-derive a receipt from its claim card")
    verify.add_argument("receipt")
    verify.add_argument("card")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            receipt = build_receipt(args.card, args.date)
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            stem = out / receipt["claim_id"]
            Path(f"{stem}.receipt.json").write_text(
                json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
            Path(f"{stem}.receipt.html").write_text(render_html(receipt), encoding="utf-8")
            counts = {r: sum(c["result"] == r for c in receipt["checks"]) for r in ("fail", "undecided")}
            print(
                f"{receipt['claim_id']}: {receipt['verdict']} (checks={len(receipt['checks'])} "
                f"failed={counts['fail']} undecided={counts['undecided']}; circles={receipt['volume']['circles']} "
                f"pairs={receipt['volume']['pairs_checked']}) -> {stem}.receipt.html"
            )
            return 0 if receipt["verdict"] == "holds" else 1
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
        problems = verify_receipt(receipt, args.card)
        for problem in problems:
            print(f"DIFFERS: {problem}")
        print(
            f"{receipt.get('claim_id')}: {'re-derives exactly' if not problems else 'does not re-derive'} "
            f"(checks={len(receipt.get('checks', []))} problems={len(problems)})"
        )
        return 0 if not problems else 1
    except CardError as exc:
        print(f"claim card rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
