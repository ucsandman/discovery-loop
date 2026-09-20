"""Fit the measured cost ladder of a prize plugin and extrapolate it to the real target.

The point of this module is to make infeasibility visible rather than hopeful. It fits
``log2(seconds) = alpha + beta * bits`` over the ladder instances the lab actually ran,
compares ``beta`` with the theoretical 0.5 of a rho / birthday search, and then says in
plain words what the real target would cost at that scaling.

Nothing here is fetched and nothing is written; ``ladder_points`` only reads evidence
files the research loop already produced, plus the plugin's committed ``records.json``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from research_state import read_json

MODEL = "log2(seconds) = alpha + beta*bits"
# Pollard rho and the birthday bound both cost ~2^(bits/2) operations.
THEORY_BETA = 0.5
SECONDS_PER_YEAR = 365.25 * 24 * 3600.0
SECONDS_PER_HOUR = 3600.0
# 2**512 is about 1.3e154: still a finite float, so the JSON writers (allow_nan=False) stay happy.
MAX_LOG2_SECONDS = 512.0
MIN_LOG2_SECONDS = -60.0
DEFAULT_CPU_COST_PER_HOUR = 0.05
DEFAULT_GPU_COST_PER_HOUR = 1.0
INFEASIBLE_USD = 1e6
INFEASIBLE_CPU_YEARS = 100.0
EXPENSIVE_USD = 1000.0
EXPENSIVE_CPU_YEARS = 1.0
MIN_POINTS = 3


class ScalingError(ValueError):
    """The supplied ladder cannot support a scaling fit."""


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _bits(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _pow2(exponent: float) -> tuple[float, bool]:
    clamped = min(MAX_LOG2_SECONDS, max(MIN_LOG2_SECONDS, exponent))
    return 2.0**clamped, clamped != exponent


def fit_scaling(points) -> dict:
    """Least squares of log2(seconds) on bits over >= 3 ladder points with >= 2 distinct bits."""
    cleaned = []
    for point in points if isinstance(points, (list, tuple)) else []:
        if not isinstance(point, dict):
            continue
        bits = _bits(point.get("bits"))
        seconds = _finite(point.get("seconds"))
        if bits is None or seconds is None or seconds <= 0:
            continue
        cleaned.append((float(bits), math.log2(seconds)))
    if len(cleaned) < MIN_POINTS:
        raise ScalingError(f"a scaling fit needs at least {MIN_POINTS} usable points, got {len(cleaned)}")
    if len({x for x, _ in cleaned}) < 2:
        raise ScalingError("a scaling fit needs at least two distinct bit sizes")

    count = len(cleaned)
    mean_x = sum(x for x, _ in cleaned) / count
    mean_y = sum(y for _, y in cleaned) / count
    sxx = sum((x - mean_x) ** 2 for x, _ in cleaned)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in cleaned)
    beta = sxy / sxx
    alpha = mean_y - beta * mean_x
    residuals = [y - (alpha + beta * x) for x, y in cleaned]
    ss_res = sum(value**2 for value in residuals)
    ss_tot = sum((y - mean_y) ** 2 for _, y in cleaned)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    residual_sd = math.sqrt(ss_res / (count - 2)) if count > 2 else 0.0
    beta_se = residual_sd / math.sqrt(sxx) if sxx > 0 else 0.0

    return {
        "model": MODEL,
        "alpha": round(alpha, 6),
        "beta": round(beta, 6),
        "beta_se": round(beta_se, 6),
        "r2": round(r2, 6),
        "n_points": count,
        "residual_sd": round(residual_sd, 6),
        "beta_vs_theory": {
            "theory_beta": THEORY_BETA,
            "observed_beta": round(beta, 6),
            "ratio": round(beta / THEORY_BETA, 6),
            "note": (
                "Theory for a rho or birthday search is beta = 0.5 (seconds scale as 2^(bits/2)). "
                "A larger observed beta means this implementation loses ground as the instance grows."
            ),
        },
    }


def _verdict(usd_mid: float, cpu_years_mid: float) -> str:
    if usd_mid > INFEASIBLE_USD or cpu_years_mid > INFEASIBLE_CPU_YEARS:
        return "infeasible"
    if usd_mid > EXPENSIVE_USD or cpu_years_mid > EXPENSIVE_CPU_YEARS:
        return "expensive"
    return "feasible"


def extrapolate(
    fit: dict,
    target_bits: int,
    *,
    cpu_cost_per_hour: float = DEFAULT_CPU_COST_PER_HOUR,
    gpu_speedup: float | None = None,
    gpu_cost_per_hour: float = DEFAULT_GPU_COST_PER_HOUR,
) -> dict:
    """Project one fit onto ``target_bits`` and say, in one sentence, what it would cost."""
    if not isinstance(fit, dict):
        raise ScalingError("extrapolate needs the dict returned by fit_scaling")
    alpha = _finite(fit.get("alpha"))
    beta = _finite(fit.get("beta"))
    bits = _bits(target_bits)
    if alpha is None or beta is None:
        raise ScalingError("fit is missing a finite alpha/beta")
    if bits is None:
        raise ScalingError("target_bits must be a positive integer")
    beta_se = _finite(fit.get("beta_se")) or 0.0
    residual_sd = _finite(fit.get("residual_sd")) or 0.0

    exponents = {
        "low": alpha + (beta - 2 * beta_se) * bits - residual_sd,
        "mid": alpha + beta * bits,
        "high": alpha + (beta + 2 * beta_se) * bits + residual_sd,
    }
    # No band may promise less work than a rho / birthday search: the fit's own intercept at beta = 0.5
    # is the optimistic bound, so a band below it would be an artefact of the fit, not a cheaper attack.
    theory_floor = alpha + THEORY_BETA * bits
    floored = sorted(key for key, exponent in exponents.items() if exponent < theory_floor)
    exponents = {key: max(exponent, theory_floor) for key, exponent in exponents.items()}
    clamped = False
    seconds = {}
    for key, exponent in exponents.items():
        value, was_clamped = _pow2(exponent)
        seconds[key] = value
        clamped = clamped or was_clamped

    cpu_cost_per_hour = max(0.0, _finite(cpu_cost_per_hour) or 0.0)
    cpu_years = {key: value / SECONDS_PER_YEAR for key, value in seconds.items()}
    usd = {key: value / SECONDS_PER_HOUR * cpu_cost_per_hour for key, value in seconds.items()}

    assumptions = [
        f"Scaling model {MODEL} fitted on {fit.get('n_points')} measured ladder points (r2 {fit.get('r2')}).",
        "The band comes from beta +/- 2 standard errors and one residual standard deviation; "
        "it is fit uncertainty only, not algorithmic risk.",
        f"CPU cost assumed at ${cpu_cost_per_hour:g} per core-hour on one core; no memory or storage cost included.",
        "Single-threaded extrapolation: real parallel work divides wall time, not total core-hours or dollars.",
    ]
    if floored:
        assumptions.append(
            f"The {', '.join(floored)} band{'s were' if len(floored) > 1 else ' was'} raised to the rho / birthday "
            f"theory bound alpha + {THEORY_BETA:g}*bits (2^{theory_floor:.4g} seconds): the fit "
            f"(beta {beta:.3g}) extrapolates below the generic attack, and no band may claim less work than that."
        )
    if clamped:
        assumptions.append(
            f"At least one band exponent was clamped to the representable range "
            f"[{MIN_LOG2_SECONDS:g}, {MAX_LOG2_SECONDS:g}] in log2 seconds; read those ends as 'beyond estimation'."
        )

    gpu_years = None
    gpu_usd = None
    speedup = _finite(gpu_speedup)
    if speedup is not None and speedup > 0:
        gpu_cost_per_hour = max(0.0, _finite(gpu_cost_per_hour) or 0.0)
        gpu_years = {key: value / speedup / SECONDS_PER_YEAR for key, value in seconds.items()}
        gpu_usd = {key: value / speedup / SECONDS_PER_HOUR * gpu_cost_per_hour for key, value in seconds.items()}
        assumptions.append(
            f"GPU figures use an assumed speedup of {speedup:g}x over this CPU baseline at "
            f"${gpu_cost_per_hour:g} per GPU-hour. The speedup is assumed, not measured here."
        )

    verdict = _verdict(usd["mid"], cpu_years["mid"])
    cores = cpu_years["mid"]
    required_hardware = f"about {cores:.3g} CPU cores running continuously for one year"
    summary = (
        f"At the measured 2^({beta:.3g}*bits) scaling, {bits} bits needs about {cpu_years['mid']:.3g} CPU-years "
        f"(range {cpu_years['low']:.3g} to {cpu_years['high']:.3g}), about US${usd['mid']:.3g} at "
        f"${cpu_cost_per_hour:g}/core-hour: {verdict}."
    )
    if verdict == "infeasible":
        summary += " A change of economics, not tuning, would be required."

    return {
        "target_bits": bits,
        "seconds": _round_band(seconds),
        "cpu_years": _round_band(cpu_years),
        "gpu_years": _round_band(gpu_years) if gpu_years else None,
        "gpu_usd": _round_band(gpu_usd) if gpu_usd else None,
        "usd": _round_band(usd),
        "required_hardware": required_hardware,
        "verdict": verdict,
        "summary": summary,
        "assumptions": assumptions,
    }


def _round_band(band: dict | None) -> dict | None:
    if not band:
        return None
    return {key: float(f"{value:.6g}") for key, value in band.items()}


def _family(function) -> str | None:
    """Normalise a hash-function label to its cost family: sha256/hash256 -> sha256, ripemd160/hash160 -> ripemd160.

    The plugin's metadata labels are prose ("HASH160 = RIPEMD-160(SHA-256(x))"), so only the leading
    token names the function; everything after it is the definition and must not join the label.

    A reduced-round variant runs in pure Python and costs ~100x a hashlib call, so it is its own family
    and never enters a full-digest extrapolation."""
    if not isinstance(function, str) or not function:
        return None
    leading = re.match(r"[a-z0-9-]+", function.strip().lower())
    if leading is None:
        return None
    label = "".join(ch for ch in leading.group(0) if ch.isalnum())
    if not label:
        return None
    if label.startswith("sha256reduced") or "reduced" in label:
        return "sha256-reduced"
    if label in ("sha256", "hash256", "sha256d", "sha256sha256"):
        return "sha256"
    if label in ("ripemd160", "hash160", "ripemd160sha256"):
        return "ripemd160"
    return label


def _records_index(root, problem: str) -> dict[str, dict]:
    """``{target_name: {"bits", "baseline_seconds"}}`` from ``problems/<problem>/records.json``.

    Both shapes the prize plugins may ship are accepted (a list of records carrying ``name``,
    or a mapping keyed by target name), and a missing or malformed file yields ``{}``.
    """
    path = Path(root) / "problems" / str(problem) / "records.json"
    try:
        data = read_json(path, None)
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("instances"), dict):
        data = data["instances"]  # ecc_prize: "targets" holds the split lists, "instances" the records
    elif isinstance(data, dict) and isinstance(data.get("targets"), (dict, list)):
        data = data["targets"]
    rows: list[tuple[str, dict]] = []
    if isinstance(data, dict):
        rows = [(str(name), row) for name, row in data.items() if isinstance(row, dict)]
    elif isinstance(data, list):
        rows = [(str(row.get("name")), row) for row in data if isinstance(row, dict) and row.get("name")]
    index = {}
    for name, row in rows:
        reference = row.get("reference") if isinstance(row.get("reference"), dict) else {}
        index[name] = {
            "bits": _bits(row.get("bits")),
            "baseline_seconds": _finite(reference.get("baseline_seconds")),
            "family": _family(row.get("function")),
        }
    return index


def _incumbent_rows(evidence: Any) -> list[dict]:
    development = evidence.get("development") if isinstance(evidence, dict) else None
    rows = development.get("incumbent") if isinstance(development, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def ladder_points(root, problem: str, family: str | None = None) -> list[dict]:
    """Measured seconds-per-bits points for ``problem``'s current incumbent.

    Reads ``runs/research/*/<problem>/evidence.json`` development incumbent rows (the only
    rows the loop stamps with ``secs``); the newest run wins per target. When no run exists,
    falls back to the committed ``records.json`` reference baselines, labelled
    ``source: baseline_reference``.
    """
    index = _records_index(root, problem)
    if family is not None:
        index = {name: row for name, row in index.items() if row.get("family") == family}
    measured: dict[str, dict] = {}
    research_root = Path(root) / "runs" / "research"
    for evidence_path in sorted(research_root.glob(f"*/{problem}/evidence.json")):
        try:
            evidence = read_json(evidence_path, None)
        except (OSError, ValueError):
            continue
        if not isinstance(evidence, dict):
            continue
        run_id = evidence.get("run_id")
        run_id = str(run_id) if isinstance(run_id, str) else evidence_path.parent.parent.name
        for row in _incumbent_rows(evidence):
            target = row.get("target")
            seconds = _finite(row.get("secs"))
            bits = index.get(str(target), {}).get("bits")
            if not isinstance(target, str) or bits is None or seconds is None or seconds <= 0:
                continue
            if row.get("failed") is True:
                continue
            measured[target] = {
                "target": target,
                "bits": bits,
                "seconds": round(seconds, 6),
                "source": "measured",
                "run_id": run_id,
            }
    if measured:
        return sorted(measured.values(), key=lambda point: (point["bits"], point["target"]))

    fallback = []
    for target, row in index.items():
        if row["bits"] is None or row["baseline_seconds"] is None or row["baseline_seconds"] <= 0:
            continue
        fallback.append(
            {
                "target": target,
                "bits": row["bits"],
                "seconds": round(row["baseline_seconds"], 6),
                "source": "baseline_reference",
                "run_id": None,
            }
        )
    return sorted(fallback, key=lambda point: (point["bits"], point["target"]))


def _metadata_entry(prize: dict, plugin_module: Any) -> dict:
    metadata = getattr(plugin_module, "PRIZE_TARGET_METADATA", None)
    if isinstance(metadata, dict):
        entry = metadata.get(prize.get("id"))
        if entry is None and isinstance(metadata.get("bounties"), dict):
            entry = metadata["bounties"].get(prize.get("id"))  # hash_collision_prize nests its bounties
        if isinstance(entry, dict):
            return entry
    return {}


def _target_bits(prize: dict, plugin_module: Any) -> int | None:
    bits = _bits(prize.get("target_bits"))
    if bits is not None:
        return bits
    return _bits(_metadata_entry(prize, plugin_module).get("bits"))


def analysis(root, prize: dict, plugin_module: Any = None) -> dict:
    """Ladder points + fit + extrapolation for one prize's real target.

    Degrades rather than raising: an unknown target size, a plugin with no ladder or a
    ladder too short to fit all come back as ``supported: False`` with a reason.
    """
    prize = prize if isinstance(prize, dict) else {}
    prize_id = prize.get("id") if isinstance(prize.get("id"), str) else ""
    problem = prize.get("plugin") if isinstance(prize.get("plugin"), str) else ""
    result = {
        "prize_id": prize_id,
        "problem": problem or None,
        "real_target": prize.get("real_target") if isinstance(prize.get("real_target"), str) else None,
        "target_bits": None,
        "points": [],
        "fit": None,
        "extrapolation": None,
        "supported": False,
        "reason": None,
        "summary": None,
    }
    if not problem:
        result["reason"] = "prize has no bound plugin; there is no ladder to measure"
        return result
    bits = _target_bits(prize, plugin_module)
    result["target_bits"] = bits
    if bits is None:
        result["reason"] = "the prize's real target size in bits is not recorded"
        return result
    descriptor = getattr(plugin_module, "PRIZE", None)
    if (
        result["real_target"] is None
        and isinstance(descriptor, dict)
        and isinstance(descriptor.get("real_target"), str)
    ):
        result["real_target"] = descriptor["real_target"]
    family = _family(_metadata_entry(prize, plugin_module).get("function"))
    result["ladder_family"] = family
    points = ladder_points(root, problem, family)
    result["points"] = points
    try:
        fit = fit_scaling(points)
    except ScalingError as error:
        result["reason"] = str(error)
        return result
    result["fit"] = fit
    extrapolation = extrapolate(fit, bits)
    result["extrapolation"] = extrapolation
    result["supported"] = True
    result["summary"] = extrapolation["summary"]
    return result
