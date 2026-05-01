"""Defensive-branch resolve tests for
``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary``.

The end-to-end happy path is covered in test_pinnacle_blade.py, but the
direct-resolve fallbacks (no targets, wrong kind, missing card, warp flag
stripped at resolution) aren't exercised. These tests target each early-
exit branch directly."""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import (
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_in_exile(state, owner_id=0, warped=True):
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=owner_id, zone=Zone.EXILE,
    )
    obj.warped = warped
    state.players[owner_id].exile.append(obj)
    return obj


def test_resolve_no_targets_is_noop():
    state = _new_state()
    obj = _put_in_exile(state)
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().resolve(state, 0, ())
    # No log line, no movement.
    assert obj in state.players[0].exile
    assert state.players[0].library == []


def test_resolve_wrong_target_kind_is_noop():
    state = _new_state()
    obj = _put_in_exile(state)
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().resolve(
        state, 0, (("creature", obj.id),),
    )
    assert obj in state.players[0].exile
    assert state.players[0].library == []


def test_resolve_missing_target_id_is_noop():
    state = _new_state()
    obj = _put_in_exile(state)
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().resolve(
        state, 0, (("exile_card", 999_999),),
    )
    # Real warped card untouched.
    assert obj in state.players[0].exile
    assert obj.warped is True


def test_resolve_warp_flag_cleared_at_resolution_fizzles():
    """If something stripped the warped flag before resolve, the effect
    fizzles silently — the card stays in exile, library unchanged."""
    state = _new_state()
    obj = _put_in_exile(state, warped=True)
    # Flag stripped between target-pick and resolve.
    obj.warped = False
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().resolve(
        state, 0, (("exile_card", obj.id),),
    )
    assert obj in state.players[0].exile
    assert state.players[0].library == []


def test_resolve_happy_path_moves_card_to_bottom_and_clears_warp():
    """Direct resolve, bypassing the modal/stack pipeline: the chosen
    warped exile card moves to the bottom of its owner's library and
    the warp flag clears."""
    state = _new_state()
    obj = _put_in_exile(state, owner_id=1, warped=True)
    sentinel_top = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.LIBRARY,
    )
    state.players[1].library.append(sentinel_top)
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().resolve(
        state, 0, (("exile_card", obj.id),),
    )
    assert obj not in state.players[1].exile
    # Bottom-of-library = end of list.
    assert state.players[1].library[-1] is obj
    assert obj.warped is False
    assert obj.zone == Zone.LIBRARY


def test_describe_text():
    desc = OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().describe()
    assert "warp" in desc
    assert "bottom" in desc
    assert "library" in desc


def test_requires_target_is_true():
    assert OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().requires_target()
