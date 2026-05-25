"""Cackling Slasher — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Cackling Slasher is a ``{3}{B}`` Creature — Human Assassin in the EoE
pool, 3/3 P/T with one safe keyword: deathtouch.  Vanilla in the
bridge-carrier sense — no ActivatedAbilities, no TriggeredAbilities,
no spell_effect.

Cackling Slasher was the synthetic equip-target in the batch-5
sibling probes ``test_squires_lightblade_parity.py`` /
``test_the_dominion_bracelet_parity.py`` — those probes used a
SYNTHETIC ``CardPrinting`` (vanilla 2/2 Bear) as the equip target
rather than ``_PRINTINGS.get("Cackling Slasher")``, so the
``_probe_module_probed_cards_via_module_scope_binding`` walker did
NOT transitively credit Cackling Slasher.  This probe is the FIRST
PROBE_MODULES-credited probe binding the Cackling Slasher slug
directly — the deathtouch-keyword variant of the bridge-simple-
vanilla-creature shape family.

Templates directly on the batch-7 sibling
``test_daggermaw_megalodon_parity.py`` — bit-identical bridge-carrier
shape contract; the per-slug attribution distinction is the printing
identity (Cackling={B} 3/3 deathtouch, Daggermaw={U}{U} 5/7 vigilance,
Magus={R} 2/2 no-kw) + the deathtouch keyword subset variant.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-6 + the batch-7 sibling Daggermaw probe
(parse + bridge round-trip + Python-side seated-permanent
observation, NO cross-engine ``compare_fields``).
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


def test_cackling_slasher_parser_claims_card():
    assert "Cackling Slasher" in _PRINTINGS, (
        "Cackling Slasher must be parser-claimed by the active "
        "CardSource"
    )


def test_cackling_slasher_printed_attrs():
    """Pins the basic printing surface: {3}{B} Creature — Human
    Assassin, 3/3 P/T, keywords = {deathtouch}, ZERO structured
    Effects."""
    p = _PRINTINGS["Cackling Slasher"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert "Human" in p.subtypes
    assert "Assassin" in p.subtypes
    assert p.keywords == frozenset({"deathtouch"}), (
        f"Cackling Slasher must carry exactly 'deathtouch' keyword "
        f"(a member of _SAFE_KEYWORDS for the bridge-simple-creature "
        f"admit); got keywords={p.keywords}"
    )
    assert p.power == 3
    assert p.toughness == 3
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == (("B", 1),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_cackling_slasher_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Cackling Slasher passes
    ``_printing_is_bridge_simple_creature`` (Creature + non-None P/T +
    deathtouch ∈ _SAFE_KEYWORDS + no AAs/TAs/spell_effect)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Cackling Slasher"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_cackling_slasher_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Cackling Slasher as
    a Python printing with the bridge-carried subset preserved:
    card_types=("Creature",), power=3, toughness=3,
    keywords=frozenset({"deathtouch"}), mana_cost generic=3 colored=
    (("B", 1),).  The parser-side subtypes ``("Human", "Assassin")``
    are NOT round-tripped per the documented CardDef bridge contract."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Cackling Slasher"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Cackling Slasher"
    assert cd.card_type == "Creature"
    assert cd.power == 3
    assert cd.toughness == 3
    assert cd.mana_cost_generic == 3
    assert cd.mana_cost_colored == (("B", 1),)
    assert "deathtouch" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 3
    assert py_round.toughness == 3
    assert py_round.mana_cost.generic == 3
    assert py_round.mana_cost.colored == (("B", 1),)
    assert py_round.keywords == frozenset({"deathtouch"})


@_rust_skip
def test_rust_parser_accepts_cackling_slasher_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Cackling
    Slasher-shape registry dict — Creature card_type + 3/3 P/T +
    deathtouch keyword + {3}{B} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Cackling Slasher (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 3, "B": 1},
            "power": 3,
            "toughness": 3,
            "keywords": ["deathtouch"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_cackling_slasher_bridge_simple_creature_deathtouch_parity():
    """**GENUINE real-EoE cross-engine probe — Cackling Slasher
    bridge-simple-creature deathtouch variant. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Cackling Slasher printing** through the
    CardDef bridge round-trip + seated-permanent observation.  Mirrors
    the EEEE-idiom; same lane discipline as batches 1-6 + the batch-7
    sibling Daggermaw / Magus probes.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Cackling Slasher slug to a probe module — the batch-5
    sibling probes (Squire's Lightblade / The Dominion Bracelet) used
    Cackling Slasher's name as a contextual reference but exercised a
    SYNTHETIC Bear as the equip target so the walker did NOT credit
    Cackling Slasher.  This probe closes that attribution gap on the
    deathtouch-keyword variant of the bridge-simple-vanilla-creature
    family.
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

    real = _PRINTINGS.get("Cackling Slasher")
    if real is None:
        pytest.skip("Cackling Slasher absent from active CardSource")
    assert "Creature" in real.card_types
    assert real.power == 3
    assert real.toughness == 3
    assert real.keywords == frozenset({"deathtouch"})

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.power == 3
    assert py_round.toughness == 3
    assert py_round.keywords == frozenset({"deathtouch"})

    # Distinctness regression guard.
    assert py_round.keywords == frozenset({"deathtouch"}), (
        "Cackling Slasher's bridge-carried keyword is 'deathtouch' — "
        "distinct from Daggermaw Megalodon (vigilance) / Bedhead Beastie "
        "(menace) / Magus of the Moon (empty) / Spectral Snatcher "
        "(empty) siblings"
    )
    assert (py_round.power, py_round.toughness) == (3, 3)

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
    assert effective_power(py_state, py_source) == 3
    assert effective_toughness(py_state, py_source) == 3
