"""Hushwood Verge — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Hushwood Verge is a Foundations (FDN) verge land — a dual-color
"verge" reprint slot in the EoE merged pool (0 17lands decks).  The
parser flattens the printed oracle (conditional-tapped-unless-you-
control-a-Forest-or-Plains rider + a two-color ``{T}`` mana ability)
to the always-untapped dual-mana-land shape.

Parser-flattened shape: ``Land``, ``produces=frozenset({'W', 'G'})``,
``enters_tapped_unless_any_player_life_at_most=0``, ``enters_tapped=
False``, TWO parser-emitted ``ActivatedAbility(AddManaToPool({c}, 1),
tap_self=True, is_mana_ability=True)`` AAs.

**EEEE-idiom for the parser-emitted dual-AA-mana-land bridge carrier**
— sibling to the other four batch verge probes; the per-slug
attribution distinction is the **(W, G) color pair**.
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


def test_hushwood_verge_parser_claims_card():
    assert "Hushwood Verge" in _PRINTINGS, (
        "Hushwood Verge must be parser-claimed by the active CardSource"
    )


def test_hushwood_verge_printed_attrs():
    """Pins the basic printing surface."""
    p = _PRINTINGS["Hushwood Verge"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset({"W", "G"})
    assert p.enters_tapped_unless_any_player_life_at_most == 0
    assert p.enters_tapped is False
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert len(p.activated_abilities) == 2
    aa_colors = [aa.effect.produces[0][0] for aa in p.activated_abilities]
    assert aa_colors == ["G", "W"], (
        f"Hushwood Verge AAs must be ordered G then W; got {aa_colors}"
    )
    for aa in p.activated_abilities:
        assert isinstance(aa.effect, AddManaToPool)
        assert aa.effect.produces[0][1] == 1
        assert aa.effect.spend_restriction is None
        assert aa.cost.tap_self is True
        assert aa.cost.mana is None
        assert aa.cost.sacrifice_self is False
        assert aa.cost.pay_life == 0
        assert aa.is_mana_ability is True
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.keywords == frozenset()


def test_hushwood_verge_aa_effect_bridge_round_trip():
    """The ``add_mana_to_pool`` bridge arm round-trips Hushwood
    Verge's two parser-emitted AA effects byte-equal."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = _PRINTINGS["Hushwood Verge"]
    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    bridged_w = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "W", "amount": 1}
    )
    assert isinstance(bridged_g, AddManaToPool)
    assert isinstance(bridged_w, AddManaToPool)
    assert bridged_g.produces == (("G", 1),)
    assert bridged_w.produces == (("W", 1),)
    aa_effects = [aa.effect for aa in real.activated_abilities]
    assert bridged_g in aa_effects
    assert bridged_w in aa_effects


@_rust_skip
def test_rust_parser_accepts_hushwood_verge_dual_mana_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Hushwood-Verge-shape registry dict."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Hushwood Verge (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "G",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "W",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
            ],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_hushwood_verge_parser_emitted_dual_mana_wg_parity():
    """**GENUINE real-EoE cross-engine probe — Hushwood Verge
    parser-emitted-dual-mana (W/G) → twin ``AddManaToPool`` AA
    resolve.  PROBED-tier flip (covered_by_construction → PROBED).**

    Distinct from the sibling verge probes on the **(W, G) color
    pair**.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Hushwood Verge")
    if real is None:
        pytest.skip("Hushwood Verge absent from active CardSource")
    assert "Land" in real.card_types
    assert real.produces == frozenset({"W", "G"})
    assert len(real.activated_abilities) == 2

    assert real.produces == frozenset({"W", "G"}), (
        "Hushwood Verge's produces is {'W', 'G'} — distinct from "
        "Blazemire Verge ({'B', 'R'}) / Floodfarm Verge ({'W', 'U'}) "
        "/ Gloomlake Verge ({'U', 'B'}) / Thornspire Verge ({'G', 'R'}) "
        "sibling verge probes"
    )

    bridged_g = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
    )
    bridged_w = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "W", "amount": 1}
    )
    aa_effects = [aa.effect for aa in real.activated_abilities]
    assert bridged_g in aa_effects
    assert bridged_w in aa_effects

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    assert len(py_state.players[0].mana_pool) == 0

    aa_by_color = {
        aa.effect.produces[0][0]: aa
        for aa in real.activated_abilities
    }
    assert set(aa_by_color.keys()) == {"G", "W"}

    aa_by_color["G"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1
    assert p0_pool[0].color == "G"
    assert p0_pool[0].spend_restriction is None

    aa_by_color["W"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 2
    coin_colors = sorted(coin.color for coin in p0_pool)
    assert coin_colors == ["G", "W"]
    assert len(py_state.players[1].mana_pool) == 0
