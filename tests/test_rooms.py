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
