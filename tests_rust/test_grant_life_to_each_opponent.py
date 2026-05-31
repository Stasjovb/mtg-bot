"""Rust-engine unit pins for the ``Effect::GrantLifeToEachOpponent``
parse + to_pydict + resolve arms.

**Grove of the Burnwillows substrate (2026-05-31 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#3 Grove).**
The Rust Effect variant carries one field (`amount: i32`); each
opponent of the source-controller GAINS `amount` life. Life-GAIN
sister of round-26's `Effect::EachOpponentLosesLife` — identical
source-finder dispatch (5-zone walk + stack scan) + recipient set
(each opponent of the source-controller), only the apply step flips
from `saturating_sub` to `saturating_add` (+ a `life_gained_this_turn`
tracker increment mirroring Python's `game.gain_life`).

These pins drive the new resolve arm DIRECTLY via the
``apply_action({"kind": "activate_ability", ...})`` path on a synthetic
Grove-AA[1]-shape Land whose AA effect is the bare
``grant_life_to_each_opponent`` leaf (NOT wrapped in a Sequence, so
this module pins the leaf's resolve in isolation). The Sequence-IN-AA
admit + the cross-engine bridge round-trip are covered by the sibling
probe at ``tests/test_grove_of_the_burnwillows_parity.py``; this module
pins the Rust-engine-side resolve semantics that the bridge relies on.

Covered:

  - parse_effect arm accepts the 2-key dict shape (kind + amount).
  - parse_effect rejects a negative amount at register time.
  - Resolve: the one opponent of the source-controller gains `amount`
    life; the controller is untouched.
  - Source-controller scoping: the gain applies to the opponent of the
    SOURCE's controller, not active_player.
  - amount=0 is a legal no-op.
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2


def _grove_life_dict(amount: int = 1):
    """Synthetic Grove-AA[1]-leaf-shape Land printing dict — the bare
    ``grant_life_to_each_opponent`` leaf as a mana-ability AA.
    """
    return {
        "name": "Synthetic Grove Life",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "grant_life_to_each_opponent",
                    "amount": amount,
                },
                "is_mana_ability": True,
            },
        ],
    }


# ---------------------------------------------------------------------------
# parse_effect + register pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new ``grant_life_to_each_opponent``
    parse arm consumes the 2-key dict shape (kind + amount) and
    registers cleanly.
    """
    pid = empty_registry.register_printing(_grove_life_dict(1))
    assert empty_registry.get_printing_name(pid) == "Synthetic Grove Life"


def test_register_rejects_negative_amount(empty_registry):
    """**parse_effect arm pin — raise-on-negative.** A negative amount
    is schema nonsense ("each opponent gains -1 life"); the parse arm
    rejects it at register time (defense-in-depth; the resolve arm
    re-checks).
    """
    with pytest.raises(Exception):
        empty_registry.register_printing(_grove_life_dict(-1))


# ---------------------------------------------------------------------------
# Resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_opponent_gains_life(engine):
    """**Resolve arm pin — default scenario.** Source-controller p0
    activates; the one opponent (p1) gains 1 life. p0 is untouched.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    src = s.register_and_inject_object(
        _grove_life_dict(1), 0, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(src, False)
    life_p0_pre = s.get_life(0)
    life_p1_pre = s.get_life(1)
    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })
    assert s.get_life(1) == life_p1_pre + 1, (
        f"Opponent must gain 1 life; got {s.get_life(1)} "
        f"(pre {life_p1_pre})"
    )
    assert s.get_life(0) == life_p0_pre, (
        f"Source-controller (p0) must be untouched; got {s.get_life(0)}"
    )


def test_resolve_alt_amount(engine):
    """**Resolve arm pin — parameterized amount.** A hypothetical
    `amount=3` printing grants the opponent 3 life.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    src = s.register_and_inject_object(
        _grove_life_dict(3), 0, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(src, False)
    life_p1_pre = s.get_life(1)
    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })
    assert s.get_life(1) == life_p1_pre + 3


def test_resolve_source_controller_scoping(engine):
    """**Source-controller fan-out pin.** The source is controlled by
    p1; the "each opponent" recipient is therefore p0 (the opponent of
    the SOURCE's controller, NOT active_player). p1 (the controller) is
    untouched.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    src = s.register_and_inject_object(
        _grove_life_dict(1), 1, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(src, False)
    life_p0_pre = s.get_life(0)
    life_p1_pre = s.get_life(1)
    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })
    # p0 (the opponent of source-controller p1) gains the life.
    assert s.get_life(0) == life_p0_pre + 1
    # p1 (the source-controller) is untouched.
    assert s.get_life(1) == life_p1_pre


def test_resolve_amount_zero_is_noop(engine):
    """**Resolve arm pin — amount=0 legal no-op.** Mirrors the
    GainLife / EachOpponentLosesLife zero-amount conventions: zero
    grants nothing, both lives unchanged.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    src = s.register_and_inject_object(
        _grove_life_dict(0), 0, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(src, False)
    life_p0_pre = s.get_life(0)
    life_p1_pre = s.get_life(1)
    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })
    assert s.get_life(0) == life_p0_pre
    assert s.get_life(1) == life_p1_pre
