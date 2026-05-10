"""Mulligan / opening-hand primitives on ``GameState``.

Ports the mulligan pre-game pattern from MTG CR 103.4 (London
mulligan): on a mulligan, the player puts their entire current hand
back into the library, shuffles, and draws a fresh hand of 7. The
caller separately tracks the mulligan count and (per London) chooses
which N cards to put on the bottom afterwards — that "put N back to
bottom" step is a separate primitive that this slice does not yet
provide.

**Scope decisions for this slice (single primitive: ``mulligan``):**

- ``mulligan(player_id, seed) -> ()``: move all cards in the player's
  hand BACK to library, shuffle the library with ``seed``, draw 7
  (or until library is empty if it has fewer than 7 cards). This
  matches both opening-hand semantics (called once at game start
  with seed=N) and iterative-mulligan semantics (called repeatedly
  with different seeds for each mulligan; the caller owns the count).

- The earlier sketch had a separate ``opening_hand`` convenience that
  shuffles + draws 7 without returning the existing hand to the
  library. That collapses to the same operation as ``mulligan`` once
  you observe that the synthetic state seeds 7 cards in hand
  already, so any opening-hand call is logically a hand-replace.
  The slice exposes only ``mulligan`` to keep the API one knob.

- "Put N to bottom" (London mulligan endgame) is deferred to a
  future slice — caller would scry-style choose N cards from the
  fresh hand and bottom them. Not in scope here.

**Cross-file friction.** ``shuffle_library_with_seed`` (round-4
library) and ``draw_card`` (round-1 zones) are pymethods, exposed
to Python but Rust-private. Calling either of them from
``state_ops_mulligan.rs`` would require either making them ``pub``
(touches sibling files) or duplicating the inline xorshift64 +
Fisher-Yates + draw/move logic. Per the recurring round pattern,
this slice inlines the logic; the duplication is documented in the
module docstring and is the next thing to clean up when a later
slice consolidates.

**Determinism.** Same source state cloned twice + ``mulligan(p, seed)``
with the same seed produces identical hands and identical library
orderings. The library shuffle is a pure function of (library state
after hand-return, seed); the draw is deterministic on top of that.
"""

from __future__ import annotations

import pytest


# Synthetic state default layout: 10 battlefield, 7 hand, 50 library
# per side. Player 0 ids 0..66 (battlefield 0..9, hand 10..16, library
# 17..66); player 1 ids 67..133 in the same partition.
P0_LIBRARY_SIZE = 50
P0_HAND_SIZE = 7


# --- Hand-of-7 invariants --------------------------------------------------


def test_mulligan_results_in_hand_of_seven(synthetic_state):
    """After ``mulligan(0, seed)`` the player has exactly 7 cards in
    hand. Library size is preserved (7 returned, 7 drawn = net zero)."""
    assert synthetic_state.hand_sizes[0] == P0_HAND_SIZE
    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE

    synthetic_state.mulligan(0, 42)

    assert synthetic_state.hand_sizes[0] == 7
    # 7 returned to library + 7 drawn = library size unchanged.
    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE


def test_mulligan_does_not_affect_other_player(synthetic_state):
    """Mulliganing player 0 leaves player 1's hand and library
    untouched."""
    p1_hand_before = synthetic_state.hand_sizes[1]
    p1_lib_before = synthetic_state.library_sizes[1]

    synthetic_state.mulligan(0, 42)

    assert synthetic_state.hand_sizes[1] == p1_hand_before
    assert synthetic_state.library_sizes[1] == p1_lib_before


def test_mulligan_total_card_count_preserved(synthetic_state):
    """No cards are lost or duplicated during the rotation: the sum
    of (hand + library + graveyard) sizes for player 0 is unchanged."""
    before = (
        synthetic_state.hand_sizes[0]
        + synthetic_state.library_sizes[0]
        + synthetic_state.graveyard_sizes[0]
    )
    synthetic_state.mulligan(0, 7)
    after = (
        synthetic_state.hand_sizes[0]
        + synthetic_state.library_sizes[0]
        + synthetic_state.graveyard_sizes[0]
    )
    assert before == after


# --- Determinism -----------------------------------------------------------


def _hand_obj_ids_via_scry(state, player_id):
    """We can't enumerate hand ids directly from Python — scry only
    reads the library. Instead, snapshot the library top-first via
    scry; the hand obj_ids are everything in the original synthetic
    state's id range minus the ones we see in library + battlefield +
    graveyard. Easier: read library top-first via scry to compare
    library order, and compare hand size as a proxy for hand-content
    determinism, with the library order being the load-bearing
    determinism check (since hand = top 7 of pre-shuffle library)."""
    return state.scry(player_id, P0_LIBRARY_SIZE)


def test_mulligan_with_seed_is_deterministic(synthetic_state):
    """Same source state cloned twice + mulligan with the same seed
    produces identical library orderings. Since the hand is drawn
    from the post-shuffle top, identical library order also implies
    identical hand contents."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.mulligan(0, 1234)
    b.mulligan(0, 1234)

    a_lib = _hand_obj_ids_via_scry(a, 0)
    b_lib = _hand_obj_ids_via_scry(b, 0)
    assert a_lib == b_lib
    assert a.hand_sizes == b.hand_sizes
    assert a.library_sizes == b.library_sizes


def test_mulligan_with_different_seeds_likely_differ(synthetic_state):
    """Different seeds produce different library orderings. With a
    50-card library two random shuffles colliding is ~1/50!, i.e.
    effectively never."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.mulligan(0, 1)
    b.mulligan(0, 9999)

    a_lib = _hand_obj_ids_via_scry(a, 0)
    b_lib = _hand_obj_ids_via_scry(b, 0)
    assert a_lib != b_lib


# --- Edge cases ------------------------------------------------------------


def test_mulligan_unknown_player_raises(synthetic_state):
    """An out-of-range player_id raises ValueError."""
    with pytest.raises(ValueError):
        synthetic_state.mulligan(99, 42)


def test_mulligan_when_total_below_seven_draws_what_exists(engine):
    """If hand + library combined have fewer than 7 cards, draw what
    exists — the player ends up with a hand equal to the total."""
    # Build a state with only 3 hand + 2 library = 5 total for player 0.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=3, num_library=2
    )
    assert state.hand_sizes[0] == 3
    assert state.library_sizes[0] == 2

    state.mulligan(0, 42)

    # All 5 cards moved into hand; library is empty.
    assert state.hand_sizes[0] == 5
    assert state.library_sizes[0] == 0


# --- CoW canary ------------------------------------------------------------


def test_clone_then_mulligan_does_not_affect_original(synthetic_state):
    """Mulligan on a clone must not leak back into the source's hand
    or library. Load-bearing CoW canary."""
    cloned = synthetic_state.clone_once()
    source_hand_before = synthetic_state.hand_sizes[0]
    source_lib_before = synthetic_state.library_sizes[0]
    source_lib_order_before = synthetic_state.scry(0, P0_LIBRARY_SIZE)

    cloned.mulligan(0, 777)

    # Source hand + library size unchanged.
    assert synthetic_state.hand_sizes[0] == source_hand_before
    assert synthetic_state.library_sizes[0] == source_lib_before
    # Source library order still in the original (insertion) order.
    source_lib_order_after = synthetic_state.scry(0, P0_LIBRARY_SIZE)
    assert source_lib_order_after == source_lib_order_before
    # Clone's library was actually shuffled (clone diverged).
    cloned_lib_order = cloned.scry(0, P0_LIBRARY_SIZE)
    assert cloned_lib_order != source_lib_order_before


# --- mulligan_to_n: parameterized hand size --------------------------------
#
# Round-17 slice. Generalizes ``mulligan(player, seed)`` (always-7) into
# ``mulligan_to_n(player, n_cards, seed)`` so a caller implementing the
# London mulligan can request hand sizes 7, 6, 5, ... directly. This
# slice does NOT model the "put N cards on the bottom" step — that's
# deferred. The hand is simply shuffled back into the library and
# ``n_cards`` are drawn off the top.


def test_mulligan_to_n_draws_n_cards(synthetic_state):
    """``mulligan_to_n(0, 4, 42)`` ends with exactly 4 cards in hand."""
    synthetic_state.mulligan_to_n(0, 4, 42)
    assert synthetic_state.hand_sizes[0] == 4
    # 7 returned + 4 drawn = library net -3 from original.
    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE - (4 - P0_HAND_SIZE)


def test_mulligan_to_n_zero_cards_returns_empty_hand(synthetic_state):
    """``mulligan_to_n(player, 0, seed)`` empties the hand and returns
    every card to the library — total card count preserved."""
    total_before = (
        synthetic_state.hand_sizes[0] + synthetic_state.library_sizes[0]
    )

    synthetic_state.mulligan_to_n(0, 0, 42)

    assert synthetic_state.hand_sizes[0] == 0
    # All hand returned, none drawn back: library size = total before.
    assert synthetic_state.library_sizes[0] == total_before


def test_mulligan_to_n_more_than_library_raises(engine):
    """If ``n_cards`` exceeds the post-return library size, raise
    ValueError. Defensive guard — real London never asks for more
    cards than the library can provide."""
    # 3 hand + 2 library = 5 total; asking for 6 must raise.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=3, num_library=2
    )
    with pytest.raises(ValueError):
        state.mulligan_to_n(0, 6, 42)


def test_mulligan_to_n_negative_n_raises(synthetic_state):
    """Negative ``n_cards`` is nonsensical — raise ValueError."""
    with pytest.raises(ValueError):
        synthetic_state.mulligan_to_n(0, -1, 42)


def test_mulligan_to_n_unknown_player_raises(synthetic_state):
    """Out-of-range player_id raises ValueError."""
    with pytest.raises(ValueError):
        synthetic_state.mulligan_to_n(99, 4, 42)


def test_mulligan_to_n_deterministic_with_same_seed(synthetic_state):
    """Same seed → same resulting hand AND library order across two
    independent clones."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.mulligan_to_n(0, 5, 1234)
    b.mulligan_to_n(0, 5, 1234)

    assert a.hand_sizes == b.hand_sizes
    assert a.library_sizes == b.library_sizes
    # Library order (post-shuffle, post-draw) must match.
    assert a.scry(0, a.library_sizes[0]) == b.scry(0, b.library_sizes[0])


def test_mulligan_to_n_different_seeds_different_hands(synthetic_state):
    """Different seeds produce different library orderings (and
    therefore different drawn hands). 50-card library makes a
    collision negligible."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.mulligan_to_n(0, 5, 1)
    b.mulligan_to_n(0, 5, 9999)

    a_lib = a.scry(0, a.library_sizes[0])
    b_lib = b.scry(0, b.library_sizes[0])
    assert a_lib != b_lib


def test_mulligan_to_n_clone_isolation(synthetic_state):
    """Running ``mulligan_to_n`` on a clone leaves the source state's
    hand and library untouched. CoW canary."""
    cloned = synthetic_state.clone_once()
    source_hand_before = synthetic_state.hand_sizes[0]
    source_lib_before = synthetic_state.library_sizes[0]
    source_lib_order_before = synthetic_state.scry(0, P0_LIBRARY_SIZE)

    cloned.mulligan_to_n(0, 3, 777)

    assert synthetic_state.hand_sizes[0] == source_hand_before
    assert synthetic_state.library_sizes[0] == source_lib_before
    assert synthetic_state.scry(0, P0_LIBRARY_SIZE) == source_lib_order_before
    # Clone diverged: hand size matches the requested n.
    assert cloned.hand_sizes[0] == 3


# --- bottom_cards_from_hand: London-mulligan bottoming ---------------------
#
# Round-18 slice. Completes the London mulligan rule (CR 103.4): after
# `mulligan_to_n(player, 7, seed)` the player has a fresh 7-card hand;
# `bottom_cards_from_hand(player, n_mulligans)` then puts the FIRST
# `n_mulligans` cards of that hand on the BOTTOM of the library
# (deterministic order — a future decision-callback slice models real
# player choice). "Library bottom" = INDEX 0 of the Vec; "library top"
# = LAST element of the Vec (matches the round-1 zone convention and
# `scry`).
#
# Default fixture layout (player 0):
#   - hand obj_ids: 10, 11, 12, 13, 14, 15, 16  (insertion order)
#   - library obj_ids: 17, 18, ..., 66  (lib[0]=17 bottom, lib[49]=66 top)
# `scry(0, lib_size)` returns top-first: [66, 65, ..., 17].


def test_bottom_cards_moves_first_n_to_library_bottom(synthetic_state):
    """`bottom_cards_from_hand(0, 2)` removes hand[0..2] (ids 10, 11)
    and puts them on the bottom of the library so that lib[0] = 10
    (bottom-most) and lib[1] = 11 — i.e. hand[0] ends up at the very
    bottom of the library, hand[1] just above it."""
    synthetic_state.bottom_cards_from_hand(0, 2)

    assert synthetic_state.hand_sizes[0] == P0_HAND_SIZE - 2
    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE + 2

    # Read the full library top-first via scry. Last two entries are
    # the new bottom of the library: scry result is [top, ..., bottom],
    # so the very last is lib[0] = id 10, second-to-last is lib[1] = 11.
    full = synthetic_state.scry(0, synthetic_state.library_sizes[0])
    assert full[-1] == 10  # hand[0] now at library bottom
    assert full[-2] == 11  # hand[1] just above it
    # Library top unchanged: lib's last element was id 66 before, still 66.
    assert full[0] == 66


def test_bottom_cards_zero_no_op(synthetic_state):
    """`bottom_cards_from_hand(player, 0)` is a no-op — hand and
    library are unchanged."""
    hand_before = synthetic_state.hand_sizes[0]
    lib_before = synthetic_state.library_sizes[0]
    lib_order_before = synthetic_state.scry(0, P0_LIBRARY_SIZE)

    synthetic_state.bottom_cards_from_hand(0, 0)

    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.library_sizes[0] == lib_before
    assert synthetic_state.scry(0, P0_LIBRARY_SIZE) == lib_order_before


def test_bottom_cards_more_than_hand_raises(synthetic_state):
    """`n` greater than the current hand size raises ValueError."""
    with pytest.raises(ValueError):
        synthetic_state.bottom_cards_from_hand(0, P0_HAND_SIZE + 1)


def test_bottom_cards_negative_raises(synthetic_state):
    """Negative `n` is nonsensical — raise ValueError."""
    with pytest.raises(ValueError):
        synthetic_state.bottom_cards_from_hand(0, -1)


def test_bottom_cards_unknown_player_raises(synthetic_state):
    """Out-of-range `player_id` raises ValueError."""
    with pytest.raises(ValueError):
        synthetic_state.bottom_cards_from_hand(99, 1)


def test_bottom_cards_preserves_library_top(synthetic_state):
    """The card on top of the library (last element of the Vec, id 66
    in the default fixture) is unaffected by bottoming — bottoming
    inserts at index 0 only."""
    top_before = synthetic_state.scry(0, 1)
    assert top_before == [66]

    synthetic_state.bottom_cards_from_hand(0, 3)

    top_after = synthetic_state.scry(0, 1)
    assert top_after == [66]


def test_bottom_cards_clone_isolation(synthetic_state):
    """Bottoming on a clone must not leak back into the source state's
    hand or library. CoW canary."""
    cloned = synthetic_state.clone_once()
    source_hand_before = synthetic_state.hand_sizes[0]
    source_lib_before = synthetic_state.library_sizes[0]
    source_lib_order_before = synthetic_state.scry(0, P0_LIBRARY_SIZE)

    cloned.bottom_cards_from_hand(0, 2)

    # Source untouched.
    assert synthetic_state.hand_sizes[0] == source_hand_before
    assert synthetic_state.library_sizes[0] == source_lib_before
    assert synthetic_state.scry(0, P0_LIBRARY_SIZE) == source_lib_order_before
    # Clone diverged.
    assert cloned.hand_sizes[0] == source_hand_before - 2
    assert cloned.library_sizes[0] == source_lib_before + 2


def test_bottom_cards_full_hand_empties_hand(synthetic_state):
    """Bottoming all 7 cards of a 7-card hand leaves the hand empty
    and grows the library by 7."""
    synthetic_state.bottom_cards_from_hand(0, P0_HAND_SIZE)

    assert synthetic_state.hand_sizes[0] == 0
    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE + P0_HAND_SIZE
    # The seven bottomed cards (ids 10..16, in hand insertion order)
    # are now at lib[0..7], with hand[0]=10 at the very bottom.
    full = synthetic_state.scry(0, synthetic_state.library_sizes[0])
    # Reverse the tail of `full` — full is top-first, so the last 7
    # entries (in reverse) reconstruct lib[0..7] in order.
    bottom_seven_in_order = list(reversed(full[-P0_HAND_SIZE:]))
    assert bottom_seven_in_order == [10, 11, 12, 13, 14, 15, 16]
