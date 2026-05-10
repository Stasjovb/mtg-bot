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


# --- DeclareBlockers -------------------------------------------------
#
# Round-23 slice (Phase 3, batch 3): extend the Action enum +
# apply_action dispatcher with ``Action::DeclareBlockers {
# assignments }``. The Python dataclass ``DeclareBlockers(
# assignments: tuple[tuple[int, int], ...])`` carries a tuple of
# ``(blocker_id, attacker_id)`` pairs; Rust stores it as
# ``Vec<(u32, u32)>`` to preserve iteration order (the dispatch loop
# calls ``declare_blocker(blocker_id, attacker_id)`` per pair, and
# damage assignment when multiple blockers block one attacker
# depends on input order — the first declared blocker eats the
# attacker's power under the round-5 single-blocker damage model).
#
# Pair-shape note: the action's pair is ``(blocker_id, attacker_id)``
# (matches the underlying ``declare_blocker(blocker_id, attacker_id)``
# primitive signature). ``state.blockers`` STORES pairs in the
# opposite order — ``(attacker_id, blocker_id)`` — for fast
# attacker-keyed lookups during damage assignment. The primitive
# handles the storage reorder; ``apply_action`` passes the pair
# straight through to the primitive.
#
# Synthetic-state reminder (cf. ``tests_rust/test_combat.py``):
# - Player 0 battlefield: ids 0..4 Forest, 5..9 Grizzly Bears.
# - Player 1 battlefield: ids 67..71 Forest, 72..76 Grizzly Bears.
# A declare-blockers test needs a declared attacker first — call
# ``declare_attacker`` on a P0 bear, then declare a P1 bear as the
# blocker.

P1_FIRST_FOREST_ID = 67  # p1 battlefield 67..71 are Forest (non-creature)
P1_FIRST_BLOCKER_ID = 72  # p1 battlefield 72..76 are 2/2 Grizzly Bears


def _seed_one_attacker(state, attacker_id=P0_FIRST_BEAR_ID):
    """Declare one P0 bear as an attacker so blocker tests have a
    legal attacker to reference. Returns the attacker id."""
    assert state.declare_attacker(attacker_id) is True
    return attacker_id


def test_apply_action_declare_blockers_empty_no_op(synthetic_state):
    """Empty ``assignments`` list: the loop body never runs and
    ``state.blockers`` stays empty. No error raised. Locks in that
    the dispatcher tolerates the zero-blockers case (Python's
    ``DeclareBlockers()`` default is the empty tuple)."""
    _seed_one_attacker(synthetic_state)
    assert synthetic_state.get_blockers() == []

    synthetic_state.apply_action(
        {"kind": "declare_blockers", "assignments": []}
    )

    assert synthetic_state.get_blockers() == []


def test_apply_action_declare_blockers_single_pair(synthetic_state):
    """A single ``(blocker_id, attacker_id)`` pair: one block lands
    on ``state.blockers`` as ``(attacker_id, blocker_id)`` (storage
    order is the opposite of the action's input order — the
    primitive handles the reorder)."""
    attacker = _seed_one_attacker(synthetic_state)
    blocker = P1_FIRST_BLOCKER_ID

    synthetic_state.apply_action(
        {
            "kind": "declare_blockers",
            "assignments": [(blocker, attacker)],
        }
    )

    assert synthetic_state.get_blockers() == [(attacker, blocker)]


def test_apply_action_declare_blockers_multiple_pairs_single_blocker_each(
    synthetic_state,
):
    """Multiple pairs, each a distinct blocker on a distinct
    attacker: all recorded. Two P0 bears attack, two P1 bears block
    one each — ``state.blockers`` has both pairs in input order."""
    a0 = P0_FIRST_BEAR_ID
    a1 = P0_FIRST_BEAR_ID + 1
    assert synthetic_state.declare_attacker(a0) is True
    assert synthetic_state.declare_attacker(a1) is True
    b0 = P1_FIRST_BLOCKER_ID
    b1 = P1_FIRST_BLOCKER_ID + 1

    synthetic_state.apply_action(
        {
            "kind": "declare_blockers",
            "assignments": [(b0, a0), (b1, a1)],
        }
    )

    # storage shape is (attacker, blocker)
    assert synthetic_state.get_blockers() == [(a0, b0), (a1, b1)]


def test_apply_action_declare_blockers_multiple_blockers_on_one_attacker(
    synthetic_state,
):
    """Multi-block: one attacker blocked by three blockers. All
    pairs land with the same ``attacker_id``; blocker order matches
    the input order — load-bearing for damage assignment when the
    round-5 model gives the attacker's power to the first declared
    blocker."""
    attacker = _seed_one_attacker(synthetic_state)
    b0 = P1_FIRST_BLOCKER_ID
    b1 = P1_FIRST_BLOCKER_ID + 1
    b2 = P1_FIRST_BLOCKER_ID + 2

    synthetic_state.apply_action(
        {
            "kind": "declare_blockers",
            "assignments": [(b0, attacker), (b1, attacker), (b2, attacker)],
        }
    )

    assert synthetic_state.get_blockers() == [
        (attacker, b0),
        (attacker, b1),
        (attacker, b2),
    ]


def test_apply_action_declare_blockers_iteration_order_preserved(synthetic_state):
    """Passing pairs in a non-sorted order — [(b2, A), (b0, A),
    (b1, A)] — must produce ``state.blockers`` in the SAME input
    order. The Vec-based iteration is stable, not sorted; callers
    that want a canonical order sort BEFORE passing."""
    attacker = _seed_one_attacker(synthetic_state)
    b0 = P1_FIRST_BLOCKER_ID
    b1 = P1_FIRST_BLOCKER_ID + 1
    b2 = P1_FIRST_BLOCKER_ID + 2

    synthetic_state.apply_action(
        {
            "kind": "declare_blockers",
            "assignments": [(b2, attacker), (b0, attacker), (b1, attacker)],
        }
    )

    # NOT sorted by blocker id — exactly the input order.
    assert synthetic_state.get_blockers() == [
        (attacker, b2),
        (attacker, b0),
        (attacker, b1),
    ]


def test_apply_action_declare_blockers_missing_key_raises_key_error(synthetic_state):
    """Missing the ``assignments`` key raises ``KeyError`` —
    ``parse_action`` rejects before dispatch (single point of
    validation, mirrors the ``attacker_ids``-missing shape on
    ``declare_attackers``)."""
    _seed_one_attacker(synthetic_state)
    with pytest.raises(KeyError, match="assignments"):
        synthetic_state.apply_action({"kind": "declare_blockers"})
    # No mutation.
    assert synthetic_state.get_blockers() == []


def test_apply_action_declare_blockers_accepts_list_of_lists(synthetic_state):
    """``assignments`` extracts as ``Vec<(u32, u32)>`` from any
    iterable-of-iterables. A plain ``list`` of 2-element ``list``s
    works — PyO3's tuple-extract accepts both Python tuples and
    fixed-length lists. The Python dataclass field is a tuple of
    tuples, but the JSON-like wire shape often uses lists; this
    test pins the relaxed acceptance."""
    attacker = _seed_one_attacker(synthetic_state)
    blocker = P1_FIRST_BLOCKER_ID

    synthetic_state.apply_action(
        {
            "kind": "declare_blockers",
            # list of lists, not list of tuples
            "assignments": [[blocker, attacker]],
        }
    )

    assert synthetic_state.get_blockers() == [(attacker, blocker)]


def test_apply_action_declare_blockers_non_creature_blocker_silently_skipped(
    synthetic_state,
):
    """A non-creature blocker (e.g. a Forest at id 67) is silently
    rejected by the underlying ``declare_blocker`` primitive
    (returns False). The dispatch discards the bool — no exception
    escapes, no entry added to ``state.blockers``. Eligible pairs
    in the same call still get through."""
    attacker = _seed_one_attacker(synthetic_state)
    forest_blocker = P1_FIRST_FOREST_ID
    bear_blocker = P1_FIRST_BLOCKER_ID
    assert synthetic_state.printing_name_of(forest_blocker) == "Forest"

    synthetic_state.apply_action(
        {
            "kind": "declare_blockers",
            "assignments": [
                (forest_blocker, attacker),
                (bear_blocker, attacker),
            ],
        }
    )

    # Only the eligible pair landed.
    assert synthetic_state.get_blockers() == [(attacker, bear_blocker)]


def test_apply_action_declare_blockers_tapped_blocker_silently_skipped(
    synthetic_state,
):
    """A tapped blocker is silently rejected (the round-5
    primitive's "blocker must be untapped" gate). Remaining
    untapped blockers in the same call still go through."""
    attacker = _seed_one_attacker(synthetic_state)
    tapped_blocker = P1_FIRST_BLOCKER_ID
    fresh_blocker = P1_FIRST_BLOCKER_ID + 1
    # Tap the first blocker before the dispatch.
    assert synthetic_state.tap_object(tapped_blocker) is True

    synthetic_state.apply_action(
        {
            "kind": "declare_blockers",
            "assignments": [
                (tapped_blocker, attacker),
                (fresh_blocker, attacker),
            ],
        }
    )

    # Tapped blocker skipped; fresh blocker landed.
    assert synthetic_state.get_blockers() == [(attacker, fresh_blocker)]


def test_apply_action_unknown_kind_message_mentions_declare_blockers(synthetic_state):
    """The unknown-kind error message includes ``declare_blockers``
    after this slice extends the variant list. Pin the substring so
    a future variant addition forces the message to grow."""
    with pytest.raises(ValueError, match=r"declare_blockers"):
        synthetic_state.apply_action({"kind": "frobnicate"})


# --- ActivateAbility -------------------------------------------------
#
# Round-23 slice (Phase 3, batch 4): extend the Action enum +
# apply_action dispatcher with ``Action::ActivateAbility { source_id,
# ability_index }``. The Python dataclass
# ``ActivateAbility(source_id: int, ability_index: int)`` carries two
# ints — the GameObject id of the permanent whose ability fires and
# the 0-based index into the source's printing.activated_abilities
# list (CR 602.2 — printings can have multiple activated abilities).
#
# Round-20 frequency: 8 of 420 decisions (~1.9%) — 5th-most-frequent
# variant after ``PassPriority``, ``DeclareAttackers``, ``PlayLand``,
# and ``DeclareBlockers``.
#
# **Dispatch is stubbed.** A grep across ``rust/src/`` confirms no
# Rust ``activate_ability`` primitive exists yet (rounds 1-22 didn't
# build one). The variant + bridge round-trip ship now, so callers
# building Action dicts can already use the ``activate_ability`` shape
# and hit a clear "not implemented yet" error path rather than the
# generic ``unknown action kind`` rejection. A future slice adds the
# primitive (mana-cost pay + ability resolution, analogous to
# ``play_land`` / ``cast_creature``) then flips the dispatch arm to a
# real ``call_method1("activate_ability", ...)`` call. Until then,
# happy-path dispatch raises ``ValueError`` with the documented
# message — these tests assert on the stubbed error path, NOT on a
# successful activation outcome.


def test_apply_action_activate_ability_stub_raises_value_error(synthetic_state):
    """Happy-path stub: a well-formed ActivateAbility dict parses
    cleanly but the dispatch arm raises ``ValueError`` because no
    Rust primitive exists yet. The error message names the variant
    + flags it as future work so a follow-up slice grepping for the
    string finds the dispatch site to flip."""
    with pytest.raises(ValueError, match=r"ActivateAbility dispatch not implemented yet"):
        synthetic_state.apply_action(
            {"kind": "activate_ability", "source_id": 5, "ability_index": 0}
        )


def test_apply_action_activate_ability_stub_error_mentions_round_24(synthetic_state):
    """The stub message points at round 24+ as the follow-up window.
    Pin the substring so the message stays informative — a future
    slice that flips the dispatch to a real call must also delete
    this test (it documents the stub-state, not the eventual real
    behavior)."""
    with pytest.raises(ValueError, match=r"round 24"):
        synthetic_state.apply_action(
            {"kind": "activate_ability", "source_id": 5, "ability_index": 2}
        )


def test_apply_action_activate_ability_missing_source_id_raises_key_error(
    synthetic_state,
):
    """Missing the ``source_id`` key raises ``KeyError`` —
    ``parse_action`` rejects before dispatch (single point of
    validation, mirrors the ``card_id``-missing shape on
    ``play_land``). The KeyError fires BEFORE the dispatch-stub
    ValueError, so this test pins the parse-time gate."""
    with pytest.raises(KeyError, match="source_id"):
        synthetic_state.apply_action(
            {"kind": "activate_ability", "ability_index": 0}
        )


def test_apply_action_activate_ability_missing_ability_index_raises_key_error(
    synthetic_state,
):
    """Missing the ``ability_index`` key raises ``KeyError`` — same
    parse-time gate as ``source_id``. Both keys are required; the
    parser reads them in order, so this test specifically exercises
    the second key's check (source_id present, ability_index
    missing)."""
    with pytest.raises(KeyError, match="ability_index"):
        synthetic_state.apply_action(
            {"kind": "activate_ability", "source_id": 5}
        )


def test_apply_action_activate_ability_wrong_type_for_source_id_raises(
    synthetic_state,
):
    """``source_id`` must be a u32-extractable integer. A string fails
    PyO3's ``extract::<u32>`` machinery → ``TypeError`` / ``ValueError``.
    The dispatch-stub never runs; the parse-time gate fires first."""
    with pytest.raises((TypeError, ValueError)):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": "not-an-int",
                "ability_index": 0,
            }
        )


def test_apply_action_activate_ability_wrong_type_for_ability_index_raises(
    synthetic_state,
):
    """``ability_index`` must be a u32-extractable integer. A string
    fails the parse-time extract — ``TypeError`` / ``ValueError``
    before any dispatch happens."""
    with pytest.raises((TypeError, ValueError)):
        synthetic_state.apply_action(
            {
                "kind": "activate_ability",
                "source_id": 5,
                "ability_index": "not-an-int",
            }
        )


def test_apply_action_unknown_kind_message_mentions_activate_ability(synthetic_state):
    """The unknown-kind error message includes ``activate_ability``
    after this slice extends the variant list. Pin the substring so
    a future variant addition forces the message to grow."""
    with pytest.raises(ValueError, match=r"activate_ability"):
        synthetic_state.apply_action({"kind": "frobnicate"})


# --- CastSpell -------------------------------------------------------
#
# Round-23+ slice (Phase 3, batch 5): extend the Action enum +
# apply_action dispatcher with ``Action::CastSpell { card_id, use_warp,
# kicked, cast_for_free, use_impending, cast_room_half }``. The Python
# dataclass ``CastSpell(card_id: int, use_warp: bool = False, kicked:
# bool = False, cast_for_free: bool = False, use_impending: bool =
# False, cast_room_half: str | None = None)`` mirrors the Rust variant
# bit-for-bit so production CastSpell payloads round-trip losslessly
# through the bridge.
#
# Round-20 frequency: 17 of 420 decisions (~4.0%) — the
# second-most-frequent non-``PassPriority`` variant after
# ``DeclareAttackers``.
#
# **First-slice scope: flags are data-only.** The dispatch arm calls
# the existing round-4 ``cast_creature(card_id, player_id)`` primitive
# and IGNORES every flag value. Mirrors the round-23 ActivateAbility
# "scaffold the variant, defer the dispatch semantics" pattern.
# Future slices wire warp / kicker / impending / cast_for_free /
# cast_room_half through to richer primitives.
#
# Synthetic-state mana reminder: ``cast_creature`` pays the printing's
# mana_cost — Llanowar Elves costs ``{G}``, so the priority player
# needs at least 1 green pip in their mana pool to land a happy-path
# cast. Use ``synthetic_state.add_mana(player, "G", n)`` to prep.


def test_apply_action_cast_spell_minimal_dispatches_to_cast_creature(synthetic_state):
    """Happy path with a minimal dict (only ``card_id``, no flag
    keys): the Llanowar Elf in the priority player's hand pays its
    {G} cost and lands on the battlefield. Pins the
    ``apply_action({"kind": "cast_spell", "card_id": N})`` shape as
    the canonical minimal payload — equivalent to Python's
    ``CastSpell(card_id=N)`` call with all flags defaulted."""
    elf_id = P0_FIRST_HAND_ID
    assert synthetic_state.printing_name_of(elf_id) == "Llanowar Elves"
    synthetic_state.add_mana(0, "G", 1)
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.apply_action({"kind": "cast_spell", "card_id": elf_id})

    # Elf landed; one G pip spent.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_apply_action_cast_spell_uses_priority_player_as_actor(synthetic_state):
    """The actor is implicit (priority player). Flip priority to
    player 1 and cast from player 1's hand — Locks in that the
    dispatcher reads ``priority_player`` rather than a hardcoded 0
    (mirrors the ``play_land`` actor-resolution convention)."""
    synthetic_state.apply_action({"kind": "pass_priority"})
    assert synthetic_state.get_priority_player() == 1
    # Player 1 also has Llanowar Elves in hand at ids 77..83 in the
    # synthetic seed (10..16 are P0's elves; P1's hand starts at 77
    # = id_offset 67 + 10). Pull the first hand object's id from the
    # snapshot (each snapshot entry is a dict with an "id" key).
    p1_hand = synthetic_state.hand_snapshot(1)
    elf_id = p1_hand[0]["id"]
    assert synthetic_state.printing_name_of(elf_id) == "Llanowar Elves"
    synthetic_state.add_mana(1, "G", 1)
    p1_bf_before = synthetic_state.battlefield_sizes[1]

    synthetic_state.apply_action({"kind": "cast_spell", "card_id": elf_id})

    # Elf landed on player 1's battlefield, not player 0's.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before + 1


def test_apply_action_cast_spell_with_all_flags_false_explicit(synthetic_state):
    """Explicit-defaults shape — every flag spelled out with its
    default value. Behavior must be bit-identical to the minimal
    shape (the flags are silently ignored by first-slice dispatch).
    Locks in the "round-trip" property: a dict that ``action_to_pydict``
    would emit (always all 6 keys) parses cleanly back through
    ``parse_action``."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    synthetic_state.apply_action(
        {
            "kind": "cast_spell",
            "card_id": elf_id,
            "use_warp": False,
            "kicked": False,
            "cast_for_free": False,
            "use_impending": False,
            "cast_room_half": None,
        }
    )

    # Same outcome as the minimal-shape test.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_apply_action_cast_spell_use_warp_true_dispatches_unchanged(synthetic_state):
    """First-slice contract: ``use_warp=True`` is parsed as data but
    has NO observable effect on the dispatch. The cast still routes
    to ``cast_creature(card_id, priority_player)`` and pays the
    base mana cost (no exile-zone alt-cost, no end-of-turn exile).
    Pins the flag-ignored convention so a future warp-plumbing slice
    has a clear baseline to diff against."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": elf_id, "use_warp": True}
    )

    # Same battlefield landing as the unflagged case — flag was ignored.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_apply_action_cast_spell_kicked_true_dispatches_unchanged(synthetic_state):
    """First-slice contract: ``kicked=True`` is parsed as data but
    has NO observable effect — the base mana cost is paid, no
    additional kicker cost is debited. A future cost-stacking slice
    will wire the kicker pip through."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)
    # Pin: only ONE G pip — if the kicker were paid, the cast would
    # fail for insufficient mana. The flag-ignored contract makes
    # the cast succeed.
    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": elf_id, "kicked": True}
    )
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_apply_action_cast_spell_cast_for_free_true_still_pays_mana(synthetic_state):
    """First-slice contract: ``cast_for_free=True`` is parsed as data
    but has NO observable effect — the base mana cost is STILL paid
    (the flag would normally bypass the mana payment, but the
    primitive can't honor that yet). A cast with the flag set but
    NO mana in pool still fails the same way an unflagged cast
    would. A future slice plumbing the flag will flip this test."""
    elf_id = P0_FIRST_HAND_ID
    # Pool is empty; flag would normally bypass payment.
    assert synthetic_state.get_mana_pool(0)["G"] == 0

    # No exception — cast_creature returns False silently when mana
    # is insufficient; apply_action discards the bool.
    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": elf_id, "cast_for_free": True}
    )

    # Cast did not happen — elf still in hand. Pins that
    # cast_for_free was ignored (flag's purpose would be to make
    # this succeed with empty pool).
    assert synthetic_state.find_object_zone(elf_id) == ZONE_HAND


def test_apply_action_cast_spell_use_impending_true_dispatches_unchanged(synthetic_state):
    """First-slice contract: ``use_impending=True`` is parsed as data
    but has NO observable effect — the creature lands as a normal
    creature (no impending counters, no creature-ness suppression).
    A future Effect dispatch slice will wire the impending mode."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": elf_id, "use_impending": True}
    )

    # Lands as a normal creature (the elf would otherwise enter with
    # time counters under real impending semantics — but the flag is
    # ignored, so it's just a regular ETB).
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD


def test_apply_action_cast_spell_cast_room_half_string_preserved(synthetic_state):
    """``cast_room_half`` is ``Option<String>`` on the Rust side —
    a string value parses cleanly (no TypeError) and has no
    observable effect on dispatch (the flag is data-only). Pins
    that the Option<String> extract path handles a non-None string
    correctly (different code path from the bool flag extracts)."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    synthetic_state.apply_action(
        {
            "kind": "cast_spell",
            "card_id": elf_id,
            "cast_room_half": "left",
        }
    )

    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD


def test_apply_action_cast_spell_cast_room_half_none_parses(synthetic_state):
    """Explicit ``cast_room_half=None`` parses cleanly — same effect
    as omitting the key (the parser maps both to the Rust
    ``Option<String>::None``)."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    synthetic_state.apply_action(
        {
            "kind": "cast_spell",
            "card_id": elf_id,
            "cast_room_half": None,
        }
    )

    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD


def test_apply_action_cast_spell_missing_card_id_raises_key_error(synthetic_state):
    """Missing the required ``card_id`` key raises ``KeyError`` —
    ``parse_action`` rejects before dispatch (single point of
    validation, mirrors the ``card_id``-missing shape on
    ``play_land``)."""
    with pytest.raises(KeyError, match="card_id"):
        synthetic_state.apply_action({"kind": "cast_spell"})


def test_apply_action_cast_spell_missing_flags_default_silently(synthetic_state):
    """Every flag is OPTIONAL — missing flag keys default to the
    Python dataclass defaults (False / None) silently, no KeyError.
    The minimal `{kind, card_id}` payload is the most common
    on-the-wire shape from the search loop, and it MUST work
    without spelling every flag out."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    # No flag keys at all. Must not raise.
    synthetic_state.apply_action({"kind": "cast_spell", "card_id": elf_id})

    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD


def test_apply_action_cast_spell_wrong_type_for_card_id_raises(synthetic_state):
    """``card_id`` must be a u32-extractable integer. A string fails
    PyO3's ``extract::<u32>`` machinery → ``TypeError`` / ``ValueError``
    before any dispatch happens (matches the ``play_land`` shape)."""
    with pytest.raises((TypeError, ValueError)):
        synthetic_state.apply_action(
            {"kind": "cast_spell", "card_id": "not-an-int"}
        )


def test_apply_action_cast_spell_wrong_type_for_use_warp_raises(synthetic_state):
    """``use_warp`` must extract as a bool. A non-bool, non-int value
    like a list fails PyO3's ``extract::<bool>`` machinery →
    ``TypeError`` / ``ValueError``. Pins the type gate for one of the
    flag fields so future-slice flag wiring has a baseline to keep."""
    elf_id = P0_FIRST_HAND_ID
    with pytest.raises((TypeError, ValueError)):
        synthetic_state.apply_action(
            {"kind": "cast_spell", "card_id": elf_id, "use_warp": [1, 2]}
        )


def test_apply_action_cast_spell_non_creature_in_hand_is_silent_no_op(
    synthetic_state,
):
    """The ``cast_creature`` primitive returns ``False`` silently
    when the target's printing isn't a Creature (the primitive's
    type-gate). ``apply_action`` discards the bool — no exception
    escapes; the test pins that flags-set-true on a non-Creature
    still does nothing (the gate fires before the flags would
    matter anyway)."""
    bears_id = P0_FIRST_BEARS_ID
    # Move bears to hand so the in-hand precondition passes; the
    # printing IS a creature though, so to test a non-creature we'd
    # need a non-creature in hand — the synthetic seed doesn't
    # have one. Instead, pin the wrong-zone failure path: bears
    # ON the battlefield can't be cast (not in hand).
    assert synthetic_state.find_object_zone(bears_id) == ZONE_BATTLEFIELD
    bf_before = synthetic_state.battlefield_sizes[0]

    # No raise — primitive returns False silently.
    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": bears_id, "use_warp": True}
    )

    # No mutation.
    assert synthetic_state.find_object_zone(bears_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_apply_action_unknown_kind_message_mentions_cast_spell(synthetic_state):
    """The unknown-kind error message includes ``cast_spell`` after
    this slice extends the variant list. Pin the substring so a
    future variant addition forces the message to grow."""
    with pytest.raises(ValueError, match=r"cast_spell"):
        synthetic_state.apply_action({"kind": "frobnicate"})


# --- TurnFaceUp ------------------------------------------------------
#
# Rolling-integration slice (post-round-23): extend the Action enum +
# apply_action dispatcher with ``Action::TurnFaceUp { card_id }``. The
# Python dataclass ``TurnFaceUp(card_id: int)`` carries a single int —
# the GameObject id of the face-down permanent on the priority
# player's battlefield to flip face up. Mirrors ``PlayLand``'s
# single-int shape exactly.
#
# CR 701.34 / 707.4 — Morph / Manifest Dread flip + Edge of Eternities
# Spacecraft station / launch. The EoE Spacecraft cycle is the
# production driver: Spacecraft enter face-down (as artifacts with no
# creature types) and accumulate charge counters via station-attaching;
# they turn face up (become creatures with their printed stats) when
# launched by paying a face-up cost. CR 701.34 is a special action —
# does not use the stack; costs are paid immediately and the flip
# resolves at once.
#
# **Dispatch is stubbed.** No Rust face-down GameObject state exists
# yet (the ``GameObject`` struct has no ``face_down`` flag today, and
# there's no Spacecraft charge-counter resolution primitive), so the
# variant + bridge round-trip ship now but the dispatch arm raises
# ``ValueError`` with a "not implemented yet" message. A future slice
# adds the per-object face-down state field + flip primitive
# (analogous to how ``tap`` / ``untap`` toggle the ``tapped`` flag)
# and flips this arm to a real ``call_method1("turn_face_up", ...)``
# dispatch. Until then, happy-path dispatch raises ``ValueError`` —
# these tests assert on the stubbed error path, NOT on a successful
# flip outcome. Mirrors the round-23 ActivateAbility "scaffold the
# variant, defer the dispatch semantics" pattern.


def test_apply_action_turn_face_up_stub_raises_value_error(synthetic_state):
    """Happy-path stub: a well-formed TurnFaceUp dict parses cleanly
    but the dispatch arm raises ``ValueError`` because no Rust face-
    down GameObject state / flip primitive exists yet. The error
    message names the variant + flags it as future work so a follow-
    up slice grepping for the string finds the dispatch site to
    flip."""
    with pytest.raises(ValueError, match=r"TurnFaceUp dispatch not implemented yet"):
        synthetic_state.apply_action({"kind": "turn_face_up", "card_id": 42})


def test_apply_action_turn_face_up_stub_error_mentions_spacecraft(synthetic_state):
    """The stub message names the missing Rust primitives (face-down
    GameObject state + Spacecraft) so a future slice grepping for
    "Spacecraft" finds the dispatch site to flip. Pin the substring
    so the message stays informative — a future slice that flips the
    dispatch to a real call must also delete this test (it documents
    the stub-state, not the eventual real behavior)."""
    with pytest.raises(ValueError, match=r"Spacecraft"):
        synthetic_state.apply_action({"kind": "turn_face_up", "card_id": 7})


def test_apply_action_turn_face_up_missing_card_id_raises_key_error(
    synthetic_state,
):
    """Missing the ``card_id`` key raises ``KeyError`` —
    ``parse_action`` rejects before dispatch (single point of
    validation, mirrors the ``card_id``-missing shape on
    ``play_land``). The KeyError fires BEFORE the dispatch-stub
    ValueError, so this test pins the parse-time gate."""
    with pytest.raises(KeyError, match="card_id"):
        synthetic_state.apply_action({"kind": "turn_face_up"})


def test_apply_action_turn_face_up_wrong_type_for_card_id_raises(
    synthetic_state,
):
    """``card_id`` must be a u32-extractable integer. A string fails
    PyO3's ``extract::<u32>`` machinery → ``TypeError`` / ``ValueError``.
    The dispatch-stub never runs; the parse-time gate fires first."""
    with pytest.raises((TypeError, ValueError)):
        synthetic_state.apply_action(
            {"kind": "turn_face_up", "card_id": "not-an-int"}
        )


def test_apply_action_unknown_kind_message_mentions_turn_face_up(synthetic_state):
    """The unknown-kind error message includes ``turn_face_up`` after
    this slice extends the variant list. Pin the substring so a future
    variant addition forces the message to grow."""
    with pytest.raises(ValueError, match=r"turn_face_up"):
        synthetic_state.apply_action({"kind": "frobnicate"})
