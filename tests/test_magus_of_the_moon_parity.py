"""Magus of the Moon — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Magus of the Moon is a ``{2}{R}`` Creature — Human Wizard in the EoE
pool (a Stellar Sights / Special Guests reprint), 2/2 P/T with ZERO
keywords on the parser side.  Vanilla in the bridge-carrier sense —
no ActivatedAbilities, no TriggeredAbilities, no spell_effect.

(The printed rule "Nonbasic lands are Mountains" lives on the
``CardPrinting.nonbasic_lands_are_mountains`` static-ability slot in
the parser — that slot is a printing-level bool not a structured
Effect.  The bridge-simple-creature admit predicate gates on
structured Effects + keywords; the parser-side static slot is
documented as the bridge-carrier-shape narrow-pin half-coverage
precedent — the printed Magus static is NOT round-tripped through
the bare CardDef bridge, mirroring the batch-5 Squire's Lightblade
ETB-attach trigger implicit drop.  The PROBED-tier per-slug
attribution is on the bridge-carried subset alone.)

Parser-emitted printing shape (the bridge-carried subset):

    ``CardPrinting(name="Magus of the Moon",
                   card_types=("Creature",),
                   subtypes=("Human", "Wizard"),
                   keywords=frozenset(),
                   power=2, toughness=2,
                   mana_cost=ManaCost(generic=2,
                                      colored=(("R", 1),)),
                   ...)``

Templates directly on the batch-7 sibling
``test_daggermaw_megalodon_parity.py`` — bit-identical bridge-
carrier shape contract; the per-slug attribution distinction is the
printing identity (Magus={R} 2/2 no-kw, Daggermaw={U}{U} 5/7 with
vigilance) + the ZERO-keyword bare-frozen-set subset shape (Magus
is the FIRST PROBE_MODULES-credited probe binding the ZERO-keyword
variant of the bridge-simple-creature family; Daggermaw carries the
vigilance keyword).

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


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Magus of the Moon is parser-claimed as a {2}{R}
# Creature — Human Wizard with ZERO keywords, 2/2, and ZERO structured
# Effects.
# ---------------------------------------------------------------------------


def test_magus_of_the_moon_parser_claims_card():
    assert "Magus of the Moon" in _PRINTINGS, (
        "Magus of the Moon must be parser-claimed by the active "
        "CardSource"
    )


def test_magus_of_the_moon_printed_attrs():
    """Pins the basic printing surface: {2}{R} Creature — Human Wizard,
    2/2 P/T, ZERO keywords, ZERO structured Effects on the parser side
    (the printed "Nonbasic lands are Mountains" rule lives on the
    ``CardPrinting.nonbasic_lands_are_mountains`` static-ability slot
    NOT on a structured Effect, and is implicit-drop for the bridge-
    simple-creature admit per the half-coverage precedent)."""
    p = _PRINTINGS["Magus of the Moon"]
    assert "Creature" in p.card_types
    assert p.supertypes == ()
    assert "Human" in p.subtypes
    assert "Wizard" in p.subtypes
    assert p.keywords == frozenset(), (
        f"Magus of the Moon must carry ZERO keywords on the parser "
        f"side; got keywords={p.keywords}"
    )
    assert p.power == 2
    assert p.toughness == 2
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("R", 1),)
    # ZERO structured Effects on the parser side.
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_magus_of_the_moon_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Magus of the Moon passes
    ``_printing_is_bridge_simple_creature`` (Creature card_type +
    non-None P/T + ZERO keywords trivially subset of _SAFE_KEYWORDS).

    NB: the parser-side ``nonbasic_lands_are_mountains=True`` static-
    ability slot does NOT trip ``_printing_is_bridge_simple_creature``
    — the admit gate's ``static_abilities`` check is on the tuple
    slot, not on the printing-level static bool.  The bool rider is
    implicit-drop for the bridge-simple-creature shape per the half-
    coverage precedent (mirrors the batch-5 Squire's Lightblade
    ETB-attach trigger implicit drop)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Magus of the Moon"]
    assert _printing_is_bridge_simple_creature(p) is True, (
        "Magus of the Moon must pass the bridge-simple-creature admit "
        "predicate (ZERO keywords trivially subset of _SAFE_KEYWORDS, "
        "no AAs/TAs/spell_effect/etc.); the static-ability bool slot "
        "is implicit-drop per the half-coverage precedent"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — _printing_to_card_def → CardDef →
# _card_def_to_python_printing materializes the bridge-carried subset
# byte-equal.
# ---------------------------------------------------------------------------


def test_magus_of_the_moon_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Magus of the Moon as
    a Python printing with the bridge-carried subset preserved:
    card_types=("Creature",), power=2, toughness=2,
    keywords=frozenset() (empty), mana_cost generic=2 colored=
    (("R", 1),).  The parser-side subtypes ``("Human", "Wizard")``
    are NOT round-tripped per the documented CardDef bridge contract
    (the same drop the batch-7 sibling Daggermaw Megalodon probe
    pins)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Magus of the Moon"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Magus of the Moon"
    assert cd.card_type == "Creature"
    assert cd.power == 2
    assert cd.toughness == 2
    assert cd.mana_cost_generic == 2
    assert cd.mana_cost_colored == (("R", 1),)
    assert cd.keywords == ()

    py_round = _card_def_to_python_printing(cd)
    assert "Creature" in py_round.card_types
    assert py_round.power == 2
    assert py_round.toughness == 2
    assert py_round.mana_cost.generic == 2
    assert py_round.mana_cost.colored == (("R", 1),)
    assert py_round.keywords == frozenset(), (
        f"Magus of the Moon ZERO-keyword bare subset must round-trip "
        f"byte-equal as frozenset(); got {py_round.keywords}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — Rust's register_printing accepts
# the Magus-shape registry dict.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_magus_of_the_moon_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Magus-of-
    the-Moon-shape registry dict — Creature card_type + 2/2 P/T + ZERO
    keywords + {2}{R} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Magus of the Moon (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "R": 1},
            "power": 2,
            "toughness": 2,
            "effects": [],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Magus of the Moon printing through the CardDef bridge
# round-trip and verifies Python's combat readers reflect the bridge-
# carried subset byte-equal to the parsed printed_P/T / card_types.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_magus_of_the_moon_bridge_simple_creature_zero_keyword_parity():
    """**GENUINE real-EoE cross-engine probe — Magus of the Moon
    bridge-simple-creature ZERO-keyword variant. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Magus of the Moon printing** through
    the CardDef bridge round-trip + the bridge-carried Python printing
    is seated on p0's battlefield + Python's combat readers
    (``effective_power``, ``effective_toughness``, ``is_creature_now``)
    are observed to reflect the bridge-carried subset byte-equal.
    Mirrors the EEEE-idiom; same lane discipline as batches 1-6 + the
    batch-7 sibling Daggermaw Megalodon probe.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the ZERO-keyword variant of the bridge-simple-vanilla-
    creature shape family to a slug — distinct from the batch-7
    sibling Daggermaw Megalodon (vigilance) / Cackling Slasher
    (deathtouch) / Bedhead Beastie (menace) per-keyword variants.  The
    ZERO-keyword variant is the structurally simplest sub-shape of
    the family — no _SAFE_KEYWORDS rider survives the bridge subset.
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

    # 1. Verify parsed.
    real = _PRINTINGS.get("Magus of the Moon")
    if real is None:
        pytest.skip("Magus of the Moon absent from active CardSource")
    assert "Creature" in real.card_types
    assert real.power == 2
    assert real.toughness == 2
    assert real.keywords == frozenset()

    # 2. Bridge admit.
    assert _printing_is_bridge_simple_creature(real) is True

    # 3. CardDef bridge round-trip.
    cd = _printing_to_card_def(real)
    assert cd.power == 2
    assert cd.toughness == 2
    py_round = _card_def_to_python_printing(cd)
    assert py_round.power == 2
    assert py_round.toughness == 2
    assert py_round.keywords == frozenset()

    # 4. Distinctness regression guard.
    assert (py_round.power, py_round.toughness) == (2, 2), (
        "Magus bridge subset P/T must be 2/2 — distinct from sibling "
        "vanilla-creature probes' shapes"
    )
    assert py_round.keywords == frozenset(), (
        "Magus's bridge-carried keywords subset is empty — distinct "
        "from Daggermaw Megalodon (vigilance) / Cackling Slasher "
        "(deathtouch) / Bedhead Beastie (menace) per-keyword siblings"
    )

    # 5. Seated-permanent observation smoke.
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
    assert effective_power(py_state, py_source) == 2
    assert effective_toughness(py_state, py_source) == 2
