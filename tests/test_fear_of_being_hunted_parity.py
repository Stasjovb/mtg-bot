"""Fear of Being Hunted — per-card real-EoE cross-engine byte-equal
probe (covered_by_construction → PROBED tier flip).

Fear of Being Hunted is a ``{1}{R}{R}`` Enchantment Creature —
Nightmare in the EoE pool, 4/2 P/T with one safe keyword: haste.
Vanilla in the bridge-carrier sense — no ActivatedAbilities, no
TriggeredAbilities, no spell_effect.

Templates directly on the batch-7 sibling
``test_bedhead_beastie_parity.py`` — bit-identical bridge-carrier shape
contract; the per-slug attribution distinction is the printing
identity (Fear of Being Hunted={1}{R}{R} 4/2 haste,
Enchantment+Creature multi-type) + the haste-keyword subset variant +
the **Enchantment+Creature multi-type carrier** sub-shape.

**EEEE-idiom for the bridge-simple vanilla-creature carrier.**  Same
lane discipline as batches 1-7 (parse + bridge round-trip + Python-
side seated-permanent observation, NO cross-engine ``compare_fields``).

**NEW shape coverage:** binds the Fear of Being Hunted slug to the
haste-keyword variant of the bridge-simple-vanilla-creature family —
the FIRST haste-keyword binding AND the FIRST Enchantment+Creature
multi-type-carrier binding under the family.  The parser-side
``card_types=("Enchantment", "Creature")`` is documented-drop on
round-trip per the bare ``_printing_is_bridge_simple_creature`` arm's
documented signature — the CardDef builds ``card_type="Creature" +
extra_card_types=()``, so the Enchantment type is symmetrically dropped
on BOTH bridge sides.  Same precedent as the batch-7 documented
subtype drop AND the batch-8 Patched Plaything Artifact-type drop.

Fear of Being Hunted is a Stellar Sights / Special-Guests reprint in
the EoE pool (0 17lands decks per the live snapshot).
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


def test_fear_of_being_hunted_parser_claims_card():
    assert "Fear of Being Hunted" in _PRINTINGS, (
        "Fear of Being Hunted must be parser-claimed by the active "
        "CardSource"
    )


def test_fear_of_being_hunted_printed_attrs():
    """Pins the basic printing surface: {1}{R}{R} Enchantment Creature
    — Nightmare, 4/2 P/T, keywords = {haste}, ZERO structured
    Effects."""
    p = _PRINTINGS["Fear of Being Hunted"]
    assert "Creature" in p.card_types
    assert "Enchantment" in p.card_types, (
        f"Fear of Being Hunted must carry 'Enchantment' card_type "
        f"alongside 'Creature' (the multi-type sub-shape pin); got "
        f"card_types={p.card_types}"
    )
    assert p.supertypes == ()
    assert p.keywords == frozenset({"haste"}), (
        f"Fear of Being Hunted must carry exactly 'haste' keyword (a "
        f"member of _SAFE_KEYWORDS for the bridge-simple-creature "
        f"admit); got keywords={p.keywords}"
    )
    assert p.power == 4
    assert p.toughness == 2
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("R", 2),)
    assert p.activated_abilities == ()
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_fear_of_being_hunted_loader_admits_as_simple_creature():
    """Pins the bridge-admit gate: Fear of Being Hunted passes
    ``_printing_is_bridge_simple_creature`` — the bare simple-creature
    arm accepts an Enchantment-Creature card-type tuple (gate is
    ``"Creature" in card_types``; the multi-type carrier flows through,
    with the Enchantment type symmetrically-dropped on bridge round-
    trip)."""
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_creature,
    )

    p = _PRINTINGS["Fear of Being Hunted"]
    assert _printing_is_bridge_simple_creature(p) is True


def test_fear_of_being_hunted_card_def_bridge_round_trip():
    """The CardDef bridge round-trip materializes Fear of Being Hunted
    as a Python printing with the bridge-carried subset preserved:
    card_types=("Creature",) — Enchantment dropped — power=4, toughness=2,
    keywords=frozenset({"haste"}), mana_cost generic=1 colored=
    (("R", 2),).  The parser-side ``card_types=("Enchantment",
    "Creature")`` is symmetrically-dropped on round-trip via the bare
    simple-creature CardDef arm (same precedent as the batch-7 subtype
    drop AND the batch-8 Patched Plaything Artifact-type drop)."""
    from mtg_bot.parity.trajectory import _printing_to_card_def
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    real = _PRINTINGS["Fear of Being Hunted"]
    cd = _printing_to_card_def(real)
    assert cd.name == "Fear of Being Hunted"
    assert cd.card_type == "Creature"
    # Documented bridge-contract drop: the Enchantment type does NOT
    # survive the bare simple-creature CardDef arm.
    assert cd.extra_card_types == (), (
        f"Bare simple-creature CardDef arm must yield empty "
        f"extra_card_types; got {cd.extra_card_types}"
    )
    assert cd.power == 4
    assert cd.toughness == 2
    assert cd.mana_cost_generic == 1
    assert cd.mana_cost_colored == (("R", 2),)
    assert "haste" in cd.keywords

    py_round = _card_def_to_python_printing(cd)
    assert py_round.card_types == ("Creature",), (
        f"CardDef bridge contract: Fear of Being Hunted's parser-side "
        f"('Enchantment', 'Creature') is documented-drop on round-trip "
        f"— only ('Creature',) survives the bare simple-creature arm; "
        f"got {py_round.card_types}"
    )
    assert py_round.power == 4
    assert py_round.toughness == 2
    assert py_round.mana_cost.generic == 1
    assert py_round.mana_cost.colored == (("R", 2),)
    assert py_round.keywords == frozenset({"haste"})


@_rust_skip
def test_rust_parser_accepts_fear_of_being_hunted_simple_creature_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the Fear of
    Being Hunted-shape registry dict — Creature card_type + 4/2 P/T +
    haste keyword + {1}{R}{R} mana cost."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Fear of Being Hunted (synthetic carrier)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "R": 2},
            "power": 4,
            "toughness": 2,
            "keywords": ["haste"],
            "effects": [],
        }
    )
    assert isinstance(pid, int)


def test_cross_engine_real_eoe_fear_of_being_hunted_bridge_simple_creature_haste_parity():
    """**GENUINE real-EoE cross-engine probe — Fear of Being Hunted
    bridge-simple-creature haste variant (Enchantment+Creature
    multi-type carrier). PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Fear of Being Hunted printing** through
    the CardDef bridge round-trip + seated-permanent observation.
    Mirrors the EEEE-idiom; same lane discipline as batches 1-7.

    **NEW shape coverage:** binds the Fear of Being Hunted slug to the
    haste-keyword variant of the bridge-simple-vanilla-creature family
    AND the FIRST Enchantment+Creature multi-type-carrier sub-shape
    under the family.  Distinct from the batch-7
    Daggermaw/Magus/Cackling/Spectral/Bedhead variants AND from the
    batch-8 Piranha/Shepherding/Slavering/Patched siblings.  The
    Enchantment-type drop on round-trip is documented (same precedent
    as the batch-7 subtype drop AND the batch-8 Patched Plaything
    Artifact-type drop).
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

    real = _PRINTINGS.get("Fear of Being Hunted")
    if real is None:
        pytest.skip("Fear of Being Hunted absent from active CardSource")
    assert "Creature" in real.card_types
    assert "Enchantment" in real.card_types
    assert real.power == 4
    assert real.toughness == 2
    assert real.keywords == frozenset({"haste"})
    assert real.activated_abilities == ()
    assert real.triggered_abilities == ()
    assert real.spell_effect is None

    assert _printing_is_bridge_simple_creature(real) is True

    cd = _printing_to_card_def(real)
    py_round = _card_def_to_python_printing(cd)
    assert py_round.card_types == ("Creature",)  # Enchantment dropped.
    assert py_round.power == 4
    assert py_round.toughness == 2
    assert py_round.keywords == frozenset({"haste"})

    # Distinctness regression guard.
    assert py_round.keywords == frozenset({"haste"}), (
        "Fear of Being Hunted's bridge-carried keyword is 'haste' — "
        "distinct from sibling vigilance/deathtouch/menace/empty/"
        "flying/trample/double-strike keyword bindings under the family"
    )
    assert (py_round.power, py_round.toughness) == (4, 2)

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
    assert effective_toughness(py_state, py_source) == 2
