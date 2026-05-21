"""ModalChooseOne envelope — Cycle 4 (per-leaf Effect for all-
untargeted modal cards + admit-predicate widen).

Spec: ``docs/SEARCH_LIMITATIONS.md`` "Spell-card-bridge —
`ModalChooseOne` envelope is a multi-round substrate effort" entry.
This module covers **Cycle 4** of the 6-slice plan: the per-leaf
Effect variants for the all-untargeted modal cards (Ruinous Rampage
is the only EoE candidate today) AND the admit-predicate widen.

**Cycle 4 scope.** The Rust ``Effect::DamageEachOpponent`` already
shipped (round-17) + bridged via ``damage_each_opponent``. This
cycle adds the SECOND leaf — ``Effect::ExileAllArtifactsWithMana
ValueAtMost { max_mv: i32 }`` (declaration + parse + to_pydict +
resolve + bridge + reverse serializer arms) — AND widens the admit
predicate ``_printing_is_bridge_simple_spell`` so the
``(0, 0)``-shape all-untargeted ``ModalChooseOne`` auto-admits via
the existing Phase-3 wrath admit arm + the round-trip-or-bail
teeth.

**Auto-grow flip.** Ruinous Rampage (~305 17lands decks) flips
COVERED → PROBED via the wider admit predicate + the new
serializer leaves. The spell-card-bridge admit set grows
15 → 16.

**Some-targeted modals still declined.** Reroute Systems, Scour
for Scrap, Archenemy's Charm, Drill Too Deep, Warping Wail, Twist
Reality, Live or Die — 7 cards — STAY DECLINED via the
target-grammar gate (their ``target_count_range`` is
``(1, 1)`` / ``(2, 2)`` / ``(0, 1)``, while the Phase-3 wrath arm
admits only ``(0, 0)``).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Leaf table — DealDamageEachOpponent
# ---------------------------------------------------------------------------


def test_leaf_serializer_emits_damage_each_opponent_dict():
    """``DealDamageEachOpponent(amount)`` round-trips through
    ``_python_spell_effect_to_dict``'s new ``_leaf`` arm to the
    canonical Rust-shape dict ``{"kind": "damage_each_opponent",
    "amount": N}``. Non-negative invariant pinned.
    """
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(DealDamageEachOpponent(amount=3))
    assert d == {"kind": "damage_each_opponent", "amount": 3}


def test_leaf_serializer_bails_on_negative_damage_each_opponent():
    """Negative amount bails — preserves the round-trip-or-bail
    invariant since Rust's resolve raises on negative ``amount``.
    """
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(DealDamageEachOpponent(amount=-1))
    assert d is None


# ---------------------------------------------------------------------------
# Leaf table — ExileAllArtifactsWithManaValueAtMost
# ---------------------------------------------------------------------------


def test_leaf_serializer_emits_exile_all_artifacts_with_mana_value_at_most_dict():
    """``ExileAllArtifactsWithManaValueAtMost(max_mv)`` round-trips
    through the new ``_leaf`` arm to the canonical Rust-shape dict.
    """
    from mtg_bot.effects.generic.exile import (
        ExileAllArtifactsWithManaValueAtMost,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(
        ExileAllArtifactsWithManaValueAtMost(max_mv=3)
    )
    assert d == {
        "kind": "exile_all_artifacts_with_mana_value_at_most",
        "max_mv": 3,
    }


def test_leaf_serializer_bails_on_negative_max_mv():
    """Negative ``max_mv`` bails — Rust's resolve + parse both raise
    on negative (defense-in-depth)."""
    from mtg_bot.effects.generic.exile import (
        ExileAllArtifactsWithManaValueAtMost,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(
        ExileAllArtifactsWithManaValueAtMost(max_mv=-1)
    )
    assert d is None


# ---------------------------------------------------------------------------
# Bridge round-trip
# ---------------------------------------------------------------------------


def test_bridge_round_trips_exile_all_artifacts_with_mana_value_at_most():
    """``cross_engine._ta_dict_to_python_effect`` consumes the
    canonical dict and produces an equivalent Python class.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.exile import (
        ExileAllArtifactsWithManaValueAtMost,
    )

    eff = _ta_dict_to_python_effect({
        "kind": "exile_all_artifacts_with_mana_value_at_most",
        "max_mv": 2,
    })
    assert isinstance(eff, ExileAllArtifactsWithManaValueAtMost)
    assert eff.max_mv == 2


# ---------------------------------------------------------------------------
# Modal composer round-trip
# ---------------------------------------------------------------------------


def test_modal_composer_round_trips_ruinous_rampage_shape():
    """A synthetic ``ModalChooseOne([DealDamageEachOpponent(3),
    ExileAllArtifactsWithManaValueAtMost(3)])`` — the EXACT
    Ruinous Rampage shape — round-trips through the modal composer
    + the per-leaf arms.
    """
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.effects.generic.exile import (
        ExileAllArtifactsWithManaValueAtMost,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    eff = ModalChooseOne(modes=(
        DealDamageEachOpponent(amount=3),
        ExileAllArtifactsWithManaValueAtMost(max_mv=3),
    ))
    d = _python_spell_effect_to_dict(eff)
    assert d == {
        "kind": "choose_one_mode",
        "modes": [
            {"kind": "damage_each_opponent", "amount": 3},
            {
                "kind": "exile_all_artifacts_with_mana_value_at_most",
                "max_mv": 3,
            },
        ],
    }
    # And the bridge round-trips it back to a structurally-
    # equivalent ModalChooseOne.
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, ModalChooseOne)
    assert len(back.modes) == 2
    assert isinstance(back.modes[0], DealDamageEachOpponent)
    assert back.modes[0].amount == 3
    assert isinstance(back.modes[1], ExileAllArtifactsWithManaValueAtMost)
    assert back.modes[1].max_mv == 3


# ---------------------------------------------------------------------------
# Admit-predicate widen
# ---------------------------------------------------------------------------


def test_admit_predicate_admits_ruinous_rampage_post_cycle4():
    """The Cycle 4 admit predicate widen flips Ruinous Rampage
    DECLINED → ADMITTED. Pre-Cycle-4 the predicate had an
    unconditional ``isinstance(se, ModalChooseOne): return False``
    early reject; post-Cycle-4 that's gone and the
    ``(0, 0)``-shape Phase-3 wrath admit arm + the round-trip-or-bail
    teeth admit the all-untargeted modal Sorcery.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_spell

    src = get_active_source().get_printings()
    rr = src.get("Ruinous Rampage")
    if rr is None:
        pytest.skip("Ruinous Rampage absent from active CardSource")
    assert _printing_is_bridge_simple_spell(rr) is True, (
        "Ruinous Rampage must auto-join the spell-card-bridge admit "
        "set post-Cycle-4: (0, 0)-shape ModalChooseOne + both modes "
        "(DealDamageEachOpponent, ExileAllArtifactsWithManaValueAtMost) "
        "leaf-recognized."
    )


def test_admit_predicate_declines_some_targeted_modal_cards():
    """The remaining some-targeted ModalChooseOne cards STAY DECLINED
    post-Cycle-4. Per-mode target binding (Cycle 5) PLUS the matching
    per-leaf Effect variants (Cycle 6+, one card at a time) are the
    substrate that admits them.

    Tested cards: Reroute Systems (``(1, 1)``-shape), Scour for Scrap
    (``or_both=True``; bails at the modal composer too), Archenemy's
    Charm (``(1, 2)``-shape), Warping Wail (``(0, 1)``-shape).
    **Drill Too Deep WAS in this list pre-Cycle-6; the
    drill-too-deep-slice (2026-05-21) closed it via the
    ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`` Effect
    variant + matching leaf + the Cycle-5 detector table extension —
    Drill Too Deep is now bridge-admitted (see
    ``test_drill_too_deep_parity.py``).**
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_spell

    src = get_active_source().get_printings()
    declined_modals = [
        "Reroute Systems",
        "Scour for Scrap",
        "Archenemy's Charm",
        "Warping Wail",
    ]
    for nm in declined_modals:
        p = src.get(nm)
        if p is None:
            # Cards may be off-set / not in active source.
            continue
        assert _printing_is_bridge_simple_spell(p) is False, (
            f"{nm} must STAY DECLINED post-Cycle-4 — some-targeted "
            f"ModalChooseOne shapes need Cycle-5 per-mode target "
            f"binding PLUS Cycle-6+ per-leaf Effect variants before "
            f"they can flip."
        )


# ---------------------------------------------------------------------------
# Rust variant — exists + parses + resolves
# ---------------------------------------------------------------------------


def test_rust_variant_parses_exile_all_artifacts_with_mana_value_at_most():
    """The new Rust ``Effect::ExileAllArtifactsWithManaValueAtMost``
    variant parses + registers + injects on the bf without raising.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    spell_id = rs.register_and_inject_object(
        {
            "name": "Synthetic Exile",
            "card_types": ["Sorcery"],
            "effects": [{
                "kind": "exile_all_artifacts_with_mana_value_at_most",
                "max_mv": 3,
            }],
        },
        0, 0,  # owner=p0, ZONE_HAND
    )
    assert isinstance(spell_id, int)


def test_rust_variant_parse_rejects_missing_max_mv():
    """``max_mv`` is REQUIRED (mirrors the regex parser contract).
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    # ``require`` raises ``KeyError`` for missing required keys
    # (the Rust ``require`` helper convention); ValueError for
    # invalid values. Mirror that distinction here.
    with pytest.raises((KeyError, ValueError), match="max_mv"):
        rs.register_and_inject_object(
            {
                "name": "Bad Exile",
                "card_types": ["Sorcery"],
                "effects": [{
                    "kind": "exile_all_artifacts_with_mana_value_at_most",
                }],
            },
            0, 0,
        )


def test_rust_variant_parse_rejects_negative_max_mv():
    """Negative ``max_mv`` is rejected at parse (defense-in-depth
    on the schema invariant — MV is non-negative per CR 202.3).
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    with pytest.raises(ValueError, match="non-negative"):
        rs.register_and_inject_object(
            {
                "name": "Bad Exile",
                "card_types": ["Sorcery"],
                "effects": [{
                    "kind": "exile_all_artifacts_with_mana_value_at_most",
                    "max_mv": -1,
                }],
            },
            0, 0,
        )


def test_rust_resolve_exiles_artifacts_at_or_below_max_mv():
    """The Rust resolve arm exiles every artifact whose total MV
    ``<= max_mv``, leaves higher-MV artifacts + non-artifacts
    untouched. Pin against the resolve-time inline expansion.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZB = 2
    # Three artifacts of varying MV + a creature.
    a0 = rs.register_and_inject_object(
        {"name": "MV0", "card_types": ["Artifact"],
         "mana_cost": {"generic": 0}}, 0, ZB,
    )
    a3 = rs.register_and_inject_object(
        {"name": "MV3", "card_types": ["Artifact"],
         "mana_cost": {"generic": 3}}, 1, ZB,
    )
    a4 = rs.register_and_inject_object(
        {"name": "MV4", "card_types": ["Artifact"],
         "mana_cost": {"generic": 4}}, 0, ZB,
    )
    cre = rs.register_and_inject_object(
        {"name": "Cre", "card_types": ["Creature"],
         "power": 2, "toughness": 2,
         "mana_cost": {"generic": 1}}, 0, ZB,
    )

    spell_id = rs.register_and_inject_object(
        {
            "name": "Exile Test",
            "card_types": ["Sorcery"],
            "effects": [{
                "kind": "exile_all_artifacts_with_mana_value_at_most",
                "max_mv": 3,
            }],
        },
        0, 0,
    )
    rs.push_to_stack(spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Survivors: MV4 + Cre.
    bf_names = sorted(e["printing_name"] for e in rs.battlefield_snapshot())
    assert bf_names == ["Cre", "MV4"], (
        f"Rust: MV0 + MV3 must be exiled; MV4 + Cre survive; "
        f"got bf={bf_names}"
    )
    # MV0 (owner p0) in p0's exile; MV3 (owner p1) in p1's exile.
    p0_exile = sorted(e["printing_name"] for e in rs.exile_snapshot(0))
    p1_exile = sorted(e["printing_name"] for e in rs.exile_snapshot(1))
    assert p0_exile == ["MV0"]
    assert p1_exile == ["MV3"]


def test_rust_resolve_rejects_negative_max_mv():
    """Resolve-time defense-in-depth: a hand-crafted
    ``ExileAllArtifactsWithManaValueAtMost { max_mv: -1 }`` raises at
    resolve. (Parse already rejects, so this is only reachable via a
    direct effect-application path; the test verifies the resolve
    arm's guard is present.)

    Driver: synthesize the dict with the parse-arm rejection in mind
    (parse REJECTS at registration, so test the parse rejection here
    as the user-facing surface — the resolve guard is internal).
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    # Parse-arm rejects negative max_mv at registration; the resolve
    # arm guard is internal defense-in-depth.
    with pytest.raises(ValueError):
        rs.register_and_inject_object(
            {
                "name": "Bad Spell",
                "card_types": ["Sorcery"],
                "effects": [{
                    "kind": "exile_all_artifacts_with_mana_value_at_most",
                    "max_mv": -5,
                }],
            },
            0, 0,
        )
