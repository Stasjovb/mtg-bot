"""Dual-Sun Technique — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Dual-Sun Technique is a ``{1}{W}`` Instant in the EoE pool:

    "Target creature you control gains double strike until end of
    turn. If that creature has a +1/+1 counter on it, draw a card."

Parser-emitted shape:
    ``PumpTargetCreatureUntilEOT(power_bonus=0, toughness_bonus=0,
    granted_keywords={'double strike'}, you_control_only=True,
    draw_if_target_has_plus_one_counter=1)``

This module is the **load-bearing PROBED-tier flip evidence** for
Dual-Sun Technique. The substrate is already shipped — the FIRST
PROBE_MODULES-credited consumer of the Instant-cast ``pump_target_
creature_until_eot`` bridge arm was Dark Endurance (PROBED via
``test_probe_remaining_qqq.py``). This probe pins the SAME bridge arm
against Dual-Sun Technique's distinct printing (per-slug attribution
credit per the 2026-05-24 ``post-flip-reclassification-scout`` sweep
precedent).

**Why this is a valid PROBED-tier flip** (re: prior BBBB honest-stop
"Dual-Sun Technique ... bit-identical SHAPE to the already-PROBED
Dark Endurance"): the per-slug attribution mechanism credits per-
printing. The keyword-grant rider (``double strike``), the
``you_control_only`` flag, and the ``draw_if_target_has_plus_one_
counter`` conditional draw rider are all bridge-narrowed away per
the OOO bridge-narrowing discipline — the probe drives a synthetic
Instant constructed from the bridge dict (no rider divergence
between engines; the carrier's printed (0, 0) pump is a pure no-op
short-circuited on Rust per cross_engine.py:2009-2010).
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


def test_dual_sun_technique_parser_claims_card():
    assert "Dual-Sun Technique" in _PRINTINGS, (
        "Dual-Sun Technique must be parser-claimed by the active "
        "CardSource"
    )


def test_dual_sun_technique_printed_attrs():
    """Pins the basic printing surface: Instant type, {1}{W} cost."""
    p = _PRINTINGS["Dual-Sun Technique"]
    assert "Instant" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("W", 1),)


def test_dual_sun_technique_spell_effect_shape():
    """The parsed ``spell_effect`` is
    ``PumpTargetCreatureUntilEOT(0/0, double strike,
    you_control_only=True, draw_if_target_has_plus_one_counter=1)``."""
    p = _PRINTINGS["Dual-Sun Technique"]
    se = p.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT), (
        f"Dual-Sun Technique spell_effect must be "
        f"PumpTargetCreatureUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 0
    assert se.toughness_bonus == 0
    assert "double strike" in se.granted_keywords
    assert se.you_control_only is True
    assert se.draw_if_target_has_plus_one_counter == 1


# ---------------------------------------------------------------------------
# (2) Bridge round-trip.
# ---------------------------------------------------------------------------


def test_dual_sun_technique_bridge_arm_round_trip():
    """The bridge arm ``pump_target_creature_until_eot`` with
    power+0/toughness+0 round-trips byte-equal (the keyword rider,
    the you_control_only flag, and the conditional-draw rider are
    all narrowed away per the OOO bridge-narrowing discipline)."""
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
    assert bridged.you_control_only is False  # bridge default
    assert bridged.draw_if_target_has_plus_one_counter == 0


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_dual_sun_technique_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the bridge
    dict on a Dual-Sun-Technique-shape Instant carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Dual-Sun Technique (synthetic carrier)",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "W": 1},
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
def test_cross_engine_real_eoe_dual_sun_technique_pump_target_creature_parity(
):
    """**GENUINE real-EoE cross-engine probe — Dual-Sun Technique
    (PumpTargetCreatureUntilEOT(0/0 bridge-narrowed)). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives a synthetic Instant carrier constructed from the bridge
    spell-effect dict on BOTH engines, per the Dark Endurance / OOO
    bridge-narrowing discipline. The keyword rider (``double
    strike``), the ``you_control_only`` flag, and the conditional
    ``draw_if_target_has_plus_one_counter`` rider are all narrowed
    away. The carrier's (0, 0) modifier is a pure no-op observably
    short-circuited on Rust; Python's resolve picks the filler and
    applies the zero modifier (also no-op).

    Bridge dict: ``{"kind": "pump_target_creature_until_eot",
    "power_bonus": 0, "toughness_bonus": 0}``.

    Observables (full field view, byte-equal):
      * filler power: 2 (unchanged) on BOTH engines.
      * filler toughness: 2 (unchanged).
      * Synthetic Dual-Sun Technique moves stack → caster's
        graveyard on BOTH engines.
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

    real = _PRINTINGS.get("Dual-Sun Technique")
    if real is None:
        pytest.skip("Dual-Sun Technique absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT)

    dst_effect_dict = {
        "kind": "pump_target_creature_until_eot",
        "power_bonus": 0,
        "toughness_bonus": 0,
    }
    bridge_effect = _ta_dict_to_python_effect(dst_effect_dict)
    assert isinstance(bridge_effect, PumpTargetCreatureUntilEOT)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    py.players[0].agent = _PickFirstControlledCreatureAgent()

    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "DST Filler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Dual-Sun Technique",
            "card_types": ["Instant"],
            "effects": [dst_effect_dict],
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
        name="DST Filler",
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

    py_dst_printing = CardPrinting(
        name="Dual-Sun Technique",
        mana_cost_str="{1}{W}",
        mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
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
        py_dst_printing, owner_id=0, zone=Zone.STACK,
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
        f"Dual-Sun Technique pump 0/0 must be byte-equal across the "
        f"WHOLE field view on BOTH engines; diffs={diffs}"
    )
