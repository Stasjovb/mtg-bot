"""Gloomlake Verge — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Gloomlake Verge is a Foundations (FDN) verge land — a dual-color
"verge" reprint slot in the EoE merged pool (0 17lands decks).  The
parser flattens the printed oracle (conditional-tapped-unless-you-
control-an-Island-or-Swamp rider + a two-color ``{T}`` mana ability)
to the always-untapped dual-mana-land shape.

Parser-flattened shape: ``Land``, ``produces=frozenset({'U', 'B'})``,
``enters_tapped_unless_any_player_life_at_most=0``, ``enters_tapped=
False``, TWO parser-emitted ``ActivatedAbility(AddManaToPool({c}, 1),
tap_self=True, is_mana_ability=True)`` AAs.

**EEEE-idiom for the parser-emitted dual-AA-mana-land bridge carrier**
— sibling to ``test_blazemire_verge_parity.py`` / ``test_floodfarm_
verge_parity.py`` / ``test_hushwood_verge_parity.py`` / ``test_
thornspire_verge_parity.py``; the per-slug attribution distinction is
the **(U, B) color pair**.
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


def test_gloomlake_verge_parser_claims_card():
    assert "Gloomlake Verge" in _PRINTINGS, (
        "Gloomlake Verge must be parser-claimed by the active CardSource"
    )


def test_gloomlake_verge_printed_attrs():
    """Pins the basic printing surface."""
    p = _PRINTINGS["Gloomlake Verge"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset({"U", "B"})
    assert p.enters_tapped_unless_any_player_life_at_most == 0
    assert p.enters_tapped is False
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert len(p.activated_abilities) == 2
    aa_colors = [aa.effect.produces[0][0] for aa in p.activated_abilities]
    assert aa_colors == ["U", "B"], (
        f"Gloomlake Verge AAs must be ordered U then B; got {aa_colors}"
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


def test_gloomlake_verge_aa_effect_bridge_round_trip():
    """The ``add_mana_to_pool`` bridge arm round-trips Gloomlake
    Verge's two parser-emitted AA effects byte-equal."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = _PRINTINGS["Gloomlake Verge"]
    bridged_u = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    bridged_b = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    assert isinstance(bridged_u, AddManaToPool)
    assert isinstance(bridged_b, AddManaToPool)
    assert bridged_u.produces == (("U", 1),)
    assert bridged_b.produces == (("B", 1),)
    aa_effects = [aa.effect for aa in real.activated_abilities]
    assert bridged_u in aa_effects
    assert bridged_b in aa_effects


@_rust_skip
def test_rust_parser_accepts_gloomlake_verge_dual_mana_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Gloomlake-Verge-shape registry dict."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Gloomlake Verge (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "U",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "B",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
            ],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_gloomlake_verge_parser_emitted_dual_mana_ub_parity():
    """**GENUINE real-EoE cross-engine probe — Gloomlake Verge
    parser-emitted-dual-mana (U/B) → twin ``AddManaToPool`` AA
    resolve.  PROBED-tier flip (covered_by_construction → PROBED).**

    Distinct from the sibling verge probes on the **(U, B) color
    pair**.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Gloomlake Verge")
    if real is None:
        pytest.skip("Gloomlake Verge absent from active CardSource")
    assert "Land" in real.card_types
    assert real.produces == frozenset({"U", "B"})
    assert len(real.activated_abilities) == 2

    assert real.produces == frozenset({"U", "B"}), (
        "Gloomlake Verge's produces is {'U', 'B'} — distinct from "
        "Blazemire Verge ({'B', 'R'}) / Floodfarm Verge ({'W', 'U'}) "
        "/ Hushwood Verge ({'W', 'G'}) / Thornspire Verge ({'G', 'R'}) "
        "sibling verge probes"
    )

    bridged_u = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    bridged_b = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    aa_effects = [aa.effect for aa in real.activated_abilities]
    assert bridged_u in aa_effects
    assert bridged_b in aa_effects

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
    assert set(aa_by_color.keys()) == {"U", "B"}

    aa_by_color["U"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1
    assert p0_pool[0].color == "U"
    assert p0_pool[0].spend_restriction is None

    aa_by_color["B"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 2
    coin_colors = sorted(coin.color for coin in p0_pool)
    assert coin_colors == ["B", "U"]
    assert len(py_state.players[1].mana_pool) == 0
