"""Integrity tests for the Stellar Sights (EoE bonus sheet) registry.

These are scaffolding tests — card mechanics are restored in
per-mechanic-family branches and verified in their own test files.
Here we only ensure the registry is complete, unique, and every
card is at least minimally wellformed (land type, stable name)."""

import json
from pathlib import Path

from mtg_bot.cards import STELLAR_SIGHTS_LANDS, all_printings


DATA_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "stellar_sights.json"
)


def test_stellar_sights_registry_has_45_cards():
    assert len(STELLAR_SIGHTS_LANDS) == 45


def test_every_scryfall_card_is_in_the_registry():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    scryfall_names = {c["name"] for c in data}
    registry_names = set(STELLAR_SIGHTS_LANDS)
    missing = scryfall_names - registry_names
    assert missing == set(), f"missing from registry: {missing}"


def test_every_entry_is_a_land():
    for name, printing in STELLAR_SIGHTS_LANDS.items():
        assert printing.is_land, f"{name} should be a land"


def test_legendary_lands_flagged_correctly():
    # Gemstone Caverns and Inventors' Fair are Legendary Lands per oracle.
    for name in ("Gemstone Caverns", "Inventors' Fair"):
        p = STELLAR_SIGHTS_LANDS[name]
        assert "Legendary" in p.supertypes, (
            f"{name} should have Legendary supertype"
        )


def test_power_depot_is_artifact_land():
    p = STELLAR_SIGHTS_LANDS["Power Depot"]
    assert p.is_land
    assert p.is_artifact


def test_stellar_sights_is_included_in_all_printings():
    pool = all_printings()
    for name in STELLAR_SIGHTS_LANDS:
        assert name in pool


def test_no_name_collisions_with_other_land_registries():
    from mtg_bot.cards import BASIC_LANDS, PLANET_LANDS, SHOCK_LANDS, UTILITY_LANDS

    ss = set(STELLAR_SIGHTS_LANDS)
    for other_name, other in (
        ("basics", BASIC_LANDS), ("planets", PLANET_LANDS),
        ("shocks", SHOCK_LANDS), ("utilities", UTILITY_LANDS),
    ):
        overlap = ss & set(other)
        assert overlap == set(), (
            f"Stellar Sights collides with {other_name}: {overlap}"
        )
