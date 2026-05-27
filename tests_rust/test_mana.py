"""Mana production / mana pool primitives on the Rust ``GameState``.

Ported from ``src/mtg_bot/effects/generic/mana.py`` (the ``AddManaToPool``
and friends sites that mutate ``Player.mana_pool``) plus the
"tap-a-Forest-for-{G}" idiom that the Python side spreads across an
``ActivatedAbility(is_mana_ability=True)`` plus an ``AddManaToPool``
effect. The Rust foundation commit (``df71d56``) added a typed
``Player.mana_pool: ManaPool { white, blue, black, red, green, colorless: u8 }``;
this slice grows the methods that read and mutate it.

**Negative-amount semantics decision** (mirrors the life slice's
choice — see ``test_life.py``): ``add_mana`` and ``remove_mana``
take ``i32`` amounts and raise ``ValueError`` on a negative value
rather than silently flooring at zero. ``amount = 0`` is allowed and
is a true no-op. ``remove_mana`` underflow (e.g. removing 1 green
from an empty pool) raises rather than clamping at zero — silent
underflow would mask paid-but-not-collected bugs.

**Mana-production lookup is provisional** (option (a) in the slice
plan): ``tap_for_mana`` recognizes Forests by printing-name string
match against the synthetic registry's "Forest" entry. This keeps
the slice scoped to ``state_ops_mana.rs`` — adding a typed
``mana_produced`` field to ``CardPrinting`` would require touching
``cards.rs``, which a sibling agent is also editing this round.
A future bridge slice will replace the name-keyed lookup with the
proper field.
"""

from __future__ import annotations

import pytest


def _bf_ids(state, player_id):
    """Return the GameObject ids on ``player_id``'s battlefield.

    Mirrors ``tests_rust/test_tap.py``'s helper. Synthetic-state
    defaults: 10 battlefield / 7 hand / 50 library per side.
    Player 0's battlefield ids are 0..9; player 1's start at 67.
    The first half (``num_battlefield // 2 = 5``) of each
    battlefield is Forests, the second half is Grizzly Bears
    (see ``make_player`` in ``rust/src/state.rs``).
    """
    if player_id == 0:
        return list(range(0, 10))
    return list(range(67, 77))


def _forest_id(state, player_id):
    """First Forest id on ``player_id``'s battlefield."""
    return _bf_ids(state, player_id)[0]


def _bears_id(state, player_id):
    """First Grizzly Bears id on ``player_id``'s battlefield (slot 5,
    since 5 forests come first)."""
    return _bf_ids(state, player_id)[5]


# --- mana pool reads ------------------------------------------------


def test_initial_mana_pool_is_empty(synthetic_state):
    """Both players' pools start at all-zero (the foundation commit
    defaults ``Player.mana_pool: ManaPool`` in ``make_player``)."""
    expected = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}
    assert synthetic_state.get_mana_pool(0) == expected
    assert synthetic_state.get_mana_pool(1) == expected


def test_get_mana_pool_returns_dict_view(synthetic_state):
    """The 7-key dict has all expected keys (six real colors + the
    ``any`` wildcard slot added by Phase 4E C2.5), all int-typed."""
    pool = synthetic_state.get_mana_pool(0)
    assert set(pool.keys()) == {"W", "U", "B", "R", "G", "C", "any"}
    for v in pool.values():
        assert isinstance(v, int)


def test_get_mana_pool_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.get_mana_pool(99)


# --- add_mana / remove_mana / empty_mana_pool -----------------------


def test_add_mana_increments_pool(synthetic_state):
    synthetic_state.add_mana(0, "G", 3)
    assert synthetic_state.get_mana_pool(0)["G"] == 3
    # Other colors / opponent pool untouched.
    pool = synthetic_state.get_mana_pool(0)
    for color in ("W", "U", "B", "R", "C"):
        assert pool[color] == 0
    assert synthetic_state.get_mana_pool(1)["G"] == 0


def test_add_mana_all_six_colors(synthetic_state):
    """Every supported color (W/U/B/R/G/C) is acceptable."""
    for color in ("W", "U", "B", "R", "G", "C"):
        synthetic_state.add_mana(0, color, 1)
    pool = synthetic_state.get_mana_pool(0)
    assert pool == {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1, "C": 1, "any": 0}


def test_add_mana_unknown_color_raises_value_error(synthetic_state):
    with pytest.raises(ValueError):
        synthetic_state.add_mana(0, "Q", 1)
    # Lowercase is also rejected — case-sensitive by convention.
    with pytest.raises(ValueError):
        synthetic_state.add_mana(0, "g", 1)


def test_add_mana_negative_amount_raises(synthetic_state):
    """Mirrors the life-slice convention: fail loudly on negative
    ``amount`` rather than silently clamping or wrapping."""
    with pytest.raises(ValueError):
        synthetic_state.add_mana(0, "G", -1)
    # State must be untouched after the rejected call.
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_add_mana_zero_amount_is_noop(synthetic_state):
    synthetic_state.add_mana(0, "G", 0)
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_add_mana_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.add_mana(99, "G", 1)


def test_remove_mana_decrements(synthetic_state):
    """Round-trip: add then remove leaves the pool unchanged."""
    synthetic_state.add_mana(0, "G", 5)
    synthetic_state.remove_mana(0, "G", 3)
    assert synthetic_state.get_mana_pool(0)["G"] == 2


def test_remove_mana_underflow_raises(synthetic_state):
    """Removing more than the pool holds raises rather than silently
    flooring at 0 — silent underflow would mask paid-but-not-
    collected bugs in cost-payment code."""
    with pytest.raises(ValueError):
        synthetic_state.remove_mana(0, "G", 1)
    # State must be untouched after the rejected call.
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_remove_mana_negative_amount_raises(synthetic_state):
    with pytest.raises(ValueError):
        synthetic_state.remove_mana(0, "G", -1)


def test_remove_mana_unknown_color_raises(synthetic_state):
    with pytest.raises(ValueError):
        synthetic_state.remove_mana(0, "Q", 1)


def test_empty_mana_pool_resets_player_to_zero(synthetic_state):
    """``empty_mana_pool(p)`` zeroes only ``p``'s pool — leaves the
    opponent alone. Mirrors the cleanup-step behavior on the Python
    side."""
    synthetic_state.add_mana(0, "G", 4)
    synthetic_state.add_mana(0, "R", 2)
    synthetic_state.add_mana(1, "U", 3)
    synthetic_state.empty_mana_pool(0)
    expected_zero = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}
    assert synthetic_state.get_mana_pool(0) == expected_zero
    # Opponent's pool untouched.
    assert synthetic_state.get_mana_pool(1)["U"] == 3


def test_empty_mana_pool_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.empty_mana_pool(99)


# --- empty_all_mana_pools (CR 106.4) --------------------------------


def test_empty_all_mana_pools_drains_both(synthetic_state):
    """``empty_all_mana_pools`` zeroes BOTH players' pools in one call.

    CR 106.4: "When a phase or step ends, each player's mana pool
    empties." Round-2 added the per-player ``empty_mana_pool``;
    this is the multi-player wrapper that the phase/step-end machinery
    will call."""
    synthetic_state.add_mana(0, "G", 3)
    synthetic_state.add_mana(1, "W", 2)
    synthetic_state.empty_all_mana_pools()
    expected_zero = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}
    assert synthetic_state.get_mana_pool(0) == expected_zero
    assert synthetic_state.get_mana_pool(1) == expected_zero


def test_empty_all_mana_pools_no_op_on_empty(synthetic_state):
    """Calling on already-empty pools is a quiet no-op (no error,
    pools stay empty). This is the common case at end-of-step when
    no player produced mana that step."""
    expected_zero = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}
    assert synthetic_state.get_mana_pool(0) == expected_zero
    assert synthetic_state.get_mana_pool(1) == expected_zero
    synthetic_state.empty_all_mana_pools()
    assert synthetic_state.get_mana_pool(0) == expected_zero
    assert synthetic_state.get_mana_pool(1) == expected_zero


def test_empty_all_mana_pools_clone_isolation(synthetic_state):
    """CoW canary — emptying on a clone leaves the original pools
    untouched. ManaPool is by-value-Copy in Player, so this should
    "just work" the same way the per-player empty does."""
    synthetic_state.add_mana(0, "G", 4)
    synthetic_state.add_mana(1, "U", 2)
    cloned = synthetic_state.clone_once()
    cloned.empty_all_mana_pools()
    expected_zero = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}
    assert cloned.get_mana_pool(0) == expected_zero
    assert cloned.get_mana_pool(1) == expected_zero
    # Original untouched.
    assert synthetic_state.get_mana_pool(0)["G"] == 4
    assert synthetic_state.get_mana_pool(1)["U"] == 2


# --- tap_for_mana ---------------------------------------------------


def test_tap_for_mana_on_forest_produces_green(synthetic_state):
    """Find a Forest on player 0's battlefield, tap it for mana,
    expect ``Some("G")``, the Forest is now tapped, and player 0's
    green count went up by 1."""
    forest_id = _forest_id(synthetic_state, 0)
    # Sanity: the synthetic state seeds a Forest at this slot.
    assert synthetic_state.printing_name_of(forest_id) == "Forest"
    assert synthetic_state.is_tapped(forest_id) is False
    assert synthetic_state.get_mana_pool(0)["G"] == 0

    result = synthetic_state.tap_for_mana(forest_id)
    assert result == "G"
    assert synthetic_state.is_tapped(forest_id) is True
    assert synthetic_state.get_mana_pool(0)["G"] == 1


def test_tap_for_mana_credits_correct_controller(synthetic_state):
    """A Forest on player 1's battlefield credits player 1's pool,
    not player 0's."""
    forest_id = _forest_id(synthetic_state, 1)
    assert synthetic_state.printing_name_of(forest_id) == "Forest"
    result = synthetic_state.tap_for_mana(forest_id)
    assert result == "G"
    assert synthetic_state.get_mana_pool(0)["G"] == 0
    assert synthetic_state.get_mana_pool(1)["G"] == 1


def test_tap_for_mana_on_already_tapped_returns_none(synthetic_state):
    """Tapping an already-tapped Forest returns None and adds no
    mana (matches the Python convention that a mana ability fails
    its tap-cost on an already-tapped permanent)."""
    forest_id = _forest_id(synthetic_state, 0)
    # Tap the Forest first.
    assert synthetic_state.tap_for_mana(forest_id) == "G"
    assert synthetic_state.get_mana_pool(0)["G"] == 1
    # Second tap is a no-op.
    assert synthetic_state.tap_for_mana(forest_id) is None
    assert synthetic_state.get_mana_pool(0)["G"] == 1


def test_tap_for_mana_on_non_land_returns_none(synthetic_state):
    """Grizzly Bears is a creature, not a land — tap_for_mana
    declines (returns None, no mana, no tap)."""
    bears_id = _bears_id(synthetic_state, 0)
    assert synthetic_state.printing_name_of(bears_id) == "Grizzly Bears"
    assert synthetic_state.tap_for_mana(bears_id) is None
    # The Bears must NOT have been tapped as a side effect.
    assert synthetic_state.is_tapped(bears_id) is False
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_tap_for_mana_unknown_id_returns_none(synthetic_state):
    """An obj_id that doesn't exist on any battlefield is a quiet
    no-op — matches ``tap_object``'s behavior on missing ids."""
    assert synthetic_state.tap_for_mana(999_999) is None


# --- CoW canary -----------------------------------------------------


def test_clone_then_add_mana_does_not_affect_original(synthetic_state):
    """Load-bearing CoW canary. ``Player`` lives by-value in
    ``GameState.players: [Player; 2]``, so cloning the GameState
    deep-copies the Player struct (including its ``ManaPool`` —
    which is itself ``Copy``). A mutation on the clone must not
    bleed back into the original.

    The mana_pool case is structurally identical to life (POD
    embedded by value in Player), so this should "just work" without
    any Arc juggling."""
    cloned = synthetic_state.clone_once()
    cloned.add_mana(0, "G", 4)
    assert cloned.get_mana_pool(0)["G"] == 4
    # Original untouched.
    assert synthetic_state.get_mana_pool(0)["G"] == 0


def test_clone_then_tap_for_mana_does_not_affect_original(synthetic_state):
    """Same canary, but exercising the full tap-for-mana path —
    which mutates BOTH a battlefield ``Arc<Vec<GameObject>>`` (via
    ``Arc::make_mut``) AND the by-value ``ManaPool``. Either side
    leaking into the original would be a CoW bug."""
    forest_id = _forest_id(synthetic_state, 0)
    cloned = synthetic_state.clone_once()
    assert cloned.tap_for_mana(forest_id) == "G"
    # Clone shows the tap + the mana.
    assert cloned.is_tapped(forest_id) is True
    assert cloned.get_mana_pool(0)["G"] == 1
    # Original observed neither.
    assert synthetic_state.is_tapped(forest_id) is False
    assert synthetic_state.get_mana_pool(0)["G"] == 0


# --- pay_mana_cost (CR 202.2) ----------------------------------------


def test_pay_mana_cost_simple_colored(synthetic_state):
    """pool={G:1}, cost={G:1} → True; pool ends empty."""
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.pay_mana_cost(0, {"G": 1}) is True
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0
    }


def test_pay_mana_cost_insufficient_color_returns_false(synthetic_state):
    """pool={W:1}, cost={G:1} → False; pool unchanged.

    A colored pip can only be paid with the matching color — the
    one white in the pool can't satisfy the green requirement.
    No mutation on the rejection path."""
    synthetic_state.add_mana(0, "W", 1)
    assert synthetic_state.pay_mana_cost(0, {"G": 1}) is False
    assert synthetic_state.get_mana_pool(0) == {
        "W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0
    }


def test_pay_mana_cost_generic_drawn_from_any_color(synthetic_state):
    """pool={G:2}, cost={generic:1, G:1} → True; pool ends empty.

    Generic mana is paid with any color (CR 107.4). After the green
    pip is reserved, the second green satisfies the generic 1."""
    synthetic_state.add_mana(0, "G", 2)
    assert synthetic_state.pay_mana_cost(0, {"generic": 1, "G": 1}) is True
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0
    }


def test_pay_mana_cost_insufficient_total_for_generic_returns_false(synthetic_state):
    """pool={G:1}, cost={generic:2} → False; pool unchanged."""
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.pay_mana_cost(0, {"generic": 2}) is False
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0, "any": 0
    }


def test_pay_mana_cost_zero_cost_returns_true(synthetic_state):
    """pool={G:1}, cost={} → True; pool unchanged.

    A zero-mana cost is trivially payable from any pool, including
    an empty one. Mirrors pay_life_cost(0) → True."""
    synthetic_state.add_mana(0, "G", 1)
    assert synthetic_state.pay_mana_cost(0, {}) is True
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0, "any": 0
    }


def test_pay_mana_cost_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.pay_mana_cost(99, {"G": 1})


def test_pay_mana_cost_clone_isolation(synthetic_state):
    """CoW canary — paying on a clone leaves the original pool
    untouched. ManaPool is by-value-Copy in Player, so this should
    "just work" the same way the add_mana clone canary does."""
    synthetic_state.add_mana(0, "G", 2)
    cloned = synthetic_state.clone_once()
    assert cloned.pay_mana_cost(0, {"G": 1}) is True
    assert cloned.get_mana_pool(0)["G"] == 1
    # Original untouched.
    assert synthetic_state.get_mana_pool(0)["G"] == 2


def test_pay_mana_cost_drains_colorless_first_for_generic(synthetic_state):
    """pool={C:1, G:2}, cost={generic:1} → True; pool ends {G:2}.

    Deterministic generic-deduction order is colorless first, then
    WUBRG. Colorless is the most-restricted source (it can ONLY pay
    generic), so draining it first preserves the most flexibility
    for any later cost-payment from the same pool."""
    synthetic_state.add_mana(0, "C", 1)
    synthetic_state.add_mana(0, "G", 2)
    assert synthetic_state.pay_mana_cost(0, {"generic": 1}) is True
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 2, "C": 0, "any": 0
    }


def test_pay_mana_cost_complex_multi_color(synthetic_state):
    """pool={W:1, U:1, B:1, R:1, G:1, C:1}, cost={generic:3, W:1, R:1}
    → True; pool ends {U:0, B:0, G:1} (rest zero).

    Step-by-step:
    1. Reserve colored pips: W:1 → W=0, R:1 → R=0.
       Intermediate pool: {W:0, U:1, B:1, R:0, G:1, C:1}.
    2. Pay generic=3 from order C, W, U, B, R, G (W and R already 0):
       drain C (1) → drain U (1) → drain B (1) → 3 paid.
    3. Final: {W:0, U:0, B:0, R:0, G:1, C:0}."""
    for color in ("W", "U", "B", "R", "G", "C"):
        synthetic_state.add_mana(0, color, 1)
    cost = {"generic": 3, "W": 1, "R": 1}
    assert synthetic_state.pay_mana_cost(0, cost) is True
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0, "any": 0
    }


# --- cross-feature edge-case coverage -------------------------------
#
# These tests exercise mana-pool interactions across slice boundaries:
# Effect dispatch through ``resolve_top_of_stack`` (the ``apply_effect``
# path), the action layer's ``ActivateAbility`` mana-ability arm, phase
# transitions, the cross-engine ``fingerprint`` / ``mana_pool_snapshot``
# projections, and CoW canaries on the cross-feature paths.

# Mirror of ``ZONE_BATTLEFIELD`` in ``state_ops_zones.rs`` so we can use
# ``register_and_inject_object`` to seed a mana-effect-bearing printing
# without poking the registry directly. Matches the constants used in
# ``tests_rust/test_resolve.py``.
ZONE_BATTLEFIELD = 2


def _add_mana_dict(color, amount, name=None):
    """Build a Forest-shaped printing whose effects list contains an
    ``add_mana_to_pool`` entry. Used to drive ``resolve_top_of_stack``
    end-to-end via ``register_and_inject_object`` + ``push_to_stack``.

    Mirrors the helper in ``tests_rust/test_resolve.py`` but kept local
    so this module stays independently importable."""
    return {
        "name": name or f"Test Mana ({color}x{amount})",
        "card_types": ["Land"],
        "effects": [
            {"kind": "add_mana_to_pool", "color": color, "amount": amount}
        ],
    }


def test_add_mana_to_pool_effect_dispatch_updates_pool(synthetic_state):
    """Cross-slice: an ``Effect::AddManaToPool`` reached via
    ``resolve_top_of_stack`` (not the direct ``add_mana`` primitive)
    still mutates the active player's mana pool. Loads the apply_effect
    path, not the slot_mut path."""
    obj_id = synthetic_state.register_and_inject_object(
        _add_mana_dict("G", 2), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.get_mana_pool(0)["G"] == 2


def test_mana_pool_empties_on_advance_phase(
    synthetic_state,
):
    """CR 106.4 — "When a phase or step ends, each player's mana pool
    empties." ``advance_phase`` empties both players' mana pools on
    EVERY phase exit (i.e. once per call, regardless of which phase
    you came from). The closed gap means a caller cannot float mana
    across a phase tick; floating must land within a single phase.

    Pins the closed gap so a future refactor that detaches
    ``advance_phase`` from the mana-empty hook surfaces here. The
    underlying primitive is ``empty_all_mana_pools`` in
    ``state_ops_mana.rs``; ``advance_phase`` mirrors it inline (see
    ``empty_all_mana_pools_inline`` in ``state_ops_steps.rs``)."""
    synthetic_state.add_mana(0, "G", 3)
    assert synthetic_state.get_mana_pool(0)["G"] == 3
    synthetic_state.advance_phase()
    # CR 106.4 fired on phase exit — pool is empty.
    assert synthetic_state.get_mana_pool(0)["G"] == 0
    # And the wrap path (CLEANUP -> UNTAP) also empties — re-stage
    # some mana on p1 and exercise the wrap.
    synthetic_state.add_mana(1, "R", 2)
    synthetic_state.set_phase(11)  # PHASE_CLEANUP
    synthetic_state.advance_phase()
    assert synthetic_state.get_mana_pool(1)["R"] == 0


def test_two_add_mana_to_pool_effects_resolve_in_lifo_order(synthetic_state):
    """Two distinct stack items each with an ``AddManaToPool`` effect
    resolve LIFO (the most recently pushed item resolves first). Their
    contributions accumulate into the same pool color slot."""
    oid1 = synthetic_state.register_and_inject_object(
        _add_mana_dict("G", 2, name="First"), 0, ZONE_BATTLEFIELD
    )
    oid2 = synthetic_state.register_and_inject_object(
        _add_mana_dict("G", 3, name="Second"), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(oid1, 0)
    synthetic_state.push_to_stack(oid2, 0)
    assert synthetic_state.stack_size() == 2

    # Top (oid2, amount=3) resolves first.
    top1 = synthetic_state.resolve_top_of_stack()
    assert top1["source_obj_id"] == oid2
    assert synthetic_state.get_mana_pool(0)["G"] == 3

    # Then the bottom (oid1, amount=2) resolves; total = 5.
    top2 = synthetic_state.resolve_top_of_stack()
    assert top2["source_obj_id"] == oid1
    assert synthetic_state.get_mana_pool(0)["G"] == 5
    assert synthetic_state.is_stack_empty() is True


def test_activate_ability_taps_forest_for_green(synthetic_state):
    """Cross-slice: ``apply_action({'kind': 'activate_ability', ...})``
    on a Forest taps the source and credits the controller's pool —
    the round-25 mana-ability arm in ``state_ops_actions.rs`` mirrors
    the Python ``ActivatedAbility(is_mana_ability=True) + AddManaToPool``
    idiom. Goes through the closed-action enum + dispatcher rather than
    the direct ``tap_for_mana`` primitive."""
    forest_id = _forest_id(synthetic_state, 0)
    assert synthetic_state.is_tapped(forest_id) is False
    assert synthetic_state.get_mana_pool(0)["G"] == 0

    synthetic_state.apply_action(
        {"kind": "activate_ability", "source_id": forest_id, "ability_index": 0}
    )

    assert synthetic_state.is_tapped(forest_id) is True
    assert synthetic_state.get_mana_pool(0)["G"] == 1


def test_activate_ability_credits_source_controller_not_active_player(
    synthetic_state,
):
    """ActivateAbility's mana-ability arm credits the source's
    *controller*, NOT ``state.active_player``. Activating a Forest on
    player 1's battlefield while player 0 is still the active player
    must add green to player 1's pool, not player 0's. This pins the
    round-25 inline dispatch's controller resolution (it reads
    ``state.players[pidx]`` for whichever player owns the source's
    battlefield slot)."""
    assert synthetic_state.active_player == 0
    p1_forest = _forest_id(synthetic_state, 1)

    synthetic_state.apply_action(
        {"kind": "activate_ability", "source_id": p1_forest, "ability_index": 0}
    )

    # Player 1 (source controller) gets the mana; player 0 untouched.
    assert synthetic_state.get_mana_pool(0)["G"] == 0
    assert synthetic_state.get_mana_pool(1)["G"] == 1
    assert synthetic_state.is_tapped(p1_forest) is True


def test_add_mana_isolation_across_players(synthetic_state):
    """Each player's pool is independent: a mutation on player 0's pool
    leaves player 1's pool entirely untouched, and vice versa. Mirrors
    the by-value ``Player`` array in ``GameState.players``."""
    synthetic_state.add_mana(0, "G", 4)
    synthetic_state.add_mana(0, "U", 2)
    # Player 1's pool is still all zero across every color.
    expected_zero = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}
    assert synthetic_state.get_mana_pool(1) == expected_zero

    # Now mutate p1; p0's pool keeps its existing contents.
    synthetic_state.add_mana(1, "R", 1)
    assert synthetic_state.get_mana_pool(0) == {
        "W": 0, "U": 2, "B": 0, "R": 0, "G": 4, "C": 0, "any": 0
    }
    assert synthetic_state.get_mana_pool(1) == {
        "W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "any": 0
    }


def test_add_mana_to_pool_effect_on_clone_does_not_mutate_original(
    synthetic_state,
):
    """CoW canary on the cross-slice effect-dispatch path: cloning the
    state and then resolving an ``AddManaToPool`` effect on the clone
    leaves the original's pool untouched. The clone takes its own
    by-value copy of the ``Player`` struct (and thus of ``ManaPool``)
    — the registry + battlefield Arc bumps don't bleed mutations back
    into the original."""
    # Pre-inject the printing into the original's registry so cloning
    # carries the printing into the clone (Arc<RegistryData> share).
    obj_id = synthetic_state.register_and_inject_object(
        _add_mana_dict("B", 3), 0, ZONE_BATTLEFIELD
    )
    clone = synthetic_state.clone_once()
    clone.push_to_stack(obj_id, 0)
    clone.resolve_top_of_stack()
    # Clone's pool gained 3 black; original's pool is still empty.
    assert clone.get_mana_pool(0)["B"] == 3
    assert synthetic_state.get_mana_pool(0)["B"] == 0


def test_fingerprint_differs_when_mana_pool_color_or_amount_differs(
    synthetic_state,
):
    """The fingerprint folds the mana pool into the gameplay-hash
    (``state_ops_fingerprint.rs::player_signature`` emits a sorted
    ``[key, count]`` list). Two states that differ ONLY in mana pool
    contents — same color but different amount, or same amount but
    different color — must produce different fingerprints. A state
    that returns to the original pool returns to the original
    fingerprint."""
    fp_empty = synthetic_state.fingerprint()
    synthetic_state.add_mana(0, "G", 1)
    fp_g1 = synthetic_state.fingerprint()
    assert fp_g1 != fp_empty

    # Different amount: G:1 vs G:2.
    synthetic_state.add_mana(0, "G", 1)
    fp_g2 = synthetic_state.fingerprint()
    assert fp_g2 != fp_g1
    assert fp_g2 != fp_empty

    # Different color: a fresh state with W:1 must not collide with G:1.
    other = synthetic_state.clone_once()  # carries G:2 forward
    other.empty_mana_pool(0)
    other.add_mana(0, "W", 1)
    fp_w1 = other.fingerprint()
    # Build a second fresh-empty state and compare W:1 vs G:1 directly.
    # (The cloned `other` has the same registry/zones as synthetic_state
    # so the only diff is the pool.)
    assert fp_w1 != fp_g1
    assert fp_w1 != fp_g2

    # Round-trip: drain the pool and the fingerprint returns to the
    # initial-empty digest.
    synthetic_state.empty_mana_pool(0)
    assert synthetic_state.fingerprint() == fp_empty


def test_mana_pool_snapshot_matches_get_mana_pool_after_mutations(
    synthetic_state,
):
    """``mana_pool_snapshot(p)`` (the parity-harness projection) and
    ``get_mana_pool(p)`` return the same 6-key dict at every point: at
    the empty seed, after mid-color mutations, and after a full empty.
    Both are read-only projections of the same underlying ``ManaPool``
    struct — they must agree by construction."""
    # Seed empty.
    assert synthetic_state.mana_pool_snapshot(0) == synthetic_state.get_mana_pool(0)

    # Mutate across multiple colors.
    synthetic_state.add_mana(0, "G", 2)
    synthetic_state.add_mana(0, "W", 1)
    synthetic_state.add_mana(0, "C", 3)
    snap = synthetic_state.mana_pool_snapshot(0)
    pool = synthetic_state.get_mana_pool(0)
    assert snap == pool
    assert snap == {"W": 1, "U": 0, "B": 0, "R": 0, "G": 2, "C": 3, "any": 0}

    # Drain and re-check.
    synthetic_state.empty_mana_pool(0)
    assert synthetic_state.mana_pool_snapshot(0) == synthetic_state.get_mana_pool(0)
    assert synthetic_state.mana_pool_snapshot(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0
    }


def test_multi_color_pool_entries_coexist(synthetic_state):
    """Adding mana of different colors to the same player's pool does
    NOT collapse colors together — each WUBRG/C slot is independently
    addressable. Two consecutive ``add_mana`` calls with different
    colors leave both colors' counts non-zero, and a third call to a
    third color stacks on without touching the first two."""
    synthetic_state.add_mana(0, "W", 2)
    synthetic_state.add_mana(0, "G", 3)
    pool = synthetic_state.get_mana_pool(0)
    assert pool["W"] == 2
    assert pool["G"] == 3
    # Other colors stay zero.
    assert pool["U"] == 0
    assert pool["B"] == 0
    assert pool["R"] == 0
    assert pool["C"] == 0

    # Stack on a third color; first two are untouched.
    synthetic_state.add_mana(0, "C", 1)
    pool = synthetic_state.get_mana_pool(0)
    assert pool == {"W": 2, "U": 0, "B": 0, "R": 0, "G": 3, "C": 1, "any": 0}

    # Pay a cost that consumes from two colors + generic; the
    # untouched slot stays put.
    assert synthetic_state.pay_mana_cost(0, {"W": 1, "G": 1, "generic": 1}) is True
    pool = synthetic_state.get_mana_pool(0)
    # generic drains from C first (deterministic order), so C goes
    # 1->0; W goes 2->1; G goes 3->2.
    assert pool == {"W": 1, "U": 0, "B": 0, "R": 0, "G": 2, "C": 0, "any": 0}


def test_add_mana_to_pool_effect_rejects_negative_amount_at_register_time(
    synthetic_state,
):
    """**Quirk: negative-amount AddManaToPool is rejected by the
    bridge parser, not at apply_effect time.** The Rust bridge's
    ``parse_effect`` enforces ``amount >= 0`` when reading the printing
    dict's ``add_mana_to_pool`` entry, so an ill-formed printing fails
    *registration* with a ``ValueError`` rather than reaching the
    stack-resolution path. This mirrors the direct ``add_mana(p, c,
    -1)`` raise (test_add_mana_negative_amount_raises) — there's no
    silent-no-op path for negative-amount mana addition anywhere.

    Pinning this at the test layer ensures a future bridge refactor
    that loosens parse-time validation surfaces here loudly instead of
    silently letting bogus negative effects through to the apply
    path."""
    with pytest.raises(ValueError):
        synthetic_state.register_and_inject_object(
            _add_mana_dict("G", -1, name="BadMana"),
            0,
            ZONE_BATTLEFIELD,
        )
    # State after the rejected register is unmutated: pool stays empty.
    expected_zero = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}
    assert synthetic_state.get_mana_pool(0) == expected_zero
    assert synthetic_state.get_mana_pool(1) == expected_zero


# -------------------- Round-28 AddNManaOfChosenColor (4 cards) --------------------


def _lotus_field_dict(amount: int = 3, options=None):
    """Lotus-Field-shape: add N mana of any one color (options-driven
    deterministic-pick-first in first-slice)."""
    spec = {
        "name": "Synthetic Lotus Field",
        "card_types": ["Land"],
        "effects": [
            {
                "kind": "add_n_mana_of_chosen_color",
                "amount": amount,
            }
        ],
    }
    if options is not None:
        spec["effects"][0]["options"] = options
    return spec


def test_register_add_n_mana_of_chosen_color_default_options(empty_registry):
    pid = empty_registry.register_printing(_lotus_field_dict(amount=3))
    effects = empty_registry.get_printing_effects(pid)
    assert effects[0]["kind"] == "add_n_mana_of_chosen_color"
    assert effects[0]["amount"] == 3
    # Default options: W/U/B/R/G (no C in the default set; mirrors
    # Python's `options: tuple[str, ...] = ("W", "U", "B", "R", "G")`).
    assert effects[0]["options"] == ["W", "U", "B", "R", "G"]


def test_register_add_n_mana_of_chosen_color_explicit_options(empty_registry):
    pid = empty_registry.register_printing(
        _lotus_field_dict(amount=2, options=["G", "R"])
    )
    effects = empty_registry.get_printing_effects(pid)
    assert effects[0]["options"] == ["G", "R"]


def test_register_add_n_mana_missing_amount_raises(empty_registry):
    import pytest
    with pytest.raises(ValueError, match="missing required 'amount'"):
        empty_registry.register_printing(
            {
                "name": "no-amount",
                "card_types": ["Land"],
                "effects": [{"kind": "add_n_mana_of_chosen_color"}],
            }
        )


def test_register_add_n_mana_negative_amount_raises(empty_registry):
    import pytest
    with pytest.raises(ValueError, match="non-negative"):
        empty_registry.register_printing(_lotus_field_dict(amount=-1))


def test_register_add_n_mana_invalid_color_raises(empty_registry):
    import pytest
    with pytest.raises(ValueError, match="unknown color"):
        empty_registry.register_printing(
            _lotus_field_dict(amount=1, options=["X"])
        )


def test_register_add_n_mana_empty_options_raises(empty_registry):
    import pytest
    with pytest.raises(ValueError, match="options must be non-empty"):
        empty_registry.register_printing(_lotus_field_dict(amount=1, options=[]))


def test_resolve_add_n_mana_picks_first_option_default_w(synthetic_state):
    """Default options is (W, U, B, R, G); first-slice deterministic
    pick is W. Resolving adds amount White mana to controller's pool."""
    pool_before_w = synthetic_state.get_mana_pool(0)["W"]
    spell_id = synthetic_state.register_and_inject_object(
        _lotus_field_dict(amount=3), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_mana_pool(0)["W"] == pool_before_w + 3


def test_resolve_add_n_mana_picks_first_option_custom_green(synthetic_state):
    """options=[G,R,U] -> picks G (first), mints amount green mana."""
    pool_before_g = synthetic_state.get_mana_pool(0)["G"]
    spell_id = synthetic_state.register_and_inject_object(
        _lotus_field_dict(amount=2, options=["G", "R", "U"]), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_mana_pool(0)["G"] == pool_before_g + 2


def test_resolve_add_n_mana_amount_zero_is_noop(synthetic_state):
    """amount=0 short-circuits; no pool change."""
    pool_before = synthetic_state.get_mana_pool(0)
    spell_id = synthetic_state.register_and_inject_object(
        _lotus_field_dict(amount=0), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    pool_after = synthetic_state.get_mana_pool(0)
    assert pool_after == pool_before


def test_resolve_add_n_mana_clone_isolation(synthetic_state):
    spell_id = synthetic_state.register_and_inject_object(
        _lotus_field_dict(amount=4, options=["R"]), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(spell_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    assert cloned.get_mana_pool(0)["R"] == synthetic_state.get_mana_pool(0)["R"] + 4
