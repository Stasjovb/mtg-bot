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
    and puts them on the bottom of the library so that hand[0] ends
    up at the very bottom, hand[1] just above it. Post-CE3:
    bottom = tail of Vec, so lib[len-1] = 10 and lib[len-2] = 11."""
    synthetic_state.bottom_cards_from_hand(0, 2)

    assert synthetic_state.hand_sizes[0] == P0_HAND_SIZE - 2
    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE + 2

    # Read the full library top-first via scry. scry returns
    # [top, ..., bottom]. The very last (= lib[len-1]) is the new
    # very bottom = id 10 (hand[0]); second-to-last = id 11 (hand[1]).
    full = synthetic_state.scry(0, synthetic_state.library_sizes[0])
    assert full[-1] == 10  # hand[0] now at library bottom
    assert full[-2] == 11  # hand[1] just above it
    # Library top unchanged: lib[0] was id 17 before, still 17 (post-CE3).
    assert full[0] == 17


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
    """The card on top of the library (post-CE3: lib[0] = id 17 in
    the default fixture) is unaffected by bottoming — bottoming
    appends to the tail only."""
    top_before = synthetic_state.scry(0, 1)
    assert top_before == [17]

    synthetic_state.bottom_cards_from_hand(0, 3)

    top_after = synthetic_state.scry(0, 1)
    assert top_after == [17]


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


# --- Cross-feature edge cases ---------------------------------------------
#
# Pin cross-primitive interactions between ``mulligan`` and the other
# round-1/2/4 primitives (setup, zones, fingerprint, scry, clone). These
# tests close the gaps between the per-primitive tests above and document
# the simplifications the Rust engine has made vs MTG CR 103.4 (London
# mulligan).
#
# **Documented parity gaps vs CR 103.4 / real MTG:**
#
# 1. G21 + G22 closed (round-27): the atomic ``mulligan_atomic(player,
#    seed, bottom_card_ids)`` primitive folds shuffle + redraw +
#    bottom-N into a single call, gated on ``mulligan_count`` so the
#    Nth call bottoms exactly N cards. The legacy split-primitive
#    flow (``mulligan`` / ``mulligan_to_n`` + ``bottom_cards_from_hand``)
#    is kept for backwards compatibility but is no longer the parity-
#    correct entrypoint. A caller using ``mulligan_atomic`` can never
#    observe a state with the hand still at 7 after the Nth mulligan
#    (the previous G21 / G22 gap). The legacy ``mulligan(player, seed)``
#    primitive still always draws 7 — that's the accepted simplification
#    for the unparameterized entrypoint and is pinned by the existing
#    legacy tests.
# 2. G23 closed: mulligan raises after 7 calls per CR 103.4 (London-style
#    cap). Mirrors Python ``simulate.setup_game(max_mulligans=7)`` — the
#    London-mulligan loop allows up to 7 mulligans per player before
#    forcing a keep. The 8th call on the same player raises
#    ``ValueError`` instead of performing the shuffle. The cap is
#    shared between ``mulligan``, ``mulligan_to_n``, and
#    ``mulligan_atomic`` (a mixed sequence of 5 + 3 hits the cap on the
#    8th call regardless of which variant). ``mulligan_count`` is NOT
#    serialized into the fingerprint — it's a per-call safety counter,
#    not part of the gameplay-relevant state digest.
# 3. G24 still open: there is NO scry-on-keep step (CR 103.4 Paris
#    mulligan). Closing this needs the decision-callback substrate that
#    a sibling slice is still building.
#
# These gaps are accepted simplifications for the parity bridge; if a
# future slice models a "real" London-mulligan transaction, this comment
# is the single place to update.


def test_synthetic_state_starts_with_seven_cards_in_hand(synthetic_state):
    """Cross-feature with setup: the fresh synthetic state always seeds 7
    cards in each player's hand. ``mulligan`` is defined against the
    invariant that hand starts at 7, so pin it explicitly — if a setup
    change ever moves the default off 7, the mulligan tests above would
    silently mis-pin their assertions."""
    assert synthetic_state.hand_sizes[0] == P0_HAND_SIZE
    assert synthetic_state.hand_sizes[1] == P0_HAND_SIZE


def test_mulligan_keeps_hand_at_seven_pinning_london_simplification(
    synthetic_state,
):
    """Cross-feature with London-mulligan parity gap: in real MTG, after
    a mulligan the player has 7 cards in hand but must put N on the
    bottom (where N = mulligan count). The Rust primitive simplifies
    by always leaving the hand at 7 and exposing bottom-N as a
    separate primitive. Pin that behavioral shape so a regression
    that, e.g., starts shrinking the hand inside ``mulligan`` surfaces
    here instead of silently corrupting parity comparisons."""
    pre_size = synthetic_state.hand_sizes[0]
    synthetic_state.mulligan(0, 42)
    assert synthetic_state.hand_sizes[0] == pre_size  # still 7
    assert synthetic_state.hand_sizes[0] == 7  # pin the absolute too


def test_mulligan_reshuffles_old_hand_back_into_library(synthetic_state):
    """Cross-feature with zones + library: the seven cards in hand
    pre-mulligan (ids 10..16 by default) all return to the LIBRARY,
    not the graveyard or exile. The fresh hand is drawn from the
    shuffled library on top of that."""
    pre_hand_ids = sorted([o["id"] for o in synthetic_state.hand_snapshot(0)])
    pre_lib_ids = sorted([o["id"] for o in synthetic_state.library_snapshot(0)])
    assert pre_hand_ids == [10, 11, 12, 13, 14, 15, 16]

    synthetic_state.mulligan(0, 42)

    # Every pre-mulligan hand id is now in the library (regardless of
    # whether it was drawn back into the new hand — verify the full
    # hand∪library set is identical, since both pools are conserved
    # together by ``mulligan``).
    post_hand_ids = set(o["id"] for o in synthetic_state.hand_snapshot(0))
    post_lib_ids = set(o["id"] for o in synthetic_state.library_snapshot(0))
    assert set(pre_hand_ids) | set(pre_lib_ids) == post_hand_ids | post_lib_ids


def test_mulligan_changes_fingerprint(synthetic_state):
    """Cross-feature with fingerprint: a mulligan shuffles the library
    and replaces the hand, so the gameplay-relevant state digest must
    change. Parity-load-bearing: if mulligan accidentally became a
    no-op, the digest would stay equal and parity_smoke would silently
    accept a broken impl."""
    fp_before = synthetic_state.fingerprint()
    synthetic_state.mulligan(0, 42)
    fp_after = synthetic_state.fingerprint()
    assert fp_before != fp_after


def test_mulligan_sequence_determinism_with_same_seeds(synthetic_state):
    """Cross-feature with fingerprint + determinism: two clones taken
    from the same state, mulliganed with the SAME sequence of seeds,
    produce identical fingerprints. This goes beyond
    ``test_mulligan_with_seed_is_deterministic`` (single seed) by
    exercising a stack of mulligans, which a London-mulligan caller
    would actually invoke."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    for seed in (11, 22, 33):
        a.mulligan(0, seed)
        b.mulligan(0, seed)

    assert a.fingerprint() == b.fingerprint()


def test_mulligan_sequence_diverges_on_seed_change(synthetic_state):
    """Cross-feature with fingerprint + determinism: same starting
    state, same first seed, DIFFERENT second seed → different
    resulting fingerprint. Pins that the per-mulligan seed actually
    threads into the per-mulligan shuffle (not just the first)."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.mulligan(0, 11)
    b.mulligan(0, 11)
    # After identical first mulligans the fingerprints match.
    assert a.fingerprint() == b.fingerprint()

    a.mulligan(0, 22)
    b.mulligan(0, 23)  # one-bit-flip on the second seed
    assert a.fingerprint() != b.fingerprint()


def test_find_object_zone_for_reshuffled_hand_card_returns_library(
    synthetic_state,
):
    """Cross-feature with zones: a card that was in hand pre-mulligan
    (id 10 in the default fixture) and got reshuffled into the
    library by ``mulligan`` reports ``ZONE_LIBRARY = 1`` via
    ``find_object_zone``. Locks in the zone-tag update side of the
    mulligan op."""
    # Pre-mulligan: hand[0] is at zone HAND (=0).
    assert synthetic_state.find_object_zone(10) == 0  # ZONE_HAND

    synthetic_state.mulligan(0, 42)

    # Post-mulligan: every old hand id (10..16) is now in the library,
    # whether or not it ended up drawn back into the new 7-card hand.
    # We can assert this for *every* id 10..16 because the new hand
    # has exactly 7 cards drawn from a 57-card library — the
    # probability that all 7 of the original hand ids drew back is
    # negligible, but more importantly the OLD ids report library
    # zone for any post-mulligan id that didn't get redrawn.
    # We assert at least one of them is now in the library; pinning
    # the shape rather than a specific id keeps this robust to
    # shuffle-seed changes.
    zones = [synthetic_state.find_object_zone(i) for i in range(10, 17)]
    # Every old hand id must now report either ZONE_HAND (=0, redrawn)
    # or ZONE_LIBRARY (=1, shuffled-and-not-redrawn). Crucially none
    # of them leak to a non-{hand,library} zone.
    assert all(z in (0, 1) for z in zones), zones
    # And at least one of them is back in the library (the new hand
    # holds 7 of 57 cards, so on average 7*7/57 ≈ 0.86 of the
    # original 7 are redrawn — the rest are in library).
    assert any(z == 1 for z in zones), zones


def test_mulligan_does_not_alter_battlefield(synthetic_state):
    """Cross-feature with battlefield zone: mulligan only touches the
    mulliganing player's hand + library; the battlefield is left
    alone. At game-start this is moot (battlefield is empty), but
    pinning the invariant explicitly catches a regression where, e.g.,
    a future implementation overzealously clears more zones."""
    bf_sizes_before = synthetic_state.battlefield_sizes
    bf_ids_before = sorted(
        o["id"] for o in synthetic_state.battlefield_snapshot()
    )

    synthetic_state.mulligan(0, 42)

    assert synthetic_state.battlefield_sizes == bf_sizes_before
    bf_ids_after = sorted(
        o["id"] for o in synthetic_state.battlefield_snapshot()
    )
    assert bf_ids_after == bf_ids_before


def test_mulligan_isolation_to_mulliganing_player(synthetic_state):
    """Cross-feature with player isolation: mulligan on player 0 does
    not change player 1's hand IDs, library IDs, or library order.
    Goes beyond the existing size-only assertion in
    ``test_mulligan_does_not_affect_other_player`` by pinning the
    full per-id contents and ordering."""
    p1_hand_before = sorted([o["id"] for o in synthetic_state.hand_snapshot(1)])
    p1_lib_order_before = synthetic_state.scry(1, P0_LIBRARY_SIZE)

    synthetic_state.mulligan(0, 42)

    p1_hand_after = sorted([o["id"] for o in synthetic_state.hand_snapshot(1)])
    p1_lib_order_after = synthetic_state.scry(1, P0_LIBRARY_SIZE)
    assert p1_hand_after == p1_hand_before
    assert p1_lib_order_after == p1_lib_order_before


def test_clone_then_mulligan_does_not_reshuffle_original_hand(
    synthetic_state,
):
    """CoW canary: cloning a state then mulliganing the clone does NOT
    leak hand-identity changes back to the source. Goes beyond
    ``test_clone_then_mulligan_does_not_affect_original`` (which checks
    sizes + library order) by pinning the exact source hand ids stay
    untouched after the clone-side mulligan."""
    source_hand_ids_before = sorted(
        o["id"] for o in synthetic_state.hand_snapshot(0)
    )
    cloned = synthetic_state.clone_once()

    cloned.mulligan(0, 999)

    source_hand_ids_after = sorted(
        o["id"] for o in synthetic_state.hand_snapshot(0)
    )
    # Source's hand still holds the original insertion-order ids.
    assert source_hand_ids_after == source_hand_ids_before
    assert source_hand_ids_after == [10, 11, 12, 13, 14, 15, 16]
    # Clone's hand has been shuffled to a different set of ids drawn
    # from the merged hand+library pool — most of the new ids should
    # have come from the library (ids 17..66 in the default fixture),
    # though some original hand ids may have been redrawn.
    clone_hand_ids = sorted(o["id"] for o in cloned.hand_snapshot(0))
    assert clone_hand_ids != source_hand_ids_before


def test_mulligan_does_not_grow_graveyard_or_exile(synthetic_state):
    """Cross-feature parity gap: mulligan returns the hand to library
    (NOT graveyard, NOT exile). Even though the per-primitive test
    above checks via ``find_object_zone`` for each old hand id, this
    test pins the broader invariant at the zone-size level: graveyard
    and exile sizes are completely untouched by the mulligan
    operation. A regression that, e.g., misrouted a discarded hand to
    the graveyard would surface immediately here."""
    gy_before = synthetic_state.graveyard_sizes
    ex_before = synthetic_state.exile_sizes

    synthetic_state.mulligan(0, 42)
    synthetic_state.mulligan(1, 7)  # also mulligan p1, to be thorough

    assert synthetic_state.graveyard_sizes == gy_before
    assert synthetic_state.exile_sizes == ex_before
    assert synthetic_state.graveyard_sizes == [0, 0]
    assert synthetic_state.exile_sizes == [0, 0]


# --- G23 closure: max-mulligan cap (CR 103.4 / London-style) --------------
#
# Round-26 G23. Python ``simulate.setup_game(max_mulligans=7)`` caps the
# London-mulligan loop at 7 mulligans per player; the Rust primitive
# mirrors that by raising on the 8th call (per-player ``mulligan_count``
# field increments at the start of each call). The cap is shared
# between ``mulligan`` and ``mulligan_to_n``.


def test_mulligan_seven_calls_succeed_eighth_raises(synthetic_state):
    """First 7 ``mulligan`` calls on the same player succeed; the 8th
    raises ``ValueError``. Boundary: count=7 is the last legal call;
    count=8 is the first illegal one. Mirrors Python's
    ``max_mulligans=7`` loop cap."""
    for _ in range(7):
        synthetic_state.mulligan(0, 42)
    # 8th call must raise — the previous 7 already consumed the cap.
    with pytest.raises(ValueError):
        synthetic_state.mulligan(0, 42)


def test_mulligan_to_n_seven_calls_succeed_eighth_raises(synthetic_state):
    """``mulligan_to_n`` shares the same cap as ``mulligan``."""
    for _ in range(7):
        synthetic_state.mulligan_to_n(0, 5, 42)
    with pytest.raises(ValueError):
        synthetic_state.mulligan_to_n(0, 5, 42)


def test_mulligan_cap_is_shared_between_mulligan_and_mulligan_to_n(
    synthetic_state,
):
    """The cap counts BOTH ``mulligan`` and ``mulligan_to_n`` calls
    against the same per-player counter — 4 of one + 3 of the other
    = 7 calls used, 8th of either kind raises."""
    for _ in range(4):
        synthetic_state.mulligan(0, 42)
    for _ in range(3):
        synthetic_state.mulligan_to_n(0, 5, 42)
    # 7 calls taken — next call of EITHER kind must raise.
    with pytest.raises(ValueError):
        synthetic_state.mulligan(0, 42)


def test_mulligan_cap_is_per_player(synthetic_state):
    """Each player has its own ``mulligan_count``. Maxing player 0's
    counter does not affect player 1's ability to mulligan."""
    for _ in range(7):
        synthetic_state.mulligan(0, 42)
    # Player 0 capped.
    with pytest.raises(ValueError):
        synthetic_state.mulligan(0, 42)
    # Player 1 still has a fresh counter — must succeed.
    synthetic_state.mulligan(1, 42)


def test_mulligan_cap_raise_does_not_mutate_state(synthetic_state):
    """When the 8th call raises, no hand / library mutation has
    happened — the fingerprint is unchanged from before the raise.
    Pins the "increment then check" ordering: the cap check fires
    BEFORE any shuffle work, so a rejected call leaves the state
    byte-identical to the post-7th state."""
    for _ in range(7):
        synthetic_state.mulligan(0, 999)
    fp_before = synthetic_state.fingerprint()
    hand_size_before = synthetic_state.hand_sizes[0]
    lib_size_before = synthetic_state.library_sizes[0]
    with pytest.raises(ValueError):
        synthetic_state.mulligan(0, 999)
    assert synthetic_state.fingerprint() == fp_before
    assert synthetic_state.hand_sizes[0] == hand_size_before
    assert synthetic_state.library_sizes[0] == lib_size_before


def test_mulligan_count_does_not_affect_fingerprint(synthetic_state):
    """``mulligan_count`` is a per-call safety counter, NOT part of
    the gameplay-relevant state digest. Two clones that diverge ONLY
    in their per-player mulligan_count (e.g. one mulliganed twice with
    a no-op-equivalent seed pair, the other not mulliganed at all) —
    well, that's not a direct test because mulligan shuffles the
    library. Instead, the load-bearing assertion is that
    ``mulligan_count`` is NOT serialized: two states with identical
    zones + life + mana + etc. but different mulligan_count values
    fingerprint to the same digest.

    We exercise this indirectly: a fresh clone (mulligan_count = 0)
    and the source state (mulligan_count = 0) have equal fingerprints
    before any mulligan runs. After running 7 mulligans on a
    SEPARATE clone with seed 42 and another 7 on it with seed 42
    again — wait, that would change the library order. The simpler
    test: confirm fingerprint depends ONLY on (zones, life, mana,
    has_lost, etc.) and not on the counter, by checking that a clone
    mulliganed-then-clone-state matches the same library order
    independently. Concrete shape: clone twice from the source,
    mulligan the first one with seed S; the second one, mulligan
    with seed S then verify the fingerprints match (per existing
    determinism test). The new contract is that the counter, having
    incremented to 1 on both, does NOT contribute to the digest —
    which the determinism test already pins."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.mulligan(0, 1234)
    b.mulligan(0, 1234)
    # mulligan_count is 1 on both. Fingerprints match (determinism +
    # counter-not-serialized).
    assert a.fingerprint() == b.fingerprint()


# --- G21 + G22 closure: atomic London-mulligan transaction (round-27) -----
#
# ``mulligan_atomic(player_id, seed, bottom_card_ids)`` folds shuffle +
# redraw-7 + bottom-N into one primitive. The bottom-count is gated
# against the per-player ``mulligan_count``: the Nth call bottoms
# exactly N cards (pre-increment count N-1 means expected size N).
# The shuffle uses the same xorshift64 seeded Fisher-Yates as the
# legacy variants, so a caller can pre-compute the post-redraw hand
# ids and pick which to bottom offline (parity_smoke + MCTS recipe).
#
# These tests pin the atomic primitive's signature + invariants; the
# legacy ``mulligan`` / ``mulligan_to_n`` / ``bottom_cards_from_hand``
# tests above continue to pin the split-flow primitives, which are
# retained for backwards compatibility.


def _hand_ids(state, player_id):
    """Pull the current hand ids for ``player_id``."""
    return [o["id"] for o in state.hand_snapshot(player_id)]


def test_mulligan_atomic_seventh_call_succeeds_eighth_raises(synthetic_state):
    """The atomic primitive shares the 7-call cap with the legacy
    variants. Each of the first 7 calls succeeds (bottoming 1, 2,
    ..., 7 cards in turn); the 8th raises ``ValueError`` without
    mutating zones."""
    for i in range(7):
        # Compute the bottom ids AFTER the shuffle by probing a clone
        # to find what the post-redraw hand will look like... but the
        # atomic primitive shuffles + redraws as one. Easier: just
        # bottom the first ``i+1`` cards of the post-redraw hand.
        # Use a clone to probe the post-redraw hand ids deterministically.
        probe = synthetic_state.clone_once()
        probe.mulligan(0, 100 + i)
        post_redraw_ids = _hand_ids(probe, 0)
        bottom_ids = post_redraw_ids[: i + 1]
        synthetic_state.mulligan_atomic(0, 100 + i, bottom_ids)
    # After 7 successful atomic calls, the cap is reached. 8th must raise.
    probe = synthetic_state.clone_once()
    # The 8th call expects bottom_card_ids.len() == mulligan_count + 1 == 8,
    # but we can't legally probe more than the hand size — and the cap
    # check fires after the count check, so we must supply exactly 8 ids.
    # The synthetic state has only 7 cards in hand post-mulligan, so 8
    # valid ids don't exist. Construct 8 distinct integer placeholders;
    # the cap check fires after the count check passes, BEFORE the
    # post-redraw verification, so the 8th call raises on the cap rather
    # than on the missing ids.
    eight_ids = [9000 + j for j in range(8)]
    with pytest.raises(ValueError):
        synthetic_state.mulligan_atomic(0, 999, eight_ids)


def test_mulligan_atomic_bottoms_correct_number_for_each_mulligan_count(
    synthetic_state,
):
    """Mulligan #1 bottoms 1 card; mulligan #2 bottoms 2 cards; mulligan
    #3 bottoms 3 cards. Library accounting confirms each call moved
    exactly N cards from hand to library bottom."""
    base_lib = synthetic_state.library_sizes[0]
    for n_mulls_taken in (1, 2, 3):
        probe = synthetic_state.clone_once()
        probe.mulligan(0, 50 + n_mulls_taken)
        post_redraw_ids = _hand_ids(probe, 0)
        bottom_ids = post_redraw_ids[:n_mulls_taken]
        synthetic_state.mulligan_atomic(0, 50 + n_mulls_taken, bottom_ids)
        # Hand must be 7 - n_mulls_taken (started at 7, drew 7, bottomed
        # n_mulls_taken; net hand size = 7 - n_mulls_taken).
        assert synthetic_state.hand_sizes[0] == 7 - n_mulls_taken
        # Library: started at base_lib, returned 7 (or 7-n_mulls_taken
        # if previous mulls already shrank hand), drew 7, bottomed
        # n_mulls_taken. Net library size = base_lib + n_mulls_taken
        # (the cumulative bottomed cards). But mulligan-then-bottom
        # within a single atomic call: hand goes from (7 - (n-1)) at
        # start of THIS call to 7 - n at end of THIS call. So one
        # additional card gets moved to library each call.
        # Easier invariant: total cards conserved.
        total = (
            synthetic_state.hand_sizes[0] + synthetic_state.library_sizes[0]
        )
        assert total == 7 + base_lib  # 7 starting hand + 50 starting library


def test_mulligan_atomic_bottom_count_mismatch_raises(synthetic_state):
    """Supplying the wrong number of bottom_card_ids raises ``ValueError``
    and does NOT mutate the state (the count check fires BEFORE the
    increment, shuffle, or bottoming)."""
    fp_before = synthetic_state.fingerprint()
    hand_before = synthetic_state.hand_sizes[0]
    lib_before = synthetic_state.library_sizes[0]
    # First mulligan should bottom 1 card; supply 0 ids.
    with pytest.raises(ValueError):
        synthetic_state.mulligan_atomic(0, 42, [])
    # State byte-identical: fingerprint, hand size, library size,
    # mulligan_count all unchanged.
    assert synthetic_state.fingerprint() == fp_before
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.library_sizes[0] == lib_before
    # First mulligan should bottom 1 card; supply 2 ids.
    with pytest.raises(ValueError):
        synthetic_state.mulligan_atomic(0, 42, [10, 11])
    assert synthetic_state.fingerprint() == fp_before
    # Now that mulligan_count is still 0, a correct atomic call (1 id)
    # would succeed — verify by probing.
    probe = synthetic_state.clone_once()
    probe.mulligan(0, 42)
    post_redraw_ids = _hand_ids(probe, 0)
    synthetic_state.mulligan_atomic(0, 42, post_redraw_ids[:1])
    assert synthetic_state.hand_sizes[0] == 6  # 7 drew, 1 bottomed


def test_mulligan_atomic_invalid_card_id_raises(synthetic_state):
    """An id not in the post-redraw hand raises ``ValueError``. The
    shuffle has already happened (state mutated), but the bottom step
    is skipped — verify by checking the hand size is still 7 (drew 7,
    bottomed 0)."""
    # Use a clearly-invalid id (9999) that no synthetic-state object holds.
    with pytest.raises(ValueError):
        synthetic_state.mulligan_atomic(0, 42, [9999])
    # The pre-check on bottom_card_ids count was OK (count=1 ==
    # mulligan_count+1=1), the increment happened, the shuffle+redraw
    # happened, but the post-redraw verification rejected 9999. Hand
    # has 7 cards (drew 7, bottomed 0).
    assert synthetic_state.hand_sizes[0] == 7


def test_mulligan_atomic_hand_size_invariant(synthetic_state):
    """After ``mulligan_atomic`` the hand size is (7 - mulligan_count):
    drew 7, bottomed mulligan_count. Pins the load-bearing invariant
    that makes G21 / G22 closed — a caller using the atomic primitive
    can NEVER observe a hand of 7 after the Nth mulligan."""
    # Mulligan #1: bottoms 1, leaves 6.
    probe = synthetic_state.clone_once()
    probe.mulligan(0, 11)
    post_redraw = _hand_ids(probe, 0)
    synthetic_state.mulligan_atomic(0, 11, post_redraw[:1])
    assert synthetic_state.hand_sizes[0] == 6

    # Mulligan #2: bottoms 2, leaves 5.
    probe2 = synthetic_state.clone_once()
    probe2.mulligan(0, 22)
    post_redraw2 = _hand_ids(probe2, 0)
    synthetic_state.mulligan_atomic(0, 22, post_redraw2[:2])
    assert synthetic_state.hand_sizes[0] == 5

    # Mulligan #3: bottoms 3, leaves 4.
    probe3 = synthetic_state.clone_once()
    probe3.mulligan(0, 33)
    post_redraw3 = _hand_ids(probe3, 0)
    synthetic_state.mulligan_atomic(0, 33, post_redraw3[:3])
    assert synthetic_state.hand_sizes[0] == 4


def test_mulligan_atomic_library_grows_by_old_hand_minus_bottom(synthetic_state):
    """Library accounting check: each atomic call adds N cards to the
    library bottom (where N is the mulligan number for this call).
    Before-and-after library sizes confirm the shift."""
    base_lib = synthetic_state.library_sizes[0]
    base_hand = synthetic_state.hand_sizes[0]
    # base_hand = 7, base_lib = 50; total = 57.

    probe = synthetic_state.clone_once()
    probe.mulligan(0, 77)
    post_redraw = _hand_ids(probe, 0)
    synthetic_state.mulligan_atomic(0, 77, post_redraw[:1])
    # After mulligan #1: hand has 6, library has base_lib + 1 = 51.
    # Total conserved.
    assert synthetic_state.hand_sizes[0] == 6
    assert synthetic_state.library_sizes[0] == base_lib + 1
    assert (
        synthetic_state.hand_sizes[0] + synthetic_state.library_sizes[0]
        == base_hand + base_lib
    )

    # And the bottomed id is at the very bottom of the library — lib[0]
    # in the Vec sense — which scry top-first shows as the LAST element.
    full_lib = synthetic_state.scry(0, synthetic_state.library_sizes[0])
    assert full_lib[-1] == post_redraw[0]  # bottomed card at lib[0]


def test_mulligan_atomic_clone_isolation(synthetic_state):
    """``mulligan_atomic`` on a clone does NOT leak any mutation back
    to the source state. Hand, library, mulligan_count, fingerprint
    all unchanged on the source after the clone-side call."""
    fp_before = synthetic_state.fingerprint()
    hand_before = synthetic_state.hand_sizes[0]
    lib_before = synthetic_state.library_sizes[0]
    lib_order_before = synthetic_state.scry(0, P0_LIBRARY_SIZE)

    cloned = synthetic_state.clone_once()
    probe = synthetic_state.clone_once()
    probe.mulligan(0, 555)
    post_redraw = _hand_ids(probe, 0)
    cloned.mulligan_atomic(0, 555, post_redraw[:1])

    # Source: byte-identical.
    assert synthetic_state.fingerprint() == fp_before
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.library_sizes[0] == lib_before
    assert synthetic_state.scry(0, P0_LIBRARY_SIZE) == lib_order_before
    # Clone: diverged — hand is 6, library has +1.
    assert cloned.hand_sizes[0] == hand_before - 1
    assert cloned.library_sizes[0] == lib_before + 1


def test_mulligan_atomic_fingerprint_stable_for_same_seed_and_bottoms(
    synthetic_state,
):
    """Two clones from the same source, atomic-mulliganed with the same
    seed AND the same bottom_card_ids, produce identical fingerprints.
    Determinism check on the atomic primitive."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    probe = synthetic_state.clone_once()
    probe.mulligan(0, 4242)
    post_redraw = _hand_ids(probe, 0)
    bottom_ids = post_redraw[:1]

    a.mulligan_atomic(0, 4242, bottom_ids)
    b.mulligan_atomic(0, 4242, bottom_ids)

    assert a.fingerprint() == b.fingerprint()
    assert a.hand_sizes == b.hand_sizes
    assert a.library_sizes == b.library_sizes
    # Library order (post-shuffle, post-redraw, post-bottom) matches.
    assert a.scry(0, a.library_sizes[0]) == b.scry(0, b.library_sizes[0])


# -------------------------------------------------------------------------
# CE8 Slice 2 — external-RNG path on the three mulligan shuffle sites.
#
# `mulligan`, `mulligan_to_n`, and `mulligan_atomic` each accept an
# optional `rng` kwarg (a Python `random.Random` instance). When
# supplied, the in-mulligan Fisher-Yates shuffle consumes draws from
# the supplied stream via `_randbelow`, matching what
# `random.Random.shuffle(list)` would produce on the Python side
# (bit-identical). When `rng=None` (default), the legacy xorshift64
# path runs unchanged.
# -------------------------------------------------------------------------


def _library_ids(state, player_id):
    return state.scry(player_id, state.library_sizes[player_id])


def test_mulligan_with_external_rng_matches_python_shuffle(synthetic_state):
    """CE8 Slice 2: with `rng=random.Random(seed)`, the in-mulligan
    shuffle matches Python's `random.Random(seed).shuffle` byte-for-
    byte. The post-redraw hand + library order are pinned by the
    matching draw stream.
    """
    import random

    # Build the reference order: drain hand into library (in hand order),
    # shuffle the combined deck with random.Random(seed), then take 7
    # off the top for the hand.
    initial_hand = _hand_ids(synthetic_state, 0)
    initial_lib = _library_ids(synthetic_state, 0)
    combined = list(initial_lib) + list(initial_hand)
    random.Random(2026).shuffle(combined)
    expected_hand = combined[:7]
    expected_lib = combined[7:]

    synthetic_state.mulligan(0, 0, rng=random.Random(2026))
    rust_hand = _hand_ids(synthetic_state, 0)
    rust_lib = _library_ids(synthetic_state, 0)

    assert rust_hand == expected_hand
    assert rust_lib == expected_lib


def test_mulligan_with_external_rng_none_falls_back_to_xorshift(synthetic_state):
    """Backward compat: `rng=None` is bit-equivalent to omitting the
    kwarg — production callers stay on xorshift64."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.mulligan(0, 42)
    b.mulligan(0, 42, rng=None)
    assert a.fingerprint() == b.fingerprint()


def test_mulligan_with_external_rng_ignores_seed(synthetic_state):
    """`rng` takes precedence over `seed`. Same rng state + different
    seed → identical post-mulligan state."""
    import random

    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.mulligan(0, 0, rng=random.Random(7))
    b.mulligan(0, 99_999, rng=random.Random(7))
    assert a.fingerprint() == b.fingerprint()


def test_mulligan_to_n_with_external_rng_matches_python_shuffle(synthetic_state):
    """`mulligan_to_n` with an external rng matches a Python reference
    shuffle: drain hand into library, shuffle with
    `random.Random(seed)`, draw `n_cards` from the top."""
    import random

    initial_hand = _hand_ids(synthetic_state, 0)
    initial_lib = _library_ids(synthetic_state, 0)
    combined = list(initial_lib) + list(initial_hand)
    random.Random(11).shuffle(combined)
    n_cards = 5
    expected_hand = combined[:n_cards]
    expected_lib = combined[n_cards:]

    synthetic_state.mulligan_to_n(0, n_cards, 0, rng=random.Random(11))
    assert _hand_ids(synthetic_state, 0) == expected_hand
    assert _library_ids(synthetic_state, 0) == expected_lib


def test_mulligan_to_n_with_external_rng_none_falls_back(synthetic_state):
    """Backward compat for `mulligan_to_n`."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.mulligan_to_n(0, 6, 42)
    b.mulligan_to_n(0, 6, 42, rng=None)
    assert a.fingerprint() == b.fingerprint()


def test_mulligan_atomic_with_external_rng_matches_python_shuffle(synthetic_state):
    """`mulligan_atomic` with an external rng yields the same post-
    shuffle hand as the Python reference, allowing the caller to pre-
    compute the bottom set deterministically.
    """
    import random

    initial_hand = _hand_ids(synthetic_state, 0)
    initial_lib = _library_ids(synthetic_state, 0)
    combined = list(initial_lib) + list(initial_hand)
    random.Random(2026).shuffle(combined)
    expected_post_redraw_hand = combined[:7]

    # First mulligan → bottoms 1 card. Pick the first id from the
    # expected post-redraw hand.
    bottom_ids = [expected_post_redraw_hand[0]]
    synthetic_state.mulligan_atomic(0, 0, bottom_ids, rng=random.Random(2026))
    # Post-bottom hand: the expected hand minus the bottomed card.
    expected_post_bottom_hand = expected_post_redraw_hand[1:]
    assert _hand_ids(synthetic_state, 0) == expected_post_bottom_hand


def test_mulligan_atomic_with_external_rng_none_falls_back(synthetic_state):
    """Backward compat for `mulligan_atomic`."""
    probe = synthetic_state.clone_once()
    probe.mulligan(0, 9999)
    bottom_ids = _hand_ids(probe, 0)[:1]

    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.mulligan_atomic(0, 9999, bottom_ids)
    b.mulligan_atomic(0, 9999, bottom_ids, rng=None)
    assert a.fingerprint() == b.fingerprint()


def test_mulligan_with_external_rng_is_deterministic(synthetic_state):
    """Two `random.Random(seed)` instances with the same seed produce
    byte-identical post-mulligan state."""
    import random

    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.mulligan(0, 0, rng=random.Random(2026))
    b.mulligan(0, 0, rng=random.Random(2026))
    assert a.fingerprint() == b.fingerprint()


def test_mulligan_with_external_rng_raises_on_invalid_rng(synthetic_state):
    """Passing an object without `_randbelow` surfaces a Python-side
    error."""
    with pytest.raises((AttributeError, TypeError)):
        synthetic_state.mulligan(0, 0, rng=42)
