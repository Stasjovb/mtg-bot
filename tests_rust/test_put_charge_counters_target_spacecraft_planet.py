"""Rust-engine unit pins for the
``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`` resolve arm.

**ModalChooseOne envelope — Cycle 6 (Drill Too Deep closure,
2026-05-21).** Drill Too Deep's mode 0 ("Put five charge counters on
target Spacecraft or Planet you control"). The other mode is the
already-shipped ``DestroyTargetArtifact``; the per-mode target-binding
detector table extension in ``state_ops_cast.rs::cast_spell_noncreature``
seats the bound target id at cast time.

These pins drive the new resolve arm DIRECTLY via
``push_to_stack`` + ``resolve_top_of_stack`` (the synthetic-test path
with no payload-target seat — the resolve arm's None-payload
deterministic-first fallback kicks in). The cast-resolve cross-engine
parity is covered by the spell-card-bridge admit-set tests; this
module pins the leaf semantics that the bridge round-trip relies on.

Covered:
- Charge counters accumulate on a Spacecraft the source-controller
  controls (happy path).
- Charge counters accumulate on a Planet (Land-subtype) the source-
  controller controls — the "Planet half" of the OR filter.
- Silent fizzle when the source-controller controls neither.
- Silent fizzle when only an OPPONENT controls a Spacecraft (the
  "you control" filter teeth).
- amount=0 is a legitimate no-op (mirrors PutChargeCountersOnSelf).
- amount<0 raises at resolve (defense-in-depth on top of the parse-
  time reject).
"""

from __future__ import annotations

import pytest


ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _drill_too_deep_mode0_dict(amount: int = 5):
    """Drill Too Deep's mode-0 spell-only printing — the
    ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`` effect
    in isolation. Avoids the modal wrapper so this module pins ONLY
    the leaf semantics; the modal cast-time binding has its own
    cycle-5/6 tests."""
    return {
        "name": "Test Charge-Spacecraft-or-Planet",
        "card_types": ["Instant"],
        "mana_cost": {"R": 1, "generic": 1},
        "effects": [
            {
                "kind": (
                    "put_charge_counters_on_target_spacecraft_or_"
                    "planet_you_control"
                ),
                "amount": amount,
            }
        ],
    }


def _spacecraft_dict(name="Test Spacecraft"):
    """Vanilla Artifact - Spacecraft printing (subtype on Artifact)."""
    return {
        "name": name,
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 2},
        "effects": [],
    }


def _planet_land_dict(name="Test Planet"):
    """Vanilla Land - Planet printing (subtype on Land)."""
    return {
        "name": name,
        "card_types": ["Land"],
        "subtypes": ["Planet"],
        "effects": [],
    }


def _vanilla_2_2_creature_dict():
    """A creature that is NEITHER a Spacecraft NOR a Planet — should
    never qualify."""
    return {
        "name": "Test Vanilla 2/2",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "effects": [],
    }


def test_resolve_charges_owned_spacecraft(engine):
    """Happy path — controller's Spacecraft gets +N charge counters.
    No payload-target seat in the synthetic push path, so the resolve
    arm falls back to the deterministic-first Spacecraft-or-Planet
    permanent the source-controller controls."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1,
    )
    ship_id = state.register_and_inject_object(
        _spacecraft_dict(), 0, ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _drill_too_deep_mode0_dict(amount=5), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    assert state.get_charge_counters(ship_id) == 5


def test_resolve_charges_owned_planet_land(engine):
    """Planet half of the OR filter — Planet is a Land subtype; a
    Land - Planet the source-controller controls qualifies."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1,
    )
    planet_id = state.register_and_inject_object(
        _planet_land_dict(), 0, ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _drill_too_deep_mode0_dict(amount=3), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    assert state.get_charge_counters(planet_id) == 3


def test_resolve_fizzles_on_opponent_only_spacecraft(engine):
    """The "you control" filter teeth — an OPPONENT's Spacecraft is
    NOT a legal target; the source-controller scan returns None and
    the resolve arm silently fizzles."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1,
    )
    opp_ship_id = state.register_and_inject_object(
        _spacecraft_dict(name="Opp Ship"), 1, ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _drill_too_deep_mode0_dict(amount=5), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    # Opponent's ship UN-touched (cross-controller "you control" teeth).
    assert state.get_charge_counters(opp_ship_id) == 0


def test_resolve_fizzles_when_only_non_qualifying_permanents(engine):
    """A creature isn't a Spacecraft and isn't a Planet — the scan
    returns None and the resolve arm fizzles silently."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1,
    )
    bear_id = state.register_and_inject_object(
        _vanilla_2_2_creature_dict(), 0, ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _drill_too_deep_mode0_dict(amount=5), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    # Bear must NOT accumulate charge counters (it doesn't qualify).
    assert state.get_charge_counters(bear_id) == 0


def test_resolve_amount_zero_is_no_op(engine):
    """amount=0 is a legitimate no-op (mirrors PutChargeCountersOnSelf's
    `amount=0` early-return). The target's `charge_counters` field
    must remain at its prior value."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=1,
    )
    ship_id = state.register_and_inject_object(
        _spacecraft_dict(), 0, ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _drill_too_deep_mode0_dict(amount=0), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    assert state.get_charge_counters(ship_id) == 0


def test_register_negative_amount_raises(empty_registry):
    """Defense-in-depth — the parser arm raises at register time on a
    negative `amount`. Mirrors the `exile_all_artifacts_with_mana_value_
    at_most` / `damage_each_opponent` raise-on-negative shape."""
    with pytest.raises(ValueError, match="non-negative"):
        empty_registry.register_printing(
            _drill_too_deep_mode0_dict(amount=-1)
        )


def test_to_pydict_round_trip(empty_registry):
    """Parse → store → read-back must preserve the `amount` field
    (the to_pydict arm). Mirrors the
    `exile_all_artifacts_with_mana_value_at_most` round-trip pin."""
    pid = empty_registry.register_printing(
        _drill_too_deep_mode0_dict(amount=5)
    )
    effs = empty_registry.get_printing_effects(pid)
    assert len(effs) == 1
    assert effs[0]["kind"] == (
        "put_charge_counters_on_target_spacecraft_or_planet_you_control"
    )
    assert effs[0]["amount"] == 5
