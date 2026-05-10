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


# --- DeclareAttackers ------------------------------------------------
#
# Round-23 slice (Phase 3, batch 2): extend the Action enum +
# apply_action dispatcher with ``Action::DeclareAttackers {
# attacker_ids }``. The Python dataclass ``DeclareAttackers(
# attacker_ids: frozenset[int])`` carries a frozenset; the bridge
# serializes it to a list at the FFI boundary. Rust stores it as
# ``Vec<u32>`` to preserve iteration order (the dispatch loop calls
# ``declare_attacker(obj_id)`` per id, and tests want deterministic
# application order).
#
# Synthetic-state reminder (cf. ``tests_rust/test_combat.py``):
# - Player 0 battlefield: ids 0..4 Forest (non-creature, P=None),
#   5..9 Grizzly Bears (2/2 creature, not summoning-sick — seeded
#   onto the battlefield, not cast).
# - Player 0 hand: ids 10..16, all Llanowar Elves (1/1).
# - Player 1 battlefield: ids 67..71 Forest, 72..76 Grizzly Bears.

P0_FIRST_BEAR_ID = 5  # 5..9 are 2/2 Grizzly Bears, not summoning-sick


def test_apply_action_declare_attackers_empty_set_no_op(synthetic_state):
    """Empty ``attacker_ids`` set: the loop body never runs and
    ``state.attackers`` stays empty. No error raised. Locks in that
    the dispatcher tolerates the zero-attackers case (Python's
    ``DeclareAttackers()`` default is ``frozenset()``)."""
    assert synthetic_state.get_attackers() == []
    synthetic_state.apply_action(
        {"kind": "declare_attackers", "attacker_ids": []}
    )
    assert synthetic_state.get_attackers() == []


def test_apply_action_declare_attackers_single_attacker(synthetic_state):
    """Single attacker id: one creature declares; ``state.attackers``
    contains that id; the creature is tapped (per the round-5
    primitive's tap-on-declare semantics)."""
    bear_id = P0_FIRST_BEAR_ID
    assert synthetic_state.is_tapped(bear_id) is False

    synthetic_state.apply_action(
        {"kind": "declare_attackers", "attacker_ids": [bear_id]}
    )

    assert synthetic_state.get_attackers() == [bear_id]
    assert synthetic_state.is_tapped(bear_id) is True


def test_apply_action_declare_attackers_multiple(synthetic_state):
    """Multiple attacker ids: every eligible id is declared and the
    final ``state.attackers`` reflects all of them in dispatch order."""
    ids = [P0_FIRST_BEAR_ID, P0_FIRST_BEAR_ID + 1, P0_FIRST_BEAR_ID + 2]

    synthetic_state.apply_action(
        {"kind": "declare_attackers", "attacker_ids": ids}
    )

    assert synthetic_state.get_attackers() == ids
    for bear_id in ids:
        assert synthetic_state.is_tapped(bear_id) is True


def test_apply_action_declare_attackers_iteration_order_preserved(synthetic_state):
    """Passing the ids in a non-sorted order — [bear+2, bear, bear+1]
    — must produce a ``state.attackers`` list in the SAME order
    (Vec iteration is stable, not sorted). Locks in the deterministic
    application order — callers that want sorted dispatch sort
    BEFORE passing; the dispatcher doesn't impose an order."""
    a = P0_FIRST_BEAR_ID + 2
    b = P0_FIRST_BEAR_ID
    c = P0_FIRST_BEAR_ID + 1

    synthetic_state.apply_action(
        {"kind": "declare_attackers", "attacker_ids": [a, b, c]}
    )

    # NOT sorted — exactly the input order.
    assert synthetic_state.get_attackers() == [a, b, c]


def test_apply_action_declare_attackers_missing_key_raises_key_error(synthetic_state):
    """Missing the ``attacker_ids`` key raises ``KeyError`` —
    ``parse_action`` rejects before dispatch (single point of
    validation, mirrors the ``card_id``-missing error shape on
    ``play_land``)."""
    with pytest.raises(KeyError, match="attacker_ids"):
        synthetic_state.apply_action({"kind": "declare_attackers"})
    # No mutation.
    assert synthetic_state.get_attackers() == []


def test_apply_action_declare_attackers_accepts_python_list(synthetic_state):
    """``attacker_ids`` extracts as ``Vec<u32>`` from any Python
    iterable. A plain ``list`` works (this is the bridge's canonical
    on-the-wire shape — the dict serialization at the bridge
    boundary converts the dataclass's frozenset to a list)."""
    bear_id = P0_FIRST_BEAR_ID
    # list literal — the standard shape.
    synthetic_state.apply_action(
        {"kind": "declare_attackers", "attacker_ids": [bear_id]}
    )
    assert synthetic_state.get_attackers() == [bear_id]


def test_apply_action_declare_attackers_accepts_frozenset(synthetic_state):
    """``attacker_ids`` also works when passed as a Python
    ``frozenset`` — same shape as Python's dataclass field. PyO3's
    ``extract::<Vec<u32>>()`` accepts any iterable, so the bridge
    doesn't have to be the only on-the-wire shape. Order is not
    asserted because frozenset has no defined iteration order;
    membership is enough."""
    bear_id = P0_FIRST_BEAR_ID
    synthetic_state.apply_action(
        {"kind": "declare_attackers", "attacker_ids": frozenset([bear_id])}
    )
    assert synthetic_state.get_attackers() == [bear_id]


def test_apply_action_declare_attackers_non_creature_silently_skipped(synthetic_state):
    """Non-creature ids (e.g. a Forest at id 0) are silently rejected
    by the underlying ``declare_attacker`` primitive (returns False).
    The dispatch discards the bool — no exception escapes, no entry
    added to ``state.attackers``. Eligible ids in the same call still
    get through."""
    forest_id = 0  # P0 Forest — not a creature
    bear_id = P0_FIRST_BEAR_ID
    assert synthetic_state.printing_name_of(forest_id) == "Forest"

    synthetic_state.apply_action(
        {"kind": "declare_attackers", "attacker_ids": [forest_id, bear_id]}
    )

    # Only the eligible id landed on the attackers list.
    assert synthetic_state.get_attackers() == [bear_id]
    # Forest stayed untapped — no side effect from the rejected call.
    assert synthetic_state.is_tapped(forest_id) is False


def test_apply_action_declare_attackers_already_tapped_silently_skipped(
    synthetic_state,
):
    """An already-tapped creature in the set is silently rejected
    (the round-5 primitive's "must be untapped to attack" gate). The
    dispatch propagates the False return as a silent skip; remaining
    untapped creatures in the set still get declared."""
    tapped_bear = P0_FIRST_BEAR_ID
    fresh_bear = P0_FIRST_BEAR_ID + 1
    # Tap the first bear before the dispatch.
    assert synthetic_state.tap_object(tapped_bear) is True

    synthetic_state.apply_action(
        {
            "kind": "declare_attackers",
            "attacker_ids": [tapped_bear, fresh_bear],
        }
    )

    # Tapped bear skipped; fresh bear declared.
    assert synthetic_state.get_attackers() == [fresh_bear]
    assert synthetic_state.is_tapped(fresh_bear) is True


def test_apply_action_declare_attackers_wrong_inner_type_raises(synthetic_state):
    """A non-integer in the ``attacker_ids`` iterable fails PyO3's
    ``extract::<u32>`` machinery — ``TypeError`` propagates. The
    dispatch never runs; ``state.attackers`` stays empty."""
    with pytest.raises((TypeError, ValueError)):
        synthetic_state.apply_action(
            {
                "kind": "declare_attackers",
                "attacker_ids": ["not-an-int"],
            }
        )
    # No mutation.
    assert synthetic_state.get_attackers() == []


def test_apply_action_unknown_kind_message_mentions_declare_attackers(synthetic_state):
    """The unknown-kind error message includes ``declare_attackers``
    after this slice extends the variant list. Pin the substring so
    a future variant addition forces the message to grow."""
    with pytest.raises(ValueError, match=r"declare_attackers"):
        synthetic_state.apply_action({"kind": "frobnicate"})
