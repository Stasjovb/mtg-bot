"""Grid-search helper: try a list of configs against one opponent.

Designed around a fixed opponent (typically RandomChoice — the
clean baseline) rather than round-robin between configs. Round-
robin gives you Elo-style pairwise data but the per-config noise
is much higher because both sides change. Fixed-opponent runs let
you say "config A wins 73% vs Random, config B wins 65% vs Random,
A is better" with much less data.

For Phase A this is a sequential loop. Phase D will need
multiprocessing parallelism (one game per process) to be tractable
for AlphaZero-style iteration; that comes later.
"""

from __future__ import annotations

from typing import Iterable, Optional

from mtg_bot.decks import Deck
from mtg_bot.training.config import (
    HeuristicConfig,
    PimcConfig,
    StrategyFactory,
)
from mtg_bot.training.self_play import MatchStats, run_match


def grid_search(
    grid: Iterable[PimcConfig],
    opponent_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    progress_callback=None,
    deck_pool: Optional[list[Deck]] = None,
) -> list[tuple[PimcConfig, MatchStats]]:
    """For each config in ``grid``, play ``n_games`` against
    ``opponent_factory`` (P1) and return results sorted by P0
    win rate (best first).

    ``progress_callback(idx, total, config, stats)`` is called after
    each config completes — useful for printing live progress on
    long sweeps. Pass ``None`` for silent operation.

    Sequential. Each config × game is independent so this could
    parallelize trivially across cores, but Windows multiprocessing
    requires picklable factories + a per-process engine import; that
    work belongs to Phase D when self-play data generation needs
    real parallelism.
    """
    grid_list = list(grid)
    results: list[tuple[PimcConfig, MatchStats]] = []
    for idx, config in enumerate(grid_list):
        stats = run_match(
            p0_factory=lambda seed, _c=config: _c.build(seed),
            p1_factory=opponent_factory,
            n_games=n_games,
            base_seed=base_seed,
            deck_pool=deck_pool,
        )
        results.append((config, stats))
        if progress_callback is not None:
            progress_callback(idx, len(grid_list), config, stats)
    results.sort(key=lambda cs: cs[1].win_rate(0), reverse=True)
    return results


def heuristic_weight_grid(
    *,
    step: float = 0.1,
    min_weight: float = 0.1,
    max_weight: float = 0.7,
    samples: int = 2,
    inner_nodes: int = 50,
) -> list[PimcConfig]:
    """Yield PimcConfigs covering a grid of heuristic weight triples
    that sum to 1.0.

    The heuristic evaluator already renormalizes, so we don't strictly
    need the sum-to-1 constraint — but enumerating only convex
    combinations keeps the grid small (a 3D simplex has ~21 points
    at 0.1 step) and the weights interpretable.

    ``samples`` and ``inner_nodes`` are deliberately small defaults
    so a full grid sweep stays tractable in 5-10 minutes (rather
    than the recommend.py defaults of 4/200 which would take
    hours). The ranking is what matters for tuning, not the
    absolute strength.
    """
    grid: list[PimcConfig] = []
    weights: list[float] = []
    w = min_weight
    while w <= max_weight + 1e-9:
        weights.append(round(w, 3))
        w += step
    for life in weights:
        for board in weights:
            card = round(1.0 - life - board, 3)
            if card < min_weight - 1e-9 or card > max_weight + 1e-9:
                continue
            grid.append(PimcConfig(
                samples=samples,
                inner_nodes=inner_nodes,
                heuristic=HeuristicConfig(
                    life_weight=life,
                    board_weight=board,
                    card_weight=card,
                ),
            ))
    return grid
