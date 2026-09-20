"""The contract a prize research plugin must satisfy before its results mean anything.

A prize plugin declares a ``PRIZE`` descriptor naming what it optimizes, what a candidate writes,
which baseline it is measured against, which targets are development and which are holdout, and the
independent verifier that recomputes the claim. The checks here are structural and offline: they
read the plugin's ``problem.py`` source with :mod:`ast` and never import generated solver code.

The isolation rule this module enforces is the one that makes a prize result auditable at all:
``problem.evaluate`` must not reach for ``seed_solver`` or a generated ``solver`` module. A
candidate that can call the code being measured can verify itself.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent

PRIZE_FIELDS = (
    "objective",
    "candidate_artifact",
    "baseline",
    "development_benchmark",
    "holdout_benchmark",
    "independent_verifier",
    "fitness_metrics",
    "real_target",
    "prize_registry_id",
    "promotion_threshold",
    "estimated_scaling",
    "publication_requirements",
    "submission_requirements",
)
TEXT_FIELDS = (
    "objective",
    "candidate_artifact",
    "baseline",
    "independent_verifier",
    "real_target",
    "prize_registry_id",
    "estimated_scaling",
    "publication_requirements",
    "submission_requirements",
)
LIST_FIELDS = ("development_benchmark", "holdout_benchmark")
COLLECTION_FIELDS = ("fitness_metrics",)
REQUIRED_MEMBERS = ("TARGETS", "evaluate", "score", "beats", "validate_release", "DEFAULTS")
# Names that problem.evaluate may never touch: the measured baseline and the generated candidate.
FORBIDDEN_IN_EVALUATE = ("seed_solver", "solver")
VERIFIER_RE = re.compile(r"problems/([a-z][a-z0-9_]*)/verify\.py\Z")
PROMOTION_KEYS = ("min_effect", "seed_count", "holdout_required")


def _plugin_name(module):
    name = getattr(module, "__name__", "") or ""
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "problems":
        return parts[1]
    source = getattr(module, "__file__", None)
    return Path(source).parent.name if source else None


def _evaluate_references(source, errors):
    """Names and attributes reachable from the module-level ``evaluate`` function."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        errors.append(f"problem.py does not parse: {exc}")
        return set(), set()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
    used = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != "evaluate":
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                used.add(child.id)
            elif isinstance(child, ast.Attribute):
                used.add(child.attr)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                names = [alias.name.split(".")[-1] for alias in child.names]
                used.update(names)
                imported.update(names)
    return imported, used


def _check_promotion_threshold(value, errors):
    if not isinstance(value, dict):
        errors.append("promotion_threshold must be an object")
        return
    unknown = sorted(set(value) - set(PROMOTION_KEYS))
    if unknown:
        errors.append(f"promotion_threshold has unsupported keys: {', '.join(unknown)}")
    effect = value.get("min_effect")
    if isinstance(effect, bool) or not isinstance(effect, (int, float)) or not 0 < float(effect) < 1:
        errors.append("promotion_threshold.min_effect must be a number between 0 and 1")
    seeds = value.get("seed_count")
    if isinstance(seeds, bool) or not isinstance(seeds, int) or seeds < 1:
        errors.append("promotion_threshold.seed_count must be an integer of at least 1")
    if value.get("holdout_required") is not True:
        errors.append("promotion_threshold.holdout_required must be true")


def validate_prize_plugin(module, root=ROOT):
    """Check one loaded plugin module against the prize contract.

    Returns ``{"ok": bool, "missing": [...], "errors": [...]}``. ``missing`` names absent PRIZE
    fields and absent plugin members; ``errors`` holds everything that is present but wrong.
    """
    root = Path(root)
    missing = []
    errors = []
    for member in REQUIRED_MEMBERS:
        if not hasattr(module, member):
            missing.append(member)
    descriptor = getattr(module, "PRIZE", None)
    if not isinstance(descriptor, dict):
        missing.append("PRIZE")
        return {"ok": False, "missing": sorted(missing), "errors": errors}

    for field in PRIZE_FIELDS:
        if field not in descriptor:
            missing.append(field)
    for field in TEXT_FIELDS:
        value = descriptor.get(field)
        if field in descriptor and (not isinstance(value, str) or not value.strip()):
            errors.append(f"{field} must be non-empty text")
    for field in LIST_FIELDS + COLLECTION_FIELDS:
        value = descriptor.get(field)
        if field not in descriptor:
            continue
        if field in LIST_FIELDS:
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
                errors.append(f"{field} must be a non-empty list of target names")
        elif not isinstance(value, (list, dict)) or not value:
            errors.append(f"{field} must be a non-empty list or object")
    if "promotion_threshold" in descriptor:
        _check_promotion_threshold(descriptor["promotion_threshold"], errors)

    known = set(getattr(module, "TARGETS", []) or []) | set(getattr(module, "HOLDOUT", []) or [])
    for field in LIST_FIELDS:
        value = descriptor.get(field)
        if not isinstance(value, list):
            continue
        unknown = sorted(item for item in value if item not in known)
        if unknown:
            errors.append(f"{field} names targets outside TARGETS and HOLDOUT: {', '.join(unknown)}")

    plugin = _plugin_name(module)
    verifier = descriptor.get("independent_verifier")
    if isinstance(verifier, str):
        match = VERIFIER_RE.fullmatch(verifier)
        if not match:
            errors.append("independent_verifier must name problems/<plugin>/verify.py")
        else:
            if plugin and match.group(1) != plugin:
                errors.append(f"independent_verifier names {match.group(1)}, not {plugin}")
            if not (root / verifier).is_file():
                errors.append(f"independent_verifier file is missing: {verifier}")

    source_path = getattr(module, "__file__", None)
    if not source_path or not Path(source_path).is_file():
        errors.append("plugin source file is unavailable for the verifier-isolation scan")
    else:
        source = Path(source_path).read_text(encoding="utf-8")
        imported, used = _evaluate_references(source, errors)
        for name in FORBIDDEN_IN_EVALUATE:
            if name in used:
                errors.append(f"problem.evaluate references {name}: the verifier must not use the measured code")
            elif name in imported:
                errors.append(f"problem.py imports {name}: the verifier must not use the measured code")

    return {"ok": not missing and not errors, "missing": sorted(set(missing)), "errors": errors}


def _defines_prize(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
        )
        if any(isinstance(target, ast.Name) and target.id == "PRIZE" for target in targets):
            return True
    return False


def prize_plugins(root=ROOT):
    """Plugin directory names whose problem.py defines a PRIZE descriptor. Nothing is imported."""
    problems = Path(root) / "problems"
    if not problems.is_dir():
        return []
    return sorted(path.parent.name for path in problems.glob("*/problem.py") if path.is_file() and _defines_prize(path))
