"""Blazemire Verge — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Blazemire Verge is a Foundations (FDN) verge land — a dual-color
"verge" / "Magic of Defense" reprint slot in the EoE merged pool (0
17lands decks — off-set FDN card not in the EoE draft sample).  The
parser flattens the printed oracle (a conditional-tapped-unless-you-
control-a-Swamp-or-Mountain rider + a two-color ``{T}`` mana ability)
to the simpler always-untapped dual-mana-land shape:

Parser-flattened shape: ``Land`` (no subtypes, no supertypes),
``produces=frozenset({'B', 'R'})``, ``enters_tapped_unless_any_player_
life_at_most=0`` (the disabled sentinel — the verge's
"you-control-a-Swamp-or-Mountain" rider is documented-DROP at the
parser shape level), ``enters_tapped=False``, TWO parser-emitted
``ActivatedAbility(AddManaToPool({c}, 1), tap_self=True,
is_mana_ability=True)`` AAs (one per produce-color).

**EEEE-idiom for the parser-emitted dual-AA-mana-land bridge carrier.**
Sibling to ``test_etched_cornfield_parity.py`` / ``test_lakeside_
shack_parity.py`` / ``test_neglected_manor_parity.py`` / ``test_
peculiar_lighthouse_parity.py`` / ``test_raucous_carnival_parity.py``
(batch 10 Duskmourn-painland cycle) — bit-identical at the
``_ta_dict_to_python_effect`` per-color round-trip mechanism; the
per-slug attribution distinction is the **PARSER-EMITTED AAs**
sub-shape (the AAs ship on the printing directly, NOT bridge-auto-
wired from ``mana_produced``; the painland sibling probes ALL go
through ``_card_def_to_python_printing``'s auto-wire path — Blazemire
Verge does NOT, because the verge has no ``_printing_to_card_def``
admit gate today).

Per the cathedral-of-war-style same-shape-different-printing-slug
precedent, each dual-color verge slug earns its own PROBED-tier slot.
This probe pins the **(B, R) color pair** on the parser-emitted-AA
sub-shape.  Sibling probes in this batch cover Floodfarm Verge (W/U),
Gloomlake Verge (U/B), Hushwood Verge (W/G), Thornspire Verge (G/R)
— closes the EoE-pool FDN-verge enemy-color cycle (the 5 ally-color
verges are not in the EoE merged pool).
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


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Blazemire Verge is parser-claimed with the
# parser-emitted-dual-AA-mana-land shape (produces={B, R}, threshold=
# disabled, two AAs, both AddManaToPool with tap_self cost).
# ---------------------------------------------------------------------------


def test_blazemire_verge_parser_claims_card():
    assert "Blazemire Verge" in _PRINTINGS, (
        "Blazemire Verge must be parser-claimed by the active CardSource"
    )


def test_blazemire_verge_printed_attrs():
    """Pins the basic printing surface: non-basic Land, no subtypes /
    supertypes, ``produces={'B', 'R'}``, ``enters_tapped_unless_any_
    player_life_at_most=0`` (disabled sentinel), ``enters_tapped=
    False``, two parser-emitted AAs (one per produce-color, tap_self
    cost, mana ability), no TAs / static abilities / keywords /
    spell_effect."""
    p = _PRINTINGS["Blazemire Verge"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset({"B", "R"}), (
        f"Blazemire Verge must produce {{'B', 'R'}}; got "
        f"produces={p.produces}"
    )
    # 0-sentinel: the verge's "you-control-a-Swamp-or-Mountain" rider
    # is documented-DROP at the parser shape level; the disabled
    # sentinel is the parser's canonical "no conditional-tapped"
    # encoding (cards/base.py:733 — "0 disables").
    assert p.enters_tapped_unless_any_player_life_at_most == 0
    assert p.enters_tapped is False
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert len(p.activated_abilities) == 2, (
        f"Blazemire Verge must have exactly 2 parser-emitted "
        f"ActivatedAbilities; got {len(p.activated_abilities)}"
    )
    aa_colors = [aa.effect.produces[0][0] for aa in p.activated_abilities]
    assert aa_colors == ["B", "R"], (
        f"Blazemire Verge AAs must be ordered B then R (matching "
        f"printed oracle 'Add {{B}} or {{R}}'); got {aa_colors}"
    )
    for aa in p.activated_abilities:
        assert isinstance(aa.effect, AddManaToPool)
        assert aa.effect.produces[0][1] == 1
        assert aa.effect.spend_restriction is None
        assert aa.cost.tap_self is True
        # No additional cost atoms (no mana, no sac, no life payment).
        assert aa.cost.mana is None
        assert aa.cost.sacrifice_self is False
        assert aa.cost.pay_life == 0
        assert aa.is_mana_ability is True
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.keywords == frozenset()


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the ``add_mana_to_pool`` bridge arm round-
# trips each parser-emitted AA's effect dict to a byte-equal
# ``AddManaToPool`` instance.  The verge has no
# ``_printing_to_card_def`` admit gate today (the FDN-verge shape is
# §2-declined at the non-basic-land substrate's untapped-no-AA
# guardrail — ``_printing_is_bridge_nonbasic_mana_land`` rejects on
# the ``printing.activated_abilities`` non-emptiness check), so the
# bridge round-trip pin operates at the per-Effect-dict level via
# ``_ta_dict_to_python_effect`` rather than the per-CardDef level via
# ``_card_def_to_python_printing``.  This is the SAME bridge contract
# the Duskmourn-painland sibling probes exercise (their per-color
# ``_ta_dict_to_python_effect`` round-trip is bit-identical to this
# probe's); the distinction is which path materializes the AA list
# (parser-emit vs bridge-auto-wire).
# ---------------------------------------------------------------------------


def test_blazemire_verge_aa_effect_bridge_round_trip():
    """The ``add_mana_to_pool`` bridge arm round-trips Blazemire
    Verge's two parser-emitted AA effects byte-equal.

    Effect-level byte-equality between the bridge dict shape and the
    bridged Effect — the canonical add_mana_to_pool round-trip the
    Duskmourn-painland sibling probes use for the bridge-auto-wired
    AA list.  Here the parser already shipped the same effect objects
    on the live printing; the bridge arm is verified to produce
    byte-equal copies.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = _PRINTINGS["Blazemire Verge"]
    bridged_b = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    bridged_r = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "R", "amount": 1}
    )
    assert isinstance(bridged_b, AddManaToPool)
    assert isinstance(bridged_r, AddManaToPool)
    assert bridged_b.produces == (("B", 1),)
    assert bridged_r.produces == (("R", 1),)
    assert bridged_b.spend_restriction is None
    assert bridged_r.spend_restriction is None

    # Byte-equality between the bridged copies and the parser-emitted
    # AA effects on the live printing.
    aa_effects = [aa.effect for aa in real.activated_abilities]
    assert bridged_b in aa_effects, (
        "Bridged B AddManaToPool must equal the parser-emitted AA[0] "
        "effect on Blazemire Verge"
    )
    assert bridged_r in aa_effects, (
        "Bridged R AddManaToPool must equal the parser-emitted AA[1] "
        "effect on Blazemire Verge"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# Blazemire-Verge-shape registry dict (Land with two ``add_mana_to_
# pool`` mana abilities).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_blazemire_verge_dual_mana_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Blazemire-Verge-shape registry dict — non-basic Land + two mana
    abilities (one per produce-color), each with ``tap_self`` cost
    and ``add_mana_to_pool`` effect."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Blazemire Verge (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "B",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "add_mana_to_pool",
                        "color": "R",
                        "amount": 1,
                    },
                    "is_mana_ability": True,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Blazemire Verge printing through Python-side resolve
# of each of its TWO parser-emitted mana abilities.  Both AAs mint
# the matching-color coin on the controller's mana pool; opponent's
# pool stays empty.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_blazemire_verge_parser_emitted_dual_mana_br_parity():
    """**GENUINE real-EoE cross-engine probe — Blazemire Verge
    parser-emitted-dual-mana (B/R) → twin ``AddManaToPool(produces=
    ((<C>, 1),))`` AA resolve.  PROBED-tier flip (covered_by_
    construction → PROBED).**

    Drives the **ACTUAL parsed Blazemire Verge printing** through
    Python-side resolve of each of its two parser-emitted mana
    abilities.  Distinct from the Duskmourn-painland sibling probes
    (Etched Cornfield / Lakeside Shack / Neglected Manor / Peculiar
    Lighthouse / Raucous Carnival / Abandoned Campground / Bleeding
    Woods / Murky Sewer / Razortrap Gorge / Strangled Cemetery) on
    TWO axes:
      * **AA materialization path** — the verge AAs ship on the parser
        printing directly (``len(real.activated_abilities) == 2`` on
        the live printing); the painland sibling probes go through
        the bridge auto-wire (``_card_def_to_python_printing``
        synthesizes the AAs from ``mana_produced``).  The verge's
        ``_printing_is_bridge_nonbasic_mana_land`` predicate REJECTS
        on the ``printing.activated_abilities`` non-emptiness check
        — the parser-emit path is §2-declined at the admit gate
        today, so the probe operates on ``real`` directly rather
        than on a round-tripped ``_card_def_to_python_printing(cd)``
        carrier.
      * **(B, R) color pair** — distinct from any painland sibling
        pair (Abandoned Campground W/U, Bleeding Woods G/R, Murky
        Sewer U/B, Razortrap Gorge B/R, Strangled Cemetery B/G,
        Etched Cornfield G/W, Lakeside Shack G/U, Neglected Manor
        W/B, Peculiar Lighthouse U/R, Raucous Carnival W/R).
        Razortrap Gorge ALSO pins B/R but on the painland sub-shape
        (bridge-auto-wire path) — Blazemire Verge pins B/R on the
        parser-emit sub-shape (the orthogonal axis).

    **Bridge arm exercised:**
      * ``add_mana_to_pool`` (the canonical per-color bridge arm;
        'B' AND 'R' per-color dispatch verified byte-equal against
        the parser-emitted AA effects in
        ``test_blazemire_verge_aa_effect_bridge_round_trip``).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Blazemire Verge")
    if real is None:
        pytest.skip("Blazemire Verge absent from active CardSource")
    assert "Land" in real.card_types
    assert real.produces == frozenset({"B", "R"})
    assert len(real.activated_abilities) == 2
    assert real.triggered_abilities == ()

    # Distinctness regression guard — the verge's produces tuple is
    # dual-color {'B', 'R'}; sibling verge probes pin distinct color
    # pairs (W/U, U/B, W/G, G/R).
    assert real.produces == frozenset({"B", "R"}), (
        "Blazemire Verge's produces is {'B', 'R'} — distinct from "
        "Floodfarm Verge ({'W', 'U'}) / Gloomlake Verge ({'U', 'B'}) "
        "/ Hushwood Verge ({'W', 'G'}) / Thornspire Verge ({'G', 'R'}) "
        "sibling verge probes"
    )

    # Both bridge-arm dispatches: 'B' and 'R' — byte-equal to the
    # parser-emitted AA effects on the live printing.
    bridged_b = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "B", "amount": 1}
    )
    bridged_r = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "R", "amount": 1}
    )
    assert isinstance(bridged_b, AddManaToPool)
    assert isinstance(bridged_r, AddManaToPool)
    aa_effects = [aa.effect for aa in real.activated_abilities]
    assert bridged_b in aa_effects
    assert bridged_r in aa_effects

    # Python-side resolve smoke — both mana abilities mint the right
    # color coins.  Seats the live ``real`` printing on p0's
    # battlefield (no bridge round-trip path is available for the
    # verge today; the parser-emit AAs are exercised directly).
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

    # Identify the AAs by their effect's produce-color (the parser
    # emits them in the printed-oracle order: B then R).
    aa_by_color = {
        aa.effect.produces[0][0]: aa
        for aa in real.activated_abilities
    }
    assert set(aa_by_color.keys()) == {"B", "R"}

    aa_by_color["B"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1
    assert p0_pool[0].color == "B", (
        f"Blazemire Verge's B-mana AA must mint a 'B' coin; got "
        f"color={p0_pool[0].color!r}"
    )
    assert p0_pool[0].spend_restriction is None

    aa_by_color["R"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 2
    coin_colors = sorted(coin.color for coin in p0_pool)
    assert coin_colors == ["B", "R"], (
        f"After resolving both AAs, pool must contain one B coin + "
        f"one R coin; got colors={coin_colors}"
    )
    # Opponent's pool stays untouched.
    assert len(py_state.players[1].mana_pool) == 0
