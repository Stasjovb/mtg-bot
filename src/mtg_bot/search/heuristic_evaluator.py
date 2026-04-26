"""Handcrafted MTG heuristic evaluator.

Replaces ``RandomRolloutEvaluator``'s "play out the game randomly to
completion" approach with a fast position scorer. Four components,
weighted-summed into ``[-1, 1]`` from the asked-for player's
perspective:

1. **Life advantage.** Most directly captures who's winning. Scaled
   so that ±20 life difference maps to ±1.0 (then clamped). Slightly
   non-linear: small life leads matter less than large ones in
   aggregate, but linear is a fine baseline.
2. **Board power.** Sum of (effective power + effective toughness)
   of each player's creatures, PLUS the printed P+T of every
   uncountered creature spell on the stack belonging to the player
   (those will become creatures on resolve — scoring them here
   captures the impending board change rather than penalizing the
   cast as "lost a card"). Scaled so a ±20 board diff maps to ±1.0.
3. **Card advantage.** A "deployed-value" count: hand size, plus
   permanents the player controls, plus uncountered non-creature
   spells on the stack belonging to the player. The intent is to
   never penalize a player for moving a card from one resource pool
   to another (hand → battlefield via spell resolution, hand → stack
   mid-cast). Differential capped at ±7. A weak signal alone but
   cheap and useful as a tiebreaker.
4. **Mana development.** Penalizes lands sitting unused in your hand
   while you still have room to grow your mana base (<5 lands in
   play). Counts each land beyond the first as "stuck" — the first
   one might reasonably be held; the second-and-onward almost never
   should. Mirrors the sign for the opponent (their stuck lands are
   good for you). Differential capped at ±4. Without this term the
   card-advantage component already netted out land-play to zero, so
   MCTS at low budget had no positive signal pulling it toward
   developing mana.

Default weights: 0.4 life / 0.4 board / 0.15 cards / 0.05 mana_dev.
Tunable via constructor for experimentation.

NOT designed to play optimal MTG — it's a baseline so MCTS has
something fast to score with that beats "play the rest of the game
out at random." The latter is unbiased but extremely slow on real
MTG; even ten random rollouts of an opening can take seconds.

The stack-aware terms exist because MCTS at low budget evaluates
positions at depth-1, when the active player has just cast a spell:
the spell sits on the stack, hand size is down by one, board hasn't
changed. Without stack scoring the eval reads "card advantage went
down → cast was bad" and PIMC systematically prefers passing. With
stack scoring, casting-then-being-evaluated produces no net penalty
(non-creature) or a positive board contribution (creature).

Reaches through ``MtgGameStateAdapter.engine_state`` to read
engine-side fields (life, hand, battlefield, stack). Coupled to MTG
by design — that's the point.
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
_MANA_DEV_NORMALIZER = 4.0
_MANA_DEV_LAND_THRESHOLD = 5  # only penalize while still ramping


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
        card_weight: float = 0.15,
        mana_dev_weight: float = 0.05,
    ) -> None:
        total = life_weight + board_weight + card_weight + mana_dev_weight
        if total <= 0:
            raise ValueError(
                f"weight sum must be positive; got {total}"
            )
        # Normalize so an all-positive subscore can never exceed 1.0
        # even when each component saturates.
        self.life_weight = life_weight / total
        self.board_weight = board_weight / total
        self.card_weight = card_weight / total
        self.mana_dev_weight = mana_dev_weight / total

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

        my_cards = self._card_count(engine, me.id)
        their_cards = self._card_count(engine, them.id)
        card_score = _clamp(
            (my_cards - their_cards) / _CARD_NORMALIZER
        )

        # Mirrored sign: stuck lands are bad for the holder, so
        # (their_stuck - my_stuck) is the positive-for-me signal.
        my_stuck = self._stuck_lands(engine, me.id)
        their_stuck = self._stuck_lands(engine, them.id)
        mana_dev_score = _clamp(
            (their_stuck - my_stuck) / _MANA_DEV_NORMALIZER
        )

        return _clamp(
            self.life_weight * life_score
            + self.board_weight * board_score
            + self.card_weight * card_score
            + self.mana_dev_weight * mana_dev_score
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
        """Sum effective (power + toughness) over creatures the player
        controls on the battlefield, plus printed (power + toughness)
        for each uncountered creature spell on the stack belonging to
        the player. Stack creatures use printed P+T because static
        battlefield buffs (anthems, equipment, +1/+1 counters) don't
        apply to the spell — they apply post-resolution. Skips
        countered spells (they'll resolve as no-ops) and triggered/
        activated abilities (those aren't "the player's value being
        deployed" in the same way)."""
        total = 0
        for o in engine.battlefield:
            if o.controller_id != player_id:
                continue
            if not is_creature_now(o):
                continue
            total += effective_power(engine, o) + effective_toughness(engine, o)
        for item in engine.stack:
            if item.countered or item.ability is not None:
                continue
            if item.controller_id != player_id:
                continue
            if not item.source.printing.is_creature:
                continue
            p = item.source.printing.power or 0
            t = item.source.printing.toughness or 0
            total += p + t
        return total

    @staticmethod
    def _stuck_lands(engine: EngineGameState, player_id: PlayerID) -> int:
        """Lands held in hand the player should be playing this turn.

        Active only while the player has fewer than
        ``_MANA_DEV_LAND_THRESHOLD`` lands on the battlefield (the early
        ramp window — once you're at five mana the marginal land matters
        less, and the term shouldn't push you to slam every land in a
        hand full of late-game spells). Within that window, each land
        beyond the first counts as stuck — holding one back can be
        legitimate (counter bait, fetch timing); holding two-plus
        almost never is at our card pool's complexity."""
        p = engine.player_by_id(player_id)
        lands_in_play = 0
        for o in engine.battlefield:
            if o.controller_id == player_id and o.printing.is_land:
                lands_in_play += 1
                if lands_in_play >= _MANA_DEV_LAND_THRESHOLD:
                    return 0
        lands_in_hand = sum(1 for c in p.hand if c.printing.is_land)
        return max(0, lands_in_hand - 1)

    @staticmethod
    def _card_count(engine: EngineGameState, player_id: PlayerID) -> int:
        """The player's "deployed value" count: hand size + permanents
        the player controls + uncountered non-creature spells on the
        stack belonging to the player.

        Counting permanents matters because casting/playing strictly
        moves a card from hand to either the battlefield (resolved
        spell, played land) or the stack (in-flight spell). Without
        counting permanents, the eval reads "hand went down" and
        penalizes any forward-moving action — including playing a land,
        which is an unalloyed good move on most turns. With permanents
        counted, ``hand → battlefield`` is a no-op for this term, and
        the meaningful signal moves to the board-power and life
        components.

        Creature spells on the stack are excluded here because they're
        scored as future board in ``_board_power`` — counting them
        again would double-attribute their value. Countered spells and
        triggered/activated abilities are excluded entirely (no value
        left to attribute)."""
        p = engine.player_by_id(player_id)
        count = len(p.hand)
        for o in engine.battlefield:
            if o.controller_id == player_id and not o.phased_out:
                count += 1
        for item in engine.stack:
            if item.countered or item.ability is not None:
                continue
            if item.controller_id != player_id:
                continue
            if item.source.printing.is_creature:
                continue
            count += 1
        return count
