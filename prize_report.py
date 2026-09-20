"""Prize hunt summary for the local dashboard (``/prize``).

Everything here is read from files that already exist: ``data/prizes.json`` (operator-curated,
untrusted display data), ``runs/prizes/`` (the registry snapshot and the enable/next control),
``runs/research/*/<plugin>/evidence.json``, ``runs/research/development-history/<plugin>-retro.json``,
``problems/_dead_ends.json`` and ``night.json``. Nothing is fetched, nothing is written, and no
sentence on this page claims a prize was won, claimed or submitted.

``build_prize(root)`` never raises: a checkout with no ``runs/`` directory and no
``data/prizes.json`` gets the same typed shape back with an explanatory ``notices`` entry.

Money board rules (simple, documented, deterministic; every pick is re-derivable by hand from
``prize_scoring.rank`` output and the ``prize_economics`` ledgers):

* highest expected economic opportunity - largest ``score.cash_ev_usd.mid``.
* strongest measurable progress      - largest measured ``best_gain`` in the plugin's ledger.
* cheapest experiment                - smallest ``score.cost_usd.mid`` among admitted prizes.
* largest legitimate prize           - largest ``estimated_usd`` whose status is verified or
                                       probably active (a prize somebody still appears to pay).
* best publication opportunity       - highest ``publication_value`` category.
* best commercial opportunity        - highest ``commercial_value`` category.
* most promising unexplored direction- highest ``priority_score`` among admitted prizes whose
                                       plugin has no recorded candidate yet.

Ties in every rule break on ``priority_score`` and then on prize id, so the board is stable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_state import read_json

DEFAULT_ALLOWANCE_USD = 10.0
DEFAULT_MINUTES = 60
DEFAULT_MOONSHOT_SHARE = 0.2
DEFAULT_MAX_SHARE = 0.5
DISABLED_QUEUE_LABEL = "hypothetical: nightly prize slot disabled"
LINEAGE_ROWS = 10
DISCOVERY_ROWS = 5
# A busy plugin has dozens of idea families. The page shows the ones a reader would act on
# (prize_economics already sorts keep-first, then by best gain) and says how many were left out.
DIRECTION_ROWS = 6
IDEA_CHARS = 200
VALUE_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
PAYABLE_STATUSES = {"verified_active", "probably_active"}

# The real target's size in bits, used only for the scaling extrapolation. These are the public
# parameters of the challenge itself (ECCp-131 is a 131-bit prime field; the funded bounties are
# full-width digests), not an estimate. prize_scaling reads prize["target_bits"] first, and the
# registry schema does not carry the field, so it is supplied here.
REAL_TARGET_BITS = {
    "certicom-eccp-131": 131,
    "certicom-ecc2k-130": 130,
    "certicom-ecc2-131": 131,
    "todd-sha1-collision": 160,
    "todd-sha256-collision": 256,
    "todd-ripemd160-collision": 160,
    "todd-hash160-collision": 160,
    "todd-hash256-collision": 256,
}

MONEY_BOARD_RULES = (
    ("highest_expected_economic_opportunity", "Largest mid-band cash expected value after the status discount."),
    ("strongest_measurable_progress", "Largest gain actually measured by a run on this prize's plugin."),
    ("cheapest_experiment", "Smallest mid-band attempt cost among the prizes this checkout can run."),
    ("largest_legitimate_prize", "Largest advertised amount whose payer still looks active."),
    ("best_publication_opportunity", "Highest publication value category in the registry."),
    ("best_commercial_opportunity", "Highest commercial value category in the registry."),
    ("most_promising_unexplored_direction", "Highest priority score among runnable prizes with no recorded attempt."),
)


def _read(path: Path, default: Any) -> Any:
    try:
        value = read_json(path, default)
    except (OSError, ValueError, TypeError):
        return default
    return value if value is not None else default


def _text(value: Any, limit: int = 400) -> str:
    return str(value)[:limit] if isinstance(value, str) else ""


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _plugin_module(name: str):
    """Import ``problems/<name>/problem.py`` for its display metadata, or return ``None``."""
    if not name:
        return None
    try:
        from problem_loader import load_problem

        return load_problem(name)
    except Exception:  # noqa: BLE001 - a broken or absent plugin must not break the page
        return None


def _non_claims() -> list[dict]:
    """The verbatim non-claim sentences the two prize plugins export, for the page footnote."""
    rows = []
    hash_module = _plugin_module("hash_collision_prize")
    sentence = getattr(hash_module, "NON_CLAIM", None)
    if isinstance(sentence, str) and sentence:
        rows.append({"plugin": "hash_collision_prize", "source": "problem.NON_CLAIM", "sentence": sentence})
    ecc_module = _plugin_module("ecc_prize")
    sentence = getattr(ecc_module, "SUBMIT_NOTE", None)
    if isinstance(sentence, str) and sentence:
        rows.append({"plugin": "ecc_prize", "source": "problem.SUBMIT_NOTE", "sentence": sentence})
    return rows


def _registry(root: Path, notices: list[str]) -> dict:
    """The registry view, falling back to an in-memory snapshot when nothing is cached yet."""
    import prize_registry

    view = prize_registry.registry_view(root)
    if view.get("prizes"):
        return view
    try:
        cached = prize_registry.snapshot(root)
    except Exception as error:  # noqa: BLE001 - an unreadable registry is a notice, not a crash
        notices.append(f"data/prizes.json could not be read: {str(error)[:200]}")
        return view
    control = prize_registry.load_control(root, cached)
    enabled = set(control.get("enabled_ids") or [])
    prizes = []
    for prize in cached.get("prizes", []):
        row = dict(prize)
        row["enabled"] = row.get("id") in enabled
        row["chosen_next"] = row.get("id") == control.get("next_id")
        prizes.append(row)
    notices.append(
        "runs/prizes/registry.json has not been written yet, so this page read data/prizes.json "
        "directly. Run `python prize_registry.py refresh` to cache the snapshot."
    )
    return {
        "source": cached.get("source"),
        "registry_hash": cached.get("registry_hash"),
        "prizes": prizes,
        "control": control,
        "refresh": view.get("refresh") or {"status": "unavailable", "prize_count": 0, "ready_count": 0},
    }


def _evidence_summary(root: Path, problem: str) -> dict:
    """Confirmation/review flags for one plugin, read from every recorded run."""
    summary = {
        "problem": problem,
        "runs": 0,
        "confirmed": 0,
        "publishable": 0,
        "confirmation_runs": 0,
        "latest_run_id": None,
        "latest_status": None,
        "latest_finished_at": None,
    }
    for path in sorted((Path(root) / "runs" / "research").glob(f"*/{problem}/evidence.json")):
        data = _read(path, None)
        if not isinstance(data, dict):
            continue
        summary["runs"] += 1
        if data.get("confirmed") is True:
            summary["confirmed"] += 1
        if data.get("publishable") is True:
            summary["publishable"] += 1
        confirmation = data.get("confirmation")
        if isinstance(confirmation, dict) and confirmation:
            summary["confirmation_runs"] += 1
        summary["latest_run_id"] = _text(data.get("run_id"), 128) or path.parent.parent.name
        summary["latest_status"] = _text(data.get("status"), 60) or None
        summary["latest_finished_at"] = _text(data.get("finished_at"), 40) or None
    return summary


def _next_experiment(root: Path, problem: str, module: Any) -> str:
    """The retro's own next experiment, else the plugin's stated objective, else a plain notice."""
    retro = _read(Path(root) / "runs" / "research" / "development-history" / f"{problem}-retro.json", {})
    text = _text(retro.get("next_experiment") if isinstance(retro, dict) else None, 600).strip()
    if text:
        return text
    prize = getattr(module, "PRIZE", None)
    objective = _text(prize.get("objective") if isinstance(prize, dict) else None, 400).strip()
    if objective:
        return f"No retro on record yet. Start from the plugin's objective: {objective}"
    return "No experiment has been recorded for this prize, and no plugin is bound to it."


def _research_state(book: dict, evidence: dict, min_effect: float) -> str:
    """Six documented states; see the module docstring for what the page shows for each."""
    attempts = book["totals"]["candidates"]
    if attempts == 0:
        return "not-started"
    if evidence["publishable"] or evidence["confirmed"]:
        return "ready-for-review"
    best = _finite(book["totals"]["best_gain"])
    if best is not None and best > min_effect:
        return "progressing" if evidence["confirmation_runs"] else "ready-for-confirmation"
    from prize_economics import STOP_AFTER_ATTEMPTS

    return "stalled" if attempts >= STOP_AFTER_ATTEMPTS else "exploratory"


def _best_candidate(book: dict) -> dict | None:
    best = None
    for row in book.get("candidates") or []:
        gain = _finite(row.get("median_gain"))
        if gain is None:
            continue
        if best is None or gain > best["gain"]:
            best = {
                "run_id": row.get("run_id"),
                "iteration": row.get("iteration"),
                "gain": gain,
                "cost_usd": row.get("cost_usd"),
                "idea": _text(row.get("idea"), IDEA_CHARS),
            }
    return best


def _lineage(book: dict) -> list[dict]:
    rows = [
        {
            "run_id": row.get("run_id"),
            "iteration": row.get("iteration"),
            "gain": _finite(row.get("median_gain")),
            "status": row.get("development_status"),
        }
        for row in book.get("candidates") or []
    ]
    return rows[-LINEAGE_ROWS:]


def _discoveries(book: dict) -> list[dict]:
    rows = [
        {
            "run_id": row.get("run_id"),
            "iteration": row.get("iteration"),
            "gain": _finite(row.get("median_gain")),
            "idea": _text(row.get("idea"), IDEA_CHARS),
        }
        for row in book.get("candidates") or []
        if (_finite(row.get("median_gain")) or 0.0) > 0
    ]
    rows.sort(key=lambda row: (-(row["gain"] or 0.0), str(row["run_id"]), row["iteration"] or 0))
    return rows[:DISCOVERY_ROWS]


def _dead_end_counts(root: Path) -> dict[str, int]:
    entries = _read(Path(root) / "problems" / "_dead_ends.json", [])
    counts: dict[str, int] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        problem = _text(entry.get("problem"), 80) or "general"
        counts[problem] = counts.get(problem, 0) + 1
    return counts


def _scaling(root: Path, prize: dict, module: Any) -> dict | None:
    """A compact scaling read for the board cell, or ``None`` when the prize has no plugin."""
    if not prize.get("plugin"):
        return None
    import prize_scaling

    bits = REAL_TARGET_BITS.get(prize.get("id"))
    subject = {**prize, "target_bits": prize.get("target_bits") or bits}
    try:
        result = prize_scaling.analysis(root, subject, module)
    except Exception as error:  # noqa: BLE001 - a scaling failure is a cell, not a 500
        return {"supported": False, "reason": str(error)[:200], "target_bits": bits, "assumptions": []}
    extrapolation = result.get("extrapolation") or {}
    fit = result.get("fit") or {}
    return {
        "supported": bool(result.get("supported")),
        "reason": result.get("reason"),
        "target_bits": result.get("target_bits"),
        "points": len(result.get("points") or []),
        "point_source": (result.get("points") or [{}])[0].get("source") if result.get("points") else None,
        "beta": fit.get("beta"),
        "r2": fit.get("r2"),
        "verdict": extrapolation.get("verdict"),
        "cpu_years_mid": (extrapolation.get("cpu_years") or {}).get("mid"),
        "usd_mid": (extrapolation.get("usd") or {}).get("mid"),
        "summary": result.get("summary"),
        "assumptions": [note for note in (extrapolation.get("assumptions") or []) if isinstance(note, str)],
    }


def _queue_settings(root: Path) -> dict:
    """The nightly prize block when night.json carries one, else the documented default."""
    schedule = _read(Path(root) / "night.json", {})
    block = schedule.get("prizes") if isinstance(schedule, dict) else None
    if not isinstance(block, dict):
        return {
            "enabled": False,
            "block": None,
            "allowance_usd": DEFAULT_ALLOWANCE_USD,
            "minutes": DEFAULT_MINUTES,
            "moonshot_share": DEFAULT_MOONSHOT_SHARE,
            "max_share": DEFAULT_MAX_SHARE,
            "source": "default",
            "label": DISABLED_QUEUE_LABEL,
        }
    enabled = block.get("enabled") is True
    return {
        "enabled": enabled,
        "block": block,
        "allowance_usd": _finite(block.get("slot_budget_usd")) or DEFAULT_ALLOWANCE_USD,
        "minutes": _finite(block.get("research_minutes")) or _finite(block.get("minutes")) or DEFAULT_MINUTES,
        "moonshot_share": _finite(block.get("moonshot_share")) or DEFAULT_MOONSHOT_SHARE,
        "max_share": _finite(block.get("max_share")) or DEFAULT_MAX_SHARE,
        "source": "night.json prizes block",
        "label": "nightly prize slot enabled" if enabled else DISABLED_QUEUE_LABEL,
    }


def _pick(rows: list[dict], key, *, filter_fn=None) -> dict | None:
    candidates = [row for row in rows if filter_fn is None or filter_fn(row)]
    if not candidates:
        return None
    return max(candidates, key=key)


def _card(row: dict | None, rule: str, why: str) -> dict:
    if not row:
        return {"id": None, "name": None, "rule": rule, "why": "No prize in the registry matches this rule yet."}
    return {"id": row["id"], "name": row["name"], "rule": rule, "why": why}


def _money_board(board: list[dict]) -> dict:
    rules = dict(MONEY_BOARD_RULES)
    priority = lambda row: row["score"]["priority_score"]  # noqa: E731 - tie-break, used five times
    runnable = [row for row in board if row["admission"] == "ready"]

    cash = _pick(board, lambda row: (row["score"]["cash_ev_usd"]["mid"], priority(row), row["id"]))
    if cash and cash["score"]["cash_ev_usd"]["mid"] <= 0:
        cash = None
    progress = _pick(
        board,
        lambda row: (row["performance_improvement_pct"] or 0.0, priority(row), row["id"]),
        filter_fn=lambda row: (row["performance_improvement_pct"] or 0.0) > 0,
    )
    cheap = _pick(runnable, lambda row: (-row["score"]["cost_usd"]["mid"], priority(row), row["id"]))
    largest = _pick(
        board,
        lambda row: (_finite(row["estimated_usd"]) or 0.0, priority(row), row["id"]),
        filter_fn=lambda row: row["status"] in PAYABLE_STATUSES and (_finite(row["estimated_usd"]) or 0.0) > 0,
    )
    publication = _pick(
        board,
        lambda row: (VALUE_ORDER.get(row["publication_value"], 0), priority(row), row["id"]),
        filter_fn=lambda row: VALUE_ORDER.get(row["publication_value"], 0) > 0,
    )
    commercial = _pick(
        board,
        lambda row: (VALUE_ORDER.get(row["commercial_value"], 0), priority(row), row["id"]),
        filter_fn=lambda row: VALUE_ORDER.get(row["commercial_value"], 0) > 0,
    )
    unexplored = _pick(
        runnable,
        lambda row: (priority(row), row["id"]),
        filter_fn=lambda row: row["research_state"] == "not-started",
    )
    return {
        "highest_expected_economic_opportunity": _card(
            cash,
            rules["highest_expected_economic_opportunity"],
            f"mid-band cash expected value ${cash['score']['cash_ev_usd']['mid']:,.2f} after the "
            f"{cash['status']} status discount"
            if cash
            else "",
        ),
        "strongest_measurable_progress": _card(
            progress,
            rules["strongest_measurable_progress"],
            f"a run measured {progress['performance_improvement_pct']:.2f} percent on {progress['plugin']}"
            if progress
            else "",
        ),
        "cheapest_experiment": _card(
            cheap,
            rules["cheapest_experiment"],
            f"mid-band attempt cost ${cheap['score']['cost_usd']['mid']:,.2f}" if cheap else "",
        ),
        "largest_legitimate_prize": _card(
            largest,
            rules["largest_legitimate_prize"],
            f"{largest['advertised_prize']} advertised, status {largest['status']} "
            f"({largest['status_confidence']} confidence)"
            if largest
            else "",
        ),
        "best_publication_opportunity": _card(
            publication,
            rules["best_publication_opportunity"],
            f"publication value {publication['publication_value']}" if publication else "",
        ),
        "best_commercial_opportunity": _card(
            commercial,
            rules["best_commercial_opportunity"],
            f"commercial value {commercial['commercial_value']}" if commercial else "",
        ),
        "most_promising_unexplored_direction": _card(
            unexplored,
            rules["most_promising_unexplored_direction"],
            f"priority score {unexplored['score']['priority_score']:.4g} and no candidate on record"
            if unexplored
            else "",
        ),
    }


def _stub(notice: str) -> dict:
    return {
        "registry": {
            "source": None,
            "registry_hash": None,
            "prizes": [],
            "control": {"schema_version": 1, "enabled_ids": [], "next_id": None, "updated_at": None},
            "refresh": {"status": "unavailable", "prize_count": 0, "ready_count": 0},
        },
        "board": [],
        "queue": {
            "allocations": [],
            "unallocated_usd": 0.0,
            "notes": [],
            "allowance_usd": DEFAULT_ALLOWANCE_USD,
            "minutes": DEFAULT_MINUTES,
            "source": "default",
            "label": DISABLED_QUEUE_LABEL,
        },
        "money_board": {key: _card(None, rule, "") for key, rule in MONEY_BOARD_RULES},
        "economics": {},
        "stop_recommendations": [],
        "intake": [],
        "nightly": {"enabled": False, "block": None},
        "non_claims": _non_claims(),
        "notices": [notice],
    }


def _contract_notices(root: Path, modules: dict) -> list[str]:
    """One notice per installed prize plugin whose PRIZE descriptor fails the contract."""
    try:
        import prize_contract
    except ImportError:
        return []
    notices = []
    try:
        installed = prize_contract.prize_plugins(root)
    except Exception as error:  # noqa: BLE001 - a broken plugin tree is reported, never fatal
        return [f"Prize plugin contracts could not be listed: {str(error)[:200]}"]
    for plugin in installed:
        module = modules.get(plugin)
        if module is None:
            continue
        verdict = prize_contract.validate_prize_plugin(module, root)
        if not verdict.get("ok"):
            problems = ", ".join([*verdict.get("missing", []), *verdict.get("errors", [])])[:300]
            notices.append(f"Plugin {plugin} fails the prize contract: {problems}")
    return notices


def prize_scaling_analysis(root: Path, prize: dict, module) -> dict | None:
    """The full scaling analysis for ``ev_impact`` (the board cell keeps only the summary)."""
    try:
        import prize_scaling
    except ImportError:
        return None
    try:
        return prize_scaling.analysis(root, prize, module)
    except Exception:  # noqa: BLE001 - the cell already reports the failure
        return None


def build_prize(root) -> dict:
    """The whole ``/prize`` payload. Pure read; never raises on an incomplete checkout."""
    try:
        return _build(Path(root))
    except Exception as error:  # noqa: BLE001 - the dashboard must still serve the page
        return _stub(f"The prize summary is unavailable in this checkout: {str(error)[:300]}")


def _build(root: Path) -> dict:
    import prize_economics
    import prize_intake
    import prize_scoring

    notices: list[str] = []
    registry = _registry(root, notices)
    prizes = [prize for prize in registry.get("prizes") or [] if isinstance(prize, dict)]
    if not prizes:
        stub = _stub("No prize registry is present in this checkout (data/prizes.json is missing or empty).")
        stub["registry"] = registry
        stub["notices"] = [*notices, *stub["notices"]]
        return stub

    plugins = sorted({_text(prize.get("plugin"), 80) for prize in prizes if prize.get("plugin")})
    ledgers = {plugin: prize_economics.ledger(root, plugin) for plugin in plugins}
    evidence = {plugin: _evidence_summary(root, plugin) for plugin in plugins}
    modules = {plugin: _plugin_module(plugin) for plugin in plugins}
    notices.extend(_contract_notices(root, modules))
    dead_ends = _dead_end_counts(root)
    progress_by_id = {
        prize["id"]: {
            "problem": prize["plugin"],
            "best_gain": ledgers[prize["plugin"]]["totals"]["best_gain"],
            "attempts": ledgers[prize["plugin"]]["totals"]["candidates"],
        }
        for prize in prizes
        if prize.get("plugin") in ledgers and prize.get("id")
    }
    scores = {row["prize_id"]: row for row in prize_scoring.rank(prizes, progress_by_id)}

    board = []
    for prize in prizes:
        prize_id = _text(prize.get("id"), 80)
        plugin = _text(prize.get("plugin"), 80) or None
        book = ledgers.get(plugin) or {
            "totals": {"candidates": 0, "best_gain": None, "model_usd": 0.0, "local_compute_usd": 0.0},
            "candidates": [],
        }
        seen = evidence.get(plugin) or _evidence_summary(root, plugin or "__none__")
        state = _research_state(book, seen, prize_economics.DEFAULT_MIN_EFFECT) if plugin else "not-started"
        best_gain = _finite(book["totals"]["best_gain"])
        board.append(
            {
                "id": prize_id,
                "name": _text(prize.get("name"), 200),
                "category": _text(prize.get("category"), 40),
                "plugin": plugin,
                "advertised_prize": _text(prize.get("advertised_prize"), 200),
                "estimated_usd": prize.get("estimated_usd"),
                "status": _text(prize.get("status"), 40),
                "status_confidence": _text(prize.get("status_confidence"), 20),
                "last_verified": prize.get("last_verified"),
                "source_url": _text(prize.get("source_url"), 400),
                "publication_value": _text(prize.get("publication_value"), 20),
                "commercial_value": _text(prize.get("commercial_value"), 20),
                "admission": _text(prize.get("admission"), 40) or "needs_setup",
                "admission_reason": prize.get("admission_reason"),
                "enabled": prize.get("enabled") is True,
                "chosen_next": prize.get("chosen_next") is True,
                "score": scores.get(prize_id) or prize_scoring.score_prize(prize),
                "research_state": state,
                "best_candidate": _best_candidate(book) if plugin else None,
                "performance_improvement_pct": round(best_gain * 100, 4) if best_gain is not None else None,
                "scaling": _scaling(root, prize, modules.get(plugin)),
                "ev_impact": prize_economics.ev_impact(
                    {"scaling": prize_scaling_analysis(root, prize, modules.get(plugin))}, best_gain or 0.0
                )["sentence"]
                if plugin
                else None,
                "research_spend": {
                    "model_usd": book["totals"].get("model_usd", 0.0),
                    "local_compute_usd": book["totals"].get("local_compute_usd", 0.0),
                },
                "attempts": book["totals"].get("candidates", 0),
                "dead_ends": dead_ends.get(plugin or "", 0),
                "recent_discoveries": _discoveries(book) if plugin else [],
                "lineage": _lineage(book) if plugin else [],
                "ready_for_confirmation": bool(
                    plugin
                    and best_gain is not None
                    and best_gain > prize_economics.DEFAULT_MIN_EFFECT
                    and not seen["confirmation_runs"]
                ),
                "ready_for_human_review": bool(plugin and (seen["confirmed"] or seen["publishable"])),
                "next_experiment": _next_experiment(root, plugin, modules.get(plugin))
                if plugin
                else ("No plugin is bound to this prize, so there is no experiment to run here."),
            }
        )

    settings = _queue_settings(root)
    plan = prize_scoring.allocate(
        prizes,
        allowance_usd=settings["allowance_usd"],
        minutes=settings["minutes"],
        moonshot_share=settings["moonshot_share"],
        max_share=settings["max_share"],
        progress_by_id=progress_by_id,
    )
    queue = {
        **plan,
        "allowance_usd": settings["allowance_usd"],
        "minutes": settings["minutes"],
        "source": settings["source"],
        "label": settings["label"],
    }

    economics = {}
    stops: list[dict] = []
    for plugin, book in ledgers.items():
        economics[plugin] = {
            "problem": book["problem"],
            "runs": book["runs"],
            "totals": book["totals"],
            "directions": book["directions"][:DIRECTION_ROWS],
            "directions_total": len(book["directions"]),
            "assumptions": book["assumptions"],
        }
        stops.extend(prize_economics.stop_recommendations(book))

    try:
        intake = prize_intake.list_candidates(root)
    except Exception as error:  # noqa: BLE001 - an unreadable intake directory is a notice
        intake = []
        notices.append(f"Intake candidates could not be listed: {str(error)[:200]}")

    if not any(row["attempts"] for row in board):
        notices.append("No research run has been recorded for any bound prize plugin yet.")

    return {
        "registry": registry,
        "board": board,
        "queue": queue,
        "money_board": _money_board(board),
        "economics": economics,
        "stop_recommendations": stops,
        "intake": intake,
        "nightly": {"enabled": settings["enabled"], "block": settings["block"]},
        "non_claims": _non_claims(),
        "notices": notices,
    }
