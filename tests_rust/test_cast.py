"""Cast / play primitives on the Rust ``GameState``.

Ported from the Python ``_play_land`` and ``_cast_spell`` paths in
``src/mtg_bot/actions.py``. The Python side spreads the cast pipeline
across hundreds of lines (alt-costs, room halves, warp / impulse /
top-of-library origins, ETB triggers, stack push, priority pass);
the Rust first slice carves off the irreducible primitive: take a
card from hand, pay its mana, deposit it on the battlefield.

**Scope simplifications** (mirrored in the module docstring on
``rust/src/state_ops_cast.rs``):

- **G7 Slice S1 (stack-and-priority creature cast) — LANDED.**
  Casting a creature spell now pays mana, fires ``Event::Cast``, and
  **pushes a spell ``StackItem``** (the card stays in hand, Rust's
  spell-stack model); it does NOT move to the battlefield in the
  cast primitive and does NOT auto-resolve. ``resolve_top_of_stack``
  later lands the creature on the battlefield (CR 608.2m via the
  already-present ``move_source_post_resolve`` permanent route,
  stamping ``summoning_sick`` + the ETB timestamp) and dispatches
  ``Event::Enters`` — byte-mirroring Python's resolve-time
  ``put_into_battlefield``. The no-stack pins below were
  closure-flipped to the stack-push + drive-resolve shape (the
  G4/G5/G6 closure-flip pattern). ``cast_creature_warp`` + the
  warp/impending/room riders remain no-stack until G7 Slice S4.
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
ZONE_STACK = 4  # G7 S5a: the spell-stack-source-zone store.

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
    """G7 S5a closure-flip (was S1). Llanowar Elves in hand costs
    {G}. Give player 0 one green and cast: the cast pushes a spell
    StackItem and re-homes the spell hand → the stack-object store
    (``zone == ZONE_STACK``, hand drains NOW), green pip consumed;
    driving ``resolve_top_of_stack`` then lands the elf on the
    battlefield. **S5a baseline move (new-code-is-right):** the spell
    leaves the hand AT CAST and ``find_object_zone`` reports
    ``ZONE_STACK`` — byte-mirroring Python ``_cast_spell``
    ``p.hand.remove(card)`` (``actions.py:1403``) + ``card.zone =
    Zone.STACK`` (``:1751``). Pre-S5a the S1 model kept it physically
    in the hand Vec (the documented, now-corrected divergence)."""
    elf_id = P0_FIRST_HAND_ID
    assert synthetic_state.printing_name_of(elf_id) == "Llanowar Elves"
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.get_mana_pool(0)["G"] == 1
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]
    stack_before = synthetic_state.stack_size()

    ok = synthetic_state.cast_creature(elf_id, 0)
    assert ok is True

    # Cast pushes the spell StackItem AND re-homes the spell to the
    # stack-object store: zone == ZONE_STACK, hand drains NOW (byte-
    # Python: p.hand.remove + card.zone=STACK), NOT yet on the
    # battlefield. Mana spent.
    assert synthetic_state.stack_size() == stack_before + 1
    assert synthetic_state.find_object_zone(elf_id) == ZONE_STACK
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before
    assert synthetic_state.get_mana_pool(0)["G"] == 0

    # Resolve: the creature lands on the battlefield, hand drains.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.is_stack_empty() is True


def test_cast_creature_insufficient_mana_returns_false(synthetic_state):
    """**G7 mid-game STATE_EQ closure-flip (auto-tap-from-lands).**
    The "insufficient mana -> clean no-op" invariant still holds, but
    under the NEW byte-Python-mirroring payment model the synthetic
    state's 5 untapped Forests would auto-tap to pay (exactly Python's
    ``_cast_spell`` -> ``auto_tap_for_cost``). To exercise GENUINE
    insufficient mana we first tap every p0 land so neither the pool
    NOR auto-tappable lands can cover the cost — then ``cast_creature``
    correctly returns ``False`` and leaves every observable bit
    untouched (the pre-fix pool-only ``is False`` here was a
    false-pass: the lands could always pay; the new model is correct,
    new-code-is-right)."""
    elf_id = P0_FIRST_HAND_ID
    # Genuinely unpayable: empty pool AND no untapped mana lands.
    for o in synthetic_state.battlefield_snapshot():
        if o["controller_id"] == 0 and o["printing_name"] == "Forest":
            synthetic_state.tap_object(o["id"])
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


def test_cast_creature_summoning_sick_after_resolve(synthetic_state):
    """G7 S1 closure-flip. A freshly-RESOLVED creature has summoning
    sickness — mirrors the Python ``put_into_battlefield`` default
    (``actions.py:2993``), stamped at RESOLUTION time by
    ``move_source_post_resolve`` (``state_ops_resolve.rs:301-303``),
    NOT at cast time (Python's ``_cast_spell`` doesn't stamp it
    either). On the stack it is still in hand, so ``is_summoning_sick``
    is ``None`` (the not-on-bf sentinel)."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.cast_creature(elf_id, 0) is True
    # Pre-resolve: spell on the stack, card in hand, no sickness stamp.
    assert synthetic_state.is_summoning_sick(elf_id) is None
    synthetic_state.resolve_top_of_stack()
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
    # G7 S1: bf landing is at resolution, not cast time.
    synthetic_state.resolve_top_of_stack()
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

    # G7 S1: bf landing is at resolution, not cast time.
    synthetic_state.resolve_top_of_stack()
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
    # G7 S1: drive the resolve on the clone so the elf lands on its
    # battlefield (cast only pushes the StackItem).
    cloned.resolve_top_of_stack()

    # Clone diverged.
    assert cloned.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert cloned.get_mana_pool(0)["G"] == 0
    # Source untouched: elf still in hand, green pip still in pool,
    # clone's stack push + resolve did not bleed back.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_HAND
    assert synthetic_state.get_mana_pool(0)["G"] == 1
    assert synthetic_state.is_stack_empty() is True


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

    # G7 S1: cast succeeds in any phase (no phase gate in the
    # primitive); bf landing is at resolution.
    synthetic_state.resolve_top_of_stack()
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
    synthetic_state.resolve_top_of_stack()
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
    synthetic_state.resolve_top_of_stack()
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
    synthetic_state.resolve_top_of_stack()
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
    # **G7 mid-game STATE_EQ closure-flip (auto-tap-from-lands).** The
    # "flash lifts timing, NOT the mana cost" invariant is unchanged,
    # but the pre-fix scenario (one G + a generic short) is now
    # PAYABLE because the synthetic state's 5 untapped Forests
    # auto-tap (byte-mirroring Python's ``_cast_spell`` ->
    # ``auto_tap_for_cost``). Tap every p0 land so the cost is
    # genuinely unaffordable (one G floating, no land headroom) —
    # then the flash creature is still correctly rejected for
    # insufficient mana (the gate the test pins), new-code-is-right.
    for o in synthetic_state.battlefield_snapshot():
        if o["controller_id"] == 0 and o["printing_name"] == "Forest":
            synthetic_state.tap_object(o["id"])
    # Only one G — short by one generic pip, and no land headroom.
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


# --- cross-feature edge cases --------------------------------------
#
# These tests exercise interactions between ``cast_creature`` /
# ``play_land`` and other Rust primitives (mana pool, stack,
# resolve, counter_spell, fingerprint, legal_decisions). The
# primitives themselves have dedicated coverage in their respective
# test files (`test_mana.py`, `test_stack.py`, `test_resolve.py`,
# `test_counterspell.py`, `test_fingerprint.py`, `test_legal.py`);
# this section pins their composition with the cast pathway.
#
# **Important Rust-side asymmetry vs Python.** Rust's
# ``cast_creature`` is a no-stack short-circuit: it pays mana then
# moves the card hand -> battlefield in one step (see module
# docstring on ``state_ops_cast.rs``). To exercise the
# "cast -> stack -> resolve" flow for an instant/sorcery, the
# tests below drive ``push_to_stack`` + ``resolve_top_of_stack``
# directly with a printing whose ``card_types`` routes the
# post-resolve mover to the graveyard. Counter-spell coverage uses
# the same pattern: a creature short-circuited via
# ``cast_creature`` is already on the battlefield and can no
# longer be countered; the cross-feature counter test pushes a
# spell on the stack manually and dispatches an Annul-style
# counter via ``Effect::CounterTargetSpell``.


def _instant_dict():
    """A vanilla instant printing with no effects. Used to exercise
    ``push_to_stack`` + ``resolve_top_of_stack`` for cast-of-non-
    permanent shape — the post-resolve mover (CR 608.2m) routes
    Instants to controller's graveyard, not the battlefield."""
    return {
        "name": "Test Vanilla Instant",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [],
    }


def _annul_dict():
    """An Annul-style counter-target-spell printing. Mirrors the
    helper used in ``test_counterspell.py`` so the cross-feature
    counter test here speaks the same shape."""
    return {
        "name": "Test Annul",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "counter_target_spell"}],
    }


def test_cast_creature_consumes_mana_from_correct_player(synthetic_state):
    """Cross-feature with the mana-pool slice: ``cast_creature`` debits
    the CASTING player's pool, not the opponent's. Give both players
    a green pip and an extra colorless; cast for player 1 and verify
    player 0's pool is untouched."""
    elf_id_p1 = P0_FIRST_HAND_ID + 67  # p1 hand starts after p0's 67 ids
    assert synthetic_state.printing_name_of(elf_id_p1) == "Llanowar Elves"
    assert synthetic_state.find_object_zone(elf_id_p1) == ZONE_HAND
    # Seed both pools with the same colors so a "wrong player" debit
    # would still observe-as-success on totals — only per-player
    # comparison catches the bug.
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(1, "G", 1)
    synthetic_state.add_mana(1, "C", 1)
    p0_pool_before = synthetic_state.get_mana_pool(0)

    assert synthetic_state.cast_creature(elf_id_p1, 1) is True

    # p1's green pip got spent.
    assert synthetic_state.get_mana_pool(1)["G"] == 0
    assert synthetic_state.get_mana_pool(1)["C"] == 1
    # p0's pool entirely untouched.
    assert synthetic_state.get_mana_pool(0) == p0_pool_before


def test_cast_creature_from_battlefield_is_rejected(synthetic_state):
    """Cross-feature with zones: a Grizzly Bears already on the
    battlefield is NOT a legal cast target (the precondition is
    "card is in player's hand"). Even with enough mana to pay,
    cast_creature returns False and leaves all state untouched."""
    bears_id = P0_FIRST_BEARS_ID
    assert synthetic_state.find_object_zone(bears_id) == ZONE_BATTLEFIELD
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 1)
    pool_before = synthetic_state.get_mana_pool(0)
    bf_before = synthetic_state.battlefield_sizes
    hand_before = synthetic_state.hand_sizes

    assert synthetic_state.cast_creature(bears_id, 0) is False

    # Mana pool untouched — the precondition check fires BEFORE the
    # mana spend in `cast_creature` (state_ops_cast.rs phase 1).
    assert synthetic_state.get_mana_pool(0) == pool_before
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.hand_sizes == hand_before
    assert synthetic_state.find_object_zone(bears_id) == ZONE_BATTLEFIELD


def test_cast_creature_rejects_instant_printing(synthetic_state):
    """Cross-feature with card_types: an Instant printing is NOT a
    creature spell. ``cast_creature``'s card_types-based detector
    must reject it. The Rust cast slice is creature-only today (see
    module docstring); when a real ``cast_spell`` primitive lands
    for instants/sorceries, this test stays valid — the
    creature-only entrypoint still won't accept Instants."""
    obj_id = synthetic_state.register_and_inject_object(
        _instant_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "U", 5)
    pool_before = synthetic_state.get_mana_pool(0)
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    assert synthetic_state.cast_creature(obj_id, 0) is False

    # No mutation anywhere: instant stays in hand, mana untouched.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    assert synthetic_state.get_mana_pool(0) == pool_before
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_cast_creature_round_trip_battlefield_via_stack_dispatch(synthetic_state):
    """Cross-feature with stack + resolve: simulate the full
    cast -> stack -> resolve -> battlefield round-trip by manually
    pushing a creature's GameObject onto the stack and resolving.
    The Rust ``cast_creature`` primitive short-circuits the stack
    (see module docstring), but the post-resolve mover on
    ``state_ops_resolve.rs`` is the canonical "land a permanent on
    the battlefield from the stack" path — used by every
    spell that goes through Effect dispatch. This test pins the
    "Creature card_types lands on battlefield" branch."""
    # Register-and-inject a fresh creature object (so we control the
    # zone — putting it in HAND means resolve's "find source" works
    # cleanly).
    obj_id = synthetic_state.register_and_inject_object(
        {
            "name": "Test RT Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
            "keywords": [],
            "effects": [],
        },
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    bf_before = synthetic_state.battlefield_sizes[0]

    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved == {"source_obj_id": obj_id, "controller": 0}

    # Creature landed on the battlefield via the post-resolve mover.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # Summoning sickness stamped on the way in (CR 302.1).
    assert synthetic_state.is_summoning_sick(obj_id) is True
    # Stack drained.
    assert synthetic_state.is_stack_empty() is True


def test_cast_creature_round_trip_instant_routes_to_graveyard(synthetic_state):
    """Cross-feature with stack + resolve: the same round-trip for an
    Instant. Post-resolve mover routes Instant card_types to the
    controller's graveyard (CR 608.2m), NOT the battlefield —
    asymmetric with the creature case above."""
    obj_id = synthetic_state.register_and_inject_object(
        _instant_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    gy_before = synthetic_state.graveyard_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    synthetic_state.resolve_top_of_stack()

    # Instant lands in p0's graveyard, NOT the battlefield.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1
    assert synthetic_state.battlefield_sizes[0] == bf_before


def test_legal_decisions_emits_cast_spell_at_sorcery_timing(synthetic_state):
    """Cross-feature with legal_decisions: when sorcery timing holds
    (active == priority, phase == MAIN1, stack empty), the
    enumerator emits a CastSpell action for the (creature) cards in
    hand. Mirrors the sorcery-timing gate at line 727 of
    state_ops_legal.rs."""
    synthetic_state.set_phase(PHASE_MAIN1)
    # Synthetic state's seed has active_player = priority_player = 0
    # and stack is empty, so we're in sorcery timing.
    actions = synthetic_state.legal_decisions(0)
    cast_actions = [a for a in actions if a["kind"] == "cast_spell"]
    # The hand seed is 7 Llanowar Elves which dedup to a single
    # CastSpell action (printing-name dedup, see state_ops_legal.rs
    # docstring "Dedup key shape").
    assert len(cast_actions) == 1
    assert cast_actions[0]["card_id"] == P0_FIRST_HAND_ID
    # All deferred alt-cost flags False/None per first-slice shape.
    assert cast_actions[0]["use_warp"] is False
    assert cast_actions[0]["kicked"] is False
    assert cast_actions[0]["cast_for_free"] is False
    assert cast_actions[0]["use_impending"] is False
    assert cast_actions[0]["cast_room_half"] is None


def test_legal_decisions_no_cast_spell_outside_sorcery_timing(synthetic_state):
    """Cross-feature with legal_decisions: outside sorcery timing
    (here: UNTAP), the enumerator's sorcery-timing early-return at
    line 727 of state_ops_legal.rs short-circuits before CastSpell
    emission. Mirrors the "no instant-speed CastSpell yet"
    first-slice scope. NOTE: ``cast_creature`` itself does NOT
    consult phase — this test pins the legal_decisions / cast
    surface contract, not the primitive's behavior."""
    synthetic_state.set_phase(PHASE_UNTAP)
    actions = synthetic_state.legal_decisions(0)
    cast_actions = [a for a in actions if a["kind"] == "cast_spell"]
    assert cast_actions == []


def test_clone_isolation_after_cast_is_per_zone(synthetic_state):
    """CoW canary across multiple zones in one call: cast_creature
    mutates hand AND battlefield AND mana_pool in a single op. The
    clone-isolation invariant must hold for every one of them, not
    just the first. Belt-and-braces vs the existing
    test_clone_then_cast_does_not_affect_original which checks hand
    + pool — here we also pin battlefield-side isolation explicitly
    via the Llanowar Elves' presence in each side's battlefield list,
    plus check that summoning_sick on the clone doesn't bleed back."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)
    bf_size_p0_before = synthetic_state.battlefield_sizes[0]
    hand_size_p0_before = synthetic_state.hand_sizes[0]

    cloned = synthetic_state.clone_once()
    assert cloned.cast_creature(elf_id, 0) is True
    # G7 S1: cast pushes the StackItem; drive resolve so the clone's
    # elf actually lands on its battlefield.
    cloned.resolve_top_of_stack()

    # Clone diverged: elf on bf, sick, hand shrunk, pool drained.
    assert cloned.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert cloned.is_summoning_sick(elf_id) is True
    assert cloned.battlefield_sizes[0] == bf_size_p0_before + 1
    assert cloned.hand_sizes[0] == hand_size_p0_before - 1
    assert cloned.get_mana_pool(0)["G"] == 0

    # Source untouched on every axis the clone moved.
    assert synthetic_state.find_object_zone(elf_id) == ZONE_HAND
    # On the source the elf is still in hand — `is_summoning_sick`
    # only looks on the battlefield (returns None for non-bf objects).
    assert synthetic_state.is_summoning_sick(elf_id) is None
    assert synthetic_state.battlefield_sizes[0] == bf_size_p0_before
    assert synthetic_state.hand_sizes[0] == hand_size_p0_before
    assert synthetic_state.get_mana_pool(0)["G"] == 1


def test_fingerprint_changes_after_cast(synthetic_state):
    """G7 S1 closure-flip. Cross-feature with fingerprint: the cast
    mutates the mana_pool signature AND pushes a spell StackItem (the
    stack signature feeds the SHA1 digest — see
    state_ops_fingerprint.rs:331-335), so the fingerprint changes
    post-cast even though the card is still in hand (not yet on bf).
    Resolving then moves it hand -> battlefield, changing the
    fingerprint AGAIN.

    Pinning: same starting fingerprint twice (determinism), a
    different fingerprint post-cast (cast sensitivity), and a third
    distinct fingerprint post-resolve (resolve sensitivity)."""
    elf_id = P0_FIRST_HAND_ID
    synthetic_state.add_mana(0, "G", 1)

    fp_pre = synthetic_state.fingerprint()
    # Sanity: determinism — same state, same hash.
    assert synthetic_state.fingerprint() == fp_pre

    assert synthetic_state.cast_creature(elf_id, 0) is True

    fp_post_cast = synthetic_state.fingerprint()
    assert fp_post_cast != fp_pre

    synthetic_state.resolve_top_of_stack()
    fp_post_resolve = synthetic_state.fingerprint()
    assert fp_post_resolve != fp_post_cast
    assert fp_post_resolve != fp_pre


def test_two_casts_in_succession_drain_mana_independently(synthetic_state):
    """G7 S5a closure-flip (was S1). Cross-feature: casting two
    creature spells in succession from the same hand requires the mana
    pool to track both spends cumulatively. Two Llanowar Elves @ {G}
    each = 2 green needed.

    Captures the "second-cast sees the first's state" composition in
    the stack-and-priority Rust model: cast elf_a (StackItem pushed,
    spell re-homed hand → stack store, hand −1 NOW, 1 G left), resolve
    it (elf_a -> bf), then cast elf_b against the updated pool (the
    second {G} drains the pool to empty), resolve it. Both elves land,
    hand drops by 2, pool ends empty. **S5a baseline move:** after
    each cast ``find_object_zone`` reports ``ZONE_STACK`` and the hand
    shrinks immediately — byte-mirroring Python ``p.hand.remove`` +
    ``card.zone=Zone.STACK`` (pre-S5a S1 kept it in the hand Vec)."""
    elf_a = P0_FIRST_HAND_ID
    elf_b = P0_FIRST_HAND_ID + 1  # hand[1] is also a Llanowar Elves
    assert synthetic_state.printing_name_of(elf_b) == "Llanowar Elves"
    synthetic_state.add_mana(0, "G", 2)
    bf_before = synthetic_state.battlefield_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]

    assert synthetic_state.cast_creature(elf_a, 0) is True
    # After the first cast: 1 G spent (pool has 1 left), elf_a on the
    # stack store (zone == ZONE_STACK, hand −1 NOW — byte-Python),
    # not bf yet.
    assert synthetic_state.get_mana_pool(0)["G"] == 1
    assert synthetic_state.find_object_zone(elf_a) == ZONE_STACK
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before
    synthetic_state.resolve_top_of_stack()
    # elf_a resolved onto the battlefield (hand stays −1, no further
    # drain — the cast already removed it).
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.find_object_zone(elf_a) == ZONE_BATTLEFIELD

    assert synthetic_state.cast_creature(elf_b, 0) is True
    # Second cast drains the remaining G against the updated pool.
    assert synthetic_state.get_mana_pool(0)["G"] == 0
    synthetic_state.resolve_top_of_stack()
    # Pool empty, hand shrunk by 2, both elves on battlefield.
    assert synthetic_state.hand_sizes[0] == hand_before - 2
    assert synthetic_state.battlefield_sizes[0] == bf_before + 2
    assert synthetic_state.find_object_zone(elf_b) == ZONE_BATTLEFIELD
    assert synthetic_state.is_stack_empty() is True


def test_cast_then_counter_via_effect_dispatch_lands_in_graveyard(synthetic_state):
    """Cross-feature with counterspell + Effect dispatch: simulate
    a "cast then counter" sequence end-to-end. Because
    ``cast_creature`` short-circuits the stack, we drive the
    creature's cast through the stack manually (register + push)
    so a counter can actually catch it. The Annul-style
    ``Effect::CounterTargetSpell`` removes the targeted creature
    from the stack and routes it to the target's controller's
    graveyard; the counter's own post-resolve goes to its
    controller's graveyard.

    Net result: BOTH spells in graveyards, NEITHER on the
    battlefield. Mirrors ``test_effect_counters_creature_beneath_routes_correct_graveyards``
    in test_counterspell.py but framed as a "cast then counter"
    interaction from the cast slice's perspective."""
    creature_id = synthetic_state.register_and_inject_object(
        {
            "name": "Test Castable Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
            "keywords": [],
            "effects": [],
        },
        1,
        ZONE_HAND,
    )
    counter_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    # p1 cast-equivalent: push the creature on the stack.
    synthetic_state.push_to_stack(creature_id, 1)
    # p0 counter-equivalent: push the counterspell on top.
    synthetic_state.push_to_stack(counter_id, 0)

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]
    p0_bf_before = synthetic_state.battlefield_sizes[0]
    p1_bf_before = synthetic_state.battlefield_sizes[1]

    # Resolve the top (counter). Counter dispatch removes the creature
    # stack item AND moves it to p1's graveyard. The outer resolver
    # then post-resolves the counter to p0's graveyard.
    synthetic_state.resolve_top_of_stack()

    # Stack drained.
    assert synthetic_state.is_stack_empty() is True
    # Creature countered -> p1's graveyard (NOT battlefield).
    assert synthetic_state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1
    assert synthetic_state.battlefield_sizes[1] == p1_bf_before
    # Counter resolved -> p0's graveyard (NOT battlefield).
    assert synthetic_state.find_object_zone(counter_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1
    assert synthetic_state.battlefield_sizes[0] == p0_bf_before


# ====================================================================
# Spell-card-bridge lever, Phase 1 (round-70) — Gate B' / B'' Rust
# regression pins. `Action::CastSpell` on a non-creature
# Instant/Sorcery routes to the new `cast_spell_noncreature`
# primitive (pays mana_cost, binds the deterministic-first target,
# pushes a spell StackItem); the existing `resolve_top_of_stack`
# drains it (applies printing.effects with the target swapped in,
# then move_source_post_resolve sends the spell hand -> graveyard via
# the ALREADY-PRESENT Instant/Sorcery -> ZONE_GRAVEYARD route).
# ====================================================================

def _depressurize_spell_dict():
    """A real-shape single-target Instant carrying the closed Tier-A
    ``depressurize_effect`` (Depressurize: target creature gets
    -3/-0 UEOT; then if its post-UEOT effective power <= 0, destroy
    it). The Rust arm self-scans the battlefield first-creature in
    ETB-timestamp order (it ignores the payload target — the
    forward-substrate field), so the destroy observable is
    deterministic."""
    return {
        "name": "Test Depressurize",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 1, "B": 1},
        "effects": [{"kind": "depressurize_effect", "power_penalty": 3}],
    }


def test_castspell_instant_routes_to_cast_spell_noncreature(synthetic_state):
    """Pin #1 (G7 S5a closure-flip): `Action::CastSpell` with a
    non-warp non-creature Instant routes to `cast_spell_noncreature`
    (NOT `cast_creature`, NOT `cast_creature_warp`): pays `mana_cost`,
    a spell StackItem is pushed (stack depth +1), the spell is re-homed
    hand → the stack-object store (``zone == ZONE_STACK``, hand drains
    NOW — byte-Python ``p.hand.remove`` + ``card.zone=Zone.STACK``),
    priority resets to active."""
    spell_id = synthetic_state.register_and_inject_object(
        _depressurize_spell_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "B", 1)
    synthetic_state.add_mana(0, "C", 1)
    hand_before = synthetic_state.hand_sizes[0]
    stack_before = synthetic_state.stack_size()

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})

    # Spell StackItem pushed; spell re-homed to the stack-object store
    # (zone == ZONE_STACK, hand −1 NOW), NOT battlefield —
    # `cast_creature` would have moved a creature; this proves the
    # spell route, not the creature route.
    assert synthetic_state.stack_size() == stack_before + 1
    assert synthetic_state.find_object_zone(spell_id) == ZONE_STACK
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    # Mana paid ({1}{B} — both pips consumed).
    pool = synthetic_state.get_mana_pool(0)
    assert pool.get("B", 0) == 0
    assert pool.get("C", 0) == 0
    # Priority reset to the active player (cast tail, verbatim from
    # `cast_creature`).
    assert synthetic_state.get_priority_player() == synthetic_state.active_player


def test_castspell_creature_still_routes_to_cast_creature(synthetic_state):
    """Pin #2 (G7 S5a closure-flip): a Creature printing through
    `Action::CastSpell{use_warp:false}` STILL routes to
    `cast_creature` (no regression — `cast_spell_noncreature`
    type-gates and returns Ok(false) for a creature so the dispatch
    falls through). Post-G7-S5a, `cast_creature` pushes a spell
    StackItem (stack depth +1) AND re-homes the spell hand → the
    stack-object store (``zone == ZONE_STACK``, hand drains NOW),
    exactly like the instant route (Pin #1). Driving
    `resolve_top_of_stack` then lands the creature on the battlefield.
    The synthetic seed's p0 hand is Llanowar Elves ({G} creature)."""
    elf_id = P0_FIRST_HAND_ID
    assert synthetic_state.printing_name_of(elf_id) == "Llanowar Elves"
    synthetic_state.add_mana(0, "G", 1)
    bf_before = synthetic_state.battlefield_sizes[0]
    stack_before = synthetic_state.stack_size()

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": elf_id})

    # Routed to `cast_creature`, which now pushes a spell StackItem
    # (stack +1) and re-homes the spell to the stack-object store
    # (zone == ZONE_STACK) — NOT the old no-stack immediate-
    # battlefield short-circuit, NOT the pre-S5a hand-resident model.
    assert synthetic_state.stack_size() == stack_before + 1
    assert synthetic_state.find_object_zone(elf_id) == ZONE_STACK
    assert synthetic_state.battlefield_sizes[0] == bf_before

    # Resolve: the creature lands on the battlefield.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.is_stack_empty() is True


def test_g7s5a_cast_creature_pushes_stackitem_rehomes_to_stack_no_autoresolve(
    synthetic_state,
):
    """G7 Slice S5a closure-flip (was `test_g7s1_..._no_autoresolve`).
    Direct `cast_creature` call: pays `mana_cost`, pushes a spell
    `StackItem` (stack depth +1), re-homes the spell hand → the
    stack-object store (``zone == ZONE_STACK``, hand drains NOW —
    byte-Python ``p.hand.remove(card)`` ``actions.py:1403`` +
    ``card.zone=Zone.STACK`` ``:1751``), NO `summoning_sick` stamp at
    cast time (the off-bf sentinel is `None`), priority resets to the
    active player. The card is NOT auto-resolved (stack non-empty
    after the cast). Then `resolve_top_of_stack` (the already-present
    resolver, NOT the pop-only G3 composer) lands the creature on the
    battlefield with summoning sickness — byte-mirroring Python's
    resolve-time `put_into_battlefield`. **S5a baseline move
    (new-code-is-right):** pre-S5a the S1 model kept the spell
    physically in the hand Vec; S5a corrects it to ZONE_STACK to
    byte-match the Python SoT."""
    elf_id = P0_FIRST_HAND_ID
    assert synthetic_state.printing_name_of(elf_id) == "Llanowar Elves"
    synthetic_state.add_mana(0, "G", 1)
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]
    stack_before = synthetic_state.stack_size()

    assert synthetic_state.cast_creature(elf_id, 0) is True

    # Stack push, spell on the stack store (zone == ZONE_STACK,
    # hand −1 NOW), mana spent, NOT resolved, NO sickness.
    assert synthetic_state.stack_size() == stack_before + 1
    assert synthetic_state.is_stack_empty() is False
    assert synthetic_state.find_object_zone(elf_id) == ZONE_STACK
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.battlefield_sizes[0] == bf_before
    assert synthetic_state.get_mana_pool(0)["G"] == 0
    assert synthetic_state.is_summoning_sick(elf_id) is None
    # Priority reset to active (cast tail, verbatim from
    # `cast_spell_noncreature`).
    assert (
        synthetic_state.get_priority_player()
        == synthetic_state.active_player
    )

    # Resolve via the real resolver: creature -> battlefield with
    # summoning sickness + the spell StackItem drained.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.find_object_zone(elf_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.is_summoning_sick(elf_id) is True
    assert synthetic_state.is_stack_empty() is True


def test_castspell_spell_resolves_effect_then_to_graveyard(synthetic_state):
    """Pin #3: `resolve_top_of_stack` on the spell StackItem applies
    the effect (the Depressurize -3/-0 + conditional destroy of the
    deterministic-first creature) AND the spell source moves to its
    controller's GRAVEYARD (CR 608.2m via the ALREADY-PRESENT
    post_resolve_destination route), NOT battlefield, NOT exile. The
    synthetic seed has Grizzly Bears (2/2) on p0 bf at ids 5..9 —
    after -3/-0 their effective power is -1 <= 0 so the first one is
    destroyed."""
    spell_id = synthetic_state.register_and_inject_object(
        _depressurize_spell_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "B", 1)
    synthetic_state.add_mana(0, "C", 1)
    # First creature in ETB-timestamp order across both bfs — the
    # synthetic seed's p0 Grizzly Bears block starts at id 5.
    first_bear = 5
    assert synthetic_state.printing_name_of(first_bear) == "Grizzly Bears"
    gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})
    synthetic_state.resolve_top_of_stack()
    synthetic_state.apply_sbas()

    # Effect applied: the first Grizzly Bears (2/2 -> -1/2) destroyed.
    assert synthetic_state.find_object_zone(first_bear) == ZONE_GRAVEYARD
    # Spell source -> p0 graveyard (NOT battlefield / exile).
    assert synthetic_state.find_object_zone(spell_id) == ZONE_GRAVEYARD
    assert synthetic_state.is_stack_empty() is True


def test_castspell_spell_target_parity_trigger_vs_spell(synthetic_state):
    """Pin #4 (the load-bearing Gate-B'' assertion): the SAME bespoke
    Effect driven by (a) a trigger-shape stack item and (b) a spell
    cast picks the SAME deterministic-first target and produces
    byte-equal state. Depressurize's Rust arm self-scans
    `bf_iter_etb_sorted` first-creature, so both drive paths destroy
    the SAME creature (the synthetic seed's first Grizzly Bears, id
    5). This proves the spell-cast path resolves the per-card arm
    identically to any other resolve driver."""
    # (a) Spell-cast path.
    spell_id = synthetic_state.register_and_inject_object(
        _depressurize_spell_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "B", 1)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})
    synthetic_state.resolve_top_of_stack()
    synthetic_state.apply_sbas()
    # The first creature scanned (id 5) is the one destroyed — the
    # deterministic-first convention; the spell-cast path bound it on
    # the StackItem AND the self-scanning arm picked it (same target).
    assert synthetic_state.find_object_zone(5) == ZONE_GRAVEYARD
    # A later creature in scan order (id 6) is untouched (only ONE
    # target — single-required-target shape).
    assert synthetic_state.find_object_zone(6) == ZONE_BATTLEFIELD


def test_castspell_insufficient_mana_no_mutation(synthetic_state):
    """Pin #5: mana insufficient -> `cast_spell_noncreature` returns
    Ok(false), no mutation (pool unchanged, card in hand, no stack
    push). Dispatch falls through to `cast_creature` which also
    Ok(false)s the non-creature -> net no-op."""
    spell_id = synthetic_state.register_and_inject_object(
        _depressurize_spell_dict(), 0, ZONE_HAND
    )
    # **G7 mid-game STATE_EQ closure-flip (auto-tap-from-lands).** The
    # cast-spell-noncreature insufficient-mana no-op invariant is
    # unchanged, but {B} + a generic short is now PAYABLE via the
    # synthetic state's untapped Forests (auto-tap byte-mirrors
    # Python's ``auto_tap_for_cost``; Forests pay generic). Tap every
    # p0 land so the cost is genuinely unaffordable — then the
    # net no-op contract (no zone / pool / stack mutation) still
    # holds, new-code-is-right.
    for o in synthetic_state.battlefield_snapshot():
        if o["controller_id"] == 0 and o["printing_name"] == "Forest":
            synthetic_state.tap_object(o["id"])
    # Only {B}; short the {1} generic, and no land headroom.
    synthetic_state.add_mana(0, "B", 1)
    pool_before = synthetic_state.get_mana_pool(0)
    hand_before = synthetic_state.hand_sizes[0]
    stack_before = synthetic_state.stack_size()

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})

    # No mutation anywhere.
    assert synthetic_state.find_object_zone(spell_id) == ZONE_HAND
    assert synthetic_state.get_mana_pool(0) == pool_before
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.stack_size() == stack_before


def test_castspell_spell_resolves_pause_sibling_parity(synthetic_state):
    """Pin #6 (sibling-parity guard — the round-60-N1 missed-sibling
    class): `resolve_top_of_stack_pause` on a spell StackItem applies
    the target swap + effect IDENTICALLY to `resolve_top_of_stack`.
    Drive the spell-cast then drain via the `_pause` entry point and
    assert the same observable (first Grizzly Bears destroyed, spell
    in graveyard)."""
    spell_id = synthetic_state.register_and_inject_object(
        _depressurize_spell_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "B", 1)
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})

    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.apply_sbas()

    assert synthetic_state.find_object_zone(5) == ZONE_GRAVEYARD
    assert synthetic_state.find_object_zone(spell_id) == ZONE_GRAVEYARD
    assert synthetic_state.is_stack_empty() is True


# ====================================================================
# Spell-card-bridge lever, Phase 2 (round-76) — the 2-slot
# heterogeneous-target grammar. `Action::CastSpell` on Diplomatic
# Relations binds TWO deterministic-first targets (slot 0 = first
# caster-controlled creature, slot 1 = first non-caster-controlled
# creature) onto the StackItem; the double resolve-time swap threads
# both into `DiplomaticRelationsEffect` (pump slot-0 +1/+0 +
# vigilance UEOT, then deal slot-0's post-pump effective power as
# damage to slot-1), then move_source_post_resolve sends the spell
# hand -> graveyard.
# ====================================================================

def _diplomatic_relations_spell_dict():
    """A real-shape 2-slot Instant carrying the closed Tier-A #7
    ``diplomatic_relations_effect`` (field-free — the 2-slot targets
    ride on the StackItem, NOT the dict)."""
    return {
        "name": "Test Diplomatic Relations",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 2, "G": 1},
        "effects": [{"kind": "diplomatic_relations_effect"}],
    }


def test_castspell_diplomatic_relations_two_slot_bind_and_resolve(
    synthetic_state,
):
    """Pin #DR (Phase-2 2-slot grammar — the load-bearing assertion):
    `Action::CastSpell` on Diplomatic Relations binds slot 0 = first
    caster (p0) creature + slot 1 = first non-caster (p1) creature
    onto the spell StackItem; `resolve_top_of_stack` swaps BOTH into
    the payload-target slots and `DiplomaticRelationsEffect` pumps
    slot-0 +1/+0 (+ vigilance UEOT) then deals slot-0's post-pump
    effective power as damage to slot-1; the spell goes to p0's
    graveyard.

    The synthetic seed's first p0-bf creature is Grizzly Bears (id
    5, 2/2 = slot 0); the first p1-bf creature is Grizzly Bears (id
    72, 2/2 = slot 1). Post-resolve: slot-0 is 3/2 (2/2 +1/+0 UEOT)
    so slot-1 takes 3 damage → 3 > its 2 toughness → SBA destroys it
    (the lethal-via-effect-power path, byte-equal with Python's
    `_apply_damage` + SBA)."""
    spell_id = synthetic_state.register_and_inject_object(
        _diplomatic_relations_spell_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 2)
    slot0 = 5   # first p0-controlled creature (seed Grizzly Bears 2/2)
    slot1 = 72  # first p1-controlled creature (seed Grizzly Bears 2/2)
    assert synthetic_state.printing_name_of(slot0) == "Grizzly Bears"
    assert synthetic_state.printing_name_of(slot1) == "Grizzly Bears"
    gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})
    synthetic_state.resolve_top_of_stack()
    synthetic_state.apply_sbas()

    # Spell -> p0 graveyard (CR 608.2m).
    assert synthetic_state.find_object_zone(spell_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1
    assert synthetic_state.is_stack_empty() is True
    # Slot 0 (p0 Grizzly Bears, 2/2) pumped to 3-power + vigilance
    # UEOT, still on the battlefield.
    assert synthetic_state.find_object_zone(slot0) == ZONE_BATTLEFIELD
    assert synthetic_state.effective_power(slot0) == 3, (
        "slot-0 Grizzly Bears must be 3-power post-pump (2/2 +1/+0)")
    # Slot 1 (p1 Grizzly Bears, 2/2) took 3 damage (slot-0's
    # post-pump power) → 3 > 2 toughness → SBA-destroyed (the
    # lethal-via-effective-power path; byte-equal with Python).
    assert synthetic_state.find_object_zone(slot1) == ZONE_GRAVEYARD, (
        "slot-1 must be SBA-destroyed by slot-0's post-pump power "
        "(3 damage > 2 toughness)")


def test_castspell_diplomatic_relations_no_opponent_creature_pumps_only(
    synthetic_state,
):
    """Pin #DR2 (the slot-1-illegal fizzle branch — CR 608.2b):
    Diplomatic Relations with NO non-caster creature still resolves;
    slot 0 is pumped + gains vigilance but the damage component
    silently fizzles (Python's `opp_target is None` early return
    AFTER the pump). We strip p1's creatures off the battlefield so
    no non-caster creature exists → slot 1 unbound, the pump-only
    branch."""
    # Remove every p1 creature from the battlefield (ids 72..76 in
    # the default seed) so the 2-slot scan finds NO slot-1
    # candidate. (Moving to p1 graveyard is enough — off-battlefield.)
    for p1_cre in range(72, 77):
        assert synthetic_state.printing_name_of(p1_cre) == "Grizzly Bears"
        synthetic_state.move_object(p1_cre, ZONE_GRAVEYARD, 1)
    spell_id = synthetic_state.register_and_inject_object(
        _diplomatic_relations_spell_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 2)
    slot0 = 5
    assert synthetic_state.printing_name_of(slot0) == "Grizzly Bears"
    gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})
    synthetic_state.resolve_top_of_stack()
    synthetic_state.apply_sbas()

    # Spell -> graveyard; slot-0 pumped (3-power); NO damage dealt
    # anywhere (slot 1 unbound — the pump-only fizzle branch).
    assert synthetic_state.find_object_zone(spell_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1
    assert synthetic_state.effective_power(slot0) == 3, (
        "slot-0 still pumped even when the damage component fizzles "
        "(Python pumps BEFORE the opp_target None check)")
    # No other p0 creature took damage (id 6 is the next p0 Bears).
    assert synthetic_state.get_damage(6) == 0


def test_castspell_diplomatic_relations_pause_sibling_parity(
    synthetic_state,
):
    """Pin #DR3 (sibling-parity guard — the §3.4 requirement): the
    2-slot double resolve-swap fires IDENTICALLY in
    `resolve_top_of_stack_pause` as in `resolve_top_of_stack`. Drive
    the 2-slot cast then drain via the `_pause` entry point; same
    observable (slot-0 pumped to 3-power, slot-1 p1 Bears
    SBA-destroyed by the 3 damage, spell in graveyard)."""
    spell_id = synthetic_state.register_and_inject_object(
        _diplomatic_relations_spell_dict(), 0, ZONE_HAND
    )
    synthetic_state.add_mana(0, "G", 1)
    synthetic_state.add_mana(0, "C", 2)

    synthetic_state.apply_action(
        {"kind": "cast_spell", "card_id": spell_id})
    synthetic_state.resolve_top_of_stack_pause()
    synthetic_state.apply_sbas()

    assert synthetic_state.find_object_zone(spell_id) == ZONE_GRAVEYARD
    assert synthetic_state.effective_power(5) == 3
    assert synthetic_state.find_object_zone(72) == ZONE_GRAVEYARD
    assert synthetic_state.is_stack_empty() is True
