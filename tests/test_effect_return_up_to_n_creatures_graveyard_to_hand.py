"""**Multi-target graveyard→HAND substrate (Archenemy's Charm Mode 1,
2026-05-22).**

Substrate tests for the new Rust
``Effect::ReturnUpToNCreaturesFromYourGraveyardToHand { min_n: i32,
max_n: i32 }`` variant + matching Python serializer leaf + cross-engine
bridge arm.

Pool scan at this lane's HEAD (2026-05-22): **zero** EoE cards use the
bare ``ReturnUpToNCreaturesFromYourGraveyardToHand`` as their
top-level spell_effect. Archenemy's Charm uses it through a
``ModalChooseOne`` mode slot, which has its own admit path. So this
lane ships **substrate-only**: variant + parse/to_pydict + resolve +
bridge + Python serializer leaf + Rust unit pins + round-trip pin.
The admit-set count is NOT incremented (no PROBED flip yet).

Tests:

* Rust unit pins (parse-time field shape, negative-field rejection,
  resolve-time creature filter, single creature + multi creature
  byte-equal moves to hand, empty-graveyard fizzle).
* Python serializer round-trip pin (Python → dict → Rust → Python).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3


def _fresh_rust():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Rust unit pins — parse + resolve smoke
# ---------------------------------------------------------------------------


def test_rust_return_up_to_n_creatures_to_hand_parses():
    """The Rust ``Effect::ReturnUpToNCreaturesFromYourGraveyardToHand
    { min_n, max_n }`` variant parses with both required int fields."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Charm",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_creatures_from_your_graveyard_to_hand"
                ),
                "min_n": 1,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)


def test_rust_return_up_to_n_creatures_to_hand_rejects_negative_min_n():
    """Negative ``min_n`` rejected at parse time."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):
        rs.register_and_inject_object(
            {
                "name": "Synth Bad",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 2, "B": 1},
                "effects": [{
                    "kind": (
                        "return_up_to_n_creatures_from_your_graveyard_"
                        "to_hand"
                    ),
                    "min_n": -1,
                    "max_n": 2,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_return_up_to_n_creatures_to_hand_rejects_negative_max_n():
    """Negative ``max_n`` rejected at parse time."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):
        rs.register_and_inject_object(
            {
                "name": "Synth Bad2",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 2, "B": 1},
                "effects": [{
                    "kind": (
                        "return_up_to_n_creatures_from_your_graveyard_"
                        "to_hand"
                    ),
                    "min_n": 1,
                    "max_n": -2,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_return_up_to_n_creatures_to_hand_returns_two_creatures():
    """Two creature cards in graveyard, max_n=2: both come back to
    hand (no counter rider, no MV gate)."""
    _require_engine()
    rs = _fresh_rust()
    # Seed two creature cards in p0's graveyard (high MV — there is no
    # MV gate on this variant, unlike the Phase-4 sibling).
    g1 = rs.register_and_inject_object(
        {"name": "Tiny 1", "card_types": ["Creature"],
         "mana_cost": {"generic": 1},
         "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    g2 = rs.register_and_inject_object(
        {"name": "Huge 2", "card_types": ["Creature"],
         "mana_cost": {"generic": 9},
         "power": 9, "toughness": 9},
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Charm Mode 1",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_creatures_from_your_graveyard_to_hand"
                ),
                "min_n": 1,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "C", 2)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # Both creatures end up in p0's hand (NOT battlefield, NOT counter).
    assert rs.find_object_zone(g1) == _ZONE_HAND, (
        f"Tiny 1 must return to hand, got zone={rs.find_object_zone(g1)}"
    )
    assert rs.find_object_zone(g2) == _ZONE_HAND, (
        f"Huge 2 must return to hand (no MV gate), got "
        f"zone={rs.find_object_zone(g2)}"
    )
    # No +1/+1 counter rider.
    assert rs.get_counters(g1) == 0
    assert rs.get_counters(g2) == 0


def test_rust_return_up_to_n_creatures_to_hand_caps_at_max_n():
    """Three creatures in graveyard, max_n=2: only the first 2 (in Vec
    order) come back. Tests the front-to-back self-scan."""
    _require_engine()
    rs = _fresh_rust()
    g1 = rs.register_and_inject_object(
        {"name": "First", "card_types": ["Creature"],
         "mana_cost": {"generic": 1},
         "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    g2 = rs.register_and_inject_object(
        {"name": "Second", "card_types": ["Creature"],
         "mana_cost": {"generic": 1},
         "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    g3 = rs.register_and_inject_object(
        {"name": "Third", "card_types": ["Creature"],
         "mana_cost": {"generic": 1},
         "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Charm Cap",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_creatures_from_your_graveyard_to_hand"
                ),
                "min_n": 1,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "C", 2)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # First + Second come back; Third (cap exceeded) stays in graveyard.
    assert rs.find_object_zone(g1) == _ZONE_HAND
    assert rs.find_object_zone(g2) == _ZONE_HAND
    assert rs.find_object_zone(g3) == _ZONE_GRAVEYARD, (
        "Third creature should stay in graveyard — max_n=2 cap"
    )


def test_rust_return_up_to_n_creatures_to_hand_skips_noncreature_card():
    """A non-creature card in the graveyard is filtered out (creature
    filter teeth)."""
    _require_engine()
    rs = _fresh_rust()
    g_creat = rs.register_and_inject_object(
        {"name": "C Creat", "card_types": ["Creature"],
         "mana_cost": {"generic": 1},
         "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    g_art = rs.register_and_inject_object(
        {"name": "C Art", "card_types": ["Artifact"],
         "mana_cost": {"generic": 1}},
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Charm Filter",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_creatures_from_your_graveyard_to_hand"
                ),
                "min_n": 1,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "C", 2)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(g_creat) == _ZONE_HAND
    assert rs.find_object_zone(g_art) == _ZONE_GRAVEYARD, (
        "Artifact card filtered out by creature-type teeth"
    )


def test_rust_return_up_to_n_creatures_to_hand_empty_graveyard_fizzles():
    """Empty graveyard → no targets → silent fizzle (no state mutation
    beyond the spell going to graveyard)."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Charm Fizzle",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_creatures_from_your_graveyard_to_hand"
                ),
                "min_n": 1,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "B", 1)
    rs.add_mana(0, "C", 2)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # The spell itself routes to p0's graveyard (CR 608.2m).
    assert rs.find_object_zone(sid) == _ZONE_GRAVEYARD


# ---------------------------------------------------------------------------
# Round-trip pin: Python serializer → Rust parse → Python bridge
# ---------------------------------------------------------------------------


def test_python_serializer_round_trip_for_return_up_to_n_creatures_to_hand():
    """Python ``ReturnUpToNCreaturesFromYourGraveyardToHand(min_n=1,
    max_n=2)`` round-trips through ``_python_spell_effect_to_dict`` →
    ``_ta_dict_to_python_effect`` byte-equal."""
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNCreaturesFromYourGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ReturnUpToNCreaturesFromYourGraveyardToHand(min_n=1, max_n=2)
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": "return_up_to_n_creatures_from_your_graveyard_to_hand",
        "min_n": 1,
        "max_n": 2,
    }
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, ReturnUpToNCreaturesFromYourGraveyardToHand)
    assert back.min_n == 1
    assert back.max_n == 2
    # Pinned-by-__post_init__ riders.
    assert back.creature is True
    assert back.destination == "hand"
    assert back.plus_one_counter is False
    assert back.max_mv == 0
    assert back.max_total_mv == 0
    assert back.target_kind == "graveyard_creature"


def test_python_serializer_round_trip_default_min_n_max_n():
    """Python defaults (min_n=1, max_n=2) round-trip cleanly; the
    deterministic-first scan picks min(graveyard_creatures, max_n)
    regardless of min_n."""
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNCreaturesFromYourGraveyardToHand,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ReturnUpToNCreaturesFromYourGraveyardToHand()  # defaults
    d = _python_spell_effect_to_dict(eff)
    assert d is not None
    assert d["kind"] == (
        "return_up_to_n_creatures_from_your_graveyard_to_hand"
    )
    assert d["min_n"] == 1
    assert d["max_n"] == 2
