"""Defensive-branch resolve tests for ``ThreatenTargetCreatureUEOT``.

The existing parser-side test ``test_parser_dsk_spells_batch5.py`` covers
the happy path (control change + untap + haste grant) and the describe
text. The remaining uncovered branches are the early bails: empty
target tuple, non-creature target kind, and a target id that's no
longer on the battlefield. These tests fill those defensive paths."""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import ThreatenTargetCreatureUEOT
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=1):
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_no_targets_is_silent_noop():
    """An empty targets tuple bails immediately."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    original_controller = bear.controller_id

    ThreatenTargetCreatureUEOT().resolve(state, 0, ())

    # Bear remains under its original controller; no log line about
    # taking control.
    assert bear.controller_id == original_controller
    assert not any("takes control" in line for line in state.log)


def test_resolve_wrong_target_kind_is_noop():
    """A non-'creature' target slot bails before the control change."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    original_controller = bear.controller_id

    # 'permanent' kind instead of 'creature'.
    ThreatenTargetCreatureUEOT().resolve(
        state, 0, (("permanent", bear.id),),
    )

    assert bear.controller_id == original_controller
    assert not any("takes control" in line for line in state.log)


def test_resolve_missing_target_id_is_noop():
    """A target id that's no longer on the battlefield bails the
    defensive ``obj is None`` check."""
    state = _new_state()

    ThreatenTargetCreatureUEOT().resolve(
        state, 0, (("creature", 999_999),),
    )

    assert not any("takes control" in line for line in state.log)
