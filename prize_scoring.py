"""Score and rank curated prize entries, and plan a research allowance across them.

Everything here is a pure function over the registry dicts described in
``docs/PRIZE-HUNT.md``: no file is written, no money is spent, nothing is fetched.
``allocate`` returns a *plan*; acting on it is a separate, human-gated step.

The categorical -> numeric maps below are deliberate, documented guesses. They exist so
that two prizes can be compared on one axis, not so that a dollar figure can be quoted.
Only ``estimated_usd`` is a verified number, and even that carries its own
``estimated_usd_basis`` in the registry. Cash and credibility are reported separately and
are never summed into a single "expected winnings" figure.
"""

from __future__ import annotations

import math
from typing import Any

# Probability that this lab produces a qualifying result, by registry category.
# Three-point bands (low, mid, high); the width is the honest part.
PROBABILITY_BANDS = {
    "likely": (0.3, 0.5, 0.7),
    "possible": (0.05, 0.15, 0.3),
    "unlikely": (0.01, 0.03, 0.08),
    "remote": (1e-4, 1e-3, 5e-3),
    "negligible": (0.0, 1e-6, 1e-4),
}
DEFAULT_PROBABILITY = "negligible"

# How much of the advertised cash survives the question "would it actually be paid?".
STATUS_FACTORS = {
    "verified_active": 1.0,
    "probably_active": 0.7,
    "status_uncertain": 0.35,
    "historical": 0.1,
    "closed": 0.0,
    "solved": 0.0,
    "not_prize_eligible": 0.0,
}

# Credibility-equivalent dollars. NOT cash: a stand-in so a no-cash record chase can be
# compared against a cash bounty on one axis. Reported under ``credibility_ev_usd``.
CREDIBILITY_USD = {"none": 0.0, "low": 500.0, "medium": 3000.0, "high": 15000.0}
CREDIBILITY_FIELDS = ("publication_value", "commercial_value", "transfer_value")

# Cost of one serious attempt, by registry category, as (low, mid, high) USD.
COST_BANDS = {
    "negligible": (0.0, 0.5, 1.0),
    "cheap": (1.0, 5.0, 10.0),
    "moderate": (10.0, 50.0, 100.0),
    "expensive": (100.0, 500.0, 1000.0),
    "prohibitive": (1000.0, 3000.0, 10000.0),
}
DEFAULT_COST = "moderate"

DENSE_FEEDBACK_MULTIPLIER = 1.5
VERIFICATION_MULTIPLIERS = {"strong": 1.2, "partial": 1.0, "weak": 0.6}
COMPETITION_MULTIPLIERS = {"none": 1.0, "low": 1.0, "medium": 0.8, "high": 0.6}
PARALLELIZABLE_MULTIPLIER = 1.1
TIME_HORIZON_MULTIPLIERS = {
    "days": 1.0,
    "weeks": 1.0,
    "months": 1.0,
    "years": 0.7,
    "open_ended": 0.7,
}

# Information-gain weights. They sum to 1.0, so the score is a real 0..1 fraction.
INFORMATION_WEIGHTS = {"dense_feedback": 0.35, "verification": 0.25, "transfer": 0.25, "progress": 0.15}
VERIFICATION_INFORMATION = {"strong": 1.0, "partial": 0.6, "weak": 0.2}
TRANSFER_INFORMATION = {"none": 0.0, "low": 0.2, "medium": 0.6, "high": 1.0}
# A measured relative gain of this size counts as a full information payout.
FULL_PROGRESS_GAIN = 0.1

MOONSHOT_DIFFICULTY = {"infeasible_today"}
MOONSHOT_RESEARCH = {"breakthrough_required"}
MOONSHOT_PROBABILITY = {"remote", "negligible"}
EXCLUDED_STATUSES = {"closed", "solved"}

BUCKETS = ("measurable-progress", "moonshot", "excluded")


def _finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    return value if math.isfinite(value) else default


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bands(low: float, mid: float, high: float, digits: int = 4) -> dict[str, float]:
    return {"low": round(low, digits), "mid": round(mid, digits), "high": round(high, digits)}


def _category(prize: dict, field: str, table: dict, default: str) -> str:
    value = _text(prize.get(field))
    return value if value in table else default


def _admission(prize: dict) -> str:
    """Read the admission decided by ``prize_registry``; derive a default when absent.

    ``prize_registry.snapshot`` merges an ``admission`` field onto every prize. A bare
    ``data/prizes.json`` entry has none, so a prize naming a plugin is treated as ready
    and a plugin-less one as ``needs_setup``. The registry decision always wins.
    """
    value = prize.get("admission")
    if isinstance(value, dict):
        value = value.get("admission")
    if isinstance(value, str) and value:
        return value
    return "ready" if _text(prize.get("plugin")) else "needs_setup"


def _bucket(prize: dict) -> str:
    if _text(prize.get("research_priority")) == "excluded" or _text(prize.get("status")) in EXCLUDED_STATUSES:
        return "excluded"
    if (
        _text(prize.get("computational_difficulty")) in MOONSHOT_DIFFICULTY
        or _text(prize.get("research_difficulty")) in MOONSHOT_RESEARCH
        or _category(prize, "probability_category", PROBABILITY_BANDS, DEFAULT_PROBABILITY) in MOONSHOT_PROBABILITY
    ):
        return "moonshot"
    return "measurable-progress"


def _cost_estimate(prize: dict, field: str) -> tuple[float, float, float]:
    block = prize.get(field)
    category = DEFAULT_COST
    if isinstance(block, dict):
        candidate = _text(block.get("category"))
        if candidate in COST_BANDS:
            category = candidate
    return COST_BANDS[category]


def _information_gain(prize: dict, progress: dict | None) -> tuple[float, list[str]]:
    rationale = []
    gain = 0.0
    if prize.get("dense_feedback") is True:
        gain += INFORMATION_WEIGHTS["dense_feedback"]
        rationale.append("dense per-attempt feedback")
    verification = _text(prize.get("independent_verification"))
    gain += INFORMATION_WEIGHTS["verification"] * VERIFICATION_INFORMATION.get(verification, 0.2)
    transfer = _text(prize.get("transfer_value"))
    gain += INFORMATION_WEIGHTS["transfer"] * TRANSFER_INFORMATION.get(transfer, 0.0)
    best_gain = _finite((progress or {}).get("best_gain"), 0.0)
    if best_gain > 0:
        share = min(1.0, best_gain / FULL_PROGRESS_GAIN)
        gain += INFORMATION_WEIGHTS["progress"] * share
        rationale.append(f"measured best gain {best_gain:.4g}")
    return min(1.0, round(gain, 6)), rationale


def _multiplier(prize: dict) -> tuple[float, list[str]]:
    rationale = []
    multiplier = 1.0
    if prize.get("dense_feedback") is True:
        multiplier *= DENSE_FEEDBACK_MULTIPLIER
    verification = _text(prize.get("independent_verification"))
    multiplier *= VERIFICATION_MULTIPLIERS.get(verification, 1.0)
    if verification == "weak":
        rationale.append("weak independent verification discounts the value")
    competition = _text(prize.get("competition_level"))
    multiplier *= COMPETITION_MULTIPLIERS.get(competition, 1.0)
    if competition in ("medium", "high"):
        rationale.append(f"{competition} competition discounts the value")
    if prize.get("parallelizable") is True:
        multiplier *= PARALLELIZABLE_MULTIPLIER
    horizon = _text(prize.get("time_horizon"))
    multiplier *= TIME_HORIZON_MULTIPLIERS.get(horizon, 1.0)
    if horizon in ("years", "open_ended"):
        rationale.append(f"{horizon} time horizon discounts the value")
    return multiplier, rationale


def score_prize(prize: dict, *, progress: dict | None = None) -> dict:
    """Score one registry prize. Never raises: unknown categories fall back to defaults.

    ``progress`` is the optional per-plugin summary from ``prize_economics`` (``best_gain``
    and ``attempts``); measured progress only raises ``information_gain``, never the cash EV.
    """
    if not isinstance(prize, dict):
        prize = {}
    probability = _category(prize, "probability_category", PROBABILITY_BANDS, DEFAULT_PROBABILITY)
    probability_band = PROBABILITY_BANDS[probability]
    status = _text(prize.get("status"))
    status_factor = STATUS_FACTORS.get(status, 0.0)

    advertised = max(0.0, _finite(prize.get("estimated_usd"), 0.0))
    cash = _bands(*(advertised * p * status_factor for p in probability_band))

    credibility_base = sum(CREDIBILITY_USD.get(_text(prize.get(field)), 0.0) for field in CREDIBILITY_FIELDS)
    # Credibility is not paid out by anyone, so the prize's payment status does not gate it.
    credibility = _bands(*(credibility_base * p for p in probability_band))

    compute = _cost_estimate(prize, "compute_cost_estimate")
    model = _cost_estimate(prize, "model_cost_estimate")
    cost = _bands(*(compute[index] + model[index] for index in range(3)))

    ev_per_dollar = {
        key: round((cash[key] + credibility[key]) / max(cost[key], 1.0), 6) for key in ("low", "mid", "high")
    }

    information_gain, information_rationale = _information_gain(prize, progress)
    multiplier, multiplier_rationale = _multiplier(prize)
    bucket = _bucket(prize)
    priority = 0.0 if bucket == "excluded" else ev_per_dollar["mid"] * multiplier * (0.5 + 0.5 * information_gain)

    rationale = [
        f"probability category {probability} (mid {probability_band[1]:g})",
        f"status {status or 'unknown'} keeps {status_factor:g} of the advertised cash",
        f"credibility-equivalent base ${credibility_base:,.0f} from publication/commercial/transfer categories",
        f"attempt cost band ${cost['low']:,.2f}-${cost['high']:,.2f}",
        f"value multiplier {multiplier:.3g}",
    ]
    rationale.extend(multiplier_rationale)
    rationale.extend(information_rationale)
    if bucket == "excluded":
        rationale.append("excluded from planning by research_priority or status")

    return {
        "prize_id": _text(prize.get("id")),
        "name": _text(prize.get("name")),
        "plugin": _text(prize.get("plugin")) or None,
        "admission": _admission(prize),
        "cash_ev_usd": cash,
        "credibility_ev_usd": credibility,
        "cost_usd": cost,
        "ev_per_dollar": ev_per_dollar,
        "information_gain": information_gain,
        "priority_score": round(priority, 6),
        "bucket": bucket,
        "rationale": rationale,
    }


def rank(prizes, progress_by_id: dict | None = None) -> list[dict]:
    """Score every prize and sort best first; excluded prizes always come last."""
    progress_by_id = progress_by_id if isinstance(progress_by_id, dict) else {}
    scored = []
    for prize in prizes if isinstance(prizes, (list, tuple)) else []:
        if not isinstance(prize, dict):
            continue
        prize_id = _text(prize.get("id"))
        scored.append(score_prize(prize, progress=progress_by_id.get(prize_id)))
    scored.sort(key=lambda row: (row["bucket"] == "excluded", -row["priority_score"], row["prize_id"]))
    return scored


def allocate(
    prizes,
    *,
    allowance_usd: float,
    minutes: float,
    moonshot_share: float = 0.2,
    max_share: float = 0.5,
    progress_by_id: dict | None = None,
) -> dict:
    """Plan an allowance across ready prizes. Deterministic; spends nothing.

    The allowance is split ``1 - moonshot_share`` / ``moonshot_share`` between the
    measurable-progress and moonshot buckets, then shared inside each bucket in
    proportion to ``priority_score * information_gain``. No prize takes more than
    ``max_share`` of the whole allowance. Money with nowhere sensible to go stays in
    ``unallocated_usd`` rather than being pushed at a weak candidate.
    """
    allowance = _finite(allowance_usd, 0.0)
    total_minutes = max(0.0, _finite(minutes, 0.0))
    moonshot_share = min(1.0, max(0.0, _finite(moonshot_share, 0.2)))
    max_share = min(1.0, max(0.0, _finite(max_share, 0.5)))
    scored = rank(prizes, progress_by_id)
    if allowance <= 0:
        return {
            "allocations": [],
            "unallocated_usd": round(max(0.0, allowance), 2),
            "notes": ["allowance is zero or negative; nothing planned"],
        }

    notes = []
    eligible = []
    for row in scored:
        if row["bucket"] == "excluded":
            continue
        if row["admission"] != "ready":
            notes.append(f"{row['prize_id']}: skipped, admission {row['admission']}")
            continue
        eligible.append(row)

    cap = allowance * max_share
    pools = {
        "measurable-progress": allowance * (1.0 - moonshot_share),
        "moonshot": allowance * moonshot_share,
    }
    shares: dict[str, float] = {}
    for bucket, pool in pools.items():
        members = [row for row in eligible if row["bucket"] == bucket]
        if not members:
            notes.append(f"no ready {bucket} prize; ${pool:.2f} left unallocated")
            continue
        weights = {row["prize_id"]: row["priority_score"] * row["information_gain"] for row in members}
        total_weight = sum(weights.values())
        if total_weight <= 0:
            notes.append(f"no positive-priority {bucket} prize; ${pool:.2f} left unallocated")
            continue
        for row in members:
            share = pool * weights[row["prize_id"]] / total_weight
            if share > cap:
                notes.append(f"{row['prize_id']}: capped at {max_share:.0%} of the allowance")
                share = cap
            shares[row["prize_id"]] = share

    allocations = []
    for row in eligible:
        usd = round(shares.get(row["prize_id"], 0.0), 2)
        if usd <= 0:
            continue
        slot_minutes = int(round(total_minutes * usd / allowance))
        allocations.append(
            {
                "prize_id": row["prize_id"],
                "plugin": row["plugin"],
                "usd": usd,
                "minutes": max(1, slot_minutes) if total_minutes > 0 else 0,
                "bucket": row["bucket"],
                "reason": (
                    f"priority {row['priority_score']:.4g}, information gain {row['information_gain']:.2g}, "
                    f"{row['bucket']} bucket"
                ),
            }
        )

    spent = sum(item["usd"] for item in allocations)
    return {
        "allocations": allocations,
        "unallocated_usd": round(max(0.0, allowance - spent), 2),
        "notes": notes,
    }


def load_prizes(root) -> list[dict]:
    """Registry prizes for ``root``, or ``[]`` when the registry module or file is absent.

    Imported lazily so this module stays usable (and testable) without ``prize_registry``.
    """
    try:
        import prize_registry
    except ImportError:
        return []
    try:
        snapshot = prize_registry.snapshot(root)
    except Exception:  # noqa: BLE001 - a broken or missing registry must not break scoring
        return []
    prizes = snapshot.get("prizes") if isinstance(snapshot, dict) else None
    return [prize for prize in prizes if isinstance(prize, dict)] if isinstance(prizes, list) else []
