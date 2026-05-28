"""Rust-engine unit pins for the
``Effect::AddOneManaFromControlledLandsProductions`` parse + to_pydict +
resolve arms.

**Reflecting Pool substrate Phase 4 Cycle 1 (2026-05-27 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §#2 Reflecting
Pool).** The Rust Effect variant is a unit (no fields); both engines
compute the color-options surface at resolve time from the source-
controller's controlled Lands' ``mana_produced`` symbols. Rust's no-
agent fallback picks the canonical-first WUBRG-then-C-ordered color;
the empty-union defensive fallback mints a colorless ``{C}`` coin.

These pins drive the new resolve arm DIRECTLY via the
``apply_action({"kind": "activate_ability", ...})`` path on synthetic
Reflecting-Pool-shape Lands. The cross-engine bridge round-trip + the
Python admit-gate substrate-only invariant are covered by the sibling
test at ``tests/test_reflecting_pool_substrate_cycle_1.py``; this
module pins the Rust-engine-side resolve semantics that the bridge
relies on.

Covered:

  - parse_effect arm accepts the 1-key dict shape.
  - Resolve picks W when only a Plains-shape Land is on the source-
    controller's bf.
  - Resolve picks canonical-first WUBRG from a multi-color Land
    union (sibling of the bigger pin in the Python-side test file).
  - Resolve falls back to {C} when the union is empty (no Lands or
    Lands with no ``mana_produced`` — defensive fallback mirrors
    Python's ``if not options: color = "C"`` at
    ``mana.py:204-205``).
  - Color union scopes to source-controller's bf (NOT both
    players').
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2


def _reflecting_pool_dict():
    """Synthetic Reflecting-Pool-shape Land printing dict."""
    return {
        "name": "Synthetic Reflecting Pool",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "add_one_mana_from_controlled_lands_productions",
                },
                "is_mana_ability": True,
            },
        ],
    }


def _land_dict(name: str, produces: list[str]):
    """Mono-color Land with explicit ``mana_produced`` list."""
    return {
        "name": name,
        "card_types": ["Land"],
        "mana_produced": produces,
    }


@pytest.fixture
def empty_state(engine):
    """Empty 0/0/0 synthetic state — Reflecting Pool's resolve scans
    the bf for produces-union derivation, so a pre-seeded bf would
    inject spurious produces."""
    return engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# parse_effect + to_pydict pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new
    ``add_one_mana_from_controlled_lands_productions`` parse arm
    consumes the 1-key dict shape and registers cleanly.
    """
    pid = empty_registry.register_printing(_reflecting_pool_dict())
    assert empty_registry.get_printing_name(pid) == "Synthetic Reflecting Pool"


# ---------------------------------------------------------------------------
# Resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_picks_w_with_only_white_land(empty_state):
    """**Resolve arm pin — single-color Land union.** When the
    source-controller's bf has only a Plains-shape (W-producing)
    Land, the produces union is {"W"} and the canonical-first pick
    is W → 1 W coin minted.
    """
    empty_state.register_and_inject_object(
        _land_dict("Synth Plains", ["W"]), 0, ZONE_BATTLEFIELD,
    )
    pool_id = empty_state.register_and_inject_object(
        _reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(pool_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    pool = empty_state.get_mana_pool(0)
    assert pool == {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}


def test_resolve_picks_canonical_first_u_when_u_g_r_union(empty_state):
    """**Resolve arm pin — multi-color Land union, canonical-first
    WUBRG.** Union of {"U","G","R"} → canonical-first WUBRG-ordered
    pick = U. The sorted-alphabetic pick would be G; this divergence
    is INTENTIONAL per the user spec (match the sibling Meteor
    Crater C1 + Phase-4E `any` code-path's canonical-first
    precedent at `daecd399`).
    """
    for name, color in (
        ("Synth Island", "U"),
        ("Synth Forest", "G"),
        ("Synth Mountain", "R"),
    ):
        empty_state.register_and_inject_object(
            _land_dict(name, [color]), 0, ZONE_BATTLEFIELD,
        )
    pool_id = empty_state.register_and_inject_object(
        _reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(pool_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    pool = empty_state.get_mana_pool(0)
    assert pool == {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0}


def test_resolve_empty_union_mints_c_fallback(empty_state):
    """**Resolve arm pin — defensive colorless fallback.** When the
    source-controller's bf has only non-Land permanents (or only the
    Reflecting Pool itself which has no ``mana_produced``), the
    union is empty → defensive fallback mints one {C} colorless
    coin. Mirrors Python's ``if not options: color = "C"`` at
    ``mana.py:204-205``.
    """
    # Inject a creature (non-Land — Land filter rejects it).
    empty_state.register_and_inject_object(
        {
            "name": "Synth Bear",
            "card_types": ["Creature"],
            "mana_cost": {"G": 1, "generic": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_BATTLEFIELD,
    )
    pool_id = empty_state.register_and_inject_object(
        _reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(pool_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    pool = empty_state.get_mana_pool(0)
    assert pool == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "any": 0}


def test_resolve_produces_union_scopes_to_source_controllers_bf(empty_state):
    """**Produces-union scoping pin.** The produces union iterates
    ONLY the source-controller's battlefield — NOT both players'
    bfs. Mirrors Python's
    ``if o.controller_id != controller_id: continue`` at
    ``mana.py:198-200``.
    """
    # p0 controls a Synth Forest (G-producing; should be IGNORED).
    empty_state.register_and_inject_object(
        _land_dict("Synth Forest", ["G"]), 0, ZONE_BATTLEFIELD,
    )
    # p1 controls a Synth Mountain (R) + the Reflecting Pool.
    empty_state.register_and_inject_object(
        _land_dict("Synth Mountain", ["R"]), 1, ZONE_BATTLEFIELD,
    )
    pool_id = empty_state.register_and_inject_object(
        _reflecting_pool_dict(), 1, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(pool_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    # p1's union = {'R'} → R; p0 stays empty.
    assert empty_state.get_mana_pool(1) == {
        "W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "any": 0,
    }
    assert empty_state.get_mana_pool(0) == {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
    }


def test_resolve_prefers_colored_over_c_in_dual_produces(empty_state):
    """**Resolve arm pin — colored precedence over C.** Mirrors the
    real-EoE Grove-of-the-Burnwillows shape (``produces={G, C, R}``):
    when the union contains both colored slots AND ``C``, the
    canonical pick W → U → B → R → G → C prefers colored. Setup:
    one Land producing ``{R, C}`` → union = {R, C}; canonical pick
    = R, NOT C.
    """
    empty_state.register_and_inject_object(
        _land_dict("Synth Dual RC", ["R", "C"]), 0, ZONE_BATTLEFIELD,
    )
    pool_id = empty_state.register_and_inject_object(
        _reflecting_pool_dict(), 0, ZONE_BATTLEFIELD,
    )
    empty_state.force_set_summoning_sick(pool_id, False)
    empty_state.apply_action({
        "kind": "activate_ability",
        "source_id": pool_id,
        "ability_index": 0,
    })
    pool = empty_state.get_mana_pool(0)
    assert pool == {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "any": 0}
