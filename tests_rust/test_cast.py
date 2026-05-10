"""Cast / play primitives on the Rust ``GameState``.

Ported from the Python ``_play_land`` and ``_cast_spell`` paths in
``src/mtg_bot/actions.py``. The Python side spreads the cast pipeline
across hundreds of lines (alt-costs, room halves, warp / impulse /
top-of-library origins, ETB triggers, stack push, priority pass);
the Rust first slice carves off the irreducible primitive: take a
card from hand, pay its mana, deposit it on the battlefield.

**Scope simplifications** (mirrored in the module docstring on
``rust/src/state_ops_cast.rs``):

- **No stack yet.** Casting a creature spell moves it directly
  hand -> battlefield after paying mana. Sorceries / instants /
  triggered-via-stack interactions are deferred until a Rust-side
  stack lands.
- **No one-land-per-turn enforcement.** ``play_land`` does not check
  ``lands_played_this_turn``. The Python side enforces this at
  ``legal_actions`` time, not inside the play primitive itself, so
  the primitive's responsibility is "move the card and tag the
  state" — caller (or a future ``legal_actions`` port) gates whether
  the call is legal at all. TODO: revisit once a per-turn flag lives
  on ``GameState``.
- **No sorcery-speed restrictions.** Same rationale: caller's
  responsibility.
- **Land detector: ``printing.mana_produced.is_some()``.** The
  registry doesn't model a card-type system yet, so the slice uses
  the "produces mana when tapped" predicate as a stepping-stone for
  "this is a land". In the synthetic seed, Forest qualifies and
  Grizzly Bears does not — covered by the tests below. Llanowar
  Elves (which has ``mana_produced`` set in the synthetic seed for
  the mana-slice's tap-for-mana coverage) would also qualify under
  this predicate; we don't test the elf-as-land case because the
  stepping-stone is acknowledged in the module docstring and a
  proper card-type system supersedes it.
- **Mana payment: best-effort spend with generic-fills-from-anywhere.**
  ``cast_creature`` reads the printing's ``mana_cost``, deducts
  colored pips from the matching pool slot, then fills generic from
  whatever's left in W/U/B/R/G/C order. Returns ``False`` (no
  mutation) if total mana is insufficient. Hybrid / X / phyrexian
  costs are not modeled.

Synthetic seed reminder (see ``make_synthetic_state`` in
``rust/src/state.rs``):

- Player 0 hand: ids 10..16, all Llanowar Elves (cost {G})
- Player 0 battlefield: ids 0..4 Forest, 5..9 Grizzly Bears
- Player 0 library: ids 17..66, all Forest
- Player 1: same shape, ids start at 67
"""

from __future__ import annotations

import pytest

# Zone constants — must match ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3

# Synthetic-state id ranges (default 10/7/50 layout).
P0_FIRST_BATTLEFIELD_ID = 0
P0_FIRST_BEARS_ID = 5  # battlefield slot 5..9 are Grizzly Bears
P0_FIRST_HAND_ID = 10  # hand[0] is a Llanowar Elves
P0_FIRST_LIBRARY_ID = 17  # library[0..49] are Forests


def _move_forest_into_hand(state, player_id=0):
    """Move a Forest from ``player_id``'s library into their hand and
    return the moved object's id. Synthetic state seeds the hand with
    Llanowar Elves only — tests that need a Forest in hand bring one
    over from the library first via the existing ``move_object``
    primitive."""
    forest_id = P0_FIRST_LIBRARY_ID  # any library slot is a Forest
    assert state.printing_name_of(forest_id) == "Forest"
    moved = state.move_object(forest_id, ZONE_HAND, player_id)
    assert moved is True
    assert state.find_object_zone(forest_id) == ZONE_HAND
    return forest_id


# --- play_land ------------------------------------------------------


def test_play_land_moves_card_from_hand_to_battlefield(synthetic_state):
    """The happy path: a Forest in hand moves to the battlefield."""
    forest_id = _move_forest_into_hand(synthetic_state, 0)
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    ok = synthetic_state.play_land(forest_id, 0)
    assert ok is True

    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # Other player untouched.
    assert synthetic_state.hand_sizes[1] == 7
    assert synthetic_state.battlefield_sizes[1] == 10


def test_play_land_returns_true_on_success(synthetic_state):
    forest_id = _move_forest_into_hand(synthetic_state, 0)
    assert synthetic_state.play_land(forest_id, 0) is True


def test_play_land_unknown_id_returns_false(synthetic_state):
    bf_before = synthetic_state.battlefield_sizes
    hand_before = synthetic_state.hand_sizes
    assert synthetic_state.play_land(999_999, 0) is False
    # No mutation.
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.hand_sizes == hand_before


def test_play_land_non_land_returns_false(synthetic_state):
    """Llanowar Elves in hand has ``mana_produced`` set on the
    synthetic seed, but Grizzly Bears (a creature with no mana
    production) does NOT qualify under the stepping-stone
    land-detector. Move a Bears into hand and verify ``play_land``
    declines."""
    bears_id = P0_FIRST_BEARS_ID  # currently on the battlefield
    assert synthetic_state.printing_name_of(bears_id) == "Grizzly Bears"
    # Yank the Bears off the battlefield and into hand so the precondition
    # ("card is in hand") is met but the printing fails the land check.
    assert synthetic_state.move_object(bears_id, ZONE_HAND, 0) is True
    assert synthetic_state.find_object_zone(bears_id) == ZONE_HAND
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.play_land(bears_id, 0) is False

    # No mutation: Bears stays in hand.
    assert synthetic_state.find_object_zone(bears_id) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_play_land_not_in_hand_returns_false(synthetic_state):
    """A Forest already on the battlefield can't be 'played as a land'
    again — the precondition is 'card is in player's hand'."""
    forest_id = P0_FIRST_BATTLEFIELD_ID  # already on the battlefield
    assert synthetic_state.printing_name_of(forest_id) == "Forest"
    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    bf_before = synthetic_state.battlefield_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]

    assert synthetic_state.play_land(forest_id, 0) is False

    # No mutation.
    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before
    assert synthetic_state.hand_sizes[0] == hand_before


# --- cast_creature --------------------------------------------------


def test_cast_creature_pays_mana_and_moves_to_battlefield(synthetic_state):
    """Llanowar Elves in hand costs {G}. Give player 0 one green and
    cast: the elf lands on the battlefield, hand shrinks by 1, the
    green pip is consumed."""
    elf_id = P0_FIRST_HAND_ID
    assert synthetic_state.printing_name_of(elf_id) == "Llanowar Elves"
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.get_mana_pool(0)["G"] == 1
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    ok = synthetic_state.cast_creature(elf_id, 0)
    assert ok is True

    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # Mana spent.
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_cast_creature_insufficient_mana_returns_false(synthetic_state):
    """Empty pool, no mana to spend. cast_creature returns False and
    leaves every observable bit of state untouched."""
    elf_id = P0_FIRST_HAND_ID
    pool_before = synthetic_state.get_mana_pool(0)
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.cast_creature(elf_id, 0) is False

    # No mutation: card still in hand, pool still empty.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_HAND
    assert synthetic_state.get_mana_pool(0) == pool_before
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_cast_creature_unknown_id_returns_false(synthetic_state):
    synthetic_state.add_mana(0, "G", 5)
    bf_before = synthetic_state.battlefield_sizes
    hand_before = synthetic_state.hand_sizes
    assert synthetic_state.cast_creature(999_999, 0) is False
    # No mutation, even on the mana side (the spell wasn't found, so
    # there was no cost to pay).
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.get_mana_pool(0)["G"] == 5


def test_cast_creature_not_in_hand_returns_false(synthetic_state):
    """A Grizzly Bears already on the battlefield can't be cast — the
    precondition is 'card is in player's hand'."""
    bears_id = P0_FIRST_BEARS_ID
    assert synthetic_state.find_object_zone(bears_id) == ZONE_BATTLEFIELD
    synthetic_state.add_mana(0, "G", 5)
    synthetic_state.add_mana(0, "C", 5)
    bf_before = synthetic_state.battlefield_sizes
    hand_before = synthetic_state.hand_sizes

    assert synthetic_state.cast_creature(bears_id, 0) is False

    # No mutation.
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.hand_sizes == hand_before


def test_cast_creature_summoning_sick_after_cast(synthetic_state):
    """A freshly-cast creature has summoning sickness — mirrors the
    Python ``put_into_battlefield`` default. ``is_summoning_sick``
    came in with the tap slice."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(elf_id, 0) is True
    assert synthetic_state.is_summoning_sick(elf_id) is True


def test_cast_creature_with_generic_cost_uses_any_color(synthetic_state):
    """Bears costs {1}{G}: one green pip + one generic. Pay green
    with G and generic with C — total spend should be exactly the
    listed pips. We move a Bears from battlefield into hand to set
    up the precondition (the synthetic seed has only elves in hand)."""
    bears_id = P0_FIRST_BEARS_ID
    assert synthetic_state.move_object(bears_id, ZONE_HAND, 0) is True
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)
    # Plus a stray red to confirm only 2 pips total go away.
    synthetic_state.add_mana(0, "R", 1)
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.cast_creature(bears_id, 0) is True

    pool = synthetic_state.get_mana_pool(0)
    assert pool["G"] == 0  # green pip went to the colored requirement
    assert pool["C"] == 0  # colorless filled the generic
    assert pool["R"] == 1  # untouched
    assert synthetic_state.find_object_zone(bears_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1


def test_cast_creature_generic_can_be_paid_with_colored(synthetic_state):
    """Generic cost can be paid with any color — Bears costs {1}{G}.
    Give player 0 only green (2 of them); the green pip pays the
    colored requirement, the leftover green pays the generic."""
    bears_id = P0_FIRST_BEARS_ID
    assert synthetic_state.move_object(bears_id, ZONE_HAND, 0) is True
    synthetic_state.add_mana(0, "G", 2)

    assert synthetic_state.cast_creature(bears_id, 0) is True

    # Both green pips spent.
    assert synthetic_state.get_mana_pool(0)["G"] == 0


# --- CoW canaries ---------------------------------------------------


def test_clone_then_cast_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary for the cast path. Casting on a clone
    must not bleed back into the source: hand, battlefield, AND mana
    pool all need to stay isolated."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    cloned = synthetic_state.clone_once()
    assert cloned.cast_creature(elf_id, 0) is True

    # Clone diverged.
    assert cloned.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert cloned.get_mana_pool(0)["G"] == 0
    # Source untouched: elf still in hand, green pip still in pool.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_HAND
    assert synthetic_state.get_mana_pool(0)["G"] == 1


def test_play_land_clone_then_play_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary for the play-land path."""
    forest_id = _move_forest_into_hand(synthetic_state, 0)

    cloned = synthetic_state.clone_once()
    assert cloned.play_land(forest_id, 0) is True

    # Clone diverged.
    assert cloned.find_object_zone(forest_id) == ZONE_BATTLEFIELD
    # Source untouched: Forest still in hand.
    assert synthetic_state.find_object_zone(forest_id) == ZONE_HAND
