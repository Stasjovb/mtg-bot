"""Handcrafted MTG heuristic evaluator.

Replaces ``RandomRolloutEvaluator``'s "play out the game randomly to
completion" approach with a fast position scorer. Three components,
weighted-summed into ``[-1, 1]`` from the asked-for player's
perspective:

1. **Life advantage.** Most directly captures who's winning. Scaled
   so that ±20 life difference maps to ±1.0 (then clamped). Slightly
   non-linear: small life leads matter less than large ones in
   aggregate, but linear is a fine baseline.
2. **Board power.** Sum of (effective power + effective toughness)
   of each player's creatures. Captures threat density. Scaled so a
   ±20 board diff maps to ±1.0.
3. **Card advantage.** Hand-size differential. Capped at ±7. A
   weak signal alone but cheap and useful as a tiebreaker.

Default weights: 0.4 life / 0.4 board / 0.2 cards. Tunable via
constructor for experimentation.

NOT designed to play optimal MTG — it's a baseline so MCTS has
something fast to score with that beats "play the rest of the game
out at random." The latter is unbiased but extremely slow on real
MTG; even ten random rollouts of an opening can take seconds.

Reaches through ``MtgGameStateAdapter.engine_state`` to read
engine-side fields (life, hand, battlefield). Coupled to MTG by
design — that's the point.
"""

from __future__ import annotations

from mtg_bot.game import (
    GameState as EngineGameState,
    effective_power, effective_toughness, is_creature_now,
)
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.protocol import GameState, PlayerID


# Normalization constants: scaled so typical EoE-game leads map
# roughly to a unit-sized signal each.
_LIFE_NORMALIZER = 20.0
_BOARD_NORMALIZER = 20.0
_CARD_NORMALIZER = 7.0


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class MtgHeuristicEvaluator(Evaluator):
    """Life + board-power + card-advantage weighted heuristic.

    Designed to be cheap (no rollouts; just sums and ratios across
    the battlefield and hands) and good-enough to give MCTS a
    directional signal. Two-player only.
    """

    def __init__(
        self,
        life_weight: float = 0.4,
        board_weight: float = 0.4,
        card_weight: float = 0.2,
    ) -> None:
        total = life_weight + board_weight + card_weight
        if total <= 0:
            raise ValueError(
                f"weight sum must be positive; got {total}"
            )
        # Normalize so an all-positive subscore can never exceed 1.0
        # even when each component saturates.
        self.life_weight = life_weight / total
        self.board_weight = board_weight / total
        self.card_weight = card_weight / total

    def _evaluate_nonterminal(
        self, state: GameState, player_id: PlayerID
    ) -> float:
        engine = self._engine_state(state)
        me = engine.player_by_id(player_id)
        opponents = [p for p in engine.players if p.id != player_id]
        if not opponents:
            # Singleton (shouldn't happen in 2-player MTG, but be
            # defensive). Score relative to nothing — return neutral.
            return 0.0
        # Two-player: just one opponent.
        them = opponents[0]

        life_score = _clamp(
            (me.life - them.life) / _LIFE_NORMALIZER
        )

        my_board = self._board_power(engine, me.id)
        their_board = self._board_power(engine, them.id)
        board_score = _clamp(
            (my_board - their_board) / _BOARD_NORMALIZER
        )

        card_score = _clamp(
            (len(me.hand) - len(them.hand)) / _CARD_NORMALIZER
        )

        return _clamp(
            self.life_weight * life_score
            + self.board_weight * board_score
            + self.card_weight * card_score
        )

    @staticmethod
    def _engine_state(state: GameState) -> EngineGameState:
        """Reach through the adapter (or accept a raw engine state
        directly, for tests)."""
        engine = getattr(state, "engine_state", None)
        if engine is not None:
            return engine
        return state  # assume it's already an EngineGameState

    @staticmethod
    def _board_power(engine: EngineGameState, player_id: PlayerID) -> int:
        """Sum effective (power + toughness) over creatures the
        player controls. Captures both threat and resilience."""
        total = 0
        for o in engine.battlefield:
            if o.controller_id != player_id:
                continue
            if not is_creature_now(o):
                continue
            total += effective_power(engine, o) + effective_toughness(engine, o)
        return total
