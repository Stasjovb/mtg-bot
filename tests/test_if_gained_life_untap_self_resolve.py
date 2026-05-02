"""Engine-resolve tests for ``IfGainedLifeThisTurnUntapSelf``.

This effect is Ragost, Deft Gastronaut's beginning-of-each-end-step
rider. The existing ``test_ragost.py`` covers the integrated trigger
path and the no-source bail, but the body's other branches
(life_gained_this_turn <= 0, source already untapped, the happy
"untap + log" mutation) aren't exercised in isolation. These tests
fill those gaps by calling ``resolve()`` directly with a synthetic
state.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import IfGainedLifeThisTurnUntapSelf
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _put_creature(state, owner_id=0, tapped=True):
    obj = state.new_object(
        SYNTHETIC_CREATURES["Battlefield Recruit"],
        owner_id=owner_id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = owner_id
    obj.tapped = tapped
    state.battlefield.append(obj)
    return obj


def test_resolve_untaps_when_life_gained_and_source_tapped():
    """Happy path: source is tapped and controller gained > 0 life."""
    state = _new_state()
    src = _put_creature(state, owner_id=0, tapped=True)
    state.resolving_source = src
    state.players[0].life_gained_this_turn = 3

    IfGainedLifeThisTurnUntapSelf().resolve(state, 0, ())

    assert src.tapped is False
    assert any(
        "untaps" in line and "3 life gained" in line
        for line in state.log
    )


def test_resolve_no_op_when_no_life_gained():
    """``life_gained_this_turn == 0`` → effect bails without untapping."""
    state = _new_state()
    src = _put_creature(state, owner_id=0, tapped=True)
    state.resolving_source = src
    state.players[0].life_gained_this_turn = 0

    IfGainedLifeThisTurnUntapSelf().resolve(state, 0, ())

    assert src.tapped is True
    assert not any("untaps" in line for line in state.log)


def test_resolve_no_op_when_source_already_untapped():
    """Source is already untapped: still gates on life_gained, but the
    final ``if source.tapped`` branch bails before logging."""
    state = _new_state()
    src = _put_creature(state, owner_id=0, tapped=False)
    state.resolving_source = src
    state.players[0].life_gained_this_turn = 5

    IfGainedLifeThisTurnUntapSelf().resolve(state, 0, ())

    # Already untapped, nothing to do.
    assert src.tapped is False
    assert not any("untaps" in line for line in state.log)


def test_resolve_no_op_when_resolving_source_is_none():
    """Defensive ``source is None`` branch — covered by the existing
    test_ragost.py case but re-asserted here for completeness in this
    file's scope."""
    state = _new_state()
    state.resolving_source = None
    state.players[0].life_gained_this_turn = 7

    # Should not raise; should not log anything.
    IfGainedLifeThisTurnUntapSelf().resolve(state, 0, ())
    assert state.log == []


def test_resolve_uses_source_controller_not_resolve_arg():
    """The effect reads ``source.controller_id``, not the
    ``controller_id`` arg to resolve. Verify by giving P1 the life
    gain while P0 is the controller_id passed in: with source
    controlled by P1, P1's life-gained counter is what's checked."""
    state = _new_state()
    src = _put_creature(state, owner_id=1, tapped=True)
    state.resolving_source = src
    # P0 is the resolve-call's controller_id; P1 controls the source.
    state.players[0].life_gained_this_turn = 0
    state.players[1].life_gained_this_turn = 4

    IfGainedLifeThisTurnUntapSelf().resolve(state, 0, ())

    # The source's controller (P1) gained life → untap fires.
    assert src.tapped is False


def test_describe_text():
    desc = IfGainedLifeThisTurnUntapSelf().describe()
    assert "gained life" in desc
    assert "untap" in desc
