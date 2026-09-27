"""Effect primitives of the non-normal card layouts (cube layouts bucket):
transforming double-faced cards, Sagas, Classes, levelers.

The engine mechanics these drive live in :mod:`mtg_bot.layouts`; parser
entry points are in :mod:`mtg_bot.cards.parser.layout_grammar`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:  # pragma: no cover
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class TransformSource(Effect):
    """"Transform <this permanent>." (CR 701.28a) -- the resolving
    ability's source transforms. No-op when the source has left the
    battlefield."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> bool:
        from mtg_bot.layouts import transform_permanent

        source = state.resolving_source
        if source is None or source not in state.battlefield:
            return False
        return transform_permanent(state, source)

    def describe(self) -> str:
        return "transform this permanent"


@dataclass(frozen=True)
class ExileSourceThenReturnTransformed(Effect):
    """"Exile <this permanent>, then return it to the battlefield
    transformed under <its owner's | your> control." The source is
    exiled; if it is a transforming double-faced card it returns with
    its back face up as a new object (a planeswalker back face enters
    with its printed loyalty). A token / non-DFC stays in exile
    (CR 701.28c). ``under_owners_control`` picks the owner over the
    ability's controller."""

    under_owners_control: bool = True

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> bool:
        from mtg_bot.layouts import put_onto_battlefield_transformed
        from mtg_bot.turn import _reset_left_battlefield_object, move_off_battlefield

        source = state.resolving_source
        if source is None or source not in state.battlefield:
            return False
        move_off_battlefield(state, source, destination="exile")
        owner = state.player_by_id(source.owner_id)
        if source not in owner.exile:
            # A token ceased to exist / a replacement moved it elsewhere.
            return False
        new_controller = (
            source.owner_id if self.under_owners_control else controller_id
        )
        owner.exile.remove(source)
        # CR 400.7: it returns as a new object -- no counters, damage or
        # temporary bonuses carry over (the flicker effects' reset).
        _reset_left_battlefield_object(source)
        if not put_onto_battlefield_transformed(state, source, new_controller):
            owner.exile.append(source)
            return False
        return True

    def describe(self) -> str:
        who = "its owner's" if self.under_owners_control else "your"
        return (
            "exile this permanent, then return it to the battlefield "
            f"transformed under {who} control"
        )
