"""**Coordinated Clobbering Cycle 2b parity probe (2026-05-24).**

Per-card real-EoE cross-engine byte-equality probe for Coordinated
Clobbering. THE FLIP that closes Coordinated Clobbering BLOCKED →
PROBED — load-bearing PROBED-tier evidence for the Cycle 2b admit-
gate flip.

Coordinated Clobbering is ``{G}`` Duskmourn Sorcery: "Tap one or two
target untapped creatures you control. They each deal damage equal
to their power to target creature an opponent controls."

The Cycle 1 + 2a substrate landings the probes consume:

  * Cycle 1 (``ee0a8155``/``b199e98b``) — ``Effect::Coordinated
    ClobberingEffect`` Rust unit variant + parse + to_pydict + bridge
    arm + reverse-serializer leaf + 2-target resolve arm.
  * Cycle 2a (``614c923f``/``78ebda90``) — ``StackItem.target_obj_id_
    3`` field + ``current_resolve_payload_target_id_3`` resolver
    bracket + ``push_to_stack_with_three_targets`` synthetic API +
    cast-time 3-slot binder in ``cast_spell_noncreature`` + resolve
    arm slot-2 read/validate/idempotent-tap step + second damage
    instance.
  * Cycle 2b (THIS lane) — Phase 6 admit-predicate arm
    (``_PHASE6_CC_3SLOT_SHAPE``) in ``trajectory._printing_is_bridge_
    simple_spell`` for the ``(2, 3)`` heterogeneous 3-slot grammar.

**Probe inventory.** Four pins follow the slug-credit convention
``test_cross_engine_real_eoe_coordinated_clobbering_<scenario>_
parity`` so the admit-set inventory pipeline awards the PROBED-flip
credit automatically:

  1. Parser SoT pin: ``Coordinated Clobbering`` parses to a
     parameterless ``CoordinatedClobberingEffect()`` with the (2, 3)
     shape + ``("creature", "my_creature", "my_creature")`` slot
     kinds + ``{G}`` mana cost / no X-pips.
  2. Trajectory serializer round-trip pin: byte-equal one-key
     ``{"kind": "coordinated_clobbering_effect"}`` round-trip dict.
  3. Admit-gate flip pin: ``_printing_is_bridge_simple_spell`` now
     ADMITS Coordinated Clobbering (the Phase 6 admit arm landed).
  4. Covered-set membership pin: ``CoordinatedClobberingEffect`` in
     ``covered_python_class_set()``.

Plus the **load-bearing** real-EoE byte-equality cast-and-resolve
probes (THE PROBED-tier flip evidence):

  5. ``test_cross_engine_real_eoe_coordinated_clobbering_two_target_
     parity`` — 2-target invocation (caster has exactly ONE untapped
     creature; cast-time binder leaves slot 2 ``None``). Pins
     idempotent-tap on slot 1 + slot-1.power damage to slot 0;
     verifies the slot-2-absent fallback contract.
  6. ``test_cross_engine_real_eoe_coordinated_clobbering_three_
     target_parity`` — 3-target invocation (caster has TWO untapped
     creatures; cast-time binder picks slot 2 = second creature).
     Pins both attackers tapped + cumulative slot-1.power +
     slot-2.power damage to slot 0. THE substrate-validating evidence
     that the 3-slot binder + the resolve arm's slot-2 step fire
     correctly through the production cast pipeline.

**Resolve-time identity guard.** The Cycle 2a resolve arm carries a
``slot2_id != slot1_id`` belt-and-suspenders guard against double-
tap + double-damage. The 3-target probe deliberately uses TWO
distinct synthetic creatures so the guard is positive-path (not
the negative case — that's pinned in the C2a substrate test file).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_LIBRARY = 1
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3


def _fresh_rust():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_coordinated_clobbering_parser_emits_expected_effect():
    """**Parser source-of-truth pin.** ``Coordinated Clobbering``
    parses to a parameterless ``CoordinatedClobberingEffect()`` with
    ``target_count_range() == (2, 3)`` and ``target_slot_kinds() ==
    ("creature", "my_creature", "my_creature")`` and
    ``mana_cost.x_pips == 0``. Pins the parser invariants the Phase
    6 admit arm + real-EoE probes rely on."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect

    real = get_active_source().get_printings().get("Coordinated Clobbering")
    if real is None:
        pytest.skip("Coordinated Clobbering absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, CoordinatedClobberingEffect)
    assert se.target_count_range() == (2, 3)
    assert se.target_slot_kinds() == (
        "creature", "my_creature", "my_creature",
    )
    assert real.mana_cost.x_pips == 0


# ---------------------------------------------------------------------------
# Trajectory serializer round-trip
# ---------------------------------------------------------------------------


def test_coordinated_clobbering_serializer_round_trip_byte_equal():
    """**Serializer round-trip pin.** The reverse serializer at
    ``_python_spell_effect_to_dict`` emits the one-key dict ``{"kind":
    "coordinated_clobbering_effect"}`` for the bespoke effect, and
    the bridge arm ``_ta_dict_to_python_effect`` re-materializes the
    field-free Python class. This is the §2 round-trip-or-bail tooth
    the admit gate consults — a regression here cascades into the
    admit gate declining Coordinated Clobbering."""
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = CoordinatedClobberingEffect()
    d = _python_spell_effect_to_dict(eff)
    assert d == {"kind": "coordinated_clobbering_effect"}
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, CoordinatedClobberingEffect)
    assert back == eff


# ---------------------------------------------------------------------------
# Admit-gate flip pin
# ---------------------------------------------------------------------------


def test_coordinated_clobbering_admit_gate_now_admits():
    """**Admit-gate flip pin (Cycle 2b).** The Phase 6 admit arm in
    ``trajectory._printing_is_bridge_simple_spell`` admits Coordinated
    Clobbering. Companion to the two inverted substrate pins (Cycle 1
    + Cycle 2a's ``..._now_admits_at_admit_gate_post_cycle_2``) — the
    flip is load-bearing for the real-EoE probes below."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = get_active_source().get_printings().get("Coordinated Clobbering")
    if real is None:
        pytest.skip("Coordinated Clobbering absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(real), (
        "Coordinated Clobbering MUST be admitted at the admit gate "
        "post-Cycle-2b (the Phase 6 admit arm landed)."
    )


# ---------------------------------------------------------------------------
# Covered-set membership
# ---------------------------------------------------------------------------


def test_coordinated_clobbering_in_covered_python_class_set():
    """**Covered-set pin.** ``CoordinatedClobberingEffect`` is in the
    covered set surface — the gate ``_spell_effect_is_covered_and_
    bridged`` consults inside the admit predicate. Pin from Cycle 1
    still firing post-Cycle-2b."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    assert "CoordinatedClobberingEffect" in covered_python_class_set()


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probes — 2-target invocation
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_coordinated_clobbering_two_target_parity():
    """**GENUINE real-EoE cross-engine probe — Coordinated
    Clobbering 2-target invocation. PROBED tier — one of the two
    load-bearing Cycle 2b admit-flip probes.**

    Drives the ACTUAL parsed Coordinated Clobbering printing on the
    Python side and the matching Rust dict on the Rust side, both
    through the FULL production cast pipeline (``cast_spell_
    noncreature`` on Rust; the Python sibling on Python). Asserts
    per-zone parity on every affected object post-resolve.

    **Slot-2-absent path.** The caster controls EXACTLY ONE untapped
    creature (slot 1) plus the spell. The cast-time binder picks
    slot 0 (the opp's bear) + slot 1 (the lone friendly attacker)
    + slot 2 = ``None`` (no second untapped creature available —
    the agent-decline branch at ``slot_idx >= min_t``). Resolve
    arm taps slot 1 + deals slot-1.power damage to slot 0; the
    slot-2-absent branch short-circuits silently per the C2a
    contract.

    Assertion strength: post-resolve, BOTH engines must show
    (a) the spell in p0's graveyard (CR 608.2m); (b) the friendly
    attacker tapped; (c) the opp creature with exactly slot-1.power
    damage marked; (d) the opp creature still on the battlefield if
    its toughness exceeds slot-1.power (we make it a 1/5 so we can
    pin damage directly rather than the destroy outcome).
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.cards import SYNTHETIC_CREATURES

    real = get_active_source().get_printings().get("Coordinated Clobbering")
    if real is None:
        pytest.skip("Coordinated Clobbering absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, CoordinatedClobberingEffect)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: one friendly 2/2 creature (untapped) on p0's bf,
    # one opp 1/5 creature on p1's bf, and the real Coordinated
    # Clobbering printing on p0's stack with the 2-target binding.
    py_my = py.new_object(
        SYNTHETIC_CREATURES["Blood Warrior"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_my.summoning_sick = False
    py_my.controller_id = 0
    py_my.tapped = False
    py.battlefield.append(py_my)
    py_opp = py.new_object(
        SYNTHETIC_CREATURES["Spider Sentinel"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_opp.summoning_sick = False
    py_opp.controller_id = 1
    py.battlefield.append(py_opp)
    # Pin printed P/T of the synthetic creatures (probe assertions
    # rely on these values — a refactor that changes them would
    # silently make the probe weak).
    py_my_power = py_my.printing.power
    py_opp_toughness = py_opp.printing.toughness
    assert py_my_power >= 1, (
        f"friendly attacker must have power>=1 (got {py_my_power})"
    )
    assert py_opp_toughness > py_my_power, (
        f"opp creature toughness ({py_opp_toughness}) must exceed "
        f"slot-1 power ({py_my_power}) so the damage assertion pins "
        f"damage marked rather than the destroy outcome"
    )

    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(),
            # 2-target binding: opp creature (slot 0) + friendly
            # creature (slot 1). NO second friendly — Python's
            # resolve walks ``my_targets = [(k,t) for (k,t) in
            # targets if k == 'my_creature']`` which finds exactly
            # one.
            targets=(
                ("creature", py_opp.id),
                ("my_creature", py_my.id),
            ),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    # Python: friendly tapped + opp takes slot-1's power as damage.
    py_my_after = next(o for o in py.battlefield if o.id == py_my.id)
    assert py_my_after.tapped is True
    py_opp_after = next(
        (o for o in py.battlefield if o.id == py_opp.id), None,
    )
    assert py_opp_after is not None, (
        "opp creature must survive (1/5 with power-2 damage marked)"
    )
    assert py_opp_after.damage == py_my_power, (
        f"opp creature must take exactly slot-1.power ({py_my_power}) "
        f"damage; got {py_opp_after.damage}"
    )

    # ---- Rust: mirror setup. One friendly 2/2 (the printing's
    # rendered P/T) on p0's bf, one opp 1/5 on p1's bf. Coordinated
    # Clobbering on p0's hand. Cast through the production path so
    # the cast-time binder fires. Slot 2 stays None (only one
    # caster-untapped creature exists).
    rs_my = rs.register_and_inject_object(
        {
            "name": py_my.printing.name,
            "card_types": ["Creature"],
            "subtypes": list(py_my.printing.subtypes),
            "power": py_my.printing.power,
            "toughness": py_my.printing.toughness,
            "mana_cost": {"generic": 1},
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs_opp = rs.register_and_inject_object(
        {
            "name": py_opp.printing.name,
            "card_types": ["Creature"],
            "subtypes": list(py_opp.printing.subtypes),
            "power": py_opp.printing.power,
            "toughness": py_opp.printing.toughness,
            "mana_cost": {"generic": 1},
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs_spell = rs.register_and_inject_object(
        {
            "name": "Coordinated Clobbering",
            "card_types": ["Sorcery"],
            "mana_cost": {"G": 1},
            "effects": [{"kind": "coordinated_clobbering_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 1)
    ok = rs.cast_spell_noncreature(rs_spell, 0)
    assert ok is True, (
        "Coordinated Clobbering cast must succeed via the production "
        "path (the cast-time 3-slot binder fires)"
    )
    # The cast-time binder must have seated the opp creature in
    # slot 0 (``stack_top_target_id`` reads slot 0).
    assert rs.stack_top_target_id() == rs_opp, (
        f"Rust per-3-slot binder must seat the opp creature ({rs_opp}) "
        f"in slot 0; got {rs.stack_top_target_id()}"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # Friendly creature tapped + still on bf (no destroy — 2/2).
    assert rs.is_tapped(rs_my) is True, (
        "Rust: slot-1 friendly attacker must be tapped post-resolve"
    )
    assert rs.find_object_zone(rs_my) == _ZONE_BATTLEFIELD
    # Opp creature took exactly slot-1.power damage (no second damage
    # instance — slot 2 was None, the C2a slot-2-absent fallback).
    assert rs.find_object_zone(rs_opp) == _ZONE_BATTLEFIELD, (
        "Rust: opp creature must survive (1/5 with power-2 damage)"
    )
    assert rs.get_damage(rs_opp) == py_my_power, (
        f"Rust: opp creature must take exactly slot-1.power "
        f"({py_my_power}) damage; got {rs.get_damage(rs_opp)} — the "
        f"slot-2-absent fallback contract"
    )
    # Spell routes to p0's graveyard (CR 608.2m).
    assert rs.find_object_zone(rs_spell) == _ZONE_GRAVEYARD


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probes — 3-target invocation
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_coordinated_clobbering_three_target_parity():
    """**GENUINE real-EoE cross-engine probe — Coordinated
    Clobbering 3-target invocation. PROBED tier — the other
    load-bearing Cycle 2b admit-flip probe.**

    Drives the ACTUAL parsed Coordinated Clobbering printing through
    the full production cast pipeline with TWO untapped friendly
    creatures available, so the cast-time binder picks slot 2 = a
    distinct second friendly. Pins both attackers tapped +
    cumulative slot-1.power + slot-2.power damage to slot 0.

    THE substrate-validating evidence that the Cycle 2a 3-slot
    binder + the resolve arm's slot-2 step + the identity guard +
    the resolver bracket restore all fire correctly through the
    production cast pipeline. Pairs with the 2-target probe to cover
    both binder branches.

    **Distinct creatures.** Two synthetic friendly creatures with
    DIFFERENT printed powers so the cumulative-damage assertion is
    sharp: 2+3=5 (not double-counted from the identity guard).
    """
    _require_engine()
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import CoordinatedClobberingEffect
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.cards import SYNTHETIC_CREATURES

    real = get_active_source().get_printings().get("Coordinated Clobbering")
    if real is None:
        pytest.skip("Coordinated Clobbering absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, CoordinatedClobberingEffect)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: TWO distinct friendly creatures (each untapped),
    # one opp creature with very high toughness so it survives the
    # cumulative damage, the real Coordinated Clobbering on the stack
    # with the 3-target binding.
    py_my1 = py.new_object(
        SYNTHETIC_CREATURES["Blood Warrior"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_my1.summoning_sick = False
    py_my1.controller_id = 0
    py_my1.tapped = False
    py.battlefield.append(py_my1)
    py_my2 = py.new_object(
        SYNTHETIC_CREATURES["Forest Giant"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_my2.summoning_sick = False
    py_my2.controller_id = 0
    py_my2.tapped = False
    py.battlefield.append(py_my2)
    # Pick a high-toughness opp creature so the cumulative damage
    # doesn't destroy it — pin damage marked directly.
    py_opp = py.new_object(
        SYNTHETIC_CREATURES["Great Wurm"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_opp.summoning_sick = False
    py_opp.controller_id = 1
    py.battlefield.append(py_opp)

    p1_power = py_my1.printing.power
    p2_power = py_my2.printing.power
    expected_total = p1_power + p2_power
    assert p1_power != p2_power, (
        f"two friendlies must have DIFFERENT powers so the cumulative "
        f"damage assertion is sharp (got {p1_power} and {p2_power})"
    )
    assert py_opp.printing.toughness > expected_total, (
        f"opp creature must survive cumulative damage "
        f"({expected_total}); toughness was {py_opp.printing.toughness}"
    )

    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(),
            # 3-target binding: opp creature (slot 0) + TWO distinct
            # friendly creatures (slots 1 + 2).
            targets=(
                ("creature", py_opp.id),
                ("my_creature", py_my1.id),
                ("my_creature", py_my2.id),
            ),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    # Python: both friendlies tapped + opp takes cumulative damage.
    py_my1_after = next(o for o in py.battlefield if o.id == py_my1.id)
    py_my2_after = next(o for o in py.battlefield if o.id == py_my2.id)
    assert py_my1_after.tapped is True
    assert py_my2_after.tapped is True
    py_opp_after = next(
        (o for o in py.battlefield if o.id == py_opp.id), None,
    )
    assert py_opp_after is not None, (
        "Python: opp creature must survive cumulative damage"
    )
    assert py_opp_after.damage == expected_total, (
        f"Python: opp creature must take cumulative damage "
        f"(slot-1.power + slot-2.power = {expected_total}); got "
        f"{py_opp_after.damage}"
    )

    # ---- Rust: mirror setup. Two distinct friendlies + one opp with
    # matching P/T to Python's side. Cast Coordinated Clobbering
    # through the production path; the cast-time 3-slot binder must
    # pick slot 0 = the opp + slot 1 = first friendly + slot 2 = the
    # second friendly.
    rs_my1 = rs.register_and_inject_object(
        {
            "name": py_my1.printing.name,
            "card_types": ["Creature"],
            "subtypes": list(py_my1.printing.subtypes),
            "power": py_my1.printing.power,
            "toughness": py_my1.printing.toughness,
            "mana_cost": {"generic": 1},
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs_my2 = rs.register_and_inject_object(
        {
            "name": py_my2.printing.name,
            "card_types": ["Creature"],
            "subtypes": list(py_my2.printing.subtypes),
            "power": py_my2.printing.power,
            "toughness": py_my2.printing.toughness,
            "mana_cost": {"generic": 1},
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs_opp = rs.register_and_inject_object(
        {
            "name": py_opp.printing.name,
            "card_types": ["Creature"],
            "subtypes": list(py_opp.printing.subtypes),
            "power": py_opp.printing.power,
            "toughness": py_opp.printing.toughness,
            "mana_cost": {"generic": 1},
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs_spell = rs.register_and_inject_object(
        {
            "name": "Coordinated Clobbering",
            "card_types": ["Sorcery"],
            "mana_cost": {"G": 1},
            "effects": [{"kind": "coordinated_clobbering_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 1)
    ok = rs.cast_spell_noncreature(rs_spell, 0)
    assert ok is True
    # The cast-time binder must seat slot 0 = the opp creature.
    assert rs.stack_top_target_id() == rs_opp
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # Both friendlies tapped — the binder's slot-2 branch fired.
    assert rs.is_tapped(rs_my1) is True
    assert rs.is_tapped(rs_my2) is True
    # Opp creature took cumulative damage = slot-1.power + slot-2.power.
    assert rs.get_damage(rs_opp) == expected_total, (
        f"Rust: opp creature must take cumulative damage "
        f"(slot-1.power + slot-2.power = {expected_total}); got "
        f"{rs.get_damage(rs_opp)} — the 3-target invocation pins the "
        f"slot-2 resolve arm step + the second damage instance"
    )
    # Spell routes to p0's graveyard.
    assert rs.find_object_zone(rs_spell) == _ZONE_GRAVEYARD
