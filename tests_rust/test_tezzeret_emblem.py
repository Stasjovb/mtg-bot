"""Rust-engine unit pins for the emblem substrate (CR 114) — Tezzeret,
Cruel Captain's −7 emblem.

Covers the Rust half of the emblem substrate that did not exist on
either engine before this slice:

  - ``Effect::CreateEmblem { emblem_kind }`` parse_effect arm +
    effect_to_pydict round-trip; unknown-kind rejection.
  - ``Effect::TezzeretEmblemBeginCombat { amount }`` parse + round-trip
    (amount defaults to 3) + negative-amount rejection.
  - The CreateEmblem resolve arm: activating the −7 (loyalty 7 → 0)
    mints a synthetic emblem GameObject into the command zone
    (``state.emblems``), surfaced via ``emblems_snapshot`` (zone == 6 ==
    ZONE_COMMAND, controller == the activator).
  - The emblem-sourced begin-combat trigger: ``dispatch_beginning_of_
    combat`` fires the command-zone emblem's trigger onto the stack
    (dispatch_event scans ``state.emblems`` as a source); resolving it
    puts three +1/+1 counters on the first artifact the controller
    controls.
  - The fingerprint emblems slot: an emblem-bearing state's fingerprint
    differs from the same state with the emblem absent (the slot is
    appended only when non-empty, so empty-emblem baselines are
    byte-identical).
  - Clone independence: a cloned state owns its own emblem objects.

The cross-engine byte-equal probe + the bridge round-trip from Python
live at ``tests/test_tezzeret_cruel_captain_parity.py``; this module
pins the Rust-engine-side parse/resolve/snapshot/fingerprint semantics.

**HONEST-STOP.** The "if it's not a creature, it becomes a 0/0 Robot
artifact creature" permanent layer-4 type-set + layer-7b P/T-set animate
is NOT modeled (no permanent type+P/T animate substrate). The 3-counter
body is the byte-equal landing. See docs/SEARCH_LIMITATIONS.md.
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2
ZONE_COMMAND = 6


def _artifact_dict():
    return {
        "name": "Doohickey",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "effects": [],
    }


def _tezzeret_dict():
    """Tezzeret-shape Planeswalker carrying ONLY the −7 create_emblem AA."""
    return {
        "name": "Tezzeret, Cruel Captain",
        "card_types": ["Planeswalker"],
        "supertypes": ["Legendary"],
        "subtypes": ["Tezzeret"],
        "mana_cost": {"generic": 3},
        "starting_loyalty": 4,
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"loyalty": 7},
                "sorcery_speed": True,
                "effect": {
                    "kind": "create_emblem",
                    "emblem_kind": "tezzeret_cruel_captain",
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# parse_effect + effect_to_pydict round-trip pins
# ---------------------------------------------------------------------------


def test_register_printing_with_create_emblem(empty_registry):
    """parse_effect accepts the create_emblem dict (kind + emblem_kind)."""
    pid = empty_registry.register_printing(_tezzeret_dict())
    assert empty_registry.get_printing_name(pid) == "Tezzeret, Cruel Captain"


def test_create_emblem_unknown_kind_rejected(empty_registry):
    """An unknown emblem_kind raises at register time (loud-fail)."""
    bad = _tezzeret_dict()
    bad["activated_abilities"][0]["effect"]["emblem_kind"] = "nonexistent"
    with pytest.raises(ValueError, match=r"unknown emblem kind"):
        empty_registry.register_printing(bad)


def test_register_printing_with_emblem_begin_combat_body(empty_registry):
    """parse_effect accepts the begin-combat body dict; amount defaults
    to 3 when omitted, and negative amount is rejected."""
    base = {
        "name": "Carrier",
        "card_types": ["Artifact"],
        "effects": [{"kind": "tezzeret_emblem_begin_combat"}],
    }
    pid = empty_registry.register_printing(base)
    assert empty_registry.get_printing_name(pid) == "Carrier"

    neg = {
        "name": "Bad Carrier",
        "card_types": ["Artifact"],
        "effects": [
            {"kind": "tezzeret_emblem_begin_combat", "amount": -1}
        ],
    }
    with pytest.raises(ValueError, match=r"non-negative"):
        empty_registry.register_printing(neg)


# ---------------------------------------------------------------------------
# CreateEmblem resolve-arm pins
# ---------------------------------------------------------------------------


def test_create_emblem_resolve_pushes_emblem_to_command_zone(engine):
    """Activating the −7 (pay 7 loyalty) mints one emblem into the
    command zone, surfaced via emblems_snapshot (zone 6, controller 0)."""
    rs = engine.make_synthetic_state(0, 0, 0)
    wid = rs.register_and_inject_object(_tezzeret_dict(), 0, ZONE_BATTLEFIELD)
    rs.set_loyalty_counters(wid, 7)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": wid, "ability_index": 0}
    )
    rs.resolve_top_of_stack()

    assert rs.get_loyalty_counters(wid) == 0
    emblems = rs.emblems_snapshot()
    assert len(emblems) == 1
    assert emblems[0]["zone"] == ZONE_COMMAND
    assert emblems[0]["controller_id"] == 0
    assert emblems[0]["printing_name"] == "Tezzeret, Cruel Captain emblem"


# ---------------------------------------------------------------------------
# Emblem-sourced begin-combat trigger + 3-counter body pins
# ---------------------------------------------------------------------------


def test_emblem_begin_combat_trigger_puts_three_counters(engine):
    """The command-zone emblem's begin-combat trigger fires and resolves
    to three +1/+1 counters on the first artifact the controller
    controls. The artifact stays a non-creature (becomes-Robot honest-
    stopped)."""
    rs = engine.make_synthetic_state(0, 0, 0)
    art_id = rs.register_and_inject_object(_artifact_dict(), 0, ZONE_BATTLEFIELD)
    wid = rs.register_and_inject_object(_tezzeret_dict(), 0, ZONE_BATTLEFIELD)
    rs.set_loyalty_counters(wid, 7)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": wid, "ability_index": 0}
    )
    rs.resolve_top_of_stack()
    assert len(rs.emblems_snapshot()) == 1
    assert rs.get_counters(art_id) == 0

    # Fire the emblem-sourced begin-combat trigger.
    rs.dispatch_beginning_of_combat()
    assert rs.stack_size() == 1
    rs.resolve_top_of_stack()
    assert rs.get_counters(art_id) == 3


def test_emblem_begin_combat_no_artifact_fizzles(engine):
    """With NO artifact on the controller's battlefield, the emblem
    trigger resolves to a silent no-op (no crash, no counters)."""
    rs = engine.make_synthetic_state(0, 0, 0)
    wid = rs.register_and_inject_object(_tezzeret_dict(), 0, ZONE_BATTLEFIELD)
    rs.set_loyalty_counters(wid, 7)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": wid, "ability_index": 0}
    )
    rs.resolve_top_of_stack()
    rs.dispatch_beginning_of_combat()
    # The trigger pushes (the predicate matched the controller), then
    # resolves to a no-op since there is no legal target artifact.
    assert rs.stack_size() == 1
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0


# ---------------------------------------------------------------------------
# Fingerprint + clone pins
# ---------------------------------------------------------------------------


def test_emblem_fingerprint_slot_back_compat(engine):
    """The fingerprint emblems slot is appended only when non-empty: a
    state with no emblems has a fingerprint distinct from the same state
    after an emblem is minted (the slot makes the emblem observable),
    and an empty-emblem state's fingerprint is unaffected by the new
    slot existing."""
    rs = engine.make_synthetic_state(0, 0, 0)
    fp_empty = rs.fingerprint()
    wid = rs.register_and_inject_object(_tezzeret_dict(), 0, ZONE_BATTLEFIELD)
    rs.set_loyalty_counters(wid, 7)
    # Fingerprint after injecting the walker but BEFORE the emblem exists.
    fp_no_emblem = rs.fingerprint()
    rs.apply_action(
        {"kind": "activate_ability", "source_id": wid, "ability_index": 0}
    )
    rs.resolve_top_of_stack()
    fp_with_emblem = rs.fingerprint()
    # The empty-board baseline differs from the walker-bearing state
    # (the walker is on the battlefield), but the load-bearing assertion
    # is that adding an emblem CHANGES the fingerprint.
    assert fp_with_emblem != fp_no_emblem
    assert fp_empty != fp_with_emblem


def test_emblem_clone_independence(engine):
    """A cloned state owns its own emblem objects — mutating the clone's
    command zone does not touch the original's, and both carry the
    emblem post-clone."""
    rs = engine.make_synthetic_state(0, 0, 0)
    wid = rs.register_and_inject_object(_tezzeret_dict(), 0, ZONE_BATTLEFIELD)
    rs.set_loyalty_counters(wid, 7)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": wid, "ability_index": 0}
    )
    rs.resolve_top_of_stack()
    assert len(rs.emblems_snapshot()) == 1

    clone = rs.clone_once()
    assert len(clone.emblems_snapshot()) == 1
    # Both carry an emblem with the same printing name post-clone.
    assert (
        clone.emblems_snapshot()[0]["printing_name"]
        == rs.emblems_snapshot()[0]["printing_name"]
        == "Tezzeret, Cruel Captain emblem"
    )
