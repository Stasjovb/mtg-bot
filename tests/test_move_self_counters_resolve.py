"""Engine-resolve tests for ``MoveSelfCountersToTargetCreatureYouControl``.

Dockworker Drone's dies trigger ("put its counters on target creature
you control") only had parser-shape coverage. The resolve body has
six defensive branches plus the happy mutation; this file exercises
each one directly.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import MoveSelfCountersToTargetCreatureYouControl
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _put(state, name, controller_id=0, counters=0):
    obj = state.new_object(
        SYNTHETIC_CREATURES[name],
        owner_id=controller_id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller_id
    obj.plus_one_counters = counters
    state.battlefield.append(obj)
    return obj


def test_resolve_moves_counters_from_source_to_target():
    state = _new_state()
    src = _put(state, "Battlefield Recruit", counters=3)
    tgt = _put(state, "Stalwart Knight", counters=1)
    state.resolving_source = src

    MoveSelfCountersToTargetCreatureYouControl().resolve(
        state, 0, (("creature", tgt.id),),
    )

    assert src.plus_one_counters == 0
    assert tgt.plus_one_counters == 4  # 1 + 3
    assert any(
        "3 +1/+1 counter(s) moved from Battlefield Recruit to Stalwart Knight"
        in line
        for line in state.log
    )


def test_resolve_no_op_when_resolving_source_is_none():
    state = _new_state()
    tgt = _put(state, "Stalwart Knight", counters=2)
    state.resolving_source = None

    MoveSelfCountersToTargetCreatureYouControl().resolve(
        state, 0, (("creature", tgt.id),),
    )

    assert tgt.plus_one_counters == 2
    assert state.log == []


def test_resolve_no_op_when_source_has_zero_counters():
    state = _new_state()
    src = _put(state, "Battlefield Recruit", counters=0)
    tgt = _put(state, "Stalwart Knight", counters=2)
    state.resolving_source = src

    MoveSelfCountersToTargetCreatureYouControl().resolve(
        state, 0, (("creature", tgt.id),),
    )

    assert src.plus_one_counters == 0
    assert tgt.plus_one_counters == 2
    assert state.log == []


def test_resolve_no_op_when_no_targets():
    state = _new_state()
    src = _put(state, "Battlefield Recruit", counters=3)
    state.resolving_source = src

    MoveSelfCountersToTargetCreatureYouControl().resolve(
        state, 0, (),
    )

    # Source counters unchanged when there's no target.
    assert src.plus_one_counters == 3
    assert state.log == []


def test_resolve_no_op_when_target_kind_wrong():
    state = _new_state()
    src = _put(state, "Battlefield Recruit", counters=3)
    state.resolving_source = src

    MoveSelfCountersToTargetCreatureYouControl().resolve(
        state, 0, (("player", 1),),
    )

    assert src.plus_one_counters == 3
    assert state.log == []


def test_resolve_no_op_when_target_id_missing():
    state = _new_state()
    src = _put(state, "Battlefield Recruit", counters=3)
    state.resolving_source = src

    MoveSelfCountersToTargetCreatureYouControl().resolve(
        state, 0, (("creature", 999_999),),
    )

    assert src.plus_one_counters == 3
    assert state.log == []


def test_legal_targets_only_includes_controllers_creatures():
    state = _new_state()
    own = _put(state, "Battlefield Recruit", controller_id=0)
    _put(state, "Stalwart Knight", controller_id=1)
    legal = MoveSelfCountersToTargetCreatureYouControl().legal_targets(
        state, 0,
    )
    target_ids = {tid for _, tid in legal}
    assert own.id in target_ids
    assert len(target_ids) == 1


def test_describe_text():
    desc = MoveSelfCountersToTargetCreatureYouControl().describe()
    assert "+1/+1" in desc
    assert "target creature" in desc
