"""Named choice helpers on the Rust ``GameState``.

Round-18 slice. The Python engine's ``apply_effect`` arms (DealDamage,
TapTarget, DestroyTarget, AddCounters, DiscardCard) duplicate the same
"pick the first card on the defender's battlefield / first card in
hand / top of library" pattern. The Rust port lifts those into named
``choose_*`` primitives on ``GameState`` so the per-effect arms can
collapse onto them.

Each helper is read-only (no ``Arc::make_mut``), returns ``Option<u32>``
(the chosen object id) or ``None`` when the choice would fizzle, and
raises ``ValueError`` on an out-of-range ``player_id`` (matches the
existing life / damage convention).

Synthetic-seed object-id layout used here (default
``make_synthetic_state(num_battlefield=10, num_hand=7,
num_library=50)``):

* p0 battlefield: ids 0..9 — first 5 are Forest (Land), last 5 are
  Grizzly Bears (Creature).
* p0 hand: ids 10..16 — Llanowar Elves (Creature).
* p0 library: ids 17..66 — Forest. Top of library = last element ⇒
  id 66.
* p1 battlefield: ids 67..76 — same Forest+Bears split. First creature
  = id 72.
* p1 hand: ids 77..83. p1 library: ids 84..133, top = id 133.
"""

from __future__ import annotations

import pytest


# --- choose_first_creature_for_player --------------------------------


def test_choose_first_creature_for_player_finds_creature(synthetic_state):
    # p0 bf is [Forest x5, Bears x5] — first creature is the first
    # Bears at bf index 5, which is obj_id 5.
    assert synthetic_state.choose_first_creature_for_player(0) == 5


def test_choose_first_creature_for_player_skips_non_creatures(synthetic_state):
    # Same layout for p1: ids 67..71 Forest, 72..76 Bears. First
    # creature on p1's battlefield is id 72.
    assert synthetic_state.choose_first_creature_for_player(1) == 72


def test_choose_first_creature_for_player_returns_none_when_empty(engine):
    # Empty battlefield ⇒ no creature ⇒ None.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.choose_first_creature_for_player(0) is None
    assert state.choose_first_creature_for_player(1) is None


def test_choose_first_creature_for_player_returns_none_when_only_lands(engine):
    # Inject a Forest-only battlefield via register_and_inject_object,
    # then verify there is no creature to choose.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    forest_dict = {
        "name": "Forest",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
    }
    state.register_and_inject_object(forest_dict, 0, 2)  # ZONE_BATTLEFIELD = 2
    state.register_and_inject_object(forest_dict, 0, 2)
    assert state.choose_first_creature_for_player(0) is None


# --- choose_first_card_in_hand_for_player ----------------------------


def test_choose_first_card_in_hand_returns_first_id(synthetic_state):
    # p0 hand[0] is obj_id 10 (Llanowar Elves).
    assert synthetic_state.choose_first_card_in_hand_for_player(0) == 10
    # p1 hand[0] is obj_id 77.
    assert synthetic_state.choose_first_card_in_hand_for_player(1) == 77


def test_choose_first_card_in_hand_empty_hand_returns_none(engine):
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.choose_first_card_in_hand_for_player(0) is None
    assert state.choose_first_card_in_hand_for_player(1) is None


# --- choose_top_of_library_for_player --------------------------------


def test_choose_top_of_library_returns_last_element_id(synthetic_state):
    # Top of library = last per round-1 convention. p0 library is
    # ids 17..66 ⇒ top = 66.
    assert synthetic_state.choose_top_of_library_for_player(0) == 66
    # p1 library: ids 84..133 ⇒ top = 133.
    assert synthetic_state.choose_top_of_library_for_player(1) == 133


def test_choose_top_of_library_empty_returns_none(engine):
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.choose_top_of_library_for_player(0) is None
    assert state.choose_top_of_library_for_player(1) is None


# --- choose_first_permanent_for_player -------------------------------


def test_choose_first_permanent_returns_bf0_id(synthetic_state):
    # Any permanent type — bf[0] regardless of card type. p0 bf[0] is
    # obj_id 0 (Forest); the helper does not filter by card type.
    assert synthetic_state.choose_first_permanent_for_player(0) == 0
    assert synthetic_state.choose_first_permanent_for_player(1) == 67


def test_choose_first_permanent_empty_returns_none(engine):
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    assert state.choose_first_permanent_for_player(0) is None


# --- choose_first_creature_for_defender ------------------------------


def test_choose_first_creature_for_defender_uses_inverse_active(synthetic_state):
    # Default active_player = 0 ⇒ defender = 1 ⇒ first creature on p1
    # is id 72.
    assert synthetic_state.active_player == 0
    assert synthetic_state.choose_first_creature_for_defender() == 72

    # Flip active to 1 by wrapping past CLEANUP. After the wrap,
    # active = 1, so defender = 0 ⇒ first creature on p0 = id 5.
    synthetic_state.set_phase(11)  # PHASE_CLEANUP
    synthetic_state.advance_phase()  # wraps to UNTAP, swaps active
    assert synthetic_state.active_player == 1
    assert synthetic_state.choose_first_creature_for_defender() == 5


# --- error path ------------------------------------------------------


def test_choose_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.choose_first_creature_for_player(99)
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.choose_first_card_in_hand_for_player(99)
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.choose_top_of_library_for_player(99)
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.choose_first_permanent_for_player(99)


# --- read-only contract ----------------------------------------------


def test_choose_clone_isolation(synthetic_state):
    # The helpers are read-only — no mutations expected. Pin the
    # contract by cloning and confirming the choice on the clone
    # matches the original, with no side effects on either.
    cloned = synthetic_state.clone_once()
    assert cloned.choose_first_creature_for_player(0) == 5
    assert synthetic_state.choose_first_creature_for_player(0) == 5

    # Sizes unchanged on both sides.
    assert (
        synthetic_state.battlefield_sizes
        == cloned.battlefield_sizes
        == [10, 10]
    )
    assert synthetic_state.hand_sizes == cloned.hand_sizes == [7, 7]
    assert synthetic_state.library_sizes == cloned.library_sizes == [50, 50]
