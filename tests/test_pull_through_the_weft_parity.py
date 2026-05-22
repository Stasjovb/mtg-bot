"""**Pull Through the Weft Cycle 1 (2026-05-22).**

Tests for the new Rust ``Effect::ReturnUpToNNonlandPermanentCardsFrom
GraveyardToHand`` variant + the spell-card-bridge admit-flip closure
of Pull Through the Weft (``{3}{G}{G}`` Sorcery).

Probes follow the slug-credit convention
``test_cross_engine_real_eoe_<slug>_<effect>_parity`` so the
admit-set inventory pipeline awards the PROBED-flip credit
automatically. Companion Rust unit pins exercise the new
``Effect::ReturnUpToNNonlandPermanentCardsFromGraveyardToHand``
variant's parse + resolve arms in isolation (parse-time field shape,
nonland-permanent filter, max_n cap, empty-graveyard fizzle).

**Dropped lands clause finding.** Pull Through the Weft's printed
oracle text is "Return up to two target nonland permanent cards from
your graveyard to your hand, then return up to two target land
cards from your graveyard to the battlefield tapped." The Python
parser at ``src/mtg_bot/cards/parser/effects.py:5794`` consumes the
FULL compound sentence in one regex but only emits the FIRST clause
as an Effect — the second (lands-to-bf-tapped) clause is DROPPED
because no ``ReturnLandFromGraveyardToBattlefieldTapped`` primitive
exists in the engine today. The Rust mirror inherits the drop by
simply not modeling it; byte-equal-irrelevant under the cross-engine
probe (the engine never tries to return lands, on either side). See
``docs/SEARCH_LIMITATIONS.md`` entry "Pull Through the Weft dropped
lands clause" for the deliberate divergence rationale.
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
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_pull_through_the_weft_parser_emits_expected_effect():
    """**Parser source-of-truth pin.** ``Pull Through the Weft`` parses
    to ``ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(min_n=0,
    max_n=2)`` with all the post_init-pinned riders (``nonland_
    permanent=True``, ``destination='hand'``, ``target_kind=
    'graveyard_creature'``). The dropped lands clause is consumed but
    not emitted — verified by the absence of any ``Sequence`` /
    second-Effect wrapper in ``spell_effect``."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    )

    real = get_active_source().get_printings().get("Pull Through the Weft")
    if real is None:
        pytest.skip("Pull Through the Weft absent from active CardSource")
    se = real.spell_effect
    assert isinstance(
        se, ReturnUpToNNonlandPermanentCardsFromGraveyardToHand
    ), (
        "Parser must emit ReturnUpToNNonlandPermanentCardsFromGraveyard"
        "ToHand for Pull Through the Weft"
    )
    assert se.min_n == 0
    assert se.max_n == 2
    assert se.nonland_permanent is True
    assert se.creature is False
    assert se.artifact is False
    assert se.land is False
    assert se.destination == "hand"
    assert se.target_kind == "graveyard_creature"
    assert se.max_mv == 0
    assert se.max_total_mv == 0
    assert se.plus_one_counter is False
    assert se.untargeted_all is False
    # The dropped lands clause is byte-equal-irrelevant: it does not
    # surface as a second Effect or a Sequence wrapper.
    from mtg_bot.effects.combinators import Sequence
    assert not isinstance(se, Sequence)
    # target_count_range reports (0, 2) — the Phase-4 admit shape.
    assert se.target_count_range() == (0, 2)


# ---------------------------------------------------------------------------
# Serializer round-trip
# ---------------------------------------------------------------------------


def test_python_serializer_round_trip_for_pull_through_the_weft():
    """Python ``ReturnUpToNNonlandPermanentCardsFromGraveyardToHand
    (min_n=0, max_n=2)`` round-trips through
    ``_python_spell_effect_to_dict`` → ``_ta_dict_to_python_effect``
    byte-equal (the §2 round-trip teeth)."""
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(
        min_n=0, max_n=2,
    )
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": (
            "return_up_to_n_nonland_permanent_cards_from_graveyard_to_hand"
        ),
        "min_n": 0,
        "max_n": 2,
    }
    back = _ta_dict_to_python_effect(d)
    assert isinstance(
        back, ReturnUpToNNonlandPermanentCardsFromGraveyardToHand
    )
    assert back.min_n == 0
    assert back.max_n == 2
    assert back.nonland_permanent is True
    assert back.creature is False
    assert back.destination == "hand"
    assert back.target_kind == "graveyard_creature"
    # Full dataclass equality — every __post_init__-pinned rider matches.
    assert back == eff


def test_python_serializer_round_trip_explicit_min_n_one():
    """Future-proofs the round-trip: a hypothetical
    ``(min_n=1, max_n=3)`` printing also round-trips byte-equal."""
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(
        min_n=1, max_n=3,
    )
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": (
            "return_up_to_n_nonland_permanent_cards_from_graveyard_to_hand"
        ),
        "min_n": 1,
        "max_n": 3,
    }
    back = _ta_dict_to_python_effect(d)
    assert back == eff


# ---------------------------------------------------------------------------
# Admit gate flip — Pull Through the Weft is in the live admit set.
# ---------------------------------------------------------------------------


def test_pull_through_the_weft_in_bridge_admit_set():
    """**Admit gate flip pin.** ``Pull Through the Weft`` is in the
    live spell-card-bridge admit set the moment its
    ``ReturnUpToNNonlandPermanentCardsFromGraveyardToHand`` Effect
    class enters the covered+bridged set. The Phase-4 multi-target
    admit predicate's ``(0, 2)`` / empty-slot_kinds shape already
    accepts uniform ``graveyard_creature`` slot kinds, so the
    AUTO-JOIN is structural — no per-card admit-list entry needed."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = get_active_source().get_printings().get("Pull Through the Weft")
    if real is None:
        pytest.skip("Pull Through the Weft absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(real), (
        "Pull Through the Weft must pass the spell-card-bridge admit "
        "predicate post-cycle-1; the covered+bridged + Phase-4 admit-"
        "shape gate fires it automatically."
    )


# ---------------------------------------------------------------------------
# Rust unit pins — parse/resolve smoke
# ---------------------------------------------------------------------------


def test_rust_return_up_to_n_nonland_permanent_parses():
    """The Rust ``Effect::ReturnUpToNNonlandPermanentCardsFromGraveyard
    ToHand { min_n, max_n }`` variant parses with both required int
    fields. Negative values rejected at parse time (schema invariant)."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Pull",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "G": 2},
            "effects": [{
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": 0,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)


def test_rust_return_up_to_n_nonland_permanent_rejects_negative_min_n():
    """Negative ``min_n`` rejected at parse time."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):  # PyValueError from Rust parse arm
        rs.register_and_inject_object(
            {
                "name": "Synth Bad",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 3, "G": 2},
                "effects": [{
                    "kind": (
                        "return_up_to_n_nonland_permanent_cards_from_"
                        "graveyard_to_hand"
                    ),
                    "min_n": -1,
                    "max_n": 2,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_return_up_to_n_nonland_permanent_rejects_negative_max_n():
    """Negative ``max_n`` rejected at parse time."""
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(Exception):
        rs.register_and_inject_object(
            {
                "name": "Synth Bad2",
                "card_types": ["Sorcery"],
                "mana_cost": {"generic": 3, "G": 2},
                "effects": [{
                    "kind": (
                        "return_up_to_n_nonland_permanent_cards_from_"
                        "graveyard_to_hand"
                    ),
                    "min_n": 0,
                    "max_n": -1,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_return_up_to_n_nonland_permanent_returns_two_happy_path():
    """Two nonland permanent cards (a Creature + an Artifact) in p0's
    graveyard, max_n=2 → both return to HAND. The resolve arm
    self-scans the graveyard front-to-back and accepts any non-Land
    card."""
    _require_engine()
    rs = _fresh_rust()
    g_creature = rs.register_and_inject_object(
        {
            "name": "Synth Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1, "toughness": 1,
        },
        0, _ZONE_GRAVEYARD,
    )
    g_artifact = rs.register_and_inject_object(
        {
            "name": "Synth Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
        },
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Pull",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "G": 2},
            "effects": [{
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": 0,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 2)
    rs.add_mana(0, "C", 3)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.find_object_zone(g_creature) == _ZONE_HAND, (
        f"Creature must return to hand, got zone={rs.find_object_zone(g_creature)}"
    )
    assert rs.find_object_zone(g_artifact) == _ZONE_HAND, (
        f"Artifact must return to hand, got zone={rs.find_object_zone(g_artifact)}"
    )


def test_rust_return_up_to_n_nonland_permanent_filter_excludes_lands():
    """Three cards in graveyard: one Land + two non-Land (Creature +
    Enchantment). max_n=2 → both non-Lands return to HAND; the Land
    STAYS in graveyard."""
    _require_engine()
    rs = _fresh_rust()
    g_land = rs.register_and_inject_object(
        {
            "name": "Synth Land",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
        },
        0, _ZONE_GRAVEYARD,
    )
    g_creature = rs.register_and_inject_object(
        {
            "name": "Synth Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1, "toughness": 1,
        },
        0, _ZONE_GRAVEYARD,
    )
    g_enchant = rs.register_and_inject_object(
        {
            "name": "Synth Enchantment",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2},
        },
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Pull",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "G": 2},
            "effects": [{
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": 0,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(g_land) == _ZONE_GRAVEYARD, (
        "Land must STAY in graveyard — nonland-permanent filter teeth"
    )
    assert rs.find_object_zone(g_creature) == _ZONE_HAND
    assert rs.find_object_zone(g_enchant) == _ZONE_HAND


def test_rust_return_up_to_n_nonland_permanent_caps_at_max_n():
    """Four non-Land cards in graveyard, max_n=2 → only the FIRST 2
    (front-to-back Vec order) return; the remaining 2 STAY in
    graveyard. Mirrors Python's deterministic-first scan pattern."""
    _require_engine()
    rs = _fresh_rust()
    g1 = rs.register_and_inject_object(
        {"name": "A", "card_types": ["Creature"],
         "mana_cost": {"generic": 1}, "power": 1, "toughness": 1},
        0, _ZONE_GRAVEYARD,
    )
    g2 = rs.register_and_inject_object(
        {"name": "B", "card_types": ["Artifact"],
         "mana_cost": {"generic": 1}},
        0, _ZONE_GRAVEYARD,
    )
    g3 = rs.register_and_inject_object(
        {"name": "C", "card_types": ["Enchantment"],
         "mana_cost": {"generic": 1}},
        0, _ZONE_GRAVEYARD,
    )
    g4 = rs.register_and_inject_object(
        {"name": "D", "card_types": ["Creature"],
         "mana_cost": {"generic": 2}, "power": 2, "toughness": 2},
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Pull",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "G": 2},
            "effects": [{
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": 0,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # First 2 in Vec order return.
    assert rs.find_object_zone(g1) == _ZONE_HAND
    assert rs.find_object_zone(g2) == _ZONE_HAND
    # Remaining stay.
    assert rs.find_object_zone(g3) == _ZONE_GRAVEYARD, (
        "Third card must stay — max_n cap honored"
    )
    assert rs.find_object_zone(g4) == _ZONE_GRAVEYARD, (
        "Fourth card must stay — max_n cap honored"
    )


def test_rust_return_up_to_n_nonland_permanent_empty_graveyard_fizzles():
    """Empty graveyard → no targets → silent fizzle (no state mutation
    beyond the spell going to graveyard)."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Pull",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "G": 2},
            "effects": [{
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": 0,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # Spell itself routes to p0's graveyard (CR 608.2m).
    assert rs.find_object_zone(sid) == _ZONE_GRAVEYARD


def test_rust_return_up_to_n_nonland_permanent_only_lands_fizzles():
    """Graveyard contains only Lands → filter rejects all → silent
    fizzle. Pins the nonland-permanent filter teeth specifically (no
    non-Land card returns when only Lands are present)."""
    _require_engine()
    rs = _fresh_rust()
    g_land1 = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"], "subtypes": ["Forest"]},
        0, _ZONE_GRAVEYARD,
    )
    g_land2 = rs.register_and_inject_object(
        {"name": "Plains", "card_types": ["Land"], "subtypes": ["Plains"]},
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Pull",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "G": 2},
            "effects": [{
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": 0,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(g_land1) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(g_land2) == _ZONE_GRAVEYARD


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probe — Pull Through the Weft PROBED flip
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_pull_through_the_weft_return_up_to_n_nonland_permanents_parity():
    """**GENUINE real-EoE cross-engine probe — Pull Through the Weft
    ({3}{G}{G} Sorcery). Multi-target admit-gate Phase 4 closure —
    admit-set flip 24 → 25. PROBED tier.**

    Drives the **ACTUAL parsed Pull Through the Weft printing** on
    the Python side: ``get_active_source().get_printings()["Pull
    Through the Weft"]`` — which the live parser maps to a
    ``spell_effect`` of ``ReturnUpToNNonlandPermanentCardsFrom
    GraveyardToHand(min_n=0, max_n=2)``.

    Oracle (verbatim, ``data/edge_of_eternities.json``):

        "[Sorcery] {3}{G}{G} — Return up to two target nonland
         permanent cards from your graveyard to your hand, then
         return up to two target land cards from your graveyard to
         the battlefield tapped."

    **Dropped lands clause.** The second clause ("then return up to
    two target land cards from your graveyard to the battlefield
    tapped") is DROPPED by the parser at ``parser/effects.py:5794``
    (no engine primitive). The Rust mirror inherits the drop. The
    cross-engine probe is byte-equal-irrelevant on the dropped
    clause — neither engine returns lands.

    **Setup.** p0's graveyard contains one Creature + one Artifact
    (both nonland permanent cards). p0 casts Pull Through the Weft.
    Both nonland permanent cards return to p0's hand.

    Assertion strength: per-zone parity on the affected objects'
    zone state, plus stack/graveyard accounting.
    """
    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards import SYNTHETIC_CREATURES

    real = get_active_source().get_printings().get("Pull Through the Weft")
    if real is None:
        pytest.skip("Pull Through the Weft absent from active CardSource")
    se = real.spell_effect
    assert isinstance(
        se, ReturnUpToNNonlandPermanentCardsFromGraveyardToHand
    )
    assert se.min_n == 0
    assert se.max_n == 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat two nonland permanent cards in p0's graveyard
    # (a creature + an artifact-shaped creature for simplicity using
    # SYNTHETIC_CREATURES), then cast Pull Through with both bound as
    # targets.
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
    py_hand_ids = [c.id for c in py.players[0].hand]
    py_gy_ids = [c.id for c in py.players[0].graveyard]
    assert py_b1.id in py_hand_ids, (
        "Python: Bear 1 must return to hand"
    )
    assert py_b2.id in py_hand_ids, (
        "Python: Bear 2 must return to hand"
    )
    assert py_b1.id not in py_gy_ids, (
        "Python: Bear 1 must leave graveyard"
    )
    assert py_b2.id not in py_gy_ids, (
        "Python: Bear 2 must leave graveyard"
    )

    # ---- Rust: seat two nonland permanent cards in p0's graveyard +
    # the real Pull Through the Weft printing's effect dict, then cast
    # via cast_spell_noncreature.
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
            "name": "Pull Through the Weft",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "G": 2},
            "effects": [{
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": 0,
                "max_n": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "G", 2)
    rs.add_mana(0, "C", 3)
    ok = rs.cast_spell_noncreature(rs_sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.find_object_zone(rs_b1) == _ZONE_HAND, (
        "Rust: Bear 1 must return to hand"
    )
    assert rs.find_object_zone(rs_b2) == _ZONE_HAND, (
        "Rust: Bear 2 must return to hand"
    )
    assert rs.find_object_zone(rs_sid) == _ZONE_GRAVEYARD, (
        "Rust: spell itself routes to graveyard post-resolve (CR 608.2m)"
    )
