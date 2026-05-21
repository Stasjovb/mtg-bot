"""ModalChooseOne envelope — Cycle 5 (per-mode target binding).

Spec: ``docs/SEARCH_LIMITATIONS.md`` "Spell-card-bridge —
`ModalChooseOne` envelope is a multi-round substrate effort" entry.
This module covers **Cycle 5** of the 6-slice plan: per-mode target
binding at cast time.

**Cycle 5 scope.** Lane X (Cycles 1-3) wired cast-time mode binding +
per-mode resolve dispatch + reverse serializer. Lane AA (Cycle 4)
added per-leaf Effect arms for all-untargeted modes (Ruinous Rampage
flipped). This cycle widens ``cast_spell_noncreature`` to bind the
deterministic-first legal target for the CHOSEN mode's leaf
filter — not just for the top-level effect (the pre-Cycle-5 ladder
only recognized non-modal targeted shapes; for modal spells it fell
through to the default "first creature" scan, which is
load-bearing-WRONG for modes whose filter is e.g. "first non-
indestructible artifact").

**Substrate-only landing.** Cycle 5 ships the API (the per-mode
target binding override in ``cast_spell_noncreature``) but DOES NOT
widen the admit predicate ``_printing_is_bridge_simple_spell``.
Modal spells in EoE (Reroute Systems, Scour for Scrap, Archenemy's
Charm, Drill Too Deep) STAY DECLINED — they need per-leaf Effect
variants (Cycle 6) before they can flip. The substrate is "wired but
unused" today; meaningful only when Cycle 6's per-leaf arms ship
and the admit set widens.

**First-slice detector table.** Today the per-mode-binding override
recognizes ONE leaf:

* ``DestroyTargetArtifact`` (Drill Too Deep mode 1): scans
  ``bf_iter_etb_sorted`` for the first non-indestructible artifact.

Cycle 6 grows this table per the candidate cards (Reroute Systems
mode 0's ``PumpTargetArtifactOrCreatureUntilEOT(power=0, tough=0,
granted_keywords={'indestructible'})`` widened variant, mode 1's
``DealDamageToTargetTappedCreature`` new variant, etc.).
"""

from __future__ import annotations

import importlib.util

import pytest

ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _fresh_state():
    """A 0-bf / 0-hand / 0-library state — everything injected via
    ``register_and_inject_object``."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Per-mode target binding — DestroyTargetArtifact leaf
# ---------------------------------------------------------------------------


def test_modal_destroy_target_artifact_binds_first_artifact():
    """A modal spell whose mode 0 is ``DestroyTargetArtifact`` binds
    the first non-indestructible artifact on EITHER bf — NOT the
    pre-Cycle-5 default first-creature. Synthetic state seeds a
    Creature first (would be picked by the default ladder) plus an
    Artifact later; verify the cast-time bind picks the Artifact.
    """
    _require_engine()
    state = _fresh_state()
    # Seed a creature first (would be picked by the default ladder).
    cre_id = state.register_and_inject_object(
        {
            "name": "Bear",
            "mana_cost": {"generic": 1, "G": 1},
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2,
            "toughness": 2,
        },
        0, ZONE_BATTLEFIELD,
    )
    # Seed an artifact AFTER the creature so the default first-
    # creature scan would NOT pick it; the modal per-mode override
    # must pick it via the artifact filter.
    art_id = state.register_and_inject_object(
        {
            "name": "Trinket",
            "mana_cost": {"generic": 2},
            "card_types": ["Artifact"],
        },
        0, ZONE_BATTLEFIELD,
    )
    # Modal spell: mode 0 = DestroyTargetArtifact, mode 1 = GainLife.
    spell_id = state.register_and_inject_object(
        {
            "name": "Modal Destroy",
            "mana_cost": {"generic": 1},
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {"kind": "destroy_target_artifact"},
                        {"kind": "gain_life", "amount": 2},
                    ],
                },
            ],
        },
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_size() == 1
    # Cast-time bind: mode 0 selected, artifact target bound.
    assert state.stack_top_chosen_mode_idx() == 0
    assert state.stack_top_target_id() == art_id, (
        f"Modal Destroy must bind the artifact at cast time per mode 0's "
        f"filter (DestroyTargetArtifact = first non-indestructible "
        f"artifact in bf_iter_etb_sorted order), not the default "
        f"first-creature. cre_id={cre_id} art_id={art_id} got="
        f"{state.stack_top_target_id()}"
    )


def test_modal_destroy_target_artifact_skips_indestructible_artifact():
    """The per-mode filter must skip indestructible artifacts — same
    as the resolve arm's filter at
    ``state_ops_resolve.rs::DestroyTargetArtifact`` (line ~6927).
    Synthetic state seeds an indestructible artifact first, then a
    destructible one; cast-time bind picks the destructible.
    """
    _require_engine()
    state = _fresh_state()
    indest_id = state.register_and_inject_object(
        {
            "name": "Sacred Trinket",
            "mana_cost": {"generic": 2},
            "card_types": ["Artifact"],
            "keywords": ["indestructible"],
        },
        0, ZONE_BATTLEFIELD,
    )
    dest_id = state.register_and_inject_object(
        {
            "name": "Trinket",
            "mana_cost": {"generic": 2},
            "card_types": ["Artifact"],
        },
        0, ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        {
            "name": "Modal Destroy",
            "mana_cost": {"generic": 1},
            "card_types": ["Instant"],
            "effects": [{
                "kind": "choose_one_mode",
                "modes": [
                    {"kind": "destroy_target_artifact"},
                    {"kind": "gain_life", "amount": 2},
                ],
            }],
        },
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_target_id() == dest_id, (
        f"Cycle 5 per-mode bind must skip the indestructible artifact "
        f"id={indest_id} and pick the destructible id={dest_id}; got="
        f"{state.stack_top_target_id()}"
    )


def test_modal_destroy_target_artifact_no_artifact_binds_none():
    """When no legal artifact target exists, the per-mode bind
    returns ``None`` (no target). Pre-Cycle-5 the ladder would have
    bound the first creature; post-Cycle-5 the modal override
    returns ``None`` because the artifact filter found no match.
    This is the substrate-correct shape — at resolve time the arm
    can re-check via CR 608.2b and fizzle.
    """
    _require_engine()
    state = _fresh_state()
    # Only a creature on bf — no artifacts.
    state.register_and_inject_object(
        {
            "name": "Bear",
            "mana_cost": {"generic": 1, "G": 1},
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2,
            "toughness": 2,
        },
        0, ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        {
            "name": "Modal Destroy",
            "mana_cost": {"generic": 1},
            "card_types": ["Instant"],
            "effects": [{
                "kind": "choose_one_mode",
                "modes": [
                    {"kind": "destroy_target_artifact"},
                    {"kind": "gain_life", "amount": 2},
                ],
            }],
        },
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_chosen_mode_idx() == 0
    # No legal artifact; bind returns None.
    assert state.stack_top_target_id() is None


# ---------------------------------------------------------------------------
# Non-recognized chosen-mode leaves fall through to default
# ---------------------------------------------------------------------------


def test_modal_unrecognized_leaf_falls_through_to_default():
    """When the chosen mode's leaf is NOT in the Cycle-5 per-mode
    detector table (today only ``DestroyTargetArtifact``), the
    bound target falls through to whatever the non-modal default
    ladder bound. For an untargeted leaf (DrawCards) on a non-
    targeted modal, that default is the "first creature" fallback,
    which is admittedly load-bearing-WRONG for genuinely-targeted
    modal modes — the admit predicate keeps such cards DECLINED
    until their leaf joins the detector table in Cycle 6.

    This test pins the back-compat default-fallback behavior so the
    detector table grows additively without surprise: an entry not
    yet in the table preserves pre-Cycle-5 behavior, which is the
    documented substrate-only safety.
    """
    _require_engine()
    state = _fresh_state()
    cre_id = state.register_and_inject_object(
        {
            "name": "Bear",
            "mana_cost": {"generic": 1, "G": 1},
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2,
            "toughness": 2,
        },
        0, ZONE_BATTLEFIELD,
    )
    # All-untargeted modal — same shape as Ruinous Rampage (Cycle 4)
    # but in synthetic form. The chosen leaf (DrawCards) is NOT in
    # the Cycle-5 detector table, so the bind falls through to the
    # default ladder's first-creature scan. (Real Ruinous Rampage
    # is admitted via the Phase-3 (0,0)-shape wrath arm in the
    # admit predicate, NOT via this code path — its leaves are
    # both untargeted and the default scan's binding never gets
    # READ by an untargeted resolve arm. The bind is a harmless
    # no-op.)
    spell_id = state.register_and_inject_object(
        {
            "name": "Modal Draw",
            "mana_cost": {"generic": 1},
            "card_types": ["Instant"],
            "effects": [{
                "kind": "choose_one_mode",
                "modes": [
                    {"kind": "draw_cards", "count": 1},
                    {"kind": "gain_life", "amount": 2},
                ],
            }],
        },
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    assert state.stack_top_chosen_mode_idx() == 0
    # DrawCards is NOT in the detector table — falls through to
    # the non-modal ladder's default first-creature bind.
    assert state.stack_top_target_id() == cre_id


# ---------------------------------------------------------------------------
# Non-modal spells: no regression
# ---------------------------------------------------------------------------


def test_non_modal_spell_unaffected_by_cycle5():
    """A non-modal targeted spell's cast-time bind is UNCHANGED by
    Cycle 5 — the per-mode override only fires when
    ``bound_mode_idx`` is ``Some(_)``. Back-compat byte-identical
    pin for the dominant non-modal cast path.
    """
    _require_engine()
    state = _fresh_state()
    cre_id = state.register_and_inject_object(
        {
            "name": "Bear",
            "mana_cost": {"generic": 1, "G": 1},
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2,
            "toughness": 2,
        },
        0, ZONE_BATTLEFIELD,
    )
    # Plain (non-modal) instant — first effect is NOT ChooseOneMode.
    spell_id = state.register_and_inject_object(
        {
            "name": "Plain Draw",
            "mana_cost": {"generic": 1},
            "card_types": ["Instant"],
            "effects": [{"kind": "draw_cards", "count": 1}],
        },
        0, ZONE_HAND,
    )
    state.add_mana(0, "C", 1)
    ok = state.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    # Non-modal: no mode bind.
    assert state.stack_top_chosen_mode_idx() is None
    # The default ladder still binds first creature.
    assert state.stack_top_target_id() == cre_id


# ---------------------------------------------------------------------------
# Admit predicate STILL declines modal cards (Cycle 5 substrate-only)
# ---------------------------------------------------------------------------


def test_admit_predicate_still_declines_some_targeted_modal_cards_post_cycle5():
    """Cycle 5 substrate ships the per-mode target binding API but
    DOES NOT widen the admit predicate. The remaining EoE some-
    targeted modal cards STAY DECLINED post-Cycle-5 — they need
    per-leaf Effect variants (Cycle 6+, one card at a time) before
    they can flip. This pin guards against accidentally enabling
    admit + diverging trajectories.

    **Drill Too Deep + Reroute Systems closures (2026-05-21).** Both
    cards were originally pinned here. ``feature/drill-too-deep-slice``
    closed Drill Too Deep via the
    ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`` Effect
    variant (see ``test_drill_too_deep_parity.py``).
    ``feature/reroute-systems-slice-v2`` closed Reroute Systems via
    its per-leaf Effect variants (extended
    ``PumpTargetArtifactOrCreatureUntilEOT`` with ``granted_keywords``
    + new ``DealDamageToTargetTappedCreature`` variant — see
    ``test_reroute_systems.py``). Scour for Scrap and Archenemy's
    Charm stay declined here pending their own per-leaf closures.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_spell

    src = get_active_source().get_printings()
    declined_modals = [
        "Scour for Scrap",
        "Archenemy's Charm",
    ]
    for nm in declined_modals:
        p = src.get(nm)
        if p is None:
            continue
        assert _printing_is_bridge_simple_spell(p) is False, (
            f"{nm} must STAY DECLINED post-Cycle-5 substrate. "
            f"Cycle 6 needs the per-leaf Effect variants + admit "
            f"widen before any some-targeted modal can flip."
        )


# ---------------------------------------------------------------------------
# Ruinous Rampage (Cycle 4 PROBED) regression guard
# ---------------------------------------------------------------------------


def test_ruinous_rampage_still_admitted_post_cycle5():
    """Lane AA's Ruinous Rampage PROBED flip relies on the
    (0,0)-shape Phase-3 wrath admit arm. Cycle 5's per-mode override
    must not regress that path (Ruinous Rampage's modes are both
    untargeted — the per-mode override doesn't fire on them via
    the detector table, but the cast-time mode-bind itself does
    fire — which IS the substrate landing Cycle 4 relied on).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_spell

    src = get_active_source().get_printings()
    rr = src.get("Ruinous Rampage")
    if rr is None:
        pytest.skip("Ruinous Rampage absent from active CardSource")
    assert _printing_is_bridge_simple_spell(rr) is True, (
        "Ruinous Rampage must remain ADMITTED post-Cycle-5: the "
        "Phase-3 wrath admit arm + Lane AA's per-leaf serializers "
        "stay in force."
    )
