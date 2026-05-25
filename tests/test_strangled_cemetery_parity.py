"""Strangled Cemetery — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Strangled Cemetery is a Duskmourn conditional-painland reprint in
the EoE merged pool (0 17lands decks — off-set DSK card not in the
EoE draft sample).  Card text:

    "This land enters tapped unless a player has 13 or less life.
     {T}: Add {B} or {G}."

This is the 10th cycle member the original round-59 painland-
substrate audit missed (the Phase-2 spec listed only the 9 main
Duskmourn painlands; this slug shares the identical shape and the
predicate ``_printing_is_bridge_nonbasic_painland_conditional`` was
authored to admit all 10 — see the predicate docstring at
``trajectory.py:8226-8228``).

Parser-flattened shape: ``Land`` (no subtypes, no supertypes),
``produces=frozenset({'B', 'G'})``,
``enters_tapped_unless_any_player_life_at_most=13``, ``enters_tapped=
False``, ZERO activated/triggered/static abilities.

**EEEE-idiom for the conditional-painland bridge carrier.**  Sibling
to ``test_abandoned_campground_parity.py`` (W/U) /
``test_bleeding_woods_parity.py`` (G/R) /
``test_murky_sewer_parity.py`` (U/B) /
``test_razortrap_gorge_parity.py`` (B/R) — bit-identical at the
bridge-auto-wire mechanism; the per-slug attribution distinction is
the **(B, G) color pair** + the **audit-recovered-10th-member**
provenance.
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


def test_strangled_cemetery_parser_claims_card():
    assert "Strangled Cemetery" in _PRINTINGS, (
        "Strangled Cemetery must be parser-claimed by the active "
        "CardSource"
    )


def test_strangled_cemetery_printed_attrs():
    """Pins the basic printing surface."""
    p = _PRINTINGS["Strangled Cemetery"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset({"B", "G"})
    assert p.enters_tapped_unless_any_player_life_at_most == 13
    assert p.enters_tapped is False
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.keywords == frozenset()


def test_strangled_cemetery_loader_admits_as_painland_conditional():
    """Pins the Phase-2 painland admit gate (10th cycle member
    coverage)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_painland_conditional,
        _printing_is_bridge_basic_land,
    )

    p = _PRINTINGS["Strangled Cemetery"]
    assert _printing_is_bridge_nonbasic_painland_conditional(p) is True, (
        "Strangled Cemetery (10th cycle member, B/G) MUST pass the "
        "Phase-2 painland predicate per the audit-recovered-10th-"
        "member docstring at trajectory.py:8226-8228"
    )
    assert _printing_is_bridge_basic_land(p) is False


def test_strangled_cemetery_card_def_bridge_round_trip():
    """CardDef bridge round-trip: dual-color painland auto-wire +
    threshold preserved."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS["Strangled Cemetery"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Strangled Cemetery"
    assert cd.card_type == "Land"
    assert set(cd.mana_produced) == {"B", "G"}
    assert cd.enters_tapped_unless_any_player_life_at_most == 13

    py_round = _card_def_to_python_printing(cd)
    assert py_round.produces == frozenset({"B", "G"})
    assert py_round.enters_tapped_unless_any_player_life_at_most == 13
    assert len(py_round.activated_abilities) == 2
    aa_colors = sorted(
        aa.effect.produces[0][0]
        for aa in py_round.activated_abilities
    )
    assert aa_colors == ["B", "G"]
    for aa in py_round.activated_abilities:
        assert isinstance(aa.effect, AddManaToPool)
        assert aa.effect.produces[0][1] == 1
        assert aa.effect.spend_restriction is None
        assert aa.cost.tap_self is True
        assert aa.is_mana_ability is True

    bridged_b = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    assert bridged_b in aa_effects
    assert bridged_g in aa_effects


@_rust_skip
def test_rust_parser_accepts_strangled_cemetery_painland_dict():
    """Rust ``register_printing`` accepts the painland shape."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Strangled Cemetery (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["B", "G"],
            "enters_tapped_unless_any_player_life_at_most": 13,
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_strangled_cemetery_painland_conditional_bg_parity():
    """**GENUINE real-EoE cross-engine probe — Strangled Cemetery
    conditional-painland (B/G) → dual ``AddManaToPool(produces=
    ((<C>, 1),))`` bridge auto-wire. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Strangled Cemetery printing** through
    the CardDef bridge round-trip + Python-side resolve.  Sibling to
    the batch-9 Abandoned Campground (W/U), Bleeding Woods (G/R),
    Murky Sewer (U/B), Razortrap Gorge (B/R) painland probes —
    distinct (B, G) color pair earns its own PROBED-tier slot AND
    closes the audit-recovered-10th-member of the Duskmourn painland
    cycle.
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Strangled Cemetery")
    if real is None:
        pytest.skip("Strangled Cemetery absent from active CardSource")
    assert "Land" in real.card_types
    assert real.produces == frozenset({"B", "G"})
    assert real.enters_tapped_unless_any_player_life_at_most == 13
    assert real.activated_abilities == ()

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.produces == frozenset({"B", "G"}), (
        "Strangled Cemetery's produces is {'B', 'G'} — distinct from "
        "sibling painland probes"
    )

    bridged_b = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    assert bridged_b in aa_effects
    assert bridged_g in aa_effects

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
    assert set(aa_by_color.keys()) == {"B", "G"}

    aa_by_color["B"].effect.resolve(py_state, py_source.controller_id)
    assert len(py_state.players[0].mana_pool) == 1
    assert py_state.players[0].mana_pool[0].color == "B"

    aa_by_color["G"].effect.resolve(py_state, py_source.controller_id)
    coin_colors = sorted(
        coin.color for coin in py_state.players[0].mana_pool
    )
    assert coin_colors == ["B", "G"]
    assert len(py_state.players[1].mana_pool) == 0
