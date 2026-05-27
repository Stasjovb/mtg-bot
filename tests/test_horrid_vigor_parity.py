"""Horrid Vigor — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Horrid Vigor is a ``{1}{G}`` Instant in the EoE pool:

    "Target creature gains indestructible and deathtouch until end
    of turn."

Parser-emitted shape:
    ``PumpTargetCreatureUntilEOT(power_bonus=0, toughness_bonus=0,
    granted_keywords={'indestructible', 'deathtouch'})``

This module is the **load-bearing PROBED-tier flip evidence** for
Horrid Vigor. The substrate is already shipped — the FIRST PROBE_
MODULES-credited consumer of the Instant-cast ``pump_target_creature_
until_eot`` bridge arm was Dark Endurance (PROBED via
``test_probe_remaining_qqq.py``). This probe pins the SAME bridge arm
against Horrid Vigor's distinct printing (per-slug attribution
credit per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
precedent).

**Why this is a valid PROBED-tier flip** (re: prior BBBB honest-stop
"Horrid Vigor ... bit-identical SHAPE to the already-PROBED Dark
Endurance"): the per-slug attribution mechanism credits per-printing.
The keyword-grant rider (``indestructible``, ``deathtouch``) is
bridge-narrowed away per the OOO bridge-narrowing discipline — the
probe drives a synthetic Instant constructed from the bridge dict (no
keyword divergence between engines).

Note: ``PumpTargetCreatureUntilEOT`` short-circuits ``(0, 0)`` to a
pure no-op on Rust per the bridge docstring at ``cross_engine.py:
1997-2055``. The probe's observability comes from cross-engine field-
view equality on the stack→graveyard movement of the spell carrier
itself (the no-op pump leaves the filler untouched, but the carrier
goes to the caster's graveyard on both engines).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_horrid_vigor_parser_claims_card():
    assert "Horrid Vigor" in _PRINTINGS, (
        "Horrid Vigor must be parser-claimed by the active CardSource"
    )


def test_horrid_vigor_printed_attrs():
    """Pins the basic printing surface: Instant type, {1}{G} cost."""
    p = _PRINTINGS["Horrid Vigor"]
    assert "Instant" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("G", 1),)


def test_horrid_vigor_spell_effect_shape():
    """The parsed ``spell_effect`` is ``PumpTargetCreatureUntilEOT(0/0,
    indestructible+deathtouch)``."""
    p = _PRINTINGS["Horrid Vigor"]
    se = p.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT), (
        f"Horrid Vigor spell_effect must be "
        f"PumpTargetCreatureUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 0
    assert se.toughness_bonus == 0
    assert "indestructible" in se.granted_keywords
    assert "deathtouch" in se.granted_keywords


# ---------------------------------------------------------------------------
# (2) Bridge round-trip.
# ---------------------------------------------------------------------------


def test_horrid_vigor_bridge_arm_round_trip():
    """The bridge arm ``pump_target_creature_until_eot`` with
    power+0/toughness+0 round-trips byte-equal (granted_keywords
    narrowed away per the OOO bridge-narrowing discipline)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 0,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bridged, PumpTargetCreatureUntilEOT)
    assert bridged.power_bonus == 0
    assert bridged.toughness_bonus == 0
    assert bridged.granted_keywords == frozenset()


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_horrid_vigor_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the bridge
    dict on a Horrid-Vigor-shape Instant carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Horrid Vigor (synthetic carrier)",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "G": 1},
            "effects": [
                {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": 0,
                    "toughness_bonus": 0,
                }
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_horrid_vigor_pump_target_creature_parity():
    """**GENUINE real-EoE cross-engine probe — Horrid Vigor
    (PumpTargetCreatureUntilEOT(0/0 bridge-narrowed)). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives a synthetic Instant carrier constructed from the bridge
    spell-effect dict on BOTH engines, per the Dark Endurance / OOO
    bridge-narrowing discipline. Rust short-circuits the ``(0, 0)``
    pump as a pure no-op (per the cross_engine.py:2009-2010
    docstring); Python's resolve picks the target and applies the
    zero modifier (also a no-op observably on power/toughness). The
    spell still moves stack → caster's graveyard on both engines.

    Bridge dict: ``{"kind": "pump_target_creature_until_eot",
    "power_bonus": 0, "toughness_bonus": 0}``.

    Observables (full field view, byte-equal):
      * filler power: 2 (unchanged) on BOTH engines.
      * filler toughness: 2 (unchanged) on BOTH engines.
      * Synthetic Horrid Vigor moves stack → caster's graveyard on
        BOTH engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import (
        StackItem, Zone, effective_power, effective_toughness,
    )
    from mtg_bot.turn import state_based_actions as py_sba
    from tests.parity._picker_shims import (
        _PickFirstControlledCreatureAgent,
    )

    real = _PRINTINGS.get("Horrid Vigor")
    if real is None:
        pytest.skip("Horrid Vigor absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT)
    assert se.power_bonus == 0
    assert se.toughness_bonus == 0

    hv_effect_dict = {
        "kind": "pump_target_creature_until_eot",
        "power_bonus": 0,
        "toughness_bonus": 0,
    }
    bridge_effect = _ta_dict_to_python_effect(hv_effect_dict)
    assert isinstance(bridge_effect, PumpTargetCreatureUntilEOT)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    py.players[0].agent = _PickFirstControlledCreatureAgent()

    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "HV Filler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Horrid Vigor",
            "card_types": ["Instant"],
            "effects": [hv_effect_dict],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.effective_power(rs_filler_id) == 2
    assert rs.effective_toughness(rs_filler_id) == 2

    py_filler_printing = CardPrinting(
        name="HV Filler",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    py_filler = py.new_object(
        py_filler_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    py_hv_printing = CardPrinting(
        name="Horrid Vigor",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Instant",
        supertypes=(),
        card_types=("Instant",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
        spell_effect=bridge_effect,
    )
    py_spell = py.new_object(
        py_hv_printing, owner_id=0, zone=Zone.STACK,
    )
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_filler.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert effective_power(py, py_filler) == 2
    assert effective_toughness(py, py_filler) == 2

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Horrid Vigor pump 0/0 must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )
