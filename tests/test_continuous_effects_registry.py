"""Phase 1 of the layered-effects refactor: additive scaffolding.

This file pins the data shape and the registry helpers so Phase 2
(layer-by-layer migration of existing field-mutation continuous
effects to registry entries) has a stable target. No behavior change
yet — the registry is empty in all current code paths.
"""

import pickle

from mtg_bot.game import ContinuousEffect, GameState


# -----------------------
# Data shape
# -----------------------


def test_continuous_effect_is_frozen_and_hashable():
    """Frozen dataclass with primitive fields = immutable + picklable
    + safe to share across MCTS branches."""
    e = ContinuousEffect(
        source_id=1, layer=2, timestamp=0, kind="control_change",
        target_id=42, params=(0,), description="P0 controls X",
    )
    # frozen: any mutation should fail.
    try:
        e.layer = 7
    except Exception:
        pass
    else:  # pragma: no cover
        raise AssertionError("ContinuousEffect must be frozen")
    # hashable.
    {e}
    # picklable (matters for MCTS spawn).
    blob = pickle.dumps(e)
    e2 = pickle.loads(blob)
    assert e == e2


def test_default_optional_fields():
    e = ContinuousEffect(
        source_id=1, layer=2, timestamp=0, kind="control_change",
    )
    assert e.sublayer == 0
    assert e.target_filter == ""
    assert e.target_id is None
    assert e.params == ()
    assert e.description == ""


# -----------------------
# Registry helpers
# -----------------------


def test_fresh_state_has_empty_registry():
    state = GameState()
    assert state.continuous_effects == []
    assert state.next_timestamp == 0


def test_add_continuous_effect_allocates_monotonic_timestamps():
    state = GameState()
    e1 = state.add_continuous_effect(
        source_id=1, layer=2, kind="control_change",
    )
    e2 = state.add_continuous_effect(
        source_id=2, layer=7, kind="pump_pt",
    )
    e3 = state.add_continuous_effect(
        source_id=1, layer=6, kind="grant_keyword",
    )
    assert e1.timestamp == 0
    assert e2.timestamp == 1
    assert e3.timestamp == 2
    assert state.next_timestamp == 3
    assert state.continuous_effects == [e1, e2, e3]


def test_add_continuous_effect_returns_appended_record():
    state = GameState()
    appended = state.add_continuous_effect(
        source_id=5, layer=2, kind="control_change",
        target_id=10, params=(0,), description="test",
    )
    assert state.continuous_effects[-1] is appended


def test_remove_drops_only_matching_source():
    state = GameState()
    a1 = state.add_continuous_effect(source_id=1, layer=2, kind="x")
    a2 = state.add_continuous_effect(source_id=2, layer=2, kind="y")
    a3 = state.add_continuous_effect(source_id=1, layer=6, kind="z")
    dropped = state.remove_continuous_effects_from_source(1)
    assert dropped == [a1, a3]
    assert state.continuous_effects == [a2]


def test_remove_returns_empty_when_no_matches():
    state = GameState()
    state.add_continuous_effect(source_id=1, layer=2, kind="x")
    dropped = state.remove_continuous_effects_from_source(999)
    assert dropped == []
    # Non-matching entry untouched.
    assert len(state.continuous_effects) == 1


def test_timestamp_continues_after_remove():
    """Timestamp counter is monotonic across the lifetime of the
    state — removing a source's effects doesn't recycle timestamps."""
    state = GameState()
    state.add_continuous_effect(source_id=1, layer=2, kind="x")
    state.add_continuous_effect(source_id=1, layer=2, kind="y")
    state.remove_continuous_effects_from_source(1)
    e3 = state.add_continuous_effect(source_id=2, layer=2, kind="z")
    assert e3.timestamp == 2
    assert state.next_timestamp == 3


# -----------------------
# Clone independence
# -----------------------


def test_clone_deep_copies_registry_list():
    state = GameState()
    state.add_continuous_effect(source_id=1, layer=2, kind="x")
    cloned = state.clone()
    # Records identical (frozen dataclasses can be shared by reference).
    assert cloned.continuous_effects == state.continuous_effects
    # But the LIST itself is a different object.
    assert cloned.continuous_effects is not state.continuous_effects


def test_clone_preserves_timestamp_counter():
    state = GameState()
    state.add_continuous_effect(source_id=1, layer=2, kind="x")
    state.add_continuous_effect(source_id=2, layer=2, kind="y")
    cloned = state.clone()
    assert cloned.next_timestamp == 2
    # Adding to clone doesn't affect original.
    cloned.add_continuous_effect(source_id=3, layer=2, kind="z")
    assert cloned.next_timestamp == 3
    assert state.next_timestamp == 2


def test_clone_then_remove_does_not_affect_original():
    state = GameState()
    state.add_continuous_effect(source_id=1, layer=2, kind="x")
    cloned = state.clone()
    cloned.remove_continuous_effects_from_source(1)
    assert cloned.continuous_effects == []
    assert len(state.continuous_effects) == 1, (
        "Original registry must be unaffected by clone's mutation"
    )
