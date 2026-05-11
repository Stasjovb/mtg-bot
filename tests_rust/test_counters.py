"""Counter primitives on the Rust ``GameState``.

Ported from ``tests/test_counters.py`` and the per-counter-type fields
in ``src/mtg_bot/game.py`` (``plus_one_counters``, ``minus_one_counters``,
``charge_counters``, ``stun_counters`` etc.) plus the +1/+1 / -1/-1
cancellation rule at ``state_based_actions`` (CR 704.5p).

Scope: a single per-instance ``i32`` net counter on ``GameObject``
modeling +1/+1 (positive) and -1/-1 (negative) — they cancel pairwise
at SBAs, so the net value captures the post-cancellation amount that
contributes to effective P/T. Multi-kind counter maps (charge / lore /
loyalty / brick / stun / time) are a future slice.

**Out of scope of this slice:**

- SBA-side cancellation. The Python engine cancels +1/+1 vs -1/-1 at
  ``state_based_actions``; the Rust side stores the net value
  pre-cancellation today (caller can subtract). Lifting this means
  adding an SBA pass — separate slice.
- Real effective-P/T composition (base + counters + auras + ContinuousModifiers).
  The synthetic Grizzly Bears printing has base P/T 0/0 today; the
  card-bridge slice that wires P/T into ``CardPrinting`` is the
  prerequisite. For this slice ``power_bonus_from_counters`` returns
  the raw counter contribution.

The CoW canary lives in ``test_counter_change_on_clone_does_not_affect_original``
— like ``test_tap.py``'s ``test_tap_one_clone_does_not_tap_other``,
this is the load-bearing assertion that ``Arc::make_mut`` was used
correctly on the per-zone Vec.
"""

from __future__ import annotations

import pytest


# `make_synthetic_state(num_battlefield=10, num_hand=7, num_library=50)`
# lays player 0 out as:
#   battlefield: ids 0..9
#   hand:        ids 10..16
#   library:     ids 17..66
# and player 1's range starts at 67. We rely on these id ranges below.
P0_FIRST_BATTLEFIELD_ID = 0
P0_FIRST_HAND_ID = 10
P0_FIRST_LIBRARY_ID = 17
P1_FIRST_BATTLEFIELD_ID = 67


def test_object_starts_with_zero_counters(synthetic_state):
    """Fresh synthetic objects come up with `counters == 0` (mirrors
    `GameObject.counters: i32 = 0` default in `rust/src/state.rs`)."""
    for obj_id in range(P0_FIRST_BATTLEFIELD_ID, P0_FIRST_BATTLEFIELD_ID + 10):
        assert synthetic_state.get_counters(obj_id) == 0
    # And in hand / library too.
    assert synthetic_state.get_counters(P0_FIRST_HAND_ID) == 0
    assert synthetic_state.get_counters(P0_FIRST_LIBRARY_ID) == 0


def test_get_counters_unknown_id_returns_none(synthetic_state):
    """Reading counters off an id that doesn't exist anywhere returns
    `None`. Matches the read-side `is_tapped` / `find_object_zone`
    convention of distinguishing 'not found' from a real value."""
    assert synthetic_state.get_counters(999_999) is None


def test_set_counters_changes_value(synthetic_state):
    """`set_counters(obj_id, n)` writes the absolute value and reports
    success. Subsequent `get_counters` reads back `n`."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    assert synthetic_state.set_counters(obj_id, 3) is True
    assert synthetic_state.get_counters(obj_id) == 3


def test_set_counters_unknown_id_returns_false(synthetic_state):
    """Setting counters on an id that isn't in any zone returns False
    rather than raising — mirrors the silent-no-op pattern that
    `tap_object` uses for the same scenario (object already left
    the relevant zone)."""
    assert synthetic_state.set_counters(999_999, 5) is False


def test_set_counters_works_in_any_zone(synthetic_state):
    """+1/+1 counters most often live on battlefield permanents but
    nothing in MTG forbids counters in other zones (e.g. Athreos
    counters on cards in graveyard, time counters on suspended cards
    in exile). The lookup must search all zones, not just battlefield."""
    # Hand and library too.
    assert synthetic_state.set_counters(P0_FIRST_HAND_ID, 2) is True
    assert synthetic_state.get_counters(P0_FIRST_HAND_ID) == 2
    assert synthetic_state.set_counters(P0_FIRST_LIBRARY_ID, 4) is True
    assert synthetic_state.get_counters(P0_FIRST_LIBRARY_ID) == 4


def test_add_counters_increments(synthetic_state):
    """`add_counters(obj_id, delta)` is the cumulative variant — two
    additions of (2, 1) leave the object at 3."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    assert synthetic_state.add_counters(obj_id, 2) is True
    assert synthetic_state.add_counters(obj_id, 1) is True
    assert synthetic_state.get_counters(obj_id) == 3


def test_add_negative_counters_decrements(synthetic_state):
    """Adding a negative delta models -1/-1 counters arriving on a
    creature that already had +1/+1 counters. The pairwise SBA
    cancellation (CR 704.5p) is implicit in the net-i32 representation
    — adding -2 to a 3 leaves 1 (net contribution to effective P/T
    after cancellation)."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, 3)
    assert synthetic_state.add_counters(obj_id, -2) is True
    assert synthetic_state.get_counters(obj_id) == 1


def test_add_counters_can_go_negative(synthetic_state):
    """The engine reports the raw net value — negative values mean
    'more -1/-1 than +1/+1 counters'. Whether the creature dies at
    0 toughness is a higher-layer SBA decision that this primitive
    does not enforce."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    assert synthetic_state.add_counters(obj_id, -2) is True
    assert synthetic_state.get_counters(obj_id) == -2


def test_add_counters_unknown_id_returns_false(synthetic_state):
    """Symmetric with `set_counters` — additive write to an id that
    isn't in any zone is a silent no-op returning False."""
    assert synthetic_state.add_counters(999_999, 1) is False


def test_power_bonus_from_counters_matches_get_counters(synthetic_state):
    """Per the +1/+1 model, a creature with N net counters contributes
    +N to its power. Real composition with base P/T + auras + layers
    happens elsewhere; this is just the counter contribution."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    # Default 0.
    assert synthetic_state.power_bonus_from_counters(obj_id) == 0
    synthetic_state.set_counters(obj_id, 4)
    assert synthetic_state.power_bonus_from_counters(obj_id) == 4
    synthetic_state.set_counters(obj_id, -1)
    assert synthetic_state.power_bonus_from_counters(obj_id) == -1


def test_power_bonus_unknown_id_returns_none(synthetic_state):
    """Same not-found convention as `get_counters`."""
    assert synthetic_state.power_bonus_from_counters(999_999) is None


def test_toughness_bonus_matches_power_bonus(synthetic_state):
    """+1/+1 affects power and toughness equally (and -1/-1 the same).
    The two methods read the same underlying field; they exist as
    distinct names so callers that care about the asymmetry case
    (e.g. *just* boosting power via a future +1/+0 counter type)
    have a clean upgrade path."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    for n in (0, 3, -2, 1):
        synthetic_state.set_counters(obj_id, n)
        assert (
            synthetic_state.power_bonus_from_counters(obj_id)
            == synthetic_state.toughness_bonus_from_counters(obj_id)
            == n
        )


def test_toughness_bonus_unknown_id_returns_none(synthetic_state):
    assert synthetic_state.toughness_bonus_from_counters(999_999) is None


def test_clone_preserves_counters(synthetic_state):
    """A clone of the state — the same `Clone` impl MCTS exercises on
    every node expansion — carries counter values forward. They live
    inside `Arc<Vec<GameObject>>` and ride the refcount bump."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, 3)
    snapshot = synthetic_state.clone_once()
    assert snapshot.get_counters(obj_id) == 3


def test_counter_change_on_clone_does_not_affect_original(synthetic_state):
    """**CoW canary.** The whole point of `Arc<Vec<GameObject>>` zones
    is that two live clones of a GameState observe independent
    mutations. Setting counters on one clone must NOT visibly mutate
    the same object on the other — `Arc::make_mut` should clone the
    inner Vec on the first mutation while another reference is live.

    Same load-bearing invariant as `test_tap_one_clone_does_not_tap_other`,
    but for the counter field. If this fails every CoW assumption
    downstream is broken."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    # Original starts at 0; baseline assertion before any mutation.
    assert synthetic_state.get_counters(obj_id) == 0
    other = synthetic_state.clone_once()
    assert other.get_counters(obj_id) == 0
    # Mutate ONLY the clone.
    assert other.set_counters(obj_id, 5) is True
    assert other.get_counters(obj_id) == 5
    # Original must NOT see the change.
    assert synthetic_state.get_counters(obj_id) == 0, (
        "CoW broken: setting counters on clone leaked into original"
    )
    # Symmetric direction: mutating the original after the clone
    # diverges should not retroactively touch the clone.
    assert synthetic_state.add_counters(obj_id, 2) is True
    assert synthetic_state.get_counters(obj_id) == 2
    assert other.get_counters(obj_id) == 5


# --- double_counters_for_player (Doubling Season-style) -----------------------
#
# Real Doubling Season is a static replacement effect that intercepts
# counter-placement events. This primitive is the simpler "snap to
# doubled state" mutator — for every creature on the given player's
# battlefield with non-zero net counters, multiply its counter value
# by 2. Useful as a building block for the future replacement-effects
# framework and as a one-shot test tool for counter-stacking scenarios.


def test_double_counters_for_player_doubles_positive(synthetic_state):
    """A creature with +3 net counters becomes +6 after doubling."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, 3)
    synthetic_state.double_counters_for_player(0)
    assert synthetic_state.get_counters(obj_id) == 6


def test_double_counters_for_player_doubles_negative(synthetic_state):
    """A creature with -2 net counters becomes -4 after doubling.
    Doubling Season's "double the counter" interpretation applies
    symmetrically to negative counters in this primitive."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, -2)
    synthetic_state.double_counters_for_player(0)
    assert synthetic_state.get_counters(obj_id) == -4


def test_double_counters_for_player_skips_zero(synthetic_state):
    """A creature at 0 net counters stays at 0 (2 * 0 == 0). The
    no-op skip is harmless — the test pins the obvious case so no
    future refactor accidentally writes a sentinel."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    assert synthetic_state.get_counters(obj_id) == 0
    synthetic_state.double_counters_for_player(0)
    assert synthetic_state.get_counters(obj_id) == 0


def test_double_counters_for_player_doubles_all_creatures(synthetic_state):
    """Every creature on the player's battlefield gets doubled in a
    single call — not just one. Sets distinct counter values across
    multiple ids and asserts each one doubled."""
    # ids 0..9 are on p0's battlefield by the synthetic-state convention.
    synthetic_state.set_counters(0, 1)
    synthetic_state.set_counters(1, 2)
    synthetic_state.set_counters(2, -3)
    synthetic_state.set_counters(3, 0)
    synthetic_state.set_counters(4, 5)
    synthetic_state.double_counters_for_player(0)
    assert synthetic_state.get_counters(0) == 2
    assert synthetic_state.get_counters(1) == 4
    assert synthetic_state.get_counters(2) == -6
    assert synthetic_state.get_counters(3) == 0
    assert synthetic_state.get_counters(4) == 10


def test_double_counters_for_player_only_affects_target_player(synthetic_state):
    """Doubling for p0 does not touch any creature on p1's
    battlefield. p1 ids start at P1_FIRST_BATTLEFIELD_ID (67)."""
    p0_obj = P0_FIRST_BATTLEFIELD_ID
    p1_obj = P1_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(p0_obj, 4)
    synthetic_state.set_counters(p1_obj, 4)
    synthetic_state.double_counters_for_player(0)
    assert synthetic_state.get_counters(p0_obj) == 8
    # p1's creature was not affected.
    assert synthetic_state.get_counters(p1_obj) == 4


def test_double_counters_for_player_unknown_player_raises(synthetic_state):
    """Out-of-range player_id raises rather than silently no-op'ing —
    mirrors the loud-failure convention of `clear_damage_for_player`
    and the rest of the per-player primitives."""
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.double_counters_for_player(99)


def test_double_counters_for_player_clone_isolation(synthetic_state):
    """**CoW canary for the doubling primitive.** Doubling on a clone
    must not retroactively mutate the original's battlefield Vec.
    Same load-bearing invariant as `test_counter_change_on_clone_does_not_affect_original`,
    but for the bulk-doubling primitive specifically."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, 3)
    snapshot = synthetic_state.clone_once()
    # Mutate ONLY the clone.
    snapshot.double_counters_for_player(0)
    assert snapshot.get_counters(obj_id) == 6
    # Original must NOT see the change.
    assert synthetic_state.get_counters(obj_id) == 3, (
        "CoW broken: double_counters_for_player on clone leaked into original"
    )


# --- proliferate (CR 701.25) -------------------------------------------------
#
# Real proliferate lets the controller pick any number of permanents
# and players with counters and add one of an existing kind; this
# primitive deterministically proliferates every eligible permanent
# on both battlefields. See `docs/SEARCH_LIMITATIONS.md` for the
# divergence note. The semantics tested here are the simplified
# always-add variant: positives tick up by 1, negatives tick down by 1
# (one more -1/-1), zero stays put.


def test_proliferate_empty_battlefields_is_noop(engine):
    """Proliferate on a state with no objects on either battlefield
    must not panic. Build a state with `num_battlefield=0` so both
    sides' battlefields are empty Vecs."""
    state = engine.make_synthetic_state(num_battlefield=0, num_hand=0, num_library=10)
    # No assertion beyond "doesn't raise" — exercises the fast path.
    state.proliferate()


def test_proliferate_no_counters_anywhere_is_noop(synthetic_state):
    """Default synthetic state has 10 + 10 battlefield permanents but
    every one is at counters=0. Proliferate must touch nothing."""
    # Snapshot every battlefield id's counter value (all 0 by default).
    p0_ids = list(range(P0_FIRST_BATTLEFIELD_ID, P0_FIRST_BATTLEFIELD_ID + 10))
    p1_ids = list(range(P1_FIRST_BATTLEFIELD_ID, P1_FIRST_BATTLEFIELD_ID + 10))
    synthetic_state.proliferate()
    for obj_id in p0_ids + p1_ids:
        assert synthetic_state.get_counters(obj_id) == 0


def test_proliferate_positive_counter_adds_one(synthetic_state):
    """A creature at +2 counters becomes +3 after a single proliferate."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, 2)
    synthetic_state.proliferate()
    assert synthetic_state.get_counters(obj_id) == 3


def test_proliferate_negative_counter_decrements(synthetic_state):
    """A creature at -2 counters (net -1/-1) becomes -3 after
    proliferate — one more -1/-1 counter, magnitude grows in the
    negative direction."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, -2)
    synthetic_state.proliferate()
    assert synthetic_state.get_counters(obj_id) == -3


def test_proliferate_mixed_board_each_kind_grows(synthetic_state):
    """A board with one creature at +1, one at -1, and one at 0:
    after proliferate they're +2, -2, 0 respectively. Pins both the
    sign-preservation behavior and the "skip zero" rule in one test."""
    plus_id = 0
    minus_id = 1
    zero_id = 2
    synthetic_state.set_counters(plus_id, 1)
    synthetic_state.set_counters(minus_id, -1)
    # zero_id stays at 0 by default.
    synthetic_state.proliferate()
    assert synthetic_state.get_counters(plus_id) == 2
    assert synthetic_state.get_counters(minus_id) == -2
    assert synthetic_state.get_counters(zero_id) == 0


def test_proliferate_affects_both_battlefields(synthetic_state):
    """Proliferate is symmetric across players — one creature each
    side, both with counters → both updated. (Real MTG proliferate
    is controller-choice; this primitive is "every eligible permanent".)"""
    p0_obj = P0_FIRST_BATTLEFIELD_ID
    p1_obj = P1_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(p0_obj, 3)
    synthetic_state.set_counters(p1_obj, -1)
    synthetic_state.proliferate()
    assert synthetic_state.get_counters(p0_obj) == 4
    assert synthetic_state.get_counters(p1_obj) == -2


def test_proliferate_saturates_at_i32_max(synthetic_state):
    """A creature at i32::MAX counters stays at i32::MAX after
    proliferate — saturating_add prevents wrap. Symmetric to the
    saturating-mul invariant on `double_counters_for_player`."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    i32_max = 2**31 - 1
    synthetic_state.set_counters(obj_id, i32_max)
    synthetic_state.proliferate()
    assert synthetic_state.get_counters(obj_id) == i32_max


def test_proliferate_saturates_at_i32_min(synthetic_state):
    """Symmetric to the i32::MAX case for the negative side: a
    counter at i32::MIN stays at i32::MIN after proliferate (which
    would otherwise try to subtract one and wrap)."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    i32_min = -(2**31)
    synthetic_state.set_counters(obj_id, i32_min)
    synthetic_state.proliferate()
    assert synthetic_state.get_counters(obj_id) == i32_min


def test_proliferate_clone_isolation(synthetic_state):
    """**CoW canary for proliferate.** Proliferating on a clone must
    not retroactively mutate the original's battlefield Vec. Same
    load-bearing invariant as the doubling-primitive canary above —
    if this fails, every CoW assumption downstream of proliferate
    is broken."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, 3)
    snapshot = synthetic_state.clone_once()
    # Mutate ONLY the clone.
    snapshot.proliferate()
    assert snapshot.get_counters(obj_id) == 4
    # Original must NOT see the change.
    assert synthetic_state.get_counters(obj_id) == 3, (
        "CoW broken: proliferate on clone leaked into original"
    )


# --- Cross-feature edge cases ------------------------------------------------
#
# These tests compose the counter primitives with sibling slices
# (Effect dispatch, state-based actions, register_and_inject_object,
# clone / fingerprint / snapshot) to pin the interaction surface that
# isolated counter tests cannot cover. They follow the convention
# established in ``test_sba.py``'s "Cross-feature: SBA + Effect
# interactions" block — printing dicts via the round-3 schema,
# ``register_and_inject_object`` to inject creatures with explicit
# P/T, ``resolve_top_of_stack`` to drive Effects through the same
# path the spell-resolution call site uses.
#
# Each test exercises a documented seam:
#   * Effect::AddCounters (round-15) on a filtered AnyCreature target
#   * Effect::AddCounters with negative count -> 0-toughness SBA
#     (CR 704.5f cross with state_ops_sba.rs)
#   * Effect::PutPlusOneCounterOnSelf (round-23) source_obj_id pattern
#   * Indestructible carve-out (CR 702.12b) blocks counter-driven 704.5f
#   * Clone-replay fingerprint identity for counter mutations
#   * CoW canary on the AddCounters Effect dispatch (clone vs original)
#   * Counter add/remove net effect through alternating apply_effect
#   * +1/+1 vs -1/-1 cancellation at SBA — Rust collapses to net-i32
#     (documented quirk, NOT a separate-kind cancellation rule)
#   * Counter "kind" distinction in storage (net-i32 model — no separate
#     stacks for + and -, documented gap)
#   * Counters surface through battlefield_snapshot (bridge round-trip)


ZONE_HAND = 0
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _two_two_creature_dict():
    """Vanilla 2/2 creature printing — no keywords, no special effects.
    Mirrors ``_two_two_creature_dict`` in test_sba.py."""
    return {
        "name": "Test Counter-Edge 2/2",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "keywords": [],
        "effects": [],
    }


def _indestructible_2_2_dict():
    """Indestructible 2/2 creature — CR 702.12 exemption canary."""
    return {
        "name": "Test Counter-Edge Indestructible 2/2",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "keywords": ["indestructible"],
        "effects": [],
    }


def _giant_growth_counters_dict(amount):
    """AddCounters{any_creature, amount} instant — Giant-Growth-shaped.
    Same schema as test_resolve.py's ``_giant_growth_dict`` /
    test_sba.py's ``_wither_dict``."""
    return {
        "name": f"Test +{amount}/+{amount} Counter",
        "card_types": ["Instant"],
        "mana_cost": {"G": 1},
        "effects": [
            {
                "kind": "add_counters",
                "count": amount,
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _self_counter_dict(amount=1):
    """Creature with PutPlusOneCounterOnSelf{amount} — Blade-of-the-
    Swarm-shaped. Same schema as test_resolve.py's ``_self_counter_dict``."""
    return {
        "name": f"Test Counter-Edge Self-Counter (x{amount})",
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
        "effects": [
            {
                "kind": "put_plus_one_counter_on_self",
                "amount": amount,
            }
        ],
    }


def test_add_counters_effect_applies_to_filtered_any_creature_target(engine):
    """``Effect::AddCounters {target: AnyCreature, count: 2}`` resolves
    by picking the FIRST creature on the defending player's
    battlefield (round-15 deterministic shape) and depositing +2
    net counters there. Cross-feature with round-15 Effect dispatch
    and round-2 ``get_counters`` read-side: the counter contribution
    must surface via the counter primitive after the spell resolves.

    Uses a synthetic state where p1's bf[0] is itself a creature so
    the filtered AnyCreature pick lands on a creature target rather
    than the synthetic seed's default bf[0] (a Forest with no
    toughness — the AddCounters arm doesn't currently filter on
    creature-type, but a future tightening would; this test would
    catch it)."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    # Inject the AnyCreature target onto p1's bf[0] (= defender's
    # smallest-index battlefield object).
    target_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    assert state.get_counters(target_id) == 0

    spell_id = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # The filtered AnyCreature pick deposited +2 counters on the
    # target via the round-2 net-i32 model.
    assert state.get_counters(target_id) == 2
    # Power-bonus / toughness-bonus accessors return the same value
    # (the round-2 read-side reports the net counter contribution).
    assert state.power_bonus_from_counters(target_id) == 2
    assert state.toughness_bonus_from_counters(target_id) == 2


def test_add_counters_effect_negative_drives_sba_destruction_via_704_5f(engine):
    """``Effect::AddCounters {target: AnyCreature, count: -2}`` on a
    fresh 2/2 leaves effective toughness 2 + (-2) = 0. The round-12
    0-toughness SBA (CR 704.5f) destroys it on the next ``apply_sbas``
    pass — NOT the damage-stamp path (CR 704.5g), since no damage
    was dealt. This pins the cross-feature interaction between
    Effect dispatch (round-15), counter storage (round-2), and the
    SBA loop (round-16's counter-aware effective-toughness check).

    Distinct from the damage-stamp path: a -1/-1 counter is NOT
    damage; CR 704.5f checks effective toughness <= 0, not marked
    damage >= toughness. The two destruction rules can fire on the
    same creature but for different reasons — this test isolates
    the 704.5f-only path."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    creature_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=-2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Counter applied: net = -2. No damage dealt.
    assert state.get_counters(creature_id) == -2
    assert state.get_damage(creature_id) == 0
    # Effective toughness = 2 + (-2) = 0 -> 704.5f triggers.
    assert state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert state.apply_sbas() == 1
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD


def test_put_plus_one_counter_on_self_lands_on_source_battlefield_obj(
    synthetic_state,
):
    """``Effect::PutPlusOneCounterOnSelf {amount: 3}`` resolves by
    locating the source GameObject (the resolving stack item's
    source, threaded through ``apply_effect`` via the round-23
    ``source_obj_id`` parameter) on a battlefield zone and adding
    counters to it. Cross-feature with round-23 source-finding
    pattern and round-2 ``get_counters`` read-side.

    Distinct from AddCounters which picks defender's bf[0]: this
    arm picks "self" by obj_id regardless of controller / zone-index
    position. Pins both:
    1. counters land on the SOURCE, not bf[0]
    2. ``get_counters`` reads back the value from the same id"""
    spell_obj_id = synthetic_state.register_and_inject_object(
        _self_counter_dict(amount=3), 0, ZONE_BATTLEFIELD
    )
    # Pre-condition: source on p0's bf, no counters yet. The default
    # synthetic state's bf[0] is a Forest (id 0); the source we
    # just injected lives at the END of p0's bf, NOT at bf[0]. This
    # is the key cross-feature property to pin — PutPlusOneCounterOnSelf
    # picks by obj_id, not by battlefield position.
    assert synthetic_state.get_counters(spell_obj_id) == 0
    assert synthetic_state.get_counters(P0_FIRST_BATTLEFIELD_ID) == 0

    synthetic_state.push_to_stack(spell_obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    # +3 counters lands on the SOURCE, not bf[0].
    assert synthetic_state.get_counters(spell_obj_id) == 3
    # bf[0] (Forest, id 0) is untouched — confirms the source-finder
    # did not mistakenly fall back to the AddCounters-shaped bf[0]
    # pick.
    assert synthetic_state.get_counters(P0_FIRST_BATTLEFIELD_ID) == 0


def test_counters_survive_clone_replay_fingerprint_identity(synthetic_state):
    """Two clones that apply the same counter mutation produce the
    same fingerprint. Cross-feature canary that the counter field
    serializes deterministically into the round-22 SHA1 fingerprint
    — if the counters slot drifts (e.g. counters stored in a hash
    map with iteration-order leakage), the digest diverges across
    clones even with identical observable state.

    This is the cross-engine parity property the round-22
    ``hash_state`` recipe relies on: the per-object 8-tuple includes
    ``counters`` at a stable position, so two replays of the same
    sequence produce identical fingerprints."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    # Drive both clones through the same sequence: set +3, add -1.
    a = synthetic_state.clone_once()
    b = synthetic_state.clone_once()
    a.set_counters(obj_id, 3)
    a.add_counters(obj_id, -1)
    b.set_counters(obj_id, 3)
    b.add_counters(obj_id, -1)
    assert a.get_counters(obj_id) == 2
    assert b.get_counters(obj_id) == 2
    # Fingerprints must match — same observable state across the
    # entire 12-char digest.
    assert a.fingerprint() == b.fingerprint()
    # And the original (still at 0 counters) must NOT match — proves
    # the fingerprint is actually sensitive to the counter field and
    # not e.g. always-zero from a serialization bug.
    assert synthetic_state.fingerprint() != a.fingerprint()


def test_add_counters_effect_on_clone_does_not_mutate_original(engine):
    """**CoW canary for the Effect::AddCounters dispatch path.**
    Resolving a counter spell on a clone must not retroactively
    mutate the original's battlefield Vec. Same load-bearing
    invariant as ``test_counter_change_on_clone_does_not_affect_original``
    but exercising the full Effect-dispatch path (round-15) rather
    than the bare ``add_counters`` primitive — verifies
    ``Arc::make_mut`` is called correctly inside the Effect arm."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    target_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=2), 0, ZONE_HAND
    )

    other = state.clone_once()
    # Mutate ONLY the clone: push and resolve the spell.
    other.push_to_stack(spell_id, 0)
    other.resolve_top_of_stack()
    assert other.get_counters(target_id) == 2

    # Original must NOT see the counter mutation — the spell is
    # still in the original's hand, the stack is empty, and the
    # target's counter value is unchanged.
    assert state.get_counters(target_id) == 0
    assert state.find_object_zone(spell_id) == ZONE_HAND
    assert state.is_stack_empty() is True


def test_add_then_remove_counters_net_zero_via_apply_effect(engine):
    """Resolving ``AddCounters{+3}`` then ``AddCounters{-3}`` against
    the same defender bf[0] leaves the target at net 0 counters.
    Pins the cross-feature property that the round-15 Effect arm
    composes additively on the round-2 i32 net-counter field — no
    separate "kind" buckets that would resist cancellation.

    This is the running-net behavior implied by the net-i32 model:
    a +N counter and a -N counter cancel into the storage layer
    directly, not via an SBA pass."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=2, num_library=1
    )
    target_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    plus_spell = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=3), 0, ZONE_HAND
    )
    minus_spell = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=-3), 0, ZONE_HAND
    )

    # Resolve +3.
    state.push_to_stack(plus_spell, 0)
    state.resolve_top_of_stack()
    assert state.get_counters(target_id) == 3

    # Resolve -3.
    state.push_to_stack(minus_spell, 0)
    state.resolve_top_of_stack()
    assert state.get_counters(target_id) == 0


def test_plus_one_minus_one_cancellation_quirk_net_i32_collapses_pre_sba(engine):
    """**Documented quirk: net-i32 collapses +1/+1 vs -1/-1 BEFORE
    SBAs.** Real MTG (CR 704.5r / 704.5p) cancels +1/+1 and -1/-1
    counters at SBA time, but stores them as distinct counter kinds
    pre-cancellation. The Rust net-i32 model (round-2) collapses
    both kinds into a single signed integer at write time — so a
    creature that received 3 +1/+1 counters and then 2 -1/-1
    counters reads as ``counters == 1`` immediately, BEFORE any SBA
    pass.

    The observable effect is the same for the destruction rules:
    a 2/2 with effective toughness 2 + 1 = 3 survives, identical to
    real MTG's post-cancellation result. The difference is
    inexpressible queries like "how many +1/+1 counters does this
    creature have right now" — see ``state_ops_counters.rs`` module
    docstring for the divergence note. This test pins the quirk so
    a future SBA-level cancellation slice replaces it deliberately
    rather than by accident."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=2, num_library=1
    )
    target_id = state.register_and_inject_object(
        _two_two_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    plus_spell = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=3), 0, ZONE_HAND
    )
    minus_spell = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=-2), 0, ZONE_HAND
    )

    # Resolve +3 then -2. Real MTG would store these as 3 +1/+1 and
    # 2 -1/-1 counters BEFORE SBAs; the Rust net-i32 model stores
    # them as net +1 immediately at write time.
    state.push_to_stack(plus_spell, 0)
    state.resolve_top_of_stack()
    state.push_to_stack(minus_spell, 0)
    state.resolve_top_of_stack()
    # Net storage is +1 BEFORE any SBA pass — the quirk.
    assert state.get_counters(target_id) == 1

    # SBA is a no-op (effective toughness 2 + 1 = 3 > 0, no damage).
    assert state.apply_sbas() == 0
    # Net value still +1 post-SBA — the observable destruction
    # outcome matches real MTG even though the internal representation
    # diverges.
    assert state.get_counters(target_id) == 1


def test_indestructible_blocks_counter_driven_704_5f_destruction(engine):
    """CR 702.12 indestructible carves out the 704.5f (0-toughness)
    destruction the same way it carves out 704.5g (lethal damage).
    A counter-driven path to effective toughness 0 on an
    indestructible creature does NOT destroy it.

    Cross-feature with state_ops_sba.rs's indestructible-keyword
    check (round-13). Mirrors ``test_indestructible_creature_with_zero_toughness_survives``
    in test_sba.py but routes the counter through the round-15
    AddCounters Effect dispatch path rather than the bare
    ``set_counters`` primitive — proves the indestructible
    exemption is at the SBA layer (where it should be), not at
    the counter-write layer."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1
    )
    indest_id = state.register_and_inject_object(
        _indestructible_2_2_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _giant_growth_counters_dict(amount=-2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Counter wrote through fine — indestructible doesn't prevent
    # the counter write itself, only the destruction step.
    assert state.get_counters(indest_id) == -2
    # SBA does NOT destroy (CR 702.12b exemption).
    assert state.apply_sbas() == 0
    assert state.find_object_zone(indest_id) == ZONE_BATTLEFIELD
    # Counter value preserved post-SBA (the indestructible carve-out
    # at the SBA layer skips the destruction step entirely; the
    # counter field is untouched by the SBA pass).
    assert state.get_counters(indest_id) == -2


def test_counters_distinguished_from_damage_in_storage(synthetic_state):
    """The counter field and the damage field are independent
    per-object scalars. Setting +3 counters does not pollute the
    damage marker, and dealing 1 damage does not pollute the counter
    field. Cross-feature with round-1 ``deal_damage`` and round-2
    ``set_counters``: the two storage slots must stay separate so
    SBAs can read each independently.

    The net-i32 model intentionally collapses +1/+1 and -1/-1
    counter KINDS into a single signed integer (documented quirk —
    see the SBA cross-feature test above), but counter vs damage
    are genuinely separate fields and must remain so."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    # Baseline.
    assert synthetic_state.get_counters(obj_id) == 0
    assert synthetic_state.get_damage(obj_id) == 0

    # Set counters: damage must stay 0.
    synthetic_state.set_counters(obj_id, 3)
    assert synthetic_state.get_counters(obj_id) == 3
    assert synthetic_state.get_damage(obj_id) == 0

    # Deal damage: counters must stay 3.
    synthetic_state.deal_damage(obj_id, 1)
    assert synthetic_state.get_counters(obj_id) == 3
    assert synthetic_state.get_damage(obj_id) == 1

    # Negative counters: damage must stay 1.
    synthetic_state.set_counters(obj_id, -2)
    assert synthetic_state.get_counters(obj_id) == -2
    assert synthetic_state.get_damage(obj_id) == 1


def test_counters_surface_through_battlefield_snapshot_round_trip(
    synthetic_state,
):
    """Counters set on a battlefield permanent appear in the
    ``battlefield_snapshot`` dict under the ``counters`` key.
    Cross-feature with the bridge / snapshot path (round-22 phase-2a)
    — same field flows into the fingerprint per-object 8-tuple, so
    the snapshot is the de-facto serialized form of the counter
    storage.

    Distinct from the ``test_battlefield_snapshot_reflects_counters_field``
    test in test_snapshot.py: that pins the snapshot side; this one
    pins it from the counter-test perspective — if counters
    storage ever moves (e.g. into a side-table keyed by id), the
    snapshot path must keep surfacing the same value.

    Note on the gap: there is no dedicated "counter snapshot
    getter" today — the per-object scalar surface IS the snapshot
    via ``battlefield_snapshot``. A future multi-kind counter map
    (charge / lore / loyalty / brick / stun / time) would need its
    own getter; this test documents the current single-value
    surface."""
    obj_id = P0_FIRST_BATTLEFIELD_ID
    synthetic_state.set_counters(obj_id, 4)

    snap = synthetic_state.battlefield_snapshot()
    matching = [d for d in snap if d["id"] == obj_id]
    assert len(matching) == 1
    assert matching[0]["counters"] == 4

    # Round-trip via clone: the clone's snapshot reports the same
    # value (the counter field rides the Arc<Vec<GameObject>>
    # refcount bump in clone_once).
    snap_clone = synthetic_state.clone_once().battlefield_snapshot()
    matching_clone = [d for d in snap_clone if d["id"] == obj_id]
    assert len(matching_clone) == 1
    assert matching_clone[0]["counters"] == 4


# -------------------- Round-28 PutPlusOneCounterOnEachCreatureYouControl --------------------


def _atmospheric_greenhouse_dict(amount: int = 1):
    """Atmospheric-Greenhouse-shape ETB: put +amount/+amount counter(s)
    on each creature you control."""
    return {
        "name": "Atmospheric Greenhouse (synthetic)",
        "mana_cost": {"G": 1, "generic": 2},
        "card_types": ["Enchantment"],
        "effects": [
            {
                "kind": "put_plus_one_counter_on_each_creature_you_control",
                "amount": amount,
            }
        ],
    }


def test_register_plus1_on_each_creature_default_amount(empty_registry):
    pid = empty_registry.register_printing(
        {
            "name": "default-counter",
            "card_types": ["Enchantment"],
            "effects": [
                {"kind": "put_plus_one_counter_on_each_creature_you_control"}
            ],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert effects[0]["kind"] == "put_plus_one_counter_on_each_creature_you_control"
    assert effects[0]["amount"] == 1


def test_register_plus1_on_each_creature_negative_amount_raises(empty_registry):
    import pytest
    with pytest.raises(ValueError, match="non-negative"):
        empty_registry.register_printing(
            {
                "name": "bad-counter",
                "card_types": ["Enchantment"],
                "effects": [
                    {
                        "kind": "put_plus_one_counter_on_each_creature_you_control",
                        "amount": -1,
                    }
                ],
            }
        )


def test_plus1_on_each_creature_pumps_all_p0_creatures(synthetic_state):
    """Each Grizzly Bears on p0's battlefield gains +1 counter; Forests
    skipped (non-creature); p1's creatures untouched."""
    snap = synthetic_state.battlefield_snapshot()
    p0_creature_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    p0_forest_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Forest"
    ]
    p1_creature_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    spell_id = synthetic_state.register_and_inject_object(
        _atmospheric_greenhouse_dict(amount=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # All p0 bears: counters = 1.
    new_snap = synthetic_state.battlefield_snapshot()
    by_id = {d["id"]: d for d in new_snap}
    for cid in p0_creature_ids:
        assert by_id[cid]["counters"] == 1
    # Forests untouched: counters = 0.
    for fid in p0_forest_ids:
        assert by_id[fid]["counters"] == 0
    # p1's creatures untouched.
    for cid in p1_creature_ids:
        assert by_id[cid]["counters"] == 0


def test_plus1_on_each_creature_amount_zero_is_noop(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    spell_id = synthetic_state.register_and_inject_object(
        _atmospheric_greenhouse_dict(amount=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    new_snap = synthetic_state.battlefield_snapshot()
    by_id = {d["id"]: d for d in new_snap}
    for cid in bear_ids:
        assert by_id[cid]["counters"] == 0


def test_plus1_on_each_creature_stacks_on_existing_counters(synthetic_state):
    """Repeated casts accumulate: 2x +1 stacks to 2 counters per creature."""
    spell_id = synthetic_state.register_and_inject_object(
        _atmospheric_greenhouse_dict(amount=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    spell_id2 = synthetic_state.register_and_inject_object(
        _atmospheric_greenhouse_dict(amount=1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id2, 0)
    synthetic_state.resolve_top_of_stack()

    snap = synthetic_state.battlefield_snapshot()
    bear_counters = [
        d["counters"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    for c in bear_counters:
        assert c == 2


def test_plus1_on_each_creature_clone_isolation(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    spell_id = synthetic_state.register_and_inject_object(
        _atmospheric_greenhouse_dict(amount=2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone: bears have +2 counters.
    clone_snap = cloned.battlefield_snapshot()
    clone_by_id = {d["id"]: d for d in clone_snap}
    for cid in bear_ids:
        assert clone_by_id[cid]["counters"] == 2
    # Original: bears still at 0 counters.
    src_snap = synthetic_state.battlefield_snapshot()
    src_by_id = {d["id"]: d for d in src_snap}
    for cid in bear_ids:
        assert src_by_id[cid]["counters"] == 0
