"""Defensive-branch resolve tests for ``UntapTargetLand``.

The existing test file ``test_stellar_sights_batch2.py`` covers Deserted
Temple's happy-path activation through the stack and the
already-untapped early-return. The remaining uncovered branches are the
``not targets`` bail, the wrong-target-kind bail, the missing-target-id
bail, the non-land target bail, and the ``describe`` text. These tests
fill those gaps directly via the public resolve API."""

from __future__ import annotations

from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import UntapTargetLand
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


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_no_targets_is_silent_noop():
    """An empty target tuple bails before touching anything."""
    state = _new_state()
    land = _put(state, BASIC_LANDS["Forest"])
    land.tapped = True

    UntapTargetLand().resolve(state, 0, ())

    # Land remains tapped (not touched), no log entry written.
    assert land.tapped is True
    assert not any("untapped" in line for line in state.log)


def test_resolve_wrong_target_kind_is_noop():
    """A non-'permanent' kind bails (e.g., a 'creature' slot somehow
    pointing at the land's id)."""
    state = _new_state()
    land = _put(state, BASIC_LANDS["Forest"])
    land.tapped = True

    UntapTargetLand().resolve(state, 0, (("creature", land.id),))

    assert land.tapped is True
    assert not any("untapped" in line for line in state.log)


def test_resolve_missing_target_id_is_noop():
    """An id that no longer exists on the battlefield (the land got
    destroyed between cast and resolve) bails defensively."""
    state = _new_state()

    UntapTargetLand().resolve(state, 0, (("permanent", 999_999),))

    assert not any("untapped" in line for line in state.log)


def test_resolve_non_land_target_is_noop():
    """A permanent that isn't a land slipping through the legal-target
    filter bails on the printing.is_land defensive recheck."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.tapped = True

    UntapTargetLand().resolve(state, 0, (("permanent", bear.id),))

    # Bear remains tapped; no untap log line.
    assert bear.tapped is True
    assert not any("untapped" in line for line in state.log)


def test_resolve_happy_path_untaps_tapped_land_directly():
    """Sanity: the happy path itself works when called directly (no
    stack involvement). Covers the mutation + log line."""
    state = _new_state()
    land = _put(state, BASIC_LANDS["Forest"])
    land.tapped = True

    UntapTargetLand().resolve(state, 0, (("permanent", land.id),))

    assert land.tapped is False
    assert any("untapped" in line for line in state.log)


def test_describe_text_mentions_untap_and_land():
    desc = UntapTargetLand().describe()
    assert "untap" in desc.lower()
    assert "land" in desc.lower()
