"""Zone-movement primitives on ``GameState``.

Ported from the zone-mutation patterns in ``src/mtg_bot/turn.py``
(``draw_card``) and ``src/mtg_bot/actions.py`` / ``effects/*`` (the
``card.zone = Zone.X`` + per-zone list mutation pattern). On the Python
side the operation is two coupled mutations — ``p.library.pop(0);
top.zone = Zone.HAND; p.hand.append(top)`` — so the Rust port collapses
both into a single primitive that owns the membership move + the
``GameObject.zone`` tag update.

**Zone identifier choice (option b in the slice brief):** raw ``u8``
constants rather than a Rust ``ZoneKind`` enum. Adding an enum to
``state.rs`` would have forced an edit on a file two sibling slices
also need to grow this commit, so we keep the encoding inline. The
constants are duplicated test-side for readability — this is a
first-slice expedient and a follow-up can either expose them as
module-level Python attrs on ``mtg_bot_engine`` or upgrade to an enum
once the parallel-slice constraint relaxes.
"""

from __future__ import annotations

import pytest

# Zone constants — must match the values in
# ``rust/src/state_ops_zones.rs``. Hard-coded here rather than imported
# so the test file is self-contained and the encoding contract is
# visible at the call site.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_STACK = 4
ZONE_EXILE = 5


# `make_synthetic_state(num_battlefield=10, num_hand=7, num_library=50)`
# lays player 0 out as:
#   battlefield: ids 0..9
#   hand:        ids 10..16
#   library:     ids 17..66
# and player 1's range starts at 67. We rely on those id ranges below.
P0_FIRST_BATTLEFIELD_ID = 0
P0_FIRST_HAND_ID = 10
P0_FIRST_LIBRARY_ID = 17


def test_find_object_zone_returns_battlefield_for_battlefield_object(synthetic_state):
    """An object known to live on the battlefield resolves to
    ``ZONE_BATTLEFIELD`` regardless of the placeholder value its
    ``GameObject.zone`` field carried at construction time."""
    assert synthetic_state.find_object_zone(P0_FIRST_BATTLEFIELD_ID) == ZONE_BATTLEFIELD


def test_find_object_zone_returns_hand_for_hand_object(synthetic_state):
    assert synthetic_state.find_object_zone(P0_FIRST_HAND_ID) == ZONE_HAND


def test_find_object_zone_returns_library_for_library_object(synthetic_state):
    assert synthetic_state.find_object_zone(P0_FIRST_LIBRARY_ID) == ZONE_LIBRARY


def test_find_object_zone_unknown_id_returns_none(synthetic_state):
    """Far-out-of-range id returns None (no exception)."""
    assert synthetic_state.find_object_zone(999_999) is None


def test_move_object_to_graveyard_removes_from_source_zone(synthetic_state):
    """Moving a battlefield object into the graveyard removes it from
    the battlefield and pushes it onto the graveyard. The object's
    ``zone`` field updates to track the new home."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    bf_before, gy_before = (
        synthetic_state.battlefield_sizes,
        synthetic_state.graveyard_sizes,
    )
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD

    moved = synthetic_state.move_object(obj_id, ZONE_GRAVEYARD, 0)
    assert moved is True

    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] - 1
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 1
    # Other player untouched.
    assert synthetic_state.battlefield_sizes[1] == bf_before[1]
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]


def test_move_object_unknown_id_returns_false(synthetic_state):
    """Asked to move an id we don't know about: no-op, return False."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes
    moved = synthetic_state.move_object(999_999, ZONE_GRAVEYARD, 0)
    assert moved is False
    # All zones unchanged.
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_move_object_preserves_id_and_printing(synthetic_state):
    """The moved object keeps its identity — same id, same printing
    (so the registry lookup chain still resolves to the same name)."""
    obj_id = P0_FIRST_HAND_ID  # an elf
    name_before = synthetic_state.printing_name_of(obj_id)
    assert name_before == "Llanowar Elves"

    assert synthetic_state.move_object(obj_id, ZONE_GRAVEYARD, 0) is True

    # Same id, still resolves to the same printing.
    assert synthetic_state.printing_name_of(obj_id) == "Llanowar Elves"
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_clone_then_move_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary: mutating a zone on a clone must not
    leak back into the source state. Each ``Player`` zone is an
    ``Arc<Vec<GameObject>>``; ``Arc::make_mut`` clones the inner Vec
    on first write, isolating the clone from its peers."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    cloned = synthetic_state.clone_once()
    bf_source_before = synthetic_state.battlefield_sizes
    gy_source_before = synthetic_state.graveyard_sizes

    assert cloned.move_object(obj_id, ZONE_GRAVEYARD, 0) is True

    # Clone diverged.
    assert cloned.find_object_zone(obj_id) == ZONE_GRAVEYARD
    # Source untouched: object is still on the battlefield with the
    # same zone-size totals.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes == bf_source_before
    assert synthetic_state.graveyard_sizes == gy_source_before


def test_draw_card_moves_top_of_library_to_hand(synthetic_state):
    """``draw_card`` returns the drawn object's id, shrinks the
    library by one, and grows the hand by one. The Rust convention is
    that the LAST element of the library Vec is the "top of library"
    (Python's ``library.pop(0)`` treats the front as the top — the
    Rust port flips that for ``Vec::pop`` cheapness; documented in
    the Rust docstring)."""
    lib_before = synthetic_state.library_sizes
    hand_before = synthetic_state.hand_sizes

    drawn = synthetic_state.draw_card(0)

    assert drawn is not None
    assert isinstance(drawn, int)
    assert synthetic_state.library_sizes[0] == lib_before[0] - 1
    assert synthetic_state.hand_sizes[0] == hand_before[0] + 1
    # Other player untouched.
    assert synthetic_state.library_sizes[1] == lib_before[1]
    assert synthetic_state.hand_sizes[1] == hand_before[1]
    # Drawn card now lives in hand.
    assert synthetic_state.find_object_zone(drawn) == ZONE_HAND


def test_draw_card_from_empty_library_returns_none(engine):
    """Draw from an empty library returns None — the Python engine
    flips ``has_lost = True`` here, but the Rust slice keeps the
    primitive narrow: pop returns ``None``, callers layer policy on
    top later."""
    state = engine.make_synthetic_state(
        num_battlefield=2, num_hand=2, num_library=0
    )
    assert state.library_sizes[0] == 0
    assert state.draw_card(0) is None
    assert state.hand_sizes[0] == 2  # unchanged
