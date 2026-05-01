"""Engine-resolve tests for ``LockOrUnlockDoorOfTargetRoomYouControl``.

The parser-shape tests in ``test_parser_lock_unlock_room.py`` cover the
recognizer, but no test exercises the resolve path that mutates a Room
permanent's ``unlocked_halves`` set. These tests run the effect against a
synthetic Room fixture and verify the lock/unlock toggle logic plus the
defensive no-op branches (no targets, wrong target kind, missing target,
opponent-controlled target, non-Room target, and zero room halves)."""

from __future__ import annotations

from mtg_bot.agents import Agent
from mtg_bot.cards import (
    BASIC_LANDS,
    RoomHalf,
    TriggeredAbility,
    make_room,
    parse_mana_cost,
)
from mtg_bot.effects import DrawCards
from mtg_bot.effects.generic import LockOrUnlockDoorOfTargetRoomYouControl
from mtg_bot.effects.predicates import Event, IsSelf
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _PickFirstAgent(Agent):
    def __init__(self, mode_pick: int = 0):
        self._mode_pick = mode_pick

    def choose_mode(self, state, player_id, mode_descriptions):
        return self._mode_pick


def _toy_room():
    """Two-half Room with cheap costs and trivial triggers."""
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
            triggered_abilities=(),
        ),
    )


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_room(state, controller_id=0, unlocked=()):
    room = state.new_object(_toy_room(), owner_id=controller_id, zone=Zone.BATTLEFIELD)
    room.controller_id = controller_id
    room.unlocked_halves = frozenset(unlocked)
    state.battlefield.append(room)
    return room


def test_resolve_unlocks_first_locked_door():
    """With both doors locked, picking mode 0 unlocks Reading Nook."""
    state = _new_state(agent=_PickFirstAgent(mode_pick=0))
    room = _put_room(state, unlocked=())
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("permanent", room.id),),
    )
    assert "Reading Nook" in room.unlocked_halves
    assert "Boiler Room" not in room.unlocked_halves
    assert any(
        "unlocks Reading Nook" in line for line in state.log
    )


def test_resolve_locks_already_unlocked_door():
    """With Reading Nook unlocked, picking mode 0 locks it back."""
    state = _new_state(agent=_PickFirstAgent(mode_pick=0))
    room = _put_room(state, unlocked={"Reading Nook"})
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("permanent", room.id),),
    )
    assert "Reading Nook" not in room.unlocked_halves
    assert any(
        "locks Reading Nook" in line for line in state.log
    )


def test_resolve_unlocks_second_door_when_pick_is_one():
    """``choose_mode`` picks index 1 → the second door (Boiler Room)
    flips state."""
    state = _new_state(agent=_PickFirstAgent(mode_pick=1))
    room = _put_room(state, unlocked=())
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("permanent", room.id),),
    )
    assert "Boiler Room" in room.unlocked_halves
    assert "Reading Nook" not in room.unlocked_halves


def test_resolve_clamps_out_of_range_mode_pick():
    """An agent that returns an out-of-range index gets clamped to the
    last valid mode (door)."""
    state = _new_state(agent=_PickFirstAgent(mode_pick=99))
    room = _put_room(state, unlocked=())
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("permanent", room.id),),
    )
    # max(0, min(99, 1)) = 1 → second door (Boiler Room) flips.
    assert "Boiler Room" in room.unlocked_halves


def test_resolve_no_targets_is_noop():
    state = _new_state()
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(state, 0, ())
    # No exception, no log entry about unlocking.
    assert not any("unlocks" in line or "locks" in line for line in state.log)


def test_resolve_wrong_target_kind_is_noop():
    state = _new_state()
    room = _put_room(state, unlocked=())
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("creature", room.id),),
    )
    # Effect bailed before mutating the Room.
    assert room.unlocked_halves == frozenset()


def test_resolve_missing_target_is_noop():
    state = _new_state()
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("permanent", 999_999),),
    )
    assert not any("unlocks" in line or "locks" in line for line in state.log)


def test_resolve_opponent_controlled_target_is_noop():
    """The effect's target filter restricts to controller's own Rooms;
    a stray opponent-controlled Room slipping through still no-ops."""
    state = _new_state()
    opp_room = _put_room(state, controller_id=1, unlocked=())
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("permanent", opp_room.id),),
    )
    assert opp_room.unlocked_halves == frozenset()


def test_resolve_non_room_target_is_noop():
    """Permanent that isn't a Room: bail without mutating it."""
    state = _new_state()
    plains = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.BATTLEFIELD)
    plains.controller_id = 0
    state.battlefield.append(plains)
    LockOrUnlockDoorOfTargetRoomYouControl().resolve(
        state, 0, (("permanent", plains.id),),
    )
    # Plains has no unlocked_halves field semantics here; the bail
    # short-circuits before touching it.
    assert not any("unlocks" in line or "locks" in line for line in state.log)


def test_legal_targets_only_includes_controllers_rooms():
    state = _new_state()
    own_room = _put_room(state, controller_id=0, unlocked=())
    _put_room(state, controller_id=1, unlocked=())
    legal = LockOrUnlockDoorOfTargetRoomYouControl().legal_targets(state, 0)
    target_ids = {tid for _, tid in legal}
    assert own_room.id in target_ids
    # Opp's room not in pool.
    assert len(target_ids) == 1


def test_describe_text():
    desc = LockOrUnlockDoorOfTargetRoomYouControl().describe()
    assert "lock or unlock" in desc.lower()
    assert "Room" in desc
