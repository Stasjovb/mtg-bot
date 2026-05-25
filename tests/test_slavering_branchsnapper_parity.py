"""Slavering Branchsnapper — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Slavering Branchsnapper is a ``{4}{G}{G}`` Creature — Lizard in the
EoE pool, 7/6 P/T with one safe keyword: trample.  Vanilla in the
bridge-carrier sense — no ActivatedAbilities, no TriggeredAbilities,
no spell_effect.

Templates directly on the batch-7 sibling
``test_bedhead_beastie_parity.py`` — bit-identical bridge-carrier shape
contract; the per-slug attribution distinction is the printing
identity (Slavering Branchsnapper={4}{G}{G} 7/6 trample) + the
trample-keyword subset variant of the bridge-simple-vanilla-creature
family.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-7 (parse + bridge round-trip + Python-
side seated-permanent observation, NO cross-engine ``compare_fields``).

**NEW shape coverage:** binds the Slavering Branchsnapper slug to the
trample-keyword variant of the bridge-simple-vanilla-creature family —
the FIRST trample-keyword binding under the family (the batch-7
Daggermaw/Magus/Cackling/Spectral/Bedhead siblings exercised
vigilance/empty/deathtouch/empty/menace respectively).

Slavering Branchsnapper is a Stellar Sights / Special-Guests reprint
in the EoE pool (0 17lands decks per the live snapshot).
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


def test_slavering_branchsnapper_parser_claims_card():
    assert "Slavering Branchsnapper" in _PRINTINGS, (
        "Slavering Branchsnapper must be parser-claimed by the active "
        "CardSource"
    )


def test_slavering_branchsnapper_printed_attrs():
    """Pins the basic printing surface: {4}{G}{G} Creature — Lizard,
    7/6 P/T, keywords = {trample}, ZERO structured Effects."""
    p = _PRINTINGS["Slavering Branchsnapper"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert p.keywords == frozenset({"trample"}), (
        f"Slavering Branchsnapper must carry exactly 'trample' keyword "
        f"(a member of _SAFE_KEYWORDS for the bridge-simple-creature "
        f"admit); got keywords={p.keywords}"
    )
    assert p.power == 7
    assert p.toughness == 6
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == (("G", 2),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_slavering_branchsnapper_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Slavering Branchsnapper passes
    ``_printing_is_bridge_simple_creature``."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Slavering Branchsnapper"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_slavering_branchsnapper_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Slavering
    Branchsnapper as a Python printing with the bridge-carried subset
    preserved: card_types=("Creature",), power=7, toughness=6,
    keywords=frozenset({"trample"}), mana_cost generic=4 colored=
    (("G", 2),)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Slavering Branchsnapper"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Slavering Branchsnapper"
    assert cd.card_type == "Creature"
    assert cd.power == 7
    assert cd.toughness == 6
    assert cd.mana_cost_generic == 4
    assert cd.mana_cost_colored == (("G", 2),)
    assert "trample" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 7
    assert py_round.toughness == 6
    assert py_round.mana_cost.generic == 4
    assert py_round.mana_cost.colored == (("G", 2),)
    assert py_round.keywords == frozenset({"trample"})


@_rust_skip
def test_rust_parser_accepts_slavering_branchsnapper_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Slavering
    Branchsnapper-shape registry dict — Creature card_type + 7/6 P/T +
    trample keyword + {4}{G}{G} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Slavering Branchsnapper (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 4, "G": 2},
            "power": 7,
            "toughness": 6,
            "keywords": ["trample"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_slavering_branchsnapper_bridge_simple_creature_trample_parity():
    """**GENUINE real-EoE cross-engine probe — Slavering Branchsnapper
    bridge-simple-creature trample variant. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Slavering Branchsnapper printing**
    through the CardDef bridge round-trip + seated-permanent
    observation.  Mirrors the EEEE-idiom; same lane discipline as
    batches 1-7.

    **NEW shape coverage:** binds the Slavering Branchsnapper slug to
    the trample-keyword variant of the bridge-simple-vanilla-creature
    family — the FIRST trample-keyword binding under the family.
    Distinct from the batch-7 Daggermaw (vigilance, 5/7) / Cackling
    Slasher (deathtouch, 3/3) / Magus of the Moon (empty, 2/2) /
    Spectral Snatcher (empty, 6/5) / Bedhead Beastie (menace, 5/6)
    per-keyword variants AND from the batch-8 Piranha Fly / Shepherding
    Spirits (both flying) siblings.
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

    real = _PRINTINGS.get("Slavering Branchsnapper")
    if real is None:
        pytest.skip(
            "Slavering Branchsnapper absent from active CardSource"
        )
    assert "Creature" in real.card_types
    assert real.power == 7
    assert real.toughness == 6
    assert real.keywords == frozenset({"trample"})
    assert real.activated_abilities == ()
    assert real.triggered_abilities == ()
    assert real.spell_effect is None

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.power == 7
    assert py_round.toughness == 6
    assert py_round.keywords == frozenset({"trample"})

    # Distinctness regression guard.
    assert py_round.keywords == frozenset({"trample"}), (
        "Slavering Branchsnapper's bridge-carried keyword is 'trample' "
        "— distinct from sibling vigilance/deathtouch/menace/empty/"
        "flying keyword bindings under the family"
    )
    assert (py_round.power, py_round.toughness) == (7, 6)

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
    assert effective_power(py_state, py_source) == 7
    assert effective_toughness(py_state, py_source) == 6
