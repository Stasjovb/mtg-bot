"""End-to-end tests for ``GameState.apply_action(action_dict)``.

Phase 3 of the Rust ``Action`` enum + apply_action dispatcher. Mirrors
the Python ``Action`` subclass hierarchy in ``src/mtg_bot/actions.py``:
each Python ``Action`` (and its dict serialization that the search
loop emits) gets a matching Rust variant inside ``rust/src/actions.rs``,
and ``apply_action`` is the bridge that turns a dict into a state
mutation.

**Slice scope.** Round 22 wired ``PassPriority`` (364 of 420 decisions
/ ~87% in the round-20 measurement). Round 23 adds ``PlayLand`` (10 of
420 / ~2.4% — the 4th-most-frequent variant). The ``apply_action``
dispatcher exists so callers can drive Rust state through the same
shape of dict the Python search loop already builds; future slices
grow the match arm (CastSpell, Activate, ...) plus a
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


# --- PlayLand --------------------------------------------------------
#
# Round-23 slice: extend the Action enum + apply_action dispatcher
# with ``Action::PlayLand { card_id }``. The Python dataclass
# ``PlayLand(card_id: int)`` carries only the card id; the implicit
# actor is the priority player. The Rust ``play_land(obj_id,
# player_id)`` primitive itself takes both — apply_action reads
# ``state.priority_player`` and forwards.
#
# Synthetic-state reminder (cf. ``tests_rust/test_cast.py``):
# - Player 0 hand: ids 10..16, all Llanowar Elves (card_types =
#   ["Creature"]).
# - Player 0 battlefield: ids 0..4 Forest, 5..9 Grizzly Bears.
# - Player 0 library: ids 17..66, all Forest. Tests that need a
#   Forest in hand pull one over via ``move_object``.

ZONE_HAND = 0
ZONE_BATTLEFIELD = 2
P0_FIRST_BATTLEFIELD_ID = 0
P0_FIRST_BEARS_ID = 5
P0_FIRST_HAND_ID = 10  # Llanowar Elves
P0_FIRST_LIBRARY_ID = 17  # first Forest in library


def _move_forest_into_hand(state, player_id=0):
    """Move a Forest from ``player_id``'s library into their hand and
    return its id. Mirrors the helper in ``tests_rust/test_cast.py`` —
    the synthetic seed has only Llanowar Elves in hand, so PlayLand
    tests need to import a land first."""
    forest_id = P0_FIRST_LIBRARY_ID
    assert state.printing_name_of(forest_id) == "Forest"
    assert state.move_object(forest_id, ZONE_HAND, player_id) is True
    assert state.find_object_zone(forest_id) == ZONE_HAND
    return forest_id


def test_apply_action_play_land_dispatches_to_play_land(synthetic_state):
    """Happy path: a Forest in the priority player's hand moves to
    the battlefield after ``apply_action({"kind": "play_land",
    "card_id": forest_id})``. The dispatch routes through
    ``call_method1("play_land", (card_id, priority_player))``."""
    forest_id = _move_forest_into_hand(synthetic_state, 0)
    assert synthetic_state.get_priority_player() == 0
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.apply_action({"kind": "play_land", "card_id": forest_id})

    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1


def test_apply_action_play_land_uses_priority_player_as_actor(synthetic_state):
    """The actor is implicit (priority player). Flip priority to
    player 1, import a Forest into player 1's hand, and verify
    apply_action moves it onto player 1's battlefield — not
    player 0's. Locks in that the dispatcher reads
    ``priority_player`` rather than a hardcoded 0."""
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.get_priority_player() == 1

    forest_id = _move_forest_into_hand(synthetic_state, 1)
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_bf_before = synthetic_state.battlefield_sizes[1]
    p0_hand_before = synthetic_state.hand_sizes[0]
    p0_bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.apply_action({"kind": "play_land", "card_id": forest_id})

    # Forest landed on player 1's battlefield.
    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    assert synthetic_state.hand_sizes[1] == p1_hand_before - 1
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before + 1
    # Player 0 entirely untouched.
    assert synthetic_state.hand_sizes[0] == p0_hand_before
    assert synthetic_state.battlefield_sizes[0] == p0_bf_before


def test_apply_action_play_land_missing_card_id_raises_key_error(synthetic_state):
    """Missing the ``card_id`` key raises ``KeyError`` —
    ``parse_action`` rejects before dispatch (single point of
    validation, mirrors the ``kind``-missing error shape)."""
    with pytest.raises(KeyError, match="card_id"):
        synthetic_state.apply_action({"kind": "play_land"})
    # No mutation.
    assert synthetic_state.get_priority_player() == 0


def test_apply_action_play_land_wrong_type_for_card_id_raises_value_error(
    synthetic_state,
):
    """``card_id`` must be a u32-extractable integer. A string raises
    ``TypeError`` from PyO3's ``extract::<u32>`` machinery (Python's
    standard mapping for failed numeric extraction)."""
    with pytest.raises((TypeError, ValueError)):
        synthetic_state.apply_action(
            {"kind": "play_land", "card_id": "not-an-int"}
        )
    # No mutation.
    assert synthetic_state.get_priority_player() == 0


def test_apply_action_play_land_on_non_land_is_a_silent_no_op(synthetic_state):
    """The ``play_land`` primitive returns ``false`` (no raise) when
    the target card isn't a land — e.g. Grizzly Bears
    (card_types = ["Creature"]). ``apply_action`` discards the bool
    return; the test pins that no state mutation occurs and no
    exception escapes."""
    bears_id = P0_FIRST_BEARS_ID
    assert synthetic_state.printing_name_of(bears_id) == "Grizzly Bears"
    # Yank the Bears off the battlefield and into hand.
    assert synthetic_state.move_object(bears_id, ZONE_HAND, 0) is True
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    # No raise — the underlying primitive returns false silently.
    synthetic_state.apply_action({"kind": "play_land", "card_id": bears_id})

    # Bears stayed in hand; no battlefield growth.
    assert synthetic_state.find_object_zone(bears_id) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_apply_action_play_land_on_card_not_in_hand_is_a_silent_no_op(
    synthetic_state,
):
    """The ``play_land`` primitive requires the card to be in the
    actor's hand; a card already on the battlefield (or any id not
    in hand) gets a ``false`` return with no mutation. The dispatch
    propagates the same shape — no exception, no state change."""
    forest_id = P0_FIRST_BATTLEFIELD_ID  # already on the battlefield
    assert synthetic_state.printing_name_of(forest_id) == "Forest"
    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.apply_action({"kind": "play_land", "card_id": forest_id})

    # Forest stayed on the battlefield, hand untouched.
    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_apply_action_play_land_twice_in_a_row_both_succeed(synthetic_state):
    """The ``play_land`` primitive does not enforce one-land-per-turn
    (per the round-4 module docstring — that's the caller's job via
    ``legal_decisions``). ``apply_action`` mustn't add the gate
    either: two consecutive PlayLand dispatches both succeed,
    producing two new lands on the battlefield. A future
    legal_decisions slice will filter the second call out at the
    decision-enumeration layer; the dispatcher stays dumb."""
    forest_a = _move_forest_into_hand(synthetic_state, 0)
    # Pull a second Forest into hand from the library.
    forest_b = P0_FIRST_LIBRARY_ID + 1
    assert synthetic_state.printing_name_of(forest_b) == "Forest"
    assert synthetic_state.move_object(forest_b, ZONE_HAND, 0) is True

    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.apply_action({"kind": "play_land", "card_id": forest_a})
    synthetic_state.apply_action({"kind": "play_land", "card_id": forest_b})

    assert synthetic_state.find_object_zone(forest_a) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(forest_b) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 2


def test_apply_action_unknown_kind_message_mentions_play_land(synthetic_state):
    """The unknown-kind error message lists the valid kinds. Round 23
    extends the list to include ``play_land``. Pin the substring so a
    future variant addition forces the message to grow."""
    with pytest.raises(ValueError, match=r"play_land"):
        synthetic_state.apply_action({"kind": "frobnicate"})
