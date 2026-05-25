"""Abandoned Campground — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Abandoned Campground is a Duskmourn conditional-painland reprint in
the EoE merged pool (0 17lands decks — off-set DSK card not in the
EoE draft sample).  Card text:

    "This land enters tapped unless a player has 13 or less life.
     {T}: Add {W} or {U}."

Parser-flattened shape: ``Land`` (no subtypes, no supertypes),
``produces=frozenset({'W', 'U'})``,
``enters_tapped_unless_any_player_life_at_most=13``, ``enters_tapped=
False``, ZERO activated/triggered/static abilities (the parser
encodes the {T}-or-mana as a flat ``produces`` set + the conditional
as the dedicated threshold field, rather than as explicit AAs).

**EEEE-idiom for the conditional-painland bridge carrier.**  Same
lane discipline as batches 1-8 (parse + bridge round-trip + Python-
side resolve, NO cross-engine ``compare_fields``).  Templates
directly on the batch-6 basic-land siblings
``test_forest_parity.py`` / ``test_island_parity.py`` /
``test_mountain_parity.py`` / ``test_plains_parity.py`` /
``test_swamp_parity.py`` — bit-identical at the bridge auto-wire
mechanism (the bridge synthesizes per-produce-color
``ActivatedAbility(AddManaToPool(...))``); the per-slug attribution
distinction is the **dual-color produces** ({'W', 'U'}) + the
**conditional-tapped rider** (threshold=13, non-basic Land), as
distinct from the mono-color basic-land bridge auto-wire.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding a Duskmourn-painland slug to the conditional-tapped non-
basic-land bridge round-trip.  The dedicated predicate
``_printing_is_bridge_nonbasic_painland_conditional`` (Non-basic
land substrate — Phase 2, 2026-05-23) admits this shape; this probe
pins the per-slug PROBED-tier credit for the (W, U) color pair.

Per the cathedral-of-war-style same-shape-different-printing-slug
precedent, each dual-color painland slug earns its own PROBED-tier
slot — sibling probes in this batch cover Bleeding Woods (G/R),
Murky Sewer (U/B), Razortrap Gorge (B/R), Strangled Cemetery (B/G).
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
# (1) Parser SoT — Abandoned Campground is parser-claimed with the
# conditional-painland shape (produces={W, U}, threshold=13, zero
# riders).
# ---------------------------------------------------------------------------


def test_abandoned_campground_parser_claims_card():
    assert "Abandoned Campground" in _PRINTINGS, (
        "Abandoned Campground must be parser-claimed by the active "
        "CardSource"
    )


def test_abandoned_campground_printed_attrs():
    """Pins the basic printing surface: non-basic Land, no subtypes /
    supertypes, ``produces={'W', 'U'}``,
    ``enters_tapped_unless_any_player_life_at_most=13``,
    ``enters_tapped=False``, zero AAs/TAs/spell_effect."""
    p = _PRINTINGS["Abandoned Campground"]
    assert "Land" in p.card_types
    assert p.supertypes == ()
    assert p.subtypes == ()
    assert p.produces == frozenset({"W", "U"}), (
        f"Abandoned Campground must produce {{'W', 'U'}}; got "
        f"produces={p.produces}"
    )
    assert p.enters_tapped_unless_any_player_life_at_most == 13, (
        "Abandoned Campground must carry "
        "enters_tapped_unless_any_player_life_at_most=13 (the "
        "Duskmourn-painland conditional threshold)"
    )
    assert p.enters_tapped is False, (
        "The parser structures the conditional INSTEAD of the plain "
        "enters_tapped flag — both must agree on this carrier"
    )
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.keywords == frozenset()


def test_abandoned_campground_loader_admits_as_painland_conditional():
    """Pins the bridge-admit gate: Abandoned Campground passes
    ``_printing_is_bridge_nonbasic_painland_conditional`` (the
    Phase-2 painland predicate)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_nonbasic_painland_conditional,
        _printing_is_bridge_basic_land,
    )

    p = _PRINTINGS["Abandoned Campground"]
    assert (
        _printing_is_bridge_nonbasic_painland_conditional(p) is True
    ), (
        "Abandoned Campground must pass the Phase-2 painland predicate "
        "(non-basic Land, dual produces, threshold=13, no other riders)"
    )
    # Disjointness pin — the basic-land sibling predicate must REJECT
    # this carrier (it has no Basic supertype yet on the parser side).
    assert _printing_is_bridge_basic_land(p) is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — CardDef carries
# ``enters_tapped_unless_any_player_life_at_most=13`` +
# ``mana_produced=('U', 'W')``; the Python materialization auto-wires
# per-produce-color ``{T}: Add {C}`` mana abilities.
# ---------------------------------------------------------------------------


def test_abandoned_campground_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Abandoned Campground
    as a Python printing with the auto-wired per-color
    ``ActivatedAbility(AddManaToPool(...))`` mana abilities + the
    conditional-tapped threshold preserved.  The parser's flat
    ``produces`` shape is DOCUMENTED-DROP on AAs across the bridge
    (the bridge synthesizes AAs from ``mana_produced`` per the
    cross_engine.py:14073-14081 auto-wire; the parser ships zero
    AAs because the conditional gate is on the threshold field).
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        _card_def_to_python_printing, _ta_dict_to_python_effect,
    )

    real = _PRINTINGS["Abandoned Campground"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Abandoned Campground"
    assert cd.card_type == "Land"
    assert cd.mana_produced == ("U", "W") or cd.mana_produced == ("W", "U"), (
        f"CardDef.mana_produced must carry both U and W; got "
        f"{cd.mana_produced!r}"
    )
    assert cd.enters_tapped_unless_any_player_life_at_most == 13, (
        "CardDef must thread the conditional-tapped threshold (13) "
        "through the bridge"
    )

    py_round = _card_def_to_python_printing(cd)
    assert "Land" in py_round.card_types
    assert py_round.produces == frozenset({"W", "U"})
    assert py_round.enters_tapped_unless_any_player_life_at_most == 13
    # Bridge auto-wire synthesizes ONE AA per produce-color.
    assert len(py_round.activated_abilities) == 2, (
        f"Bridge must auto-wire one mana ability per produce-color "
        f"(2 colors → 2 AAs); got {len(py_round.activated_abilities)}"
    )
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    aa_colors = sorted(
        aa.effect.produces[0][0]
        for aa in py_round.activated_abilities
    )
    assert aa_colors == ["U", "W"], (
        f"Bridge-auto-wired AAs must produce 'U' and 'W' coins; got "
        f"colors={aa_colors}"
    )
    for aa in py_round.activated_abilities:
        assert isinstance(aa.effect, AddManaToPool)
        assert aa.effect.produces[0][1] == 1
        assert aa.effect.spend_restriction is None
        assert aa.cost.tap_self is True
        assert aa.is_mana_ability is True

    # Effect-level byte-equality between the bridge dict and the
    # bridged Effect — the canonical add_mana_to_pool round-trip.
    bridged_u = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    bridged_w = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "W", "amount": 1}
    )
    assert isinstance(bridged_u, AddManaToPool)
    assert isinstance(bridged_w, AddManaToPool)
    assert bridged_u in aa_effects
    assert bridged_w in aa_effects


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# Abandoned-Campground-shape registry dict.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_abandoned_campground_painland_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Abandoned-Campground-shape painland registry dict — non-basic
    Land + dual produce + the conditional-tapped threshold."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Abandoned Campground (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {},
            "effects": [],
            "mana_produced": ["U", "W"],
            "enters_tapped_unless_any_player_life_at_most": 13,
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Abandoned Campground printing through the bridge
# round-trip + Python-side resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_abandoned_campground_painland_conditional_uw_parity():
    """**GENUINE real-EoE cross-engine probe — Abandoned Campground
    conditional-painland (W/U) → dual ``AddManaToPool(produces=
    ((<C>, 1),))`` bridge auto-wire. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Abandoned Campground printing** through
    the CardDef bridge round-trip + Python-side resolve.  Mirrors the
    EEEE-idiom of the batch-6 basic-land sibling probes, distinguished
    by the **dual produce-color** (W AND U) and the **conditional-
    tapped rider** (threshold=13).

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding a Duskmourn-painland slug to the per-slug PROBED-tier
    credit.  Distinct from the batch-6 basic-land (Forest/Island/
    Mountain/Plains/Swamp) probes — those pin the mono-color basic-
    land auto-wire on the ``Basic`` supertype path; this probe pins
    the non-basic-painland dual-color auto-wire on the
    ``_printing_is_bridge_nonbasic_painland_conditional`` predicate
    path (Phase-2 substrate).

    **Bridge auto-wire exercised:**
      * ``_printing_to_card_def`` painland arm
        (``enters_tapped_unless_any_player_life_at_most`` threaded).
      * ``_card_def_to_python_printing`` land-mana-ability auto-wire
        synthesizes one ``ActivatedAbility(AddManaToPool(...))`` per
        produce-color (cross_engine.py:14073-14081).
      * ``add_mana_to_pool`` (round-27 bridge arm; 'W' AND 'U'
        per-color dispatch).
    """
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Abandoned Campground")
    if real is None:
        pytest.skip("Abandoned Campground absent from active CardSource")
    assert "Land" in real.card_types
    assert real.produces == frozenset({"W", "U"})
    assert real.enters_tapped_unless_any_player_life_at_most == 13
    assert real.activated_abilities == ()
    assert real.triggered_abilities == ()

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)

    # Distinctness regression guard — the painland produces tuple is
    # dual-color {'W', 'U'}; sibling painland probes pin distinct
    # color pairs.
    assert py_round.produces == frozenset({"W", "U"}), (
        "Abandoned Campground's produces is {'W', 'U'} — distinct "
        "from Bleeding Woods ({'G', 'R'}) / Murky Sewer ({'U', 'B'}) "
        "/ Razortrap Gorge ({'B', 'R'}) / Strangled Cemetery "
        "({'B', 'G'}) sibling painland probes"
    )
    assert py_round.enters_tapped_unless_any_player_life_at_most == 13

    # Both bridge-arm dispatches: 'W' and 'U'.
    bridged_w = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "W", "amount": 1}
    )
    bridged_u = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "U", "amount": 1}
    )
    assert isinstance(bridged_w, AddManaToPool)
    assert isinstance(bridged_u, AddManaToPool)
    assert bridged_w.produces == (("W", 1),)
    assert bridged_u.produces == (("U", 1),)
    assert bridged_w.spend_restriction is None
    assert bridged_u.spend_restriction is None

    # The bridge auto-wires both ABAs onto the round-tripped printing.
    aa_effects = [aa.effect for aa in py_round.activated_abilities]
    assert bridged_w in aa_effects
    assert bridged_u in aa_effects

    # Python-side resolve smoke — both mana abilities mint the right
    # color coins.
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

    # Identify the AAs by their effect's produce-color.
    aa_by_color = {
        aa.effect.produces[0][0]: aa
        for aa in py_round.activated_abilities
    }
    assert set(aa_by_color.keys()) == {"W", "U"}

    aa_by_color["W"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 1
    assert p0_pool[0].color == "W", (
        f"Abandoned Campground's W-mana AA must mint a 'W' coin; got "
        f"color={p0_pool[0].color!r}"
    )
    assert p0_pool[0].spend_restriction is None

    aa_by_color["U"].effect.resolve(py_state, py_source.controller_id)
    p0_pool = py_state.players[0].mana_pool
    assert len(p0_pool) == 2
    coin_colors = sorted(coin.color for coin in p0_pool)
    assert coin_colors == ["U", "W"], (
        f"After resolving both AAs, pool must contain one W coin + "
        f"one U coin; got colors={coin_colors}"
    )
    # Opponent's pool stays untouched.
    assert len(py_state.players[1].mana_pool) == 0
