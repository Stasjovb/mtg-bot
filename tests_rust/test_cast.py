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
- **Land detector: ``printing.card_types`` contains ``"Land"``.**
  Foundation r6 (cf1fc6c) added ``card_types: Vec<String>`` to
  ``CardPrinting``; the cast slice now uses a clean type-based
  detector. In the synthetic seed Forest carries ``["Land"]``,
  Grizzly Bears carries ``["Creature"]``, and Llanowar Elves
  carries ``["Creature"]`` — so ``play_land(llanowar)`` correctly
  rejects (the round-4 ``mana_produced.is_some()`` stepping stone
  produced a documented false-positive on the elf; this slice
  retires it).
- **Creature-spell detector: ``printing.card_types`` contains
  ``"Creature"``.** ``cast_creature`` now refuses to cast a
  printing whose types don't include ``"Creature"`` — Forest
  (a ``["Land"]``) is correctly rejected.
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
    """Grizzly Bears (card_types = ["Creature"]) does NOT qualify
    under the card_types-based land detector. Move a Bears into
    hand and verify ``play_land`` declines."""
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


def test_play_land_on_creature_returns_false(synthetic_state):
    """Llanowar Elves seeds with ``card_types = ["Creature"]`` and
    ``mana_produced = Some(["G"])``. Round-4 used the
    ``mana_produced.is_some()`` stepping-stone, which falsely
    accepted the elf as a land. Foundation r6 added card_types and
    this slice rewired ``play_land`` to check it; the elf must now
    be rejected. The synthetic seed already has Llanowar Elves in
    hand at ``P0_FIRST_HAND_ID``."""
    elf_id = P0_FIRST_HAND_ID
    assert synthetic_state.printing_name_of(elf_id) == "Llanowar Elves"
    assert synthetic_state.find_object_zone(elf_id) == ZONE_HAND
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.play_land(elf_id, 0) is False

    # No mutation: elf stays in hand, never reaches the battlefield.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_HAND
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_play_land_correctly_accepts_forest(synthetic_state):
    """Belt-and-braces confirmation that Forest still plays as a
    land under the new card_types-based detector. Forest carries
    ``card_types = ["Land"]`` in the synthetic seed."""
    forest_id = _move_forest_into_hand(synthetic_state, 0)
    assert synthetic_state.printing_name_of(forest_id) == "Forest"

    assert synthetic_state.play_land(forest_id, 0) is True

    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD


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


def test_cast_creature_on_land_returns_false(synthetic_state):
    """A Forest (``card_types = ["Land"]``) is not a Creature spell.
    The card_types-based detector in ``cast_creature`` must reject
    it. Move a Forest into hand, give the player a green pip, and
    verify the cast declines and the pip stays in the pool."""
    forest_id = _move_forest_into_hand(synthetic_state, 0)
    assert synthetic_state.printing_name_of(forest_id) == "Forest"
    synthetic_state.add_mana(0, "G", 1)
    pool_before = synthetic_state.get_mana_pool(0)
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.cast_creature(forest_id, 0) is False

    # No mutation: Forest stays in hand, mana pool untouched.
    assert synthetic_state.find_object_zone(forest_id) == ZONE_HAND
    assert synthetic_state.get_mana_pool(0) == pool_before
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_cast_creature_correctly_accepts_grizzly_bears(synthetic_state):
    """Belt-and-braces confirmation that a Creature-typed printing
    still casts under the new card_types-based detector. Grizzly
    Bears carries ``card_types = ["Creature"]``."""
    bears_id = P0_FIRST_BEARS_ID
    assert synthetic_state.move_object(bears_id, ZONE_HAND, 0) is True
    synthetic_state.add_mana(0, "G", 2)
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.cast_creature(bears_id, 0) is True

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


# --- flash (CR 702.8) -----------------------------------------------
#
# Flash makes a creature castable at instant speed: a flash creature can
# be cast any time the player has priority — outside main phase, on the
# opponent's turn, in response to a triggered ability, etc.
#
# **Documentation-only slice.** The current Rust ``cast_creature`` does
# not gate on ``state.phase`` at all (sorcery-speed enforcement lives
# in the Python ``legal_actions`` layer; this primitive is "move the
# card and tag the state"). With no phase gate to bypass, "flash works"
# is vacuously true: any creature, flash or not, casts in any phase.
# These tests pin that behavior so the slice that adds the
# sorcery-speed guard can NOT regress flash without going red here.
# The mana-cost test exercises the orthogonal "all other gates stay
# in place" guarantee called out in the round-19 task description.
#
# Phase constants — must match ``rust/src/state_ops_steps.rs``.
PHASE_UNTAP = 0
PHASE_BEGIN_COMBAT = 4
PHASE_MAIN1 = 3


def _flash_bear_dict():
    """A 2/2 creature printing carrying just the ``flash`` keyword.
    Cost {1}{G} matches Grizzly Bears so the existing mana-payment
    coverage carries over. Shape mirrors ``_vigilance_bear_dict`` in
    ``test_combat.py`` — register-and-inject is the standard test
    harness for slice-local printings."""
    return {
        "name": "Test Flash Bear",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "keywords": ["flash"],
        "effects": [],
    }


def _vanilla_bear_dict():
    """A 2/2 creature printing with NO keywords. Companion to
    ``_flash_bear_dict`` — used by the regression test that proves
    casting in non-main phases is unchanged for vanilla creatures
    (i.e. the slice didn't accidentally add a phase guard)."""
    return {
        "name": "Test Vanilla Bear",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "keywords": [],
        "effects": [],
    }


def test_cast_creature_flash_in_untap_phase(synthetic_state):
    """A flash creature can be cast in UNTAP — the most aggressively
    non-main phase. Synthetic state's default phase IS UNTAP, but pin
    the read explicitly so a future fixture change can't silently
    move us off the test's intended phase."""
    synthetic_state.set_phase(PHASE_UNTAP)
    obj_id = synthetic_state.register_and_inject_object(
        _flash_bear_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.cast_creature(obj_id, 0) is True

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1


def test_cast_creature_flash_in_combat_phase(synthetic_state):
    """A flash creature can be cast during combat (BEGIN_COMBAT here),
    which is the most common real-game flash window — flashing in a
    blocker after attackers are declared, or a flash creature in
    response to a combat trigger."""
    synthetic_state.set_phase(PHASE_BEGIN_COMBAT)
    obj_id = synthetic_state.register_and_inject_object(
        _flash_bear_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)

    assert synthetic_state.cast_creature(obj_id, 0) is True
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_cast_creature_vanilla_in_non_main_phase_still_succeeds(synthetic_state):
    """Regression / today's-reality canary: the slice does NOT add a
    phase guard for vanilla creatures (sorcery-speed enforcement is
    Python-side / a future Rust slice). This test pins that fact —
    when the future slice tightens the gate, this test should be
    updated alongside the gate so the change is visible."""
    synthetic_state.set_phase(PHASE_BEGIN_COMBAT)
    obj_id = synthetic_state.register_and_inject_object(
        _vanilla_bear_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)

    # Today: succeeds (no phase guard exists). When the phase guard
    # lands, this assertion flips to False and the test is renamed
    # ``..._still_rejected`` per the round-19 task description.
    assert synthetic_state.cast_creature(obj_id, 0) is True
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_cast_creature_flash_on_opponents_turn(synthetic_state):
    """Flash creature controlled by player 1 can be cast while player
    0 is the active player (i.e. it's player 0's turn). Synthetic
    state seeds ``active_player = 0``; we set the phase to a
    non-main phase to be explicit, then cast as player 1."""
    synthetic_state.set_phase(PHASE_BEGIN_COMBAT)
    assert synthetic_state.active_player == 0
    obj_id = synthetic_state.register_and_inject_object(
        _flash_bear_dict(), 1, ZONE_HAND
    )
    synthetic_state.add_mana(1, "G", 1)
    synthetic_state.add_mana(1, "C", 1)

    assert synthetic_state.cast_creature(obj_id, 1) is True
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_cast_creature_flash_still_respects_mana_cost(synthetic_state):
    """Flash lifts the timing restriction, NOT the mana cost. A flash
    creature still has to pay its full mana cost; insufficient mana
    rejects the cast just like a vanilla creature would. Pins the
    "all other gates stay in place" invariant from the round-19
    task description."""
    synthetic_state.set_phase(PHASE_BEGIN_COMBAT)
    obj_id = synthetic_state.register_and_inject_object(
        _flash_bear_dict(), 0, ZONE_HAND
    )
    # Only one G — short by one generic pip.
    synthetic_state.add_mana(0, "G", 1)
    pool_before = synthetic_state.get_mana_pool(0)
    bf_before = synthetic_state.battlefield_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]

    assert synthetic_state.cast_creature(obj_id, 0) is False

    # No mutation: the flash creature stays in hand, pool untouched.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    assert synthetic_state.get_mana_pool(0) == pool_before
    assert synthetic_state.battlefield_sizes[0] == bf_before
    assert synthetic_state.hand_sizes[0] == hand_before
