"""End-to-end tests for ``GameState.apply_action(action_dict)``.

Round-22 foundation slice — Phase 3 kickoff of the Rust ``Action`` enum
+ apply_action dispatcher. Mirrors the Python ``Action`` subclass
hierarchy in ``src/mtg_bot/actions.py``: each Python ``Action`` (and
its dict serialization that the search loop emits) gets a matching
Rust variant inside ``rust/src/actions.rs``, and ``apply_action`` is
the bridge that turns a dict into a state mutation.

**Slice scope.** Only the ``PassPriority`` variant is wired up in this
slice. Round-20 measurements showed ``PassPriority`` was 364 of 420
decisions (~87%) in a sample game — the obvious first variant. The
``apply_action`` dispatcher exists so callers can drive Rust state
through the same shape of dict the Python search loop already builds;
future slices grow the match arm (CastSpell, PlayLand, ...) plus a
``legal_decisions`` enumerator without changing the bridge shape.

**Bridge surface is end-to-end only.** ``parse_action`` /
``action_to_pydict`` are module-internal helpers in ``actions.rs``;
this slice exposes them only through ``apply_action`` (the actually-
useful pyfunction). A future slice can lift them to module-level
``#[pyfunction]`` if a test needs to round-trip a dict in isolation,
but today the end-to-end path is what matters and avoids touching
``lib.rs``.
"""

from __future__ import annotations

import pytest


def test_apply_action_pass_priority_toggles_priority(synthetic_state):
    """``apply_action({"kind": "pass_priority"})`` routes to the
    existing ``pass_priority()`` primitive — priority flips from
    active player (0) to the other player (1)."""
    assert synthetic_state.get_priority_player() == 0
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.get_priority_player() == 1


def test_apply_action_pass_priority_twice_returns_to_original(synthetic_state):
    """The pass-priority dispatch is involutive — two applies return
    to the starting priority player. Locks in that the dispatch
    routes to the toggle primitive (not the give-priority-to
    primitive with a fixed argument)."""
    synthetic_state.apply_action({"kind": "pass_priority"})
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.get_priority_player() == 0


def test_apply_action_returns_none(synthetic_state):
    """``apply_action`` is a side-effecting mutator — Python
    convention is to return ``None``. Locks in that callers can't
    accidentally rely on a return value the future grow-the-arm
    slices might change."""
    result = synthetic_state.apply_action({"kind": "pass_priority"})
    assert result is None


def test_apply_action_unknown_kind_raises_value_error(synthetic_state):
    """Unknown ``kind`` strings raise ``ValueError`` with a helpful
    message listing the valid kinds. Single point of validation:
    ``parse_action`` rejects before dispatch."""
    with pytest.raises(ValueError, match="unknown action kind"):
        synthetic_state.apply_action({"kind": "frobnicate"})
    # State unchanged after the rejected call.
    assert synthetic_state.get_priority_player() == 0


def test_apply_action_missing_kind_raises_key_error(synthetic_state):
    """Missing the ``kind`` key raises ``KeyError`` — mirrors the
    ``cards.rs`` ``require`` helper's error shape so callers
    that handle one bridge's errors handle them all the same way."""
    with pytest.raises(KeyError, match="kind"):
        synthetic_state.apply_action({})
    assert synthetic_state.get_priority_player() == 0


def test_apply_action_does_not_affect_active_player(synthetic_state):
    """Active player and priority player are independent fields.
    ``apply_action({"kind": "pass_priority"})`` moves only
    ``priority_player``; ``active_player`` stays put (mirrors the
    underlying ``pass_priority()`` primitive's contract)."""
    starting_active = synthetic_state.active_player
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.active_player == starting_active


def test_apply_action_on_clone_does_not_affect_original(synthetic_state):
    """CoW canary via the Action bridge: applying an action to a clone
    mutates only the clone's priority. The original is untouched.
    The clone is a by-value copy of the ``priority_player`` u8 field
    here, but this test pins the behavior so a future slice that
    moves state into an Arc-backed structure doesn't silently leak
    mutations back."""
    cloned = synthetic_state.clone_once()
    cloned.apply_action({"kind": "pass_priority"})
    assert cloned.get_priority_player() == 1
    assert synthetic_state.get_priority_player() == 0
