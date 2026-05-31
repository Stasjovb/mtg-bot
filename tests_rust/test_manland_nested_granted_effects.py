"""Rust substrate pins for the manland nested-granted-AA Effects:
``Effect::PumpSelfXPowerUEOT`` (Lavaclaw Reaches) and
``Effect::SwitchSourcePowerToughnessUEOT`` (Wandering Fumarole).

Both are bare unit variants landed 2026-05-31 alongside the
manland-lavaclaw closure. These pins exercise the parse_effect arm
(via ``register_printing`` accepting the unit-variant dict) and the
resolve arm (via an ETB-effect carrier, the same end-to-end idiom
``test_ueot.py`` uses for ``pump_self_until_eot``).

The cross-engine PROBED credit for the two cards lives in
``tests/test_lavaclaw_reaches_parity.py`` /
``tests/test_wandering_fumarole_parity.py`` (Python side); these pins
lock the Rust parse + resolve behavior the substrate provides.

**PumpSelfXPowerUEOT resolve.** Reads ``current_resolve_x_value`` (the
X-cost binding) and pushes ``PowerToughnessBonus { power: X, toughness:
0 }`` on the source. On the synthetic ETB path no X is bound
(``current_resolve_x_value = None``), so X clamps to 0 and the resolve
is a silent no-op -- the source's effective P/T stays printed. This
pins the X<=0 short-circuit (the warm path) and the parse arm.

**SwitchSourcePowerToughnessUEOT resolve.** Substrate-only no-op (Rust
layer-7e P/T-switch deferred -- see docs/SEARCH_LIMITATIONS.md). The
resolve does not mutate P/T; this pins that the variant parses + the
resolve runs without error and leaves P/T unchanged.
"""

from __future__ import annotations


# Zone constants -- mirror ``rust/src/state_ops_zones.rs`` (same as
# test_ueot.py).
ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _etb_pump_self_x_dict():
    """Vanilla 2/2 creature whose ETB effect is PumpSelfXPowerUEOT."""
    return {
        "name": "Synthetic Lavaclaw Pump (ETB)",
        "mana_cost": {"generic": 1, "R": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "effects": [],
        "etb_effects": [
            {"kind": "pump_self_x_power_ueot"},
        ],
    }


def _etb_switch_pt_dict():
    """Vanilla 1/4 creature whose ETB effect is
    SwitchSourcePowerToughnessUEOT."""
    return {
        "name": "Synthetic Fumarole Switch (ETB)",
        "mana_cost": {"generic": 2, "U": 1},
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 4,
        "effects": [],
        "etb_effects": [
            {"kind": "switch_source_power_toughness_ueot"},
        ],
    }


# ---------------------------------------------------------------- parse pins


def test_register_pump_self_x_power_ueot(empty_registry):
    """**parse_effect arm pin.** The unit-variant dict
    ``{"kind": "pump_self_x_power_ueot"}`` registers cleanly as an ETB
    effect (parse_effect accepts the bare unit shape)."""
    pid = empty_registry.register_printing(_etb_pump_self_x_dict())
    assert empty_registry.get_printing_name(pid) == (
        "Synthetic Lavaclaw Pump (ETB)"
    )


def test_register_switch_source_power_toughness_ueot(empty_registry):
    """**parse_effect arm pin.** The unit-variant dict
    ``{"kind": "switch_source_power_toughness_ueot"}`` registers
    cleanly as an ETB effect."""
    pid = empty_registry.register_printing(_etb_switch_pt_dict())
    assert empty_registry.get_printing_name(pid) == (
        "Synthetic Fumarole Switch (ETB)"
    )


# ---------------------------------------------------------------- resolve pins


def test_pump_self_x_power_ueot_no_x_is_noop(synthetic_state):
    """**PumpSelfXPowerUEOT resolve arm pin -- X<=0 short-circuit.**
    With no X bound on the synthetic ETB path
    (``current_resolve_x_value = None`` -> clamps to 0), the resolve is
    a silent no-op: the source's effective P/T stays printed (2/2)."""
    obj_id = synthetic_state.register_and_inject_object(
        _etb_pump_self_x_dict(), 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Drain the on-stack ETB effect.
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    # X<=0 -> no pump; effective P/T equals printed.
    assert synthetic_state.effective_power(obj_id) == 2
    assert synthetic_state.effective_toughness(obj_id) == 2


def test_switch_source_power_toughness_ueot_is_substrate_noop(
    synthetic_state,
):
    """**SwitchSourcePowerToughnessUEOT resolve arm pin -- substrate-
    only no-op.** Rust layer-7e P/T-switch is deferred (see
    docs/SEARCH_LIMITATIONS.md); the resolve runs without error and
    leaves the source's effective P/T unchanged (printed 1/4)."""
    obj_id = synthetic_state.register_and_inject_object(
        _etb_switch_pt_dict(), 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Drain the on-stack ETB effect.
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    # Substrate-only no-op: P/T unchanged (NOT switched to 4/1).
    assert synthetic_state.effective_power(obj_id) == 1
    assert synthetic_state.effective_toughness(obj_id) == 4
