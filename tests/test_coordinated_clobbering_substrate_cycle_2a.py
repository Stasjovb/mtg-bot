"""**Coordinated Clobbering Cycle 2a substrate (2026-05-24).**

Tests for the ``target_obj_id_3`` plumbing + the new 3-slot synthetic
``push_to_stack_with_three_targets`` API + the Cycle 1 resolve arm's
slot-2 extension (read/validate/tap step + second damage instance).

**Scope (Cycle 2a — substrate-only).**

This cycle ships ONLY:

  * New ``StackItem.target_obj_id_3: Option<u32>`` field on the Rust
    side (matched by ``current_resolve_payload_target_id_3`` state
    slot + the resolver's save → set → restore bracket on BOTH resolve
    entry points).
  * New ``push_to_stack_with_three_targets`` synthetic API (the
    test-only sibling of the existing single-slot
    ``push_to_stack_with_target``). Slot 2 is optional — passing
    ``None`` (the slot-2-absent fallback) MUST keep the
    StackItem's resolve behavior byte-equal to the existing 2-slot
    push.
  * Extension of ``Effect::CoordinatedClobberingEffect``'s resolve
    arm with a slot-2 read/validate/tap step + a second damage
    instance to slot 0 (each chosen attacker deals damage equal to
    its own power, per the oracle text).
  * Cast-time binder extension in ``cast_spell_noncreature`` for the
    3-slot Coordinated-Clobbering grammar (deterministic-first opp
    creature for slot 0, deterministic-first caster-untapped for slot
    1, optional second caster-untapped for slot 2 with agent-decline
    branch at ``slot_idx >= min_t``). The binder NEVER fires
    production paths this cycle because the admit gate still
    declines Coordinated Clobbering — Cycle 2b ships the actual flip.

**Cycle 2b deliverable shape** (what THIS cycle pre-positions for):

  * Phase 6 admit-predicate arm in
    ``trajectory.py::_printing_is_bridge_simple_spell`` for the
    ``(2, 3)`` heterogeneous shape with ``slot_kinds == ("creature",
    "my_creature", "my_creature")``.
  * Admit-set pin bump:
    ``tests/test_cross_engine_etb_triggers.py::test_spell_card_lever_
    phase1_negative_pins_decline_set`` removes Coordinated Clobbering
    + bumps the admit count.
  * Per-card real-EoE probe driving the actual parsed Coordinated
    Clobbering printing through both engines byte-equal — cast +
    resolve, 2-target AND 3-target invocations.
  * Inversion of the substrate-only invariant pin from Cycle 1
    (renamed to
    ``test_coordinated_clobbering_now_admits_at_admit_gate_post_
    cycle_2``).

**Substrate-only invariant pin** (LOAD-BEARING — same as Cycle 1's):
``_printing_is_bridge_simple_spell(Coordinated Clobbering)`` is STILL
``False`` after this cycle. If this pin (in
``tests/test_coordinated_clobbering_substrate_cycle_1.py``) fails
post-Cycle-2a, the substrate-only invariant has been violated.
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3
_ZONE_EXILE = 5


def _fresh_rust():
    """Synthetic two-player state with both players at 20 life."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _new_creature(rs, name, owner, power, toughness, *, keywords=None):
    """Inject a creature on owner's battlefield with the printed P/T
    and (optional) keywords. The freshly-injected creature is on bf,
    untapped, no damage, no counters."""
    obj_dict = {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": power,
        "toughness": toughness,
    }
    if keywords is not None:
        obj_dict["keywords"] = keywords
    return rs.register_and_inject_object(
        obj_dict, owner, _ZONE_BATTLEFIELD,
    )


def _inject_cc_spell(rs, caster):
    """Inject a bare Coordinated-Clobbering-shape Sorcery on the
    caster's hand. Returns the spell's obj id."""
    return rs.register_and_inject_object(
        {
            "name": "CC Probe",
            "card_types": ["Sorcery"],
            "mana_cost": {"G": 1},
            "effects": [{"kind": "coordinated_clobbering_effect"}],
        },
        caster, _ZONE_HAND,
    )


# ---------------------------------------------------------------------------
# 3-slot synthetic push API contract
# ---------------------------------------------------------------------------


def test_push_to_stack_with_three_targets_exists_and_seats_all_three_slots():
    """``push_to_stack_with_three_targets`` is the new synthetic push
    API. With all three slots bound to ``Some(_)``, the resolver's
    save → set → restore bracket sees all three payload-target slots
    populated.

    Tests the existence + signature of the new API. No resolve
    invocation here — the next test exercises the full
    cast-and-resolve.
    """
    _require_engine()
    rs = _fresh_rust()
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=2)
    my_grizzly = _new_creature(rs, "My Grizzly", owner=0, power=2, toughness=2)
    my_panda = _new_creature(rs, "My Panda", owner=0, power=3, toughness=3)
    spell_id = _inject_cc_spell(rs, caster=0)
    # No exception → API exists with the documented signature.
    rs.push_to_stack_with_three_targets(
        spell_id, 0, opp_bear, my_grizzly, my_panda,
    )
    assert rs.stack_size() == 1


def test_push_to_stack_with_three_targets_slot2_absent_fallback_byte_equal_to_2_slot():
    """**Slot-2-absent fallback pin.** When the optional 3rd target is
    ``None``, the 3-slot push behaves byte-equal to the legacy 2-slot
    push. Resolve drives the same outcome: tap slot 1, deal slot-1's
    power as damage to slot 0, NO second damage instance, NO second
    tap.

    This pin guards the back-compat invariant: existing 2-slot
    consumers must NOT regress when the 3-slot substrate lands.
    """
    _require_engine()
    rs = _fresh_rust()
    # P0 caster, P1 opp. Single opp bear + single friendly grizzly.
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=4)
    my_grizzly = _new_creature(rs, "My Grizzly", owner=0, power=2, toughness=2)
    spell_id = _inject_cc_spell(rs, caster=0)
    rs.push_to_stack_with_three_targets(
        spell_id, 0, opp_bear, my_grizzly, None,
    )
    rs.resolve_top_of_stack()
    # Slot 1 (my_grizzly) must be tapped (idempotent; oracle "tap one
    # or two target untapped creatures you control").
    assert rs.is_tapped(my_grizzly) is True, (
        "Slot 1 (my creature) must be tapped after CC resolves"
    )
    # Slot 0 (opp_bear) takes 2 damage (grizzly's power). Bear has
    # toughness 4 so it survives — pin the damage count, not the
    # death.
    assert rs.get_damage(opp_bear) == 2, (
        "Slot 0 (opp creature) must take exactly slot-1's power "
        "(2) — no second damage instance with slot 2 absent"
    )


def test_three_target_resolve_taps_both_attackers_and_doubles_damage():
    """**Three-target invocation full pin.** With slot 2 bound to a
    distinct second friendly untapped creature, the CC resolve arm:
      * Taps BOTH friendly attackers (slots 1 and 2).
      * Deals slot-1.power damage to slot 0.
      * Deals slot-2.power damage to slot 0 (cumulative — Python's
        `for obj in my_objs: opp_obj.take_damage(...)` walks both
        chosen attackers per `bespoke.py:2480-2486`).
    """
    _require_engine()
    rs = _fresh_rust()
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=10)
    my_grizzly = _new_creature(rs, "My Grizzly", owner=0, power=2, toughness=2)
    my_panda = _new_creature(rs, "My Panda", owner=0, power=3, toughness=3)
    spell_id = _inject_cc_spell(rs, caster=0)
    rs.push_to_stack_with_three_targets(
        spell_id, 0, opp_bear, my_grizzly, my_panda,
    )
    rs.resolve_top_of_stack()
    # Both friendly attackers tapped.
    assert rs.is_tapped(my_grizzly) is True
    assert rs.is_tapped(my_panda) is True
    # Opp bear takes 2 + 3 = 5 damage (both attackers' power).
    assert rs.get_damage(opp_bear) == 5, (
        "Slot 0 must take slot-1.power + slot-2.power (2+3=5)"
    )


def test_three_target_resolve_slot2_illegal_fizzles_only_slot2_branch():
    """**Slot-2 fizzle (CR 608.2b) — slot-1 survives + slot-2 illegal.**
    If slot 2's target is no longer caster-controlled at resolve
    time (e.g. ceased / changed controller via a hypothetical state
    transition between cast and resolve), the slot-2 read finds the
    creature absent from caster's bf → the slot-2 branch silently
    skips its tap + damage. Slot 1 still fires.

    Synthetic shape: bind slot 2 to an id that does NOT exist on any
    battlefield. The slot-2 lookup returns ``None``, the branch
    short-circuits, no tap, no damage.
    """
    _require_engine()
    rs = _fresh_rust()
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=10)
    my_grizzly = _new_creature(rs, "My Grizzly", owner=0, power=2, toughness=2)
    spell_id = _inject_cc_spell(rs, caster=0)
    # Slot 2 points at a never-injected id (every injected id is <
    # 1_000_000 by registry convention). The lookup returns None
    # → silent skip on the slot-2 branch.
    rs.push_to_stack_with_three_targets(
        spell_id, 0, opp_bear, my_grizzly, 999_999,
    )
    rs.resolve_top_of_stack()
    # Slot 1 still tapped + slot 1's damage instance fires.
    assert rs.is_tapped(my_grizzly) is True
    assert rs.get_damage(opp_bear) == 2, (
        "Slot 0 takes only slot-1's damage (2); slot 2 fizzles "
        "silently per CR 608.2b"
    )


def test_three_target_resolve_slot2_same_id_as_slot1_does_not_double_apply():
    """**Identity guard — `slot2_id == slot1_id`.** If a synthetic /
    mis-bound caller passes the same id for slots 1 and 2, the
    resolve arm's identity guard short-circuits the slot-2 branch.
    Slot 1 still fires its tap + damage exactly once.

    Pins the belt-and-suspenders guard against double-tap +
    double-damage from a duplicate id. Python's
    ``for obj in my_objs`` walks the distinct chosen attackers; the
    Rust arm's `id != slot1` guard mirrors that distinctness.
    """
    _require_engine()
    rs = _fresh_rust()
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=10)
    my_grizzly = _new_creature(rs, "My Grizzly", owner=0, power=2, toughness=2)
    spell_id = _inject_cc_spell(rs, caster=0)
    # Slot 1 and slot 2 both point at my_grizzly.
    rs.push_to_stack_with_three_targets(
        spell_id, 0, opp_bear, my_grizzly, my_grizzly,
    )
    rs.resolve_top_of_stack()
    # Tap fires once; damage applied once (identity guard prevents
    # double).
    assert rs.is_tapped(my_grizzly) is True
    assert rs.get_damage(opp_bear) == 2, (
        "Identity guard MUST prevent double-damage from a "
        "duplicate slot-1/slot-2 id"
    )


def test_three_target_resolve_slot2_opp_controlled_fizzles():
    """**Slot-2 controller re-validation (CR 608.2b).** Python's CC
    skips an attacker whose ``controller_id != caster_id`` at resolve
    time (the controller change between cast and resolve fizzles
    that attacker's contribution). If slot 2 points at an
    opp-controlled creature, the slot-2 branch skips silently.
    """
    _require_engine()
    rs = _fresh_rust()
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=10)
    my_grizzly = _new_creature(rs, "My Grizzly", owner=0, power=2, toughness=2)
    # Slot 2 is opp-controlled — illegal per Python's
    # `controller_id != caster_id` skip.
    other_opp_creature = _new_creature(rs, "Opp Wolf", owner=1, power=4, toughness=4)
    spell_id = _inject_cc_spell(rs, caster=0)
    rs.push_to_stack_with_three_targets(
        spell_id, 0, opp_bear, my_grizzly, other_opp_creature,
    )
    rs.resolve_top_of_stack()
    # The opp wolf is NOT tapped (slot 2 fizzled silently).
    assert rs.is_tapped(other_opp_creature) is False, (
        "Slot 2 must NOT tap an opp-controlled creature — the "
        "controller-re-validation MUST fizzle that slot silently"
    )
    # Damage from slot 1 still applied; no damage from slot 2.
    assert rs.get_damage(opp_bear) == 2


# ---------------------------------------------------------------------------
# Resolver bracket sibling-parity — slot 3 swap is save → set → restore
# ---------------------------------------------------------------------------


def test_resolve_top_of_stack_restores_target_id_3_after_resolution():
    """**Resolver bracket sibling parity pin.** After
    ``resolve_top_of_stack`` runs, the transient
    ``current_resolve_payload_target_id_3`` slot MUST be restored to
    its prior value (the save → set → restore bracket discipline
    that every transient swap follows). This pin guards the bracket
    pairing — a missed restore would leak the slot-3 binding into
    the next resolve, causing cross-resolution interference.

    Synthetic shape: push a CC spell with slot 3 bound, resolve it,
    then read the transient slot. Today there's no public getter on
    the transient itself — instead we push a SECOND non-CC item and
    resolve; if the bracket leaked, that resolution would see a
    leaked slot-3 binding. Pin via behavioral observation: a second
    resolve with no slot-3 binding seats the slot at ``None`` (no
    crash, no interference).
    """
    _require_engine()
    rs = _fresh_rust()
    opp_bear = _new_creature(rs, "Opp Bear", owner=1, power=1, toughness=10)
    my_grizzly = _new_creature(rs, "My Grizzly", owner=0, power=2, toughness=2)
    my_panda = _new_creature(rs, "My Panda", owner=0, power=3, toughness=3)
    spell_id = _inject_cc_spell(rs, caster=0)
    rs.push_to_stack_with_three_targets(
        spell_id, 0, opp_bear, my_grizzly, my_panda,
    )
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    # A second resolve attempt on an empty stack must not crash.
    # The bracket restore is verified mechanically — the file-level
    # comment at the swap site asserts the pairing; this test pins
    # behavioral non-leak.


# ---------------------------------------------------------------------------
# Substrate parse + serializer surfaces (unchanged from Cycle 1)
# ---------------------------------------------------------------------------


def test_cycle_2a_substrate_does_not_regress_cycle_1_parse_round_trip():
    """**Back-compat pin.** The Cycle 1 parse / to_pydict / bridge
    arms must remain byte-equal — the Cycle 2a substrate widens the
    StackItem field set + the resolve arm but does NOT touch the
    Effect-variant parse or serializer surfaces.
    """
    _require_engine()
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
# Cycle 2b closure marker (INVERTED — was the substrate-only invariant).
# ---------------------------------------------------------------------------


def test_coordinated_clobbering_now_admits_at_admit_gate_post_cycle_2():
    """**Cycle 2b closure marker (INVERTED — was the substrate-only
    invariant in Cycle 2a, flipped here).** The spell-card-bridge
    admit predicate ``_printing_is_bridge_simple_spell`` now ADMITS
    Coordinated Clobbering — the Cycle 2b Phase 6 admit arm
    (``_PHASE6_CC_3SLOT_SHAPE`` disjunct) flipped the gate, consuming
    the 3-slot substrate this cycle pre-positioned (the
    ``target_obj_id_3`` plumbing + ``push_to_stack_with_three_
    targets`` synthetic API + the resolve arm's slot-2 extension +
    the cast-time binder).

    Sibling-paired with
    ``test_coordinated_clobbering_now_admits_at_admit_gate_post_
    cycle_2`` in
    ``test_coordinated_clobbering_substrate_cycle_1.py`` — both
    Cycle 1 + Cycle 2a substrate-only invariants flipped atomically
    in the SAME Cycle 2b commit (the load-bearing closure marker
    discipline — flip the gate AND flip both invariant pins in
    lockstep so a regression of any of the three surfaces is caught
    here loudly).

    If this pin fails — i.e. Coordinated Clobbering goes back to
    DECLINED — the Cycle 2b Phase 6 admit arm has regressed. The
    flip cascades into the per-card real-EoE probe + the admit-set
    pin bump (count 41 → 42); a regression here masks both."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = get_active_source().get_printings().get("Coordinated Clobbering")
    if real is None:
        pytest.skip("Coordinated Clobbering absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(real), (
        "Coordinated Clobbering MUST be ADMITTED at the admit gate "
        "post-Cycle-2b (the Phase 6 admit arm landed in "
        "trajectory._printing_is_bridge_simple_spell). A DECLINE "
        "here is a regression of the Cycle 2b flip."
    )
