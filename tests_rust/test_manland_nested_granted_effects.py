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

**SwitchSourcePowerToughnessUEOT resolve.** Layer-7e P/T-switch LANDED
(feature/fumarole-ptswitch). The resolve pushes a
``UeotModifier::SwitchPT`` onto the source; the effective-P/T readers
apply ONE swap of the fully-composed (post-7b/c/d) P/T per odd net
count (CR 613.4 layer 7e). A 1/4 carrier becomes effective 4/1 after
one switch; a second switch cancels back to 1/4 (two swaps = no net
swap), mirroring Python's ``_compute_effective_pt`` 7e branch.
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


def _etb_double_switch_pt_dict():
    """Vanilla 1/4 creature whose ETB fires TWO
    SwitchSourcePowerToughnessUEOT effects -- two swaps net to no swap
    (CR 613.4 layer 7e parity)."""
    return {
        "name": "Synthetic Fumarole Double Switch (ETB)",
        "mana_cost": {"generic": 2, "U": 1},
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 4,
        "effects": [],
        "etb_effects": [
            {"kind": "switch_source_power_toughness_ueot"},
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


def test_switch_source_power_toughness_ueot_swaps_pt(
    synthetic_state,
):
    """**SwitchSourcePowerToughnessUEOT resolve arm pin -- layer-7e
    swap LANDED.** The resolve pushes a ``UeotModifier::SwitchPT`` onto
    the source; the effective-P/T readers apply ONE swap of the
    fully-composed P/T (CR 613.4 layer 7e). A printed 1/4 carrier reads
    effective 4/1 after one switch -- byte-equal with Python's
    ``_compute_effective_pt`` 7e branch."""
    obj_id = synthetic_state.register_and_inject_object(
        _etb_switch_pt_dict(), 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Drain the on-stack ETB effect (one switch).
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    # One switch: printed 1/4 -> effective 4/1.
    assert synthetic_state.effective_power(obj_id) == 4
    assert synthetic_state.effective_toughness(obj_id) == 1


def test_switch_source_power_toughness_ueot_double_switch_cancels(
    synthetic_state,
):
    """**Two switches cancel (CR 613.4 layer 7e parity).** A carrier
    whose ETB fires TWO ``SwitchSourcePowerToughnessUEOT`` effects
    pushes two ``SwitchPT`` entries -- an even net count = no net swap,
    so the carrier reads its printed 1/4. Mirrors Python's 7e
    ``for _ in layer7e: p, t = t, p`` over two entries (a swap is its
    own inverse)."""
    obj_id = synthetic_state.register_and_inject_object(
        _etb_double_switch_pt_dict(), 0, ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    # Resolve the spell (enters bf), then drain ETB-queued items until
    # the stack is empty (two switch effects).
    synthetic_state.resolve_top_of_stack()
    while synthetic_state.stack_size() > 0:
        synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    # Two switches net to zero: printed 1/4.
    assert synthetic_state.effective_power(obj_id) == 1
    assert synthetic_state.effective_toughness(obj_id) == 4


# --------------------------------------------------------- granted-AA enum pins
#
# **Manland grant enum (feature/manland-grant-enum, 2026-06-01).** The
# nested granted AA now round-trips onto the animated land via the new
# ``granted_activated_abilities`` field on ``Effect::BecomeLandCreatureUEOT``
# (a ``UeotModifier::GrantedActivatedAbility`` carrier per grant). The
# legal-enumeration appends the granted AA AFTER the land's printing AAs,
# byte-equal with Python's ``effective_activated_abilities`` order, so the
# granted ``{0}`` switch / ``{X}`` pump is enumerable + activatable by index.


_ZONE_BF = 2


def _fumarole_manland_land_dict():
    """A Land whose animate AA grants the nested ``{0}`` switch (Wandering
    Fumarole shape). No ``mana_produced`` so the animate AA is index 0
    and the granted switch is index 1."""
    return {
        "name": "Pin Fumarole (manland)",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"mana": {"generic": 2, "U": 1, "R": 1}},
                "effect": {
                    "kind": "become_land_creature_ueot",
                    "power": 1,
                    "toughness": 4,
                    "granted_activated_abilities": [
                        {
                            "cost": {},
                            "effect": {
                                "kind": "switch_source_power_toughness_ueot"
                            },
                        }
                    ],
                },
            }
        ],
    }


def _lavaclaw_manland_land_dict():
    """A Land whose animate AA grants the nested ``{X}`` pump (Lavaclaw
    Reaches shape). No ``mana_produced`` so the animate AA is index 0 and
    the granted pump is index 1."""
    return {
        "name": "Pin Lavaclaw (manland)",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"mana": {"generic": 1, "B": 1, "R": 1}},
                "effect": {
                    "kind": "become_land_creature_ueot",
                    "power": 2,
                    "toughness": 2,
                    "granted_subtype": "Elemental",
                    "granted_activated_abilities": [
                        {
                            "cost": {"mana": {"X": 1}},
                            "effect": {"kind": "pump_self_x_power_ueot"},
                        }
                    ],
                },
            }
        ],
    }


def _clean_rust_state():
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    return build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))


def test_register_become_land_creature_ueot_with_granted_aa(empty_registry):
    """**parse_effect arm pin — granted_activated_abilities.** A manland
    animate AA whose ``become_land_creature_ueot`` effect carries a nested
    ``granted_activated_abilities`` list registers cleanly (the parser
    recurses through ``parse_activated_ability``)."""
    pid = empty_registry.register_printing(_fumarole_manland_land_dict())
    assert empty_registry.get_printing_name(pid) == "Pin Fumarole (manland)"


def test_granted_switch_aa_not_enumerated_before_animate():
    """**Pre-animate: no granted AA.** The granted ``{0}`` switch is only
    live while the land is animated — before activating the animate AA,
    ``legal_decisions`` offers only the animate AA (index 0), never the
    granted switch."""
    rs = _clean_rust_state()
    land = rs.register_and_inject_object(
        _fumarole_manland_land_dict(), 0, _ZONE_BF,
    )
    rs.set_active_player(0)
    rs.set_phase(3)
    for color, n in [("C", 2), ("U", 1), ("R", 1)]:
        rs.add_mana(0, color, n)
    idxs = sorted(
        a["ability_index"]
        for a in rs.legal_decisions(0)
        if a.get("kind") == "activate_ability" and a.get("source_id") == land
    )
    assert idxs == [0], (
        f"Pre-animate, only the animate AA (index 0) is legal; got {idxs}"
    )


def test_granted_switch_aa_enumerates_at_index_1_after_animate():
    """**Post-animate enumeration pin.** After activating the animate AA,
    the granted ``{0}`` switch appears at ``ability_index=1`` (AFTER the
    printing's own AA at index 0)."""
    rs = _clean_rust_state()
    land = rs.register_and_inject_object(
        _fumarole_manland_land_dict(), 0, _ZONE_BF,
    )
    rs.set_active_player(0)
    rs.set_phase(3)
    for color, n in [("C", 2), ("U", 1), ("R", 1)]:
        rs.add_mana(0, color, n)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert (rs.effective_power(land), rs.effective_toughness(land)) == (1, 4)
    idxs = sorted(
        a["ability_index"]
        for a in rs.legal_decisions(0)
        if a.get("kind") == "activate_ability" and a.get("source_id") == land
    )
    assert idxs == [1], (
        f"Post-animate, the granted {{0}} switch is legal at index 1; "
        f"got {idxs}"
    )


def test_granted_switch_aa_activates_by_index_swaps_pt():
    """**Granted-AA activation pin.** Activating the granted ``{0}`` switch
    by ``ability_index=1`` swaps the animated 1/4 to 4/1; a second
    activation cancels back to 1/4."""
    rs = _clean_rust_state()
    land = rs.register_and_inject_object(
        _fumarole_manland_land_dict(), 0, _ZONE_BF,
    )
    rs.set_active_player(0)
    rs.set_phase(3)
    for color, n in [("C", 2), ("U", 1), ("R", 1)]:
        rs.add_mana(0, color, n)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land, "ability_index": 1}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert (rs.effective_power(land), rs.effective_toughness(land)) == (4, 1)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land, "ability_index": 1}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert (rs.effective_power(land), rs.effective_toughness(land)) == (1, 4)


def test_granted_x_pump_aa_enumerates_and_binds_x_after_animate():
    """**Granted X-pump enumeration + X-binding pin.** Lavaclaw's granted
    ``{X}`` pump enumerates at ``ability_index=1`` post-animate;
    activating it with a tapped manland + a 3-mana floating pool binds
    X=3 deterministically (upper bound = floating pool, no land headroom),
    pumping the animated 2/2 to 5/2."""
    rs = _clean_rust_state()
    land = rs.register_and_inject_object(
        _lavaclaw_manland_land_dict(), 0, _ZONE_BF,
    )
    rs.set_active_player(0)
    rs.set_phase(3)
    for color, n in [("C", 1), ("B", 1), ("R", 1)]:
        rs.add_mana(0, color, n)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert (rs.effective_power(land), rs.effective_toughness(land)) == (2, 2)
    idxs = sorted(
        a["ability_index"]
        for a in rs.legal_decisions(0)
        if a.get("kind") == "activate_ability" and a.get("source_id") == land
    )
    assert idxs == [1]
    # Tap manland + exactly 3 floating -> X upper bound = 3.
    rs.tap_object(land)
    rs.empty_all_mana_pools()
    for color, n in [("C", 3)]:
        rs.add_mana(0, color, n)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land, "ability_index": 1}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert (rs.effective_power(land), rs.effective_toughness(land)) == (5, 2)


def test_granted_aa_clears_at_cleanup():
    """**UEOT expiry pin.** The granted AA rides a ``UeotModifier`` that
    auto-expires at the CR 514.3 cleanup pass — after cleanup the granted
    ``{0}`` switch is no longer enumerated (and the land reverts to a
    non-creature, so no AA is offered at all)."""
    rs = _clean_rust_state()
    land = rs.register_and_inject_object(
        _fumarole_manland_land_dict(), 0, _ZONE_BF,
    )
    rs.set_active_player(0)
    rs.set_phase(3)
    for color, n in [("C", 2), ("U", 1), ("R", 1)]:
        rs.add_mana(0, color, n)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    # Granted AA live pre-cleanup.
    pre = sorted(
        a["ability_index"]
        for a in rs.legal_decisions(0)
        if a.get("kind") == "activate_ability" and a.get("source_id") == land
    )
    assert pre == [1]
    rs.cleanup_step_for_active_player()
    # Post-cleanup: the animate modifier + the granted-AA modifier both
    # expired; the land is a plain Land again with only its printing's
    # animate AA (index 0), now affordable-gated. Seed mana so the
    # animate AA re-emits — the granted switch (index 1) must be GONE.
    rs.set_active_player(0)
    rs.set_phase(3)
    for color, n in [("C", 2), ("U", 1), ("R", 1)]:
        rs.add_mana(0, color, n)
    post = sorted(
        a["ability_index"]
        for a in rs.legal_decisions(0)
        if a.get("kind") == "activate_ability" and a.get("source_id") == land
    )
    assert post == [0], (
        f"Post-cleanup the granted switch must be gone; only the printing "
        f"animate AA (index 0) remains. Got {post}"
    )
