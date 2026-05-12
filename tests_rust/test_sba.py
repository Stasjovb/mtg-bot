"""State-based action (SBA) loop primitives on the Rust ``GameState``.

Ported from ``src/mtg_bot/turn.py::state_based_actions`` /
``_state_based_actions_pass`` and ``CR 704.5`` audit numbering.

**Slice scope: lethal-damage (CR 704.5g) AND 0-toughness (CR 704.5f) SBAs.**

- CR 704.5g — a creature whose marked damage is >= its toughness is
  destroyed (moved to its controller's graveyard).
- CR 704.5f — a creature with toughness 0 (or less) is put into its
  owner's graveyard, regardless of marked damage.

This slice exposes ``apply_sbas() -> int`` (count of destructions
this pass) plus the underlying ``is_lethal(obj_id) -> Option<bool>``
helper. ``apply_sbas`` applies 704.5f BEFORE 704.5g per CR rule order;
in practice the same set of victims gets destroyed but the ordering
is preserved for niche edge cases.

Effective toughness for the 0-toughness check is computed as
``printing.toughness + obj.counters`` (round-3's net-i32 +1/+1 vs
-1/-1 model). A creature with base toughness 1 and a -1/-1 counter
(counters = -1) has effective toughness 0 and dies.

**Out of scope, deferred to future slices:**

- **SBA loop driver / quiescence.** Real MTG checks SBAs simultaneously
  and re-checks until stable. This slice does ONE pass; iteration to
  fixed point is a future slice that integrates apply_sbas into the
  combat / spell-resolution call sites.
- **Order independence / simultaneous destruction.** This slice
  collects all victims first, then moves them — so two creatures both
  past lethal both die in the same call (test below). Real MTG
  semantics around layered toughness modifications + cancellation
  (704.5r) are deferred.
- **Marked damage clearing.** Damage clears at end of turn (CR 514.2),
  NOT on every SBA pass. apply_sbas does NOT zero damage on surviving
  creatures (verified below). For destroyed creatures the damage on
  the now-graveyarded GameObject is left as-is (zone change makes it
  irrelevant; CR 614.12 says marked damage is removed on zone change
  but for this slice we don't bother explicitly zeroing it).
- **Indestructibility / regeneration / planeswalker loyalty / legend
  rule / +1/+1 vs -1/-1 cancellation / saga age / aura on illegal
  target / etc.** All other SBAs from ``_state_based_actions_pass``
  belong to subsequent slices.
- **Battlefield-only.** apply_sbas only inspects battlefield zones;
  damage on non-battlefield objects is ignored (it shouldn't exist
  there in normal play, and the lethal-damage SBA is intrinsically
  battlefield-scoped).

**Composes with prior slices:**
- ``state_ops_damage`` (deal_damage to set up lethal scenarios).
- ``CardPrinting.toughness: Option<i16>`` from the bridge-ext slice.
- ``state_ops_zones::move_object`` for graveyard movement.
"""

from __future__ import annotations

import pytest

# `make_synthetic_state(num_battlefield=10, num_hand=7, num_library=50)`
# lays player 0 out as:
#   battlefield: ids 0..9 (split: ids 0..4 are Forests, 5..9 are
#                          Grizzly Bears — see make_player in state.rs)
#   hand:        ids 10..16 (Llanowar Elves)
#   library:     ids 17..66 (Forests)
# Player 1's range starts at 67 with the same layout.
P0_FIRST_BEAR_ID = 5            # First Grizzly Bears (2/2) on p0 battlefield
P0_SECOND_BEAR_ID = 6
P0_FIRST_FOREST_ID = 0          # First Forest on p0 battlefield (no toughness)
P1_FIRST_BEAR_ID = 67 + 5       # First Bear on p1 battlefield


def test_apply_sbas_no_op_on_clean_state(synthetic_state):
    """Fresh state, no creatures damaged. apply_sbas returns 0
    (no destructions) and battlefield sizes are unchanged."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes
    assert synthetic_state.apply_sbas() == 0
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_apply_sbas_returns_count_of_destructions(synthetic_state):
    """Damage Grizzly Bears (toughness 2) for 2; apply_sbas returns 1
    indicating one creature was destroyed by the lethal-damage SBA."""
    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)
    assert synthetic_state.apply_sbas() == 1


def test_apply_sbas_moves_lethal_creature_to_graveyard(synthetic_state):
    """Damage a 2/2 for 2. apply_sbas moves the dead creature off the
    battlefield and into its controller's graveyard."""
    obj_id = P0_FIRST_BEAR_ID
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    synthetic_state.deal_damage(obj_id, 2)
    assert synthetic_state.apply_sbas() == 1

    # Battlefield shrinks by one, graveyard grows by one — for player 0.
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] - 1
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 1
    # Player 1 untouched.
    assert synthetic_state.battlefield_sizes[1] == bf_before[1]
    assert synthetic_state.graveyard_sizes[1] == gy_before[1]
    # The find_object_zone helper reports the object as graveyarded now.
    # ZONE_GRAVEYARD = 3 (see state_ops_zones.rs).
    assert synthetic_state.find_object_zone(obj_id) == 3


def test_apply_sbas_does_not_clear_non_lethal_damage(synthetic_state):
    """Damage a 2/2 for 1 (non-lethal). apply_sbas leaves the creature
    on the battlefield AND does NOT zero its marked damage. Damage
    clears at end of turn (CR 514.2), not on every SBA pass."""
    obj_id = P0_FIRST_BEAR_ID
    synthetic_state.deal_damage(obj_id, 1)
    assert synthetic_state.apply_sbas() == 0
    # Still on battlefield.
    assert synthetic_state.find_object_zone(obj_id) == 2
    # Damage marker preserved (CR 514.2 — clears at end-of-turn cleanup).
    assert synthetic_state.get_damage(obj_id) == 1


def test_apply_sbas_lethal_creature_damage_post_destruction(synthetic_state):
    """When a lethally-damaged creature is moved to graveyard the
    damage on the destroyed GameObject can either be reset to 0 or
    left as-is — this slice picks "leave as-is" for simplicity (the
    object has left the battlefield so its damage marker is not
    consulted by anything). Document via assertion: the object exists
    in the graveyard after destruction; we don't assert the damage
    value. (CR 614.12 says marked damage is removed on zone change,
    but for SBA scope we treat the marker as ignored once off-
    battlefield.)"""
    obj_id = P0_FIRST_BEAR_ID
    synthetic_state.deal_damage(obj_id, 5)  # overkill
    assert synthetic_state.apply_sbas() == 1
    # Object is in graveyard (zone 3).
    assert synthetic_state.find_object_zone(obj_id) == 3


def test_apply_sbas_handles_multiple_lethal_creatures(synthetic_state):
    """Damage two creatures lethally; apply_sbas returns 2. Both move
    to graveyard in the same call (collect-then-mutate pattern)."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)
    synthetic_state.deal_damage(P0_SECOND_BEAR_ID, 2)

    assert synthetic_state.apply_sbas() == 2
    # Both moved.
    assert synthetic_state.find_object_zone(P0_FIRST_BEAR_ID) == 3
    assert synthetic_state.find_object_zone(P0_SECOND_BEAR_ID) == 3
    # Battlefield -2, graveyard +2.
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] - 2
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 2


def test_apply_sbas_only_affects_creatures_not_lands(synthetic_state):
    """A Forest (no toughness — non-creature land) damaged for 99 is
    NOT destroyed by lethal-damage SBA. Forest stays on battlefield;
    apply_sbas returns 0. The check is gated on
    ``CardPrinting.toughness.is_some()``."""
    forest_id = P0_FIRST_FOREST_ID
    bf_before = synthetic_state.battlefield_sizes

    # Forest has no toughness; deal_damage still works (it's a raw
    # marker on GameObject), but the SBA must not destroy it.
    synthetic_state.deal_damage(forest_id, 99)

    assert synthetic_state.apply_sbas() == 0
    # Forest still on battlefield (zone 2).
    assert synthetic_state.find_object_zone(forest_id) == 2
    assert synthetic_state.battlefield_sizes == bf_before


def test_apply_sbas_creature_with_more_damage_than_toughness_still_destroyed(
    synthetic_state,
):
    """Overkill is fine — a 2/2 with 99 damage marked is still
    destroyed (the predicate is damage >= toughness, not damage ==
    toughness)."""
    obj_id = P0_FIRST_BEAR_ID
    synthetic_state.deal_damage(obj_id, 99)
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == 3


def test_apply_sbas_lethal_creature_on_p1_goes_to_p1_graveyard(
    synthetic_state,
):
    """Symmetric: lethal damage on a player-1 creature moves it to
    player 1's graveyard, not player 0's. The destination follows the
    creature's controller."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    synthetic_state.deal_damage(P1_FIRST_BEAR_ID, 2)
    assert synthetic_state.apply_sbas() == 1

    # Player 1 lost a creature, gained a graveyard entry.
    assert synthetic_state.battlefield_sizes[1] == bf_before[1] - 1
    assert synthetic_state.graveyard_sizes[1] == gy_before[1] + 1
    # Player 0 untouched.
    assert synthetic_state.battlefield_sizes[0] == bf_before[0]
    assert synthetic_state.graveyard_sizes[0] == gy_before[0]


def test_is_lethal_helper_creature_at_threshold(synthetic_state):
    """``is_lethal(obj_id)`` returns Some(True) when damage >= toughness,
    Some(False) when below, and None for non-creatures or unknown ids."""
    bear_id = P0_FIRST_BEAR_ID
    forest_id = P0_FIRST_FOREST_ID

    # Bear at 0 damage: not lethal.
    assert synthetic_state.is_lethal(bear_id) is False

    # Bear at 2 damage (= toughness): lethal.
    synthetic_state.deal_damage(bear_id, 2)
    assert synthetic_state.is_lethal(bear_id) is True

    # Forest (no toughness): always None.
    assert synthetic_state.is_lethal(forest_id) is None

    # Unknown id: None.
    assert synthetic_state.is_lethal(999_999) is None


def test_apply_sbas_no_op_returns_zero_repeatedly(synthetic_state):
    """Calling apply_sbas twice on a clean state returns 0 both times.
    Idempotent on a state with no pending destructions."""
    assert synthetic_state.apply_sbas() == 0
    assert synthetic_state.apply_sbas() == 0


def test_apply_sbas_after_destruction_returns_zero(synthetic_state):
    """After one apply_sbas destroys a creature, calling it again
    returns 0 — there's nothing left to destroy. (No SBA cascade in
    this slice; second call is a true no-op.)"""
    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.apply_sbas() == 0


def test_clone_preserves_sba_pending(synthetic_state):
    """**CoW canary for the SBA path.** Damage a creature on a clone,
    apply_sbas on the clone destroys it, original's battlefield is
    unchanged. Same load-bearing invariant as
    ``test_deal_damage_on_clone_does_not_affect_original`` from the
    damage slice but exercising the destruction path through
    move_object."""
    obj_id = P0_FIRST_BEAR_ID
    bf_before_p0 = synthetic_state.battlefield_sizes[0]
    gy_before_p0 = synthetic_state.graveyard_sizes[0]

    other = synthetic_state.clone_once()
    # Mutate ONLY the clone.
    other.deal_damage(obj_id, 2)
    assert other.apply_sbas() == 1

    # Clone reflects destruction.
    assert other.find_object_zone(obj_id) == 3  # graveyard
    assert other.battlefield_sizes[0] == bf_before_p0 - 1
    assert other.graveyard_sizes[0] == gy_before_p0 + 1

    # Original must NOT see the destruction.
    assert synthetic_state.find_object_zone(obj_id) == 2  # battlefield
    assert synthetic_state.battlefield_sizes[0] == bf_before_p0
    assert synthetic_state.graveyard_sizes[0] == gy_before_p0
    assert synthetic_state.get_damage(obj_id) == 0


# ----------------------------- 0-toughness SBA (CR 704.5f) -----------------
#
# A creature with toughness 0 (or less) is destroyed regardless of marked
# damage. Effective toughness = printed toughness + counters (net-i32
# +1/+1 vs -1/-1 model). A 1/1 with a -1/-1 counter (counters=-1) has
# effective toughness 0 and dies. A 0/0 creature dies on entering a state
# where SBAs are checked.
#
# These tests use ``register_and_inject_object`` from
# ``state_ops_resolve.rs`` to put printings with explicit power/toughness
# onto the battlefield; combined with the ``set_counters`` primitive from
# round-3 that's enough to construct every shape we want to exercise.

ZONE_HAND = 0  # mirrors rust/src/state_ops_zones.rs
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _zero_zero_creature_dict():
    """A printing for a 0/0 creature — dies the moment SBAs check it."""
    return {
        "name": "Test 0/0",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 0,
        "toughness": 0,
        "keywords": [],
        "effects": [],
    }


def test_zero_toughness_creature_dies(synthetic_state):
    """A 1/1 creature with a -1/-1 counter (effective toughness 0) is
    destroyed by ``apply_sbas`` — that's CR 704.5f. The damage marker
    is irrelevant; what matters is effective toughness <= 0."""
    obj_id = P0_FIRST_BEAR_ID  # Grizzly Bears, 2/2
    # Drop net counters to -2 so effective toughness = 2 + (-2) = 0.
    synthetic_state.set_counters(obj_id, -2)
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_negative_toughness_via_counters_dies(synthetic_state):
    """Effective toughness can go strictly negative (more -1/-1 than
    base toughness). 704.5f says toughness 0 OR LESS triggers destruction;
    a 2/2 with -3 net counters (effective toughness -1) is destroyed."""
    obj_id = P0_FIRST_BEAR_ID  # 2/2
    synthetic_state.set_counters(obj_id, -3)  # effective toughness -1
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_creature_with_zero_base_toughness_immediately_dies(synthetic_state):
    """Register a 0/0 creature directly to battlefield (no counters,
    no damage). apply_sbas destroys it via 704.5f — base toughness 0 is
    enough on its own."""
    obj_id = synthetic_state.register_and_inject_object(
        _zero_zero_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_apply_sbas_handles_zero_toughness_alongside_lethal_damage(synthetic_state):
    """One creature dies via 704.5f (0-toughness via counters), another
    via 704.5g (lethal damage). Both go to graveyard in the same
    apply_sbas pass; the count is 2."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes

    # First bear: lethal damage (704.5g).
    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)
    # Second bear: 0 effective toughness via counters (704.5f).
    synthetic_state.set_counters(P0_SECOND_BEAR_ID, -2)

    assert synthetic_state.apply_sbas() == 2

    assert synthetic_state.find_object_zone(P0_FIRST_BEAR_ID) == ZONE_GRAVEYARD
    assert synthetic_state.find_object_zone(P0_SECOND_BEAR_ID) == ZONE_GRAVEYARD
    # Both moved off p0's battlefield, both into p0's graveyard.
    assert synthetic_state.battlefield_sizes[0] == bf_before[0] - 2
    assert synthetic_state.graveyard_sizes[0] == gy_before[0] + 2


def test_apply_sbas_returns_correct_count_with_zero_toughness_destructions(
    synthetic_state,
):
    """A pass that destroys only via 704.5f still returns the destruction
    count — the count tallies 0-toughness victims the same as lethal-damage
    victims. Three creatures, all driven to effective toughness 0 by
    counters → return value 3."""
    for obj_id in (P0_FIRST_BEAR_ID, P0_SECOND_BEAR_ID, P1_FIRST_BEAR_ID):
        synthetic_state.set_counters(obj_id, -2)  # 2/2 -> effective 0
    assert synthetic_state.apply_sbas() == 3
    for obj_id in (P0_FIRST_BEAR_ID, P0_SECOND_BEAR_ID, P1_FIRST_BEAR_ID):
        assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_apply_sbas_positive_counters_save_creature_from_lethal(synthetic_state):
    """Anti-canary: the 0-toughness check must NOT fire on creatures
    with positive net effective toughness. A 2/2 with +1 counters has
    effective toughness 3 — undamaged, survives apply_sbas."""
    obj_id = P0_FIRST_BEAR_ID
    synthetic_state.set_counters(obj_id, 1)
    assert synthetic_state.apply_sbas() == 0
    # Still on battlefield.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_apply_sbas_zero_toughness_does_not_destroy_non_creatures(synthetic_state):
    """A Forest (no toughness) cannot satisfy the 0-toughness check —
    the predicate is gated on ``printing.toughness.is_some()``. Even
    setting a -10 counter on a Forest does not destroy it."""
    forest_id = P0_FIRST_FOREST_ID
    synthetic_state.set_counters(forest_id, -10)
    assert synthetic_state.apply_sbas() == 0
    assert synthetic_state.find_object_zone(forest_id) == ZONE_BATTLEFIELD


# ----------------------------- Indestructible (CR 702.12) ------------------
#
# Indestructible creatures don't die from either of the destruction SBAs
# this slice owns:
# - 704.5g (lethal damage): "destroy" effects (and thus the lethal-damage
#   SBA, which destroys) skip indestructible permanents.
# - 704.5f (0-or-negative toughness): a creature whose toughness is 0 or
#   less is put into its owner's graveyard — but per CR 702.12b, that
#   wording reads "is destroyed", so indestructible creatures are
#   exempt here too.
#
# Indestructible creatures CAN still take damage (the damage marker
# updates), they just don't die from it. Damage clears at end of turn
# via the cleanup-step path. They CAN still be exiled (exile is not
# "destroy"); this slice doesn't change ExileTarget behavior.
#
# Effective-toughness tracking still applies — counters update, the
# damage field updates — only the destruction step is skipped.


def _indestructible_2_2_creature_dict():
    """A 2/2 creature printing with the indestructible keyword."""
    return {
        "name": "Test Indestructible 2/2",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "keywords": ["indestructible"],
        "effects": [],
    }


def _indestructible_1_1_creature_dict():
    """A 1/1 creature printing with the indestructible keyword."""
    return {
        "name": "Test Indestructible 1/1",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "keywords": ["indestructible"],
        "effects": [],
    }


def test_indestructible_creature_with_lethal_damage_survives(synthetic_state):
    """A 2/2 indestructible creature dealt 5 damage is NOT destroyed by
    apply_sbas (CR 702.12 exempts it from 704.5g). The creature stays on
    the battlefield and the damage marker is preserved (damage clears at
    end of turn, not on SBA pass)."""
    obj_id = synthetic_state.register_and_inject_object(
        _indestructible_2_2_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.deal_damage(obj_id, 5)  # overkill on a 2/2

    assert synthetic_state.apply_sbas() == 0
    # Still on battlefield.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    # Damage marker preserved.
    assert synthetic_state.get_damage(obj_id) == 5


def test_indestructible_creature_with_zero_toughness_survives(synthetic_state):
    """A 1/1 indestructible creature with a -1/-1 counter (effective
    toughness 0) is NOT destroyed by apply_sbas — CR 702.12b exempts
    indestructible creatures from 704.5f. The creature stays on the
    battlefield with the counter intact."""
    obj_id = synthetic_state.register_and_inject_object(
        _indestructible_1_1_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.set_counters(obj_id, -1)  # effective toughness 0

    assert synthetic_state.apply_sbas() == 0
    # Still on battlefield.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_indestructible_creature_with_negative_toughness_survives(synthetic_state):
    """An indestructible 2/2 with -3 net counters (effective toughness
    -1) still survives. 702.12b exempts indestructible creatures even
    from strictly negative effective toughness."""
    obj_id = synthetic_state.register_and_inject_object(
        _indestructible_2_2_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.set_counters(obj_id, -3)  # effective toughness -1

    assert synthetic_state.apply_sbas() == 0
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_indestructible_count_returns_zero_for_indestructible_creatures(
    synthetic_state,
):
    """apply_sbas returns 0 destructions when only indestructible
    creatures would otherwise die. Set up two indestructibles past
    lethal, both via different rules; count should still be 0."""
    a = synthetic_state.register_and_inject_object(
        _indestructible_2_2_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    b = synthetic_state.register_and_inject_object(
        _indestructible_1_1_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    # a: lethal damage path
    synthetic_state.deal_damage(a, 9)
    # b: 0-toughness path
    synthetic_state.set_counters(b, -1)

    assert synthetic_state.apply_sbas() == 0
    assert synthetic_state.find_object_zone(a) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(b) == ZONE_BATTLEFIELD


def test_indestructible_does_not_protect_non_indestructible_neighbor(
    synthetic_state,
):
    """Sanity / mixed-pass: an indestructible creature past lethal AND a
    non-indestructible creature past lethal in the same apply_sbas pass.
    Only the non-indestructible one dies; count is 1."""
    indestructible_id = synthetic_state.register_and_inject_object(
        _indestructible_2_2_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.deal_damage(indestructible_id, 5)
    # Vanilla Grizzly Bears (2/2, no keywords) on the synthetic
    # state — kill via lethal damage.
    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)

    assert synthetic_state.apply_sbas() == 1
    # Indestructible survives.
    assert synthetic_state.find_object_zone(indestructible_id) == ZONE_BATTLEFIELD
    # Non-indestructible Grizzly Bear is destroyed.
    assert synthetic_state.find_object_zone(P0_FIRST_BEAR_ID) == ZONE_GRAVEYARD


def test_non_indestructible_creature_with_lethal_still_dies(synthetic_state):
    """Anti-canary: the indestructible carve-out must NOT mistakenly
    spare creatures that happen to share the battlefield with an
    indestructible. A vanilla 2/2 still dies from lethal damage when an
    indestructible 2/2 also exists on the board."""
    # Add an indestructible to the board (no damage, healthy).
    indestructible_id = synthetic_state.register_and_inject_object(
        _indestructible_2_2_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    # Damage a vanilla Grizzly Bear lethally.
    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)

    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(P0_FIRST_BEAR_ID) == ZONE_GRAVEYARD
    # Indestructible was untouched and remains.
    assert synthetic_state.find_object_zone(indestructible_id) == ZONE_BATTLEFIELD


# ----------------------------- SBA loop driver (CR 704.3) ------------------
#
# CR 704.3 — "Whenever a player would get priority [...] the game first
# performs all applicable state-based actions as a single event. [...]
# After SBAs are performed, [...] if any SBAs were performed as a result
# of the check, all applicable SBAs are checked again."
#
# Round-5's apply_sbas is a SINGLE pass. apply_sbas_until_quiescent loops
# until no SBA fires, returning the number of passes that fired. With
# only the destruction SBAs available today (no cascading effects like
# +1/+1 counter on death yet), every realistic scenario completes in
# exactly one pass — but pinning the API now means later slices that
# add cascading effects (sagas advancing on resolve, death triggers,
# etc.) plug into the loop without re-shaping callers.


def test_apply_sbas_until_quiescent_zero_passes_on_clean_state(synthetic_state):
    """No SBAs fire on a clean state -> returns 0 passes. Battlefields
    and graveyards unchanged."""
    bf_before = synthetic_state.battlefield_sizes
    gy_before = synthetic_state.graveyard_sizes
    assert synthetic_state.apply_sbas_until_quiescent() == 0
    assert synthetic_state.battlefield_sizes == bf_before
    assert synthetic_state.graveyard_sizes == gy_before


def test_apply_sbas_until_quiescent_one_pass_kills_lethal(synthetic_state):
    """One lethal-damage creature -> first pass destroys it, second pass
    is a no-op so loop exits. Returns 1 (one pass fired SBAs)."""
    obj_id = P0_FIRST_BEAR_ID
    synthetic_state.deal_damage(obj_id, 2)
    assert synthetic_state.apply_sbas_until_quiescent() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_apply_sbas_until_quiescent_one_pass_kills_multiple(synthetic_state):
    """Three lethal-damage creatures -> all die in pass 1 (CR 704.3
    says SBAs check simultaneously). Returns 1 (one pass, three
    deaths)."""
    for obj_id in (P0_FIRST_BEAR_ID, P0_SECOND_BEAR_ID, P1_FIRST_BEAR_ID):
        synthetic_state.deal_damage(obj_id, 2)
    assert synthetic_state.apply_sbas_until_quiescent() == 1
    for obj_id in (P0_FIRST_BEAR_ID, P0_SECOND_BEAR_ID, P1_FIRST_BEAR_ID):
        assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_apply_sbas_until_quiescent_handles_zero_toughness(synthetic_state):
    """A 0-toughness creature (round-12 SBA) is destroyed in one pass.
    Returns 1."""
    obj_id = P0_FIRST_BEAR_ID  # 2/2
    synthetic_state.set_counters(obj_id, -2)  # effective toughness 0
    assert synthetic_state.apply_sbas_until_quiescent() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_apply_sbas_until_quiescent_combined_lethal_and_zero_toughness(
    synthetic_state,
):
    """One lethal-damage creature AND one 0-toughness creature -> both
    die in pass 1 (single apply_sbas pass kills both). Returns 1."""
    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)
    synthetic_state.set_counters(P0_SECOND_BEAR_ID, -2)
    assert synthetic_state.apply_sbas_until_quiescent() == 1
    assert synthetic_state.find_object_zone(P0_FIRST_BEAR_ID) == ZONE_GRAVEYARD
    assert synthetic_state.find_object_zone(P0_SECOND_BEAR_ID) == ZONE_GRAVEYARD


def test_apply_sbas_until_quiescent_clone_isolation(synthetic_state):
    """CoW canary for the loop primitive — running it on a clone does
    not affect the original."""
    obj_id = P0_FIRST_BEAR_ID
    bf_before_p0 = synthetic_state.battlefield_sizes[0]
    gy_before_p0 = synthetic_state.graveyard_sizes[0]

    other = synthetic_state.clone_once()
    other.deal_damage(obj_id, 2)
    assert other.apply_sbas_until_quiescent() == 1

    # Clone reflects destruction.
    assert other.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert other.battlefield_sizes[0] == bf_before_p0 - 1
    assert other.graveyard_sizes[0] == gy_before_p0 + 1

    # Original is untouched.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before_p0
    assert synthetic_state.graveyard_sizes[0] == gy_before_p0


def test_apply_sbas_until_quiescent_indestructible_skipped(synthetic_state):
    """A round-13 indestructible 2/2 with lethal damage stays alive;
    no SBA fires so the loop returns 0."""
    obj_id = synthetic_state.register_and_inject_object(
        _indestructible_2_2_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.deal_damage(obj_id, 5)  # overkill on a 2/2 indestructible
    assert synthetic_state.apply_sbas_until_quiescent() == 0
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


# ----------------------------- Counter-modified toughness for 704.5g --------
#
# The lethal-damage SBA (CR 704.5g) compares marked damage against EFFECTIVE
# toughness, not printed toughness. Effective toughness folds in the +1/+1
# vs -1/-1 counter contribution: ``printing.toughness + obj.counters`` for
# the round-2 net-i32 model.
#
# Round-5's apply_sbas originally used the raw printed value, which drifts
# from real MTG once counters land on the creature: a 2/2 with two +1/+1
# counters takes 3 damage and survives (effective toughness 4); a 4/4 with
# two -1/-1 counters takes 3 damage and dies (effective toughness 2). The
# round-12 0-toughness SBA (704.5f) has always used effective toughness
# since it landed; this group of tests pins the same semantics into 704.5g.
#
# Pre-existing tests (no-counter cases) still pass under the upgraded
# predicate — when ``obj.counters == 0`` effective and printed toughness
# coincide.


def _two_two_creature_dict():
    """Vanilla 2/2 creature printing — no keywords, no special effects."""
    return {
        "name": "Test 2/2",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "keywords": [],
        "effects": [],
    }


def _four_four_creature_dict():
    """Vanilla 4/4 creature printing — no keywords, no special effects."""
    return {
        "name": "Test 4/4",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4},
        "power": 4,
        "toughness": 4,
        "keywords": [],
        "effects": [],
    }


def _six_six_creature_dict():
    """Vanilla 6/6 creature printing — no keywords, no special effects."""
    return {
        "name": "Test 6/6",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 6},
        "power": 6,
        "toughness": 6,
        "keywords": [],
        "effects": [],
    }


def test_sba_lethal_damage_uses_counter_modified_toughness_increased(
    synthetic_state,
):
    """A 2/2 with +2 net counters (effective toughness 4) takes 3 damage —
    NOT lethal under counter-modified semantics. Creature survives. Pins
    the upgraded 704.5g predicate against the raw-printed-toughness
    regression."""
    obj_id = P0_FIRST_BEAR_ID  # Grizzly Bears, 2/2
    synthetic_state.set_counters(obj_id, 2)  # effective toughness 2 + 2 = 4
    synthetic_state.deal_damage(obj_id, 3)
    assert synthetic_state.apply_sbas() == 0
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_sba_lethal_damage_uses_counter_modified_toughness_decreased(
    synthetic_state,
):
    """A 4/4 with -2 net counters (effective toughness 2) takes 3 damage —
    IS lethal under counter-modified semantics. Without the upgrade,
    raw toughness 4 would mean 3 < 4 and the creature would survive
    (the raw-toughness regression). Effective toughness 2 means 3 >= 2,
    and the creature dies."""
    obj_id = synthetic_state.register_and_inject_object(
        _four_four_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.set_counters(obj_id, -2)  # effective toughness 4 - 2 = 2
    synthetic_state.deal_damage(obj_id, 3)
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_sba_lethal_damage_pre_existing_passes(synthetic_state):
    """Pin the no-counter case: a 2/2 with 0 counters and 2 damage still
    dies. The upgraded predicate must reduce to the printed-toughness
    behavior when counters == 0."""
    obj_id = P0_FIRST_BEAR_ID
    synthetic_state.deal_damage(obj_id, 2)
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_sba_zero_toughness_pre_existing_passes(synthetic_state):
    """Pin the printed-zero-toughness case: a 0/0 creature dies on the
    first SBA pass via 704.5f, even with no counters and no damage.
    Independent of the 704.5g upgrade (the slice doesn't touch this
    path) but documented here as a baseline canary."""
    obj_id = synthetic_state.register_and_inject_object(
        _zero_zero_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD


def test_sba_negative_counters_dont_kill_high_toughness(synthetic_state):
    """Anti-canary: a 6/6 with -2 net counters (effective toughness 4) and
    no damage doesn't trigger ANY destruction SBA. The 704.5f check sees
    effective 4 > 0; the 704.5g check sees damage 0 < 4; both pass.
    Apply_sbas returns 0."""
    obj_id = synthetic_state.register_and_inject_object(
        _six_six_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.set_counters(obj_id, -2)  # effective toughness 4
    assert synthetic_state.apply_sbas() == 0
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD


def test_sba_clone_isolation_with_counters(synthetic_state):
    """CoW canary for the counter-modified 704.5g path. Damage and
    counter-set on a CLONE drives the clone's creature past effective
    toughness; apply_sbas on the clone destroys it; the original is
    untouched (battlefield, graveyard, damage, counters all unchanged)."""
    obj_id = P0_FIRST_BEAR_ID  # Grizzly Bears, 2/2
    bf_before_p0 = synthetic_state.battlefield_sizes[0]
    gy_before_p0 = synthetic_state.graveyard_sizes[0]

    other = synthetic_state.clone_once()
    # On the clone: drop to effective toughness 1 with -1 net counter,
    # deal 1 damage. Lethal under counter-modified 704.5g (1 >= 1).
    other.set_counters(obj_id, -1)
    other.deal_damage(obj_id, 1)
    assert other.apply_sbas() == 1

    # Clone reflects destruction.
    assert other.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert other.battlefield_sizes[0] == bf_before_p0 - 1
    assert other.graveyard_sizes[0] == gy_before_p0 + 1

    # Original is untouched: still on battlefield, no damage, no counters.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before_p0
    assert synthetic_state.graveyard_sizes[0] == gy_before_p0
    assert synthetic_state.get_damage(obj_id) == 0
    assert synthetic_state.get_counters(obj_id) == 0


# ----------------------------- Cross-feature: SBA + Effect interactions -----
#
# Composes the SBA primitives (round-5 lethal, round-12 0-toughness,
# round-13 indestructible exemption, round-15 apply_sbas_until_quiescent,
# round-16 counter-aware effective toughness) with the post-round-3
# Effect arms — DealDamage, DealDamageAnyTarget, DamageEachCreature,
# AddCounters, Sacrifice. The Effect arms write the damage / counter /
# zone state that SBAs then react to; the integration boundary is the
# caller's responsibility (Effects don't auto-invoke SBAs — the test
# resolves the spell, then calls apply_sbas / apply_sbas_until_quiescent
# explicitly). This mirrors how the spell-resolution call site will run
# the SBA loop after each top-of-stack resolve once those pieces wire
# together in a later slice.
#
# All printing dicts here follow the round-3 bridge parser schema
# established in test_resolve.py (kind / amount / count / target).


def _bombard_any_creature_dict(amount):
    """A DealDamage{any_creature, amount} sorcery — Bombard-shaped."""
    return {
        "name": "Test Bombard AnyCreature",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _deal_damage_any_target_dict(amount):
    """A DealDamageAnyTarget{amount} sorcery — Debris Field Crusher-shaped.
    Hits the FIRST creature on defender's bf (skipping lands)."""
    return {
        "name": "Test AnyTarget Bolt",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 2},
        "effects": [{"kind": "deal_damage_any_target", "amount": amount}],
    }


def _pyroclasm_dict(amount):
    """A DamageEachCreature{amount} sorcery — Pyroclasm-shaped. Hits
    every creature on every player's bf symmetrically."""
    return {
        "name": "Test Pyroclasm SBA",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [{"kind": "damage_each_creature", "amount": amount}],
    }


def _wither_dict(amount):
    """An AddCounters{any_creature, amount} instant — wither/infect-shaped.
    Negative ``amount`` rides the same net-i32 counter field."""
    return {
        "name": "Test Wither SBA",
        "card_types": ["Instant"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "add_counters",
                "count": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _altar_sacrifice_dict():
    """A Sacrifice{any_creature} sorcery — Altar's Reap-shaped. Sacrifices
    the FIRST creature on the ACTIVE player's bf (asymmetric vs the
    damage / counter arms which target the defender)."""
    return {
        "name": "Test Altar Sacrifice SBA",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "sacrifice",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _indestructible_2_2_dict():
    """A 2/2 indestructible vanilla creature printing — round-13 SBA
    exemption canary."""
    return {
        "name": "Test Indestructible 2/2 cross",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "keywords": ["indestructible"],
        "effects": [],
    }


def test_sba_after_deal_damage_any_creature_destroys_target(engine):
    """DealDamage{any_creature, 10} resolves onto the smallest-index
    object on the defender's battlefield. To make the smallest-index
    pick a creature (so the damage lands somewhere SBA cares about),
    build a fresh empty-battlefield state and inject a vanilla 2/2 on
    p1 as bf[0]. Resolve the spell -> 10 damage marked. Then
    apply_sbas_until_quiescent destroys it via the round-5 lethal-
    damage path (10 >= toughness 2)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    creature_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _bombard_any_creature_dict(amount=10), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Pre-SBA: creature has 10 damage, still on battlefield.
    assert state.get_damage(creature_id) == 10
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD

    # SBA loop drains it (round-5 lethal-damage path).
    passes = state.apply_sbas_until_quiescent()
    assert passes == 1
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD


def test_sba_after_deal_damage_any_target_destroys_first_creature(
    synthetic_state,
):
    """DealDamageAnyTarget{3} on the seeded state picks the FIRST
    CREATURE (not just bf[0]) on p1's battlefield — that's obj_id 72
    (Bears, 2/2). 3 damage > 2 toughness -> lethal. SBA destroys it."""
    target_id = P1_FIRST_BEAR_ID  # 72, first Bears on p1
    spell_id = synthetic_state.register_and_inject_object(
        _deal_damage_any_target_dict(amount=3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.get_damage(target_id) == 3
    assert synthetic_state.find_object_zone(target_id) == ZONE_BATTLEFIELD

    assert synthetic_state.apply_sbas_until_quiescent() == 1
    assert synthetic_state.find_object_zone(target_id) == ZONE_GRAVEYARD


def test_sba_after_damage_each_creature_kills_all_non_indestructible(
    synthetic_state,
):
    """DamageEachCreature{2} marks 2 damage on every creature on both
    bfs (10 Bears total: 5 on p0 + 5 on p1, ids 5-9 and 72-76). All
    are 2/2 vanilla -> all 10 lethal. SBA loop destroys all 10 in one
    pass. Forests (lands) untouched by both Effect and SBA."""
    spell_id = synthetic_state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Pre-SBA: all 10 Bears at damage=2, still on battlefield.
    bear_ids = (5, 6, 7, 8, 9, 72, 73, 74, 75, 76)
    for bid in bear_ids:
        assert synthetic_state.get_damage(bid) == 2
        assert synthetic_state.find_object_zone(bid) == ZONE_BATTLEFIELD

    assert synthetic_state.apply_sbas_until_quiescent() == 1
    for bid in bear_ids:
        assert synthetic_state.find_object_zone(bid) == ZONE_GRAVEYARD
    # Forests untouched.
    for land_id in (0, 1, 2, 3, 4, 67, 68, 69, 70, 71):
        assert synthetic_state.find_object_zone(land_id) == ZONE_BATTLEFIELD


def test_sba_after_damage_each_creature_spares_indestructibles(engine):
    """DamageEachCreature{2} damages every creature on every bf
    (including indestructibles — the Effect arm doesn't filter; round-13
    indestructible is honored at SBA time). After the AOE: vanilla 2/2
    dies, indestructible 2/2 survives with damage=2 marker preserved."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    vanilla_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    indest_id = state.register_and_inject_object(
        _indestructible_2_2_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _pyroclasm_dict(amount=2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Both creatures took 2 damage.
    assert state.get_damage(vanilla_id) == 2
    assert state.get_damage(indest_id) == 2

    # SBA: vanilla dies, indestructible survives.
    assert state.apply_sbas_until_quiescent() == 1
    assert state.find_object_zone(vanilla_id) == ZONE_GRAVEYARD
    assert state.find_object_zone(indest_id) == ZONE_BATTLEFIELD
    # Damage marker on the indestructible is preserved (clears at
    # cleanup-step, not on SBA).
    assert state.get_damage(indest_id) == 2


def test_sba_after_negative_counters_destroys_via_zero_toughness(engine):
    """AddCounters{any_creature, -2} on a fresh-state board where bf[0]
    is a 2/2 Creature -> -2 net counters -> effective toughness 2 + (-2)
    = 0. Round-12 0-toughness SBA (704.5f) destroys it. The default
    synthetic state's defender bf[0] is a Forest (no toughness) so we
    build a custom state to make the smallest-index pick a creature."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    creature_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _wither_dict(amount=-2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Counter applied: net = -2, effective toughness = 2 - 2 = 0.
    assert state.get_counters(creature_id) == -2
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD

    # Round-12 0-toughness SBA fires.
    assert state.apply_sbas_until_quiescent() == 1
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD


def test_sba_indestructible_survives_negative_counters_zero_toughness(engine):
    """An indestructible 2/2 hit with AddCounters{-2} has effective
    toughness 0 -> 704.5f WOULD destroy a normal creature, but round-13
    exempts indestructible from BOTH 704.5g (damage) AND 704.5f
    (0-toughness). The creature survives with counters=-2 intact."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indest_id = state.register_and_inject_object(
        _indestructible_2_2_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _wither_dict(amount=-2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Counter applied to indestructible: effective toughness 0.
    assert state.get_counters(indest_id) == -2

    # SBA does nothing (round-13 exemption covers 704.5f too).
    assert state.apply_sbas_until_quiescent() == 0
    assert state.find_object_zone(indest_id) == ZONE_BATTLEFIELD
    assert state.get_counters(indest_id) == -2


def test_sba_indestructible_survives_deal_damage_lethal(engine):
    """DealDamage{any_creature, 10} resolves on an indestructible 2/2 ->
    damage=10 marker, lethal under 704.5g for a vanilla creature.
    Round-13 indestructible exempts it; SBA doesn't fire, creature
    stays on the battlefield, damage marker preserved."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indest_id = state.register_and_inject_object(
        _indestructible_2_2_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _bombard_any_creature_dict(amount=10), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    assert state.get_damage(indest_id) == 10
    assert state.apply_sbas_until_quiescent() == 0
    assert state.find_object_zone(indest_id) == ZONE_BATTLEFIELD
    assert state.get_damage(indest_id) == 10


def test_sba_loop_converges_after_stacked_damage_effects(engine):
    """Stack multiple DealDamageAnyTarget{2} spells onto two creatures
    (resolve them sequentially), then run apply_sbas_until_quiescent
    once. Verifies (a) the loop reaches quiescence in ONE pass when
    Effects pre-populate damage but don't cascade through SBAs (no
    death-triggered new damage in scope), and (b) all destroyed
    creatures end up in graveyards. No infinite loop."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    a = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    b = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    # First Bolt: hits a (smallest-index creature).
    spell1 = state.register_and_inject_object(
        _deal_damage_any_target_dict(amount=2), 0, ZONE_HAND
    )
    state.push_to_stack(spell1, 0)
    state.resolve_top_of_stack()
    # Damage a directly via deal_damage so both end up lethal pre-SBA
    # (DealDamageAnyTarget picks the smallest-index creature, so two
    # casts would both hit a).
    state.deal_damage(b, 2)

    assert state.get_damage(a) == 2
    assert state.get_damage(b) == 2
    assert state.find_object_zone(a) == ZONE_BATTLEFIELD
    assert state.find_object_zone(b) == ZONE_BATTLEFIELD

    # Single pass kills both (collect-then-mutate semantics from round-5).
    assert state.apply_sbas_until_quiescent() == 1
    assert state.find_object_zone(a) == ZONE_GRAVEYARD
    assert state.find_object_zone(b) == ZONE_GRAVEYARD


def test_sacrifice_effect_moves_to_graveyard_without_sba(synthetic_state):
    """Sacrifice moves a creature to graveyard directly via the Effect
    arm (round-14) — no SBA-mediated lethal damage involved. The
    creature ends up in graveyard regardless of its damage / counters
    state. SBA after the sacrifice is a no-op (the target is no longer
    on the battlefield, so no SBA predicate applies to it)."""
    target_obj_id = 0  # p0's bf[0]
    spell_id = synthetic_state.register_and_inject_object(
        _altar_sacrifice_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Target sacrificed by Effect arm.
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD
    # SBA finds nothing to do (target already off bf).
    assert synthetic_state.apply_sbas_until_quiescent() == 0
    assert synthetic_state.find_object_zone(target_obj_id) == ZONE_GRAVEYARD


def test_sba_lethal_damage_plus_negative_counters_single_destruction(engine):
    """A creature has BOTH lethal damage (704.5g would fire) AND -1/-1
    net counters bringing effective toughness <= 0 (704.5f would fire).
    apply_sbas_until_quiescent must NOT double-destroy or hang on a
    dispatch loop — the creature lands in graveyard exactly once, in
    a single pass. Counter-aware toughness (round-16) makes 704.5g
    fire even harder (damage 1 >= effective toughness 1) but the
    collect-then-mutate pattern from round-5 deduplicates."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    creature_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    # Apply both predicates: -1 net counter (effective toughness 1)
    # AND 1 damage (>= effective toughness 1 -> lethal under 704.5g).
    state.set_counters(creature_id, -1)
    state.deal_damage(creature_id, 1)

    p1_gy_before = state.graveyard_sizes[1]

    # Single pass; both predicates point at the same creature; one
    # destruction recorded.
    passes = state.apply_sbas_until_quiescent()
    assert passes == 1
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    # Graveyard grew by exactly 1 — no double-move.
    assert state.graveyard_sizes[1] == p1_gy_before + 1


def test_damage_clears_at_cleanup_so_sba_does_not_re_destroy(synthetic_state):
    """A DealDamageAnyTarget{1} survives on a 2/2 (1 < 2 effective
    toughness). Run apply_sbas — no destruction. Run cleanup step —
    damage zeroes (CR 514.2). Run apply_sbas again — still no
    destruction. The damage clearing happens BEFORE the next round's
    SBA pass so the creature doesn't get re-destroyed by stale damage.

    Documents the cleanup-step / SBA interaction: cleanup clears
    damage globally; subsequent SBA passes see a clean board."""
    target_id = P1_FIRST_BEAR_ID  # 2/2 Bears
    spell_id = synthetic_state.register_and_inject_object(
        _deal_damage_any_target_dict(amount=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Non-lethal damage applied.
    assert synthetic_state.get_damage(target_id) == 1

    # SBA: no destruction (1 < 2).
    assert synthetic_state.apply_sbas_until_quiescent() == 0
    assert synthetic_state.find_object_zone(target_id) == ZONE_BATTLEFIELD
    # Damage marker preserved (CR 514.2 — clears at end-of-turn cleanup).
    assert synthetic_state.get_damage(target_id) == 1

    # Cleanup step (CR 514.2): clears all marked damage on both bfs.
    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["damage_cleared"] >= 1
    assert synthetic_state.get_damage(target_id) == 0

    # Second SBA pass: nothing to destroy, no re-destroy.
    assert synthetic_state.apply_sbas_until_quiescent() == 0
    assert synthetic_state.find_object_zone(target_id) == ZONE_BATTLEFIELD


def test_sba_after_pyroclasm_mixed_indestructible_partial_kill(engine):
    """Composition stress: Pyroclasm-3 on a mixed board of vanilla 2/2s
    (lethal -> die) and indestructible 2/2s (lethal but indestructible
    -> survive). Verifies the round-13 carve-out propagates correctly
    through the round-18 DamageEachCreature symmetric AOE. The pass
    count is 1; only the vanilla dies; the indestructible keeps its
    damage marker."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    vanilla_a = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    indest_a = state.register_and_inject_object(
        _indestructible_2_2_dict(), 0, ZONE_BATTLEFIELD
    )
    vanilla_b = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    indest_b = state.register_and_inject_object(
        _indestructible_2_2_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _pyroclasm_dict(amount=3), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Pyroclasm hit every creature on every bf (Effect arm does NOT
    # filter on indestructible — round-13 lives at SBA time).
    for cid in (vanilla_a, indest_a, vanilla_b, indest_b):
        assert state.get_damage(cid) == 3

    # SBA pass: vanillas die, indestructibles survive.
    assert state.apply_sbas_until_quiescent() == 1
    assert state.find_object_zone(vanilla_a) == ZONE_GRAVEYARD
    assert state.find_object_zone(vanilla_b) == ZONE_GRAVEYARD
    assert state.find_object_zone(indest_a) == ZONE_BATTLEFIELD
    assert state.find_object_zone(indest_b) == ZONE_BATTLEFIELD


# ----------------------------- CE5 closure: SBA victim collection -----------
#
# `collect_sba_victims` walks the battlefield in ETB-timestamp order
# (matching Python's centralized `state.battlefield` walk in
# `turn.py:1242`) via the shared `crate::bf_iter::bf_iter_etb_sorted`
# helper. Pre-CE5 the Rust side walked p0-then-p1, which diverged from
# Python whenever ETB timestamps interleaved across players.
#
# The tie-break invariant: synthetic-state objects all carry
# `etb_timestamp == 0` (because `make_player` populates the bf without
# calling `reserve_etb_timestamp`); the helper's stable sort preserves
# the pre-CE5 p0-then-p1, insertion-order walk for those, so every
# pre-existing test in this file (which exclusively constructs state
# via `make_synthetic_state` or `register_and_inject_object` injecting
# into a *single* player at a time) stays bit-equal.
#
# These regression tests use `register_and_inject_object` to drive
# strictly-monotonic ETB stamps across both players. Each injection
# into ZONE_BATTLEFIELD bumps `state.next_etb_timestamp` (see
# `state_ops_resolve.rs:5178`), so we can build interleaved-timestamp
# states by injecting alternately into p0 and p1.


def test_collect_sba_victims_walks_etb_order_across_players(engine):
    """Build a state via `register_and_inject_object` with ETB
    timestamps strictly interleaved across players (p0 first, then p1,
    then p0). Damage all three lethally. `apply_sbas` must destroy
    them in ETB-timestamp order, NOT p0-batch then p1-batch. The
    observable: each player's graveyard receives its dead creatures in
    the order they died, and the controllers' graveyard order matches
    the ETB-stamp order projected onto that player.

    Specifically: p0_a (ts=0), p1_a (ts=1), p0_b (ts=2). Pre-CE5,
    p0's graveyard would receive [p0_a, p0_b] in that order and p1's
    would receive [p1_a] — same dead sets — but the collection order
    of victims would be (p0_a, p0_b, p1_a). Post-CE5, the collection
    order is (p0_a, p1_a, p0_b), which still pushes p0_a then p0_b
    onto p0's graveyard and p1_a onto p1's graveyard. So per-graveyard
    contents stay bit-equal — what we can pin instead is that BOTH
    graveyards' contents match the per-player projection of the ETB
    order. (The collection order change becomes observable downstream
    in CE8's trigger emitter, which we don't have yet.)"""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    p0_a = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_a = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    p0_b = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )

    # Damage all three lethally.
    for cid in (p0_a, p1_a, p0_b):
        state.deal_damage(cid, 2)

    assert state.apply_sbas() == 3
    for cid in (p0_a, p1_a, p0_b):
        assert state.find_object_zone(cid) == ZONE_GRAVEYARD

    # Per-graveyard contents: p0 has both p0_a and p0_b; p1 has p1_a.
    p0_gy = [d["id"] for d in state.graveyard_snapshot(0)]
    p1_gy = [d["id"] for d in state.graveyard_snapshot(1)]
    assert p0_gy == [p0_a, p0_b]
    assert p1_gy == [p1_a]


def test_collect_sba_victims_etb_order_same_player_interleave(engine):
    """Two creatures on p0's battlefield with an interleaved p1 ETB
    between them. The same-player projection through the ETB-ordered
    walk preserves (p0_a, p0_b) ordering — pre- and post-CE5 the
    p0 graveyard receives them in the same relative order. This pins
    the no-regression case (same-player projection stays stable)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    p0_a = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    _p1_a = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    p0_b = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )

    # Damage only the p0 creatures lethally.
    state.deal_damage(p0_a, 2)
    state.deal_damage(p0_b, 2)

    assert state.apply_sbas() == 2
    p0_gy = [d["id"] for d in state.graveyard_snapshot(0)]
    assert p0_gy == [p0_a, p0_b]


def test_collect_sba_victims_etb_order_visible_via_clone_and_count(engine):
    """Cross-player simultaneous SBA pass: p0 has one lethal creature,
    p1 has one lethal creature, p1's ETB stamp is LOWER than p0's
    (achieved by injecting p1's creature first). Pre-CE5 the
    collection walked p0-first then p1, putting p0's victim first
    in the destruction loop; post-CE5 the walk follows ETB order, so
    p1's victim is destroyed first. Both end up in their respective
    graveyards either way (each player's graveyard contains exactly
    one creature). The end-state predicates that hold across both
    orderings: count == 2, both creatures graveyarded, each graveyard
    grew by exactly one. The closure makes the collection order
    available to CE8's future trigger emitter without changing this
    end-state."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    # Inject p1 FIRST so it has the lower ETB timestamp.
    p1_a = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    p0_a = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )

    state.deal_damage(p1_a, 2)
    state.deal_damage(p0_a, 2)

    p0_gy_before = state.graveyard_sizes[0]
    p1_gy_before = state.graveyard_sizes[1]
    assert state.apply_sbas() == 2
    assert state.find_object_zone(p1_a) == ZONE_GRAVEYARD
    assert state.find_object_zone(p0_a) == ZONE_GRAVEYARD
    assert state.graveyard_sizes[0] == p0_gy_before + 1
    assert state.graveyard_sizes[1] == p1_gy_before + 1


def test_collect_sba_victims_empty_when_no_lethal(engine):
    """Build a state with creatures across both players' battlefields
    in interleaved ETB order, none of them lethal. apply_sbas returns 0
    and no graveyard movement happens. This pins the empty-case path
    through `bf_iter_etb_sorted` — the helper walks a non-empty list
    but produces zero victims."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=1
    )
    p0_a = state.register_and_inject_object(
        _two_two_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    p1_a = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )

    # No damage applied; no lethal predicates.
    assert state.apply_sbas() == 0
    assert state.find_object_zone(p0_a) == ZONE_BATTLEFIELD
    assert state.find_object_zone(p1_a) == ZONE_BATTLEFIELD
    assert state.graveyard_sizes == [0, 0]


def test_collect_sba_victims_synthetic_state_tie_break_preserves_p0_first(
    synthetic_state,
):
    """Tie-break invariant: when every bf object has
    `etb_timestamp == 0` (the synthetic-state path — `make_player`
    populates without calling `reserve_etb_timestamp`), the stable
    sort preserves the p0-then-p1 walk so pre-CE5 baselines stay
    bit-equal.

    Concretely: damage one creature on each player's bf lethally.
    The collection order is (p0_creature, p1_creature) — same as
    pre-CE5. Per-graveyard end state is unchanged."""
    synthetic_state.deal_damage(P0_FIRST_BEAR_ID, 2)
    synthetic_state.deal_damage(P1_FIRST_BEAR_ID, 2)

    assert synthetic_state.apply_sbas() == 2
    p0_gy = [d["id"] for d in synthetic_state.graveyard_snapshot(0)]
    p1_gy = [d["id"] for d in synthetic_state.graveyard_snapshot(1)]
    assert p0_gy == [P0_FIRST_BEAR_ID]
    assert p1_gy == [P1_FIRST_BEAR_ID]
