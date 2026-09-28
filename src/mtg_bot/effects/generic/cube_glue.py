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


# ---------------------------------------------------------------------------
# Graveyard -> hand for any card descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnTargetGraveyardCardToHand(Effect):
    """"Return [up to one ]target <descriptor> card from your graveyard
    to your hand." for any ``CardFilter`` descriptor (Wrenn and Six's
    "up to one target land card", Tamiyo, Collector of Tales' "target
    card"). Targets are ``("graveyard_card", id)``; a target that left
    the graveyard before resolution does nothing."""

    card_filter: object = None
    optional: bool = False

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (0 if self.optional else 1, 1)

    def legal_targets(self, state, controller_id):
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_card", c.id) for c in p.graveyard
            if self.card_filter is None or self.card_filter.matches(c.printing)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, reveal_to_all

        p = state.player_by_id(controller_id)
        for kind, tid in targets:
            if kind != "graveyard_card":
                continue
            card = next((c for c in p.graveyard if c.id == tid), None)
            if card is None:
                continue
            p.graveyard.remove(card)
            card.zone = Zone.HAND
            p.hand.append(card)
            reveal_to_all(state, card)
            state.log.append(
                f"{card.printing.name} returns from P{controller_id}'s "
                f"graveyard to hand"
            )

    def describe(self) -> str:
        upto = "up to one " if self.optional else ""
        return f"return {upto}target card from your graveyard to your hand"


# ---------------------------------------------------------------------------
# "Exile the top card of your library. You may cast that card. If you
# don't, <effect>." (Chandra, Torch of Defiance)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExileTopCardMayCastOtherwise(Effect):
    """Exile the top card of the controller's library; the controller may
    cast it right now (paying its costs -- the U/B bucket's
    ``creature_casting_ub.cast_now``: the spell goes on the stack above
    this ability, timing restrictions don't apply). If they don't
    (declined, a land, uncastable, or nothing was exiled), ``otherwise``
    resolves. An uncast card stays in exile with no permission."""

    otherwise: Effect | None = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.creature_casting_ub import can_cast_now, cast_now
        from mtg_bot.effects.generic.cube_creatures_rmc import exile_card

        p = state.player_by_id(controller_id)
        cast = False
        if p.library:
            card = p.library.pop(0)
            exile_card(state, card)
            state.log.append(
                f"P{controller_id} exiles {card.printing.name} from the top "
                f"of their library"
            )
            if (
                can_cast_now(state, controller_id, card, free=False)
                and (
                    p.agent is None
                    or p.agent.choose_yes_no(
                        state, controller_id, f"cast {card.printing.name}?",
                    )
                )
            ):
                cast = cast_now(state, controller_id, card, free=False)
        if not cast and self.otherwise is not None:
            self.otherwise.resolve(state, controller_id, ())

    def describe(self) -> str:
        tail = (
            f"; if you don't, {self.otherwise.describe()}"
            if self.otherwise is not None else ""
        )
        return (
            "exile the top card of your library; you may cast that card"
            + tail
        )


# ---------------------------------------------------------------------------
# "Choose a nonland card name, then reveal the top N cards of your
# library. Put all cards with the chosen name from among them into your
# hand and the rest into your graveyard." (Tamiyo, Collector of Tales)
# ---------------------------------------------------------------------------

NAME_NOT_IN_LIBRARY = "(a card name not in your library)"


@dataclass(frozen=True)
class ChooseNameRevealTopPutNamedIntoHand(Effect):
    """The name is chosen through ``choose_mode`` over the distinct
    (nonland, when ``nonland``) names in the controller's library plus
    one entry standing for any other name -- the spells-B bucket's
    Demonic Consultation convention (naming a card that isn't in the
    library is equivalent to naming any other absent card). The top
    ``count`` cards are revealed; every card with the chosen name goes
    to the hand, the rest to the graveyard."""

    count: int = 4
    nonland: bool = True

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, reveal_to_all

        p = state.player_by_id(controller_id)
        names = sorted({
            c.printing.name for c in p.library
            if not (self.nonland and c.printing.is_land)
        })
        options = names + [NAME_NOT_IN_LIBRARY]
        idx = len(options) - 1
        if p.agent is not None:
            picked = p.agent.choose_mode(state, controller_id, options)
            if isinstance(picked, int) and 0 <= picked < len(options):
                idx = picked
        chosen = options[idx]
        state.log.append(f"P{controller_id} names {chosen}")
        revealed = p.library[: self.count]
        del p.library[: self.count]
        to_hand = 0
        for c in revealed:
            reveal_to_all(state, c)
            if c.printing.name == chosen:
                c.zone = Zone.HAND
                p.hand.append(c)
                to_hand += 1
            else:
                c.zone = Zone.GRAVEYARD
                p.graveyard.append(c)
        state.log.append(
            f"P{controller_id} reveals {len(revealed)} card(s); {to_hand} "
            f"named card(s) to hand, the rest to the graveyard"
        )

    def describe(self) -> str:
        kind = "nonland " if self.nonland else ""
        return (
            f"choose a {kind}card name; reveal the top {self.count} cards; "
            f"put the named ones into your hand and the rest into your "
            f"graveyard"
        )


# ---------------------------------------------------------------------------
# "At the beginning of your next main phase" delayed mana (Mana Drain) and
# counter-removal mana (Coalition Relic)
# ---------------------------------------------------------------------------


def stack_spell_mana_value(item) -> int:
    """Mana value of a spell on the stack (CR 202.3e: X counts)."""
    cost = item.source.printing.mana_cost
    return cost.total + cost.x_pips * max(0, item.x_value)


@dataclass(frozen=True)
class CounterThenDelayedManaEqualToMV(Effect):
    """"Counter target spell. At the beginning of your next main phase,
    add an amount of {<color>} equal to that spell's mana value." (Mana
    Drain.) ``counter`` is the parsed counter effect; its target is this
    effect's target. The countered spell's mana value is taken as it
    last existed on the stack (X included). If the spell wasn't
    countered (it left the stack, or can't be countered) no delayed
    trigger is created. The delayed trigger is a
    ``state.delayed_triggers`` entry with ``"step": "main"``, fired by
    ``turn.run_delayed_main_phase_triggers`` at the controller's next
    main phase (both turn loops)."""

    counter: Effect | None = None
    color: str = "C"

    def requires_target(self) -> bool:
        return self.counter.requires_target()

    def legal_targets(self, state, controller_id):
        return self.counter.legal_targets(state, controller_id)

    def target_count_range(self):
        return self.counter.target_count_range()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.mana import AddManaToPool

        item = None
        if targets and targets[0][0] == "stack":
            idx = targets[0][1]
            if 0 <= idx < len(state.stack):
                item = state.stack[idx]
        was_countered = item is not None and item.countered
        self.counter.resolve(state, controller_id, targets)
        if item is None or was_countered or not item.countered:
            return
        mv = stack_spell_mana_value(item)
        source = state.resolving_spell or state.resolving_source
        state.delayed_triggers.append({
            "step": "main",
            "controller_id": controller_id,
            "source_id": source.id if source is not None else None,
            "effect": AddManaToPool(produces=((self.color, mv),)),
            "fire_at_turn": state.turn_number,
        })
        state.log.append(
            f"P{controller_id} will add {mv} {{{self.color}}} at the "
            f"beginning of their next main phase"
        )

    def describe(self) -> str:
        return (
            f"{self.counter.describe()}; at the beginning of your next main "
            f"phase, add {{{self.color}}} equal to that spell's mana value"
        )


@dataclass(frozen=True)
class RemoveAllCountersAddManaPerCounter(Effect):
    """"Remove all <kind> counters from this <permanent>. Add one mana of
    any color for each <kind> counter removed this way." (Coalition
    Relic.) The mana is ``any``-color coins (the engine's one-mana-of-
    any-color convention)."""

    kind: str = "charge"

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.mana import AddManaToPool
        from mtg_bot.game import counter_count, remove_counters

        src = state.resolving_source
        if src is None or src not in state.battlefield:
            return
        n = counter_count(src, self.kind)
        removed = remove_counters(src, self.kind, n) if n else 0
        state.log.append(
            f"{src.printing.name}: removes {removed} {self.kind} counter(s)"
        )
        if removed:
            AddManaToPool(produces=(("any", removed),)).resolve(
                state, controller_id,
            )

    def describe(self) -> str:
        return (
            f"remove all {self.kind} counters from this permanent; add one "
            f"mana of any color for each"
        )
