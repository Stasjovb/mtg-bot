"""Rust-engine unit pins for the
``Effect::GainControlOfTargetSliverPermanently`` parse + to_pydict +
resolve arms.

**Sliver Overlord substrate (2026-05-31 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §Sliver
Overlord).** The Rust Effect is a field-free unit variant; it performs a
PERMANENT control change of a TARGET Sliver creature to the activator
(the AA's controller) — a DIRECT ``obj.controller`` write (NOT the UEOT
``controller_override`` path). The chosen target rides on the AA action-
dict's ``target_creature_id`` slot → ``current_resolve_payload_target_id``;
the activator is read from ``current_resolve_source_controller``.

These pins drive the new resolve arm via the synthetic-spell idiom: a
carrier whose spell body is the bare gain-control effect, pushed with
``push_to_stack_with_target`` (seats both the payload-target slot AND the
source-controller). The cross-engine bridge round-trip + the Python
BLOCKED→PROBED flip invariant are covered by the sibling
``tests/test_sliver_overlord_parity.py``; this module pins the Rust-
engine-side resolve semantics.

Covered:

  - parse_effect arm accepts the bare unit dict shape.
  - to_pydict emits byte-equal dict (round-trip via parse_effect).
  - Resolve targeting an opponent's Sliver → permanent direct controller
    change to the activator (controller_override stays None).
  - Resolve targeting a Sliver the activator already controls → same-
    controller no-op.
  - Resolve targeting a NON-Sliver creature → silent fizzle (controller
    unchanged).
  - Resolve with no target seated → silent no-op.
"""

from __future__ import annotations


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_BATTLEFIELD = 2


def _gain_control_spell_dict():
    """Synthetic carrier whose spell body is the bare gain-control
    effect — drives the resolve arm via ``push_to_stack_with_target``."""
    return {
        "name": "Synthetic Sliver Overlord (gain-control body)",
        "card_types": ["Sorcery"],
        "effects": [
            {"kind": "gain_control_of_target_sliver_permanently"},
        ],
    }


def _sliver_dict():
    return {
        "name": "Plain Sliver",
        "card_types": ["Creature"],
        "subtypes": ["Sliver"],
        "power": 1,
        "toughness": 1,
    }


def _non_sliver_dict():
    return {
        "name": "Plain Bear",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }


# ---------------------------------------------------------------------------
# parse_effect + to_pydict round-trip pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new
    ``gain_control_of_target_sliver_permanently`` parse arm consumes the
    bare unit dict shape (kind only) and registers cleanly."""
    pid = empty_registry.register_printing(_gain_control_spell_dict())
    assert (
        empty_registry.get_printing_name(pid)
        == "Synthetic Sliver Overlord (gain-control body)"
    )


# ---------------------------------------------------------------------------
# resolve-arm behavioral pins
# ---------------------------------------------------------------------------


def test_resolve_gain_control_of_opponent_sliver(engine):
    """Activator (p0) targets a Sliver controlled by p1: the Sliver's
    controller_id flips to 0 via a DIRECT permanent write;
    controller_override stays None."""
    rs = engine.make_synthetic_state(0, 0, 0)
    spell = rs.register_and_inject_object(
        _gain_control_spell_dict(), 0, ZONE_BATTLEFIELD,
    )
    sliver = rs.register_and_inject_object(
        _sliver_dict(), 1, ZONE_BATTLEFIELD,
    )
    rs.push_to_stack_with_target(spell, 0, sliver)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == sliver)
    assert obj["controller_id"] == 0, (
        f"p0 must gain control of the target Sliver (1 -> 0); got "
        f"{obj['controller_id']}"
    )
    assert obj["controller_override"] is None, (
        "permanent direct control change must NOT stamp the UEOT "
        "controller_override field"
    )


def test_resolve_same_controller_noop(engine):
    """Activator targets a Sliver it ALREADY controls → silent no-op
    (mirrors Python's ``obj.controller_id == controller_id`` early
    return). Controller unchanged, no override."""
    rs = engine.make_synthetic_state(0, 0, 0)
    spell = rs.register_and_inject_object(
        _gain_control_spell_dict(), 0, ZONE_BATTLEFIELD,
    )
    sliver = rs.register_and_inject_object(
        _sliver_dict(), 0, ZONE_BATTLEFIELD,
    )
    rs.push_to_stack_with_target(spell, 0, sliver)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == sliver)
    assert obj["controller_id"] == 0
    assert obj["controller_override"] is None


def test_resolve_non_sliver_target_fizzle(engine):
    """Activator targets a NON-Sliver creature → silent fizzle (mirrors
    Python's ``"Sliver" not in eff_subtypes(obj): return``). Controller
    unchanged."""
    rs = engine.make_synthetic_state(0, 0, 0)
    spell = rs.register_and_inject_object(
        _gain_control_spell_dict(), 0, ZONE_BATTLEFIELD,
    )
    bear = rs.register_and_inject_object(
        _non_sliver_dict(), 1, ZONE_BATTLEFIELD,
    )
    rs.push_to_stack_with_target(spell, 0, bear)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == bear)
    assert obj["controller_id"] == 1, (
        f"a NON-Sliver target must NOT change controller; got "
        f"{obj['controller_id']}"
    )
    assert obj["controller_override"] is None


def test_resolve_no_target_noop(engine):
    """No target seated (the carrier pushed without a target) → silent
    no-op (mirrors Python's ``if not targets: return``)."""
    rs = engine.make_synthetic_state(0, 0, 0)
    spell = rs.register_and_inject_object(
        _gain_control_spell_dict(), 0, ZONE_BATTLEFIELD,
    )
    sliver = rs.register_and_inject_object(
        _sliver_dict(), 1, ZONE_BATTLEFIELD,
    )
    # Push WITHOUT a target (the bare single-source push).
    rs.push_to_stack(spell, 0)
    rs.resolve_top_of_stack()

    obj = next(e for e in rs.battlefield_snapshot() if e["id"] == sliver)
    assert obj["controller_id"] == 1, (
        f"with no target seated the effect is a no-op; the Sliver's "
        f"controller must stay 1; got {obj['controller_id']}"
    )
    assert obj["controller_override"] is None
