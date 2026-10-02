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


__all__ = [
    "CardsNamedInAllGraveyards",
    "EnteredThisTurn",
]
