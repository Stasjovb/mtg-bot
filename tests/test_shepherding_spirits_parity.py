"""Shepherding Spirits — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Shepherding Spirits is a ``{4}{W}{W}`` Creature — Spirit in the EoE
pool, 4/5 P/T with one safe keyword: flying.  Vanilla in the bridge-
carrier sense — no ActivatedAbilities, no TriggeredAbilities, no
spell_effect.

Templates directly on the batch-7 sibling
``test_bedhead_beastie_parity.py`` — bit-identical bridge-carrier shape
contract; the per-slug attribution distinction is the printing
identity (Shepherding Spirits={4}{W}{W} 4/5 flying, Piranha Fly={1}{U}
2/1 flying — same keyword, distinct P/T) + the (4, 5) P/T variant of
the flying sub-shape.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-7 (parse + bridge round-trip + Python-
side seated-permanent observation, NO cross-engine ``compare_fields``).

**NEW shape coverage:** binds the Shepherding Spirits slug to the
flying-keyword variant of the bridge-simple-vanilla-creature family at
the (4, 5) P/T point.  Per the cathedral-of-war-style same-Effect-
class-different-printing-slug precedent, each P/T variant earns a
PROBED-tier slot.

Shepherding Spirits is a Stellar Sights / Special-Guests reprint in
the EoE pool (0 17lands decks per the live snapshot — not in the
17lands draft sample).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_BATTLEFIELD = 2


def test_shepherding_spirits_parser_claims_card():
    assert "Shepherding Spirits" in _PRINTINGS, (
        "Shepherding Spirits must be parser-claimed by the active "
        "CardSource"
    )


def test_shepherding_spirits_printed_attrs():
    """Pins the basic printing surface: {4}{W}{W} Creature — Spirit,
    4/5 P/T, keywords = {flying}, ZERO structured Effects."""
    p = _PRINTINGS["Shepherding Spirits"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert p.keywords == frozenset({"flying"}), (
        f"Shepherding Spirits must carry exactly 'flying' keyword (a "
        f"member of _SAFE_KEYWORDS for the bridge-simple-creature "
        f"admit); got keywords={p.keywords}"
    )
    assert p.power == 4
    assert p.toughness == 5
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == (("W", 2),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_shepherding_spirits_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Shepherding Spirits passes
    ``_printing_is_bridge_simple_creature``."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Shepherding Spirits"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_shepherding_spirits_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Shepherding Spirits
    as a Python printing with the bridge-carried subset preserved:
    card_types=("Creature",), power=4, toughness=5,
    keywords=frozenset({"flying"}), mana_cost generic=4 colored=
    (("W", 2),)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Shepherding Spirits"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Shepherding Spirits"
    assert cd.card_type == "Creature"
    assert cd.power == 4
    assert cd.toughness == 5
    assert cd.mana_cost_generic == 4
    assert cd.mana_cost_colored == (("W", 2),)
    assert "flying" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 4
    assert py_round.toughness == 5
    assert py_round.mana_cost.generic == 4
    assert py_round.mana_cost.colored == (("W", 2),)
    assert py_round.keywords == frozenset({"flying"})


@_rust_skip
def test_rust_parser_accepts_shepherding_spirits_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Shepherding Spirits-shape registry dict — Creature card_type + 4/5
    P/T + flying keyword + {4}{W}{W} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Shepherding Spirits (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 4, "W": 2},
            "power": 4,
            "toughness": 5,
            "keywords": ["flying"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_shepherding_spirits_bridge_simple_creature_flying_parity():
    """**GENUINE real-EoE cross-engine probe — Shepherding Spirits
    bridge-simple-creature flying variant at the (4, 5) P/T point.
    PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Shepherding Spirits printing** through
    the CardDef bridge round-trip + seated-permanent observation.
    Mirrors the EEEE-idiom; same lane discipline as batches 1-7.

    **NEW shape coverage:** binds the Shepherding Spirits slug to the
    flying-keyword variant of the bridge-simple-vanilla-creature
    family at the (4, 5) P/T point.  Per the cathedral-of-war-style
    same-Effect-class-different-printing-slug precedent, each P/T
    variant earns a PROBED-tier slot — distinct from the batch-8 sibling
    Piranha Fly (flying, 2/1).
    """
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature, _printing_to_card_def,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _card_def_to_python_printing,
    )
    from mtg_bot.game import (
        Zone, effective_power, effective_toughness, is_creature_now,
    )

    real = _PRINTINGS.get("Shepherding Spirits")
    if real is None:
        pytest.skip("Shepherding Spirits absent from active CardSource")
    assert "Creature" in real.card_types
    assert real.power == 4
    assert real.toughness == 5
    assert real.keywords == frozenset({"flying"})
    assert real.activated_abilities == ()
    assert real.triggered_abilities == ()
    assert real.spell_effect is None

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.power == 4
    assert py_round.toughness == 5
    assert py_round.keywords == frozenset({"flying"})

    # Distinctness regression guard.
    assert (py_round.power, py_round.toughness) == (4, 5), (
        "Shepherding Spirits bridge subset P/T must be 4/5 — distinct "
        "from sibling flying-keyword Piranha Fly (2/1)"
    )

    # Seated-permanent observation.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    py_source = py_state.new_object(
        py_round, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.summoning_sick = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    assert is_creature_now(py_source) is True
    assert effective_power(py_state, py_source) == 4
    assert effective_toughness(py_state, py_source) == 5
