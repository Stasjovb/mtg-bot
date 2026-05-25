"""Bleeding Woods — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Bleeding Woods is a Duskmourn conditional-painland reprint in the
EoE merged pool (0 17lands decks — off-set DSK card not in the EoE
draft sample).  Card text:

    "This land enters tapped unless a player has 13 or less life.
     {T}: Add {R} or {G}."

Parser-flattened shape: ``Land`` (no subtypes, no supertypes),
``produces=frozenset({'G', 'R'})``,
``enters_tapped_unless_any_player_life_at_most=13``, ``enters_tapped=
False``, ZERO activated/triggered/static abilities.

**EEEE-idiom for the conditional-painland bridge carrier.**  Sibling
to ``test_abandoned_campground_parity.py`` — bit-identical at the
bridge-auto-wire mechanism; the per-slug attribution distinction is
the **(G, R) color pair** vs Abandoned Campground's (W, U).  Per the
cathedral-of-war-style same-shape-different-printing-slug precedent,
each dual-color painland slug earns its own PROBED-tier slot.
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


def test_bleeding_woods_parser_claims_card():
    assert "Bleeding Woods" in _PRINTINGS, (
        "Bleeding Woods must be parser-claimed by the active CardSource"
    )


def test_bleeding_woods_printed_attrs():
    """Pins the basic printing surface: non-basic Land,
    ``produces={'G', 'R'}``, threshold=13, no other riders."""
    p = _PRINTINGS["Bleeding Woods"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset({"G", "R"})
    assert p.enters_tapped_unless_any_player_life_at_most == 13
    assert p.enters_tapped is False
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.keywords == frozenset()


def test_bleeding_woods_loader_admits_as_painland_conditional():
    """Pins the Phase-2 painland admit gate."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_painland_conditional,
        _printing_is_bridge_basic_land,
    )

    p = _PRINTINGS["Bleeding Woods"]
    assert _printing_is_bridge_nonbasic_painland_conditional(p) is True
    assert _printing_is_bridge_basic_land(p) is False


def test_bleeding_woods_card_def_bridge_round_trip():
    """CardDef bridge round-trip: dual-color painland auto-wire +
    threshold preserved."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS["Bleeding Woods"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Bleeding Woods"
    assert cd.card_type == "Land"
    assert set(cd.mana_produced) == {"G", "R"}
    assert cd.enters_tapped_unless_any_player_life_at_most == 13

    py_round = _card_def_to_python_printing(cd)
    assert py_round.produces == frozenset({"G", "R"})
    assert py_round.enters_tapped_unless_any_player_life_at_most == 13
    assert len(py_round.activated_abilities) == 2
    aa_colors = sorted(
        aa.effect.produces[0][0]
        for aa in py_round.activated_abilities
    )
    assert aa_colors == ["G", "R"]
    for aa in py_round.activated_abilities:
        assert isinstance(aa.effect, AddManaToPool)
        assert aa.effect.produces[0][1] == 1
        assert aa.effect.spend_restriction is None
        assert aa.cost.tap_self is True
        assert aa.is_mana_ability is True

    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    bridged_r = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "R", "amount": 1}
    )
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    assert bridged_g in aa_effects
    assert bridged_r in aa_effects


@_rust_skip
def test_rust_parser_accepts_bleeding_woods_painland_dict():
    """Rust ``register_printing`` accepts the painland shape."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Bleeding Woods (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["G", "R"],
            "enters_tapped_unless_any_player_life_at_most": 13,
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_bleeding_woods_painland_conditional_gr_parity():
    """**GENUINE real-EoE cross-engine probe — Bleeding Woods
    conditional-painland (G/R) → dual ``AddManaToPool(produces=
    ((<C>, 1),))`` bridge auto-wire. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Bleeding Woods printing** through the
    CardDef bridge round-trip + Python-side resolve.  Sibling to the
    batch-9 Abandoned Campground (W/U), Murky Sewer (U/B), Razortrap
    Gorge (B/R), Strangled Cemetery (B/G) painland probes — each
    color pair earns its own PROBED-tier slot per the cathedral-of-
    war-style same-shape-different-printing-slug precedent.
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Bleeding Woods")
    if real is None:
        pytest.skip("Bleeding Woods absent from active CardSource")
    assert "Land" in real.card_types
    assert real.produces == frozenset({"G", "R"})
    assert real.enters_tapped_unless_any_player_life_at_most == 13
    assert real.activated_abilities == ()

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.produces == frozenset({"G", "R"}), (
        "Bleeding Woods's produces is {'G', 'R'} — distinct from "
        "sibling painland probes"
    )

    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    bridged_r = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "R", "amount": 1}
    )
    assert isinstance(bridged_g, AddManaToPool)
    assert isinstance(bridged_r, AddManaToPool)
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    assert bridged_g in aa_effects
    assert bridged_r in aa_effects

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
    assert set(aa_by_color.keys()) == {"G", "R"}

    aa_by_color["G"].effect.resolve(py_state, py_source.controller_id)
    assert len(py_state.players[0].mana_pool) == 1
    assert py_state.players[0].mana_pool[0].color == "G"

    aa_by_color["R"].effect.resolve(py_state, py_source.controller_id)
    coin_colors = sorted(
        coin.color for coin in py_state.players[0].mana_pool
    )
    assert coin_colors == ["G", "R"]
    assert len(py_state.players[1].mana_pool) == 0
