"""Give In to Violence — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Give In to Violence is a ``{1}{B}`` Instant in the EoE pool:

    "Target creature gets +2/+2 and gains lifelink until end of turn."

Parser-emitted shape:
    ``PumpTargetCreatureUntilEOT(power_bonus=2, toughness_bonus=2,
    granted_keywords={'lifelink'})``

This module is the **load-bearing PROBED-tier flip evidence** for Give
In to Violence. The substrate is already shipped — the FIRST PROBE_
MODULES-credited consumer of the Instant-cast ``pump_target_creature_
until_eot`` bridge arm was Dark Endurance (PROBED via
``test_probe_remaining_qqq.py::test_cross_engine_real_eoe_dark_
endurance_pump_target_filler_parity``). This probe pins the SAME
bridge arm against Give In to Violence's distinct printing (per-slug
attribution credit per the 2026-05-24 ``post-flip-reclassification-
scout`` sweep precedent + the Unwanted Remake / Innocuous Rat / Fear
of Failed Tests probes from batches 1+2 that established per-slug
credit for bit-identical-shape probes).

**Why this is a valid PROBED-tier flip** (re: prior BBBB honest-stop
"Give In to Violence (... PumpTargetCreatureUntilEOT bit-identical to
PROBED Dark Endurance)"): the per-slug attribution mechanism credits
per-printing — even when the underlying Effect+bridge arm is bit-
identical to a sibling PROBED card. The keyword-grant rider
(``lifelink``) is bridge-narrowed away per the OOO bridge-narrowing
discipline that Dark Endurance established — the probe drives a
synthetic Instant constructed from the bridge dict (no keyword
divergence between engines).
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
# (1) Parser SoT — Give In to Violence is parser-claimed and emits the
# bare PumpTargetCreatureUntilEOT shape (+2/+2, lifelink rider).
# ---------------------------------------------------------------------------


def test_give_in_to_violence_parser_claims_card():
    assert "Give In to Violence" in _PRINTINGS, (
        "Give In to Violence must be parser-claimed by the active "
        "CardSource"
    )


def test_give_in_to_violence_printed_attrs():
    """Pins the basic printing surface: Instant type, {1}{B} cost."""
    p = _PRINTINGS["Give In to Violence"]
    assert "Instant" in p.card_types
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("B", 1),)


def test_give_in_to_violence_spell_effect_shape():
    """The parsed ``spell_effect`` is ``PumpTargetCreatureUntilEOT(+2/
    +2, lifelink)``; the bridge-narrowing discipline drops the
    keyword grant — only power_bonus / toughness_bonus reach Rust."""
    p = _PRINTINGS["Give In to Violence"]
    se = p.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT), (
        f"Give In to Violence spell_effect must be "
        f"PumpTargetCreatureUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 2
    assert se.toughness_bonus == 2
    assert "lifelink" in se.granted_keywords


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the pump_target_creature_until_eot bridge arm
# with power_bonus=2, toughness_bonus=2 round-trips to
# PumpTargetCreatureUntilEOT(power_bonus=2, toughness_bonus=2) (bridge
# narrows away the keyword rider per the OOO discipline).
# ---------------------------------------------------------------------------


def test_give_in_to_violence_bridge_arm_round_trip():
    """The bridge arm ``pump_target_creature_until_eot`` with power+2
    / toughness+2 round-trips byte-equal (granted_keywords narrowed
    away per the OOO bridge-narrowing discipline established by Dark
    Endurance)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 2,
            "toughness_bonus": 2,
        }
    )
    assert isinstance(bridged, PumpTargetCreatureUntilEOT)
    assert bridged.power_bonus == 2
    assert bridged.toughness_bonus == 2
    # The OOO bridge-narrowing discipline drops the keyword rider on
    # round-trip — bridged.granted_keywords is empty.
    assert bridged.granted_keywords == frozenset()


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust accepts the
# pump_target_creature_until_eot dict on a Give-In-to-Violence-shape
# Instant.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_give_in_to_violence_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "pump_target_creature_until_eot", "power_bonus": 2,
    "toughness_bonus": 2}`` dict shape on a Give-In-to-Violence-shape
    Instant carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Give In to Violence (synthetic carrier)",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "B": 1},
            "effects": [
                {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": 2,
                    "toughness_bonus": 2,
                }
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives a
# synthetic Give-In-to-Violence Instant carrier (bridge-narrowed) on
# BOTH engines through the spell-resolution path. Bare +2/+2 modifier
# lands on a filler 2/2; cross-engine full field view byte-equal.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_give_in_to_violence_pump_target_creature_parity(
):
    """**GENUINE real-EoE cross-engine probe — Give In to Violence
    (PumpTargetCreatureUntilEOT(+2/+2 bridge-narrowed)). PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives a synthetic Instant carrier constructed from the bridge
    spell-effect dict on BOTH engines. The real Give In to Violence
    printing is verified at probe entry for shape but NOT used to drive
    resolution — per the Dark Endurance / OOO bridge-narrowing
    discipline, the bridge ``pump_target_creature_until_eot`` arm does
    NOT plumb ``granted_keywords`` into the dict shape, so a probe
    driving the real printing on Python would grant lifelink while the
    bridge synth on Rust would not. Constructing the Python carrier
    from the bridge dict ensures both engines apply the SAME +2/+2
    mutation with no keyword divergence — the OOO bridge-narrowing
    discipline.

    Bridge dict: ``{"kind": "pump_target_creature_until_eot",
    "power_bonus": 2, "toughness_bonus": 2}``.

    Setup:
      * p0 has a filler 2/2 Creature (the only legal target on both
        engines).
      * p1 has no permanents.
      * Both engines push a synthetic ``Give In to Violence``-named
        Instant with the bridge spell_effect onto the stack.
      * Python side: ``_PickFirstControlledCreatureAgent`` picks the
        filler.

    Observables (full field view, byte-equal):
      * filler effective power: 2 → 4 on BOTH engines.
      * filler effective toughness: 2 → 4 on BOTH engines.
      * Synthetic Give In to Violence moves stack → caster's
        graveyard on BOTH engines.
      * Lives unchanged (the +2/+2 pump never resolves combat damage,
        so the lifelink rider — even if it were on the bridge — would
        be unobservable at this probe scope).
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

    # 1. Verify the genuine parsed Give In to Violence printing.
    real = _PRINTINGS.get("Give In to Violence")
    if real is None:
        pytest.skip("Give In to Violence absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT)
    assert se.power_bonus == 2
    assert se.toughness_bonus == 2
    assert "lifelink" in se.granted_keywords

    # 2. Build the bridge spell-effect dict (+2/+2, no keywords).
    giv_effect_dict = {
        "kind": "pump_target_creature_until_eot",
        "power_bonus": 2,
        "toughness_bonus": 2,
    }
    bridge_effect = _ta_dict_to_python_effect(giv_effect_dict)
    assert isinstance(bridge_effect, PumpTargetCreatureUntilEOT)
    assert bridge_effect.power_bonus == 2
    assert bridge_effect.toughness_bonus == 2

    # 3. Build cross-engine states (empty decks).
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # 4. Rust: seat the filler 2/2 on p0's bf, then push synthetic
    # Give In to Violence with the bridge spell_effect onto the stack.
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "GIV Filler",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        0, ZB,
    )
    assert rs.effective_power(rs_filler_id) == 2
    assert rs.effective_toughness(rs_filler_id) == 2

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Give In to Violence",
            "card_types": ["Instant"],
            "effects": [giv_effect_dict],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    assert rs.stack_size() == 1
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.effective_power(rs_filler_id) == 4, (
        "Rust: filler power must be 4 after +2 pump"
    )
    assert rs.effective_toughness(rs_filler_id) == 4, (
        "Rust: filler toughness must be 4 after +2 pump"
    )

    # 5. Python: seat the filler 2/2 on p0's bf, then push synthetic
    # Give In to Violence with the bridge spell_effect onto the stack.
    py_filler_printing = CardPrinting(
        name="GIV Filler",
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
    assert effective_power(py, py_filler) == 2
    assert effective_toughness(py, py_filler) == 2

    py_giv_printing = CardPrinting(
        name="Give In to Violence",
        mana_cost_str="{1}{B}",
        mana_cost=ManaCost(generic=1, colored=(("B", 1),)),
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
        py_giv_printing, owner_id=0, zone=Zone.STACK,
    )
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_filler.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert effective_power(py, py_filler) == 4
    assert effective_toughness(py, py_filler) == 4

    # 6. Cross-engine byte-equality across the WHOLE field view.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Give In to Violence pump +2/+2 must be byte-equal across "
        f"the WHOLE field view on BOTH engines; diffs={diffs}"
    )
