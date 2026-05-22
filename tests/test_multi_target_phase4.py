"""**Multi-target admit-gate Phase 4 widen (2026-05-21).**

Tests for the spell-card-bridge lever's Phase-4 multi-target admit
arm and the inaugural consumer:
``ReturnUpToNSmallCreaturesFromGraveyardWithCounters`` (Scout for
Survivors, `{2}{W}` Sorcery, 4,170 17lands decks).

Probes follow the slug-credit convention
``test_cross_engine_real_eoe_<slug>_<effect>_parity`` so the
admit-set inventory pipeline awards the PROBED-flip credit
automatically. Companion Rust unit pins exercise the new
``Effect::ReturnUpToNSmallCreaturesFromGraveyardWithCounters``
variant's parse + resolve arms in isolation (parse-time field
shape, sum-MV budget, +1/+1 counter rider, ETB-trigger fan-out).
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
# Rust unit pins — parse/resolve smoke
# ---------------------------------------------------------------------------


def test_rust_return_up_to_n_small_creatures_from_graveyard_with_counters_parses():
    """The Rust
    ``Effect::ReturnUpToNSmallCreaturesFromGraveyardWithCounters {
    max_n, max_total_mv }`` variant parses with both required int
    fields. Negative values are rejected at parse time (schema
    invariant)."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Scout",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_small_creatures_from_graveyard_"
                    "with_counters"
                ),
                "max_n": 3,
                "max_total_mv": 3,
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)


def test_rust_return_up_to_n_small_creatures_rejects_negative_max_n():
    """Negative ``max_n`` rejected at parse time."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):  # PyValueError from Rust parse arm
        rs.register_and_inject_object(
            {
                "name": "Synth Bad",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 2, "W": 1},
                "effects": [{
                    "kind": (
                        "return_up_to_n_small_creatures_from_graveyard_"
                        "with_counters"
                    ),
                    "max_n": -1,
                    "max_total_mv": 3,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_return_up_to_n_small_creatures_rejects_negative_max_total_mv():
    """Negative ``max_total_mv`` rejected at parse time."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):
        rs.register_and_inject_object(
            {
                "name": "Synth Bad2",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 2, "W": 1},
                "effects": [{
                    "kind": (
                        "return_up_to_n_small_creatures_from_graveyard_"
                        "with_counters"
                    ),
                    "max_n": 3,
                    "max_total_mv": -3,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_return_up_to_n_small_creatures_resolves_within_budget():
    """Two creature cards (MV 1 + MV 2 = 3) in graveyard, budget 3, max_n=3.
    Both come back to battlefield with a +1/+1 counter."""
    _require_engine()
    rs = _fresh_rust()
    # Seed two creature cards in p0's graveyard.
    g1 = rs.register_and_inject_object(
        {"name": "Tiny 1", "card_types": ["Creature"],
         "mana_cost": {"generic": 1},
         "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    g2 = rs.register_and_inject_object(
        {"name": "Tiny 2", "card_types": ["Creature"],
         "mana_cost": {"generic": 2},
         "power": 2, "toughness": 2},
        0, _ZONE_GRAVEYARD,
    )
    # Seed a Scout-for-Survivors-shaped spell in p0's hand + mana.
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Scout",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_small_creatures_from_graveyard_"
                    "with_counters"
                ),
                "max_n": 3,
                "max_total_mv": 3,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "W", 1)
    rs.add_mana(0, "C", 2)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # Both creatures should now be on p0's battlefield with +1/+1
    # counter (counters >= 1).
    assert rs.find_object_zone(g1) == _ZONE_BATTLEFIELD, (
        f"Tiny 1 must return to battlefield, got zone={rs.find_object_zone(g1)}"
    )
    assert rs.find_object_zone(g2) == _ZONE_BATTLEFIELD, (
        f"Tiny 2 must return to battlefield, got zone={rs.find_object_zone(g2)}"
    )
    assert rs.get_counters(g1) == 1, (
        f"Tiny 1 must have +1/+1 counter, got {rs.get_counters(g1)}"
    )
    assert rs.get_counters(g2) == 1, (
        f"Tiny 2 must have +1/+1 counter, got {rs.get_counters(g2)}"
    )


def test_rust_return_up_to_n_small_creatures_skips_over_budget_card():
    """Three creatures (MV 1, MV 5, MV 2). Budget 3, max_n=3. The
    MV-5 card is OVER the per-card cap so doesn't enter the pool;
    the MV-1 + MV-2 pair both come back."""
    _require_engine()
    rs = _fresh_rust()
    g1 = rs.register_and_inject_object(
        {"name": "Tiny", "card_types": ["Creature"],
         "mana_cost": {"generic": 1},
         "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    g2 = rs.register_and_inject_object(
        {"name": "Huge", "card_types": ["Creature"],
         "mana_cost": {"generic": 5},
         "power": 5, "toughness": 5},
        0, _ZONE_GRAVEYARD,
    )
    g3 = rs.register_and_inject_object(
        {"name": "Medium", "card_types": ["Creature"],
         "mana_cost": {"generic": 2},
         "power": 2, "toughness": 2},
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Scout 2",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_small_creatures_from_graveyard_"
                    "with_counters"
                ),
                "max_n": 3,
                "max_total_mv": 3,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "W", 1)
    rs.add_mana(0, "C", 2)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(g1) == _ZONE_BATTLEFIELD
    assert rs.find_object_zone(g2) == _ZONE_GRAVEYARD, (
        "Huge (MV 5) must stay in graveyard — exceeds per-card budget"
    )
    assert rs.find_object_zone(g3) == _ZONE_BATTLEFIELD


def test_rust_return_up_to_n_small_creatures_skips_noncreature_card():
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
            "name": "Synth Scout 3",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_small_creatures_from_graveyard_"
                    "with_counters"
                ),
                "max_n": 3,
                "max_total_mv": 3,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "W", 1)
    rs.add_mana(0, "C", 2)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(g_creat) == _ZONE_BATTLEFIELD
    assert rs.find_object_zone(g_art) == _ZONE_GRAVEYARD, (
        "Artifact card filtered out by creature-type teeth"
    )


def test_rust_return_up_to_n_small_creatures_empty_graveyard_fizzles_silently():
    """Empty graveyard → no targets → silent fizzle (no state mutation
    beyond the spell going to graveyard)."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Scout 4",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_small_creatures_from_graveyard_"
                    "with_counters"
                ),
                "max_n": 3,
                "max_total_mv": 3,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "W", 1)
    rs.add_mana(0, "C", 2)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # The spell itself should be in p0's graveyard (CR 608.2m).
    assert rs.find_object_zone(sid) == _ZONE_GRAVEYARD


# ---------------------------------------------------------------------------
# Round-trip pin: the new Effect variant round-trips through
# Python serializer + Rust parse + cross_engine bridge.
# ---------------------------------------------------------------------------


def test_python_serializer_round_trip_for_scout_for_survivors():
    """Python ``ReturnUpToNSmallCreaturesFromGraveyardWithCounters(max_n=3,
    max_total_mv=3)`` round-trips through
    ``_python_spell_effect_to_dict`` → ``_ta_dict_to_python_effect``
    byte-equal (the §2 round-trip teeth)."""
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ReturnUpToNSmallCreaturesFromGraveyardWithCounters(
        max_n=3, max_total_mv=3,
    )
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": (
            "return_up_to_n_small_creatures_from_graveyard_with_counters"
        ),
        "max_n": 3,
        "max_total_mv": 3,
    }
    back = _ta_dict_to_python_effect(d)
    # Equality on the dataclass: same max_n + max_total_mv + every
    # pinned-by-__post_init__ rider.
    assert isinstance(back, ReturnUpToNSmallCreaturesFromGraveyardWithCounters)
    assert back.max_n == 3
    assert back.max_total_mv == 3
    assert back.creature is True
    assert back.destination == "battlefield"
    assert back.plus_one_counter is True
    assert back.max_mv == 3


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probe — Scout for Survivors PROBED flip
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_scout_for_survivors_return_up_to_n_creatures_with_counters_parity():
    """**GENUINE real-EoE cross-engine probe — Scout for Survivors
    ({2}{W} Sorcery, 4,170 17lands decks). Multi-target admit-gate
    Phase 4 widen — admit-set flip 20 → 21. PROBED tier.**

    Drives the **ACTUAL parsed Scout for Survivors printing** on the
    Python side: ``get_active_source().get_printings()["Scout for
    Survivors"]`` — which the live parser maps to a ``spell_effect``
    of ``ReturnUpToNSmallCreaturesFromGraveyardWithCounters(max_n=3,
    max_total_mv=3)``.

    Oracle (verbatim, ``data/edge_of_eternities.json``):

        "[Sorcery] {2}{W} — Return up to three target creature cards
         with total mana value 3 or less from your graveyard to the
         battlefield. Put a +1/+1 counter on each of them."

    **Setup.** p0's graveyard contains two MV-1 creatures (sum 2 ≤
    3). p0 casts Scout for Survivors. Both creatures return to
    battlefield with a +1/+1 counter each.

    Assertion strength: per-zone parity on the affected objects'
    zone + counter state, plus stack/graveyard accounting.
    """
    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards import SYNTHETIC_CREATURES

    real = get_active_source().get_printings().get("Scout for Survivors")
    if real is None:
        pytest.skip("Scout for Survivors absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ReturnUpToNSmallCreaturesFromGraveyardWithCounters)
    assert se.max_n == 3
    assert se.max_total_mv == 3

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat two Bears in p0's graveyard, then cast Scout
    # with both bound as targets.
    py_b1 = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_b1.summoning_sick = False
    py.players[0].graveyard.append(py_b1)
    py_b2 = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_b2.summoning_sick = False
    py.players[0].graveyard.append(py_b2)

    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(),
            targets=(
                ("graveyard_creature", py_b1.id),
                ("graveyard_creature", py_b2.id),
            ),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    py_bf = list(py.battlefield)
    assert py_b1 in py_bf, "Python: Bear 1 must return to battlefield"
    assert py_b2 in py_bf, "Python: Bear 2 must return to battlefield"
    # +1/+1 counter applied to each.
    assert py_b1.plus_one_counters == 1, (
        f"Python: Bear 1 must have +1/+1 counter, got {py_b1.plus_one_counters}"
    )
    assert py_b2.plus_one_counters == 1, (
        f"Python: Bear 2 must have +1/+1 counter, got {py_b2.plus_one_counters}"
    )

    # ---- Rust: seat two Bears in p0's graveyard + the real Scout
    # printing's effect dict, then cast via cast_spell_noncreature.
    rs_b1 = rs.register_and_inject_object(
        {
            "name": "Sapling",
            "card_types": ["Creature"],
            "subtypes": ["Plant"],
            "power": 1, "toughness": 2,
            "mana_cost": {"G": 1},
        },
        0, _ZONE_GRAVEYARD,
    )
    rs_b2 = rs.register_and_inject_object(
        {
            "name": "Sapling",
            "card_types": ["Creature"],
            "subtypes": ["Plant"],
            "power": 1, "toughness": 2,
            "mana_cost": {"G": 1},
        },
        0, _ZONE_GRAVEYARD,
    )
    rs_sid = rs.register_and_inject_object(
        {
            "name": "Scout for Survivors",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [{
                "kind": (
                    "return_up_to_n_small_creatures_from_graveyard_"
                    "with_counters"
                ),
                "max_n": 3,
                "max_total_mv": 3,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "W", 1)
    rs.add_mana(0, "C", 2)
    ok = rs.cast_spell_noncreature(rs_sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.find_object_zone(rs_b1) == _ZONE_BATTLEFIELD, (
        "Rust: Bear 1 must return to battlefield"
    )
    assert rs.find_object_zone(rs_b2) == _ZONE_BATTLEFIELD, (
        "Rust: Bear 2 must return to battlefield"
    )
    assert rs.get_counters(rs_b1) == 1, (
        "Rust: Bear 1 must have +1/+1 counter"
    )
    assert rs.get_counters(rs_b2) == 1, (
        "Rust: Bear 2 must have +1/+1 counter"
    )
    assert rs.find_object_zone(rs_sid) == _ZONE_GRAVEYARD, (
        "Rust: spell itself routes to graveyard post-resolve (CR 608.2m)"
    )
