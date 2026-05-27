"""Rust-engine unit pins for the
``Effect::AddOneManaOfChosenPermanentColor`` parse + to_pydict + resolve
arms.

**Meteor Crater substrate Phase 4 Cycle 1 (2026-05-27 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#1 Meteor
Crater).** The Rust Effect variant is a unit (no fields); both engines
compute the color-options surface at resolve time from the source-
controller's battlefield permanents' colored pips. Rust's no-agent
fallback picks the canonical-first WUBRG-ordered color; the empty-
union defensive fallback mints a colorless ``{C}`` coin.

These pins drive the new resolve arm DIRECTLY via the
``apply_action({"kind": "activate_ability", ...})`` path on synthetic
Meteor-Crater-shape Lands. The cross-engine bridge round-trip + the
Python admit-gate substrate-only invariant are covered by the sibling
test at ``tests/test_meteor_crater_substrate_cycle_1.py``; this module
pins the Rust-engine-side resolve semantics that the bridge relies on.

Covered:

  - parse_effect arm accepts the 1-key dict shape.
  - to_pydict arm emits the same byte-equal 1-key dict.
  - Resolve picks W when only a white permanent is on the source-
    controller's bf.
  - Resolve picks canonical-first WUBRG from a multi-color union
    (sibling of the bigger pin in the Python-side test file).
  - Resolve falls back to {C} when the union is empty (all-colorless
    permanents — defensive fallback mirrors Python's
    ``if not options: color = "C"`` at ``mana.py:255-256``).
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2


def _meteor_crater_dict():
    """Synthetic Meteor-Crater-shape Land printing dict."""
    return {
        "name": "Synthetic Meteor Crater",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "add_one_mana_of_chosen_permanent_color",
                },
                "is_mana_ability": True,
            },
        ],
    }


def _mono_colored_creature_dict(color: str):
    """Mono-colored creature with 1 colored pip + 1 generic in cost."""
    return {
        "name": f"Synthetic {color} Creature",
        "card_types": ["Creature"],
        "mana_cost": {color: 1, "generic": 1},
        "power": 1,
        "toughness": 1,
    }


@pytest.fixture
def empty_state(engine):
    """Empty 0/0/0 synthetic state — Meteor Crater's resolve scans
    bf for color-union derivation, so a pre-seeded bf would inject
    spurious colors."""
    return engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# parse_effect + to_pydict pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new
    ``add_one_mana_of_chosen_permanent_color`` parse arm consumes
    the 1-key dict shape and registers cleanly.
    """
    pid = empty_registry.register_printing(_meteor_crater_dict())
    assert empty_registry.get_printing_name(pid) == "Synthetic Meteor Crater"


# ---------------------------------------------------------------------------
# Resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_picks_w_with_only_white_permanent(empty_state):
    """**Resolve arm pin — single-color union.** When the source-
    controller's bf has only a mono-W permanent, the color union is
    {"W"} and the canonical-first pick is W → 1 W coin minted.
    """
    empty_state.register_and_inject_object(
        _mono_colored_creature_dict("W"), 0, ZONE_BATTLEFIELD,
    )
    crater_id = empty_state.register_and_inject_object(
        _meteor_crater_dict(), 0, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(crater_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })
    pool = empty_state.get_mana_pool(0)
    assert pool == {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}


def test_resolve_picks_canonical_first_u_when_u_g_r_union(empty_state):
    """**Resolve arm pin — multi-color union, canonical-first WUBRG.**
    Union of {"U","G","R"} → canonical-first WUBRG-ordered pick = U.
    The sorted-alphabetic pick would be G; this divergence is
    INTENTIONAL per the user spec (match the Phase-4E `any` code-
    path's canonical-first precedent at `daecd399`).
    """
    for color in ("U", "G", "R"):
        empty_state.register_and_inject_object(
            _mono_colored_creature_dict(color), 0, ZONE_BATTLEFIELD,
        )
    crater_id = empty_state.register_and_inject_object(
        _meteor_crater_dict(), 0, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(crater_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })
    pool = empty_state.get_mana_pool(0)
    assert pool == {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}


def test_resolve_empty_union_mints_c_fallback(empty_state):
    """**Resolve arm pin — defensive colorless fallback.** When the
    source-controller's bf has no colored permanents (only
    colorless), the union is empty → defensive fallback mints one
    {C} colorless coin. Mirrors Python's
    ``if not options: color = "C"`` at ``mana.py:255-256``.
    """
    empty_state.register_and_inject_object(
        {
            "name": "Synthetic Colorless Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
        },
        0,
        ZONE_BATTLEFIELD,
    )
    crater_id = empty_state.register_and_inject_object(
        _meteor_crater_dict(), 0, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(crater_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })
    pool = empty_state.get_mana_pool(0)
    assert pool == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "any": 0}


def test_resolve_color_union_scopes_to_source_controllers_bf(empty_state):
    """**Color union scoping pin.** The color union iterates ONLY the
    source-controller's battlefield — NOT both players' bfs. Mirrors
    Python's ``if o.controller_id != controller_id: continue`` at
    ``mana.py:251-253``.
    """
    # p0 controls a green creature (should be IGNORED — not source-
    # controller).
    empty_state.register_and_inject_object(
        _mono_colored_creature_dict("G"), 0, ZONE_BATTLEFIELD,
    )
    # p1 controls a red creature + the Meteor Crater.
    empty_state.register_and_inject_object(
        _mono_colored_creature_dict("R"), 1, ZONE_BATTLEFIELD,
    )
    crater_id = empty_state.register_and_inject_object(
        _meteor_crater_dict(), 1, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(crater_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": crater_id,
        "ability_index": 0,
    })
    # p1's union = {'R'} → R; p0 stays empty.
    assert empty_state.get_mana_pool(1) == {
        "W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "any": 0,
    }
    assert empty_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
    }
