"""Library / discard / scry primitives on ``GameState``.

Ported from the library-mutation patterns in ``src/mtg_bot/game.py``
(``shuffle_library``) and the discard pattern in
``src/mtg_bot/actions.py`` (ward-discard: ``p.hand.remove(card);
card.zone = Zone.GRAVEYARD; p.graveyard.append(card)``). On the Python
side these are open-coded at each call site; the Rust port collapses
them into single primitives that own membership + zone-tag semantics.

**RNG choice (inline xorshift64):** to avoid a Cargo.toml race with
sibling slices, the shuffle uses a tiny inline xorshift64 generator
rather than pulling in the ``rand`` crate. Determinism guarantee:
``shuffle_library_with_seed(player_id, seed)`` is a pure function of
``(library, seed)`` — same library + same seed produces the same
permutation, byte for byte.

**"Top of library" convention** (inherited from
``state_ops_zones.rs``): the LAST element of the library ``Vec`` is
the top of the library. ``scry`` therefore reads the tail and returns
ids in top-first order (last element first).
"""

from __future__ import annotations

import pytest


# `make_synthetic_state(num_battlefield=10, num_hand=7, num_library=50)`
# lays player 0 out as:
#   battlefield: ids 0..9
#   hand:        ids 10..16
#   library:     ids 17..66
# Player 1's range starts at 67.
P0_FIRST_BATTLEFIELD_ID = 0
P0_FIRST_HAND_ID = 10
P0_FIRST_LIBRARY_ID = 17
P0_LIBRARY_SIZE = 50


# --- Discard ----------------------------------------------------------------


def test_discard_moves_card_to_graveyard(synthetic_state):
    """Discarding a card from hand removes it from hand and pushes it
    onto the graveyard. The object's identity is preserved (registry
    name still resolves)."""
    obj_id = P0_FIRST_HAND_ID  # an elf
    hand_before = synthetic_state.hand_sizes
    gy_before = synthetic_state.graveyard_sizes
    name_before = synthetic_state.printing_name_of(obj_id)
    assert name_before == "Llanowar Elves"

    discarded = synthetic_state.discard(obj_id, 0)

    assert discarded is True
    assert synthetic_state.hand_sizes[0] == hand_before[0] - 1
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 1
    # Other player untouched.
    assert synthetic_state.hand_sizes[1] == hand_before[1]
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]
    # Same id, same printing — found in the graveyard now.
    assert synthetic_state.printing_name_of(obj_id) == "Llanowar Elves"


def test_discard_unknown_id_returns_false(synthetic_state):
    """Far-out-of-range id returns False (no exception, no zone
    mutation)."""
    hand_before = synthetic_state.hand_sizes
    gy_before = synthetic_state.graveyard_sizes
    assert synthetic_state.discard(999_999, 0) is False
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_discard_card_not_in_hand_returns_false(synthetic_state):
    """Trying to discard a battlefield object: precondition fails,
    return False, no zone mutation."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    bf_before = synthetic_state.battlefield_sizes
    hand_before = synthetic_state.hand_sizes
    gy_before = synthetic_state.graveyard_sizes

    assert synthetic_state.discard(obj_id, 0) is False

    # Object stayed on the battlefield.
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_discard_clone_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary: discarding on a clone must not leak
    back into the source state."""
    obj_id = P0_FIRST_HAND_ID
    cloned = synthetic_state.clone_once()
    hand_source_before = synthetic_state.hand_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    assert cloned.discard(obj_id, 0) is True

    # Clone diverged.
    assert cloned.hand_sizes[0] == hand_source_before[0] - 1
    assert cloned.graveyard_sizes[0] == gy_source_before[0] + 1
    # Source untouched.
    assert synthetic_state.hand_sizes == hand_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before


# --- Shuffle ---------------------------------------------------------------


def _library_obj_ids(state, player_id, scry_n):
    """Snapshot the player's library obj_ids by scrying the whole
    thing (top-first). The library size is at most P0_LIBRARY_SIZE
    here, so scry(player, P0_LIBRARY_SIZE) returns the entire library
    in top-first order without mutating it."""
    return state.scry(player_id, scry_n)


def test_shuffle_with_seed_is_deterministic(synthetic_state):
    """Same source state cloned twice + shuffled with the same seed
    produces identical library orders. Pure function of (library,
    seed)."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.shuffle_library_with_seed(0, 42)
    b.shuffle_library_with_seed(0, 42)

    a_order = _library_obj_ids(a, 0, P0_LIBRARY_SIZE)
    b_order = _library_obj_ids(b, 0, P0_LIBRARY_SIZE)

    assert a_order == b_order
    assert len(a_order) == P0_LIBRARY_SIZE


def test_shuffle_with_different_seeds_likely_different(synthetic_state):
    """Different seeds produce different orders. Probabilistic, but
    for a 50-card library two random shuffles colliding is ~1/50!,
    i.e. effectively never."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.shuffle_library_with_seed(0, 42)
    b.shuffle_library_with_seed(0, 99)

    a_order = _library_obj_ids(a, 0, P0_LIBRARY_SIZE)
    b_order = _library_obj_ids(b, 0, P0_LIBRARY_SIZE)

    assert a_order != b_order


def test_shuffle_preserves_card_set(synthetic_state):
    """Shuffle is a permutation: same set of obj_ids before and after,
    no duplicates, no losses."""
    before = sorted(_library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE))
    synthetic_state.shuffle_library_with_seed(0, 12345)
    after = sorted(_library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE))
    assert before == after
    assert len(set(after)) == P0_LIBRARY_SIZE


def test_shuffle_clone_does_not_affect_original(synthetic_state):
    """Shuffling a clone's library must not leak back into the
    source. CoW canary."""
    cloned = synthetic_state.clone_once()
    source_before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)

    cloned.shuffle_library_with_seed(0, 7)
    cloned_after = _library_obj_ids(cloned, 0, P0_LIBRARY_SIZE)

    # Source still in original order.
    source_after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert source_after == source_before
    # Clone actually got shuffled (it shouldn't match the source for
    # a 50-card library with any non-degenerate seed).
    assert cloned_after != source_before


# --- Scry ------------------------------------------------------------------


def test_scry_top_n_returns_n_obj_ids_in_top_order(synthetic_state):
    """``scry(0, 3)`` returns the top 3 obj_ids of player 0's library
    in top-first order. Post-CE3: top of library = FIRST element of
    the Vec, so the returned list reads the head forward."""
    top3 = synthetic_state.scry(0, 3)
    assert len(top3) == 3
    # Library was built as ids 17..66 in push order. Post-CE3
    # lib[0] = top = id 17. Top-first iteration yields 17, 18, 19.
    assert top3 == [17, 18, 19]


def test_scry_more_than_library_size_returns_what_exists(synthetic_state):
    """Scry N where N > library size: clamp to library size, return
    everything that exists (top-first)."""
    all_ids = synthetic_state.scry(0, 100)
    assert len(all_ids) == P0_LIBRARY_SIZE


def test_scry_zero_returns_empty(synthetic_state):
    assert synthetic_state.scry(0, 0) == []


def test_scry_does_not_mutate_library(synthetic_state):
    """Scry is a peek — library size is unchanged after the call."""
    lib_before = synthetic_state.library_sizes
    _ = synthetic_state.scry(0, 5)
    assert synthetic_state.library_sizes == lib_before


def test_apply_scry_keep_on_top_preserves_order(synthetic_state):
    """Scry the top 3, put all 3 back on top in the same order:
    library is unchanged."""
    before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    top3 = synthetic_state.scry(0, 3)

    ok = synthetic_state.apply_scry(0, top3, [])
    assert ok is True

    after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert after == before
    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE


def test_apply_scry_send_some_to_bottom_reorders_library(synthetic_state):
    """Post-CE3 orientation: scry top 3 (ids 17, 18, 19), keep 17 +
    18 on top, send 19 to the bottom. Library size unchanged; new
    top-first reads 17, 18, then-the-old-fourth-card (id 20); the
    bottom card (formerly id 66) is now still 66 with id 19 just
    below — actually the bottom slot (lib[len-1]) becomes id 19 by
    the apply_scry contract (bottom_ids[0] = very bottom)."""
    top3 = synthetic_state.scry(0, 3)
    assert top3 == [17, 18, 19]

    ok = synthetic_state.apply_scry(0, [17, 18], [19])
    assert ok is True

    assert synthetic_state.library_sizes[0] == P0_LIBRARY_SIZE
    new_top3 = synthetic_state.scry(0, 3)
    assert new_top3 == [17, 18, 20]

    # Old bottom card (id 66) is now second-from-bottom; new very
    # bottom is id 19 (the bottom_ids[0] contract). Read whole library
    # and check the very bottom (= last element of the Vec, = LAST
    # element of a top-first scry).
    all_ids = synthetic_state.scry(0, P0_LIBRARY_SIZE)
    assert all_ids[-1] == 19
    assert all_ids[-2] == 66


def test_apply_scry_validation_failure_returns_false(synthetic_state):
    """If the union of top_ids + bottom_ids does not match the top N
    we peeked at, validation fails and the library is unchanged."""
    before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    # Pretend we scryed 2, but pass an id that isn't in the top 2.
    ok = synthetic_state.apply_scry(0, [17, 999_999], [])
    assert ok is False
    after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert after == before


# --- Search library --------------------------------------------------------

# In synthetic_state, the library is built entirely of Forests (pid 0)
# at ids 17..66 for player 0. So a search for FOREST_PID must hit, and
# a search for an unknown printing_id must miss.
FOREST_PID = 0
ZONE_HAND = 0


def test_search_library_for_first_with_printing_returns_match(synthetic_state):
    """Synthetic state seeds Forest in library; search returns the
    obj_id of the FIRST GameObject in the library Vec matching the
    printing_id. The library Vec was filled push-order (ids 17..66),
    so lib[0] = id 17 = the first match."""
    found = synthetic_state.search_library_for_first_with_printing(0, FOREST_PID)
    assert found == P0_FIRST_LIBRARY_ID  # 17


def test_search_library_for_first_with_printing_returns_none_when_not_found(
    synthetic_state,
):
    """Search for a printing_id that isn't in the library returns
    None (no exception, no mutation)."""
    found = synthetic_state.search_library_for_first_with_printing(0, 99)
    assert found is None


def test_search_library_for_first_does_not_move_or_reorder(synthetic_state):
    """Search is a pure read — library order and size unchanged after
    the call."""
    before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    size_before = synthetic_state.library_sizes
    hand_before = synthetic_state.hand_sizes

    _ = synthetic_state.search_library_for_first_with_printing(0, FOREST_PID)

    after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert after == before
    assert synthetic_state.library_sizes == size_before
    assert synthetic_state.hand_sizes == hand_before


def test_search_library_and_move_to_hand_moves_card(synthetic_state):
    """Search + move: hand grows by 1, library shrinks by 1."""
    hand_before = synthetic_state.hand_sizes
    lib_before = synthetic_state.library_sizes

    found = synthetic_state.search_library_and_move_to_hand(0, FOREST_PID, 42)

    assert found is not None
    assert synthetic_state.hand_sizes[0] == hand_before[0] + 1
    assert synthetic_state.library_sizes[0] == lib_before[0] - 1
    # Other player untouched.
    assert synthetic_state.hand_sizes[1] == hand_before[1]
    assert synthetic_state.library_sizes[1] == lib_before[1]


def test_search_library_and_move_to_hand_zone_field_updated(synthetic_state):
    """Moved card's zone field is set to ZONE_HAND, and the card lives
    in hand now (find_object_zone reports ZONE_HAND)."""
    found = synthetic_state.search_library_and_move_to_hand(0, FOREST_PID, 42)
    assert found is not None
    assert synthetic_state.find_object_zone(found) == ZONE_HAND


def test_search_library_and_move_to_hand_failed_search_still_shuffles(
    synthetic_state,
):
    """Real MTG: even a failed search reveals to opponents and shuffles
    the library. Two clones, search for missing pid with different
    seeds, libraries should differ."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    hand_before = synthetic_state.hand_sizes

    found_a = a.search_library_and_move_to_hand(0, 99, 1)
    found_b = b.search_library_and_move_to_hand(0, 99, 99)

    assert found_a is None
    assert found_b is None
    # Hand sizes unchanged on both — nothing moved.
    assert a.hand_sizes == hand_before
    assert b.hand_sizes == hand_before
    # Library sizes unchanged on both — nothing moved.
    assert a.library_sizes == synthetic_state.library_sizes
    assert b.library_sizes == synthetic_state.library_sizes
    # But the libraries WERE shuffled — different seeds produce
    # different orders.
    a_order = _library_obj_ids(a, 0, P0_LIBRARY_SIZE)
    b_order = _library_obj_ids(b, 0, P0_LIBRARY_SIZE)
    assert a_order != b_order


def test_search_library_and_move_to_hand_returns_none_on_miss(synthetic_state):
    """Missing printing_id returns None (and shuffles, per the rule
    above — but the return value is None)."""
    found = synthetic_state.search_library_and_move_to_hand(0, 99, 7)
    assert found is None


def test_clone_then_search_does_not_affect_original(synthetic_state):
    """CoW canary: search+move on a clone must not leak back into the
    source. Both library order AND hand membership are checked."""
    cloned = synthetic_state.clone_once()
    source_lib_before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    source_hand_before = synthetic_state.hand_sizes
    source_lib_size_before = synthetic_state.library_sizes

    found = cloned.search_library_and_move_to_hand(0, FOREST_PID, 42)
    assert found is not None

    # Source untouched.
    assert synthetic_state.hand_sizes == source_hand_before
    assert synthetic_state.library_sizes == source_lib_size_before
    source_lib_after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert source_lib_after == source_lib_before


# --- Search library by type (round-15) -------------------------------------

# Synthetic registry pids:
#   pid 0 = Forest         (card_types = ["Land"])
#   pid 1 = Grizzly Bears  (card_types = ["Creature"])
#   pid 2 = Llanowar Elves (card_types = ["Creature"])
BEARS_PID = 1
ELVES_PID = 2


def test_search_library_by_type_finds_creature(synthetic_state):
    """Library laid out (top -> bottom, post-CE3) as [Forest, Forest,
    Bears, Forest]: top-to-bottom search for "Creature" returns the
    Bears' obj_id (the Forests at the top are skipped, Bears is next
    down)."""
    synthetic_state.load_deck(0, [FOREST_PID, FOREST_PID, BEARS_PID, FOREST_PID])
    # Post-CE3: top-of-library = the FIRST input = Forest; lib[2] =
    # Bears. Top-to-bottom iteration skips the two Forests and
    # returns Bears' obj_id.
    top_first_ids = synthetic_state.scry(0, 4)
    bears_id = top_first_ids[2]  # third from top
    assert synthetic_state.printing_name_of(bears_id) == "Grizzly Bears"

    found = synthetic_state.search_library_for_first_of_type(0, "Creature")
    assert found == bears_id


def test_search_library_by_type_finds_land(synthetic_state):
    """Default synthetic state has 50 Forests in the library. A
    top-to-bottom search for "Land" returns the obj_id of the TOP of
    the library (id 17 — the FIRST element of the Vec post-CE3)."""
    found = synthetic_state.search_library_for_first_of_type(0, "Land")
    # Top of library = lib[0] post-CE3; synthetic seeded ids 17..66
    # so id 17 is the top.
    assert found == 17


def test_search_library_by_type_unknown_type_returns_none(synthetic_state):
    """Searching for a type string with no matching card in the library
    returns None (no exception, no mutation). Default library is all
    Forests, so "Planeswalker" finds nothing."""
    found = synthetic_state.search_library_for_first_of_type(0, "Planeswalker")
    assert found is None


def test_search_library_by_type_empty_library_returns_none(synthetic_state):
    """Empty library + any search type returns None."""
    synthetic_state.load_deck(0, [])
    assert synthetic_state.library_sizes[0] == 0
    found = synthetic_state.search_library_for_first_of_type(0, "Land")
    assert found is None


def test_search_library_by_type_unknown_player_raises(synthetic_state):
    """An out-of-range player_id raises ValueError rather than silently
    returning None."""
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.search_library_for_first_of_type(7, "Creature")


def test_search_library_by_type_does_not_mutate_library(synthetic_state):
    """Search alone is a pure read — library order and size unchanged
    after the call."""
    before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    size_before = synthetic_state.library_sizes
    hand_before = synthetic_state.hand_sizes

    _ = synthetic_state.search_library_for_first_of_type(0, "Land")

    after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert after == before
    assert synthetic_state.library_sizes == size_before
    assert synthetic_state.hand_sizes == hand_before


def test_search_and_move_to_hand_moves_card(synthetic_state):
    """Composition: search creature + move to hand. Library shrinks by
    1, hand grows by 1, moved card has zone = ZONE_HAND."""
    synthetic_state.load_deck(0, [FOREST_PID, FOREST_PID, BEARS_PID, FOREST_PID])
    hand_before = synthetic_state.hand_sizes
    lib_before = synthetic_state.library_sizes

    found = synthetic_state.search_library_for_first_of_type_and_move_to_hand(
        0, "Creature"
    )

    assert found is not None
    assert synthetic_state.printing_name_of(found) == "Grizzly Bears"
    assert synthetic_state.hand_sizes[0] == hand_before[0] + 1
    assert synthetic_state.library_sizes[0] == lib_before[0] - 1
    # Moved card now lives in hand.
    assert synthetic_state.find_object_zone(found) == ZONE_HAND
    # Other player untouched.
    assert synthetic_state.hand_sizes[1] == hand_before[1]
    assert synthetic_state.library_sizes[1] == lib_before[1]


def test_search_and_move_to_hand_no_match_returns_none_no_mutation(synthetic_state):
    """No match: returns None, library unchanged, hand unchanged.
    Unlike round-14's printing-search variant (which shuffles on miss),
    this composition is a pure no-op when nothing matches — the
    library/hand sizes and ordering are bit-for-bit identical."""
    lib_before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    hand_before = synthetic_state.hand_sizes
    lib_size_before = synthetic_state.library_sizes

    found = synthetic_state.search_library_for_first_of_type_and_move_to_hand(
        0, "Planeswalker"
    )

    assert found is None
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.library_sizes == lib_size_before
    lib_after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert lib_after == lib_before


# --- Search library by type + ALWAYS shuffle (round-16, CR 701.19) --------

# Per CR 701.19, a tutor-style "search library, then shuffle" effect
# ALWAYS shuffles afterward — whether or not a card was found. This is
# distinct from round-15's `search_library_for_first_of_type_and_move_to_hand`
# (no shuffle) and from round-14's printing-id variant
# `search_library_and_move_to_hand` (shuffles unconditionally too).


def test_search_and_shuffle_finds_creature_and_shuffles(synthetic_state):
    """Library with a creature: search + always-shuffle returns the
    moved card's obj_id, library size shrinks by 1, and the library
    order is changed by the post-search shuffle. Default synthetic
    library is 50 Forests; we load a mixed deck so there's a creature
    to find AND enough cards to make the shuffle observable."""
    # 50 cards: 49 Forests + 1 Bears so after removal there are still
    # 49 cards (>= 2) for Fisher-Yates to do something meaningful.
    deck = [FOREST_PID] * 49 + [BEARS_PID]
    synthetic_state.load_deck(0, deck)
    lib_before = _library_obj_ids(synthetic_state, 0, len(deck))
    hand_before = synthetic_state.hand_sizes
    lib_size_before = synthetic_state.library_sizes

    found = synthetic_state.search_library_for_first_of_type_and_shuffle(
        0, "Creature", 42
    )

    assert found is not None
    assert synthetic_state.printing_name_of(found) == "Grizzly Bears"
    # Library shrank by 1, hand grew by 1.
    assert synthetic_state.library_sizes[0] == lib_size_before[0] - 1
    assert synthetic_state.hand_sizes[0] == hand_before[0] + 1
    # The library was shuffled — its top-first order is no longer the
    # original lib_before minus the moved card. (With 49 cards left
    # after removal, the chance of a non-trivial Fisher-Yates landing
    # on the identity permutation is ~1/49!.)
    lib_after = _library_obj_ids(synthetic_state, 0, len(deck) - 1)
    # The set of remaining ids is (lib_before's ids) - {found}.
    expected_remaining = [i for i in lib_before if i != found]
    assert sorted(lib_after) == sorted(expected_remaining)
    assert lib_after != expected_remaining


def test_search_and_shuffle_no_match_still_shuffles(synthetic_state):
    """No match: returns None, library size UNCHANGED, but the library
    is STILL shuffled (CR 701.19). Default synthetic library is 50
    Forests, so "Planeswalker" finds nothing."""
    lib_before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    hand_before = synthetic_state.hand_sizes
    lib_size_before = synthetic_state.library_sizes

    found = synthetic_state.search_library_for_first_of_type_and_shuffle(
        0, "Planeswalker", 42
    )

    assert found is None
    # Hand and library SIZES unchanged.
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.library_sizes == lib_size_before
    # But library ORDER changed — the shuffle ran even on a miss.
    lib_after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert sorted(lib_after) == sorted(lib_before)
    assert lib_after != lib_before


def test_search_and_shuffle_empty_library_returns_none(synthetic_state):
    """Empty library: returns None, no error, no mutation. Shuffle on
    a size-0 library is a no-op."""
    synthetic_state.load_deck(0, [])
    assert synthetic_state.library_sizes[0] == 0

    found = synthetic_state.search_library_for_first_of_type_and_shuffle(
        0, "Creature", 42
    )

    assert found is None
    assert synthetic_state.library_sizes[0] == 0


def test_search_and_shuffle_unknown_player_raises(synthetic_state):
    """Out-of-range player_id raises (matches the search-only
    sibling's loud-failure convention)."""
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.search_library_for_first_of_type_and_shuffle(
            7, "Creature", 42
        )


def test_search_and_shuffle_deterministic_with_same_seed(synthetic_state):
    """Same source state cloned twice + same seed produces identical
    results: same moved card AND identical resulting library order."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    found_a = a.search_library_for_first_of_type_and_shuffle(0, "Land", 42)
    found_b = b.search_library_for_first_of_type_and_shuffle(0, "Land", 42)

    assert found_a == found_b
    a_order = _library_obj_ids(a, 0, P0_LIBRARY_SIZE - 1)
    b_order = _library_obj_ids(b, 0, P0_LIBRARY_SIZE - 1)
    assert a_order == b_order


def test_search_and_shuffle_different_seed_different_order(synthetic_state):
    """Different seeds applied to identical clones produce different
    library orders. With a 50-card library, false equality is ~1/50!,
    effectively never."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.search_library_for_first_of_type_and_shuffle(0, "Land", 1)
    b.search_library_for_first_of_type_and_shuffle(0, "Land", 99)

    a_order = _library_obj_ids(a, 0, P0_LIBRARY_SIZE - 1)
    b_order = _library_obj_ids(b, 0, P0_LIBRARY_SIZE - 1)
    assert a_order != b_order


def test_search_and_shuffle_clone_isolation(synthetic_state):
    """CoW canary: search+shuffle on a clone must not leak back into
    the source. Both library order AND hand membership are checked."""
    cloned = synthetic_state.clone_once()
    source_lib_before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    source_hand_before = synthetic_state.hand_sizes
    source_lib_size_before = synthetic_state.library_sizes

    found = cloned.search_library_for_first_of_type_and_shuffle(
        0, "Land", 42
    )
    assert found is not None

    # Source untouched.
    assert synthetic_state.hand_sizes == source_hand_before
    assert synthetic_state.library_sizes == source_lib_size_before
    source_lib_after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert source_lib_after == source_lib_before


# --- Mill target player (round-19, complement to Effect::Mill) -------------

# Round-1's `Effect::Mill` always mills the resolving spell's controller
# (= active_player). This primitive is the "specify which player gets
# milled" form for effects like Glimpse the Unthinkable / Mind Funeral
# whose target is "target player puts the top N of their library into
# their graveyard". Top-of-library = LAST element of the Vec, so milling
# moves cards from the tail.
ZONE_GRAVEYARD = 3


def test_mill_target_player_basic_returns_actual_milled(synthetic_state):
    """Player has 5 cards in library, mill 3: returns 3, library shrinks
    to 2, graveyard grows by 3."""
    synthetic_state.load_deck(0, [FOREST_PID] * 5)
    assert synthetic_state.library_sizes[0] == 5
    gy_before = synthetic_state.graveyard_sizes[0]

    milled = synthetic_state.mill_target_player(0, 3)

    assert milled == 3
    assert synthetic_state.library_sizes[0] == 2
    assert synthetic_state.graveyard_sizes[0] == gy_before + 3


def test_mill_target_player_zero_count_is_noop(synthetic_state):
    """count = 0 is a legal no-op: returns 0, no library / graveyard
    mutation."""
    lib_before = synthetic_state.library_sizes
    gy_before = synthetic_state.graveyard_sizes

    milled = synthetic_state.mill_target_player(0, 0)

    assert milled == 0
    assert synthetic_state.library_sizes == lib_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_mill_target_player_count_exceeds_library_size(synthetic_state):
    """Mill more than the library has: returns library size, library
    empties, graveyard receives all the cards. Real MTG: milling an
    empty library is NOT a loss — the loss state-based action only
    fires on a *draw* attempt against an empty library."""
    synthetic_state.load_deck(0, [FOREST_PID] * 4)
    gy_before = synthetic_state.graveyard_sizes[0]

    milled = synthetic_state.mill_target_player(0, 100)

    assert milled == 4
    assert synthetic_state.library_sizes[0] == 0
    assert synthetic_state.graveyard_sizes[0] == gy_before + 4


def test_mill_target_player_empty_library_returns_zero(synthetic_state):
    """Empty library: returns 0, no mutation. (Same path as count=0
    short-circuit.)"""
    synthetic_state.load_deck(0, [])
    assert synthetic_state.library_sizes[0] == 0
    gy_before = synthetic_state.graveyard_sizes[0]

    milled = synthetic_state.mill_target_player(0, 5)

    assert milled == 0
    assert synthetic_state.library_sizes[0] == 0
    assert synthetic_state.graveyard_sizes[0] == gy_before


def test_mill_target_player_targets_opponent(synthetic_state):
    """Active player is 0 by default; milling player_id=1 mills the
    opponent, not the controller. Opponent's library shrinks; active
    player's library is untouched."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    milled = synthetic_state.mill_target_player(1, 4)

    assert milled == 4
    # Opponent (p1) milled.
    assert synthetic_state.library_sizes[1] == p1_lib_before - 4
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 4
    # Active player (p0) untouched.
    assert synthetic_state.library_sizes[0] == p0_lib_before
    assert synthetic_state.graveyard_sizes[0] == 0


def test_mill_target_player_negative_count_raises(synthetic_state):
    """Negative count is invalid input — raises ValueError per the
    project's loud-fail convention. (Library/graveyard untouched.)"""
    lib_before = synthetic_state.library_sizes
    gy_before = synthetic_state.graveyard_sizes

    with pytest.raises(ValueError):
        synthetic_state.mill_target_player(0, -1)

    assert synthetic_state.library_sizes == lib_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_mill_target_player_unknown_player_raises(synthetic_state):
    """Out-of-range player_id raises IndexError, mirroring how
    `move_object_from_graveyard_to_battlefield` and the other round-1
    player-indexed primitives validate."""
    with pytest.raises((IndexError, OverflowError)):
        synthetic_state.mill_target_player(7, 1)


def test_mill_target_player_resets_state_on_milled_cards(synthetic_state):
    """A milled card lands in the graveyard with its per-object state
    reset (CR 400.7): tapped, summoning_sick, damage, counters all
    zeroed. The synthetic library cards default to clean state, so
    we stamp counters onto the top-of-library card via `set_counters`
    (which works cross-zone) and assert the milled card has counters
    == 0 on arrival in the graveyard. Also asserts the milled card's
    `find_object_zone` reports ZONE_GRAVEYARD."""
    # Top of library is the FIRST element of the Vec post-CE3 (=
    # smallest id). Default synthetic_state.library has ids 17..66
    # for player 0; top = 17.
    top_id = 17
    # Stamp counters on the top library card.
    assert synthetic_state.set_counters(top_id, 5) is True
    assert synthetic_state.get_counters(top_id) == 5

    milled = synthetic_state.mill_target_player(0, 1)

    assert milled == 1
    # Card is now in graveyard.
    assert synthetic_state.find_object_zone(top_id) == ZONE_GRAVEYARD
    # Counters reset to zero.
    assert synthetic_state.get_counters(top_id) == 0


def test_mill_target_player_clone_does_not_affect_original(synthetic_state):
    """CoW canary: milling on a clone must not leak back into the source.
    Both library size AND graveyard size are checked on the source."""
    cloned = synthetic_state.clone_once()
    source_lib_before = synthetic_state.library_sizes
    source_gy_before = synthetic_state.graveyard_sizes

    milled = cloned.mill_target_player(0, 3)
    assert milled == 3

    # Clone diverged.
    assert cloned.library_sizes[0] == source_lib_before[0] - 3
    assert cloned.graveyard_sizes[0] == source_gy_before[0] + 3
    # Source untouched.
    assert synthetic_state.library_sizes == source_lib_before
    assert synthetic_state.graveyard_sizes == source_gy_before


# --- Cross-feature edge-case coverage --------------------------------------
#
# These tests exercise the library / draw / mill / surveil / search
# primitives together with sibling subsystems: Effect-dispatch via
# resolve_top_of_stack, zone tagging via find_object_zone, fingerprinting,
# state-based actions (apply_sbas), and CoW (clone_once). They probe the
# documented current behavior of the engine — including the deliberate
# divergences from real MTG that are tracked in
# ``docs/SEARCH_LIMITATIONS.md`` (the round-23 SearchLibraryForBasicLand
# no-shuffle gap; DrawCards-on-empty-library as a silent short-circuit
# instead of a CR 704.5b deck-out loss).
#
# **Effect-dispatch shape (mirroring ``test_resolve.py``):**
#   - Build a printing dict whose ``effects`` list carries the kind under
#     test, register+inject it as a hand object, push it on the stack,
#     and call ``resolve_top_of_stack``.
#   - Inspect zone sizes, ``find_object_zone(obj_id)``, ``is_tapped``,
#     etc. for the cross-feature assertion.
#
# These tests do NOT touch Rust source — they assert the dispatch shape
# the round-1..round-23 slices already implement.

ZONE_BATTLEFIELD = 2


def _draw_two_dict():
    """Concentrate-shaped sorcery — draw 2 cards on resolve."""
    return {
        "name": "Test Draw 2 (lib edge)",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1, "generic": 1},
        "effects": [{"kind": "draw_cards", "count": 2}],
    }


def _draw_huge_dict():
    """A draw-100 sorcery — exercises empty-library short-circuit when
    the library has fewer than 100 cards."""
    return {
        "name": "Test Draw 100 (lib edge)",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 5, "generic": 5},
        "effects": [{"kind": "draw_cards", "count": 100}],
    }


def _mill_two_dict():
    """A mill-2 sorcery — Effect::Mill (controller mills self)."""
    return {
        "name": "Test Mill 2 (lib edge)",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "mill", "count": 2}],
    }


def _mill_target_player_two_dict():
    """A mill-target-player-2 sorcery — Effect::MillTargetPlayer; per
    the round-19 spec, deterministic target is the defender."""
    return {
        "name": "Test MillTargetPlayer 2 (lib edge)",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1, "generic": 1},
        "effects": [{"kind": "mill_target_player", "count": 2}],
    }


def _surveil_one_dict():
    """A Surveil-1 sorcery — first-slice deterministic keep-on-top, no
    library mutation from the dispatch (round-23 scope)."""
    return {
        "name": "Test Surveil 1 (lib edge)",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "surveil", "count": 1}],
    }


def _basic_land_tapped_dict():
    """Rampant-Growth-shaped sorcery — search a basic land, put it onto
    the battlefield TAPPED (round-23 SearchLibraryForBasicLandTapped)."""
    return {
        "name": "Test BasicLandTapped (lib edge)",
        "card_types": ["Sorcery"],
        "effects": [
            {"kind": "search_library_for_basic_land_tapped", "count": 1}
        ],
    }


def test_effect_drawcards_moves_top_of_library_to_hand(synthetic_state):
    """Cross-feature: ``Effect::DrawCards`` dispatch moves the actual
    top-of-library obj_id from the library Vec onto the controller's
    hand Vec. Post-CE3: top = FIRST element of the library Vec
    (Python pop(0) convention). After resolution, the formerly-top
    library card has ``find_object_zone == ZONE_HAND``.

    The synthetic seed lays p0's library as ids 17..66 push-order, so
    the top of library is id 17, second-from-top is id 18."""
    top_id = 17
    second_id = 18
    assert synthetic_state.find_object_zone(top_id) != ZONE_HAND

    obj_id = synthetic_state.register_and_inject_object(
        _draw_two_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Both formerly-top library cards now live in hand.
    assert synthetic_state.find_object_zone(top_id) == ZONE_HAND
    assert synthetic_state.find_object_zone(second_id) == ZONE_HAND


def test_effect_mill_moves_top_of_library_to_graveyard(synthetic_state):
    """Cross-feature: ``Effect::Mill`` dispatch moves the top-of-library
    obj_id to the CONTROLLER's graveyard. Post-CE3 zones convention:
    top of library = FIRST element of the library Vec. After
    resolution, the formerly-top card has ``find_object_zone ==
    ZONE_GRAVEYARD``."""
    top_id = 17
    second_id = 18
    assert synthetic_state.find_object_zone(top_id) != ZONE_GRAVEYARD

    obj_id = synthetic_state.register_and_inject_object(
        _mill_two_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Both formerly-top library cards now live in the controller's
    # graveyard. The source sorcery also lands there via CR 608.2m.
    assert synthetic_state.find_object_zone(top_id) == ZONE_GRAVEYARD
    assert synthetic_state.find_object_zone(second_id) == ZONE_GRAVEYARD


def test_effect_mill_target_player_mills_target_not_source(synthetic_state):
    """Cross-feature: ``Effect::MillTargetPlayer`` mills the DEFENDER's
    library (deterministic target = 1 - active_player per round-19),
    NOT the source's controller. Load-bearing distinction from
    ``Effect::Mill`` (which would hit the controller).

    p0 casts the spell; p1 is the defender, so p1's library shrinks by
    2 and p0's library is untouched."""
    p0_lib_before = synthetic_state.library_sizes[0]
    p1_lib_before = synthetic_state.library_sizes[1]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    obj_id = synthetic_state.register_and_inject_object(
        _mill_target_player_two_dict(), 0, ZONE_HAND  # controller p0
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p1 (target / defender) milled.
    assert synthetic_state.library_sizes[1] == p1_lib_before - 2
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 2
    # p0 (controller / source) library untouched. p0's graveyard gained
    # only the source sorcery (CR 608.2m post-resolve), not the milled
    # cards.
    assert synthetic_state.library_sizes[0] == p0_lib_before


def test_effect_surveil_first_slice_keeps_library_and_top_id_unchanged(
    synthetic_state,
):
    """Cross-feature: round-23 Surveil baseline is "keep all on top".
    Surveil 1 does NOT move the top-of-library card anywhere — library
    size and the identity of the top card both stay put. After the
    round-27 G20 closure (decision-callback substrate landed) this
    baseline now flows through `resolve_top_of_stack`'s auto-resolve
    path with strategy ``"keep_all_on_top"``: the Surveil arm pops
    cards into a `PendingDecision::SurveilChoice`, then the auto-
    resolve at the tail of `resolve_top_of_stack` returns them to
    library top in the original order. The library + graveyard
    observation surface is bit-equal to the pre-r27 path. Real
    surveil-to-graveyard now uses the new `submit_surveil_decision`
    dispatcher — see `tests_rust/test_pending_decisions.py`."""
    top_id = 17  # post-CE3: top = lib[0]
    lib_before = synthetic_state.library_sizes[0]
    gy_before = synthetic_state.graveyard_sizes[0]

    obj_id = synthetic_state.register_and_inject_object(
        _surveil_one_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Library size unchanged — keep-all-on-top is mechanically a no-op
    # on the library. Top-of-library id is also unchanged (the round-22
    # scry returns top-first, so [0] is still the same obj_id).
    assert synthetic_state.library_sizes[0] == lib_before
    assert synthetic_state.find_object_zone(top_id) == 1  # ZONE_LIBRARY
    assert synthetic_state.scry(0, 1) == [top_id]
    # Graveyard gained only the source (sorcery via CR 608.2m), not any
    # surveil-routed card.
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1


def test_effect_search_library_for_basic_land_tapped_enters_tapped(
    synthetic_state,
):
    """Cross-feature: round-23 ``SearchLibraryForBasicLandTapped`` puts
    a basic Forest from the library onto the active player's battlefield
    TAPPED. Probes the zones + tapped intersection.

    The synthetic seed library is 100% Forest (card_types=["Land"]);
    deterministic first-match-from-top picks the top-of-library card
    (id 66). It lands on p0's battlefield with ``is_tapped == True``
    and ``find_object_zone == ZONE_BATTLEFIELD``.

    **Documented no-shuffle gap:** the round-23 first slice does NOT
    shuffle the library after the search (CR 701.19/701.22 would
    require it). Tracked in ``docs/SEARCH_LIMITATIONS.md`` — pending
    RNG-externalization work."""
    top_id = 17  # post-CE3: top = lib[0] = id 17 (first push-order)

    obj_id = synthetic_state.register_and_inject_object(
        _basic_land_tapped_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # The land moved to p0's battlefield, tapped.
    assert synthetic_state.find_object_zone(top_id) == ZONE_BATTLEFIELD
    assert synthetic_state.is_tapped(top_id) is True
    # NOT summoning-sick (CR 302.1 applies to creatures; a land bypasses).
    assert synthetic_state.is_summoning_sick(top_id) is False


def test_drawcards_from_empty_library_marks_player_for_loss_on_next_sba(engine):
    """Round-26 G10 closure: ``Effect::DrawCards`` against an empty
    library now flips the player's ``attempted_draw_on_empty`` cause
    signal AND surfaces them as a loser. CR 704.5b — a player who
    attempted to draw from an empty library loses on the next SBA pass.

    The Rust engine now models the loss eagerly (``losers()`` reads the
    cause-signal directly so the loss is visible BEFORE ``apply_sbas``
    runs, matching Python's eager ``p.has_lost = True`` in
    ``turn.draw_card``), and ``apply_sbas`` transitions the cause-signal
    into the sticky ``has_lost`` flag so the loss is irrevocable."""
    # Tiny library (1 card) so DrawCards-2 over-draws by 1.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    assert state.library_sizes[0] == 1
    life_before = list(state.life_totals)

    obj_id = state.register_and_inject_object(_draw_two_dict(), 0, ZONE_HAND)
    state.push_to_stack(obj_id, 0)
    state.resolve_top_of_stack()

    # Library drained, hand grew by the one available card. No crash.
    assert state.library_sizes[0] == 0
    # The empty-pop flipped the cause-signal — p0 is now a loser per
    # CR 704.5b, observable BEFORE the next SBA pass via the eager API.
    assert list(state.losers()) == [0]
    assert state.winner() == 1  # eager (cause-flag-driven)
    assert state.is_game_over() is True  # eager
    # Post-CE10 (CE-pure-derivation-is_over): the SBA-gated surface
    # (winner_id getter) stays stale until apply_sbas commits the loss.
    assert state.winner_id is None
    # apply_sbas transitions cause-signal -> sticky has_lost; the loss
    # is now permanent. Return count stays 0 (no creatures destroyed —
    # player-loss is a separate SBA category, doesn't bump the count).
    assert state.apply_sbas() == 0
    assert list(state.losers()) == [0]
    # Post-SBA: surface flips to match.
    assert state.winner_id == 1
    # gain_life on the dead player cannot revive them — has_lost is
    # sticky. Life total unchanged either way (deck-out doesn't manifest
    # via life).
    assert list(state.life_totals) == life_before


def test_drawcards_count_larger_than_library_drains_then_loses_on_sba(engine):
    """Round-26 G10 closure: a DrawCards-N resolution where N > library
    size empties the library AND flags the player. Same shape as the
    previous test but with a much larger over-draw delta: the
    ``attempted_draw_on_empty`` cause-signal only flips once (it's a
    bool, not a counter) regardless of how many extra pops short-circuit
    on the empty library."""
    # Library size 3, draw 100 — drains the library and short-circuits
    # the remaining 97 pops.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=3
    )
    assert state.library_sizes[0] == 3
    hand_before = state.hand_sizes[0]

    obj_id = state.register_and_inject_object(
        _draw_huge_dict(), 0, ZONE_BATTLEFIELD
    )
    state.push_to_stack(obj_id, 0)
    state.resolve_top_of_stack()

    # All 3 cards drained from library to hand. No crash, no error.
    assert state.library_sizes[0] == 0
    assert state.hand_sizes[0] == hand_before + 3
    # Empty-library pop flipped the cause-signal — p0 is now a loser
    # via the eager API.
    assert list(state.losers()) == [0]
    assert state.winner() == 1  # eager
    # Post-CE10: SBA-gated surface stays stale.
    assert state.winner_id is None
    # apply_sbas locks in the loss via has_lost; return count stays 0
    # (no creatures destroyed). Idempotent: subsequent passes are no-ops.
    assert state.apply_sbas() == 0
    assert list(state.losers()) == [0]
    # Post-SBA: surface flips to match.
    assert state.winner_id == 1
    assert state.apply_sbas() == 0
    assert list(state.losers()) == [0]


def test_effect_drawcards_clone_does_not_mutate_original_library_or_hand(
    synthetic_state,
):
    """CoW canary on the Effect-dispatch path: resolving DrawCards on a
    clone leaves the source state's library AND hand exactly as before.
    The library order, the library size, AND the hand size on the source
    must all be untouched.

    Cross-feature with the CoW Arc-make-mut invariant — the round-8
    DrawCards arm uses ``Arc::make_mut`` on both ``player.library`` and
    ``player.hand``, so a clone+resolve should clone-on-write both
    zones."""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _draw_two_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_obj_id, 0)
    source_lib_before = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    source_hand_before = synthetic_state.hand_sizes[0]
    source_lib_size_before = synthetic_state.library_sizes[0]

    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Source: untouched on every front (library order + size + hand size).
    source_lib_after = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert source_lib_after == source_lib_before
    assert synthetic_state.library_sizes[0] == source_lib_size_before
    assert synthetic_state.hand_sizes[0] == source_hand_before
    # Clone: library shrank by 2 (the two drawn cards), source sorcery
    # routed to graveyard via CR 608.2m, drew 2 to hand. Net hand delta
    # on clone: -1 (source leaves) + 2 (drawn) = +1.
    assert cloned.library_sizes[0] == source_lib_size_before - 2
    assert cloned.hand_sizes[0] == source_hand_before - 1 + 2


def test_fingerprint_changes_when_library_order_changes(synthetic_state):
    """Cross-feature with round-22 fingerprinting: two clones of the
    same state with the same library *contents* but different *order*
    have DIFFERENT fingerprints. The fingerprint covers the library
    Vec's order (not just its set membership), so a shuffle is
    observable via fingerprint diff alone."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.shuffle_library_with_seed(0, 1)
    b.shuffle_library_with_seed(0, 99)

    # Same contents on both (shuffle is a permutation), but different
    # order — fingerprint differs.
    a_order = _library_obj_ids(a, 0, P0_LIBRARY_SIZE)
    b_order = _library_obj_ids(b, 0, P0_LIBRARY_SIZE)
    assert sorted(a_order) == sorted(b_order)
    assert a_order != b_order
    assert a.fingerprint() != b.fingerprint()


def test_fingerprint_changes_after_mill_target_player_moves_card(
    synthetic_state,
):
    """Cross-feature with round-22 fingerprinting + round-19 mill: a
    mill_target_player call changes the fingerprint because both the
    library and the graveyard contents change. Pins down that the
    fingerprint is sensitive to library->graveyard zone moves."""
    fp_before = synthetic_state.fingerprint()

    milled = synthetic_state.mill_target_player(0, 1)
    assert milled == 1

    fp_after = synthetic_state.fingerprint()
    assert fp_after != fp_before


def test_find_object_zone_post_mill_reports_graveyard(synthetic_state):
    """Cross-feature with zones (round-1 find_object_zone): after a
    mill, the milled card's ``find_object_zone`` reports
    ``ZONE_GRAVEYARD``, NOT ``ZONE_LIBRARY``. Confirms zone-tag and
    Vec-membership are kept in lockstep across the library->graveyard
    move (the obj.zone field is stamped to ZONE_GRAVEYARD on the way
    out per the round-10 mill arm)."""
    top_id = 17  # post-CE3: top = lib[0] = id 17
    assert synthetic_state.find_object_zone(top_id) == 1  # ZONE_LIBRARY

    milled = synthetic_state.mill_target_player(0, 1)
    assert milled == 1

    assert synthetic_state.find_object_zone(top_id) == ZONE_GRAVEYARD


# -------------------- Round-28 SearchLibraryForCard (9 cards) --------------------


ZONE_BATTLEFIELD_LOCAL = 2
ZONE_LIBRARY = 1


def _tutor_dict(filter_name: str = "artifact", max_mv: int = 0, may_fail: bool = True):
    """Spineseeker-Centipede-shape generalized tutor: search library
    for a card matching filter_name, reveal, put in hand."""
    return {
        "name": "Synthetic Tutor",
        "card_types": ["Sorcery"],
        "mana_cost": {"generic": 2},
        "effects": [
            {
                "kind": "search_library_for_card",
                "filter_name": filter_name,
                "max_mv": max_mv,
                "may_fail": may_fail,
            }
        ],
    }


def _vanilla_artifact_dict(name="Test Artifact"):
    return {
        "name": name,
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1},
    }


def _vanilla_creature_dict_local(name="Test Creature", mv=2):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": mv},
        "power": 2,
        "toughness": 2,
    }


def test_register_search_library_for_card_required_filter_name(engine):
    """Missing filter_name raises at parse."""
    import pytest
    reg = engine.Registry()
    with pytest.raises(ValueError, match="missing required 'filter_name'"):
        reg.register_printing(
            {
                "name": "Bad Tutor",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "search_library_for_card"}],
            }
        )


def test_register_search_library_for_card_defaults(engine):
    """max_mv defaults to 0, may_fail defaults to True."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Default Tutor",
            "card_types": ["Sorcery"],
            "effects": [
                {"kind": "search_library_for_card", "filter_name": "artifact"}
            ],
        }
    )
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "search_library_for_card"
    assert eff["filter_name"] == "artifact"
    assert eff["max_mv"] == 0
    assert eff["may_fail"] is True


def test_resolve_search_library_for_artifact_moves_first_match_to_hand(synthetic_state):
    """Inject an artifact into p0's library, cast tutor — artifact
    moves to p0's hand."""
    artifact_id = synthetic_state.register_and_inject_object(
        _vanilla_artifact_dict(), 0, ZONE_LIBRARY
    )
    tutor_id = synthetic_state.register_and_inject_object(
        _tutor_dict(filter_name="artifact"), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(tutor_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(artifact_id) == ZONE_HAND


def test_resolve_search_library_for_basic_plains_picks_named_basic(synthetic_state):
    """basic_plains filter matches printing.name == 'Plains'."""
    plains_id = synthetic_state.register_and_inject_object(
        {
            "name": "Plains",
            "card_types": ["Land"],
            "mana_produced": ["W"],
        },
        0,
        ZONE_LIBRARY,
    )
    tutor_id = synthetic_state.register_and_inject_object(
        _tutor_dict(filter_name="basic_plains"), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(tutor_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.find_object_zone(plains_id) == ZONE_HAND


def test_resolve_search_library_for_creature_small_obeys_max_mv(synthetic_state):
    """creature_small filter picks first creature with mana_value <= max_mv."""
    # Inject a 4-mana creature (too big) then a 1-mana creature (small).
    # Library Vec: top is last; inject big first so small ends up on top.
    big_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_local(name="Big Beast", mv=4), 0, ZONE_LIBRARY
    )
    small_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict_local(name="Small Beast", mv=1), 0, ZONE_LIBRARY
    )
    tutor_id = synthetic_state.register_and_inject_object(
        _tutor_dict(filter_name="creature_small", max_mv=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(tutor_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Small went to hand; big stayed in library.
    assert synthetic_state.find_object_zone(small_id) == ZONE_HAND
    assert synthetic_state.find_object_zone(big_id) == ZONE_LIBRARY


def test_resolve_search_library_for_card_unknown_filter_fizzles(synthetic_state):
    """Unknown filter_name → silent fizzle, no library mutation."""
    artifact_id = synthetic_state.register_and_inject_object(
        _vanilla_artifact_dict(), 0, ZONE_LIBRARY
    )
    tutor_id = synthetic_state.register_and_inject_object(
        _tutor_dict(filter_name="bogus_filter"), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(tutor_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Artifact stays in library.
    assert synthetic_state.find_object_zone(artifact_id) == ZONE_LIBRARY


def test_resolve_search_library_for_card_no_match_fizzles(synthetic_state):
    """No match in library → silent fizzle."""
    tutor_id = synthetic_state.register_and_inject_object(
        _tutor_dict(filter_name="artifact"), 0, ZONE_HAND
    )
    # Synthetic state's default library has only Forests; no Artifact.
    p0_hand_before = synthetic_state.hand_sizes[0]
    synthetic_state.push_to_stack(tutor_id, 0)
    synthetic_state.resolve_top_of_stack()
    # No card moved to hand from the search (source itself goes to gy
    # via post-resolve since it's a Sorcery, so hand_size delta = -1
    # from the source removal, not the search).
    assert synthetic_state.hand_sizes[0] == p0_hand_before - 1


def test_resolve_search_library_for_card_clone_isolation(synthetic_state):
    artifact_id = synthetic_state.register_and_inject_object(
        _vanilla_artifact_dict(), 0, ZONE_LIBRARY
    )
    tutor_id = synthetic_state.register_and_inject_object(
        _tutor_dict(filter_name="artifact"), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(tutor_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone: artifact in hand. Source: artifact still in library.
    assert cloned.find_object_zone(artifact_id) == ZONE_HAND
    assert synthetic_state.find_object_zone(artifact_id) == ZONE_LIBRARY


# -------------------------------------------------------------------------
# CE8 Slice 2 — external-RNG path on the three gameplay shuffle sites.
#
# `shuffle_library_with_seed`, `search_library_and_move_to_hand`, and
# `search_library_for_first_of_type_and_shuffle` all accept an optional
# `rng` kwarg (a Python `random.Random` instance). When supplied, the
# Fisher-Yates shuffle consumes draws from the supplied stream via
# `_randbelow`, matching `random.Random.shuffle(list)` byte-for-byte.
# When `rng=None` (default), the legacy xorshift64 path runs unchanged.
# -------------------------------------------------------------------------


def test_shuffle_library_with_external_rng_matches_python_shuffle(synthetic_state):
    """CE8 Slice 2: passing `rng=random.Random(seed)` to
    `shuffle_library_with_seed` produces a library order bit-identical
    to what `random.Random(seed).shuffle(obj_ids)` produces on the
    Python side."""
    import random

    pre_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    # Python reference using the same seed.
    py_ids = list(pre_ids)
    random.Random(2026).shuffle(py_ids)

    # Rust path consuming from `random.Random(2026)`.
    synthetic_state.shuffle_library_with_seed(0, 0, rng=random.Random(2026))
    rust_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)

    assert rust_ids == py_ids


def test_shuffle_library_with_external_rng_ignores_seed(synthetic_state):
    """`rng` takes precedence over the `seed` parameter — two calls
    with the same `rng` state and different `seed` values produce
    identical library orders."""
    import random

    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.shuffle_library_with_seed(0, 0, rng=random.Random(42))
    b.shuffle_library_with_seed(0, 99_999, rng=random.Random(42))

    a_ids = _library_obj_ids(a, 0, P0_LIBRARY_SIZE)
    b_ids = _library_obj_ids(b, 0, P0_LIBRARY_SIZE)
    assert a_ids == b_ids


def test_shuffle_library_with_external_rng_none_falls_back_to_xorshift(
    synthetic_state,
):
    """Backward compat: `rng=None` (or omitting the kwarg) keeps the
    xorshift64 path bit-equivalent to pre-slice behavior."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.shuffle_library_with_seed(0, 42)
    b.shuffle_library_with_seed(0, 42, rng=None)

    a_ids = _library_obj_ids(a, 0, P0_LIBRARY_SIZE)
    b_ids = _library_obj_ids(b, 0, P0_LIBRARY_SIZE)
    assert a_ids == b_ids


def test_search_library_and_move_to_hand_with_external_rng_matches_python_shuffle(
    synthetic_state,
):
    """The post-search shuffle in `search_library_and_move_to_hand`
    routes through the external rng when supplied. Compare the
    post-shuffle library against a Python reference that does the
    same remove + `random.Random(seed).shuffle` on obj_ids.
    """
    import random

    pre_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)

    # Python reference: remove the first Forest then shuffle.
    py_ids = list(pre_ids)
    # First match for FOREST_PID = id 17 (lib[0]), per the synthetic
    # state's id allocation.
    py_ids.remove(P0_FIRST_LIBRARY_ID)
    random.Random(2026).shuffle(py_ids)

    found = synthetic_state.search_library_and_move_to_hand(
        0, FOREST_PID, 0, rng=random.Random(2026)
    )
    assert found == P0_FIRST_LIBRARY_ID
    rust_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE - 1)
    assert rust_ids == py_ids


def test_search_library_and_move_to_hand_with_external_rng_failed_search_still_shuffles(
    synthetic_state,
):
    """Per CR 701.18, a failed search still shuffles. Confirm the
    external-rng path triggers the shuffle even when no match is
    found."""
    import random

    pre_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    py_ids = list(pre_ids)
    random.Random(7).shuffle(py_ids)

    # printing_id 99 is not in the library; search misses.
    found = synthetic_state.search_library_and_move_to_hand(
        0, 99, 0, rng=random.Random(7)
    )
    assert found is None
    rust_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)
    assert rust_ids == py_ids


def test_search_library_and_move_to_hand_with_external_rng_none_falls_back(
    synthetic_state,
):
    """Backward compat for `search_library_and_move_to_hand`: omitting
    `rng` (or passing `rng=None`) keeps the xorshift64 path bit-equal."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.search_library_and_move_to_hand(0, FOREST_PID, 42)
    b.search_library_and_move_to_hand(0, FOREST_PID, 42, rng=None)

    a_ids = _library_obj_ids(a, 0, P0_LIBRARY_SIZE - 1)
    b_ids = _library_obj_ids(b, 0, P0_LIBRARY_SIZE - 1)
    assert a_ids == b_ids


def test_search_library_for_first_of_type_and_shuffle_with_external_rng_matches_python(
    synthetic_state,
):
    """The post-search shuffle in
    `search_library_for_first_of_type_and_shuffle` routes through the
    external rng when supplied. Reference: Python remove-the-first-Land
    + `random.Random(seed).shuffle` on obj_ids."""
    import random

    pre_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE)

    # First Land match in library = lib[0] = id 17 (the entire library
    # is Forest in the synthetic state).
    py_ids = list(pre_ids)
    py_ids.remove(P0_FIRST_LIBRARY_ID)
    random.Random(2026).shuffle(py_ids)

    found = synthetic_state.search_library_for_first_of_type_and_shuffle(
        0, "Land", 0, rng=random.Random(2026)
    )
    assert found == P0_FIRST_LIBRARY_ID
    rust_ids = _library_obj_ids(synthetic_state, 0, P0_LIBRARY_SIZE - 1)
    assert rust_ids == py_ids


def test_search_library_for_first_of_type_and_shuffle_with_external_rng_none_falls_back(
    synthetic_state,
):
    """Backward compat: omitting `rng` keeps the xorshift64 path
    bit-equal to passing `rng=None`."""
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()

    a.search_library_for_first_of_type_and_shuffle(0, "Land", 42)
    b.search_library_for_first_of_type_and_shuffle(0, "Land", 42, rng=None)

    a_ids = _library_obj_ids(a, 0, P0_LIBRARY_SIZE - 1)
    b_ids = _library_obj_ids(b, 0, P0_LIBRARY_SIZE - 1)
    assert a_ids == b_ids


def test_shuffle_library_with_external_rng_is_deterministic(synthetic_state):
    """Two clones + two fresh `random.Random(seed)` of the same seed
    produce byte-identical libraries."""
    import random

    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.shuffle_library_with_seed(0, 0, rng=random.Random(99))
    b.shuffle_library_with_seed(0, 0, rng=random.Random(99))
    a_ids = _library_obj_ids(a, 0, P0_LIBRARY_SIZE)
    b_ids = _library_obj_ids(b, 0, P0_LIBRARY_SIZE)
    assert a_ids == b_ids


def test_shuffle_library_with_external_rng_raises_on_invalid_rng(synthetic_state):
    """Passing an object without `_randbelow` surfaces a Python-side
    error (matches the substrate contract in `external_rng`)."""
    with pytest.raises((AttributeError, TypeError)):
        synthetic_state.shuffle_library_with_seed(0, 0, rng=42)
