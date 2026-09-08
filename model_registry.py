"""Canonical subscription model identities and routing-policy validation."""

from __future__ import annotations


MODEL_REGISTRY = {
    "fable": {"family": "anthropic", "transport": "fable", "model": "claude-fable-5-1"},
    "opus": {"family": "anthropic", "transport": "fable", "model": "claude-opus-5"},
    "astra": {"family": "openai", "transport": "astra", "model": "gpt-6-astra"},
    "sol": {"family": "openai", "transport": "astra", "model": "gpt-5.6-sol"},
}
DEFAULT_CHAIN = ("fable", "opus", "astra", "sol")
VALID_FAMILIES = frozenset({"anthropic", "openai"})
VALID_ROUTING_POLICIES = frozenset(
    {"scheduled", "ordered", "auto", "openai_only", "anthropic_only", "astra_only", "fable_only", "paired"}
)


def model_spec(name: str) -> dict:
    """Return a copy of one canonical model record."""
    if name not in MODEL_REGISTRY:
        raise ValueError(f"unknown model alias {name!r}")
    return {"alias": name, **MODEL_REGISTRY[name]}


def alias_for_model(model: str, family: str | None = None) -> str:
    """Resolve an exact configured model identity, optionally constrained by family."""
    matches = [
        alias
        for alias, item in MODEL_REGISTRY.items()
        if item["model"] == model and (family is None or item["family"] == family)
    ]
    if len(matches) != 1:
        raise ValueError(f"model {model!r} is absent from the canonical registry for this family")
    return matches[0]


def _unique_aliases(values) -> list[str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("routing chain must be a non-empty list of model aliases")
    result = []
    for value in values:
        if not isinstance(value, str) or value not in MODEL_REGISTRY:
            raise ValueError(f"unknown model alias {value!r}")
        if value in result:
            raise ValueError(f"routing chain repeats model alias {value!r}")
        result.append(value)
    return result


def validate_routing_config(value) -> dict:
    """Validate and normalize the routing block stored under ``night.routing``."""
    if not isinstance(value, dict):
        raise ValueError("night routing configuration must be an object")
    allowed = {"policy", "chain", "disabled_families"}
    if set(value) - allowed:
        raise ValueError("night routing configuration contains unknown fields")
    policy = value.get("policy", "scheduled")
    if policy not in VALID_ROUTING_POLICIES:
        raise ValueError(f"unknown routing policy {policy!r}")
    chain = _unique_aliases(value.get("chain", DEFAULT_CHAIN))
    disabled = value.get("disabled_families", [])
    if not isinstance(disabled, list) or any(item not in VALID_FAMILIES for item in disabled):
        raise ValueError("disabled_families must contain only anthropic or openai")
    if len(set(disabled)) != len(disabled):
        raise ValueError("disabled_families cannot contain duplicates")
    return {"policy": policy, "chain": chain, "disabled_families": list(disabled)}


def routing_config(config: dict) -> dict:
    """Read the normalized routing block from a full night schedule."""
    if not isinstance(config, dict) or not isinstance(config.get("night", {}), dict):
        raise ValueError("night schedule must be an object")
    return validate_routing_config(config.get("night", {}).get("routing", {}))


def policy_chain(policy: str, configured_chain, requested_alias: str | None = None) -> list[str]:
    """Resolve an ordered model chain without inventing aliases outside configuration."""
    if policy not in VALID_ROUTING_POLICIES:
        raise ValueError(f"unknown routing policy {policy!r}")
    chain = _unique_aliases(configured_chain)
    if policy == "ordered":
        return chain
    if policy in {"scheduled", "paired"}:
        if requested_alias == "paired":
            return chain
        if requested_alias not in MODEL_REGISTRY:
            raise ValueError("paired routing requires a registered requested model")
        requested_family = MODEL_REGISTRY[requested_alias]["family"]
        same_family = [name for name in chain if MODEL_REGISTRY[name]["family"] == requested_family]
        if requested_alias in same_family:
            same_family.remove(requested_alias)
            same_family.insert(0, requested_alias)
        other_family = [name for name in chain if MODEL_REGISTRY[name]["family"] != requested_family]
        return same_family + other_family
    if policy == "astra_only":
        return ["astra"] if "astra" in chain else []
    if policy == "fable_only":
        return ["fable"] if "fable" in chain else []
    if policy == "openai_only":
        return [name for name in chain if MODEL_REGISTRY[name]["family"] == "openai"]
    if policy == "anthropic_only":
        return [name for name in chain if MODEL_REGISTRY[name]["family"] == "anthropic"]
    return chain
