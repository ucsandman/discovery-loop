"""Claim Notary: re-check someone else's circle-packing claim and issue a receipt anyone can re-run.

    python notary.py check CARD.json [--out DIR] [--date YYYY-MM-DD]
    python notary.py verify-receipt RECEIPT.json CARD.json
    python notary.py issue claims/<id>/card.json [--date YYYY-MM-DD] [--correction TEXT]
    python notary.py reverify-all
    python notary.py index

The public registry is claims/<id>/ (card and file) and receipts/ (JSON, HTML and Markdown receipts, the index and
the corrections log).

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
FORMATS = ("pck", "packomania_txt", "json_corner", "json_centred", "txt_corner")
UNPUBLISHED = {
    "none": "No coordinates were published with this claim.",
    "program": "The result was published as a program, not coordinates. Phase 1 runs no outside code.",
}
CLAIMS_DIR = HERE / "claims"
RECEIPTS_DIR = HERE / "receipts"
CORRECTIONS = "CORRECTIONS.md"
OUTCOME_KEYS = (
    "schema",
    "claim_id",
    "issued_on",
    "claim",
    "card_sha256",
    "artifact",
    "rule",
    "measured",
    "volume",
    "verdict",
)
NUMBER = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
MIN_DECIMALS = 10
FLOAT_FLOOR = 1e-14  # the float verifier cannot resolve slacks finer than this
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
    "artifact": "Coordinates published",
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
    if isinstance(artifact, dict) and "published" in artifact:
        if set(artifact) - {"published", "note"} or artifact["published"] not in UNPUBLISHED:
            raise CardError("an unpublished artifact is {published: none or program, optional note}")
        target = None
    else:
        if (
            not isinstance(artifact, dict)
            or set(artifact) - {"path", "format", "sha256"}
            or not {"path", "format"} <= set(artifact)
        ):
            raise CardError("artifact must be {path, format, optional sha256} or {published, note}")
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


def _centre(value):
    """Shift a corner-origin decimal string to the centred square without rounding it."""
    try:
        with localcontext(prec=80):
            return format(Decimal(value) - Decimal("0.5"), "f")
    except (InvalidOperation, TypeError):
        return str(value)


def read_rows(text, fmt):
    """Rows of (x, y, r) decimal strings, centre-origin, exactly as printed."""
    lines = [line.strip() for line in text.splitlines()]
    if fmt == "pck":  # largest radius, author, then 'x y r'
        return [tuple(line.split()) for line in lines[2:] if line]
    if fmt == "packomania_txt":  # '#' comment lines, then 'index x y r'
        return [tuple(line.split()[1:]) for line in lines if line and not line.startswith("#")]
    if fmt in ("json_corner", "json_centred"):  # [[x, y, r], ...] or {"circles"|"pieces"|"solution": [...]}
        try:
            data = json.loads(text, parse_float=str, parse_int=str)
        except ValueError:
            return [("unreadable JSON",)]
        if isinstance(data, dict):
            data = next((data[k] for k in ("circles", "pieces", "solution") if k in data), None)
        if not isinstance(data, list):
            return [("no circle list",)]
        shift = _centre if fmt == "json_corner" else str
        return [
            (shift(c[0]), shift(c[1]), str(c[2]))
            if isinstance(c, list) and len(c) == 3
            else tuple(map(str, c))
            if isinstance(c, list)
            else (str(c),)
            for c in data
        ]
    # txt_corner: one circle per line, 'x y r' in [0, 1]^2, separated by spaces, commas or brackets
    rows = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        values = re.findall(NUMBER, line)
        rows.append((_centre(values[0]), _centre(values[1]), values[2]) if len(values) == 3 else tuple(values))
    return rows


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
    fmt = card["artifact"].get("format", "unpublished")
    checks = []

    def add(name, result, detail):
        checks.append({"name": name, "result": result, "detail": detail})

    artifact_sha = text_sha256(artifact_path) if artifact_path else None
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
        "artifact": {"path": card["artifact"].get("path"), "format": fmt, "sha256": artifact_sha, "decimals": None},
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
    if card["problem"] in PROBLEMS and artifact_path is None:
        add("scope", "pass", "Circle packing in the unit square, maximise the sum of radii.")
        note = card["artifact"].get("note")
        add("artifact", "undecided", UNPUBLISHED[card["artifact"]["published"]] + (f" {note}" if note else ""))
        return _seal(body, checks, "insufficient_spec")
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
    p = run_primary(primary, rows, n)
    e = exact(rows, n, tolerance)
    strict = (  # both verifiers see the packing fit with no allowance for rounding at all
        "error" not in e
        and "error" not in p
        and e["min_wall_slack"] >= 0
        and (e["min_pair_slack_sq"] or 0) >= 0
        and p["min_wall_slack"] >= -FLOAT_FLOOR
        and p["min_pair_slack_sq"] >= -FLOAT_FLOOR
    )
    if decimals is not None and decimals < MIN_DECIMALS and not strict:
        add(
            "precision",
            "undecided",
            f"Values are printed to {decimals} decimals and the packing fits only after allowing for that rounding; "
            f"at least {MIN_DECIMALS} decimals are needed to decide.",
        )
    float_tol = max(float(tolerance), FLOAT_FLOOR)
    p_ok = "error" not in p and p["min_wall_slack"] >= -float_tol and p["min_pair_slack_sq"] >= -float_tol
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
        reason = e.get("error") or p.get("error") or _violation(e, tolerance)
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
    unit = Fraction(1, 10 ** notary_exact.decimals_of(card["claimed_sum"]))
    rounded = diff <= max(SUM_AGREEMENT, unit / 2)
    truncated = unit > SUM_AGREEMENT and 0 <= total - claimed < unit
    add(
        "claimed_sum",
        "pass" if rounded or truncated else "fail",
        f"Claimed {card['claimed_sum']}, recomputed {_exact_decimal(total)}, difference {_sci(diff)}. "
        + (
            "Agrees to 1e-9."
            if diff <= SUM_AGREEMENT
            else "Agrees with the claim rounded to its printed digits."
            if rounded
            else "Agrees with the claim truncated to its printed digits."
            if truncated
            else "Neither rounding nor truncating the recomputed sum gives the claimed value."
        ),
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


def _violation(e, tolerance):
    """Plain words for how far a packing breaks the square or overlaps, against the rounding allowance."""
    parts = []
    if e["min_wall_slack"] < -tolerance:
        parts.append(f"a circle crosses the square's edge by {_sci(-e['min_wall_slack'])}")
    if e["min_pair_slack_sq"] is not None and e["min_pair_slack_sq"] < -tolerance:
        parts.append(f"two circles overlap (squared distance short by {_sci(-e['min_pair_slack_sq'])})")
    worst = max(-e["min_wall_slack"], -(e["min_pair_slack_sq"] or 0))
    times = f"about {float(worst / tolerance):,.0f} times" if tolerance else "beyond"
    return (
        " and ".join(parts) + f", {times} what rounding to the printed digits can cause "
        f"(allowance {_power_text(tolerance)})"
    )


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


def outcome(receipt):
    """The parts of a receipt that state a result; wording and program hashes are presentation."""
    body = {key: receipt.get(key) for key in OUTCOME_KEYS}
    body["checks"] = [(c["name"], c["result"]) for c in receipt.get("checks", [])]
    return body


def _receipt_paths(claim_id, receipts_dir):
    stem = Path(receipts_dir) / claim_id
    return Path(f"{stem}.receipt.json"), Path(f"{stem}.receipt.html"), Path(f"{stem}.md")


def write_receipt(receipt, receipts_dir):
    json_path, html_path, md_path = _receipt_paths(receipt["claim_id"], receipts_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(render_html(receipt), encoding="utf-8")
    md_path.write_text(render_markdown(receipt), encoding="utf-8")
    return json_path


def issue(card_path, issued_on, receipts_dir=None, correction=None):
    """Issue a registry receipt. Replacing a receipt whose outcome changes needs a correction, which is logged."""
    receipts_dir = Path(receipts_dir or RECEIPTS_DIR)
    receipt = build_receipt(card_path, issued_on)
    json_path = _receipt_paths(receipt["claim_id"], receipts_dir)[0]
    if json_path.is_file():
        old = json.loads(json_path.read_text(encoding="utf-8"))
        before, after = outcome(old), outcome(receipt)
        before.pop("issued_on")
        after.pop("issued_on")
        if before != after:
            if not correction:
                raise CardError(
                    f"{receipt['claim_id']}: the outcome would change "
                    f"({old['verdict']} -> {receipt['verdict']}); pass --correction with the reason"
                )
            log = receipts_dir / CORRECTIONS
            text = log.read_text(encoding="utf-8") if log.is_file() else CORRECTIONS_HEADER
            log.write_text(
                text.rstrip("\n") + f"\n| {issued_on} | {receipt['claim_id']} | {old['verdict']} | "
                f"{receipt['verdict']} | {correction.replace('|', '/')} |\n",
                encoding="utf-8",
            )
    write_receipt(receipt, receipts_dir)
    return receipt


CORRECTIONS_HEADER = """# Corrections

Every receipt whose outcome changed after it was issued, and why. A receipt is replaced only through
`python notary.py issue CARD --correction "reason"`, which writes the line below. Wording changes and new program
versions that leave every outcome the same are not corrections; the nightly re-check reports them separately.

| Date | Claim | Was | Now | Reason |
| --- | --- | --- | --- | --- |
"""


def reverify_all(claims_dir=None, receipts_dir=None):
    """Re-derive every registry receipt from its card. Returns one (claim_id, status, detail) per receipt or card."""
    claims_dir, receipts_dir = Path(claims_dir or CLAIMS_DIR), Path(receipts_dir or RECEIPTS_DIR)
    results, seen = [], set()
    for path in sorted(receipts_dir.glob("*.receipt.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        claim_id = receipt.get("claim_id", path.name)
        seen.add(claim_id)
        card = claims_dir / claim_id / "card.json"
        body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        if hashlib.sha256(canonical(body).encode()).hexdigest() != receipt.get("receipt_sha256"):
            results.append((claim_id, "tampered", "receipt_sha256 does not match the receipt's contents"))
            continue
        if not card.is_file():
            results.append((claim_id, "missing_card", f"no {card.relative_to(claims_dir.parent)}"))
            continue
        try:
            fresh = build_receipt(card, receipt["issued_on"])
        except CardError as exc:
            results.append((claim_id, "card_rejected", str(exc)))
            continue
        changed = [k for k, v in outcome(fresh).items() if v != outcome(receipt)[k]]
        if changed:
            results.append((claim_id, "changed", "differs in " + ", ".join(changed)))
        elif fresh != receipt:
            results.append((claim_id, "reworded", "same outcome; wording or program versions are newer"))
        else:
            results.append((claim_id, "reproduced", receipt["verdict"]))
    for card in sorted(claims_dir.glob("*/card.json")):
        if card.parent.name not in seen:
            results.append((card.parent.name, "unissued", "card has no receipt yet"))
    return results


def _md(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(receipt):
    title, sentence = VERDICT_TEXT[receipt["verdict"]]
    claim = receipt["claim"]
    measured = receipt["measured"]
    ref = claim.get("reference")
    lines = [
        f"# {_md(claim['statement'])}",
        "",
        f"Claim Notary receipt, issued {receipt['issued_on']}. Claimed by {_md(claim['claimant'])}"
        + (f" ([source]({claim['source_url']}))." if claim.get("source_url") else "."),
        "",
        f"> **{title}.** {sentence}",
        "",
        "## The claim",
        "",
        "| | |",
        "| --- | --- |",
        f"| Circles | {claim['n']} |",
        f"| Claimed sum of radii | {_md(claim['claimed_sum'])} |",
    ]
    if ref:
        lines.append(f"| Reference it beats | {_md(ref['value'])} ({_md(ref['source'])}) |")
    if "claimed_gain_pct" in claim:
        lines.append(f"| Claimed gain | {_md(claim['claimed_gain_pct'])}% |")
    lines += ["", "## What was checked", "", "| Check | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {LABELS.get(c['name'], c['name'])} | {c['result']} | {_md(c['detail'])} |" for c in receipt["checks"]]
    lines += [
        "",
        "## What was measured",
        "",
        "| | |",
        "| --- | --- |",
        f"| Recomputed sum of radii (exact) | `{measured.get('sum', 'none')}` |",
        f"| Smallest gap to a wall | {measured.get('min_wall_slack', 'none')} |",
        f"| Smallest squared gap between two circles (negative means overlap) | "
        f"{measured.get('min_pair_slack_sq', 'none')} |",
        f"| Tolerance, from the file's {receipt['artifact']['decimals']} printed decimals | "
        f"{receipt['rule']['tolerance']} |",
        f"| Work done | {receipt['volume']['circles']} circles, {receipt['volume']['pairs_checked']} pairs |",
        "",
        "## What this receipt does not show",
        "",
    ]
    lines += [f"- {item}" for item in receipt["does_not_show"]]
    lines += [
        "",
        "## Check it yourself",
        "",
        f"From a clone of this repository: `python notary.py verify-receipt receipts/{receipt['claim_id']}.receipt.json "
        f"claims/{receipt['claim_id']}/card.json`. It re-runs every check and lists any difference.",
        "",
        "| | sha256 |",
        "| --- | --- |",
        f"| Receipt | `{receipt['receipt_sha256']}` |",
        f"| Claim card | `{receipt['card_sha256']}` |",
    ]
    if receipt["artifact"]["sha256"]:
        lines.append(f"| File `{receipt['artifact']['path']}` | `{receipt['artifact']['sha256']}` |")
    lines += [f"| Verifier `{v['path']}` | `{v['sha256']}` |" for v in receipt["verifiers"].values()]
    lines += ["", f"Rules fixed in advance in [{receipt['rule']['prereg']}](../{receipt['rule']['prereg']})."]
    return "\n".join(lines) + "\n"


def render_index(receipts_dir=None):
    """receipts/README.md: the calibration line and one row per receipt."""
    receipts_dir = Path(receipts_dir or RECEIPTS_DIR)
    receipts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(receipts_dir.glob("*.receipt.json"))]
    counts = {v: sum(r["verdict"] == v for r in receipts) for v in VERDICT_TEXT}
    log = receipts_dir / CORRECTIONS
    corrections = (
        sum(1 for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("| 2"))
        if log.is_file()
        else 0
    )
    lines = [
        "# Claim Notary receipts",
        "",
        "Independent re-checks of optimization claims made by others, mostly found with AI. Each receipt was produced",
        "by two verifiers that share no code, binds the exact file it checked by hash, and can be re-run by anyone",
        "with `python notary.py verify-receipt`. Every receipt is re-derived from its claim card on every push and",
        "every night. How it works: [docs/NOTARY.md](../docs/NOTARY.md).",
        "",
        f"**Claims checked: {len(receipts)}.** Holds: {counts['holds']}. Does not hold: {counts['does_not_hold']}. "
        f"Cannot be decided from what was given: {counts['insufficient_spec']}. Outside what we can check: "
        f"{counts['cannot_check']}. Corrections to our own receipts: {corrections} ([log]({CORRECTIONS})).",
        "",
        "| Claim | Claimed by | Verdict | Recomputed sum | Issued |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in sorted(receipts, key=lambda r: (r["claim"]["claimant"], r["claim_id"])):
        lines.append(
            f"| [{_md(r['claim_id'])}]({r['claim_id']}.md) | {_md(r['claim']['claimant'])} | "
            f"{VERDICT_TEXT[r['verdict']][0]} | {r['measured'].get('sum', 'none')} | {r['issued_on']} |"
        )
    path = receipts_dir / "README.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not log.is_file():
        log.write_text(CORRECTIONS_HEADER, encoding="utf-8")
    return path


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
    ]
    if receipt["artifact"]["sha256"]:
        hashes.append((f"File ({receipt['artifact']['path']})", receipt["artifact"]["sha256"]))
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
    issue_cmd = sub.add_parser("issue", help="issue a registry receipt into receipts/ and refresh the index")
    issue_cmd.add_argument("card")
    issue_cmd.add_argument("--date", default=datetime.date.today().isoformat())
    issue_cmd.add_argument("--correction", help="required when the new receipt changes an issued outcome")
    sub.add_parser("reverify-all", help="re-derive every registry receipt from its claim card")
    sub.add_parser("index", help="rewrite receipts/README.md")
    args = parser.parse_args(argv)
    try:
        if args.command == "issue":
            receipt = issue(args.card, args.date, correction=args.correction)
            render_index()
            print(f"{receipt['claim_id']}: {receipt['verdict']} -> receipts/{receipt['claim_id']}.md")
            return 0
        if args.command == "index":
            print(f"wrote {render_index().relative_to(HERE)}")
            return 0
        if args.command == "reverify-all":
            results = reverify_all()
            for claim_id, status, detail in results:
                print(f"{status:13} {claim_id}: {detail}")
            tally = {s: sum(r[1] == s for r in results) for s in sorted({r[1] for r in results})}
            bad = sum(n for s, n in tally.items() if s not in ("reproduced", "reworded"))
            print(
                f"receipts={sum(r[1] != 'unissued' for r in results)} " + " ".join(f"{s}={n}" for s, n in tally.items())
            )
            print("REVERIFY PASS" if results and not bad else "REVERIFY FAIL")
            return 0 if results and not bad else 1
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
