"""Search / evaluator configs as serializable dataclasses.

Each config is a pure data description that can be:
- Serialized to JSON (for storing tuning results, versioning
  evaluators, comparing runs).
- Built into a live ``SearchStrategy`` via ``build(seed)``.

Frozen so configs are hashable (usable as dict keys, set members)
— important for grid-search loops that want to deduplicate or
look up "have we measured this config yet?"

The build pattern keeps strategy construction in one place. A
tuning loop can produce hundreds of configs and just call
``cfg.build(seed)`` per game without the loop knowing anything
about MCTS / PIMC / evaluator wiring.

Picklability matters: ``run_match_parallel`` ships configs across
``multiprocessing.Pool`` worker boundaries (spawn on Windows,
fork on Unix). Frozen dataclasses + their bound ``.build``
methods pickle cleanly. Closures over local variables do NOT —
that's why every per-game configuration lives in a config class
here, not in an inline closure at the call site.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from mtg_bot.search import (
    Budget,
    MCTS,
    PIMC,
    RandomChoice,
)
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.search.nn_evaluator import NNEvaluator
from mtg_bot.search.strategy import SearchStrategy


@dataclass(frozen=True)
class HeuristicConfig:
    """Weights for ``MtgHeuristicEvaluator``. Defaults match the
    evaluator's own defaults (0.4 / 0.4 / 0.15 / 0.05)."""

    life_weight: float = 0.4
    board_weight: float = 0.4
    card_weight: float = 0.15
    mana_dev_weight: float = 0.05

    def build(self) -> Evaluator:
        return MtgHeuristicEvaluator(
            life_weight=self.life_weight,
            board_weight=self.board_weight,
            card_weight=self.card_weight,
            mana_dev_weight=self.mana_dev_weight,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HeuristicConfig":
        return cls(**d)


@dataclass(frozen=True)
class PimcConfig:
    """Full PIMC search config: K samples, MCTS budget per sub-search,
    and the heuristic-evaluator weights.

    Defaults match ``recommend.py``: samples=4, max_nodes=200, default
    heuristic weights. That's the UI's recommendation budget — slow
    enough to actually search, fast enough to stay responsive.
    Tuning loops typically dial samples + nodes down to keep games
    cheap (~3-6s instead of ~10-15s)."""

    samples: int = 4
    inner_nodes: int = 200
    heuristic: HeuristicConfig = field(default_factory=HeuristicConfig)
    batch_size: int = 1

    def build(self, seed: int = 0) -> SearchStrategy:
        """Construct a fresh PIMC search strategy seeded for
        reproducibility. Different ``seed`` values give different
        sub-search RNGs."""
        evaluator = self.heuristic.build()
        inner_nodes = self.inner_nodes
        batch_size = self.batch_size
        rng_seed_inner = seed + 100
        rng_seed_outer = seed + 200

        def inner_factory() -> MCTS:
            return MCTS(
                evaluator=evaluator,
                budget_factory=lambda: Budget(max_nodes=inner_nodes),
                rng=random.Random(rng_seed_inner),
                batch_size=batch_size,
            )

        return PIMC(
            inner_factory=inner_factory,
            samples=self.samples,
            rng=random.Random(rng_seed_outer),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "inner_nodes": self.inner_nodes,
            "heuristic": self.heuristic.to_dict(),
            "batch_size": self.batch_size,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PimcConfig":
        return cls(
            samples=d["samples"],
            inner_nodes=d["inner_nodes"],
            heuristic=HeuristicConfig.from_dict(d["heuristic"]),
            batch_size=d.get("batch_size", 1),
        )


@dataclass(frozen=True)
class NNPimcConfig:
    """Full PIMC config backed by a saved NN evaluator. Carries a
    ``weights_path`` rather than an evaluator instance because
    ``NNEvaluator`` (and the underlying ``torch.nn.Module``) is not
    designed for cross-process pickling — the evaluator is built
    fresh inside ``build`` from the bytes on disk, which always
    works.

    ``batch_size`` defaults to 32 to capture the B1 batched-leaf-
    evaluation win on the NN forward pass.
    """

    weights_path: str
    samples: int = 4
    inner_nodes: int = 200
    batch_size: int = 32

    def build(self, seed: int = 0) -> SearchStrategy:
        evaluator = NNEvaluator(weights_path=Path(self.weights_path))
        inner_nodes = self.inner_nodes
        batch_size = self.batch_size
        rng_seed_inner = seed + 100
        rng_seed_outer = seed + 200

        def inner_factory() -> MCTS:
            return MCTS(
                evaluator=evaluator,
                budget_factory=lambda: Budget(max_nodes=inner_nodes),
                rng=random.Random(rng_seed_inner),
                batch_size=batch_size,
            )

        return PIMC(
            inner_factory=inner_factory,
            samples=self.samples,
            rng=random.Random(rng_seed_outer),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights_path": self.weights_path,
            "samples": self.samples,
            "inner_nodes": self.inner_nodes,
            "batch_size": self.batch_size,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NNPimcConfig":
        return cls(
            weights_path=d["weights_path"],
            samples=d["samples"],
            inner_nodes=d["inner_nodes"],
            batch_size=d.get("batch_size", 32),
        )


def random_choice_factory(seed: int) -> RandomChoice:
    """Strategy factory for ``RandomChoice``. The standard "is the
    PIMC actually doing something useful?" baseline. Has no config
    of its own; just needs a seed."""
    return RandomChoice(rng=random.Random(seed))


# Type alias for any callable that produces a search strategy from
# a seed. Both ``PimcConfig.build`` and ``random_choice_factory``
# satisfy this; tuning loops are written against this surface so
# they can pit any strategy type against any other.
StrategyFactory = Callable[[int], SearchStrategy]
