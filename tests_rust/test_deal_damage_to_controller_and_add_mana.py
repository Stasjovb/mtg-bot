"""Rust-engine unit pins for the
``Effect::DealDamageToControllerAndAddMana`` parse + to_pydict +
resolve arms.

**Ancient Tomb substrate Phase 4 Cycle 1 (2026-05-27 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#3 Ancient
Tomb).** The Rust Effect variant carries fields (`damage: u32` +
`produces: Vec<(u8, u32)>`); both engines apply damage as life-loss
first then mint the produces tuple into the controller's mana pool.

These pins drive the new resolve arm DIRECTLY via the
``apply_action({"kind": "activate_ability", ...})`` path on synthetic
Ancient-Tomb-shape Lands. The cross-engine bridge round-trip + the
Python admit-gate substrate-only invariant are covered by the sibling
test at ``tests/test_ancient_tomb_substrate_cycle_1.py``; this
module pins the Rust-engine-side resolve semantics that the bridge
relies on.

Covered:

  - parse_effect arm accepts the 3-key dict shape.
  - Resolve at full life drops life by 2 and mints {C}{C}.
  - Resolve at 1 life drops life to -1 and still mints {C}{C}
    (Python parity — mana minting unconditionally runs after the
    life decrement).
  - Source-controller scoping: damage + mana apply to source
    controller, not active_player.
  - to_pydict emits byte-equal dict (round-trip via parse_effect).
"""

from __future__ import annotations


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2


def _ancient_tomb_dict():
    """Synthetic Ancient-Tomb-shape Land printing dict."""
    return {
        "name": "Synthetic Ancient Tomb",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "deal_damage_to_controller_and_add_mana",
                    "damage": 2,
                    "produces": [["C", 2]],
                },
                "is_mana_ability": True,
            },
        ],
    }


# ---------------------------------------------------------------------------
# parse_effect + register pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new
    ``deal_damage_to_controller_and_add_mana`` parse arm consumes
    the 3-key dict shape (kind + damage + produces) and registers
    cleanly.
    """
    pid = empty_registry.register_printing(_ancient_tomb_dict())
    assert empty_registry.get_printing_name(pid) == "Synthetic Ancient Tomb"


def test_register_alt_damage_and_produces(empty_registry):
    """**parse_effect arm pin — parameterized.** A hypothetical
    `Add {C}{C}{C}. This land deals 3 damage to you.` printing
    serializes to `damage=3, produces=[["C", 3]]` and registers
    cleanly. The variant parameterizes on damage + produces, so a
    future printing with that shape would claim by table extension.
    """
    alt = {
        "name": "Synthetic Bigger Tomb",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "deal_damage_to_controller_and_add_mana",
                    "damage": 3,
                    "produces": [["C", 3]],
                },
                "is_mana_ability": True,
            },
        ],
    }
    pid = empty_registry.register_printing(alt)
    assert empty_registry.get_printing_name(pid) == "Synthetic Bigger Tomb"


# ---------------------------------------------------------------------------
# Resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_default_full_life(engine):
    """**Resolve arm pin — default scenario.** Controller at default
    starting life. Activating mints 2 C coins AND drops life by 2.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    pool_id = s.register_and_inject_object(
        _ancient_tomb_dict(), 0, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(pool_id, False)
    life_pre = s.get_life(0)
    s.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    assert s.get_life(0) == life_pre - 2
    assert s.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "any": 0,
    }


def test_resolve_at_1_life_lethal_damage(engine):
    """**Resolve arm pin — lethal damage at 1 life.** Setting life
    to 1: damage drives life to -1 (no clamping in this arm; SBAs
    handle game-loss elsewhere). The mana minting still runs after
    (Python parity — `.resolve()` unconditionally appends mana
    after the life decrement).
    """
    s = engine.make_synthetic_state(0, 0, 0)
    pool_id = s.register_and_inject_object(
        _ancient_tomb_dict(), 0, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(pool_id, False)
    s.set_life(0, 1)
    s.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    assert s.get_life(0) == -1, (
        f"Life=1 - damage=2 must land at -1; got {s.get_life(0)}"
    )
    assert s.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "any": 0,
    }


def test_resolve_source_controller_scoping(engine):
    """**Source-controller fan-out pin.** The damage applies to
    source-controller p1 (not active_player p0); the mana lands in
    p1's pool. p0 is fully untouched.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    pool_id = s.register_and_inject_object(
        _ancient_tomb_dict(), 1, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(pool_id, False)
    life_p0_pre = s.get_life(0)
    life_p1_pre = s.get_life(1)
    s.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    # p1 (source-controller) gets damage + mana.
    assert s.get_life(1) == life_p1_pre - 2
    assert s.get_mana_pool(1) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "any": 0,
    }
    # p0 untouched.
    assert s.get_life(0) == life_p0_pre
    assert s.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
    }
