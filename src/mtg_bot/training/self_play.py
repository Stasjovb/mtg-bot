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
"""

from __future__ import annotations

import random
from dataclasses import dataclass

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
    wins: dict[PlayerID, int] = {0: 0, 1: 0}
    draws = 0
    total_decisions = 0
    for game_idx in range(n_games):
        engine_seed = base_seed + game_idx
        engine = setup_game(
            [
                RandomAgent(rng=random.Random(engine_seed + 1)),
                RandomAgent(rng=random.Random(engine_seed + 2)),
            ],
            ["G", "R"],
            seed=engine_seed,
        )
        adapter = MtgGameStateAdapter(engine)

        strategies = {
            0: p0_factory(base_seed + 100 * game_idx),
            1: p1_factory(base_seed + 100 * game_idx + 50),
        }
        rng = random.Random(base_seed + 100 * game_idx + 99)

        winner, decisions = _play_capped_game(
            adapter, strategies, rng, decision_cap,
        )
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
