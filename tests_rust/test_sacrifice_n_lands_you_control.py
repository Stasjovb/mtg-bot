"""Rust-engine unit pins for the ``Effect::SacrificeNLandsYouControl``
parse + to_pydict + resolve arms.

**Lotus Field substrate (2026-05-31 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §Lotus Field).**
The Rust Effect variant carries one field (``count: i32``); the
source-controller sacrifices ``count`` LANDS they control, excluding
the source. Mirrors Python's ``SacrificeNLandsYouControl(count: int =
2)`` at ``effects/generic/zone_moves.py:220`` — Lotus Field's "When
Lotus Field enters, sacrifice two lands." ETB trigger.

The resolve arm walks a ``while remaining > 0`` loop that rescans the
controller's battlefield each iteration for the smallest-index LAND
whose id != source_obj_id, picks it (the no-agent deterministic
shortcut, mirroring Python's ``options[0]``), and routes it to the
controller's graveyard. The loop breaks early when no eligible land
remains (Python's ``if not options: break``), so it sacrifices
``min(count, eligible_lands)`` lands.

These pins drive the new resolve arm DIRECTLY via the
``apply_action({"kind": "activate_ability", ...})`` path on a synthetic
Land whose AA effect is the bare ``sacrifice_n_lands_you_control``
leaf (the ETB-effect resolve dispatch is the same ``apply_effect`` path
regardless of whether the effect rode a trigger or an AA). This module
pins the Rust-engine-side resolve semantics that the cross-engine
bridge relies on. The cross-engine bridge round-trip is covered by the
sibling probe at ``tests/test_lotus_field_parity.py``.

Covered:

  - parse_effect arm accepts the 2-key dict shape (kind + count).
  - parse_effect rejects a negative count at register time.
  - to_pydict round-trips the 2-key dict shape.
  - Resolve: sacrifices ``count`` non-source lands from the source-
    controller's battlefield; the source land is NOT sacrificed.
  - Resolve under-count: fewer eligible lands than ``count`` sacrifices
    all available and stops (no error).
  - Source-controller scoping: sacrifices the SOURCE's controller's
    lands, not active_player's.
  - count=0 is a legal no-op.
  - Non-land permanents on the controller's battlefield are NOT
    sacrificed (the is_land filter bites).
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2


def _saccer_dict(count: int = 2):
    """Synthetic Lotus-Field-ETB-shape Land printing dict — the bare
    ``sacrifice_n_lands_you_control`` leaf wired as a mana-ability AA so
    the test can drive it via ``apply_action(activate_ability)``.
    """
    return {
        "name": "Synthetic Saccer",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "sacrifice_n_lands_you_control",
                    "count": count,
                },
                "is_mana_ability": True,
            },
        ],
    }


def _plain_land():
    """A vanilla mana land to populate the sacrifice candidate set."""
    return {
        "name": "Plain Land",
        "card_types": ["Land"],
        "mana_produced": ["G"],
    }


def _plain_creature():
    """A vanilla creature — NOT a land, so the is_land filter must skip
    it.
    """
    return {
        "name": "Plain Creature",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }


def _gy_names_for(state, player_id: int):
    """Graveyard printing-names for a given player (``graveyard_snapshot``
    takes a player_id and returns that player's graveyard directly).
    """
    return sorted(
        o["printing_name"] for o in state.graveyard_snapshot(player_id)
    )


def _bf_count_for(state, controller_id: int) -> int:
    return sum(
        1
        for o in state.battlefield_snapshot()
        if o["controller_id"] == controller_id
    )


# ---------------------------------------------------------------------------
# parse_effect + register + to_pydict pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new
    ``sacrifice_n_lands_you_control`` parse arm consumes the 2-key dict
    shape (kind + count) and registers cleanly.
    """
    pid = empty_registry.register_printing(_saccer_dict(2))
    assert empty_registry.get_printing_name(pid) == "Synthetic Saccer"


def test_register_rejects_negative_count(empty_registry):
    """**parse_effect arm pin — raise-on-negative.** A negative count is
    schema nonsense ("sacrifice -1 lands"); the parse arm rejects it at
    register time (defense-in-depth; the resolve arm re-checks).
    """
    with pytest.raises(Exception):
        empty_registry.register_printing(_saccer_dict(-1))


def test_register_alt_count(empty_registry):
    """**parse_effect arm pin — parameterized count.** A count != the
    Python default (2) registers cleanly.
    """
    pid = empty_registry.register_printing(_saccer_dict(3))
    assert empty_registry.get_printing_name(pid) == "Synthetic Saccer"


# ---------------------------------------------------------------------------
# Resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_sacrifices_two_non_source_lands(engine):
    """**Resolve arm pin — default Lotus Field scenario.** Source-
    controller p0 has 3 plain lands + the source on the battlefield;
    activating the AA sacrifices exactly 2 non-source lands. The source
    land is NOT sacrificed (it survives, tapped from the cost).
    """
    s = engine.make_synthetic_state(0, 0, 0)
    for _ in range(3):
        s.register_and_inject_object(_plain_land(), 0, ZONE_BATTLEFIELD)
    src = s.register_and_inject_object(_saccer_dict(2), 0, ZONE_BATTLEFIELD)
    s.force_set_summoning_sick(src, False)

    assert _bf_count_for(s, 0) == 4  # 3 plain lands + source
    assert _gy_names_for(s, 0) == []

    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })

    # 2 plain lands sacrificed; the source + 1 plain land remain.
    assert _bf_count_for(s, 0) == 2
    assert _gy_names_for(s, 0) == ["Plain Land", "Plain Land"]
    # The source land was NOT sacrificed (still on the battlefield).
    src_on_bf = any(
        o["id"] == src for o in s.battlefield_snapshot()
    )
    assert src_on_bf, "source land must not sacrifice itself"
    # Mana-ability bypass-stack: stack empty post-activation.
    assert s.stack_size() == 0


def test_resolve_under_count_sacrifices_all_available(engine):
    """**Resolve arm pin — under-count.** Source-controller has only 1
    non-source land but ``count=2``; the loop sacrifices the 1 available
    and stops (Python's ``if not options: break``), no error.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_plain_land(), 0, ZONE_BATTLEFIELD)
    src = s.register_and_inject_object(_saccer_dict(2), 0, ZONE_BATTLEFIELD)
    s.force_set_summoning_sick(src, False)

    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })

    # The 1 plain land sacrificed; only the source remains.
    assert _gy_names_for(s, 0) == ["Plain Land"]
    src_on_bf = any(o["id"] == src for o in s.battlefield_snapshot())
    assert src_on_bf


def test_resolve_no_other_lands_is_noop(engine):
    """**Resolve arm pin — zero eligible lands.** Source-controller has
    only the source land; the loop finds no eligible non-source land and
    breaks immediately. Nothing is sacrificed (the source is excluded).
    """
    s = engine.make_synthetic_state(0, 0, 0)
    src = s.register_and_inject_object(_saccer_dict(2), 0, ZONE_BATTLEFIELD)
    s.force_set_summoning_sick(src, False)

    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })

    assert _gy_names_for(s, 0) == []
    src_on_bf = any(o["id"] == src for o in s.battlefield_snapshot())
    assert src_on_bf


def test_resolve_count_zero_is_noop(engine):
    """**Resolve arm pin — count=0 legal no-op.** Mirrors the GainLife /
    EachOpponentLosesLife zero-amount conventions: count=0 sacrifices
    nothing even with eligible lands present.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    for _ in range(2):
        s.register_and_inject_object(_plain_land(), 0, ZONE_BATTLEFIELD)
    src = s.register_and_inject_object(_saccer_dict(0), 0, ZONE_BATTLEFIELD)
    s.force_set_summoning_sick(src, False)

    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })

    assert _gy_names_for(s, 0) == []
    assert _bf_count_for(s, 0) == 3  # 2 plain lands + source untouched


def test_resolve_skips_non_land_permanents(engine):
    """**Resolve arm pin — is_land filter.** A creature on the
    controller's battlefield is NOT a sacrifice candidate; the loop
    skips it and sacrifices the lands. With 1 creature + 1 land +
    source and ``count=2``, only the 1 land is sacrificed.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    s.register_and_inject_object(_plain_creature(), 0, ZONE_BATTLEFIELD)
    s.register_and_inject_object(_plain_land(), 0, ZONE_BATTLEFIELD)
    src = s.register_and_inject_object(_saccer_dict(2), 0, ZONE_BATTLEFIELD)
    s.force_set_summoning_sick(src, False)

    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })

    # Only the land hit the graveyard; the creature survives.
    assert _gy_names_for(s, 0) == ["Plain Land"]
    creature_on_bf = any(
        o["printing_name"] == "Plain Creature"
        for o in s.battlefield_snapshot()
    )
    assert creature_on_bf, "non-land permanent must not be sacrificed"


def test_resolve_source_controller_scoping(engine):
    """**Source-controller fan-out pin.** The source is controlled by
    p1; the sacrificed lands come from p1's battlefield (the SOURCE's
    controller), NOT p0's. p0's lands are untouched.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    # p0's lands — must be untouched.
    for _ in range(2):
        s.register_and_inject_object(_plain_land(), 0, ZONE_BATTLEFIELD)
    # p1's lands + the source (controlled by p1).
    for _ in range(2):
        s.register_and_inject_object(_plain_land(), 1, ZONE_BATTLEFIELD)
    src = s.register_and_inject_object(_saccer_dict(2), 1, ZONE_BATTLEFIELD)
    s.force_set_summoning_sick(src, False)

    s.apply_action({
        "kind": "activate_ability",
        "source_id": src,
        "ability_index": 0,
    })

    # p1 (source-controller) sacrificed both of its plain lands.
    assert _gy_names_for(s, 1) == ["Plain Land", "Plain Land"]
    # p0's lands untouched.
    assert _gy_names_for(s, 0) == []
    assert _bf_count_for(s, 0) == 2
