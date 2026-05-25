"""Bedhead Beastie — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Bedhead Beastie is a ``{4}{R}{R}`` Creature — Beast in the EoE pool
(a Stellar Sights / Special Guests reprint), 5/6 P/T with one safe
keyword: menace.  Vanilla in the bridge-carrier sense — no
ActivatedAbilities, no TriggeredAbilities, no spell_effect.

Templates directly on the batch-7 sibling
``test_daggermaw_megalodon_parity.py`` — bit-identical bridge-carrier
shape contract; the per-slug attribution distinction is the printing
identity (Bedhead Beastie={R}{R} 5/6 menace, Daggermaw={U}{U} 5/7
vigilance, Cackling Slasher={B} 3/3 deathtouch) + the menace-keyword
subset variant.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-6 + the batch-7 sibling probes (parse +
bridge round-trip + Python-side seated-permanent observation, NO
cross-engine ``compare_fields``).
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


def test_bedhead_beastie_parser_claims_card():
    assert "Bedhead Beastie" in _PRINTINGS, (
        "Bedhead Beastie must be parser-claimed by the active "
        "CardSource"
    )


def test_bedhead_beastie_printed_attrs():
    """Pins the basic printing surface: {4}{R}{R} Creature — Beast,
    5/6 P/T, keywords = {menace}, ZERO structured Effects."""
    p = _PRINTINGS["Bedhead Beastie"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert "Beast" in p.subtypes
    assert p.keywords == frozenset({"menace"}), (
        f"Bedhead Beastie must carry exactly 'menace' keyword (a "
        f"member of _SAFE_KEYWORDS for the bridge-simple-creature "
        f"admit); got keywords={p.keywords}"
    )
    assert p.power == 5
    assert p.toughness == 6
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == (("R", 2),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_bedhead_beastie_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Bedhead Beastie passes
    ``_printing_is_bridge_simple_creature`` (Creature + non-None P/T +
    menace ∈ _SAFE_KEYWORDS + no AAs/TAs/spell_effect)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Bedhead Beastie"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_bedhead_beastie_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Bedhead Beastie as
    a Python printing with the bridge-carried subset preserved:
    card_types=("Creature",), power=5, toughness=6,
    keywords=frozenset({"menace"}), mana_cost generic=4 colored=
    (("R", 2),)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Bedhead Beastie"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Bedhead Beastie"
    assert cd.card_type == "Creature"
    assert cd.power == 5
    assert cd.toughness == 6
    assert cd.mana_cost_generic == 4
    assert cd.mana_cost_colored == (("R", 2),)
    assert "menace" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 5
    assert py_round.toughness == 6
    assert py_round.mana_cost.generic == 4
    assert py_round.mana_cost.colored == (("R", 2),)
    assert py_round.keywords == frozenset({"menace"})


@_rust_skip
def test_rust_parser_accepts_bedhead_beastie_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Bedhead
    Beastie-shape registry dict — Creature card_type + 5/6 P/T +
    menace keyword + {4}{R}{R} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Bedhead Beastie (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 4, "R": 2},
            "power": 5,
            "toughness": 6,
            "keywords": ["menace"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_bedhead_beastie_bridge_simple_creature_menace_parity():
    """**GENUINE real-EoE cross-engine probe — Bedhead Beastie
    bridge-simple-creature menace variant. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Bedhead Beastie printing** through the
    CardDef bridge round-trip + seated-permanent observation.  Mirrors
    the EEEE-idiom; same lane discipline as batches 1-6 + the batch-7
    sibling probes.

    **NEW shape coverage:** binds the Bedhead Beastie slug to the
    menace-keyword variant of the bridge-simple-vanilla-creature
    family.  Distinct from the batch-7 Daggermaw Megalodon (vigilance)
    / Cackling Slasher (deathtouch) / Magus of the Moon (empty) /
    Spectral Snatcher (empty) per-keyword variants.
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

    real = _PRINTINGS.get("Bedhead Beastie")
    if real is None:
        pytest.skip("Bedhead Beastie absent from active CardSource")
    assert "Creature" in real.card_types
    assert real.power == 5
    assert real.toughness == 6
    assert real.keywords == frozenset({"menace"})

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.power == 5
    assert py_round.toughness == 6
    assert py_round.keywords == frozenset({"menace"})

    # Distinctness regression guard.
    assert py_round.keywords == frozenset({"menace"}), (
        "Bedhead Beastie's bridge-carried keyword is 'menace' — "
        "distinct from Daggermaw Megalodon (vigilance) / Cackling "
        "Slasher (deathtouch) / Magus of the Moon (empty) / Spectral "
        "Snatcher (empty) siblings"
    )
    assert (py_round.power, py_round.toughness) == (5, 6)

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
    assert effective_power(py_state, py_source) == 5
    assert effective_toughness(py_state, py_source) == 6
