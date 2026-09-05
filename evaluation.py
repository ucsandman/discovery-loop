"""Paired evaluation and honest dataset classification for research runs.

All comparisons use the problem plugin's score function, whose convention is
that larger is better.  Raw solver values remain in the evidence so results can
be independently checked against the plugin verifier.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict


def build_matrix(targets, seed_count, base_seed=10_000):
    """Return the target/seed matrix shared by an incumbent and candidate."""
    if isinstance(seed_count, bool) or not isinstance(seed_count, int) or seed_count < 1:
        raise ValueError("seed_count must be a positive integer")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int):
        raise ValueError("base_seed must be an integer")
    targets = list(targets)
    if not targets:
        raise ValueError("at least one target is required")
    if len(set(targets)) != len(targets):
        raise ValueError("targets must be unique")
    return [
        {"target": target, "seed": base_seed + seed_index} for seed_index in range(seed_count) for target in targets
    ]


def build_manifest(problem, name=None):
    """Describe development, confirmation and sealed data without overstating it.

    Explicit plugin splits win.  Legacy TARGETS are deterministically divided
    into development and validation, but both are labelled previously exposed.
    A plugin HOLDOUT remains separate from prompts, while being disclosed as a
    reusable confirmation set rather than a never-touched release test.
    """
    targets = list(getattr(problem, "TARGETS", ()))
    development = list(getattr(problem, "DEVELOPMENT_TARGETS", getattr(problem, "DEVELOPMENT", ())))
    validation = list(getattr(problem, "VALIDATION_TARGETS", getattr(problem, "VALIDATION", ())))
    holdout = list(getattr(problem, "HOLDOUT", ()))
    # Existing plugins historically exposed every TARGET as development.  When
    # they have no separate holdout, carve a stable validation fold while
    # explicitly retaining its previously-exposed classification.
    if development == targets and not validation and not holdout and len(targets) >= 2:
        development = []
    if not development and not validation:
        if len(targets) < 2:
            development = targets
        else:
            validation_indexes = set(range(4, len(targets), 5)) or {len(targets) - 1}
            validation = [target for index, target in enumerate(targets) if index in validation_indexes]
            development = [target for index, target in enumerate(targets) if index not in validation_indexes]
    elif not development:
        validation_set = set(validation)
        development = [target for target in targets if target not in validation_set]
    elif not validation:
        development_set = set(development)
        validation = [target for target in targets if target not in development_set]

    release_holdout = list(getattr(problem, "RELEASE_HOLDOUT", ()))
    confirmation = holdout or validation
    _require_disjoint("development", development, "confirmation", confirmation)
    _require_disjoint("development", development, "release_holdout", release_holdout)
    _require_disjoint("confirmation", confirmation, "release_holdout", release_holdout)

    if holdout:
        classification = "reused_holdout_confirmation"
        limitations = [
            "The confirmation targets are excluded from generation prompts.",
            "This holdout has existed in the checkout and may have been used in earlier post-hoc checks; it is not a sealed generalization test.",
        ]
    else:
        classification = "previously_exposed_benchmark_validation"
        limitations = [
            "Development and validation targets come from the legacy visible benchmark and may have influenced earlier model runs.",
            "Confirmation on this split measures repeatability on known benchmark data, not unseen generalization.",
        ]
    if release_holdout:
        limitations.append(
            "Newly acquired release targets remain sealed and are not evaluated during routine discovery."
        )
    else:
        limitations.append(
            "No newly acquired sealed release set is available; no unseen-performance claim can be made."
        )

    return {
        "problem": name or getattr(problem, "NAME", None),
        "development": development,
        "validation": validation,
        "confirmation": confirmation,
        "release_holdout": release_holdout,
        "classification": classification,
        "previously_exposed": sorted(set(development + validation)),
        "limitations": limitations,
    }


def score_rows(problem, records, rows):
    """Attach finite, higher-is-better scores to independently checked rows."""
    scored = []
    for row in rows:
        item = dict(row)
        failed = bool(item.get("error")) or "value" not in item
        score = problem.FAIL_SCORE if failed else problem.score(item["value"], records.get(item["target"]))
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(float(score)):
            raise ValueError(f"non-finite score for {item.get('target')}/{item.get('seed')}")
        item["score"] = float(score)
        item["failed"] = failed
        scored.append(item)
    return scored


def compare_paired(incumbent_rows, candidate_rows, min_effect, min_seeds=3):
    """Compare exact target/seed pairs using a robust replicated gate."""
    if isinstance(min_effect, bool) or not isinstance(min_effect, (int, float)) or not math.isfinite(min_effect):
        raise ValueError("min_effect must be a finite positive number")
    if min_effect <= 0:
        raise ValueError("min_effect must be a finite positive number")
    if isinstance(min_seeds, bool) or not isinstance(min_seeds, int) or min_seeds < 1:
        raise ValueError("min_seeds must be a positive integer")
    incumbent = _index_rows(incumbent_rows, "incumbent")
    candidate = _index_rows(candidate_rows, "candidate")
    if set(incumbent) != set(candidate):
        missing_candidate = sorted(set(incumbent) - set(candidate))
        missing_incumbent = sorted(set(candidate) - set(incumbent))
        raise ValueError(
            f"paired matrix mismatch: missing candidate={missing_candidate}, missing incumbent={missing_incumbent}"
        )
    seeds_by_target = defaultdict(set)
    for target, seed in incumbent:
        seeds_by_target[target].add(seed)
    seed_sets = list(seeds_by_target.values())
    if any(seeds != seed_sets[0] for seeds in seed_sets[1:]):
        raise ValueError("paired rows do not form a rectangular target/seed matrix")

    pairs = []
    for target, seed in sorted(incumbent, key=lambda key: (str(key[0]), key[1])):
        inc = incumbent[(target, seed)]
        cand = candidate[(target, seed)]
        raw_gain = cand["score"] - inc["score"]
        gain = raw_gain / max(1.0, abs(inc["score"]))
        if not math.isfinite(gain):
            raise ValueError(f"non-finite paired gain for {target}/{seed}")
        pairs.append(
            {
                "target": target,
                "seed": seed,
                "incumbent_value": inc.get("value"),
                "candidate_value": cand.get("value"),
                "incumbent_score": inc["score"],
                "candidate_score": cand["score"],
                "raw_gain": raw_gain,
                "gain": gain,
                "incumbent_failed": bool(inc.get("failed")),
                "candidate_failed": bool(cand.get("failed")),
            }
        )

    gains = [pair["gain"] for pair in pairs]
    incumbent_failures = sum(pair["incumbent_failed"] for pair in pairs)
    candidate_failures = sum(pair["candidate_failed"] for pair in pairs)
    by_seed = defaultdict(list)
    for pair in pairs:
        by_seed[pair["seed"]].append(pair["gain"])
    per_seed = [
        {"seed": seed, "median_gain": statistics.median(seed_gains), "gains": seed_gains}
        for seed, seed_gains in sorted(by_seed.items())
    ]
    median_gain = statistics.median(gains)
    failure_rate_ok = candidate_failures <= incumbent_failures
    replication_ok = len(seed_sets[0]) >= min_seeds
    return {
        "pairs": pairs,
        "gains": gains,
        "per_seed": per_seed,
        "median_gain": median_gain,
        "min_effect": float(min_effect),
        "incumbent_failure_rate": incumbent_failures / len(pairs),
        "candidate_failure_rate": candidate_failures / len(pairs),
        "candidate_failures": candidate_failures,
        "failure_rate_ok": failure_rate_ok,
        "distinct_seeds": len(seed_sets[0]),
        "required_seeds": min_seeds,
        "replication_ok": replication_ok,
        "passes": median_gain >= min_effect and candidate_failures == 0 and failure_rate_ok and replication_ok,
    }


def _index_rows(rows, label):
    index = {}
    for row in rows:
        if "target" not in row or "seed" not in row or "score" not in row:
            raise ValueError(f"{label} row lacks target, seed or score")
        key = (row["target"], row["seed"])
        if key in index:
            raise ValueError(f"duplicate {label} row for {key[0]}/{key[1]}")
        score = row["score"]
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(float(score)):
            raise ValueError(f"non-finite {label} score for {key[0]}/{key[1]}")
        index[key] = dict(row, score=float(score))
    if not index:
        raise ValueError(f"{label} rows are empty")
    return index


def _require_disjoint(left_name, left, right_name, right):
    overlap = sorted(set(left) & set(right))
    if overlap:
        raise ValueError(f"{left_name} and {right_name} overlap: {overlap}")
