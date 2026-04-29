"""Tests for the DSK Rooms mechanic — engine + parser claims.

Covers:

- ``RoomHalf`` dataclass + ``make_room`` factory.
- ``CardPrinting.is_room`` / ``room_halves`` field plumbing.
- ``GameObject.unlocked_halves`` set.
- ``CastSpell(card_id, cast_room_half=...)`` — paying the chosen
  half's cost, the entering Room is unlocked on that half.
- ``UnlockRoomHalf`` action — sorcery speed, pays the locked half's
  cost, adds to ``unlocked_halves``, fires "When you unlock this
  door" triggers, logs ``"Room fully unlocked"`` on the transition.
- Ability gating: triggered abilities tagged with a ``room_half``
  are inert while that half is locked. Unlocking the half makes
  them active.
- ``legal_actions`` surfaces ``CastSpell`` per half whose cost is
  payable, and ``UnlockRoomHalf`` per locked half on Rooms the
  player controls.
- Parser claims for the two Rooms wired in this round
  (``Funeral Room // Awakening Hall``,
  ``Glassworks // Shattered Yard``).
"""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    UnlockRoomHalf,
    apply_action,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import (
    BASIC_LANDS,
    SYNTHETIC_CREATURES,
    RoomHalf,
    TriggeredAbility,
    make_room,
    parse_mana_cost,
)
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.effects import (
    DealDamageEachOpponent,
    DrawCards,
    GainLife,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsCreature,
    IsSelf,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import sacrifice
from mtg_bot.turn import Step
from mtg_bot.cards.source import get_active_source


_PARSER_PRINTINGS = OracleParserCardSource().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]

    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None

    def choose_surveil(self, state, player_id, top_card_id):
        return False  # don't mill — keep on top


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_battlefield(state, printing, controller_id=0, owner_id=None):
    if owner_id is None:
        owner_id = controller_id
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller_id
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def _put_hand(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.HAND)
    state.players[owner_id].hand.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Tiny synthetic Room used by most engine tests
# ---------------------------------------------------------------------------

# Half A: ETB-self trigger that draws a card. Cheap enough to cast
# off two basics.
# Half B: end-step trigger that pings each opponent for 1.
def _toy_room():
    return make_room(
        RoomHalf(
            name="Reading Nook",
            mana_cost_str="{W}",
            mana_cost=parse_mana_cost("{W}"),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        RoomHalf(
            name="Boiler Room",
            mana_cost_str="{R}",
            mana_cost=parse_mana_cost("{R}"),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_END_STEP,
                    predicate=Controlled(YOU),
                    effect=DealDamageEachOpponent(amount=1),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Dataclass + factory
# ---------------------------------------------------------------------------


def test_make_room_combines_names_and_costs():
    room = _toy_room()
    assert room.name == "Reading Nook // Boiler Room"
    assert room.is_room
    assert "Room" in room.subtypes
    assert "Enchantment" in room.card_types
    assert len(room.room_halves) == 2
    # Combined mana_cost is the sum of both halves.
    assert room.mana_cost.colored == (("R", 1), ("W", 1))
    assert room.mana_cost_str == "{W} // {R}"


def test_room_half_abilities_tagged_on_parent():
    room = _toy_room()
    # Each half's triggered ability is flattened onto the parent
    # printing, tagged with room_half=<half-name>.
    by_half = {a.room_half for a in room.triggered_abilities}
    assert by_half == {"Reading Nook", "Boiler Room"}


# ---------------------------------------------------------------------------
# CastSpell with cast_room_half
# ---------------------------------------------------------------------------


def test_cast_room_pays_chosen_half_cost():
    state = _new_state()
    room_card = _put_hand(state, _toy_room(), owner_id=0)
    # Two Plains; we cast for Reading Nook ({W}) — should tap exactly one.
    plains_a = _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    plains_b = _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)

    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Reading Nook"),
    )
    # One Plains tapped, one still untapped.
    tapped = sum(1 for o in [plains_a, plains_b] if o.tapped)
    assert tapped == 1
    # Spell on the stack with the chosen half captured.
    assert len(state.stack) == 1
    assert state.stack[0].cast_room_half == "Reading Nook"


def test_cast_room_resolves_with_chosen_half_unlocked():
    state = _new_state()
    room_card = _put_hand(state, _toy_room(), owner_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Reading Nook"),
    )
    drain_stack(state)
    # Room is on the battlefield with Reading Nook unlocked.
    bf_room = next(o for o in state.battlefield if o.id == room_card.id)
    assert bf_room.unlocked_halves == frozenset({"Reading Nook"})
    # ETB trigger on Reading Nook fired (drew a card from an empty
    # library — the player would draw zero cards if no library, but
    # the event itself logs).
    assert any(
        "Reading Nook" in line and "unlocked" in line
        for line in state.log
    )


# ---------------------------------------------------------------------------
# Ability gating: locked halves' abilities are inert
# ---------------------------------------------------------------------------


def test_locked_half_trigger_does_not_fire_at_etb():
    state = _new_state()
    room_card = _put_hand(state, _toy_room(), owner_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    # Cast Boiler Room; Reading Nook is locked. Reading Nook's ETB
    # draw trigger must NOT fire.
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    pre_hand = len(state.players[0].hand)
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Boiler Room"),
    )
    drain_stack(state)
    # Hand size unchanged: Boiler Room half doesn't draw, and Reading
    # Nook's draw trigger was gated off.
    bf_room = next(o for o in state.battlefield if o.id == room_card.id)
    assert "Reading Nook" not in bf_room.unlocked_halves
    # Hand still contains 0 newly drawn cards (only the room is now
    # off the hand).
    assert len(state.players[0].hand) == pre_hand - 1


# ---------------------------------------------------------------------------
# UnlockRoomHalf action
# ---------------------------------------------------------------------------


def test_unlock_pays_cost_and_marks_unlocked():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Reading Nook"})
    plains = _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    pre_log = len(state.log)
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Boiler Room"),
    )
    assert plains.tapped
    assert "Boiler Room" in room.unlocked_halves
    assert "Reading Nook" in room.unlocked_halves
    assert any("fully unlocked" in line for line in state.log[pre_log:])


def test_unlock_already_unlocked_is_noop():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Reading Nook"})
    plains = _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Reading Nook"),
    )
    # No mana spent; still just the one half.
    assert not plains.tapped
    assert room.unlocked_halves == frozenset({"Reading Nook"})


def test_unlock_unknown_half_is_noop():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Reading Nook"})
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Nonexistent"),
    )
    assert room.unlocked_halves == frozenset({"Reading Nook"})


def test_unlock_not_a_room_is_noop():
    state = _new_state()
    bear = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0)
    apply_action(
        state, 0, UnlockRoomHalf(card_id=bear.id, half_name="X"),
    )
    # No-op: Wild Bear is not a Room.
    assert bear.unlocked_halves == frozenset()


def test_unlock_not_your_room_is_noop():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=1)
    room.unlocked_halves = frozenset({"Reading Nook"})
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Boiler Room"),
    )
    assert "Boiler Room" not in room.unlocked_halves


def test_unlock_without_mana_is_noop():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Reading Nook"})
    # No mountains on the battlefield — Boiler Room costs {R} we can't pay.
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Boiler Room"),
    )
    assert "Boiler Room" not in room.unlocked_halves


# ---------------------------------------------------------------------------
# legal_actions surfaces UnlockRoomHalf and per-half CastSpell
# ---------------------------------------------------------------------------


def test_legal_actions_per_half_cast():
    state = _new_state()
    room_card = _put_hand(state, _toy_room(), owner_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    actions = legal_actions(state, 0)
    casts = [
        a for a in actions
        if isinstance(a, CastSpell) and a.card_id == room_card.id
    ]
    halves = {a.cast_room_half for a in casts}
    assert halves == {"Reading Nook", "Boiler Room"}


def test_legal_actions_only_payable_halves():
    state = _new_state()
    room_card = _put_hand(state, _toy_room(), owner_id=0)
    # Only a Plains: only Reading Nook ({W}) is payable.
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    actions = legal_actions(state, 0)
    casts = [
        a for a in actions
        if isinstance(a, CastSpell) and a.card_id == room_card.id
    ]
    halves = {a.cast_room_half for a in casts}
    assert halves == {"Reading Nook"}


def test_legal_actions_unlock_appears():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Reading Nook"})
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    actions = legal_actions(state, 0)
    unlocks = [a for a in actions if isinstance(a, UnlockRoomHalf)]
    assert len(unlocks) == 1
    assert unlocks[0].card_id == room.id
    assert unlocks[0].half_name == "Boiler Room"


def test_legal_actions_unlock_skipped_for_locked_unpayable():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Reading Nook"})
    # No Mountain — Boiler Room ({R}) unpayable.
    actions = legal_actions(state, 0)
    unlocks = [a for a in actions if isinstance(a, UnlockRoomHalf)]
    assert unlocks == []


# ---------------------------------------------------------------------------
# Unlocking a half fires the half's "When you unlock this door" trigger
# ---------------------------------------------------------------------------


def test_unlock_fires_door_trigger():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Boiler Room"})
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    pre_hand = len(state.players[0].hand)
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Reading Nook"),
    )
    drain_stack(state)
    # Reading Nook's ETB-style trigger fired — drew a card.
    assert len(state.players[0].hand) == pre_hand + 1


# ---------------------------------------------------------------------------
# Parser claims
# ---------------------------------------------------------------------------


def test_parser_claims_funeral_room_awakening_hall():
    name = "Funeral Room // Awakening Hall"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Funeral Room", "Awakening Hall"}
    # Half costs.
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Funeral Room"].mana_cost_str == "{2}{B}"
    assert by_name["Awakening Hall"].mana_cost_str == "{6}{B}{B}"
    # Each half contributes one trigger; both are tagged.
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Awakening Hall", "Funeral Room"]


def test_parser_claims_glassworks_shattered_yard():
    name = "Glassworks // Shattered Yard"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Glassworks", "Shattered Yard"}


def test_room_builder_skips_non_rooms():
    from mtg_bot.cards.parser.room_builder import _build_room_printing
    card = {
        "name": "Banishing Light",
        "type_line": "Enchantment",
        "oracle_text": "",
    }
    assert _build_room_printing(card) is None


def test_room_builder_skips_unknown_room():
    from mtg_bot.cards.parser.room_builder import _build_room_printing
    card = {
        "name": "Smoky Lounge // Misty Salon",
        "type_line": "Enchantment — Room // Enchantment — Room",
        "oracle_text": "",
    }
    # Not in our claim table yet.
    assert _build_room_printing(card) is None


# ---------------------------------------------------------------------------
# Behavioral: Funeral Room dies-trigger drains opponents
# ---------------------------------------------------------------------------


def test_funeral_room_drains_on_creature_dies():
    state = _new_state()
    room = _put_battlefield(
        state, _PARSER_PRINTINGS["Funeral Room // Awakening Hall"],
        controller_id=0,
    )
    # Cast for Funeral Room: that's the half that's unlocked.
    room.unlocked_halves = frozenset({"Funeral Room"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    pre_my_life = state.players[0].life
    pre_opp_life = state.players[1].life
    sacrifice(state, bear)
    drain_stack(state)
    assert state.players[1].life == pre_opp_life - 1
    assert state.players[0].life == pre_my_life + 1


def test_funeral_room_locked_does_not_fire():
    state = _new_state()
    room = _put_battlefield(
        state, _PARSER_PRINTINGS["Funeral Room // Awakening Hall"],
        controller_id=0,
    )
    # Awakening Hall is unlocked instead — Funeral Room locked.
    room.unlocked_halves = frozenset({"Awakening Hall"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    pre_my_life = state.players[0].life
    pre_opp_life = state.players[1].life
    sacrifice(state, bear)
    drain_stack(state)
    # Locked half's drain trigger did NOT fire.
    assert state.players[1].life == pre_opp_life
    assert state.players[0].life == pre_my_life


# ---------------------------------------------------------------------------
# Behavioral: Glassworks ETB pings on unlock; Shattered Yard pings end step
# ---------------------------------------------------------------------------


def test_glassworks_etb_damages_target_creature():
    state = _new_state()
    enemy = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    # Cast Glassworks — half unlocked, ETB trigger targets enemy.
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Glassworks // Shattered Yard"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Glassworks"),
    )
    drain_stack(state)
    assert enemy.damage == 4 or enemy not in state.battlefield


def test_shattered_yard_locked_doesnt_ping():
    """Shattered Yard's end-step ping is gated on its half being
    unlocked. With only Glassworks unlocked, the end-step trigger
    does not fire."""
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Glassworks // Shattered Yard"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Glassworks"})
    pre_opp_life = state.players[1].life
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert state.players[1].life == pre_opp_life


# ---------------------------------------------------------------------------
# Parser claims: Grand Entryway // Elegant Rotunda
# ---------------------------------------------------------------------------


def test_parser_claims_grand_entryway_elegant_rotunda():
    name = "Grand Entryway // Elegant Rotunda"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Grand Entryway", "Elegant Rotunda"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Grand Entryway"].mana_cost_str == "{1}{W}"
    assert by_name["Elegant Rotunda"].mana_cost_str == "{2}{W}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Elegant Rotunda", "Grand Entryway"]


def test_grand_entryway_creates_glimmer_token_on_unlock():
    """Casting Grand Entryway unlocks that half and the door trigger
    creates a 1/1 white Glimmer enchantment-creature token."""
    state = _new_state()
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Grand Entryway // Elegant Rotunda"],
        owner_id=0,
    )
    pre_bf = len(state.battlefield)
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Grand Entryway"),
    )
    drain_stack(state)
    # Battlefield gained the Room itself plus a Glimmer token.
    glimmers = [
        o for o in state.battlefield if o.printing.name == "Glimmer"
    ]
    assert len(glimmers) == 1
    assert glimmers[0].controller_id == 0
    assert "Glimmer" in glimmers[0].printing.subtypes
    assert "Enchantment" in glimmers[0].printing.card_types
    assert "Creature" in glimmers[0].printing.card_types
    # Sanity: Room is on the battlefield with Grand Entryway unlocked.
    bf_room = next(o for o in state.battlefield if o.id == room_card.id)
    assert bf_room.unlocked_halves == frozenset({"Grand Entryway"})
    # The token plus the Room are net new permanents (room left hand).
    assert len(state.battlefield) >= pre_bf + 2


def test_grand_entryway_locked_does_not_make_token():
    """If only Elegant Rotunda is unlocked, Grand Entryway's token
    trigger does not fire."""
    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Grand Entryway // Elegant Rotunda"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Elegant Rotunda"})
    pre_glimmers = sum(
        1 for o in state.battlefield if o.printing.name == "Glimmer"
    )
    # Re-fire the synthetic ENTERS dispatch — the half is locked, so
    # nothing should land on the stack.
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event
    dispatch_event(state, Event.ENTERS, label="enters", obj=room)
    drain_stack(state)
    glimmers = sum(
        1 for o in state.battlefield if o.printing.name == "Glimmer"
    )
    assert glimmers == pre_glimmers


def test_elegant_rotunda_puts_counters_on_two_targets_on_unlock():
    """Unlocking Elegant Rotunda fires +1/+1 counters on up to two
    target creatures."""
    state = _new_state()
    bear_a = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    bear_b = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Grand Entryway // Elegant Rotunda"],
        controller_id=0,
    )
    # Already-unlocked Grand Entryway (don't refire it); pay to unlock
    # Elegant Rotunda. Three Plains cover {2}{W}.
    room.unlocked_halves = frozenset({"Grand Entryway"})
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)

    apply_action(
        state, 0,
        UnlockRoomHalf(card_id=room.id, half_name="Elegant Rotunda"),
    )
    drain_stack(state)
    # The _PickFirstAgent picks the first legal target each call —
    # max_n=2 → both bears get counters.
    assert bear_a.plus_one_counters >= 1
    assert bear_b.plus_one_counters >= 1


# ---------------------------------------------------------------------------
# Parser claims: Meat Locker // Drowned Diner
# ---------------------------------------------------------------------------


def test_parser_claims_meat_locker_drowned_diner():
    name = "Meat Locker // Drowned Diner"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Meat Locker", "Drowned Diner"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Meat Locker"].mana_cost_str == "{2}{U}"
    assert by_name["Drowned Diner"].mana_cost_str == "{3}{U}{U}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Drowned Diner", "Meat Locker"]


def test_meat_locker_taps_and_stuns_target_on_unlock():
    """Casting Meat Locker unlocks it; the door trigger taps the
    target creature and applies two stun counters."""
    state = _new_state()
    enemy = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Meat Locker // Drowned Diner"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Meat Locker"),
    )
    drain_stack(state)
    assert enemy.tapped
    assert enemy.stun_counters == 2


def test_meat_locker_no_legal_target_is_noop():
    """With no creatures on the battlefield the door trigger
    resolves harmlessly (up-to-one optional target)."""
    state = _new_state()
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Meat Locker // Drowned Diner"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Meat Locker"),
    )
    drain_stack(state)
    # No crash; Room landed unlocked on Meat Locker.
    bf_room = next(o for o in state.battlefield if o.id == room_card.id)
    assert bf_room.unlocked_halves == frozenset({"Meat Locker"})


def test_drowned_diner_draws_three_then_discards_on_unlock():
    """Drowned Diner's door trigger draws 3 then discards 1 (net +2
    cards in hand)."""
    state = _new_state()
    # Stock a 3-card library so DrawCards has something to draw.
    for _ in range(3):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Meat Locker // Drowned Diner"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Meat Locker"})
    # Pay to unlock Drowned Diner ({3}{U}{U}).
    for _ in range(5):
        _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    pre_hand = len(state.players[0].hand)
    pre_grave = len(state.players[0].graveyard)
    apply_action(
        state, 0,
        UnlockRoomHalf(card_id=room.id, half_name="Drowned Diner"),
    )
    drain_stack(state)
    # +3 from Draw, -1 from DiscardSelf → net +2 in hand.
    assert len(state.players[0].hand) == pre_hand + 2
    # Discarded card landed in graveyard.
    assert len(state.players[0].graveyard) == pre_grave + 1


def test_drowned_diner_locked_does_not_fire_on_etb():
    """Casting for the Meat Locker half doesn't fire the Drowned
    Diner trigger."""
    state = _new_state()
    for _ in range(3):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Meat Locker // Drowned Diner"],
        owner_id=0,
    )
    pre_hand = len(state.players[0].hand)
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Meat Locker"),
    )
    drain_stack(state)
    # Casting drops the Room from hand → -1. No card draw fired
    # (Drowned Diner locked, Meat Locker half doesn't draw).
    assert len(state.players[0].hand) == pre_hand - 1


# ---------------------------------------------------------------------------
# Parser claims: Underwater Tunnel // Slimy Aquarium
# ---------------------------------------------------------------------------


def test_parser_claims_underwater_tunnel_slimy_aquarium():
    name = "Underwater Tunnel // Slimy Aquarium"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Underwater Tunnel", "Slimy Aquarium"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Underwater Tunnel"].mana_cost_str == "{U}"
    assert by_name["Slimy Aquarium"].mana_cost_str == "{3}{U}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Slimy Aquarium", "Underwater Tunnel"]


def test_underwater_tunnel_surveils_two_on_unlock():
    """Underwater Tunnel's door trigger looks at the top 2 cards and
    runs Surveil. The PickFirst agent declines to mill, so the
    library order is unchanged but the surveil log line lands."""
    state = _new_state()
    for _ in range(4):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    pre_lib = len(state.players[0].library)
    pre_grave = len(state.players[0].graveyard)
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Underwater Tunnel // Slimy Aquarium"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Underwater Tunnel"),
    )
    drain_stack(state)
    # Agent declined to mill, so library/graveyard are unchanged.
    assert len(state.players[0].library) == pre_lib
    assert len(state.players[0].graveyard) == pre_grave
    # Surveil log appears.
    assert any("surveils 2" in line for line in state.log)


def test_slimy_aquarium_manifests_then_counters_on_unlock():
    """Slimy Aquarium's door trigger manifests one card and puts a
    +1/+1 counter on it."""
    state = _new_state()
    for _ in range(2):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Underwater Tunnel // Slimy Aquarium"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Underwater Tunnel"})
    # Pay {3}{U} to unlock Slimy Aquarium.
    for _ in range(4):
        _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    pre_bf = len(state.battlefield)
    apply_action(
        state, 0,
        UnlockRoomHalf(card_id=room.id, half_name="Slimy Aquarium"),
    )
    drain_stack(state)
    # One face-down creature entered the battlefield.
    assert len(state.battlefield) == pre_bf + 1
    new_perm = state.battlefield[-1]
    assert new_perm.face_down
    assert new_perm.plus_one_counters == 1


# ---------------------------------------------------------------------------
# Parser claims: Moldering Gym // Weight Room
# ---------------------------------------------------------------------------


def test_parser_claims_moldering_gym_weight_room():
    name = "Moldering Gym // Weight Room"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Moldering Gym", "Weight Room"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Moldering Gym"].mana_cost_str == "{2}{G}"
    assert by_name["Weight Room"].mana_cost_str == "{5}{G}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Moldering Gym", "Weight Room"]


def test_moldering_gym_fetches_basic_land_on_unlock():
    """Moldering Gym's door trigger fetches a basic land tapped."""
    state = _new_state()
    state.players[0].library.append(
        state.new_object(BASIC_LANDS["Forest"], owner_id=0, zone=Zone.LIBRARY)
    )
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    _put_battlefield(state, BASIC_LANDS["Forest"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Forest"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Forest"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Moldering Gym // Weight Room"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Moldering Gym"),
    )
    drain_stack(state)
    # Look for a tapped Forest now on the battlefield that wasn't
    # there at start (the fetched one).
    forests_tapped = [
        o for o in state.battlefield
        if o.printing.name == "Forest" and o.tapped
    ]
    assert len(forests_tapped) >= 1


def test_weight_room_manifests_with_three_counters_on_unlock():
    """Weight Room's door trigger manifests one card and puts THREE
    +1/+1 counters on it."""
    state = _new_state()
    for _ in range(2):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Moldering Gym // Weight Room"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Moldering Gym"})
    # Pay {5}{G} to unlock Weight Room.
    for _ in range(6):
        _put_battlefield(state, BASIC_LANDS["Forest"], controller_id=0)
    pre_bf = len(state.battlefield)
    apply_action(
        state, 0,
        UnlockRoomHalf(card_id=room.id, half_name="Weight Room"),
    )
    drain_stack(state)
    assert len(state.battlefield) == pre_bf + 1
    new_perm = state.battlefield[-1]
    assert new_perm.face_down
    assert new_perm.plus_one_counters == 3


def test_manifest_dread_then_counters_no_op_on_empty_library():
    """When the library has no cards, ManifestDread's resolution puts
    nothing on the battlefield and the counter step no-ops cleanly."""
    from mtg_bot.effects import ManifestDreadThenPutPlusOneCountersOnIt

    state = _new_state()
    pre_bf = len(state.battlefield)
    eff = ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=2)
    eff.resolve(state, controller_id=0, targets=())
    # No new permanent created; no exception.
    assert len(state.battlefield) == pre_bf


# ---------------------------------------------------------------------------
# Parser claims: Surgical Suite // Hospital Room
# ---------------------------------------------------------------------------


def test_parser_claims_surgical_suite_hospital_room():
    name = "Surgical Suite // Hospital Room"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Surgical Suite", "Hospital Room"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Surgical Suite"].mana_cost_str == "{1}{W}"
    assert by_name["Hospital Room"].mana_cost_str == "{3}{W}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Hospital Room", "Surgical Suite"]


def test_surgical_suite_reanimates_small_creature_on_unlock():
    """Surgical Suite's door trigger returns a target creature card with
    mana value 3 or less from the graveyard to the battlefield."""
    state = _new_state()
    # Two Wild Bears in the graveyard — "Wild Bear" is a 2/2 for {1}{G}
    # (mana value 2 — passes the ≤3 filter).
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(bear)
    # Two Plains cover the {1}{W} cost.
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Surgical Suite // Hospital Room"],
        owner_id=0,
    )
    pre_bf = len(state.battlefield)
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Surgical Suite"),
    )
    drain_stack(state)
    # Bear is back on the battlefield; graveyard is empty.
    on_bf = [o for o in state.battlefield if o.printing.name == "Wild Bear"]
    assert len(on_bf) == 1
    assert bear not in state.players[0].graveyard
    # Battlefield gained the Room itself plus the bear (net +2 vs pre).
    assert len(state.battlefield) == pre_bf + 2


def test_surgical_suite_skips_too_expensive_target():
    """Surgical Suite's max_mv=3 rider filters out creatures with mana
    value 4 or more — they aren't legal targets, so the door trigger
    has nothing to return when only an expensive creature is available.
    """
    from mtg_bot.cards import make_creature
    state = _new_state()
    # A 5-mana creature in the graveyard — not a legal target.
    big = make_creature("Big Bear", "{4}{G}", 5, 5)
    big_obj = state.new_object(big, owner_id=0, zone=Zone.GRAVEYARD)
    state.players[0].graveyard.append(big_obj)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Surgical Suite // Hospital Room"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Surgical Suite"),
    )
    drain_stack(state)
    # The big bear stays in the graveyard — no legal target.
    assert big_obj in state.players[0].graveyard
    # Room is still on the battlefield with Surgical Suite unlocked.
    bf_room = next(o for o in state.battlefield if o.id == room_card.id)
    assert bf_room.unlocked_halves == frozenset({"Surgical Suite"})


def test_hospital_room_puts_counter_on_attacker_when_unlocked():
    """Hospital Room's YOU_ATTACK trigger fires once per declare-
    attackers pass when its half is unlocked, putting a +1/+1 counter
    on the (lone) attacking creature."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import declare_attackers

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Surgical Suite // Hospital Room"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Hospital Room"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    declare_attackers(state, [bear.id])
    _drain(state)
    # The lone attacker (bear) is the only legal target for the
    # PickFirst agent — counter lands on it.
    assert bear.plus_one_counters == 1


def test_hospital_room_locked_does_not_fire():
    """If Hospital Room is locked (Surgical Suite is unlocked instead),
    the YOU_ATTACK trigger doesn't fire — no +1/+1 counter on the
    attacker."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import declare_attackers

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Surgical Suite // Hospital Room"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Surgical Suite"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    declare_attackers(state, [bear.id])
    _drain(state)
    assert bear.plus_one_counters == 0


# ---------------------------------------------------------------------------
# Parser claims: Ticket Booth // Tunnel of Hate
# ---------------------------------------------------------------------------


def test_parser_claims_ticket_booth_tunnel_of_hate():
    name = "Ticket Booth // Tunnel of Hate"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Ticket Booth", "Tunnel of Hate"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Ticket Booth"].mana_cost_str == "{2}{R}"
    assert by_name["Tunnel of Hate"].mana_cost_str == "{4}{R}{R}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Ticket Booth", "Tunnel of Hate"]


def test_ticket_booth_manifests_one_card_on_unlock():
    """Ticket Booth's door trigger manifests dread — examines top two,
    keeps one face-down on the battlefield, the other goes to the
    graveyard. No +1/+1 counter rider (distinct from Slimy Aquarium /
    Weight Room which add counters on top)."""
    state = _new_state()
    for _ in range(2):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Ticket Booth // Tunnel of Hate"],
        owner_id=0,
    )
    pre_bf = len(state.battlefield)
    pre_grave = len(state.players[0].graveyard)
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Ticket Booth"),
    )
    drain_stack(state)
    # One face-down creature entered (the Room is the +1; the manifested
    # face-down is the +2). The other examined card went to graveyard.
    facedowns = [o for o in state.battlefield if o.face_down]
    assert len(facedowns) == 1
    assert facedowns[0].plus_one_counters == 0  # bare ManifestDread, no counter
    assert len(state.battlefield) == pre_bf + 2  # room + manifested
    assert len(state.players[0].graveyard) == pre_grave + 1


def test_tunnel_of_hate_grants_double_strike_to_attacker_when_unlocked():
    """Tunnel of Hate's YOU_ATTACK trigger grants double strike UEOT to
    the (lone) attacking creature when unlocked."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import effective_keywords

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Ticket Booth // Tunnel of Hate"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Tunnel of Hate"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    declare_attackers(state, [bear.id])
    _drain(state)
    # The PickFirst agent picks the lone attacker — double strike UEOT.
    assert "double strike" in effective_keywords(state, bear)


def test_tunnel_of_hate_locked_does_not_grant_keyword():
    """If Tunnel of Hate is locked, the YOU_ATTACK trigger doesn't fire
    — the attacker doesn't gain double strike."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import effective_keywords

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Ticket Booth // Tunnel of Hate"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Ticket Booth"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    declare_attackers(state, [bear.id])
    _drain(state)
    assert "double strike" not in effective_keywords(state, bear)


# ---------------------------------------------------------------------------
# Parser claims: Derelict Attic // Widow's Walk
# ---------------------------------------------------------------------------


def test_parser_claims_derelict_attic_widows_walk():
    name = "Derelict Attic // Widow's Walk"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Derelict Attic", "Widow's Walk"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Derelict Attic"].mana_cost_str == "{2}{B}"
    assert by_name["Widow's Walk"].mana_cost_str == "{3}{B}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Derelict Attic", "Widow's Walk"]


def test_derelict_attic_draws_two_loses_two_on_unlock():
    """Casting Derelict Attic unlocks the half; the door trigger draws
    two cards and you lose 2 life."""
    state = _new_state()
    # Stock library so DrawCards has cards to draw.
    for _ in range(3):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    _put_battlefield(state, BASIC_LANDS["Swamp"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Swamp"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Swamp"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Derelict Attic // Widow's Walk"],
        owner_id=0,
    )
    pre_hand = len(state.players[0].hand)
    pre_life = state.players[0].life
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Derelict Attic"),
    )
    drain_stack(state)
    # Cast removes Room from hand (-1) and Derelict Attic draws 2 (+2).
    assert len(state.players[0].hand) == pre_hand - 1 + 2
    # Lost 2 life.
    assert state.players[0].life == pre_life - 2


def test_derelict_attic_locked_does_not_fire():
    """If only Widow's Walk is unlocked, Derelict Attic's draw / life-
    loss trigger doesn't fire on a refired ENTERS dispatch."""
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    state = _new_state()
    for _ in range(3):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Derelict Attic // Widow's Walk"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Widow's Walk"})
    pre_hand = len(state.players[0].hand)
    pre_life = state.players[0].life
    dispatch_event(state, Event.ENTERS, label="enters", obj=room)
    drain_stack(state)
    # Locked Derelict Attic — no draw, no life loss.
    assert len(state.players[0].hand) == pre_hand
    assert state.players[0].life == pre_life


def test_widows_walk_pumps_lone_attacker_when_unlocked():
    """Widow's Walk's YOU_ATTACK trigger gates on the LoneAttackerForYou
    predicate: when exactly one creature you control is attacking, that
    attacker gets +1/+0 and gains deathtouch UEOT."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import effective_keywords, effective_power

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Derelict Attic // Widow's Walk"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Widow's Walk"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    base_power = effective_power(state, bear)
    declare_attackers(state, [bear.id])
    _drain(state)
    # Lone attacker: +1/+0 and deathtouch UEOT.
    assert effective_power(state, bear) == base_power + 1
    assert "deathtouch" in effective_keywords(state, bear)


def test_widows_walk_does_not_fire_when_not_alone():
    """With two attackers, Widow's Walk's LoneAttackerForYou predicate
    fails — no pump or deathtouch grant."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import effective_keywords, effective_power

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Derelict Attic // Widow's Walk"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Widow's Walk"})
    bear_a = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    bear_b = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    base_a = effective_power(state, bear_a)
    base_b = effective_power(state, bear_b)
    declare_attackers(state, [bear_a.id, bear_b.id])
    _drain(state)
    # Two attackers — predicate fails, neither pumped nor deathtouched.
    assert effective_power(state, bear_a) == base_a
    assert effective_power(state, bear_b) == base_b
    assert "deathtouch" not in effective_keywords(state, bear_a)
    assert "deathtouch" not in effective_keywords(state, bear_b)


def test_widows_walk_locked_does_not_fire():
    """If Widow's Walk is locked (only Derelict Attic unlocked), the
    trigger is gated off — no pump or deathtouch even on a lone attacker.
    """
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import effective_keywords, effective_power

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Derelict Attic // Widow's Walk"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Derelict Attic"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    base = effective_power(state, bear)
    declare_attackers(state, [bear.id])
    _drain(state)
    assert effective_power(state, bear) == base
    assert "deathtouch" not in effective_keywords(state, bear)


def test_lone_attacker_predicate_ignores_opponent_attacker():
    """The LoneAttackerForYou predicate is true ONLY when the lone
    attacker is controlled by the source's controller. An opponent's
    lone attacker doesn't fire your Widow's Walk."""
    from mtg_bot.effects.predicates import LoneAttackerForYou

    state = _new_state()
    # Room belongs to P0; the lone attacker belongs to P1.
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Derelict Attic // Widow's Walk"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Widow's Walk"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    bear.attacking = True
    pred = LoneAttackerForYou()
    assert pred.matches(state, {}, room) is False


def test_lone_attacker_predicate_is_false_with_no_attackers():
    """No attackers → predicate is false (length check fails before
    the controller-id branch)."""
    from mtg_bot.effects.predicates import LoneAttackerForYou

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Derelict Attic // Widow's Walk"],
        controller_id=0,
    )
    pred = LoneAttackerForYou()
    assert pred.matches(state, {}, room) is False


# ---------------------------------------------------------------------------
# Parser claims: Unholy Annex // Ritual Chamber
# ---------------------------------------------------------------------------


def test_parser_claims_unholy_annex_ritual_chamber():
    name = "Unholy Annex // Ritual Chamber"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Unholy Annex", "Ritual Chamber"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Unholy Annex"].mana_cost_str == "{2}{B}"
    assert by_name["Ritual Chamber"].mana_cost_str == "{3}{B}{B}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Ritual Chamber", "Unholy Annex"]


def test_ritual_chamber_creates_demon_token_on_unlock():
    """Casting Ritual Chamber unlocks the half; the door trigger
    creates a 6/6 black Demon token with flying."""
    state = _new_state()
    # Five Swamps cover {3}{B}{B}.
    for _ in range(5):
        _put_battlefield(state, BASIC_LANDS["Swamp"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Unholy Annex // Ritual Chamber"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Ritual Chamber"),
    )
    drain_stack(state)
    demons = [
        o for o in state.battlefield if o.printing.name == "Demon"
    ]
    assert len(demons) == 1
    demon = demons[0]
    assert demon.controller_id == 0
    assert "Demon" in demon.printing.subtypes
    assert demon.printing.power == 6
    assert demon.printing.toughness == 6
    assert "flying" in demon.printing.keywords


def test_ritual_chamber_locked_does_not_make_token():
    """If only Unholy Annex is unlocked, Ritual Chamber's token
    trigger does not fire."""
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    state = _new_state()
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Unholy Annex // Ritual Chamber"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Unholy Annex"})
    pre_demons = sum(
        1 for o in state.battlefield if o.printing.name == "Demon"
    )
    dispatch_event(state, Event.ENTERS, label="enters", obj=room)
    drain_stack(state)
    demons = sum(
        1 for o in state.battlefield if o.printing.name == "Demon"
    )
    assert demons == pre_demons


def test_unholy_annex_drains_when_you_control_a_demon():
    """With Ritual Chamber's Demon on the battlefield, Unholy Annex's
    end-step trigger draws a card AND fires the favorable branch:
    each opponent loses 2 life and you gain 2 life."""
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = _new_state()
    # Stock library so DrawCards has a card to draw.
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Unholy Annex // Ritual Chamber"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Unholy Annex"})
    # Land the Demon token directly so we don't have to cast Ritual
    # Chamber for this scenario.
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS as _TP
    _put_battlefield(state, _TP["Demon"], controller_id=0)

    pre_my_life = state.players[0].life
    pre_opp_life = state.players[1].life
    pre_hand = len(state.players[0].hand)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Drew a card.
    assert len(state.players[0].hand) == pre_hand + 1
    # Demon-controlled branch: opp -2 life, you +2 life.
    assert state.players[1].life == pre_opp_life - 2
    assert state.players[0].life == pre_my_life + 2


def test_unholy_annex_drains_self_when_no_demon():
    """Without a Demon on the battlefield, Unholy Annex's end-step
    trigger draws a card AND fires the unfavorable branch:
    you lose 2 life."""
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = _new_state()
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Unholy Annex // Ritual Chamber"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Unholy Annex"})

    pre_my_life = state.players[0].life
    pre_opp_life = state.players[1].life
    pre_hand = len(state.players[0].hand)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Drew a card unconditionally.
    assert len(state.players[0].hand) == pre_hand + 1
    # No Demon → you lose 2 life; opponent unchanged.
    assert state.players[0].life == pre_my_life - 2
    assert state.players[1].life == pre_opp_life


def test_unholy_annex_locked_does_not_fire():
    """If only Ritual Chamber is unlocked, Unholy Annex's end-step
    trigger doesn't fire — no draw, no life shift."""
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = _new_state()
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Unholy Annex // Ritual Chamber"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Ritual Chamber"})

    pre_my_life = state.players[0].life
    pre_opp_life = state.players[1].life
    pre_hand = len(state.players[0].hand)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert len(state.players[0].hand) == pre_hand
    assert state.players[0].life == pre_my_life
    assert state.players[1].life == pre_opp_life


def test_conditional_subtype_no_else_branch_is_noop():
    """ConditionalIfYouControlSubtype with else_effect=None and no
    matching subtype is a clean no-op (logs the skip; doesn't raise)."""
    from mtg_bot.effects import ConditionalIfYouControlSubtype, GainLife

    state = _new_state()
    # No Demon on the battlefield, no else branch.
    eff = ConditionalIfYouControlSubtype(
        subtype="Demon",
        then_effect=GainLife(amount=5),
        else_effect=None,
    )
    pre_life = state.players[0].life
    eff.resolve(state, controller_id=0, targets=())
    # Then-branch did NOT fire (no Demon); else=None is a silent skip.
    assert state.players[0].life == pre_life


def test_conditional_subtype_describe_strings_compose():
    """ConditionalIfYouControlSubtype.describe surfaces both branches
    when an else is set, and only the if-branch when there's no else.
    Surface text is consumer-only (logs / debug); we just sanity-check
    that the strings interpolate without error."""
    from mtg_bot.effects import (
        ConditionalIfYouControlSubtype,
        GainLife,
        LoseLife,
    )

    eff_with_else = ConditionalIfYouControlSubtype(
        subtype="Demon",
        then_effect=GainLife(amount=2),
        else_effect=LoseLife(amount=2),
    )
    desc = eff_with_else.describe()
    assert "Demon" in desc
    assert "Otherwise" in desc

    eff_no_else = ConditionalIfYouControlSubtype(
        subtype="Demon",
        then_effect=GainLife(amount=2),
    )
    desc2 = eff_no_else.describe()
    assert "Demon" in desc2
    assert "Otherwise" not in desc2


# ---------------------------------------------------------------------------
# Parser claims: Bottomless Pool // Locker Room
# ---------------------------------------------------------------------------


def test_parser_claims_bottomless_pool_locker_room():
    name = "Bottomless Pool // Locker Room"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Bottomless Pool", "Locker Room"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Bottomless Pool"].mana_cost_str == "{U}"
    assert by_name["Locker Room"].mana_cost_str == "{4}{U}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Bottomless Pool", "Locker Room"]


def test_bottomless_pool_bounces_target_creature_on_unlock():
    """Casting Bottomless Pool unlocks it; the door trigger returns the
    chosen creature to its owner's hand."""
    state = _new_state()
    enemy = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Bottomless Pool // Locker Room"],
        owner_id=0,
    )
    pre_opp_hand = len(state.players[1].hand)
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Bottomless Pool"),
    )
    drain_stack(state)
    # Enemy bear left the battlefield and is now in opponent's hand.
    assert enemy not in state.battlefield
    assert len(state.players[1].hand) == pre_opp_hand + 1


def test_bottomless_pool_no_target_is_noop():
    """With no creatures on the battlefield the door trigger resolves
    harmlessly (up-to-one optional target)."""
    state = _new_state()
    _put_battlefield(state, BASIC_LANDS["Island"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Bottomless Pool // Locker Room"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Bottomless Pool"),
    )
    drain_stack(state)
    bf_room = next(o for o in state.battlefield if o.id == room_card.id)
    assert bf_room.unlocked_halves == frozenset({"Bottomless Pool"})


def test_locker_room_draws_when_your_creature_hits_player():
    """Locker Room's "one or more creatures you control deal combat
    damage to a player" trigger draws a card. Modeled via
    ``Event.DEALS_COMBAT_DAMAGE`` + once_per_turn=True so a multi-
    attacker hit fires the draw exactly once."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import (
        clear_combat_state,
        declare_attackers,
        resolve_combat_damage,
    )

    state = _new_state()
    state.players[1].life = 20  # ensure not lethal
    # Stock library so DrawCards has cards.
    for _ in range(3):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Bottomless Pool // Locker Room"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Locker Room"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    declare_attackers(state, [bear.id])
    pre_hand = len(state.players[0].hand)
    resolve_combat_damage(state, defending_player_id=1)
    _drain(state)
    # Drew exactly one card.
    assert len(state.players[0].hand) == pre_hand + 1
    clear_combat_state(state)


def test_locker_room_draws_only_once_per_turn():
    """Two attackers connecting in the same combat fire the trigger
    only once (once_per_turn ledger captures the "one or more"
    aggregated semantics)."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import (
        clear_combat_state,
        declare_attackers,
        resolve_combat_damage,
    )

    state = _new_state()
    state.players[1].life = 20
    for _ in range(5):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Bottomless Pool // Locker Room"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Locker Room"})
    bear_a = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    bear_b = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    declare_attackers(state, [bear_a.id, bear_b.id])
    pre_hand = len(state.players[0].hand)
    resolve_combat_damage(state, defending_player_id=1)
    _drain(state)
    # Both bears connect, but only ONE card drawn.
    assert len(state.players[0].hand) == pre_hand + 1
    clear_combat_state(state)


def test_locker_room_locked_does_not_fire():
    """If only Bottomless Pool is unlocked, Locker Room's combat-damage
    trigger doesn't fire — no card drawn."""
    from mtg_bot.actions import drain_stack as _drain
    from mtg_bot.combat import (
        clear_combat_state,
        declare_attackers,
        resolve_combat_damage,
    )

    state = _new_state()
    state.players[1].life = 20
    for _ in range(3):
        state.players[0].library.append(
            state.new_object(
                SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
            )
        )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Bottomless Pool // Locker Room"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Bottomless Pool"})
    bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )
    declare_attackers(state, [bear.id])
    pre_hand = len(state.players[0].hand)
    resolve_combat_damage(state, defending_player_id=1)
    _drain(state)
    # No draw — the half is locked.
    assert len(state.players[0].hand) == pre_hand
    clear_combat_state(state)


# ---------------------------------------------------------------------------
# Parser claims: Roaring Furnace // Steaming Sauna
# ---------------------------------------------------------------------------


def test_parser_claims_roaring_furnace_steaming_sauna():
    name = "Roaring Furnace // Steaming Sauna"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Roaring Furnace", "Steaming Sauna"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Roaring Furnace"].mana_cost_str == "{1}{R}"
    assert by_name["Steaming Sauna"].mana_cost_str == "{3}{U}{U}"
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Roaring Furnace", "Steaming Sauna"]


def test_roaring_furnace_burns_target_by_hand_size_on_unlock():
    """Casting Roaring Furnace unlocks it; the door trigger deals damage
    equal to the number of cards in your hand to target enemy creature.
    With 3 cards in hand at resolution time, a 2/2 enemy bear takes 3
    and dies."""
    state = _new_state()
    enemy = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    # Stuff three filler cards into hand BEFORE casting (Wild Bears in
    # hand are fine — they aren't on the battlefield).
    for _ in range(3):
        _put_hand(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Roaring Furnace // Steaming Sauna"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Roaring Furnace"),
    )
    drain_stack(state)
    # Cast cleared the Room from hand — 3 filler cards remain at resolve.
    # Bear takes 3 damage and dies (2 toughness).
    assert enemy not in state.battlefield
    assert enemy in state.players[1].graveyard


def test_roaring_furnace_no_damage_with_empty_hand():
    """With zero cards in hand at resolution time, the trigger deals no
    damage — the bear survives."""
    state = _new_state()
    enemy = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Roaring Furnace // Steaming Sauna"],
        owner_id=0,
    )
    # Casting the Room removes it from hand → 0 cards left at resolve.
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Roaring Furnace"),
    )
    drain_stack(state)
    # Bear unhurt.
    assert enemy in state.battlefield
    assert enemy.damage == 0


def test_steaming_sauna_draws_at_your_end_step_when_unlocked():
    """Steaming Sauna's end-step trigger draws a card on YOUR end step
    when the half is unlocked."""
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = _new_state()
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Roaring Furnace // Steaming Sauna"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Steaming Sauna"})
    pre_hand = len(state.players[0].hand)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert len(state.players[0].hand) == pre_hand + 1


def test_steaming_sauna_locked_does_not_draw():
    """If only Roaring Furnace is unlocked, Steaming Sauna's end-step
    draw doesn't fire."""
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = _new_state()
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Roaring Furnace // Steaming Sauna"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Roaring Furnace"})
    pre_hand = len(state.players[0].hand)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert len(state.players[0].hand) == pre_hand


def test_deal_damage_to_opponent_creature_by_cards_in_hand_no_target_noop():
    """The new primitive is a no-op when no target is chosen / available
    (defensive resolve guard)."""
    from mtg_bot.effects import DealDamageToOpponentCreatureByCardsInHand

    state = _new_state()
    eff = DealDamageToOpponentCreatureByCardsInHand()
    # No targets → no-op (no exception).
    eff.resolve(state, controller_id=0, targets=())


def test_deal_damage_to_opponent_creature_by_cards_in_hand_describe():
    """The describe() string mentions the hand-count formulation."""
    from mtg_bot.effects import DealDamageToOpponentCreatureByCardsInHand

    eff = DealDamageToOpponentCreatureByCardsInHand()
    desc = eff.describe()
    assert "cards in your hand" in desc
    assert "creature" in desc


# ---------------------------------------------------------------------------
# Parser claims: Restricted Office // Lecture Hall
# ---------------------------------------------------------------------------


def test_parser_claims_restricted_office_lecture_hall():
    name = "Restricted Office // Lecture Hall"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Restricted Office", "Lecture Hall"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Restricted Office"].mana_cost_str == "{2}{W}{W}"
    assert by_name["Lecture Hall"].mana_cost_str == "{5}{U}{U}"
    # Only Restricted Office contributes a triggered ability — Lecture
    # Hall's "Other permanents you control have hexproof" is an honest
    # no-op static (hexproof is unenforced metadata in this engine).
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Restricted Office"]


def test_restricted_office_destroys_only_power3_or_greater_creatures():
    """Casting Restricted Office unlocks the half; the door trigger
    destroys creatures with effective_power >= 3 — smaller creatures
    survive."""
    state = _new_state()
    # Two enemy creatures with different powers. Wild Bear is 2/2 — too
    # small to die to the wrath. Make a 4/4 by stacking +1/+1 counters.
    small_bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    big_bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    big_bear.plus_one_counters = 2  # 4/4 — at or above the 3 threshold.
    # Pay {2}{W}{W} — 4 Plains.
    for _ in range(4):
        _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    room_card = _put_hand(
        state,
        _PARSER_PRINTINGS["Restricted Office // Lecture Hall"],
        owner_id=0,
    )
    apply_action(
        state, 0,
        CastSpell(room_card.id, cast_room_half="Restricted Office"),
    )
    drain_stack(state)
    # 4/4 dies, 2/2 survives.
    assert big_bear not in state.battlefield
    assert small_bear in state.battlefield


def test_restricted_office_locked_does_not_wrath():
    """If only Lecture Hall is unlocked, Restricted Office's wrath
    trigger does not fire when the Room re-enters via dispatch_event."""
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    state = _new_state()
    big_bear = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    big_bear.plus_one_counters = 2  # 4/4.
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Restricted Office // Lecture Hall"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Lecture Hall"})
    dispatch_event(state, Event.ENTERS, label="enters", obj=room)
    drain_stack(state)
    # Big bear survives — Restricted Office's wrath was gated by
    # the locked half.
    assert big_bear in state.battlefield


def test_destroy_all_creatures_min_power_filter_describe():
    """The describe() string surfaces the power-floor wording."""
    from mtg_bot.effects import DestroyAllCreatures

    eff = DestroyAllCreatures(min_power=3)
    assert eff.describe() == "destroy all creatures with power 3 or greater"


def test_destroy_all_creatures_min_power_filter_resolve():
    """``min_power=N`` only kills creatures whose effective_power is at
    least N. Tested in isolation against a hand-rolled battlefield."""
    from mtg_bot.effects import DestroyAllCreatures

    state = _new_state()
    weakling = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=0,
    )  # 2/2.
    bruiser = _put_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], controller_id=1,
    )
    bruiser.plus_one_counters = 1  # 3/3 — just at the threshold.
    DestroyAllCreatures(min_power=3).resolve(state, controller_id=0)
    assert weakling in state.battlefield
    assert bruiser not in state.battlefield


# ---------------------------------------------------------------------------
# Parser claims: Charred Foyer // Warped Space
# ---------------------------------------------------------------------------


def test_parser_claims_charred_foyer_warped_space():
    name = "Charred Foyer // Warped Space"
    assert name in _PARSER_PRINTINGS
    p = _PARSER_PRINTINGS[name]
    assert p.is_room
    halves = {h.name for h in p.room_halves}
    assert halves == {"Charred Foyer", "Warped Space"}
    by_name = {h.name: h for h in p.room_halves}
    assert by_name["Charred Foyer"].mana_cost_str == "{3}{R}"
    assert by_name["Warped Space"].mana_cost_str == "{4}{R}{R}"
    # Only Charred Foyer contributes a triggered ability — Warped Space's
    # "you may pay {0} rather than the mana cost" is an honest no-op
    # permission in this engine (no alt-cost selection plumbing yet).
    by_half = sorted(a.room_half for a in p.triggered_abilities)
    assert by_half == ["Charred Foyer"]


def test_charred_foyer_exiles_top_on_upkeep_when_unlocked():
    """Charred Foyer's upkeep trigger exiles the top card of the
    controller's library and marks it ``playable_from_exile_this_turn``
    so the impulse-cast pipeline picks it up."""
    from mtg_bot.turn import run_beginning_of_upkeep_triggers

    state = _new_state()
    library_card = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
    )
    state.players[0].library.append(library_card)
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Charred Foyer // Warped Space"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Charred Foyer"})
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    # Top library card moved to exile and is impulse-castable.
    assert library_card in state.players[0].exile
    assert library_card.playable_from_exile_this_turn is True


def test_charred_foyer_locked_does_not_exile():
    """If only Warped Space is unlocked, Charred Foyer's upkeep trigger
    does not fire — the top card stays on the library."""
    from mtg_bot.turn import run_beginning_of_upkeep_triggers

    state = _new_state()
    library_card = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
    )
    state.players[0].library.append(library_card)
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Charred Foyer // Warped Space"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Warped Space"})
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert library_card in state.players[0].library
    assert library_card not in state.players[0].exile


def test_charred_foyer_does_not_fire_on_opponent_upkeep():
    """The trigger is gated ``Controlled(YOU)`` on a turn-structure
    event — it should fire only on the Room controller's upkeep, not
    the opponent's."""
    from mtg_bot.turn import run_beginning_of_upkeep_triggers

    state = _new_state()
    library_card = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
    )
    state.players[0].library.append(library_card)
    room = _put_battlefield(
        state,
        _PARSER_PRINTINGS["Charred Foyer // Warped Space"],
        controller_id=0,
    )
    room.unlocked_halves = frozenset({"Charred Foyer"})
    # Flip the active player to P1 — it's the opponent's upkeep now.
    state.active_player_idx = 1
    state.priority_player_idx = 1
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    # P0's library is untouched — Charred Foyer didn't fire on the
    # opponent's upkeep.
    assert library_card in state.players[0].library


def test_exile_top_of_library_may_play_this_turn_describe_singular():
    """The describe() string for the default ``amount=1`` form."""
    from mtg_bot.effects import ExileTopOfLibraryMayPlayThisTurn

    eff = ExileTopOfLibraryMayPlayThisTurn(amount=1)
    desc = eff.describe()
    assert "exile the top card" in desc
    assert "may play it this turn" in desc


def test_exile_top_of_library_may_play_this_turn_describe_plural():
    """The describe() string for the multi-card form."""
    from mtg_bot.effects import ExileTopOfLibraryMayPlayThisTurn

    eff = ExileTopOfLibraryMayPlayThisTurn(amount=3)
    desc = eff.describe()
    assert "exile the top 3 cards" in desc
    assert "may play them this turn" in desc


def test_exile_top_of_library_may_play_this_turn_handles_empty_library():
    """Running out of cards mid-exile simply stops; no exception, no
    empty-library loss (impulse-cast doesn't draw)."""
    from mtg_bot.effects import ExileTopOfLibraryMayPlayThisTurn

    state = _new_state()
    # Empty library — no cards to exile.
    state.players[0].library.clear()
    eff = ExileTopOfLibraryMayPlayThisTurn(amount=2)
    eff.resolve(state, controller_id=0, targets=())
    # Player 0 is still alive; nothing in exile.
    assert state.players[0].exile == []

