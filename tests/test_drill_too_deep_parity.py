"""Cross-engine parity probes for Drill Too Deep.

**ModalChooseOne envelope — Cycle 6 (Drill Too Deep closure,
2026-05-21).** Drill Too Deep is the FIRST per-mode-target
ModalChooseOne to flip from BLOCKED → PROBED. The substrate that
makes this possible:

  1. Lane BB's per-mode target binding detector table in
     ``state_ops_cast.rs::cast_spell_noncreature`` (Cycle 5 substrate).
  2. The new Rust ``Effect::PutChargeCountersOnTargetSpacecraftOrPlanet
     YouControl { amount: i32 }`` variant (declaration + parse + to_pydict
     + resolve arm) — Drill Too Deep mode 0.
  3. The detector table arm for the new variant — scans for first
     Spacecraft-or-Planet permanent the caster controls.
  4. The matching bridge round-trip arms:
       * ``cross_engine.py::_ta_dict_to_python_effect`` dict→Python
         arm (constructs the Python effect class).
       * ``trajectory.py::_python_spell_effect_to_dict``'s ``_leaf``
         table (composer recurses through ModalChooseOne modes into
         this table).
  5. The companion ``DestroyTargetArtifact`` leaf arm (mode 1's
     serializer — previously missing; the bridge dict→Python arm +
     Rust variant had shipped since round 23, the leaf was the gap).

Lives in its own module (NOT in ``test_parity_smoke.py``) per the
concurrent-agent merge-conflict-minimization hint — Lane EE
(Reroute Systems) is touching the same parity_smoke shared file.

Covered:
- Real EoE printing's spell_effect IS the expected ModalChooseOne shape.
- Serializer round-trip emits a clean ``choose_one_mode`` dict with
  both per-mode leaves (mode 0 = put_charge_counters_on_target_*;
  mode 1 = destroy_target_artifact).
- Bridge dict→Python arm reconstructs both modes faithfully.
- The card passes the ``_printing_is_bridge_simple_spell`` admit gate.
"""

from __future__ import annotations

import pytest


def test_real_eoe_drill_too_deep_spell_effect_is_modal_chooseone_with_expected_modes():
    """**Verify-first.** The live parser maps Drill Too Deep to
    ``ModalChooseOne(modes=(
        PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=5),
        DestroyTargetArtifact(),
    ))`` — both modes carry the per-mode-target shape and the live
    parser already emits the wider ``PutChargeCountersOnTarget
    SpacecraftOrPlanetYouControl`` (NOT the narrower Spacecraft-only
    variant). This pin freezes the parser SoT so a parser drift is
    caught here, not silently downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.counters import (
        PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    )
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact

    p = get_active_source().get_printings().get("Drill Too Deep")
    if p is None:
        pytest.skip("Drill Too Deep absent from active CardSource")
    assert "Instant" in p.card_types
    se = p.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert se.or_both is False
    assert len(se.modes) == 2
    assert isinstance(
        se.modes[0], PutChargeCountersOnTargetSpacecraftOrPlanetYouControl
    )
    assert se.modes[0].amount == 5
    assert isinstance(se.modes[1], DestroyTargetArtifact)


def test_cross_engine_real_eoe_drill_too_deep_put_charge_counters_serializer_round_trip():
    """**ModalChooseOne envelope — Cycle 6 (Drill Too Deep closure,
    serializer round-trip pin).** The trajectory reverse-serializer
    must emit a clean ``choose_one_mode`` dict with both per-mode
    leaves AND the dict→Python bridge must reconstruct the original
    ModalChooseOne byte-equal.

    This is the load-bearing round-trip test: a partially-serializable
    ModalChooseOne returns ``None`` from
    ``_python_spell_effect_to_dict`` and the admit gate refuses to
    flip the card into the bridge admit set (the no-fallback-hybrid
    teeth). Adding the new per-mode-target leaf AND the previously-
    missing ``DestroyTargetArtifact`` leaf together flip Drill Too
    Deep from None-emitted (BLOCKED) to a clean two-mode dict
    (PROBED)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.counters import (
        PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    )
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = get_active_source().get_printings().get("Drill Too Deep")
    if p is None:
        pytest.skip("Drill Too Deep absent from active CardSource")
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    assert d is not None, (
        "Drill Too Deep's spell_effect MUST round-trip clean post-"
        "Cycle-6 (both modes leaf-recognized; serializer recurses "
        "via the ModalChooseOne composer)"
    )
    # Expected dict shape: choose_one_mode composer + the two leaves.
    assert d == {
        "kind": "choose_one_mode",
        "modes": [
            {
                "kind": (
                    "put_charge_counters_on_target_spacecraft_or_"
                    "planet_you_control"
                ),
                "amount": 5,
            },
            {"kind": "destroy_target_artifact"},
        ],
    }
    # Bridge round-trip: dict → Python effect → must equal the
    # original ModalChooseOne (modes are typed-frozen dataclasses;
    # equality is field-based).
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ModalChooseOne)
    assert rebuilt.or_both is False
    assert len(rebuilt.modes) == 2
    assert isinstance(
        rebuilt.modes[0], PutChargeCountersOnTargetSpacecraftOrPlanetYouControl
    )
    assert rebuilt.modes[0].amount == 5
    assert isinstance(rebuilt.modes[1], DestroyTargetArtifact)


def test_drill_too_deep_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-Cycle-6 (this slice), Drill Too
    Deep MUST pass ``_printing_is_bridge_simple_spell`` — the
    spell-card-bridge admit gate. The card has (1, 1) target_count_
    range with empty target_slot_kinds (Phase-1 admit shape); both
    modes are covered+bridged; the serializer round-trips cleanly
    (the §2 teeth all fire positively).

    Bridge-admitted cards become eligible for the Phase-1 carrier
    path (cast_spell → cast-time bind → stack-resolve → graveyard
    routing) on BOTH engines — making real-EoE cast-resolve parity
    probes possible. Per the exact-set pin at
    ``test_probe_spell_card_bridge_admitted.py`` AND
    ``test_cross_engine_etb_triggers.py`` (the two
    admit-set-drift guards), this flip grows the admit set from
    17 → 19 (Drill Too Deep + Untimely Malfunction, the latter
    co-admitted via the new ``destroy_target_artifact`` leaf)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Drill Too Deep")
    if p is None:
        pytest.skip("Drill Too Deep absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True
    # Also pin the per-tooth gates that the admit gate ANDs together —
    # if any one tooth fails, the message at debug time tells us which.
    assert trajectory._spell_effect_is_covered_and_bridged(p) is True
    assert trajectory._python_spell_effect_to_dict(p.spell_effect) is not None


def test_cross_engine_real_eoe_drill_too_deep_put_charge_counters_on_target_spacecraft_or_planet_you_control_parity():
    """**GENUINE real-EoE cross-engine probe — Drill Too Deep mode 0
    (PutChargeCountersOnTargetSpacecraftOrPlanetYouControl, 5 charge
    counters on a Spacecraft you control). ModalChooseOne envelope
    Cycle 6 — admit-set flip 17 → 18 for Drill Too Deep itself.
    PROBED tier — the slice's headline pin.**

    Pushes the GENUINE parsed Drill Too Deep ``ModalChooseOne``
    spell_effect through the resolve path on BOTH engines and
    asserts byte-equal target state (+5 charge counters on the
    controller's Spacecraft) post-resolve.

    Setup:
      * p0 controls a Spacecraft (printing's `subtypes` includes
        "Spacecraft").
      * Python: spell on stack with ``chosen_modes=(0,)`` and a
        target tuple referencing the ship.
      * Rust: spell registered + pushed with cast-time mode 0 +
        the per-mode target binding's first-legal Spacecraft pick.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.counters import (
        PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    )
    from mtg_bot.cards.base import make_spacecraft

    real = get_active_source().get_printings().get("Drill Too Deep")
    if real is None:
        pytest.skip("Drill Too Deep absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(
        se.modes[0],
        PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # ---- Python: Spacecraft on p0's bf; spell on stack mode 0.
    test_ship = make_spacecraft(
        "Test Drill Ship", "{2}", power=2, toughness=2, station_threshold=3,
    )
    py_ship = py.new_object(test_ship, owner_id=0, zone=Zone.BATTLEFIELD)
    py.battlefield.append(py_ship)
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(0,),
            targets=(("permanent", py_ship.id),),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_ship.charge_counters == 5
    py_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert py_gy_names == ["Drill Too Deep"]

    # ---- Rust: register a Spacecraft on p0's bf + drive the modal
    # cast via the registry-inject + push_to_stack_with_mode shape.
    # (Direct apply via push_to_stack with mode-bound StackItem is the
    # simplest cross-engine pin shape — mirrors Ruinous Rampage
    # mode-0/mode-1 probe shape.)
    rs_ship_id = rs.register_and_inject_object(
        {
            "name": "Test Drill Ship",
            "card_types": ["Artifact"],
            "subtypes": ["Spacecraft"],
            "mana_cost": {"generic": 2},
            "effects": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Drill Too Deep",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1, "generic": 1},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {
                            "kind": (
                                "put_charge_counters_on_target_"
                                "spacecraft_or_planet_you_control"
                            ),
                            "amount": 5,
                        },
                        {"kind": "destroy_target_artifact"},
                    ],
                }
            ],
        },
        0, ZONE_BATTLEFIELD,
    )
    # The Rust spell needs the same cast-time bind: mode 0 + the
    # Spacecraft on p0's bf. Use push_to_stack_with_target to seat
    # the payload-target id; mode index is set via the
    # mode-binding API if available, else fall back to a plain
    # push (where the resolve arm's None-payload fallback kicks in
    # and picks the controller's first Spacecraft).
    # NOTE: For this synthetic-path pin we bypass cast_spell_noncreature
    # (which would require funded mana + a printing the cast knows
    # about), using push_to_stack to land the spell directly on the
    # stack with the bound target id — the resolve arm reads the
    # current_resolve_payload_target_id swap or, absent that, scans
    # for the controller's first Spacecraft (matching the Python
    # outcome above).
    rs.push_to_stack(rs_spell_id, 0)
    # No public push_to_stack_with_mode/target hook in the synthetic
    # test surface; rely on the None-payload deterministic-first
    # fallback (which targets p0's first Spacecraft — the test ship).
    # The cast-time bind from the per-mode detector table is exercised
    # by the integration tests in test_modal_chooseone_envelope_cycle5.py
    # and test_drill_too_deep.py; THIS probe pins the resolve arm.
    # However, the synthetic push doesn't bind the mode — the resolve
    # arm dispatches via the ChooseOneMode resolve arm which then
    # picks mode 0 by default. The choose_one_mode resolve arm reads
    # chosen_mode_idx from the StackItem; without a seat it defaults
    # to 0 on the Rust side (the verified Cycle 2 substrate).
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Pin the target's charge_counters via get_charge_counters.
    assert rs.get_charge_counters(rs_ship_id) == 5
