"""Engine effects for the Vintage Roto P3 bucket: mana, costs and cast
permissions (``docs/ROTO_COVERAGE_PLAN.md`` section 4).

The parser side lives in ``cards/parser/roto_mana.py``; every effect
here is built only by that grammar. Formulas and predicates the effects
need sit next to them so the shared ``effects/formulas.py`` /
``object_predicates.py`` modules stay untouched by this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.formulas import Formula
from mtg_bot.effects.object_predicates import ObjectPredicate

if TYPE_CHECKING:
    from mtg_bot.game import GameState


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardsNamedInAllGraveyards(Formula):
    """The number of cards named ``name`` in every graveyard (Rite of
    Flame's "for each card named Rite of Flame in each graveyard"). The
    resolving spell is on the stack, so it never counts itself."""

    name: str

    def value(self, state: "GameState", controller_id: int) -> int:
        return sum(
            1 for p in state.players for c in p.graveyard
            if c.printing.name == self.name
        )


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnteredThisTurn(ObjectPredicate):
    """A permanent that entered the battlefield this turn ("creatures
    that entered this turn", Force of Despair). Reads the
    ``GameObject.entered_battlefield_turn`` stamp
    ``actions.put_into_battlefield`` writes for every permanent."""

    def test(self, obj, state) -> bool:
        turn = getattr(obj, "entered_battlefield_turn", None)
        return turn is not None and turn == state.turn_number


# ---------------------------------------------------------------------------
# Mana effects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AddManaPerCardInTargetOpponentsHand(Effect):
    """"Add {C} for each card in target opponent's hand." (Jeska's Will).
    A spell mode, not a mana ability: it targets and uses the stack. The
    hand is counted as the spell resolves."""

    color: str = "R"

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int,
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players
            if p.id != controller_id and not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import ManaCoin

        if not targets or targets[0][0] != "player":
            return
        opp = next(
            (p for p in state.players if p.id == targets[0][1]), None,
        )
        if opp is None or opp.id == controller_id:
            return
        n = len(opp.hand)
        pool = state.player_by_id(controller_id).mana_pool
        pool.extend(ManaCoin(color=self.color) for _ in range(n))
        state.log.append(
            f"P{controller_id} adds {{{self.color}}}x{n} (cards in "
            f"P{opp.id}'s hand)"
        )

    def describe(self) -> str:
        return f"add {{{self.color}}} for each card in target opponent's hand"


__all__ = [
    "AddManaPerCardInTargetOpponentsHand",
    "CardsNamedInAllGraveyards",
    "EnteredThisTurn",
]
