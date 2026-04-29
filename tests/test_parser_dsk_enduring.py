"""Tests for the DSK Enduring cycle dies-trigger.

The Enduring cycle (Innocence W, Curiosity U, Tenacity B, Courage R,
Vitality G) prints a shared ``"When this creature dies, if it was a
creature, return it to the battlefield under its owner's control. It's
an enchantment."`` rider on each creature. This batch lands the cycle's
parser/engine plumbing:

- ``GameObject.enduring_returned_as_enchantment`` flag — sticky per-
  instance marker that suppresses the printed Creature card type at
  runtime via ``is_creature_now``. Mirrors the ``impending_active``
  precedent (printing keeps the type, GameObject suppresses it).
- ``EnduringDiesReturnAsEnchantmentEffect`` — bespoke parameterless
  Effect class that reads ``state.resolving_source`` to locate the
  dying card in its owner's graveyard, moves it back onto the
  battlefield under the owner's control, and sets the new flag.
  Mirrors the ``PerigeeBeckonerDiesReturnTappedEffect`` precedent.
- ``"it was a creature"`` intervening-if gate phrase → ``IsCreature()``
  predicate. Composes onto the ``IsSelf()`` base predicate of the
  ``"this creature dies"`` self-trigger via the existing
  intervening-if path.
- ``return it to the battlefield under its owner's control. It's an
  enchantment`` effect-phrase regex → the new bespoke effect class.

Of the five Enduring printings, ``Enduring Curiosity`` claims end-to-
end via these additions alone — its non-dies trigger
(``"Whenever a creature you control deals combat damage to a player,
draw a card."``) was already supported. The four other cards
(Innocence, Tenacity, Courage, Vitality) carry additional printed
clauses (aggregate "one or more" enters trigger, gain-life trigger,
"another creature you control enters" trigger with subject pump,
mana-ability anthem static) that need grammar/event additions outside
the Enduring cycle's scope — those land in the parallel
creatures-batch-4 / spells-batch-4 work and the four cards stay
unclaimed end-to-end on this branch.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DrawCards,
    EnduringDiesReturnAsEnchantmentEffect,
    TriggeredAbility,
)
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.effects.object_predicates import (
    IsCreature,
    IsPlayer,
)
from mtg_bot.effects.predicates import (
    Controlled,
    Event,
    IsSelf,
    StateBound,
    Subject,
    YOU,
)


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- effect-phrase grammar ----------


def test_parse_enduring_dies_return_as_enchantment_body():
    # Bare effect-phrase parse for the Enduring cycle's shared body.
    # The phrase appears inside an intervening-if line and the
    # parenthesized ``(It's not a creature.)`` reminder is stripped
    # before this dispatcher runs, so the regex matches the two-
    # sentence body verbatim.
    phrase = (
        "return it to the battlefield under its owner's control. "
        "It's an enchantment"
    )
    assert _parse_effect_phrase(phrase) == (
        EnduringDiesReturnAsEnchantmentEffect()
    )


def test_parse_enduring_body_unrelated_text_rejects():
    # A near-miss phrase that drops the "It's an enchantment" tail must
    # NOT be claimed by the new regex — the bare graveyard-return
    # primitive is a different engine class. Belt-and-suspenders that
    # the new grammar entry didn't accidentally widen the dispatcher.
    phrase = (
        "return it to the battlefield under its owner's control"
    )
    assert _parse_effect_phrase(phrase) is None


# ---------- intervening-if trigger-line end-to-end ----------


def test_parse_enduring_dies_trigger_line():
    # End-to-end through the trigger-line parser. The intervening-if
    # path composes the gate predicate (``IsCreature()``) onto the
    # base predicate of ``"this creature dies"`` (``IsSelf()``) via
    # plain ``And``, mirroring the Delirium / Void gate precedents.
    # The ``Enduring Curiosity`` name is substituted with
    # ``"this creature"`` by ``_substitute_self_name`` before the
    # condition phrase is looked up.
    line = (
        "When Enduring Curiosity dies, if it was a creature, "
        "return it to the battlefield under its owner's control. "
        "It's an enchantment."
    )
    parsed = _parse_triggered_ability_line(line, name="Enduring Curiosity")
    assert parsed == TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf() & Subject(None, IsCreature()),
        effect=EnduringDiesReturnAsEnchantmentEffect(),
    )


def test_parse_enduring_dies_trigger_line_innocence():
    # Same shape against a different printing's name — the substitution
    # rewrites both the full name and the canonical surface, so every
    # Enduring printing's dies trigger maps to the same
    # ``TriggeredAbility``. Belt-and-suspenders that the
    # ``_substitute_self_name`` step generalizes across the cycle.
    line = (
        "When Enduring Innocence dies, if it was a creature, "
        "return it to the battlefield under its owner's control. "
        "It's an enchantment."
    )
    parsed = _parse_triggered_ability_line(line, name="Enduring Innocence")
    assert parsed == TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf() & Subject(None, IsCreature()),
        effect=EnduringDiesReturnAsEnchantmentEffect(),
    )


def test_parse_enduring_intervening_if_unknown_gate_rejects():
    # A near-miss intervening-if line whose gate phrase isn't in the
    # phrasebook rejects outright — the don't-silently-drop-the-gate
    # discipline is preserved. Belt-and-suspenders that adding the
    # ``"it was a creature"`` entry didn't widen the gate dispatcher
    # to accept arbitrary phrases.
    line = (
        "When this creature dies, if there's a moon, "
        "return it to the battlefield under its owner's control. "
        "It's an enchantment."
    )
    assert _parse_triggered_ability_line(line) is None


# ---------- Effect resolution semantics ----------


def test_enduring_effect_returns_card_to_owners_battlefield():
    # The resolve path moves the dying card from its owner's graveyard
    # to its OWNER's battlefield (per oracle — "owner's control", not
    # "your control") and sets the
    # ``enduring_returned_as_enchantment`` flag. We simulate the post-
    # death state by hand-placing the card in the graveyard and
    # invoking ``resolve`` with ``state.resolving_source`` set.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(bear)
    state.resolving_source = bear
    try:
        EnduringDiesReturnAsEnchantmentEffect().resolve(
            state, controller_id=0,
        )
    finally:
        state.resolving_source = None
    assert bear in state.battlefield
    assert bear.zone == Zone.BATTLEFIELD
    assert bear not in state.players[0].graveyard
    assert bear.controller_id == 0
    assert bear.enduring_returned_as_enchantment is True


def test_enduring_effect_routes_to_owner_not_resolver():
    # Even if the effect resolves under a different controller's id
    # (the dying creature was stolen mid-combat and graveyarded under
    # the thief's pile), the returned permanent goes back to its
    # OWNER's battlefield. We verify by passing a different
    # ``controller_id`` to ``resolve`` than the bear's ``owner_id``;
    # the effect ignores the resolver-controller and routes by owner.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(bear)
    state.resolving_source = bear
    try:
        # Resolver-controller is P1 — but the bear's owner is P0, so
        # the bear lands on P0's battlefield with controller P0.
        EnduringDiesReturnAsEnchantmentEffect().resolve(
            state, controller_id=1,
        )
    finally:
        state.resolving_source = None
    assert bear in state.battlefield
    assert bear.controller_id == 0
    assert bear.enduring_returned_as_enchantment is True


def test_enduring_effect_no_op_if_source_not_in_graveyard():
    # If the dying card has already left the graveyard (replaced by an
    # exile, dredged into the library, etc.) the resolve is a clean
    # no-op rather than a crash. Mirrors the
    # ``PerigeeBeckonerDiesReturnTappedEffect`` precedent.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.EXILE,
    )
    # Note: NOT appended to graveyard; the bear is "elsewhere".
    state.resolving_source = bear
    try:
        EnduringDiesReturnAsEnchantmentEffect().resolve(
            state, controller_id=0,
        )
    finally:
        state.resolving_source = None
    assert bear not in state.battlefield


def test_enduring_effect_no_op_if_no_resolving_source():
    # When the engine somehow invokes the resolve without a
    # ``state.resolving_source`` (defensive — never happens via the
    # standard dies-dispatch path), the effect is a clean no-op.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.resolving_source = None
    EnduringDiesReturnAsEnchantmentEffect().resolve(state, controller_id=0)
    # No crash, no battlefield mutation.
    assert state.battlefield == []


def test_enduring_effect_no_op_for_token_source():
    # Tokens cease to exist on death (CR 704.5d). If somehow a token
    # had this dies-rider (e.g. a future card grants it), the resolve
    # path declines to bring it back. Mirrors the Perigee Beckoner
    # token guard.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    drone = state.new_object(
        TOKEN_PRINTINGS["Drone"], owner_id=0, zone=Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(drone)
    state.resolving_source = drone
    try:
        EnduringDiesReturnAsEnchantmentEffect().resolve(
            state, controller_id=0,
        )
    finally:
        state.resolving_source = None
    assert drone not in state.battlefield
    # Token stays in the graveyard pile (the engine's separate token
    # cleanup will remove it; the Enduring effect just declines to
    # touch it).


def test_enduring_effect_describe():
    # The describe output spells out the card's printed return-as-
    # enchantment body so log lines are readable. Lowercase to match
    # the convention of every other effect's describe in this engine.
    eff = EnduringDiesReturnAsEnchantmentEffect()
    assert eff.describe() == (
        "return it to the battlefield under its owner's control. "
        "it's an enchantment"
    )


# ---------- ``enduring_returned_as_enchantment`` flag semantics ----------


def test_is_creature_now_false_with_enduring_flag():
    # The new flag short-circuits ``is_creature_now`` to False, so the
    # returned permanent counts as an enchantment only. The printing
    # still has "Creature" in card_types — the suppression is per-
    # instance, mirroring ``impending_active``.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone, is_creature_now

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    # Sanity: a vanilla creature reads as a creature.
    assert is_creature_now(bear) is True
    bear.enduring_returned_as_enchantment = True
    # After the flag is set, the same printing reads as a non-creature.
    assert is_creature_now(bear) is False
    # Printing's card_types is unchanged — the suppression is per-
    # instance.
    assert "Creature" in bear.printing.card_types


def test_is_creature_now_face_down_takes_precedence_over_enduring():
    # CR 701.34: a face-down permanent is always a 2/2 creature. The
    # face-down branch in ``is_creature_now`` short-circuits FIRST —
    # before any other suppression / activation reads — so a face-down
    # permanent reads as a creature even if the Enduring flag is set
    # (an unrealistic combination, but the precedence is well-defined).
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone, is_creature_now

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    bear.face_down = True
    bear.enduring_returned_as_enchantment = True
    assert is_creature_now(bear) is True


# ---------- end-to-end claim ----------


def test_enduring_curiosity_claimed_by_parser():
    # Enduring Curiosity ``{2}{U}{U}`` 4/3 Enchantment Creature — Cat
    # Glimmer. Three oracle lines:
    #
    # 1. ``Flash`` (existing keyword grammar)
    # 2. ``Whenever a creature you control deals combat damage to a
    #    player, draw a card.`` (existing predicate-trigger phrase)
    # 3. ``When Enduring Curiosity dies, if it was a creature, return
    #    it to the battlefield under its owner's control. It's an
    #    enchantment. (It's not a creature.)`` (NEW intervening-if
    #    gate phrase + NEW effect-phrase regex feeding the new
    #    ``EnduringDiesReturnAsEnchantmentEffect`` engine class)
    #
    # Every Enduring printing carries the same dies trigger; Curiosity
    # is the one whose other lines are already supported by the
    # parser, so it's the cycle's end-to-end claim on this branch.
    # The other four cards (Innocence, Tenacity, Courage, Vitality)
    # stay unclaimed pending grammar additions outside the Enduring
    # cycle's scope.
    assert "Enduring Curiosity" in _claimed_names()


def test_enduring_curiosity_carries_dies_trigger():
    # Belt-and-suspenders that the claimed printing actually carries
    # the Enduring dies trigger with the gate predicate composed onto
    # the IsSelf base. Otherwise the engine wouldn't return the card
    # as an enchantment when it dies.
    src = OracleParserCardSource()
    p = src.get_printings()["Enduring Curiosity"]
    dies = [
        ab for ab in p.triggered_abilities
        if ab.event == Event.DIES
    ]
    assert len(dies) == 1
    assert dies[0] == TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf() & Subject(None, IsCreature()),
        effect=EnduringDiesReturnAsEnchantmentEffect(),
    )


def test_enduring_curiosity_carries_combat_damage_trigger():
    # Belt-and-suspenders that the claimed printing carries the
    # printed non-dies trigger (combat damage to a player → draw a
    # card). Otherwise the parser would have silently dropped a
    # printed clause, which would violate the parser-is-right rule.
    src = OracleParserCardSource()
    p = src.get_printings()["Enduring Curiosity"]
    cd = [
        ab for ab in p.triggered_abilities
        if ab.event == Event.DEALS_COMBAT_DAMAGE
    ]
    assert len(cd) == 1
    assert cd[0].effect == DrawCards(amount=1)
    # Predicate composes "creature you control source" + "player target".
    assert cd[0].predicate == (
        Subject("source", IsCreature())
        & Controlled(YOU, subject="source")
        & Subject("target", IsPlayer())
    )


def test_enduring_curiosity_carries_flash_keyword():
    # The Flash keyword line is a separate clause from the trigger
    # bodies; verify it survives end-to-end so the engine surfaces
    # the printing at instant speed.
    src = OracleParserCardSource()
    p = src.get_printings()["Enduring Curiosity"]
    assert "flash" in p.keywords


# ---------- engine path: dies dispatch fires the Enduring trigger ----------


def test_enduring_dies_via_engine_path_returns_as_enchantment():
    # End-to-end through the engine's dies dispatch: a permanent with
    # the Enduring dies-trigger goes to the graveyard via
    # ``move_off_battlefield``, the predicate-style ``Event.DIES``
    # dispatcher pushes the trigger onto the stack, and resolving
    # the stack item brings the card back to the battlefield with
    # ``enduring_returned_as_enchantment=True``.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import GameState, Player, Zone, is_creature_now
    from mtg_bot.turn import move_off_battlefield

    src = OracleParserCardSource()
    curiosity_p = src.get_printings()["Enduring Curiosity"]

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    obj = state.new_object(curiosity_p, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    # Sanity: while on the battlefield, it's a creature.
    assert is_creature_now(obj) is True

    # Send it to the graveyard (simulates lethal damage / destroy).
    # The dies dispatch fires here and pushes the Enduring trigger
    # onto the stack.
    move_off_battlefield(state, obj, destination="graveyard")
    assert obj in state.players[0].graveyard
    assert obj not in state.battlefield
    # The combat-damage trigger doesn't fire on dies — only the
    # dies-trigger goes on the stack.
    assert len(state.stack) == 1

    # Resolve the trigger; the card returns to its owner's battlefield
    # as an enchantment.
    resolve_top_of_stack(state)
    assert obj in state.battlefield
    assert obj.controller_id == 0
    assert obj.enduring_returned_as_enchantment is True
    # The printed Creature card type is suppressed at runtime; the
    # returned permanent reads as an enchantment only.
    assert is_creature_now(obj) is False


def test_enduring_second_death_does_not_re_fire():
    # Once the card has returned as an enchantment, a hypothetical
    # second death (it gets destroyed somehow) does NOT fire the
    # dies-trigger again — the engine's
    # ``move_off_battlefield`` ``was_creature`` gate reads False
    # after the flag is set, so the predicate-style DIES dispatch
    # is skipped entirely. Belt-and-suspenders against the cycle
    # accidentally chaining returns indefinitely.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import move_off_battlefield

    src = OracleParserCardSource()
    curiosity_p = src.get_printings()["Enduring Curiosity"]

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    obj = state.new_object(curiosity_p, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    obj.enduring_returned_as_enchantment = True

    # The card is now an enchantment-only permanent. Send it to the
    # graveyard.
    move_off_battlefield(state, obj, destination="graveyard")
    # No dies-trigger fired — the stack is empty after the move.
    assert state.stack == []
    # The card stays in the graveyard.
    assert obj in state.players[0].graveyard
