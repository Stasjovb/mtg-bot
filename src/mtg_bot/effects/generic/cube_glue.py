"""Engine effects for the cube "glue" bucket.

The last unclaimed PowerLSV cube cards each needed one piece the other
buckets didn't ship. Every effect here is generic (parameterized by the
printed shape), not per-card; the parser side is
``cards/parser/cube_glue_grammar.py``. Shortcuts are documented in the
"glue" section of ``docs/SEARCH_LIMITATIONS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.game import GameState


# ---------------------------------------------------------------------------
# Linked "the exiled card" returns (CR 607.2a)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnCardsExiledWithSourceToOwnersHand(Effect):
    """"Return the exiled card to its owner's hand." (Tidehollow
    Sculler's leaves-the-battlefield half). Every card linked to the
    resolving source's battlefield incarnation (the imprint link,
    ``GameObject.imprinted_on``) goes back to its owner's hand. A card
    exiled by the linked ETB AFTER this resolved (the classic "Sculler
    left in response" line) was linked too late and stays exiled."""

    consumes_exile_link = True

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.cube_creatures_wg import cards_exiled_with
        from mtg_bot.game import Zone

        source = state.resolving_source
        if source is None:
            return
        for card in cards_exiled_with(state, source):
            owner = state.player_by_id(card.owner_id)
            owner.exile.remove(card)
            card.imprinted_on = None
            card.zone = Zone.HAND
            owner.hand.append(card)
            state.log.append(
                f"{card.printing.name} returns from exile to P{owner.id}'s "
                f"hand"
            )

    def describe(self) -> str:
        return "return the exiled card to its owner's hand"


@dataclass(frozen=True)
class RevealHandMayExileCardOrChosenCreatureUntilSourceLeaves(Effect):
    """"Choose target opponent and up to one target creature they
    control. They reveal their hand. You may exile a <filter> card from
    their hand or the chosen creature until <this> leave(s) the
    battlefield." (Cloak and Dagger, Entwined.)

    Two target slots: the opponent (``"player"``) and up to one creature
    (``"creature"``) that opponent controls -- with two players "they
    control" is "an opponent controls". On resolution the opponent's
    hand is revealed to the controller; the controller may exile ONE
    object: a matching hand card (it returns to its owner's hand when
    the source leaves -- Deep-Cavern Bat's ``exiled_until_leaves_from_hand``
    link) or the chosen creature (it returns to the battlefield -- the
    Oblivion-Ring ``exiled_by_source`` link). The pick among both kinds
    goes through the generic id picker ``choose_card_from_library``
    after a ``choose_yes_no`` consent. If the source already left the
    battlefield, nothing is exiled (CR 610.3c)."""

    card_filter: object = None

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (1, 2)

    def target_slot_kinds(self) -> tuple[str, ...]:
        return ("player", "creature")

    def legal_targets(self, state, controller_id):
        from mtg_bot.game import is_creature_now

        out: list[Target] = [
            ("player", p.id) for p in state.players
            if not p.has_lost and p.id != controller_id
        ]
        out.extend(
            ("creature", o.id) for o in state.battlefield
            if is_creature_now(o) and o.controller_id != controller_id
        )
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, reveal_to
        from mtg_bot.turn import move_off_battlefield

        opp = next(
            (state.player_by_id(t[1]) for t in targets if t[0] == "player"),
            None,
        )
        if opp is None or opp.has_lost:
            return
        for c in opp.hand:
            reveal_to(c, controller_id)
        src = state.resolving_source
        if src is None or src not in state.battlefield:
            return
        creature = next(
            (
                o for t in targets if t[0] == "creature"
                for o in state.battlefield
                if o.id == t[1] and o.controller_id == opp.id
            ),
            None,
        )
        options = [
            c for c in opp.hand
            if self.card_filter is None or self.card_filter.matches(c.printing)
        ]
        choices = [c.id for c in options]
        if creature is not None:
            choices.append(creature.id)
        if not choices:
            return
        me = state.player_by_id(controller_id)
        pick = choices[0]
        if me.agent is not None:
            if not me.agent.choose_yes_no(
                state, controller_id,
                "exile a card from their hand or the chosen creature until "
                "this leaves?",
            ):
                return
            picked = me.agent.choose_card_from_library(
                state, controller_id, choices,
            )
            if picked in choices:
                pick = picked
        if creature is not None and pick == creature.id:
            creature.exiled_by_source = src.id
            state.log.append(
                f"{creature.printing.name} is exiled until "
                f"{src.printing.name} leaves the battlefield"
            )
            move_off_battlefield(state, creature, destination="exile")
            return
        card = next(c for c in options if c.id == pick)
        opp.hand.remove(card)
        card.zone = Zone.EXILE
        card.exiled_by_source = src.id
        card.exiled_until_leaves_from_hand = True
        opp.exile.append(card)
        state.log.append(
            f"P{controller_id} exiles {card.printing.name} from P{opp.id}'s "
            f"hand until {src.printing.name} leaves the battlefield"
        )

    def describe(self) -> str:
        return (
            "choose target opponent and up to one target creature they "
            "control; they reveal their hand; you may exile a card from it "
            "or the chosen creature until this leaves the battlefield"
        )
