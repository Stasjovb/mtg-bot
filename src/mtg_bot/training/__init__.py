"""Training infrastructure — Phase A.

Self-play harness, search/evaluator config dataclasses, and a grid-
search helper. No neural-net code yet (that's Phase C); this is the
scaffolding all later training approaches need.

The point of this phase is to validate the full "play N games at
config X, return aggregate stats" loop end-to-end with the existing
heuristic evaluator. Once it works for tuning 3 weights, it works
for fitting 20 weights, and it works for training a network. Doing
the infrastructure first avoids over-engineering the eventual NN
parts before the harness has produced any real data.

Module map:

- ``config``     — ``HeuristicConfig`` + ``PimcConfig`` dataclasses
                   with ``build()`` (→ search strategy) and JSON
                   serialization. Frozen for use as dict keys / set
                   members in tuning loops.
- ``self_play`` — ``run_match(p0_factory, p1_factory, n_games, ...)``:
                   plays N games with a hard decision cap, returns
                   aggregate wins/losses/draws + average decisions.
                   Deterministic from ``base_seed``.
- ``grid``      — ``grid_search`` over a list of configs, each
                   played N games against a fixed opponent factory.
                   Returns results sorted by win rate.

CLI demo at ``scripts/tune_heuristic.py``.
"""

from __future__ import annotations

from mtg_bot.training.config import (
    HeuristicConfig,
    PimcConfig,
    random_choice_factory,
)
from mtg_bot.training.grid import grid_search, heuristic_weight_grid
from mtg_bot.training.self_play import MatchStats, run_match

__all__ = [
    "HeuristicConfig",
    "MatchStats",
    "PimcConfig",
    "grid_search",
    "heuristic_weight_grid",
    "random_choice_factory",
    "run_match",
]
