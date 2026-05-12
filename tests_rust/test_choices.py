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
    # Top of library = lib[0] post-CE3 (Python pop(0) convention).
    # p0 library is built as ids 17..66 in push order ⇒ top = 17.
    assert synthetic_state.choose_top_of_library_for_player(0) == 17
    # p1 library: ids 84..133 ⇒ top = 84.
    assert synthetic_state.choose_top_of_library_for_player(1) == 84


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


# --- choose_first_card_in_graveyard_for_player -----------------------
#
# Round-19 extend slice: graveyard / keyword / tapped selectors.
#
# The synthetic-state seed has empty graveyards on both sides
# (``make_player`` initializes ``graveyard: Arc::new(Vec::new())``).
# These tests use ``register_and_inject_object`` with
# ``ZONE_GRAVEYARD = 3`` to seed graveyard contents, and use
# ``tap_object`` to dirty creatures for the tapped selector.


# Scryfall-style printing dicts shared across the new selectors.
_FOREST = {
    "name": "Forest",
    "card_types": ["Land"],
    "mana_cost": {},
    "effects": [],
    "mana_produced": ["G"],
}
_BEARS = {
    "name": "Grizzly Bears",
    "card_types": ["Creature"],
    "mana_cost": {"G": 1, "generic": 1},
    "effects": [],
}
_FLYER = {
    "name": "Wind Drake",
    "card_types": ["Creature"],
    "mana_cost": {"U": 1, "generic": 2},
    "effects": [],
    "keywords": ["flying"],
}
_TRAMPLER = {
    "name": "Rumbling Baloth",
    "card_types": ["Creature"],
    "mana_cost": {"G": 1, "generic": 3},
    "effects": [],
    "keywords": ["trample"],
}

ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def test_choose_first_card_in_graveyard_returns_first_id(engine):
    # Seed two cards into p0's graveyard. The selector should pick
    # the first one (zone[0]) — i.e. the one inserted first.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    first_id = state.register_and_inject_object(_FOREST, 0, ZONE_GRAVEYARD)
    second_id = state.register_and_inject_object(_BEARS, 0, ZONE_GRAVEYARD)
    assert first_id != second_id
    assert state.choose_first_card_in_graveyard_for_player(0) == first_id
    # p1's graveyard is still empty.
    assert state.choose_first_card_in_graveyard_for_player(1) is None


def test_choose_first_card_in_graveyard_empty_returns_none(synthetic_state):
    # The default synthetic state has empty graveyards on both sides.
    assert synthetic_state.choose_first_card_in_graveyard_for_player(0) is None
    assert synthetic_state.choose_first_card_in_graveyard_for_player(1) is None


def test_choose_first_card_in_graveyard_out_of_range_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.choose_first_card_in_graveyard_for_player(99)


# --- choose_first_creature_with_keyword_for_player -------------------


def test_choose_first_creature_with_keyword_finds_match(engine):
    # Layout: [Forest, Bears (no keywords), Wind Drake (flying)].
    # Asking for "flying" returns the Wind Drake.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    state.register_and_inject_object(_FOREST, 0, ZONE_BATTLEFIELD)
    state.register_and_inject_object(_BEARS, 0, ZONE_BATTLEFIELD)
    flyer_id = state.register_and_inject_object(_FLYER, 0, ZONE_BATTLEFIELD)
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "flying")
        == flyer_id
    )


def test_choose_first_creature_with_keyword_no_match_returns_none(engine):
    # Bears + Forest only. Nothing has "flying" → None.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    state.register_and_inject_object(_FOREST, 0, ZONE_BATTLEFIELD)
    state.register_and_inject_object(_BEARS, 0, ZONE_BATTLEFIELD)
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "flying")
        is None
    )


def test_choose_first_creature_with_keyword_zone_order_first_match(engine):
    # Two flyers and a trampler interleaved; the FIRST flyer in
    # zone-order wins, not the trampler (different keyword) and not
    # the second flyer.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    state.register_and_inject_object(_TRAMPLER, 0, ZONE_BATTLEFIELD)
    first_flyer = state.register_and_inject_object(
        _FLYER, 0, ZONE_BATTLEFIELD
    )
    state.register_and_inject_object(_TRAMPLER, 0, ZONE_BATTLEFIELD)
    state.register_and_inject_object(_FLYER, 0, ZONE_BATTLEFIELD)
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "flying")
        == first_flyer
    )


def test_choose_first_creature_with_keyword_lowercases_arg(engine):
    # Caller passes "Flying" (capitalized); the printing's keyword
    # list stores "flying" (lowercase). Helper folds the arg to
    # lowercase before comparison.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    flyer_id = state.register_and_inject_object(_FLYER, 0, ZONE_BATTLEFIELD)
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "Flying")
        == flyer_id
    )
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "FLYING")
        == flyer_id
    )


def test_choose_first_creature_with_keyword_skips_non_creatures(engine):
    # Even if a non-creature printing carried the keyword (it
    # doesn't here — Forest has no keywords), the helper requires
    # card_types to contain "Creature". The Bears (Creature, no
    # keywords) does not match "flying", so the Forest-then-Bears
    # battlefield returns None for "flying".
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    state.register_and_inject_object(_FOREST, 0, ZONE_BATTLEFIELD)
    state.register_and_inject_object(_BEARS, 0, ZONE_BATTLEFIELD)
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "flying")
        is None
    )


def test_choose_first_creature_with_keyword_empty_keyword_matches_no_keywords(engine):
    # Empty keyword arg matches a Creature with an empty keyword
    # list (degenerate but defined). Bears has no keywords, so it
    # matches. Wind Drake has ["flying"], so it does NOT match.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    state.register_and_inject_object(_FLYER, 0, ZONE_BATTLEFIELD)
    bears_id = state.register_and_inject_object(_BEARS, 0, ZONE_BATTLEFIELD)
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "")
        == bears_id
    )


def test_choose_first_creature_with_keyword_out_of_range_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.choose_first_creature_with_keyword_for_player(
            99, "flying"
        )


# --- choose_first_tapped_creature_for_player -------------------------


def test_choose_first_tapped_creature_finds_tapped(synthetic_state):
    # Default synthetic state: p0 bf is [Forest x5, Bears x5] with
    # all tapped == False. Tap the first Bears (id 5) and assert
    # the helper picks it.
    assert synthetic_state.tap_object(5) is True
    assert synthetic_state.choose_first_tapped_creature_for_player(0) == 5


def test_choose_first_tapped_creature_all_untapped_returns_none(synthetic_state):
    # Fresh state, nothing tapped → None.
    assert synthetic_state.choose_first_tapped_creature_for_player(0) is None
    assert synthetic_state.choose_first_tapped_creature_for_player(1) is None


def test_choose_first_tapped_creature_zone_order_first_tapped(synthetic_state):
    # p0 bf creatures are at indices 5..9 (ids 5..9). Tap ids 7
    # and 9; the helper should return the first tapped one in zone
    # order — id 7, not the lower-id-but-later-in-zone case.
    assert synthetic_state.tap_object(9) is True
    assert synthetic_state.tap_object(7) is True
    assert synthetic_state.choose_first_tapped_creature_for_player(0) == 7


def test_choose_first_tapped_creature_skips_tapped_non_creatures(engine):
    # Tap a Forest (Land) AND a Bears (Creature). The helper must
    # skip the tapped Land and pick the tapped Creature.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    forest_id = state.register_and_inject_object(
        _FOREST, 0, ZONE_BATTLEFIELD
    )
    bears_id = state.register_and_inject_object(_BEARS, 0, ZONE_BATTLEFIELD)
    assert state.tap_object(forest_id) is True
    assert state.tap_object(bears_id) is True
    assert (
        state.choose_first_tapped_creature_for_player(0) == bears_id
    )


def test_choose_first_tapped_creature_out_of_range_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.choose_first_tapped_creature_for_player(99)


# --- cross-feature edge cases ----------------------------------------
#
# These cover interactions between the choose_* selectors and the rest
# of the engine's primitives — zone moves, tap/untap, clone CoW,
# fingerprint, and combat-decl bookkeeping. They pin the contract that
# the read-only selectors observe the CURRENT zone state (not a cached
# snapshot) and that CoW-cloned states diverge cleanly once mutated.


def test_choose_after_move_object_battlefield_creature_to_graveyard(synthetic_state):
    # The first creature on p0's battlefield is id 5 (default seed).
    # Move it to the graveyard via move_object — the next selector
    # call should advance to the next creature in zone order (id 6).
    assert synthetic_state.choose_first_creature_for_player(0) == 5
    assert synthetic_state.move_object(5, 3, 0) is True  # ZONE_GRAVEYARD = 3
    assert synthetic_state.choose_first_creature_for_player(0) == 6
    # The moved creature is now the first graveyard card.
    assert synthetic_state.choose_first_card_in_graveyard_for_player(0) == 5


def test_choose_top_of_library_after_draw_card(synthetic_state):
    # Top-of-library convention = lib[0] (post-CE3 Python pop(0)
    # alignment). p0's library top is id 17 by default. draw_card
    # removes lib[0], so the new top should be id 18.
    assert synthetic_state.choose_top_of_library_for_player(0) == 17
    drawn = synthetic_state.draw_card(0)
    assert drawn == 17
    assert synthetic_state.choose_top_of_library_for_player(0) == 18


def test_choose_first_card_in_hand_after_draw(synthetic_state):
    # Default p0 hand[0] = id 10 (Llanowar Elves). draw_card appends
    # the drawn object to the END of the hand, so hand[0] is unchanged.
    assert synthetic_state.choose_first_card_in_hand_for_player(0) == 10
    synthetic_state.draw_card(0)
    # Still id 10 — draw appends, doesn't prepend.
    assert synthetic_state.choose_first_card_in_hand_for_player(0) == 10


def test_choose_first_tapped_creature_after_untap_all(synthetic_state):
    # Tap one creature, then call untap_all_for_player — the selector
    # must return None afterwards because the only tapped creature got
    # untapped. Cross-feature: tap_object + untap_all_for_player +
    # choose_first_tapped_creature.
    assert synthetic_state.tap_object(5) is True
    assert synthetic_state.choose_first_tapped_creature_for_player(0) == 5
    synthetic_state.untap_all_for_player(0)
    assert synthetic_state.choose_first_tapped_creature_for_player(0) is None


def test_choose_clone_isolation_after_mutation(synthetic_state):
    # Clone-replay / CoW canary: cloning then mutating the clone
    # MUST leave the source's selector outputs unchanged. This pins
    # the read-only contract on choose_* against Arc::make_mut
    # behavior on the underlying Vec.
    cloned = synthetic_state.clone_once()
    assert cloned.choose_first_creature_for_player(0) == 5
    # Mutate the clone — move id 5 to the graveyard.
    assert cloned.move_object(5, 3, 0) is True
    # Source still sees id 5; clone advances to id 6.
    assert synthetic_state.choose_first_creature_for_player(0) == 5
    assert cloned.choose_first_creature_for_player(0) == 6


def test_choose_first_creature_with_keyword_unaffected_by_tap(engine):
    # Tapping a creature does not change keyword membership — the
    # selector filters by printing keyword AND card_types, not by
    # tapped state. Cross-feature: tap_object + keyword selector.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    flyer_id = state.register_and_inject_object(_FLYER, 0, ZONE_BATTLEFIELD)
    assert state.tap_object(flyer_id) is True
    # Still returns the (now tapped) flyer — the selector does not
    # filter by tapped.
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "flying")
        == flyer_id
    )


def test_choose_first_creature_after_reanimate(engine):
    # Inject a creature into the graveyard, then reanimate it onto
    # the battlefield. The "first creature" selector picks it up
    # immediately; the graveyard selector stops seeing it. Cross-
    # feature: register_and_inject_object + reanimate primitive +
    # choose selectors.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    bears_id = state.register_and_inject_object(_BEARS, 0, ZONE_GRAVEYARD)
    assert state.choose_first_creature_for_player(0) is None
    assert state.choose_first_card_in_graveyard_for_player(0) == bears_id
    moved = state.move_object_from_graveyard_to_battlefield(0, bears_id)
    assert moved is True
    assert state.choose_first_creature_for_player(0) == bears_id
    assert state.choose_first_card_in_graveyard_for_player(0) is None


def test_choose_first_permanent_skipped_by_creature_selector(engine):
    # Cross-feature: choose_first_permanent picks bf[0] regardless
    # of type; choose_first_creature SKIPS lands and picks the first
    # Creature deeper in the zone. Seed: [Forest, Forest, Bears]
    # — permanent selector returns the Forest at index 0; creature
    # selector returns the Bears at index 2.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    forest_id = state.register_and_inject_object(
        _FOREST, 0, ZONE_BATTLEFIELD
    )
    state.register_and_inject_object(_FOREST, 0, ZONE_BATTLEFIELD)
    bears_id = state.register_and_inject_object(
        _BEARS, 0, ZONE_BATTLEFIELD
    )
    assert state.choose_first_permanent_for_player(0) == forest_id
    assert state.choose_first_creature_for_player(0) == bears_id


def test_choose_determinism_across_repeated_calls(synthetic_state):
    # Determinism canary: repeated read-only selector calls on an
    # unmutated state produce identical outputs. Pins that the
    # selectors are pure functions of state (no internal counters,
    # no first-call caching that could drift).
    snap = (
        synthetic_state.choose_first_creature_for_player(0),
        synthetic_state.choose_first_card_in_hand_for_player(0),
        synthetic_state.choose_top_of_library_for_player(0),
        synthetic_state.choose_first_permanent_for_player(0),
        synthetic_state.choose_first_creature_for_defender(),
    )
    for _ in range(5):
        repeat = (
            synthetic_state.choose_first_creature_for_player(0),
            synthetic_state.choose_first_card_in_hand_for_player(0),
            synthetic_state.choose_top_of_library_for_player(0),
            synthetic_state.choose_first_permanent_for_player(0),
            synthetic_state.choose_first_creature_for_defender(),
        )
        assert repeat == snap


def test_choose_fingerprint_unchanged_by_read_only_selectors(synthetic_state):
    # The choose_* helpers are documented as read-only — calling
    # them must not perturb the gameplay-relevant state, which means
    # the fingerprint stays bit-equal across a call. Cross-feature:
    # fingerprint + every choose selector.
    before = synthetic_state.fingerprint()
    synthetic_state.choose_first_creature_for_player(0)
    synthetic_state.choose_first_card_in_hand_for_player(0)
    synthetic_state.choose_top_of_library_for_player(0)
    synthetic_state.choose_first_permanent_for_player(0)
    synthetic_state.choose_first_creature_for_defender()
    synthetic_state.choose_first_card_in_graveyard_for_player(0)
    synthetic_state.choose_first_creature_with_keyword_for_player(0, "flying")
    synthetic_state.choose_first_tapped_creature_for_player(0)
    after = synthetic_state.fingerprint()
    assert before == after


def test_choose_fingerprint_differs_after_tap_shifts_tapped_selector(synthetic_state):
    # Cross-feature fingerprint canary: tapping a creature shifts
    # both choose_first_tapped_creature's output AND the fingerprint
    # (because tapped is part of the per-object zone signature). Pins
    # that the selector's observable change matches a real state
    # transition, not a no-op.
    before_fp = synthetic_state.fingerprint()
    assert synthetic_state.choose_first_tapped_creature_for_player(0) is None
    assert synthetic_state.tap_object(5) is True
    after_fp = synthetic_state.fingerprint()
    assert after_fp != before_fp
    assert synthetic_state.choose_first_tapped_creature_for_player(0) == 5


def test_choose_first_creature_for_defender_after_active_player_flip(synthetic_state):
    # Cross-feature: choose_first_creature_for_defender is defined
    # as `1 - active_player`. Flipping active_player (via wrap-past-
    # cleanup) MUST flip the selector's output. The default seed
    # produces id 72 (first creature on p1's bf, since active = 0
    # ⇒ defender = 1); after the flip, defender = 0 ⇒ id 5.
    assert synthetic_state.choose_first_creature_for_defender() == 72
    synthetic_state.set_phase(11)  # PHASE_CLEANUP
    synthetic_state.advance_phase()  # wraps, swaps active
    assert synthetic_state.active_player == 1
    assert synthetic_state.choose_first_creature_for_defender() == 5


def test_choose_first_creature_with_keyword_after_inject_into_opponent_bf(engine):
    # Cross-feature controller scoping: a flyer on p1's battlefield
    # must NOT be visible to p0's keyword selector — the selector is
    # per-player. Seeds two separate flyers (one per controller) and
    # checks each side sees only its own.
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=0
    )
    p0_flyer = state.register_and_inject_object(_FLYER, 0, ZONE_BATTLEFIELD)
    p1_flyer = state.register_and_inject_object(_FLYER, 1, ZONE_BATTLEFIELD)
    assert p0_flyer != p1_flyer
    assert (
        state.choose_first_creature_with_keyword_for_player(0, "flying")
        == p0_flyer
    )
    assert (
        state.choose_first_creature_with_keyword_for_player(1, "flying")
        == p1_flyer
    )
