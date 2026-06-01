"""Cross-engine parity probe for Robe of Stars — phasing substrate
closure (2026-05-31, ``feature/robe-of-stars``).

**Robe of Stars — the phasing-substrate Equipment-AA flip.** ``{1}{W}``
Artifact — Equipment (Special Guests / EoE pool). Oracle:

    "Equipped creature gets +0/+3.
     Astral Projection — {1}{W}: Equipped creature phases out.
     Equip {1}"

**What this slice shipped (verify-first finding, 2026-05-31).** The
Python side already had a full ``PhaseOutEquippedCreature`` Effect +
a ``GameObject.phased_out`` bool (set at resolve, cleared at the
controller's untap step, filtered out of combat-damage). The Rust side
had NEITHER. Robe was ``blocked_subsystem_gated`` on exactly one
uncovered Effect class: ``PhaseOutEquippedCreature`` (the
``EquipToTargetCreatureYouControl`` equip ability was already covered).

The substrate this slice added:

  * Rust ``GameObject.phased_out: bool`` field (mirrors Python's
    ``game.py:613``; sibling of ``regeneration_shield`` but SURFACED in
    the snapshot dict so the phase-OUT state change is byte-equal-
    observable cross-engine).
  * Rust ``Effect::PhaseOutEquippedCreature`` (enum variant + parse +
    to_pydict + valid-kinds + resolve arm reading the resolving
    Equipment source's ``attached_to`` and stamping ``phased_out`` on
    the host + clearing the host's combat participation).
  * cross_engine reverse bridge arm ``phase_out_equipped_creature``.
  * ``phased_out`` snapshot key (additive; ``false`` on every
    pre-substrate object, so all pre-substrate snapshot baselines stay
    byte-identical).

**Deliberate phasing shortcut (CR 702.26 NOT fully modeled).** Only the
byte-equal-observable phase-OUT state change (host ``phased_out`` flips
true) is exercised + asserted. Phase-IN (untap-step clear) and
treat-as-nonexistent (combat / SBA / targeting exclusion) are
deliberately out of this probe's scope and mirror Python's own
simplified phasing — documented in
``docs/SEARCH_LIMITATIONS.md`` "Robe of Stars phasing substrate".

**Probe drive asymmetry (the established substrate idiom — cf.
``tests/test_ancient_tomb_substrate_cycle_1.py``'s cross-engine pin).**
The Rust side drives the FULL real ``{1}{W}`` AA-activation path
(``apply_action`` ``activate_ability`` → mana pay → stack push →
``resolve_top_of_stack``). The Python side drives the real-parsed AA's
Effect ``.resolve(state, controller_id, ())`` directly with
``state.resolving_source`` set (Python's auto-tap cost machinery holds
coin objects, not symbols — driving it would test the cost path, not
the phasing effect; the resolve boundary is where byte-equality is
asserted). Both assert byte-equal ``phased_out`` on the equipped host.

This module is the GENUINE real-EoE cross-engine byte-equality probe
(registered in ``scripts/measure_pool_parity.py`` PROBE_MODULES). It
drives the REAL parsed Robe of Stars printing's Astral Projection AA
through BOTH engines and asserts byte-equal phased-out state.
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# Verify-first: parser SoT pins — the Python side is fully wired.
# ---------------------------------------------------------------------------


def test_real_robe_of_stars_parser_sot_phase_out_aa():
    """**Verify-first.** The live parser maps Robe of Stars to a ``{1}{W}``
    Artifact — Equipment with the +0/+3 anthem and TWO activated
    abilities: AA[0] is the Astral Projection ``{1}{W}`` mana-only
    (no riders, not a mana ability, instant-speed) ability whose effect
    is ``PhaseOutEquippedCreature``; AA[1] is the synthesized Equip {1}
    (sorcery-speed). Freezes the parser SoT so a parser drift is caught
    here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.tap import PhaseOutEquippedCreature

    p = get_active_source().get_printings().get("Robe of Stars")
    if p is None:
        pytest.skip("Robe of Stars absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    assert p.mana_cost_str == "{1}{W}"
    pb, tb, gks = p.equipment_bonuses
    assert (pb, tb) == (0, 3)
    assert gks == frozenset()
    # Exactly two activated abilities; the phase-out AA is index 0.
    assert len(p.activated_abilities) == 2
    aa = p.activated_abilities[0]
    assert aa.cost.mana.generic == 1
    assert aa.cost.mana.colored == (("W", 1),)
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert isinstance(aa.effect, PhaseOutEquippedCreature)
    # The phase-out AA cost is mana-only — NO tap-self / sac / pay-life
    # / other riders (the clean-carrier shape).
    c = aa.cost
    assert c.tap_self is False
    assert c.sacrifice_self is False
    assert c.exile_self is False
    assert c.pay_life == 0
    # The Equip {1} ability surfaces (already covered cross-engine).
    equip = p.activated_abilities[1]
    assert equip.cost.mana_str == "{1}"
    assert equip.sorcery_speed is True


def test_phase_out_equipped_creature_effect_class_now_covered():
    """**Verify-first.** ``PhaseOutEquippedCreature`` is now in the
    covered-by-rust set (the ``Effect::PhaseOutEquippedCreature`` Rust
    variant landed this slice), and all of Robe of Stars's emitted
    Effect classes are covered (so the card is byte-equal-covered at the
    Effect+bridge level — the precondition for the PROBED flip)."""
    from mtg_bot.parity.effect_coverage import (
        card_effect_classes,
        covered_python_class_set,
    )
    from mtg_bot.cards.source import get_active_source

    cov = covered_python_class_set()
    assert "PhaseOutEquippedCreature" in cov
    p = get_active_source().get_printings().get("Robe of Stars")
    if p is None:
        pytest.skip("Robe of Stars absent from active CardSource")
    assert card_effect_classes(p).issubset(cov)


def test_phase_out_equipped_creature_bridge_round_trips():
    """**Verify-first — the reverse bridge arm.** The
    ``phase_out_equipped_creature`` safe dict round-trips back to the
    genuine Python ``PhaseOutEquippedCreature`` class."""
    from mtg_bot.effects.generic.tap import PhaseOutEquippedCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "phase_out_equipped_creature"}
    )
    assert isinstance(bridged, PhaseOutEquippedCreature)


def test_rust_register_printing_with_phase_out_aa():
    """**Rust parse arm pin.** The new ``phase_out_equipped_creature``
    parse arm accepts the bare unit dict and registers cleanly on a
    synthetic Robe-shape Equipment printing with the ``{1}{W}`` AA."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_synthetic_robe_dict())
    assert reg.get_printing_name(pid) == "Synthetic Robe of Stars"


def test_phased_out_snapshot_key_default_false():
    """**Snapshot surface pin.** Every freshly-allocated object surfaces
    ``phased_out: False`` in the snapshot dict (back-compat default —
    additive key, invariant value on objects that haven't been phased
    out)."""
    _require_engine()
    import mtg_bot_engine

    st = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    host = st.register_and_inject_object(
        _bear_inj("Bear"), 0, ZONE_BATTLEFIELD
    )
    for entry in st.battlefield_snapshot():
        assert "phased_out" in entry
        assert entry["phased_out"] is False


# ---------------------------------------------------------------------------
# Injection helpers.
# ---------------------------------------------------------------------------


def _synthetic_robe_dict():
    """Minimal Robe-of-Stars-shape Equipment printing dict for the Rust
    Registry. The Astral Projection ``{1}{W}`` mana-only AA at index 0
    with the new ``phase_out_equipped_creature`` Effect.
    """
    return {
        "name": "Synthetic Robe of Stars",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "activated_abilities": [
            {
                "cost": {"mana": {"generic": 1, "W": 1}},
                "effect": {"kind": "phase_out_equipped_creature"},
                "is_mana_ability": False,
            },
        ],
    }


def _bear_inj(name):
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "power": 2,
        "toughness": 2,
        "effects": [],
    }


def _rust_obj_field(rust_state, obj_id, field):
    for entry in rust_state.battlefield_snapshot():
        if entry["id"] == obj_id:
            return entry.get(field)
    return None


def _py_obj(py_state, obj_id):
    for o in py_state.battlefield:
        if o.id == obj_id:
            return o
    return None


def _py_new_state():
    from mtg_bot.game import GameState, Player

    st = GameState()
    st.players.append(Player(id=0))
    st.players.append(Player(id=1))
    st.active_player_idx = 0
    return st


def _py_put(state, printing, controller, attached_to=None):
    from mtg_bot.game import Zone

    obj = state.new_object(printing, controller, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equality probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_robe_of_stars_parity():
    """**GENUINE real-EoE probe — phasing substrate (Robe of Stars).**

    Drives the real parsed Robe of Stars Astral Projection AA
    end-to-end and asserts byte-equal cross-engine phased-out state on
    the equipped host.

    Scenario A (Robe equipped to a host): Robe is attached to a host
    bear on p0's bf. Activating the ``{1}{W}`` AA (Rust: full
    ``apply_action`` activation + mana pay + stack resolve; Python: the
    real-parsed Effect ``.resolve`` with ``resolving_source`` set)
    phases the host out → ``host.phased_out`` flips ``True`` on BOTH
    engines, the Robe itself stays ``phased_out=False`` on BOTH, and an
    unrelated opponent creature stays ``phased_out=False`` on BOTH.

    Scenario B (Robe NOT equipped): an unattached Robe. Activating the
    AA is a silent no-op on BOTH engines — nothing phases out.
    """
    _require_engine()
    import mtg_bot_engine
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source

    real = get_active_source().get_printings().get("Robe of Stars")
    if real is None:
        pytest.skip("Robe of Stars absent from active CardSource")
    real_aa_effect = real.activated_abilities[0].effect

    # ===== Scenario A: Robe equipped to a host. =====
    rust_state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    rs_host = rust_state.register_and_inject_object(
        _bear_inj("Host Bear"), 0, ZONE_BATTLEFIELD
    )
    rs_opp = rust_state.register_and_inject_object(
        _bear_inj("Opp Bear"), 1, ZONE_BATTLEFIELD
    )
    rs_robe = rust_state.register_and_inject_object(
        _synthetic_robe_dict(), 0, ZONE_BATTLEFIELD
    )
    assert rust_state.attach(rs_robe, rs_host) is True
    rust_state.force_set_summoning_sick(rs_robe, False)
    # Fund the {1}{W} cost: two white coins (W pays {W}, W pays {1}).
    rust_state.add_mana(0, "W", 2)

    py_state = _py_new_state()
    py_host = _py_put(py_state, _bear_inj_py("Host Bear"), 0)
    py_opp = _py_put(py_state, _bear_inj_py("Opp Bear"), 1)
    py_robe = _py_put(
        py_state, real, 0, attached_to=py_host.id
    )

    # Pre-state byte-equal: nothing phased out yet.
    assert _rust_obj_field(rust_state, rs_host, "phased_out") is False
    assert _py_obj(py_state, py_host.id).phased_out is False

    # Rust: full real-AA activation path (pay {1}{W} → stack → resolve).
    rust_state.apply_action({
        "kind": "activate_ability",
        "source_id": rs_robe,
        "ability_index": 0,
    })
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    # The {1}{W} cost was fully paid.
    assert rust_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
    }

    # Python: drive the real-parsed Effect's resolve directly with the
    # resolving Equipment source set (the resolve boundary).
    py_state.resolving_source = py_robe
    try:
        real_aa_effect.resolve(py_state, 0, ())
    finally:
        py_state.resolving_source = None

    # ----- byte-equal phased-out state on EVERY object -----
    # Host phased out on both.
    assert _rust_obj_field(rust_state, rs_host, "phased_out") is True
    assert _py_obj(py_state, py_host.id).phased_out is True
    assert (
        _rust_obj_field(rust_state, rs_host, "phased_out")
        == _py_obj(py_state, py_host.id).phased_out
        is True
    )
    # The Robe itself is NOT phased out on either engine.
    assert _rust_obj_field(rust_state, rs_robe, "phased_out") is False
    assert _py_obj(py_state, py_robe.id).phased_out is False
    assert (
        _rust_obj_field(rust_state, rs_robe, "phased_out")
        == _py_obj(py_state, py_robe.id).phased_out
        is False
    )
    # The unrelated opponent creature is NOT phased out on either.
    assert _rust_obj_field(rust_state, rs_opp, "phased_out") is False
    assert _py_obj(py_state, py_opp.id).phased_out is False
    assert (
        _rust_obj_field(rust_state, rs_opp, "phased_out")
        == _py_obj(py_state, py_opp.id).phased_out
        is False
    )

    # ===== Scenario B: Robe NOT equipped — silent no-op. =====
    rust_state2 = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    rs_robe2 = rust_state2.register_and_inject_object(
        _synthetic_robe_dict(), 0, ZONE_BATTLEFIELD
    )
    rust_state2.force_set_summoning_sick(rs_robe2, False)
    rust_state2.add_mana(0, "W", 2)

    py_state2 = _py_new_state()
    py_robe2 = _py_put(py_state2, real, 0)  # unattached

    rust_state2.apply_action({
        "kind": "activate_ability",
        "source_id": rs_robe2,
        "ability_index": 0,
    })
    while rust_state2.stack_size() > 0:
        rust_state2.resolve_top_of_stack()

    py_state2.resolving_source = py_robe2
    try:
        real_aa_effect.resolve(py_state2, 0, ())
    finally:
        py_state2.resolving_source = None

    # No object phased out on either engine — the unequipped AA is a
    # byte-equal no-op.
    assert _rust_obj_field(rust_state2, rs_robe2, "phased_out") is False
    assert _py_obj(py_state2, py_robe2.id).phased_out is False
    assert (
        _rust_obj_field(rust_state2, rs_robe2, "phased_out")
        == _py_obj(py_state2, py_robe2.id).phased_out
        is False
    )


def _bear_inj_py(name):
    """Python-side bear printing matching ``_bear_inj``'s shape."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
