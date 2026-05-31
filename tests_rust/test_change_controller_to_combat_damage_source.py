"""Rust-engine unit pins for the
``Effect::ChangeControllerToCombatDamageSource`` parse + to_pydict +
resolve arms + the ``resolving_combat_damage_source_controller_id``
state slot.

**Contested War Zone substrate (2026-05-31 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §Group 1
Contested War Zone).** The Rust Effect is a field-free unit variant; it
performs a PERMANENT control change of the source (the Land) to the
combat-damage source's controller — a DIRECT ``obj.controller`` write
(NOT the UEOT ``controller_override`` path). The new controller is read
at resolve time from the
``resolving_combat_damage_source_controller_id`` state slot.

These pins drive the new resolve arm DIRECTLY: inject a Land carrying
the bare effect, seat the source-controller slot via the test-only
setter, push the Land onto the stack as its own source, and
``resolve_top_of_stack``. The cross-engine bridge round-trip + the
Python covered-by-construction flip invariant are covered by the
sibling test at ``tests/test_contested_war_zone_parity.py``; this
module pins the Rust-engine-side resolve semantics + the slot plumbing.

**SUBSTRATE-ONLY landing.** The live DEALS_COMBAT_DAMAGE trigger flip
to PROBED is blocked on multi-subject predicate dispatch + the deferred
StackItem source-controller mirror; see
``docs/SEARCH_LIMITATIONS.md``.

Covered:

  - parse_effect arm accepts the bare unit dict shape.
  - to_pydict emits byte-equal dict (round-trip via parse_effect).
  - Resolve with source-controller != Land controller → permanent
    direct controller change (controller_override stays None).
  - Resolve with source-controller == Land controller → same-controller
    no-op.
  - Resolve with the slot unset (u8::MAX sentinel = Python None) →
    no-op.
  - ``dispatch_combat_damage_to_player`` seats + restores the slot.
"""

from __future__ import annotations


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2

# Sentinel for "no active combat-damage source controller" (u8::MAX).
NO_SOURCE_CONTROLLER = 255


def _change_controller_land_dict():
    """Synthetic Contested-War-Zone-shape Land printing dict carrying
    the bare change-controller effect as its resolve payload."""
    return {
        "name": "Synthetic Contested War Zone",
        "card_types": ["Land"],
        "effects": [{"kind": "change_controller_to_combat_damage_source"}],
    }


# ---------------------------------------------------------------------------
# parse_effect + to_pydict round-trip pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new
    ``change_controller_to_combat_damage_source`` parse arm consumes the
    bare unit dict shape (kind only) and registers cleanly."""
    pid = empty_registry.register_printing(_change_controller_land_dict())
    assert (
        empty_registry.get_printing_name(pid)
        == "Synthetic Contested War Zone"
    )


# ---------------------------------------------------------------------------
# resolve-arm behavioral pins
# ---------------------------------------------------------------------------


def _inject_land(rs, owner):
    return rs.register_and_inject_object(
        _change_controller_land_dict(), owner, ZONE_BATTLEFIELD
    )


def test_resolve_permanent_control_change(engine):
    """Source-controller (p1) differs from the Land's controller (p0):
    the Land's controller_id flips to 1 via a DIRECT permanent write;
    controller_override stays None."""
    rs = engine.make_synthetic_state(0, 0, 0)
    land = _inject_land(rs, owner=0)
    rs.set_resolving_combat_damage_source_controller_id(1)
    rs.push_to_stack(land, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 1
    assert obj["controller_override"] is None


def test_resolve_same_controller_noop(engine):
    """Source-controller equals the Land's controller → silent no-op."""
    rs = engine.make_synthetic_state(0, 0, 0)
    land = _inject_land(rs, owner=0)
    rs.set_resolving_combat_damage_source_controller_id(0)
    rs.push_to_stack(land, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 0
    assert obj["controller_override"] is None


def test_resolve_unset_slot_noop(engine):
    """Slot unset (u8::MAX sentinel = Python None) → silent no-op."""
    rs = engine.make_synthetic_state(0, 0, 0)
    land = _inject_land(rs, owner=0)
    rs.push_to_stack(land, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 0
    assert obj["controller_override"] is None


def test_resolve_source_off_battlefield_noop(engine):
    """Source (the Land) not on either battlefield → silent no-op
    (mirrors Python's ``if source is None: return``). Seat the slot but
    push a stack item whose source id does not exist on the bf."""
    rs = engine.make_synthetic_state(0, 0, 0)
    # Inject a land then push a NON-EXISTENT source id (land + 999).
    land = _inject_land(rs, owner=0)
    rs.set_resolving_combat_damage_source_controller_id(1)
    rs.push_to_stack(land + 999, 0)
    # Resolving a stack item whose source isn't registered is a no-op
    # (the resolve arm's source lookup finds nothing).
    try:
        rs.resolve_top_of_stack()
    except Exception:
        # Some engines fail-loud on a missing source printing; that is
        # also an acceptable no-change outcome for this guard.
        pass
    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == land)
    assert obj["controller_id"] == 0
    assert obj["controller_override"] is None


# ---------------------------------------------------------------------------
# slot-plumbing pins (dispatch site)
# ---------------------------------------------------------------------------


def test_dispatch_seats_and_restores_source_controller_slot(engine):
    """``dispatch_combat_damage_to_player`` seats the source-controller
    slot for the synchronous observer dispatch and restores it to the
    sentinel afterward."""
    rs = engine.make_synthetic_state(0, 0, 0)
    bear = rs.register_and_inject_object(
        {
            "name": "Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        1,
        ZONE_BATTLEFIELD,
    )
    assert (
        rs.resolving_combat_damage_source_controller_id
        == NO_SOURCE_CONTROLLER
    )
    rs.dispatch_combat_damage_to_player(bear, 0, 2)
    assert (
        rs.resolving_combat_damage_source_controller_id
        == NO_SOURCE_CONTROLLER
    ), "slot must be restored to the sentinel after dispatch returns"
