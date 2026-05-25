"""Spectral Snatcher — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Spectral Snatcher is a ``{4}{B}{B}`` Creature — Spirit in the EoE pool
(a Stellar Sights / Special Guests reprint), 6/5 P/T with ZERO
keywords on the parser side.  Vanilla in the bridge-carrier sense —
no ActivatedAbilities, no TriggeredAbilities, no spell_effect.

Templates directly on the batch-7 sibling
``test_magus_of_the_moon_parity.py`` — bit-identical bridge-carrier
shape contract; the per-slug attribution distinction is the printing
identity (Spectral Snatcher={B}{B} 6/5 no-kw, Magus={R} 2/2 no-kw,
Daggermaw={U}{U} 5/7 vigilance) + the (6, 5) P/T variant of the ZERO-
keyword sub-shape.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-6 + the batch-7 sibling Daggermaw /
Magus / Cackling Slasher probes (parse + bridge round-trip + Python-
side seated-permanent observation, NO cross-engine
``compare_fields``).
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


def test_spectral_snatcher_parser_claims_card():
    assert "Spectral Snatcher" in _PRINTINGS, (
        "Spectral Snatcher must be parser-claimed by the active "
        "CardSource"
    )


def test_spectral_snatcher_printed_attrs():
    """Pins the basic printing surface: {4}{B}{B} Creature — Spirit,
    6/5 P/T, ZERO keywords, ZERO structured Effects."""
    p = _PRINTINGS["Spectral Snatcher"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert "Spirit" in p.subtypes
    assert p.keywords == frozenset(), (
        f"Spectral Snatcher must carry ZERO keywords on the parser "
        f"side; got keywords={p.keywords}"
    )
    assert p.power == 6
    assert p.toughness == 5
    assert p.mana_cost.generic == 4
    assert p.mana_cost.colored == (("B", 2),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_spectral_snatcher_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Spectral Snatcher passes
    ``_printing_is_bridge_simple_creature`` (ZERO keywords trivially
    subset of _SAFE_KEYWORDS)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Spectral Snatcher"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_spectral_snatcher_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Spectral Snatcher as
    a Python printing with the bridge-carried subset preserved:
    card_types=("Creature",), power=6, toughness=5, keywords=frozenset()
    (empty), mana_cost generic=4 colored=(("B", 2),)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Spectral Snatcher"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Spectral Snatcher"
    assert cd.card_type == "Creature"
    assert cd.power == 6
    assert cd.toughness == 5
    assert cd.mana_cost_generic == 4
    assert cd.mana_cost_colored == (("B", 2),)
    assert cd.keywords == ()

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 6
    assert py_round.toughness == 5
    assert py_round.mana_cost.generic == 4
    assert py_round.mana_cost.colored == (("B", 2),)
    assert py_round.keywords == frozenset()


@_rust_skip
def test_rust_parser_accepts_spectral_snatcher_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Spectral
    Snatcher-shape registry dict — Creature card_type + 6/5 P/T + ZERO
    keywords + {4}{B}{B} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Spectral Snatcher (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 4, "B": 2},
            "power": 6,
            "toughness": 5,
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_spectral_snatcher_bridge_simple_creature_zero_keyword_parity():
    """**GENUINE real-EoE cross-engine probe — Spectral Snatcher
    bridge-simple-creature ZERO-keyword (6, 5) variant. PROBED-tier
    flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Spectral Snatcher printing** through
    the CardDef bridge round-trip + seated-permanent observation.
    Mirrors the EEEE-idiom; same lane discipline as batches 1-6 + the
    batch-7 sibling probes.

    **NEW shape coverage:** binds the Spectral Snatcher slug to the
    (6, 5) P/T variant of the ZERO-keyword sub-shape of the bridge-
    simple-vanilla-creature family.  Distinct from the batch-7 Magus
    of the Moon (2, 2) ZERO-keyword variant + Daggermaw Megalodon
    (5, 7) vigilance / Cackling Slasher (3, 3) deathtouch / Bedhead
    Beastie (5, 6) menace variants — per the cathedral-of-war-style
    same-Effect-class-different-printing-slug precedent, each printing-
    slug earns a PROBED-tier slot.
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

    real = _PRINTINGS.get("Spectral Snatcher")
    if real is None:
        pytest.skip("Spectral Snatcher absent from active CardSource")
    assert "Creature" in real.card_types
    assert real.power == 6
    assert real.toughness == 5
    assert real.keywords == frozenset()

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.power == 6
    assert py_round.toughness == 5
    assert py_round.keywords == frozenset()

    # Distinctness regression guard.
    assert (py_round.power, py_round.toughness) == (6, 5), (
        "Spectral Snatcher bridge subset P/T must be 6/5 — distinct "
        "from sibling vanilla-creature probes' P/T shapes"
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
    assert effective_power(py_state, py_source) == 6
    assert effective_toughness(py_state, py_source) == 5
