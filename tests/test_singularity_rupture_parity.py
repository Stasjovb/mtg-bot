"""**Singularity Rupture Cycle 1 (2026-05-24).**

Tests for the new Rust ``Effect::SingularityRuptureEffect`` unit
variant + the spell-card-bridge admit-flip closure of Singularity
Rupture (``{3}{U}{B}{B}`` Sorcery).

Probes follow the slug-credit convention
``test_cross_engine_real_eoe_<slug>_<effect>_parity`` so the
admit-set inventory pipeline awards the PROBED-flip credit
automatically. Companion Rust unit pins exercise the new
``Effect::SingularityRuptureEffect`` variant's parse + resolve arms
in isolation (parse-time field-free shape, wrath phase, mill phase,
empty-library mill stop).

**Phase 4 auto-grow under the `not slot_kinds` permissive
disjunct.** Singularity Rupture's parsed `target_count_range()` is
``(0, 8)`` and its `target_slot_kinds()` reports ``()`` (empty —
the class doesn't override `target_slot_kinds`). Its mana cost
``{3}{U}{B}{B}`` carries no X-pips. The Phase 4 admit predicate at
``trajectory._PHASE4_MULTI_GRAVEYARD_SHAPE`` accepts under the
``not slot_kinds`` permissive branch — auto-grow STRUCTURAL, no
admit-predicate widen required.

**Resolve-time self-scan vs CR 601.2c cast-time binding.** The
cross-engine harness's ``_PickFirstLegalTargetAgent`` picks
``legal_targets[0]`` non-None on every call until the pool is
exhausted; for a ``min_t=0, max_t=8`` "any number of target
players" multi-target the agent picks EVERY living player as a
target. Python's ``SingularityRuptureEffect.resolve`` walks the
bound targets; Rust's resolve self-scans all living players in
``state.players`` iteration order — both converge to "mill every
living player" byte-equal under the harness convention. See
``docs/SEARCH_LIMITATIONS.md`` entry "Multi-target Phase 4 resolve-
time self-scan vs CR 601.2c cast-time binding".
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_LIBRARY = 1
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3


def _fresh_rust():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_singularity_rupture_parser_emits_expected_effect():
    """**Parser source-of-truth pin.** ``Singularity Rupture`` parses
    to a parameterless ``SingularityRuptureEffect()`` (a frozen
    dataclass with no fields). The full single-sentence body
    ("destroy all creatures, then any number of target players each
    mill half their library, rounded down") consumes one parser regex
    at ``parser/effects.py::_SINGULARITY_RUPTURE`` and emits the
    bespoke Effect class — NOT a ``Sequence`` wrapper over a wrath +
    a multi-target mill primitive."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import SingularityRuptureEffect

    real = get_active_source().get_printings().get("Singularity Rupture")
    if real is None:
        pytest.skip(
            "Singularity Rupture absent from active CardSource"
        )
    se = real.spell_effect
    assert isinstance(se, SingularityRuptureEffect), (
        "Parser must emit SingularityRuptureEffect for Singularity "
        "Rupture (a parameterless bespoke spell-effect class)"
    )
    # target_count_range reports (0, 8) — the Phase-4 admit shape
    # (max_t=8>1, min_t=0 → "any number" branch).
    assert se.target_count_range() == (0, 8)
    # No slot_kinds → empty default. The Phase 4 permissive disjunct
    # accepts empty slot_kinds for the auto-grow path.
    assert se.target_slot_kinds() == ()
    # No Sequence / no second-Effect wrapper — the full body is one
    # bespoke Effect class.
    from mtg_bot.effects.combinators import Sequence
    assert not isinstance(se, Sequence)
    # Mana cost has no X — fits the Phase 4 `not _printing_is_x_cost`
    # conjunct.
    assert real.mana_cost.x_pips == 0


# ---------------------------------------------------------------------------
# Serializer round-trip
# ---------------------------------------------------------------------------


def test_python_serializer_round_trip_for_singularity_rupture():
    """Python ``SingularityRuptureEffect()`` round-trips through
    ``_python_spell_effect_to_dict`` → ``_ta_dict_to_python_effect``
    byte-equal (the §2 round-trip teeth). Unit-variant: only ``kind``
    in the dict."""
    from mtg_bot.effects.bespoke import SingularityRuptureEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = SingularityRuptureEffect()
    d = _python_spell_effect_to_dict(eff)
    assert d == {"kind": "singularity_rupture_effect"}
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, SingularityRuptureEffect)
    assert back == eff


# ---------------------------------------------------------------------------
# Admit gate flip — Singularity Rupture is in the live admit set.
# ---------------------------------------------------------------------------


def test_singularity_rupture_in_bridge_admit_set():
    """**Admit gate flip pin.** ``Singularity Rupture`` is in the
    live spell-card-bridge admit set the moment its
    ``SingularityRuptureEffect`` Python class enters the covered+
    bridged set. The Phase-4 multi-target admit predicate's
    ``(0, 8)`` / empty-slot_kinds shape already accepts under the
    ``not slot_kinds`` permissive disjunct, so the AUTO-JOIN is
    structural — no per-card admit-list entry needed, no admit-
    predicate widen required."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    real = get_active_source().get_printings().get("Singularity Rupture")
    if real is None:
        pytest.skip(
            "Singularity Rupture absent from active CardSource"
        )
    assert trajectory._printing_is_bridge_simple_spell(real), (
        "Singularity Rupture must pass the spell-card-bridge admit "
        "predicate post-cycle-1; the covered+bridged + Phase-4 "
        "permissive-shape gate fires it automatically."
    )


def test_singularity_rupture_effect_class_now_covered():
    """``SingularityRuptureEffect`` is in the live covered+bridged set
    post-Cycle-1 (the Rust ``Effect::SingularityRuptureEffect`` variant
    + the bridge arm both shipped in this lane, so the 1:1 identity
    mapping in ``map_rust_to_python`` includes ``SingularityRupture
    Effect`` in the covered intersection)."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    cov = covered_python_class_set()
    assert "SingularityRuptureEffect" in cov, (
        "SingularityRuptureEffect must be in the covered+bridged set "
        "post-Cycle-1 (Rust variant + bridge arm shipped this lane)"
    )


# ---------------------------------------------------------------------------
# Rust unit pins — parse + resolve smoke
# ---------------------------------------------------------------------------


def test_rust_singularity_rupture_effect_parses():
    """The Rust ``Effect::SingularityRuptureEffect`` unit variant
    parses from the one-key dict ``{"kind":
    "singularity_rupture_effect"}`` — no other fields required."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Rupture",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "U": 1, "B": 2},
            "effects": [{"kind": "singularity_rupture_effect"}],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)


def test_rust_singularity_rupture_destroys_all_creatures():
    """**Wrath phase pin.** Two creatures on each side's bf →
    ALL FOUR go to their controller's graveyard. Indestructible
    creatures (if any) would survive — but the default vanilla
    creature in the per-card probe has no indestructible keyword."""
    _require_engine()
    rs = _fresh_rust()
    # p0 creatures
    bf_p0a = rs.register_and_inject_object(
        {"name": "P0A", "card_types": ["Creature"],
         "mana_cost": {"generic": 1}, "power": 1, "toughness": 1},
        0, _ZONE_BATTLEFIELD,
    )
    bf_p0b = rs.register_and_inject_object(
        {"name": "P0B", "card_types": ["Creature"],
         "mana_cost": {"generic": 2}, "power": 2, "toughness": 2},
        0, _ZONE_BATTLEFIELD,
    )
    # p1 creatures
    bf_p1a = rs.register_and_inject_object(
        {"name": "P1A", "card_types": ["Creature"],
         "mana_cost": {"generic": 1}, "power": 1, "toughness": 1},
        1, _ZONE_BATTLEFIELD,
    )
    bf_p1b = rs.register_and_inject_object(
        {"name": "P1B", "card_types": ["Creature"],
         "mana_cost": {"generic": 3}, "power": 3, "toughness": 3},
        1, _ZONE_BATTLEFIELD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Rupture",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "U": 1, "B": 2},
            "effects": [{"kind": "singularity_rupture_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "B", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(bf_p0a) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(bf_p0b) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(bf_p1a) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(bf_p1b) == _ZONE_GRAVEYARD


def test_rust_singularity_rupture_indestructible_creature_survives():
    """**Indestructible filter pin.** A creature with the
    ``indestructible`` keyword survives the wrath; non-indestructible
    creatures still die. Mirrors Python's ``destroy`` SBA path
    (indestructible creatures are not destroyed by the destroy
    effect)."""
    _require_engine()
    rs = _fresh_rust()
    bf_normal = rs.register_and_inject_object(
        {"name": "Normal", "card_types": ["Creature"],
         "mana_cost": {"generic": 1}, "power": 1, "toughness": 1},
        0, _ZONE_BATTLEFIELD,
    )
    bf_indestr = rs.register_and_inject_object(
        {"name": "Indestructible", "card_types": ["Creature"],
         "mana_cost": {"generic": 2}, "power": 2, "toughness": 2,
         "keywords": ["indestructible"]},
        1, _ZONE_BATTLEFIELD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Rupture",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "U": 1, "B": 2},
            "effects": [{"kind": "singularity_rupture_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "B", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.find_object_zone(bf_normal) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(bf_indestr) == _ZONE_BATTLEFIELD, (
        "Indestructible creature must survive the wrath"
    )


def test_rust_singularity_rupture_mills_half_library_each_player():
    """**Mill phase pin.** Each living player mills
    ``floor(library_size / 2)`` cards from the TOP of their library
    (``library[0]`` n times). Both players have libraries → both get
    milled.

    **Library injection order convention.** ``register_and_inject_
    object`` to the LIBRARY zone uses ``insert(0, ...)`` (test-
    injection convention — see state_ops_resolve.rs:22540). So the
    LAST card inserted lands at ``library[0]`` (the TOP / next-drawn
    slot post-CE3). For a list ``[c0, c1, c2, c3]`` inserted in
    order, the library state is ``[c3, c2, c1, c0]`` and milling 2
    from the top pops ``c3`` then ``c2``."""
    _require_engine()
    rs = _fresh_rust()
    # p0 library: 4 cards → mill 2 (top 2 to graveyard).
    # Last-inserted = library[0] (TOP). So p0_lib[3] is at the top.
    p0_lib = []
    for i in range(4):
        p0_lib.append(rs.register_and_inject_object(
            {"name": f"P0L{i}", "card_types": ["Creature"],
             "mana_cost": {"generic": 1}, "power": 1, "toughness": 1},
            0, _ZONE_LIBRARY,
        ))
    # p1 library: 6 cards → mill 3. p1_lib[5] is at the top.
    p1_lib = []
    for i in range(6):
        p1_lib.append(rs.register_and_inject_object(
            {"name": f"P1L{i}", "card_types": ["Creature"],
             "mana_cost": {"generic": 1}, "power": 1, "toughness": 1},
            1, _ZONE_LIBRARY,
        ))
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Rupture",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "U": 1, "B": 2},
            "effects": [{"kind": "singularity_rupture_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "B", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # p0: top 2 (last-inserted = p0_lib[3], p0_lib[2]) milled;
    # bottom 2 (p0_lib[1], p0_lib[0]) stay.
    assert rs.find_object_zone(p0_lib[3]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(p0_lib[2]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(p0_lib[1]) == _ZONE_LIBRARY
    assert rs.find_object_zone(p0_lib[0]) == _ZONE_LIBRARY
    # p1: top 3 (last-inserted = p1_lib[5], p1_lib[4], p1_lib[3])
    # milled; bottom 3 (p1_lib[2], p1_lib[1], p1_lib[0]) stay.
    assert rs.find_object_zone(p1_lib[5]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(p1_lib[4]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(p1_lib[3]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(p1_lib[2]) == _ZONE_LIBRARY
    assert rs.find_object_zone(p1_lib[1]) == _ZONE_LIBRARY
    assert rs.find_object_zone(p1_lib[0]) == _ZONE_LIBRARY


def test_rust_singularity_rupture_empty_library_no_mill():
    """**Empty library mill stop pin.** A player with 0 or 1 cards in
    library mills 0 (floor(0/2) = 0, floor(1/2) = 0). The mill phase
    silently no-ops for that player; the wrath phase still fires."""
    _require_engine()
    rs = _fresh_rust()
    # p0 library: 1 card → mill 0.
    p0_card = rs.register_and_inject_object(
        {"name": "P0L0", "card_types": ["Creature"],
         "mana_cost": {"generic": 1}, "power": 1, "toughness": 1},
        0, _ZONE_LIBRARY,
    )
    # p1 library: empty → mill 0.
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Rupture",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "U": 1, "B": 2},
            "effects": [{"kind": "singularity_rupture_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "B", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # p0's 1 card stays — floor(1/2) = 0 mill.
    assert rs.find_object_zone(p0_card) == _ZONE_LIBRARY


def test_rust_singularity_rupture_no_creatures_no_libraries_silent_resolve():
    """**No-op resolve pin.** No creatures on either bf + empty
    libraries → both phases silent no-op. The spell still routes to
    p0's graveyard post-resolve (CR 608.2m)."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Rupture",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "U": 1, "B": 2},
            "effects": [{"kind": "singularity_rupture_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "B", 2)
    rs.add_mana(0, "C", 3)
    assert rs.cast_spell_noncreature(sid, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.find_object_zone(sid) == _ZONE_GRAVEYARD


# ---------------------------------------------------------------------------
# Real-EoE cross-engine parity probe — Singularity Rupture PROBED flip
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_singularity_rupture_wrath_and_mill_parity():
    """**GENUINE real-EoE cross-engine probe — Singularity Rupture
    ({3}{U}{B}{B} Sorcery). Multi-target admit-gate Phase 4 closure
    under the `not slot_kinds` permissive disjunct — admit-set flip
    39 → 40 (or 40 → 41 depending on rebase order with Warping Wail
    Cycle 4). PROBED tier.**

    Drives the **ACTUAL parsed Singularity Rupture printing** on the
    Python side: ``get_active_source().get_printings()["Singularity
    Rupture"]`` — which the live parser maps to a ``spell_effect`` of
    ``SingularityRuptureEffect()`` (a parameterless bespoke spell-
    effect class).

    Oracle (verbatim, ``data/edge_of_eternities.json``):

        "[Sorcery] {3}{U}{B}{B} — Destroy all creatures, then any
         number of target players each mill half their library,
         rounded down."

    **Setup.** Both bf have one vanilla creature; each library has
    4 cards. p0 casts Singularity Rupture. Both creatures die;
    each player mills ``floor(4/2) = 2`` cards from the top of
    their library.

    **Resolve-time self-scan vs cast-time bind.** The cross-engine
    harness's ``_PickFirstLegalTargetAgent`` picks every living
    player as a target (since it returns ``pool[0]`` non-None on
    each call, draining the legal_targets pool); Python's resolve
    mills each bound target; Rust's resolve self-scans all living
    players byte-equal under the harness convention. No
    ``StackItem.target_player_ids`` plumbing required.

    Assertion strength: per-zone parity on every affected object
    (creatures + milled library cards), plus stack/graveyard
    accounting.
    """
    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.bespoke import SingularityRuptureEffect
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards import SYNTHETIC_CREATURES

    real = get_active_source().get_printings().get("Singularity Rupture")
    if real is None:
        pytest.skip(
            "Singularity Rupture absent from active CardSource"
        )
    se = real.spell_effect
    assert isinstance(se, SingularityRuptureEffect)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: one vanilla creature on each side's bf; 4 cards
    # in each library; the real Singularity Rupture printing on the
    # stack with both living players bound as targets (the
    # `_PickFirstLegalTargetAgent`-driven all-targets pick).
    # Python's `state.battlefield` is a centralized list shared by
    # both players (per `game.py:2585` GameState dataclass). Each
    # GameObject carries `controller_id` to identify its side.
    py_bf_p0 = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bf_p0.summoning_sick = False
    py_bf_p0.controller_id = 0
    py.battlefield.append(py_bf_p0)
    py_bf_p1 = py.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_bf_p1.summoning_sick = False
    py_bf_p1.controller_id = 1
    py.battlefield.append(py_bf_p1)

    # Python library convention: `library[0]` is the TOP (next-
    # drawn / next-milled — see Python's `library.pop(0)` precedent
    # at `effects/bespoke.py:1660` in SingularityRuptureEffect itself
    # and at `effects/generic/library_lookat.py` etc.). Test setup
    # appends to tail, so the FIRST appended card lands at the TOP
    # iff the library was empty. ``py_p0_lib_top`` lists the cards in
    # eventual top-to-bottom order for clarity.
    py_p0_lib_top_to_bottom = []
    for i in range(4):
        c = py.new_object(
            SYNTHETIC_CREATURES["Sapling"], owner_id=0, zone=Zone.LIBRARY,
        )
        py.players[0].library.append(c)
        py_p0_lib_top_to_bottom.append(c)
    py_p1_lib_top_to_bottom = []
    for i in range(4):
        c = py.new_object(
            SYNTHETIC_CREATURES["Sapling"], owner_id=1, zone=Zone.LIBRARY,
        )
        py.players[1].library.append(c)
        py_p1_lib_top_to_bottom.append(c)

    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(),
            targets=(
                ("player", py.players[0].id),
                ("player", py.players[1].id),
            ),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    # Both creatures destroyed → graveyards.
    py_p0_gy_ids = [c.id for c in py.players[0].graveyard]
    py_p1_gy_ids = [c.id for c in py.players[1].graveyard]
    assert py_bf_p0.id in py_p0_gy_ids, (
        "Python: p0's creature must be in p0's graveyard post-wrath"
    )
    assert py_bf_p1.id in py_p1_gy_ids, (
        "Python: p1's creature must be in p1's graveyard post-wrath"
    )
    # Each player milled top 2 (= first-2-in-top-to-bottom order).
    # Python's `SingularityRuptureEffect.resolve` pops `library[0]`
    # twice → the top-2 elements of `py_p0_lib_top_to_bottom`.
    py_p0_milled = py_p0_lib_top_to_bottom[:2]
    py_p1_milled = py_p1_lib_top_to_bottom[:2]
    for c in py_p0_milled:
        assert c.id in py_p0_gy_ids, (
            f"Python: p0 milled card {c.id} must be in graveyard"
        )
    for c in py_p1_milled:
        assert c.id in py_p1_gy_ids, (
            f"Python: p1 milled card {c.id} must be in graveyard"
        )
    # Bottom-2 stay in library.
    py_p0_lib_ids = [c.id for c in py.players[0].library]
    py_p1_lib_ids = [c.id for c in py.players[1].library]
    for c in py_p0_lib_top_to_bottom[2:]:
        assert c.id in py_p0_lib_ids, (
            f"Python: unmilled p0 card {c.id} must stay in library"
        )
    for c in py_p1_lib_top_to_bottom[2:]:
        assert c.id in py_p1_lib_ids, (
            f"Python: unmilled p1 card {c.id} must stay in library"
        )
    # Library sizes converge: both engines mill 2, leaving 2 each.
    assert len(py.players[0].library) == 2
    assert len(py.players[1].library) == 2
    # Graveyards: p0 = 1 wrath victim + 2 milled + 1 resolving
    # Sorcery (CR 608.2m) = 4; p1 = 1 wrath victim + 2 milled = 3.
    assert len(py.players[0].graveyard) == 4
    assert len(py.players[1].graveyard) == 3

    # ---- Rust: mirror setup. Inject one vanilla creature each, 4
    # library cards each, then cast the real-printing-dict Singularity
    # Rupture via cast_spell_noncreature.
    rs_bf_p0 = rs.register_and_inject_object(
        {
            "name": "Sapling",
            "card_types": ["Creature"],
            "subtypes": ["Plant"],
            "power": 1, "toughness": 2,
            "mana_cost": {"G": 1},
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs_bf_p1 = rs.register_and_inject_object(
        {
            "name": "Sapling",
            "card_types": ["Creature"],
            "subtypes": ["Plant"],
            "power": 1, "toughness": 2,
            "mana_cost": {"G": 1},
        },
        1, _ZONE_BATTLEFIELD,
    )
    # Rust library injection: `insert(0, ...)` — each successive
    # insertion goes to the TOP. So `rs_p0_lib[0]` (first inserted)
    # ends up at the BOTTOM; `rs_p0_lib[3]` (last) is at the TOP.
    rs_p0_lib = []
    for i in range(4):
        rs_p0_lib.append(rs.register_and_inject_object(
            {
                "name": f"Sapling{i}",
                "card_types": ["Creature"],
                "subtypes": ["Plant"],
                "power": 1, "toughness": 2,
                "mana_cost": {"G": 1},
            },
            0, _ZONE_LIBRARY,
        ))
    rs_p1_lib = []
    for i in range(4):
        rs_p1_lib.append(rs.register_and_inject_object(
            {
                "name": f"Sapling{i}",
                "card_types": ["Creature"],
                "subtypes": ["Plant"],
                "power": 1, "toughness": 2,
                "mana_cost": {"G": 1},
            },
            1, _ZONE_LIBRARY,
        ))
    rs_sid = rs.register_and_inject_object(
        {
            "name": "Singularity Rupture",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 3, "U": 1, "B": 2},
            "effects": [{"kind": "singularity_rupture_effect"}],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "B", 2)
    rs.add_mana(0, "C", 3)
    ok = rs.cast_spell_noncreature(rs_sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # Both creatures destroyed.
    assert rs.find_object_zone(rs_bf_p0) == _ZONE_GRAVEYARD, (
        "Rust: p0's creature must be in graveyard post-wrath"
    )
    assert rs.find_object_zone(rs_bf_p1) == _ZONE_GRAVEYARD, (
        "Rust: p1's creature must be in graveyard post-wrath"
    )
    # Each player milled top 2 library cards. Rust's library
    # injection convention prepends — last-inserted = top.
    # Top 2 of p0 = rs_p0_lib[3], [2]; bottom 2 = [1], [0].
    assert rs.find_object_zone(rs_p0_lib[3]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(rs_p0_lib[2]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(rs_p0_lib[1]) == _ZONE_LIBRARY
    assert rs.find_object_zone(rs_p0_lib[0]) == _ZONE_LIBRARY
    assert rs.find_object_zone(rs_p1_lib[3]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(rs_p1_lib[2]) == _ZONE_GRAVEYARD
    assert rs.find_object_zone(rs_p1_lib[1]) == _ZONE_LIBRARY
    assert rs.find_object_zone(rs_p1_lib[0]) == _ZONE_LIBRARY
    # Spell itself routes to p0's graveyard.
    assert rs.find_object_zone(rs_sid) == _ZONE_GRAVEYARD, (
        "Rust: spell itself routes to graveyard post-resolve "
        "(CR 608.2m)"
    )
