"""Round-29 EoE Void LTB-tracking (production call-site wiring).

The ConditionalIfVoid intervening-if substrate landed in commit
de4a578c with no production call sites flipping
`permanent_left_battlefield_this_turn`. This module pins the follow-
up wiring: the `move_object` primitive is the single chokepoint that
flips the flag whenever a NONLAND permanent moves FROM the
battlefield to any other zone, and the cleanup-step (via
`advance_phase` entry to PHASE_CLEANUP) resets both Void flags so
the next turn starts fresh.

Option A: setter lives in `state_ops_zones.rs::move_object`. Every
effect that ends with a battlefield-exit goes through `move_object`
transitively (destroy / exile / bounce / sacrifice — all of those
arms eventually call `move_object` or use the in-place
`Arc::make_mut`-remove pattern that bypasses move_object; see the
per-test notes below for which path each effect takes).

Mirror of Python's `turn.move_off_battlefield` (turn.py:158-164),
which gates the flag on `not obj.printing.is_land`.

See `docs/RUST_PARITY_GAPS.md` I28 for the lifecycle invariant
(setter site + reset site + consumer + per-state indexing).
"""

from __future__ import annotations

import pytest


# Zone constants — mirror `rust/src/state_ops_zones.rs`.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5

# Phase constants — mirror `rust/src/state_ops_steps.rs`.
PHASE_UNTAP = 0
PHASE_MAIN1 = 3
PHASE_END_STEP = 10
PHASE_CLEANUP = 11


# ---------- Fixtures: printing dicts -----------------------------


def _vanilla_creature_dict(name: str = "Test Bear"):
    """A vanilla 2/2 Creature, for tests that need a non-land
    permanent on the battlefield."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


def _vanilla_land_dict(name: str = "Test Forest"):
    """A vanilla Land — should NOT flip the void flag when it leaves
    the battlefield (CR 110.4 / EoE Void rule mirror gates on
    nonland)."""
    return {
        "name": name,
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "mana_produced": ["G"],
    }


def _murder_creature_dict():
    """Destroy-target instant — uses any_creature filter. In Rust's
    current dispatch this picks defender's bf[0] regardless of
    actual card type (see state_ops_resolve.rs DestroyTarget arm).
    Caller is responsible for arranging bf[0] to be the intended
    target."""
    return {
        "name": "Test Murder",
        "card_types": ["Instant"],
        "mana_cost": {"B": 1, "generic": 2},
        "effects": [
            {
                "kind": "destroy_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _bounce_dict():
    """ReturnToHand spell — picks defender's bf[0]."""
    return {
        "name": "Test Unsummon",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [
            {
                "kind": "return_to_hand",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _exile_dict():
    """ExileTarget spell — picks defender's bf[0]."""
    return {
        "name": "Test Path",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [
            {
                "kind": "exile_target",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _sacrifice_dict():
    """Sacrifice spell — picks active player's own bf[0]."""
    return {
        "name": "Test Altar",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": "sacrifice",
                "target": {"kind": "any_creature"},
            }
        ],
    }


def _conditional_if_void_decode_dict(draw_then: int = 4, draw_else: int = 2):
    """Decode-Transmissions-shape conditional — exact mirror of the
    fixture in tests_rust/test_resolve.py (kept local so this module
    is self-contained)."""
    return {
        "name": "Synthetic Decode (Void)",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 3, "U": 1},
        "effects": [
            {
                "kind": "conditional_if_void",
                "then_effect": {"kind": "draw_cards", "count": draw_then},
                "else_effect": {"kind": "draw_cards", "count": draw_else},
            }
        ],
    }


# ---------- Primitive: move_object FROM battlefield --------------


def test_move_object_creature_from_bf_to_graveyard_flips_flag(engine):
    """Direct primitive — moving a Creature off the battlefield flips
    `permanent_left_battlefield_this_turn` (observable via the
    `is_void_active` getter). Chokepoint test for Option A."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    # p1's battlefield: inject a creature so bf is exactly [creature].
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    assert state.is_void_active is False

    moved = state.move_object(creature_id, ZONE_GRAVEYARD, 1)
    assert moved is True
    # Flag flipped: a nonland permanent left the battlefield.
    # Read via is_void_active (the public getter); only LTB was
    # touched so the read is equivalent to checking the LTB half.
    assert state.is_void_active is True


def test_move_object_land_from_bf_to_graveyard_does_not_flip(engine):
    """Lands are excluded by the gate (mirrors Python's
    `not obj.printing.is_land` filter at turn.py:163). Moving a
    Forest off the battlefield leaves the flag untouched."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    land_id = state.register_and_inject_object(
        _vanilla_land_dict(), 1, ZONE_BATTLEFIELD
    )
    assert state.is_void_active is False

    moved = state.move_object(land_id, ZONE_GRAVEYARD, 1)
    assert moved is True
    # Land — flag stays false.
    assert state.permanent_left_battlefield_this_turn is False
    assert state.is_void_active is False


def test_move_object_from_hand_does_not_flip_flag(engine):
    """Source zone is hand, not battlefield — flag must not flip.
    The gate is one-directional: only battlefield-exit is
    Void-triggering."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_HAND
    )
    assert state.is_void_active is False

    moved = state.move_object(creature_id, ZONE_GRAVEYARD, 0)
    assert moved is True
    # Source was hand — flag stays false even for a creature.
    assert state.permanent_left_battlefield_this_turn is False


def test_move_object_to_exile_from_bf_flips_flag(engine):
    """Destination is exile (not graveyard) — the gate is on source
    zone, not destination. Flag flips regardless of where the
    nonland permanent goes."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )

    moved = state.move_object(creature_id, ZONE_EXILE, 1)
    assert moved is True
    assert state.permanent_left_battlefield_this_turn is True


def test_move_object_to_hand_from_bf_flips_flag(engine):
    """Bounce destination — same gate as exile/graveyard. Source is
    battlefield, object is nonland → flag flips."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )

    moved = state.move_object(creature_id, ZONE_HAND, 1)
    assert moved is True
    assert state.permanent_left_battlefield_this_turn is True


def test_move_object_flag_is_state_scoped_not_per_player(engine):
    """The flag lives on GameState, not per-Player (matches Python's
    `GameState.permanent_left_battlefield_this_turn`). Both players'
    Void-triggers see the same flag regardless of whose permanent
    left."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    # p0 has a creature, p1 has a creature.
    p0_creature = state.register_and_inject_object(
        _vanilla_creature_dict("p0 bear"), 0, ZONE_BATTLEFIELD
    )
    p1_creature = state.register_and_inject_object(
        _vanilla_creature_dict("p1 bear"), 1, ZONE_BATTLEFIELD
    )
    assert state.is_void_active is False

    # Destroy only p0's creature.
    state.move_object(p0_creature, ZONE_GRAVEYARD, 0)
    # The single flag is now true — visible to every Void consumer.
    assert state.permanent_left_battlefield_this_turn is True
    assert state.is_void_active is True

    # p1's creature still on bf, unrelated.
    assert state.find_object_zone(p1_creature) == ZONE_BATTLEFIELD


def test_move_object_missing_id_does_not_flip_flag(engine):
    """A no-op move (id not in any zone) returns false and does NOT
    flip the flag — the gate is gated on the find-and-remove
    succeeding from the battlefield branch."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    moved = state.move_object(999, ZONE_GRAVEYARD, 0)
    assert moved is False
    assert state.permanent_left_battlefield_this_turn is False


# ---------- End-to-end: Effect arms (destroy / exile / bounce / sac) -


def _setup_with_creature_on_p1_bf(engine):
    """Helper — fresh synthetic state with a single Creature on
    p1's battlefield (the dispatchers for DestroyTarget /
    ReturnToHand / ExileTarget pick defender's bf[0])."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=20
    )
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    return state, creature_id


def test_resolve_destroy_target_creature_flips_void_flag(engine):
    """End-to-end: a Murder-shape Effect::DestroyTarget on a creature
    flips the Void flag via the chokepoint primitive. Mirrors the
    Decode-Transmissions / Hymn-of-the-Faller use case at runtime."""
    state, creature_id = _setup_with_creature_on_p1_bf(engine)
    spell_id = state.register_and_inject_object(
        _murder_creature_dict(), 0, ZONE_HAND
    )
    assert state.is_void_active is False

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Creature destroyed → flag flipped.
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    assert state.permanent_left_battlefield_this_turn is True
    assert state.is_void_active is True


def test_resolve_exile_target_creature_flips_void_flag(engine):
    """End-to-end: ExileTarget on a creature flips the flag too —
    the gate fires regardless of destination zone."""
    state, creature_id = _setup_with_creature_on_p1_bf(engine)
    spell_id = state.register_and_inject_object(
        _exile_dict(), 0, ZONE_HAND
    )

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    assert state.find_object_zone(creature_id) == ZONE_EXILE
    assert state.permanent_left_battlefield_this_turn is True


def test_resolve_return_to_hand_creature_flips_void_flag(engine):
    """End-to-end: ReturnToHand (bounce) on a creature flips the
    flag. Bounce is the canonical Decode-Transmissions trigger
    scenario: a spell bounces a creature, then the next spell that
    resolves sees `is_void_active == true` and fires its then-branch."""
    state, creature_id = _setup_with_creature_on_p1_bf(engine)
    spell_id = state.register_and_inject_object(
        _bounce_dict(), 0, ZONE_HAND
    )

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    assert state.find_object_zone(creature_id) == ZONE_HAND
    assert state.permanent_left_battlefield_this_turn is True


def test_resolve_sacrifice_creature_flips_void_flag(engine):
    """End-to-end: Sacrifice picks the ACTIVE player's bf[0]. Setup
    is p0's creature (active player = 0), sacrifice fires, flag
    flips."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=20
    )
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _sacrifice_dict(), 0, ZONE_HAND
    )

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    assert state.permanent_left_battlefield_this_turn is True


def test_resolve_destroy_target_land_does_not_flip_void_flag(engine):
    """Destroying a Land does NOT flip the void flag — gate on
    `not is_land` per Python's `move_off_battlefield`."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=20
    )
    land_id = state.register_and_inject_object(
        _vanilla_land_dict(), 1, ZONE_BATTLEFIELD
    )
    spell_id = state.register_and_inject_object(
        _murder_creature_dict(), 0, ZONE_HAND
    )

    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()

    # Land moved (the dispatcher's any_creature filter is misnamed —
    # it picks bf[0] regardless), but the void gate excluded it.
    assert state.find_object_zone(land_id) == ZONE_GRAVEYARD
    assert state.permanent_left_battlefield_this_turn is False
    assert state.is_void_active is False


# ---------- Reset hook (cleanup step) -----------------------------


def test_advance_phase_into_cleanup_resets_void_flags(engine):
    """The Void flags reset on entry to PHASE_CLEANUP (mirrors
    Python's `run_cleanup_step` at turn.py:1094-1095). Set the
    flag manually, walk into cleanup, verify it's clear."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    state.set_void_flags(permanent_left_battlefield=True, spell_warped=True)
    assert state.is_void_active is True

    # Position one phase before CLEANUP, then advance once.
    state.set_phase(PHASE_END_STEP)
    state.advance_phase()
    assert state.current_phase() == PHASE_CLEANUP

    # Both flags reset.
    assert state.permanent_left_battlefield_this_turn is False
    assert state.spell_warped_this_turn is False
    assert state.is_void_active is False


def test_advance_phase_into_cleanup_resets_via_real_ltb_event(engine):
    """Cleanup reset works even when the flag was set via the real
    production path (move_object from bf, not via set_void_flags).
    End-to-end mirror of the canonical 'kill something this turn,
    flag flips, cleanup wipes it' lifecycle."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    state.move_object(creature_id, ZONE_GRAVEYARD, 1)
    assert state.permanent_left_battlefield_this_turn is True

    state.set_phase(PHASE_END_STEP)
    state.advance_phase()
    assert state.current_phase() == PHASE_CLEANUP
    assert state.permanent_left_battlefield_this_turn is False


def test_void_flag_persists_across_non_cleanup_phase_changes(engine):
    """Mid-turn phase ticks (UNTAP -> UPKEEP, MAIN1 -> COMBAT, etc.)
    do NOT reset the void flags — only CLEANUP entry does. The
    flag's lifetime is the whole turn."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10
    )
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    state.move_object(creature_id, ZONE_GRAVEYARD, 1)
    assert state.permanent_left_battlefield_this_turn is True

    state.set_phase(PHASE_MAIN1)
    state.advance_phase()  # MAIN1 -> BEGIN_COMBAT
    assert state.permanent_left_battlefield_this_turn is True
    state.advance_phase()  # BEGIN_COMBAT -> DECLARE_ATTACKERS
    assert state.permanent_left_battlefield_this_turn is True


# ---------- ConditionalIfVoid integration -------------------------


def test_conditional_if_void_resolves_then_branch_after_production_ltb(engine):
    """End-to-end pin for the deferred-work fix: a Creature is
    destroyed via the production resolve pipeline (no test-only
    `set_void_flags` call), then a ConditionalIfVoid spell resolves
    and sees `is_void_active == true`, firing the then-branch.

    This is the test that was load-bearing for closing the
    'substrate ships but never fires in production' gap that the
    ConditionalIfVoid shipping commit (de4a578c) documented."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=20
    )
    # p1's creature on the battlefield — Murder-target.
    creature_id = state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_BATTLEFIELD
    )
    murder_id = state.register_and_inject_object(
        _murder_creature_dict(), 0, ZONE_HAND
    )
    decode_id = state.register_and_inject_object(
        _conditional_if_void_decode_dict(draw_then=4, draw_else=2),
        0,
        ZONE_HAND,
    )
    p0_lib_before = state.library_sizes[0]
    assert state.is_void_active is False

    # Resolve Murder first — kills the creature, flag flips.
    state.push_to_stack(murder_id, 0)
    state.resolve_top_of_stack()
    assert state.find_object_zone(creature_id) == ZONE_GRAVEYARD
    assert state.is_void_active is True

    # Now resolve Decode — Void is active, then-branch fires
    # (draw 4 instead of draw 2).
    state.push_to_stack(decode_id, 0)
    state.resolve_top_of_stack()
    assert state.library_sizes[0] == p0_lib_before - 4


def test_conditional_if_void_resolves_else_branch_when_only_land_moved(engine):
    """Inverse pin: destroying a Land does NOT flip the flag, so a
    follow-up ConditionalIfVoid spell sees `is_void_active == false`
    and fires the ELSE-branch (draw 2). Pins the `not is_land` gate
    in the production path end-to-end."""
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=20
    )
    land_id = state.register_and_inject_object(
        _vanilla_land_dict(), 1, ZONE_BATTLEFIELD
    )
    murder_id = state.register_and_inject_object(
        _murder_creature_dict(), 0, ZONE_HAND
    )
    decode_id = state.register_and_inject_object(
        _conditional_if_void_decode_dict(draw_then=4, draw_else=2),
        0,
        ZONE_HAND,
    )
    p0_lib_before = state.library_sizes[0]

    state.push_to_stack(murder_id, 0)
    state.resolve_top_of_stack()
    # Land moved off bf, but the gate filtered it.
    assert state.find_object_zone(land_id) == ZONE_GRAVEYARD
    assert state.is_void_active is False

    state.push_to_stack(decode_id, 0)
    state.resolve_top_of_stack()
    # Else-branch fired: drew 2 (not 4).
    assert state.library_sizes[0] == p0_lib_before - 2
