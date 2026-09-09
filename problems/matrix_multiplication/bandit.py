"""UCB1 multi-armed bandit over composition operators.

Arms are the real operator names appearing in ``composition.py`` /
``multiscale.py`` construction trees — no invented names:

    library            registry lookup (known, exactly-verified decompositions)
    tensor_product     tensor product of two registry decompositions
    block_embed        block composition: embed a smaller decomposition in a
                       diagonal block, add cross-block terms, naive-fill rest
    level2_partition   Level 2 block-partition enumeration in multiscale search
    border_terms       cross-block rank-1 outer-product terms
    naive_fill         naive triples covering otherwise-uncovered outputs
    level1_repair      Level 1 delete-and-repair polish

Reward signal (fixed, documented here and in smart_loop.py):
    1.0  the operator is in the winning construction and its candidate was
         exact-verified AND survived the breaker suite
    0.5  the operator is in the winning construction and its candidate was
         exact-verified but the breaker broke it
    0.0  otherwise — the operator did not produce the promoted candidate
         (including arms absent from the winning construction, and runs
         with no verified candidate at all)

Selection is UCB1: score(arm) = mean(arm) + c * sqrt(ln(N) / n(arm)), with
a cold start (every arm is selected once before confidence bounds apply)
and an epsilon-greedy fallback — with probability epsilon a uniform-random
arm is chosen, which keeps exploration alive when rewards shift across
problem sizes.

Persistence: state is a plain dict ``{arm: {"pulls": int, "reward": float}}``
plus hyperparameters. It round-trips through
``PatternLibrary.get_bandit_state`` / ``save_bandit_state`` (see
``patterns/library.py``); the JSON file itself is ``patterns/_bandit.json``.
"""

from __future__ import annotations

import math


class OperatorBandit:
    """UCB1 bandit over the composition-operator arm set."""

    ARMS = (
        "library",
        "tensor_product",
        "block_embed",
        "level2_partition",
        "border_terms",
        "naive_fill",
        "level1_repair",
    )

    def __init__(self, c: float = 2.0, epsilon: float = 0.1, state: dict | None = None):
        self.c = float(c)
        self.epsilon = float(epsilon)
        self._pulls: dict[str, int] = {arm: 0 for arm in self.ARMS}
        self._reward: dict[str, float] = {arm: 0.0 for arm in self.ARMS}
        if state:
            arms = state.get("arms", {})
            for arm in self.ARMS:
                entry = arms.get(arm, {})
                self._pulls[arm] = int(entry.get("pulls", 0))
                self._reward[arm] = float(entry.get("reward", 0.0))
            self.c = float(state.get("c", self.c))
            self.epsilon = float(state.get("epsilon", self.epsilon))

    # -- learning ------------------------------------------------------

    def record(self, arm: str, reward: float) -> None:
        """Record one observed reward for *arm*. Raises KeyError for unknown arms."""
        if arm not in self._pulls:
            raise KeyError(f"unknown bandit arm: {arm!r}")
        self._pulls[arm] += 1
        self._reward[arm] += float(reward)

    def mean(self, arm: str) -> float:
        """Mean observed reward for *arm* (0.0 before the first pull)."""
        n = self._pulls[arm]
        return self._reward[arm] / n if n else 0.0

    def pulls(self, arm: str) -> int:
        """Number of recorded pulls for *arm*."""
        return self._pulls[arm]

    def total_pulls(self) -> int:
        """Total recorded pulls across all arms."""
        return sum(self._pulls.values())

    # -- selection -----------------------------------------------------

    def _ucb(self, arm: str, total: int) -> float:
        n = self._pulls[arm]
        if n == 0:
            return math.inf  # cold start: untried arms go first
        return self.mean(arm) + self.c * math.sqrt(math.log(total) / n)

    def select(self, rng) -> str:
        """Choose one arm: epsilon-greedy fallback, else the top UCB arm."""
        if rng.random() < self.epsilon:
            return rng.choice(list(self.ARMS))
        ranked = self.rank_arms(rng)
        return ranked[0]

    def rank_arms(self, rng) -> list[str]:
        """All arms ordered by UCB score, descending.

        Ties (including the all-untried cold start) are broken by *rng*
        shuffle, so early orderings explore rather than stall. Callers
        that only care about a subset of arms filter the result.
        """
        total = max(1, self.total_pulls())
        order = list(self.ARMS)
        rng.shuffle(order)  # tie-break before the stable sort
        order.sort(key=lambda arm: self._ucb(arm, total), reverse=True)
        return order

    # -- persistence ---------------------------------------------------

    def state_dict(self) -> dict:
        """Plain-dict snapshot for PatternLibrary.get/save_bandit_state."""
        return {
            "c": self.c,
            "epsilon": self.epsilon,
            "arms": {
                arm: {"pulls": self._pulls[arm], "reward": self._reward[arm]}
                for arm in self.ARMS
            },
        }


def ops_in_construction(construction) -> set[str]:
    """Collect every ``op`` string in a construction tree (any nesting)."""
    ops: set[str] = set()
    stack = [construction]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            op = node.get("op")
            if isinstance(op, str):
                ops.add(op)
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return ops


if __name__ == "__main__":
    import random

    rng = random.Random(0)
    bandit = OperatorBandit()
    # Simulate: "library" always produces the surviving winner.
    for _ in range(10):
        first = bandit.rank_arms(rng)[0]
        for arm in OperatorBandit.ARMS:
            bandit.record(arm, 1.0 if arm == "library" else 0.0)
    print("ranked:", bandit.rank_arms(rng))
    print("means:", {a: round(bandit.mean(a), 3) for a in OperatorBandit.ARMS})
    print("pulls:", {a: bandit.pulls(a) for a in OperatorBandit.ARMS})
