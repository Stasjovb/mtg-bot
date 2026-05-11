"""Life modification primitives on the Rust ``GameState``.

Ported from Python's ``src/mtg_bot/game.py`` (the ``gain_life`` helper
and the many ``p.life -= amount`` direct mutations scattered through
``effects/``, ``combat.py``, and ``actions.py``). The Python side
exposes only ``gain_life`` as a named helper — there is no
``lose_life`` or ``set_life`` function — so the Rust API surface here
is a small generalization rather than a one-to-one port.

**Negative-amount semantics decision** (documented divergence from
Python): the Python ``gain_life`` silently no-ops on
``amount <= 0`` (returns 0, makes no mutation). The Rust port raises
``ValueError`` on a negative ``amount`` for ``gain_life`` /
``lose_life`` instead. Rationale: silent no-ops on bad inputs are a
known anti-pattern in this codebase (see the user's
"silent no-op pipeline runs are pipeline bugs" guidance) — the engine
should fail loudly when a caller passes nonsense. ``amount = 0`` is
allowed and is a true no-op (it's a legitimate value, not an error).

**No clamping at zero**: ``lose_life`` allows the result to go
negative. The engine reports raw life totals; "loss at 0" is a
state-based action concern handled at a higher layer (not yet
implemented in Rust).
"""

from __future__ import annotations

import pytest


def test_initial_life_is_twenty(synthetic_state):
    assert synthetic_state.life_totals == [20, 20]


def test_get_life_returns_player_life(synthetic_state):
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20


def test_get_life_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.get_life(99)


def test_set_life_changes_only_target_player(synthetic_state):
    synthetic_state.set_life(0, 15)
    assert synthetic_state.get_life(0) == 15
    assert synthetic_state.get_life(1) == 20
    assert synthetic_state.life_totals == [15, 20]


def test_set_life_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.set_life(99, 10)


def test_lose_life_subtracts(synthetic_state):
    synthetic_state.lose_life(0, 5)
    assert synthetic_state.get_life(0) == 15
    assert synthetic_state.get_life(1) == 20


def test_gain_life_adds(synthetic_state):
    synthetic_state.gain_life(0, 5)
    assert synthetic_state.get_life(0) == 25
    assert synthetic_state.get_life(1) == 20


def test_lose_life_can_go_negative(synthetic_state):
    # Engine reports raw life; "loss at 0" is a state-based action
    # at a higher layer, not implemented here.
    synthetic_state.lose_life(0, 25)
    assert synthetic_state.get_life(0) == -5


def test_lose_life_negative_amount_rejects(synthetic_state):
    # Documented divergence from Python's silent no-op:
    # the Rust engine raises on negative `amount`.
    with pytest.raises(ValueError):
        synthetic_state.lose_life(0, -3)
    # State must be untouched after the rejected call.
    assert synthetic_state.get_life(0) == 20


def test_gain_life_negative_amount_rejects(synthetic_state):
    with pytest.raises(ValueError):
        synthetic_state.gain_life(0, -3)
    assert synthetic_state.get_life(0) == 20


def test_lose_life_zero_amount_is_noop(synthetic_state):
    synthetic_state.lose_life(0, 0)
    assert synthetic_state.get_life(0) == 20


def test_gain_life_zero_amount_is_noop(synthetic_state):
    synthetic_state.gain_life(0, 0)
    assert synthetic_state.get_life(0) == 20


def test_clone_preserves_life_totals(synthetic_state):
    synthetic_state.set_life(0, 12)
    synthetic_state.set_life(1, 17)
    cloned = synthetic_state.clone_once()
    assert cloned.life_totals == [12, 17]


def test_modify_one_clone_does_not_affect_other(synthetic_state):
    # Load-bearing CoW test: Player is held by-value in
    # GameState.players, so cloning the GameState copies the Player,
    # and a life mutation on the clone must not bleed back into the
    # original.
    cloned = synthetic_state.clone_once()
    cloned.set_life(0, 1)
    cloned.lose_life(1, 7)
    assert cloned.life_totals == [1, 13]
    assert synthetic_state.life_totals == [20, 20]


def test_set_life_to_negative_value_is_allowed(synthetic_state):
    # `set_life` is a raw setter — no clamping, no sign restriction.
    synthetic_state.set_life(0, -5)
    assert synthetic_state.get_life(0) == -5


# ---------------------------------------------------------------------------
# pay_life_cost — CR 118.4 cost-payment counterpart to lose_life.
#
# Costs are checked-then-paid: a player can pay X life as a cost only if
# their current life total is strictly greater than X (paying X would
# drop them to current - X, which must be >= 1; CR 118.4: "A player
# can't pay more life than they have"). Concretely, the no-pay-to-die
# rule means pay_life_cost(life=5, amount=5) returns False — paying it
# would zero them out, which isn't allowed for a voluntary cost.
#
# Returns True on successful payment (life decremented), False on
# inability to pay (life unchanged). amount=0 is a no-op success.
# Negative amount and unknown player_id raise (matches gain/lose_life).
# ---------------------------------------------------------------------------


def test_pay_life_cost_decrements_life(synthetic_state):
    assert synthetic_state.pay_life_cost(0, 5) is True
    assert synthetic_state.get_life(0) == 15
    assert synthetic_state.get_life(1) == 20


def test_pay_life_cost_zero_amount_is_noop_success(synthetic_state):
    assert synthetic_state.pay_life_cost(0, 0) is True
    assert synthetic_state.get_life(0) == 20


def test_pay_life_cost_negative_amount_raises(synthetic_state):
    with pytest.raises(ValueError):
        synthetic_state.pay_life_cost(0, -1)
    assert synthetic_state.get_life(0) == 20


def test_pay_life_cost_unknown_player_raises(synthetic_state):
    with pytest.raises((ValueError, IndexError, OverflowError)):
        synthetic_state.pay_life_cost(99, 1)


def test_pay_life_cost_exact_life_returns_false(synthetic_state):
    # Paying 5 life when at 5 would zero the player; not allowed for a
    # voluntary cost (CR 118.4 — can't pay more life than you have, and
    # going to 0 from a cost is the no-pay-to-die boundary).
    synthetic_state.set_life(0, 5)
    assert synthetic_state.pay_life_cost(0, 5) is False
    assert synthetic_state.get_life(0) == 5


def test_pay_life_cost_more_than_life_returns_false(synthetic_state):
    synthetic_state.set_life(0, 3)
    assert synthetic_state.pay_life_cost(0, 7) is False
    assert synthetic_state.get_life(0) == 3


def test_pay_life_cost_one_less_than_life_returns_true(synthetic_state):
    # Paying life - 1 leaves the player at 1; that's the legal boundary.
    synthetic_state.set_life(0, 5)
    assert synthetic_state.pay_life_cost(0, 4) is True
    assert synthetic_state.get_life(0) == 1


def test_pay_life_cost_clone_preserves(synthetic_state):
    # CoW canary: paying life on a clone must not bleed back into the
    # original.
    cloned = synthetic_state.clone_once()
    assert cloned.pay_life_cost(0, 7) is True
    assert cloned.get_life(0) == 13
    assert synthetic_state.get_life(0) == 20


# ---------------------------------------------------------------------------
# Cross-feature edge cases — life-total interactions with the wider engine.
#
# The tests above cover the bare life primitives in isolation. The block
# below threads life through the higher layers: `Effect` dispatch via
# `resolve_top_of_stack` (LoseLife / TargetOpponentLosesLife /
# EachOpponentLosesLife / GainLife / DealDamage-to-player), the CR-119.3
# distinction between life loss and damage, the SBA + winloss derivation
# from raw life totals, the fingerprint's sensitivity to life-total
# changes, and the CoW canary across clones for the player-life path.
#
# These tests compose existing primitives — none of them probes new Rust
# behavior. They lock down the cross-feature contract so a future
# refactor that breaks (e.g.) the EachOpponent → controller-opponent
# routing or the SBA's life<=0 derivation surfaces here.
# ---------------------------------------------------------------------------


# Zone constants — mirror `tests_rust/test_resolve.py` (and
# `rust/src/state_ops_zones.rs`).
ZONE_HAND = 0
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _lose_life_dict(amount=2):
    """A self-life-loss printing — Decode-Transmissions-shaped.
    Source's controller loses `amount` life on resolve."""
    return {
        "name": f"Test SelfLoseLife (x{amount})",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1, "generic": 2},
        "effects": [{"kind": "lose_life", "amount": amount}],
    }


def _target_opponent_loses_life_dict(amount=2):
    """A target-opponent-life-loss printing — Dubious-Delicacy-shaped.
    The one opponent loses `amount` life on resolve."""
    return {
        "name": f"Test TargetOppLose (x{amount})",
        "card_types": ["Sorcery"],
        "mana_cost": {"generic": 2},
        "effects": [{"kind": "target_opponent_loses_life", "amount": amount}],
    }


def _each_opponent_loses_life_dict(amount=2):
    """An each-opponent-life-loss printing — Balemurk-Leech-shaped.
    Every opponent of the source's controller loses `amount` life."""
    return {
        "name": f"Test EachOppLose (x{amount})",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1, "generic": 1},
        "effects": [{"kind": "each_opponent_loses_life", "amount": amount}],
    }


def _gain_life_dict(amount=3):
    """A gain-life printing — Healing-Salve-shaped."""
    return {
        "name": f"Test GainLife (x{amount})",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [{"kind": "gain_life", "amount": amount}],
    }


def _deal_damage_to_player_dict(amount=3):
    """A direct-damage-to-player printing — Bombard-shaped.
    `deal_damage` with target=any_player. Per CR 119.3 this is
    distinct from `lose_life`: real-MTG damage prevention /
    replacement effects can intercept this arm but not the
    life-loss arm. The first-slice Rust dispatch collapses both
    to "subtract from defender's life" (no prevention layer yet),
    so today these two land identical life deltas — this test
    pins that observable behavior."""
    return {
        "name": f"Test PlayerBurn (x{amount})",
        "card_types": ["Sorcery"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [
            {
                "kind": "deal_damage",
                "amount": amount,
                "target": {"kind": "any_player"},
            }
        ],
    }


def test_effect_lose_life_decrements_controller_only(synthetic_state):
    """`Effect::LoseLife` apply_effect path — resolving a LoseLife
    spell controlled by p0 decrements p0's life (the controller),
    NOT p1's. Cross-feature: composes register_and_inject_object +
    push_to_stack + resolve_top_of_stack + apply_effect's LoseLife
    arm + the bare `players[idx].life -= amount` write."""
    src_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(amount=4), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # p0 (controller) -4; p1 untouched. Distinct from the
    # EachOpponent / TargetOpponent arms which hit the opponent.
    assert synthetic_state.get_life(0) == 16
    assert synthetic_state.get_life(1) == 20


def test_effect_target_opponent_loses_life_hits_only_opponent(
    synthetic_state,
):
    """`Effect::TargetOpponentLosesLife` apply_effect path — only the
    opponent of the source's controller is decremented; the
    controller is untouched. Mirrors the LoseLife test inversion."""
    src_id = synthetic_state.register_and_inject_object(
        _target_opponent_loses_life_dict(amount=5), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # p1 (the one opponent) -5; p0 (controller) untouched.
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 15


def test_effect_each_opponent_loses_life_hits_every_non_controller(
    synthetic_state,
):
    """`Effect::EachOpponentLosesLife` apply_effect path — in 2-player
    this reduces to "the one opponent", but the test pins the
    every-non-controller routing semantics. Crucially: p0 (the
    source's controller) MUST be unaffected — a regression that
    routed through LoseLife would decrement p0 instead of p1."""
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_loses_life_dict(amount=3), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # p0 (controller) untouched; p1 (every opponent of p0) -3.
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 17


def test_life_loss_to_zero_triggers_sba_loss_outcome(synthetic_state):
    """Cross-feature: LoseLife + apply_sbas_until_quiescent →
    winloss derivation. A LoseLife-20 effect controlled by p0
    drops p0 to exactly 0; after one quiescent SBA pass, the
    pure-derivation winloss flags p0 as a loser and p1 as winner.
    Composes round-1 life + round-24 LoseLife dispatch + round-15
    SBA loop + winloss `losers()` / `winner()` / `is_game_over()`."""
    src_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(amount=20), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # p0 dropped from 20 → 0. Below the alive-threshold (CR
    # 104.3a: 0 or less life loses).
    assert synthetic_state.get_life(0) == 0
    # SBA pass observes life<=0 (the pure-derivation winloss path
    # picks this up; the SBA loop itself doesn't carry a life-loss
    # action, but `losers()` is computed at-read from current
    # life totals).
    synthetic_state.apply_sbas_until_quiescent()
    assert list(synthetic_state.losers()) == [0]
    assert synthetic_state.winner() == 1
    assert synthetic_state.is_game_over() is True


def test_life_loss_past_zero_via_each_opponent_triggers_loss(
    synthetic_state,
):
    """A more-than-lethal EachOpponentLosesLife (25 against 20 life)
    drops p1 to -5 — still flagged as a loser, winner=p0. Pins
    that the "loss at 0 OR BELOW" boundary holds for overkill
    routed through the each-opponent arm, not just self-LoseLife."""
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_loses_life_dict(amount=25), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # p1 -25, well past zero.
    assert synthetic_state.get_life(1) == -5
    synthetic_state.apply_sbas_until_quiescent()
    assert list(synthetic_state.losers()) == [1]
    assert synthetic_state.winner() == 0
    assert synthetic_state.is_game_over() is True


def test_effect_deal_damage_and_lose_life_land_same_delta(synthetic_state):
    """CR 119.3 distinguishes "damage" (DealDamage) from "life loss"
    (LoseLife): real MTG routes damage through prevention /
    replacement layers but life loss bypasses them. The first-slice
    Rust dispatch hasn't grown a prevention layer yet, so both arms
    land identical life deltas today — pin that observable parity so
    a future divergence (when the prevention layer arrives) shows up
    as a deliberate test update, not a silent semantic drift.
    Crucially, both arms exist as distinct apply_effect branches —
    so resolving each on a fresh state with the same amount yields
    identical observable life totals."""
    # Arm 1: DealDamage to AnyPlayer.
    burn_id = synthetic_state.register_and_inject_object(
        _deal_damage_to_player_dict(amount=4), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(burn_id, 0)
    synthetic_state.resolve_top_of_stack()
    p1_after_burn = synthetic_state.get_life(1)
    assert p1_after_burn == 16  # 20 - 4

    # Arm 2: TargetOpponentLosesLife with the SAME amount on a
    # clone-equivalent fresh state. Same defender, same amount —
    # same end-state life total.
    fresh = synthetic_state.clone_once()
    fresh.set_life(1, 20)  # reset to baseline for apples-to-apples
    lose_id = fresh.register_and_inject_object(
        _target_opponent_loses_life_dict(amount=4), 0, ZONE_BATTLEFIELD
    )
    fresh.push_to_stack(lose_id, 0)
    fresh.resolve_top_of_stack()
    p1_after_lose = fresh.get_life(1)
    assert p1_after_lose == 16  # identical to burn arm today
    assert p1_after_burn == p1_after_lose


def test_effect_gain_life_positive_delta(synthetic_state):
    """`Effect::GainLife` apply_effect path — positive delta only.
    Resolving a GainLife-7 instant takes the controller from 20 to
    27; the opponent is untouched. Pins that the GainLife arm
    routes additively, not by replacement, and that it targets the
    controller (not the opponent)."""
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.get_life(1) == 20
    src_id = synthetic_state.register_and_inject_object(
        _gain_life_dict(amount=7), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Controller (p0) gained 7; opponent untouched.
    assert synthetic_state.get_life(0) == 27
    assert synthetic_state.get_life(1) == 20


def test_clone_isolates_life_after_effect_resolution(synthetic_state):
    """CoW canary across the apply_effect path. Same load-bearing
    invariant as the bare-primitive
    `test_modify_one_clone_does_not_affect_other`, but exercised
    via stack resolution (a different code path that goes through
    `state_ops_resolve.rs`'s direct `state.players[idx].life`
    write). Mutating life on the clone via Effect dispatch must
    not bleed back into the original."""
    # Pre-load a LoseLife-7 spell on the original's stack so both
    # sides observe the same starting topology.
    src_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(amount=7), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    assert synthetic_state.get_life(0) == 20

    # Clone, then resolve only on the clone.
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone diverged: p0 lost 7 (controller of LoseLife).
    assert cloned.get_life(0) == 13
    assert cloned.is_stack_empty() is True
    # Original untouched in BOTH life and stack — CoW canary.
    assert synthetic_state.get_life(0) == 20
    assert synthetic_state.stack_size() == 1


def test_fingerprint_changes_when_life_differs_via_effect(synthetic_state):
    """Parity-critical: the 12-char SHA1 state fingerprint includes
    life totals. After a LoseLife-2 effect resolves and changes
    p0's life, the fingerprint MUST change. Symmetric with the
    direct-primitive `test_fingerprint_changes_when_life_changes`
    in `test_fingerprint.py`, but exercised via the apply_effect
    pathway so both code paths share the parity contract."""
    fp_before = synthetic_state.fingerprint()
    src_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(amount=2), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_life(0) == 18
    fp_after = synthetic_state.fingerprint()
    assert fp_after != fp_before


def test_multi_effect_sequence_gain_then_lose_net_delta(synthetic_state):
    """A multi-resolution sequence: gain 5, then lose 8 — the net
    delta against the controller's starting 20 is -3 (final = 17).
    Pins that gain and lose compose additively without weird
    interaction (no cap, no floor, no replacement-order ambiguity)."""
    p0_before = synthetic_state.get_life(0)
    assert p0_before == 20

    # +5 (gain).
    gain_id = synthetic_state.register_and_inject_object(
        _gain_life_dict(amount=5), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(gain_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.get_life(0) == 25

    # -8 (lose, controller-targeted via LoseLife).
    lose_id = synthetic_state.register_and_inject_object(
        _lose_life_dict(amount=8), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(lose_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Net: +5 - 8 = -3 from baseline.
    assert synthetic_state.get_life(0) == p0_before - 3
    # Reverse-order verification on a clean clone — lose-first,
    # then gain — must land the same end-state (commutative).
    other = synthetic_state.clone_once()
    other.set_life(0, p0_before)
    lose_first = other.register_and_inject_object(
        _lose_life_dict(amount=8), 0, ZONE_BATTLEFIELD
    )
    other.push_to_stack(lose_first, 0)
    other.resolve_top_of_stack()
    gain_after = other.register_and_inject_object(
        _gain_life_dict(amount=5), 0, ZONE_HAND
    )
    other.push_to_stack(gain_after, 0)
    other.resolve_top_of_stack()
    assert other.get_life(0) == p0_before - 3


def test_get_life_agrees_with_life_totals_after_effect(synthetic_state):
    """The two read paths (`get_life(i)` and the `life_totals`
    snapshot list) must agree byte-for-byte after a mutation goes
    through the apply_effect pathway. Pins that the snapshot
    getter isn't a stale cached copy — it reads through to the
    same `players[i].life` field."""
    # Mutate via EachOpponentLosesLife so p1 ends at a non-baseline
    # value (17), while p0 stays at 20.
    src_id = synthetic_state.register_and_inject_object(
        _each_opponent_loses_life_dict(amount=3), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Both read paths must agree.
    snapshot = list(synthetic_state.life_totals)
    assert snapshot == [synthetic_state.get_life(0), synthetic_state.get_life(1)]
    assert snapshot == [20, 17]
