"""Self-play harness: run N games at given configs, aggregate stats.

The existing ``mtg_bot.search.harness`` is generic and protocol-
shaped (works on toy games too). This module wraps it for the MTG-
specific tuning use case: deterministic seeding from a base seed,
hard decision cap so a stuck game can't hang the loop, and a
``MatchStats`` that tracks average decisions per game (useful for
spotting "this config plays infinite-loop games" without time-
profiling each one).

All state is built fresh per game — no shared engine state across
games. Both player slots get independent RNGs derived from the base
seed so the same call always produces the same result (essential
for comparing tuning runs).

Parallel mode: ``run_match_parallel`` distributes the N games
across a ``multiprocessing.Pool``. Per-game seeds are derived from
``game_idx``, not worker assignment, so the result is identical to
the sequential ``run_match`` for the same ``base_seed``.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import random
from dataclasses import dataclass
from typing import Optional

from mtg_bot.agents import RandomAgent
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.protocol import CHANCE_PLAYER, PlayerID
from mtg_bot.simulate import setup_game
from mtg_bot.training.config import StrategyFactory


# Hard cap on decisions per game. A pathological infinite priority
# loop (which has shown up before — see PIMC step-reentry bug) would
# otherwise hang the tuning loop. Real games are well under this; if
# we hit the cap, that's a bug.
_DEFAULT_DECISION_CAP = 4000


@dataclass(frozen=True)
class MatchStats:
    """Aggregate result of ``run_match``.

    ``wins[0]`` / ``wins[1]``: games player 0 / player 1 won.
    ``draws``: games that ended in a draw or hit the decision cap.
    ``games``: total games played (== wins[0] + wins[1] + draws).
    ``avg_decisions``: mean decisions across all games. Spots
    pathological game-length blowups even when the win rate looks
    fine.
    """

    wins: dict[PlayerID, int]
    draws: int
    games: int
    avg_decisions: float

    def win_rate(self, player_id: PlayerID) -> float:
        """Fraction of games ``player_id`` won. Draws don't count
        for either side."""
        return self.wins.get(player_id, 0) / self.games if self.games else 0.0


def run_match(
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    decision_cap: int = _DEFAULT_DECISION_CAP,
) -> MatchStats:
    """Play ``n_games`` of ``p0_factory`` vs ``p1_factory`` and
    aggregate stats.

    Each game gets independent seeds derived from ``base_seed``:

    - Game ``i`` uses engine seed ``base_seed + i``.
    - P0's strategy is built with seed ``base_seed + 100*i``.
    - P1's strategy is built with seed ``base_seed + 100*i + 50``.
    - Chance-node sampling RNG uses seed ``base_seed + 100*i + 99``.

    The deterministic seeding means the same call produces the same
    result — essential for "does heuristic config A beat config B?"
    comparisons across tuning runs.
    """
    results = [
        _play_one_match_game(
            game_idx, p0_factory, p1_factory, base_seed, decision_cap,
        )
        for game_idx in range(n_games)
    ]
    return _aggregate_results(results, n_games)


def run_match_parallel(
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    decision_cap: int = _DEFAULT_DECISION_CAP,
    n_workers: Optional[int] = None,
) -> MatchStats:
    """Same contract as ``run_match`` but distributes games across a
    ``multiprocessing.Pool``.

    Identical output to the sequential function for the same
    ``base_seed`` — per-game seeds are derived from ``game_idx``,
    not worker assignment, so each game produces the same result
    no matter which worker plays it. ``Pool.map`` preserves input
    order so aggregation is deterministic too.

    ``n_workers`` defaults to ``cpu_count() - 2`` (leaves a few
    cores for OS / Python main / other work). Pass an explicit int
    to override.

    Caller note: factories must be picklable. Module-level functions
    and bound methods of picklable dataclasses work; lambdas and
    nested closures don't. The ``evaluate_nn`` CLI builds factories
    that pickle.

    Worker spawn cost on Windows is ~1-2s per worker, paid once per
    pool. Dominates wall-clock at very small ``n_games``; amortizes
    away past a few dozen games.
    """
    if n_workers is None:
        n_workers = max(1, (os.cpu_count() or 1) - 2)
    if n_workers < 1:
        raise ValueError(f"n_workers must be >= 1, got {n_workers}")
    if n_games == 0:
        return MatchStats(wins={0: 0, 1: 0}, draws=0, games=0, avg_decisions=0.0)

    args_list = [
        (i, p0_factory, p1_factory, base_seed, decision_cap)
        for i in range(n_games)
    ]
    with mp.Pool(processes=n_workers) as pool:
        results = pool.map(_play_one_match_game_packed, args_list)
    return _aggregate_results(results, n_games)


def _play_one_match_game_packed(
    args: tuple,
) -> tuple[Optional[PlayerID], int]:
    """Top-level pickleable worker. Unpacks the args tuple and
    delegates to ``_play_one_match_game``. Lives at module top
    level (not nested) so multiprocessing can pickle it across
    the spawn boundary."""
    return _play_one_match_game(*args)


def _play_one_match_game(
    game_idx: int,
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    base_seed: int,
    decision_cap: int,
) -> tuple[Optional[PlayerID], int]:
    """Play one game and return ``(winner_or_None, decisions)``.
    Used by both the sequential and parallel match drivers — same
    seed derivation logic in both paths so the results match."""
    engine_seed = base_seed + game_idx
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(engine_seed + 1)),
            RandomAgent(rng=random.Random(engine_seed + 2)),
        ],
        ["G", "R"],
        seed=engine_seed,
    )
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    strategies = {
        0: p0_factory(base_seed + 100 * game_idx),
        1: p1_factory(base_seed + 100 * game_idx + 50),
    }
    rng = random.Random(base_seed + 100 * game_idx + 99)
    return _play_capped_game(adapter, strategies, rng, decision_cap)


def _aggregate_results(
    results: list[tuple[Optional[PlayerID], int]], n_games: int,
) -> MatchStats:
    """Aggregate per-game ``(winner_or_None, decisions)`` results
    into a ``MatchStats``."""
    wins: dict[PlayerID, int] = {0: 0, 1: 0}
    draws = 0
    total_decisions = 0
    for winner, decisions in results:
        total_decisions += decisions
        if winner == 0:
            wins[0] += 1
        elif winner == 1:
            wins[1] += 1
        else:
            draws += 1
    return MatchStats(
        wins=wins,
        draws=draws,
        games=n_games,
        avg_decisions=total_decisions / n_games if n_games else 0.0,
    )


def _play_capped_game(
    adapter: MtgGameStateAdapter,
    strategies: dict[PlayerID, "object"],
    rng: random.Random,
    decision_cap: int,
) -> tuple[PlayerID | None, int]:
    """Play one game with a hard decision cap. Returns
    ``(winner_id_or_None, decisions_made)``. If the cap is hit
    without termination, returns ``(None, decision_cap)`` — caller
    counts that as a draw."""
    decisions = 0
    while not adapter.is_terminal() and decisions < decision_cap:
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            decision = rng.choices(choices, weights=weights, k=1)[0]
        else:
            decision = strategies[active].choose(adapter, active)
        adapter.apply(decision)
        decisions += 1
    if adapter.is_terminal():
        return adapter.winner(), decisions
    return None, decisions
