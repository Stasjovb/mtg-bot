"""Lakeside Shack — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Lakeside Shack is a Duskmourn conditional-painland reprint in the
EoE merged pool (0 17lands decks — off-set DSK card not in the EoE
draft sample).  Card text:

    "This land enters tapped unless a player has 13 or less life.
     {T}: Add {G} or {U}."

Parser-flattened shape: ``Land`` (no subtypes, no supertypes),
``produces=frozenset({'G', 'U'})``,
``enters_tapped_unless_any_player_life_at_most=13``, ``enters_tapped=
False``, ZERO activated/triggered/static abilities.

**EEEE-idiom for the conditional-painland bridge carrier.**  Sibling
to ``test_abandoned_campground_parity.py`` (W/U), ``test_bleeding_
woods_parity.py`` (G/R), ``test_murky_sewer_parity.py`` (U/B),
``test_razortrap_gorge_parity.py`` (B/R), ``test_strangled_
cemetery_parity.py`` (B/G) — bit-identical at the bridge-auto-wire
mechanism; the per-slug attribution distinction is the **(G, U) color
pair**.  Per the cathedral-of-war-style same-shape-different-printing-
slug precedent, each dual-color painland slug earns its own PROBED-
tier slot.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.mana import AddManaToPool


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_BATTLEFIELD = 2


def test_lakeside_shack_parser_claims_card():
    assert "Lakeside Shack" in _PRINTINGS, (
        "Lakeside Shack must be parser-claimed by the active CardSource"
    )


def test_lakeside_shack_printed_attrs():
    """Pins the basic printing surface: non-basic Land,
    ``produces={'G', 'U'}``, threshold=13, no other riders."""
    p = _PRINTINGS["Lakeside Shack"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset({"G", "U"})
    assert p.enters_tapped_unless_any_player_life_at_most == 13
    assert p.enters_tapped is False
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.keywords == frozenset()


def test_lakeside_shack_loader_admits_as_painland_conditional():
    """Pins the Phase-2 painland admit gate."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_painland_conditional,
        _printing_is_bridge_basic_land,
    )

    p = _PRINTINGS["Lakeside Shack"]
    assert _printing_is_bridge_nonbasic_painland_conditional(p) is True
    assert _printing_is_bridge_basic_land(p) is False


def test_lakeside_shack_card_def_bridge_round_trip():
    """CardDef bridge round-trip: dual-color painland auto-wire +
    threshold preserved."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS["Lakeside Shack"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Lakeside Shack"
    assert cd.card_type == "Land"
    assert set(cd.mana_produced) == {"G", "U"}
    assert cd.enters_tapped_unless_any_player_life_at_most == 13

    py_round = _card_def_to_python_printing(cd)
    assert py_round.produces == frozenset({"G", "U"})
    assert py_round.enters_tapped_unless_any_player_life_at_most == 13
    assert len(py_round.activated_abilities) == 2
    aa_colors = sorted(
        aa.effect.produces[0][0]
        for aa in py_round.activated_abilities
    )
    assert aa_colors == ["G", "U"]
    for aa in py_round.activated_abilities:
        assert isinstance(aa.effect, AddManaToPool)
        assert aa.effect.produces[0][1] == 1
        assert aa.effect.spend_restriction is None
        assert aa.cost.tap_self is True
        assert aa.is_mana_ability is True

    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    bridged_u = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    assert bridged_g in aa_effects
    assert bridged_u in aa_effects


@_rust_skip
def test_rust_parser_accepts_lakeside_shack_painland_dict():
    """Rust ``register_printing`` accepts the painland shape."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Lakeside Shack (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["G", "U"],
            "enters_tapped_unless_any_player_life_at_most": 13,
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_lakeside_shack_painland_conditional_gu_parity():
    """**GENUINE real-EoE cross-engine probe — Lakeside Shack
    conditional-painland (G/U) → dual ``AddManaToPool(produces=
    ((<C>, 1),))`` bridge auto-wire. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Lakeside Shack printing** through the
    CardDef bridge round-trip + Python-side resolve.  Sibling to the
    batch-9 Abandoned Campground (W/U), Bleeding Woods (G/R), Murky
    Sewer (U/B), Razortrap Gorge (B/R), Strangled Cemetery (B/G)
    painland probes — each color pair earns its own PROBED-tier slot
    per the cathedral-of-war-style same-shape-different-printing-slug
    precedent.
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Lakeside Shack")
    if real is None:
        pytest.skip("Lakeside Shack absent from active CardSource")
    assert "Land" in real.card_types
    assert real.produces == frozenset({"G", "U"})
    assert real.enters_tapped_unless_any_player_life_at_most == 13
    assert real.activated_abilities == ()

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.produces == frozenset({"G", "U"}), (
        "Lakeside Shack's produces is {'G', 'U'} — distinct from "
        "sibling painland probes"
    )

    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    bridged_u = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    assert isinstance(bridged_g, AddManaToPool)
    assert isinstance(bridged_u, AddManaToPool)
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    assert bridged_g in aa_effects
    assert bridged_u in aa_effects

    # Python-side resolve smoke.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    py_source = py_state.new_object(
        py_round, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    assert len(py_state.players[0].mana_pool) == 0

    aa_by_color = {
        aa.effect.produces[0][0]: aa
        for aa in py_round.activated_abilities
    }
    assert set(aa_by_color.keys()) == {"G", "U"}

    aa_by_color["G"].effect.resolve(py_state, py_source.controller_id)
    assert len(py_state.players[0].mana_pool) == 1
    assert py_state.players[0].mana_pool[0].color == "G"

    aa_by_color["U"].effect.resolve(py_state, py_source.controller_id)
    coin_colors = sorted(
        coin.color for coin in py_state.players[0].mana_pool
    )
    assert coin_colors == ["G", "U"]
    assert len(py_state.players[1].mana_pool) == 0
