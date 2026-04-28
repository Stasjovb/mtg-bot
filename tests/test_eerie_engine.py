"""Engine-side tests for the Duskmourn ``Eerie`` mechanic.

Covers the predicate-trigger plumbing that the parser layer composes
on top of:

* ``Event.ROOM_FULLY_UNLOCKED`` — new event entry + ``EVENT_SUBJECTS``
  mapping (``("room",)``).
* ``IsEnchantment`` predicate — identity check on the named subject's
  ``card_types``.
* ``_unlock_room_half`` dispatching ``Event.ROOM_FULLY_UNLOCKED`` only
  on the all-halves transition (NOT on every door unlock), with the
  Room ``GameObject`` threaded through as the ``"room"`` subject.

Parser claims for the printed Eerie creatures and the ability-word
strip / compound trigger phrase live in ``test_eerie.py``.
"""

from __future__ import annotations

from mtg_bot.actions import (
    UnlockRoomHalf,
    apply_action,
    dispatch_event,
    drain_stack,
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
from mtg_bot.cards.base import DrawCards, make_creature
from mtg_bot.effects.predicates import (
    EVENT_SUBJECTS,
    YOU,
    Controlled,
    Event,
    IsEnchantment,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


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


# ---------------------------------------------------------------------------
# Event.ROOM_FULLY_UNLOCKED + EVENT_SUBJECTS mapping
# ---------------------------------------------------------------------------


def test_room_fully_unlocked_event_registered():
    # The new event lives on the Event enum and is registered in
    # EVENT_SUBJECTS so the dispatcher can validate subject slots.
    assert Event.ROOM_FULLY_UNLOCKED.value == "room_fully_unlocked"
    assert EVENT_SUBJECTS[Event.ROOM_FULLY_UNLOCKED] == ("room",)


# ---------------------------------------------------------------------------
# IsEnchantment predicate
# ---------------------------------------------------------------------------


def test_is_enchantment_matches_enchantment_subject():
    state = _new_state()
    # An enchantment-creature printing carries "Enchantment" in
    # card_types, which is what IsEnchantment keys off.
    enchantment = make_creature(
        name="Test Enchantment Creature",
        cost="{1}",
        power=1,
        toughness=1,
        enchantment=True,
    )
    obj = _put_battlefield(state, enchantment)
    assert "Enchantment" in enchantment.card_types
    assert IsEnchantment().matches(state, {"obj": obj}, source=obj)


def test_is_enchantment_rejects_non_enchantment_subject():
    state = _new_state()
    bear = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"])
    assert not IsEnchantment().matches(state, {"obj": bear}, source=bear)


def test_is_enchantment_handles_missing_subject():
    # ``subject="missing"`` resolves to None — predicate evaluates false
    # rather than raising. Mirrors the convention every other
    # subject-scoped predicate uses (IsCreature / IsArtifact / etc.).
    state = _new_state()
    bear = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"])
    assert not IsEnchantment(subject="missing").matches(
        state, {"obj": bear}, source=bear,
    )


def test_is_enchantment_rejects_player_subject():
    # Players have no ``printing`` attribute — the predicate evaluates
    # false rather than raising.
    state = _new_state()
    bear = _put_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"])
    assert not IsEnchantment(subject="player").matches(
        state, {"player": state.players[0]}, source=bear,
    )


# ---------------------------------------------------------------------------
# _unlock_room_half fires ROOM_FULLY_UNLOCKED only on the transition
# ---------------------------------------------------------------------------


# A toy Eerie observer printing: a creature whose ROOM_FULLY_UNLOCKED
# arm draws a card, so we can assert the dispatch happens at the right
# moment.
def _eerie_observer():
    return make_creature(
        name="Test Eerie Watcher",
        cost="{W}",
        power=1,
        toughness=1,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ROOM_FULLY_UNLOCKED,
                predicate=Controlled(YOU, subject="room"),
                effect=DrawCards(amount=1),
            ),
        ),
    )


def _toy_room():
    return make_room(
        RoomHalf(
            name="Reading Nook",
            mana_cost_str="{W}",
            mana_cost=parse_mana_cost("{W}"),
            triggered_abilities=(),
        ),
        RoomHalf(
            name="Boiler Room",
            mana_cost_str="{R}",
            mana_cost=parse_mana_cost("{R}"),
            triggered_abilities=(),
        ),
    )


def test_unlock_first_half_does_not_fire_room_fully_unlocked():
    # Unlocking the FIRST half of a Room (transitioning from {} to
    # {first}) does NOT fire ROOM_FULLY_UNLOCKED — the event is anchored
    # on the all-halves transition.
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset()
    observer = _put_battlefield(state, _eerie_observer(), controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Plains"], controller_id=0)
    pre_hand = len(state.players[0].hand)
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Reading Nook"),
    )
    drain_stack(state)
    # Eerie observer's draw did NOT fire — only one half is unlocked.
    assert len(state.players[0].hand) == pre_hand
    assert observer.id  # touch unused-var warning


def test_unlock_second_half_fires_room_fully_unlocked():
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    room.unlocked_halves = frozenset({"Reading Nook"})
    _put_battlefield(state, _eerie_observer(), controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=0)
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    pre_hand = len(state.players[0].hand)
    apply_action(
        state, 0, UnlockRoomHalf(card_id=room.id, half_name="Boiler Room"),
    )
    drain_stack(state)
    # ROOM_FULLY_UNLOCKED fired: the observer drew a card.
    assert len(state.players[0].hand) == pre_hand + 1
    assert "fully unlocked" in " ".join(state.log)


def test_room_fully_unlocked_only_for_controllers_rooms():
    # An Eerie observer under Player 0 must NOT fire when Player 1
    # fully unlocks one of THEIR Rooms — Controlled(YOU, subject="room")
    # gates the trigger on the firing source's controller matching the
    # Room's controller.
    state = _new_state()
    opp_room = _put_battlefield(state, _toy_room(), controller_id=1)
    opp_room.unlocked_halves = frozenset({"Reading Nook"})
    _put_battlefield(state, _eerie_observer(), controller_id=0)
    _put_battlefield(state, BASIC_LANDS["Mountain"], controller_id=1)
    pre_hand = len(state.players[0].hand)
    apply_action(
        state, 1,
        UnlockRoomHalf(card_id=opp_room.id, half_name="Boiler Room"),
    )
    drain_stack(state)
    # Observer did NOT fire — the Room isn't under its controller.
    assert len(state.players[0].hand) == pre_hand


# ---------------------------------------------------------------------------
# dispatch_event(Event.ROOM_FULLY_UNLOCKED) standalone
# ---------------------------------------------------------------------------


def test_dispatch_room_fully_unlocked_fires_predicate_trigger():
    # Direct dispatch path — bypasses the unlock action so we exercise
    # the dispatch+predicate plumbing in isolation.
    state = _new_state()
    room = _put_battlefield(state, _toy_room(), controller_id=0)
    _put_battlefield(state, _eerie_observer(), controller_id=0)
    state.players[0].library.append(
        state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.LIBRARY,
        )
    )
    pre_hand = len(state.players[0].hand)
    dispatch_event(state, Event.ROOM_FULLY_UNLOCKED, room=room)
    drain_stack(state)
    assert len(state.players[0].hand) == pre_hand + 1
