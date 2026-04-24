"""Integrity tests for the EoE Special Guests (set ``spg``) subset.

Scaffolding tests only — per-card mechanics restoration happens in
follow-up branches and is verified in dedicated test files. Here we
only guarantee the registry is complete, type-correct, and non-colliding.
"""

import json
from pathlib import Path

from mtg_bot.cards import SPECIAL_GUESTS_EOE, all_printings


DATA_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "special_guests_eoe.json"
)


def test_special_guests_registry_has_10_cards():
    assert len(SPECIAL_GUESTS_EOE) == 10


def test_every_scryfall_card_is_in_the_registry():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    scryfall_names = {c["name"] for c in data}
    registry_names = set(SPECIAL_GUESTS_EOE)
    missing = scryfall_names - registry_names
    extra = registry_names - scryfall_names
    assert missing == set(), f"missing from registry: {missing}"
    assert extra == set(), f"extra in registry: {extra}"


def test_card_types_match_oracle():
    # Each card should carry the right top-level card type so the
    # spell/permanent resolution pipeline dispatches correctly.
    expected = {
        "Warping Wail": "is_instant",
        "Deafening Silence": "is_permanent",
        "Robe of Stars": "is_artifact",
        "Nexus of Fate": "is_instant",
        "Paradox Haze": "is_permanent",
        "Darkness": "is_instant",
        "Magus of the Moon": "is_creature",
        "Burgeoning": "is_permanent",
        "Green Sun's Zenith": "is_sorcery",
        "Sliver Overlord": "is_creature",
    }
    for name, type_prop in expected.items():
        p = SPECIAL_GUESTS_EOE[name]
        assert getattr(p, type_prop), f"{name} should satisfy {type_prop}"


def test_sliver_overlord_is_legendary():
    p = SPECIAL_GUESTS_EOE["Sliver Overlord"]
    assert "Legendary" in p.supertypes
    assert "Sliver" in p.subtypes
    assert "Mutant" in p.subtypes
    assert p.power == 7 and p.toughness == 7


def test_magus_of_the_moon_is_2_2_human_wizard():
    p = SPECIAL_GUESTS_EOE["Magus of the Moon"]
    assert p.power == 2 and p.toughness == 2
    assert "Human" in p.subtypes
    assert "Wizard" in p.subtypes


def test_robe_of_stars_is_equipment():
    p = SPECIAL_GUESTS_EOE["Robe of Stars"]
    assert p.is_artifact
    assert "Equipment" in p.subtypes


def test_special_guests_is_included_in_all_printings():
    pool = all_printings()
    for name in SPECIAL_GUESTS_EOE:
        assert name in pool


def test_stand_in_no_op_describes_and_resolves():
    """Exercise the placeholder spell-effect used by stand-in SPG spells.

    As per-card restorations ship, entries are removed from this list.
    Once this list is empty the ``_SpgNoOp`` class can be deleted.
    """
    from types import SimpleNamespace

    still_stand_ins = ("Nexus of Fate", "Darkness", "Green Sun's Zenith")
    for name in still_stand_ins:
        eff = SPECIAL_GUESTS_EOE[name].spell_effect
        assert eff is not None
        assert name in eff.describe()
        log: list[str] = []
        fake_state = SimpleNamespace(log=log)
        eff.resolve(fake_state, controller_id=0, targets=())
        assert any(name in line for line in log)


def test_no_name_collisions_with_other_registries():
    from mtg_bot.cards import (
        BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, PLANET_LANDS,
        SHOCK_LANDS, STELLAR_SIGHTS_LANDS, SYNTHETIC_CREATURES,
        UTILITY_LANDS,
    )

    spg = set(SPECIAL_GUESTS_EOE)
    for other_name, other in (
        ("basics", BASIC_LANDS), ("planets", PLANET_LANDS),
        ("shocks", SHOCK_LANDS), ("utilities", UTILITY_LANDS),
        ("stellar_sights", STELLAR_SIGHTS_LANDS),
        ("eoe_creatures", EOE_CREATURES), ("eoe_spells", EOE_SPELLS),
        ("synthetic", SYNTHETIC_CREATURES),
    ):
        overlap = spg & set(other)
        assert overlap == set(), (
            f"Special Guests collides with {other_name}: {overlap}"
        )
