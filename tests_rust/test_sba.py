"""State-based action (SBA) loop primitives on the Rust ``GameState``.

Ported from ``src/mtg_bot/turn.py::state_based_actions`` /
``_state_based_actions_pass`` and ``CR 704.5`` audit numbering.

**First-slice scope: lethal-damage SBA only (CR 704.5g).** A creature
whose marked damage is greater than or equal to its toughness is
destroyed (moved from battlefield to its controller's graveyard).
This slice exposes ``apply_sbas() -> int`` (count of destructions
this pass) plus the underlying ``is_lethal(obj_id) -> Option<bool>``
helper.

**Out of scope, deferred to future slices:**

- **0-toughness SBA (CR 704.5f).** "A creature with toughness 0 dies"
  is conceptually similar but reads from current toughness rather
  than from damage >= toughness. Test stays as a ``@pytest.mark.skip``
  to lock the API surface.
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


@pytest.mark.skip(
    reason=(
        "0-toughness SBA (CR 704.5f) deferred to future slice. The "
        "existing damage primitive does not subtract from a creature's "
        "effective toughness, and there's no -1/-1 counter / "
        "anthem-debuff path in the engine yet. When this lands, the "
        "test should pass: a creature whose effective toughness has "
        "dropped to 0 (e.g. via a -X/-X effect) gets destroyed by "
        "apply_sbas independent of marked damage. The API stays the "
        "same — apply_sbas() returns the destruction count, including "
        "0-toughness victims."
    )
)
def test_zero_toughness_creature_dies(synthetic_state):
    """Locked-in API surface for the future 0-toughness SBA slice."""
    obj_id = P0_FIRST_BEAR_ID
    # Hypothetical future API: shrink toughness past 0 somehow.
    # synthetic_state.set_toughness(obj_id, 0)
    assert synthetic_state.apply_sbas() == 1
    assert synthetic_state.find_object_zone(obj_id) == 3
