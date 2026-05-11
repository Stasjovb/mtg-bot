"""Round-27 UEOT framework — per-object expiring-modifier substrate.

Closes parity gap G7 (cleanup step does not run "until end of turn"
effect expiration). Ports the architectural shape of Python's
``mtg_bot.effects.modifiers.LayerPayload`` family
(``PowerToughnessBonus``, ``GrantKeyword``, ``BecomesLandCreature``)
into the Rust GameObject as a per-object
``ueot_modifiers: Vec<UeotModifier>`` stack, plus a CR-514.3 firing
point inside ``cleanup_step_for_active_player`` and the inline mirror
that ``advance_phase`` drives.

Proves the framework with ``Effect::PumpSelfUntilEOT`` — the simplest
of the four top-14 UEOT effects (12 cards in the EoE pool —
Attack-in-the-Box, etc.). The "source gets +P/+T UEOT" shape:

  1. cast/inject a creature with ``effects: [pump_self_until_eot
     power_bonus=N toughness_bonus=M]``;
  2. resolve_top_of_stack -> creature lands on battlefield (CR
     608.2m post-resolve dispatch) AND its own ``effects`` fire,
     pushing a ``PowerToughnessBonus { N, M }`` UEOT modifier on
     the just-landed permanent;
  3. ``effective_power`` / ``effective_toughness`` getters report
     ``printing.power + N`` / ``printing.toughness + M`` (the
     readers walk the modifier Vec on top of printed P/T);
  4. ``cleanup_step_for_active_player`` (or
     ``advance_phase``-through-PHASE_CLEANUP) clears every UEOT
     modifier on every battlefield (CR 514.3) — effective P/T
     returns to base.

The pinned fingerprint baselines are intentionally NOT shifted: UEOT
modifiers are deliberately omitted from the parity-fingerprint
serializer. Rationale (per the brief):

  * UEOT modifiers auto-expire at the next CR 514.3 firing — a
    mid-turn snapshot vs an end-of-turn snapshot would naturally
    diverge in raw modifiers but be parity-equal at gameplay
    boundaries.
  * The 12 pinned baselines in ``RUST_PARITY_GAPS.md`` represent
    "what the cross-engine smoke harness compares"; folding UEOT
    in would shift every baseline and bind us to a Python-side
    serializer shape that hasn't been pinned yet.
  * Effective P/T (with bonus) still surfaces through
    ``effective_power`` / ``effective_toughness`` getters — that's
    the gameplay-load-bearing observable, not the raw modifier list.
"""

from __future__ import annotations

import pytest


# Zone constants duplicated test-side for readability (mirrors the
# pattern in test_resolve.py / test_zones.py).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# Phase constants for advance_phase tests (mirrors test_steps.py).
PHASE_UNTAP = 0
PHASE_MAIN1 = 3
PHASE_END_STEP = 10
PHASE_CLEANUP = 11


def _pump_self_attacker_dict(power_bonus: int = 2, toughness_bonus: int = 2):
    """Vanilla 2/2 creature whose ETB effect pumps itself +N/+M UEOT.

    This is the simplest possible end-to-end PumpSelfUntilEOT proof —
    when the spell resolves, the post-resolve dispatch moves the
    creature to its controller's battlefield AND then fires the ETB
    effects. The ETB effect is the pump-self; the source GameObject
    by ETB time is the just-landed permanent, so the
    ``UeotModifier::PowerToughnessBonus`` lands on the right object.
    """
    return {
        "name": "Pump Self Bears (synthetic)",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "effects": [],
        "etb_effects": [
            {
                "kind": "pump_self_until_eot",
                "power_bonus": power_bonus,
                "toughness_bonus": toughness_bonus,
            }
        ],
    }


def _vanilla_bears_dict():
    """A 2/2 with no ETB effects — for "the OTHER creature didn't gain
    P/T" inverse-completeness pins."""
    return {
        "name": "Vanilla Bears (synthetic)",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "effects": [],
    }


# ---------------------------------------------------------------- effect parsing


def test_register_pump_self_until_eot_default_values(empty_registry):
    """Missing ``power_bonus`` / ``toughness_bonus`` register as 0
    each — mirrors Python's ``PumpSelfUntilEOT(power_bonus: int = 0,
    toughness_bonus: int = 0)`` defaults."""
    pid = empty_registry.register_printing(
        {
            "name": "default-pump-test",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "effects": [{"kind": "pump_self_until_eot"}],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert len(effects) == 1
    assert effects[0]["kind"] == "pump_self_until_eot"
    assert effects[0]["power_bonus"] == 0
    assert effects[0]["toughness_bonus"] == 0


def test_register_pump_self_until_eot_negative_bonuses(empty_registry):
    """Negative bonuses are allowed — Python's dataclass has no
    raise-on-negative guard. A future debuff card can use this shape."""
    pid = empty_registry.register_printing(
        {
            "name": "shrink-test",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
            "effects": [
                {
                    "kind": "pump_self_until_eot",
                    "power_bonus": -1,
                    "toughness_bonus": -2,
                }
            ],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert effects[0]["power_bonus"] == -1
    assert effects[0]["toughness_bonus"] == -2


# ---------------------------------------------------------------- effective P/T accessors


def test_effective_power_matches_printed_when_no_ueot(synthetic_state):
    """A vanilla 2/2 with no UEOT modifiers has effective_power = 2."""
    obj_id = synthetic_state.register_and_inject_object(
        _vanilla_bears_dict(), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.effective_power(obj_id) == 2
    assert synthetic_state.effective_toughness(obj_id) == 2


def test_effective_power_returns_none_for_non_creature(synthetic_state):
    """Non-creatures (no printed power) return None — mirrors
    Python's ``effective_power`` `None` return for non-creature."""
    non_creature_pid = synthetic_state.register_and_inject_object(
        {
            "name": "Synthetic Land",
            "card_types": ["Land"],
            "mana_produced": ["G"],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    assert synthetic_state.effective_power(non_creature_pid) is None
    assert synthetic_state.effective_toughness(non_creature_pid) is None


def test_effective_power_returns_none_for_missing_obj(synthetic_state):
    """Unknown obj_ids return None (mirrors the ``find`` short-circuit
    in every battlefield-walk reader)."""
    assert synthetic_state.effective_power(99_999) is None
    assert synthetic_state.effective_toughness(99_999) is None


# ---------------------------------------------------------------- PumpSelfUntilEOT proof


def test_pump_self_until_eot_resolves_and_pumps_source(synthetic_state):
    """**Load-bearing PumpSelfUntilEOT proof.**

    Cast a 2/2 creature whose ETB pumps itself +3/+3 UEOT. After
    resolve_top_of_stack:
      * the creature is on the active player's battlefield (CR
        608.2m post-resolve);
      * its effective_power is 5 (2 printed + 3 UEOT bonus);
      * its effective_toughness is 5.
    """
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.effective_power(obj_id) == 5
    assert synthetic_state.effective_toughness(obj_id) == 5


def test_pump_self_until_eot_zero_zero_is_noop(synthetic_state):
    """A 0/0 PumpSelf bonus is a legal no-op (parity edge case).
    Resolving it does NOT push a modifier (the warm path stays
    allocation-free) and the source's effective P/T equals printed."""
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=0, toughness_bonus=0),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.effective_power(obj_id) == 2  # printed
    assert synthetic_state.effective_toughness(obj_id) == 2


def test_pump_self_until_eot_negative_bonus_shrinks_source(synthetic_state):
    """A -1/-2 PumpSelf shrinks the source's effective P/T (debuff
    semantics). Pins that effective-P/T arithmetic is signed."""
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=-1, toughness_bonus=-2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.effective_power(obj_id) == 1
    assert synthetic_state.effective_toughness(obj_id) == 0


def test_pump_self_until_eot_only_pumps_source_not_siblings(synthetic_state):
    """A pump on creature X must not bleed onto creature Y on the same
    battlefield. Inverse-completeness pin: the modifier lives on the
    SOURCE's `ueot_modifiers`, not on a globally-scoped registry."""
    pumped_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    sibling_id = synthetic_state.register_and_inject_object(
        _vanilla_bears_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(pumped_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Pumped: 2 + 2 = 4 / 4
    assert synthetic_state.effective_power(pumped_id) == 4
    assert synthetic_state.effective_toughness(pumped_id) == 4
    # Sibling: untouched 2 / 2.
    assert synthetic_state.effective_power(sibling_id) == 2
    assert synthetic_state.effective_toughness(sibling_id) == 2


# ---------------------------------------------------------------- CR 514.3 expiration via cleanup_step


def test_cleanup_step_clears_ueot_modifier(synthetic_state):
    """End-to-end UEOT lifecycle: pump-self resolves, effective P/T
    moves, cleanup_step runs, effective P/T returns to base.

    This is the load-bearing CR 514.3 closure for round-27. The
    cleanup_step's summary dict reports ``ueot_cleared: 1`` (the one
    permanent that had a non-empty UEOT-modifiers Vec)."""
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Mid-turn snapshot: pumped.
    assert synthetic_state.effective_power(obj_id) == 5

    summary = synthetic_state.cleanup_step_for_active_player()
    assert summary["ueot_cleared"] == 1

    # Post-cleanup: back to printed.
    assert synthetic_state.effective_power(obj_id) == 2
    assert synthetic_state.effective_toughness(obj_id) == 2


def test_clear_ueot_modifiers_all_primitive(synthetic_state):
    """``clear_ueot_modifiers_all`` is callable independently of the
    composed cleanup_step. Returns the count of objects whose UEOT
    Vec was non-empty before draining."""
    a_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=1, toughness_bonus=1),
        0,
        ZONE_HAND,
    )
    b_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(a_id, 0)
    synthetic_state.resolve_top_of_stack()
    synthetic_state.push_to_stack(b_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.effective_power(a_id) == 3  # 2 + 1
    assert synthetic_state.effective_power(b_id) == 4  # 2 + 2

    cleared = synthetic_state.clear_ueot_modifiers_all()
    assert cleared == 2
    assert synthetic_state.effective_power(a_id) == 2
    assert synthetic_state.effective_power(b_id) == 2


def test_clear_ueot_modifiers_all_skip_when_no_modifiers(synthetic_state):
    """Warm path: no battlefield permanent has a non-empty UEOT Vec,
    so the primitive returns 0 with no CoW work (the Arc::make_mut
    short-circuit fires)."""
    # No UEOT effects in the synthetic state's seeded battlefield.
    fingerprint_before = synthetic_state.fingerprint()
    cleared = synthetic_state.clear_ueot_modifiers_all()
    assert cleared == 0
    # Fingerprint is unchanged (this also pins that the UEOT clear
    # didn't accidentally tick any observable state).
    assert synthetic_state.fingerprint() == fingerprint_before


def test_cleanup_idempotent_for_ueot_clear(synthetic_state):
    """Running cleanup twice in a row is a no-op on the second call —
    the UEOT Vec is already drained."""
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()

    first = synthetic_state.cleanup_step_for_active_player()
    assert first["ueot_cleared"] == 1
    second = synthetic_state.cleanup_step_for_active_player()
    assert second["ueot_cleared"] == 0


# ---------------------------------------------------------------- CR 514.3 expiration via advance_phase


def test_advance_phase_through_cleanup_clears_ueot(synthetic_state):
    """``advance_phase`` is the production game-loop primitive — it
    composes cleanup_step on entry to PHASE_CLEANUP. Round-27 wires
    the UEOT clear into that composition so the parity-smoke harness
    sees the expiration at the right phase boundary.

    Setup: pump_self spell resolves at MAIN1, walk advance_phase
    forward to CLEANUP. Effective P/T returns to base."""
    synthetic_state.set_phase(PHASE_MAIN1)
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.effective_power(obj_id) == 5

    # Walk forward through every phase until we land on CLEANUP.
    while synthetic_state.current_phase() != PHASE_CLEANUP:
        synthetic_state.advance_phase()

    # On entry to CLEANUP the composed cleanup_step ran and drained
    # the UEOT modifiers.
    assert synthetic_state.effective_power(obj_id) == 2
    assert synthetic_state.effective_toughness(obj_id) == 2


def test_end_turn_and_start_next_clears_ueot(synthetic_state):
    """``end_turn_and_start_next`` is the higher-level round-17
    composition that wraps the full cleanup -> next-turn-untap step.
    It must drain UEOT modifiers along with the rest of cleanup."""
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=4, toughness_bonus=4),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.effective_power(obj_id) == 6

    synthetic_state.end_turn_and_start_next()
    # Next turn — UEOT cleared.
    assert synthetic_state.effective_power(obj_id) == 2


# ---------------------------------------------------------------- effective keyword reader


def _vanilla_creature_with_keyword_dict(keyword: str):
    return {
        "name": f"Vanilla with {keyword}",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "keywords": [keyword],
        "effects": [],
    }


def _plain_2_2_dict():
    return {
        "name": "Plain 2/2",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "effects": [],
    }


def test_has_keyword_reads_printed_keyword(synthetic_state):
    """A creature with printed `flying` returns True from
    `has_keyword(id, 'flying')`. Pins the printed-side baseline so a
    UEOT-side regression doesn't accidentally drop the printed set."""
    obj_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_with_keyword_dict("flying"), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.has_keyword(obj_id, "flying") is True
    assert synthetic_state.has_keyword(obj_id, "trample") is False


def test_has_keyword_returns_false_for_missing(synthetic_state):
    """Unknown obj_ids return False (mirrors the private helper)."""
    assert synthetic_state.has_keyword(99_999, "flying") is False


# ---------------------------------------------------------------- CoW preservation


def test_clone_then_pump_does_not_affect_original(synthetic_state):
    """**CoW canary for UEOT modifier writes.** Cloning the state and
    pushing a UEOT modifier on the clone must not bleed the modifier
    back into the source — same load-bearing assertion every other
    per-object-mutation slice carries (damage / tapped / counters /
    summoning_sick)."""
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone has the pump applied (post-resolve put creature on bf with
    # +2/+2 modifier).
    assert cloned.effective_power(obj_id) == 4
    # Source: object still in hand (untouched stack), no modifier
    # written — find_object_zone == ZONE_HAND, effective_power is None.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_HAND
    assert synthetic_state.effective_power(obj_id) is None


def test_clone_then_cleanup_does_not_affect_original_ueot(synthetic_state):
    """Inverse canary: pump applied THEN cleanup on the clone must
    not bleed cleanup's UEOT-clear into the source's modifier Vec."""
    obj_id = synthetic_state.register_and_inject_object(
        _pump_self_attacker_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(obj_id, 0)
    synthetic_state.resolve_top_of_stack()
    # Both states agree the modifier is live; clone first.
    assert synthetic_state.effective_power(obj_id) == 5
    cloned = synthetic_state.clone_once()

    cloned.cleanup_step_for_active_player()

    # Clone: UEOT cleared.
    assert cloned.effective_power(obj_id) == 2
    # Source: UEOT still live (cleanup didn't run on it).
    assert synthetic_state.effective_power(obj_id) == 5


# ---------------------------------------------------------------- PumpTargetCreatureUntilEOT (r28)


def _pump_target_instant_dict(power_bonus: int = 3, toughness_bonus: int = 3):
    """Giant-Growth-shape instant: cast and resolve, the spell pumps
    the first creature on the controller's battlefield +N/+M UEOT.

    This is the simplest end-to-end PumpTargetCreatureUntilEOT proof —
    cast as an instant with one effect; resolve puts the source in the
    graveyard (CR 608.2m) but the resolve dispatch fires the effect
    first against the source's controller's battlefield."""
    return {
        "name": "Giant Growth (synthetic)",
        "mana_cost": {"G": 1},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "pump_target_creature_until_eot",
                "power_bonus": power_bonus,
                "toughness_bonus": toughness_bonus,
            }
        ],
    }


def test_register_pump_target_creature_until_eot_default_values(empty_registry):
    """Missing power_bonus / toughness_bonus default to 0 (mirrors the
    PumpSelfUntilEOT schema)."""
    pid = empty_registry.register_printing(
        {
            "name": "default-target-pump",
            "card_types": ["Instant"],
            "effects": [{"kind": "pump_target_creature_until_eot"}],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert len(effects) == 1
    assert effects[0]["kind"] == "pump_target_creature_until_eot"
    assert effects[0]["power_bonus"] == 0
    assert effects[0]["toughness_bonus"] == 0


def test_register_pump_target_creature_until_eot_negative_bonuses(empty_registry):
    """Negative bonuses allowed (debuff-shaped target pumps)."""
    pid = empty_registry.register_printing(
        {
            "name": "shrink-target",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": -2,
                    "toughness_bonus": -3,
                }
            ],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert effects[0]["power_bonus"] == -2
    assert effects[0]["toughness_bonus"] == -3


def _first_creature_id_on_battlefield(state, player_id: int) -> int:
    """Helper: find the id of the first creature on `player_id`'s
    battlefield in zone-iteration order. Mirrors the arm's selection
    logic so tests can assert on the actually-pumped creature."""
    snap = state.battlefield_snapshot()
    # battlefield_snapshot returns p0-then-p1 by-player order (per
    # round-21 documented Rust-only divergence); filter to the
    # requested controller.
    for d in snap:
        if d["controller_id"] != player_id:
            continue
        # First-creature-on-battlefield: synthetic state has Forests
        # (Land) then Grizzly Bears (Creature). The arm filters on
        # card_types contains "Creature".
        if d["printing_name"] == "Grizzly Bears":
            return d["id"]
    raise AssertionError(f"no Grizzly Bears on player {player_id}'s battlefield")


def test_pump_target_creature_until_eot_pumps_controllers_first_creature(synthetic_state):
    """Load-bearing PumpTargetCreatureUntilEOT proof: the resolving
    spell pumps the FIRST creature on the source's controller's
    battlefield. Synthetic state's p0 battlefield has Forests
    (non-creature) then Grizzly Bears; the first eligible target is
    the first Grizzly Bears."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_instant_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Grizzly Bears moved from 2/2 to 5/5 via the UEOT bonus.
    assert synthetic_state.effective_power(target_id) == 5
    assert synthetic_state.effective_toughness(target_id) == 5


def test_pump_target_creature_until_eot_zero_zero_is_noop(synthetic_state):
    """0/0 is a legal no-op: warm path stays allocation-free; no
    modifier written; target's effective P/T equals printed."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_instant_dict(power_bonus=0, toughness_bonus=0),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.effective_power(target_id) == 2
    assert synthetic_state.effective_toughness(target_id) == 2


def test_pump_target_creature_until_eot_no_creature_fizzles_silently(synthetic_state):
    """No creatures on the source's controller's battlefield → silent
    fizzle. The source still goes to graveyard (CR 608.2m) and no
    modifier lands anywhere."""
    state = synthetic_state.clone_once()
    # Drain p0's battlefield by moving every object to graveyard.
    while True:
        snap = state.battlefield_snapshot()
        my_ids = [d["id"] for d in snap if d["controller_id"] == 0]
        if not my_ids:
            break
        state.move_object(my_ids[0], 3, 0)  # ZONE_GRAVEYARD

    pump_id = state.register_and_inject_object(
        _pump_target_instant_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    state.push_to_stack(pump_id, 0)
    # Should resolve without raising; no creature was on p0 bf, so no
    # modifier was written anywhere.
    state.resolve_top_of_stack()


def test_pump_target_creature_until_eot_clears_at_cleanup(synthetic_state):
    """The UEOT modifier auto-clears at the next cleanup step — same
    contract PumpSelfUntilEOT pins."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_instant_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.effective_power(target_id) == 4

    synthetic_state.cleanup_step_for_active_player()

    assert synthetic_state.effective_power(target_id) == 2
    assert synthetic_state.effective_toughness(target_id) == 2


def test_pump_target_creature_until_eot_picks_first_of_multiple(synthetic_state):
    """When multiple creatures are eligible, pick the FIRST one (zone-
    iteration order) — first-slice deterministic convention. Pumps
    target_id (first Grizzly Bears); second Grizzly Bears stays
    printed."""
    snap = synthetic_state.battlefield_snapshot()
    p0_creatures = [
        d for d in snap if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    assert len(p0_creatures) >= 2, (
        "synthetic state default has >=2 Grizzly Bears on p0 battlefield"
    )
    first_bear_id = p0_creatures[0]["id"]
    second_bear_id = p0_creatures[1]["id"]

    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_instant_dict(power_bonus=1, toughness_bonus=1),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Only the first Bears creature gets pumped; second stays printed.
    # (Bears printed P/T = 2/2 per synthetic state's Grizzly Bears.)
    assert synthetic_state.effective_power(first_bear_id) == 3
    assert synthetic_state.effective_power(second_bear_id) == 2


def test_pump_target_creature_until_eot_clone_isolation(synthetic_state):
    """CoW isolation: clone before resolve; resolve on clone; original's
    targets remain printed P/T."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_instant_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone has pumped target.
    assert cloned.effective_power(target_id) == 5
    # Original target still at printed P/T (no pump written).
    assert synthetic_state.effective_power(target_id) == 2


# ---------------------------------------------------------------- PumpCreaturesYouControlUntilEOT (r28)


def _pump_creatures_instant_dict(power_bonus: int = 1, toughness_bonus: int = 1):
    """Anthem-shape instant: pump every creature on the controller's
    battlefield +N/+M UEOT."""
    return {
        "name": "Anthem Instant (synthetic)",
        "mana_cost": {"W": 1},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "pump_creatures_you_control_until_eot",
                "power_bonus": power_bonus,
                "toughness_bonus": toughness_bonus,
            }
        ],
    }


def test_register_pump_creatures_you_control_until_eot_defaults(empty_registry):
    pid = empty_registry.register_printing(
        {
            "name": "default-anthem",
            "card_types": ["Instant"],
            "effects": [{"kind": "pump_creatures_you_control_until_eot"}],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert effects[0]["kind"] == "pump_creatures_you_control_until_eot"
    assert effects[0]["power_bonus"] == 0
    assert effects[0]["toughness_bonus"] == 0


def test_pump_creatures_you_control_until_eot_pumps_all_controller_creatures(synthetic_state):
    """Every Grizzly Bears on p0's battlefield gets +1/+1; Forests
    (non-creature) are untouched."""
    snap_before = synthetic_state.battlefield_snapshot()
    p0_creature_ids = [
        d["id"] for d in snap_before
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    p0_forest_ids = [
        d["id"] for d in snap_before
        if d["controller_id"] == 0 and d["printing_name"] == "Forest"
    ]
    p1_creature_ids = [
        d["id"] for d in snap_before
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    assert len(p0_creature_ids) >= 2
    assert len(p0_forest_ids) >= 1
    assert len(p1_creature_ids) >= 1

    pump_id = synthetic_state.register_and_inject_object(
        _pump_creatures_instant_dict(power_bonus=1, toughness_bonus=1),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()

    # All of p0's creatures pumped: 2/2 -> 3/3.
    for cid in p0_creature_ids:
        assert synthetic_state.effective_power(cid) == 3
        assert synthetic_state.effective_toughness(cid) == 3
    # Forests are non-creature: effective_power returns None.
    for fid in p0_forest_ids:
        assert synthetic_state.effective_power(fid) is None
    # p1's creatures untouched: still 2/2.
    for cid in p1_creature_ids:
        assert synthetic_state.effective_power(cid) == 2
        assert synthetic_state.effective_toughness(cid) == 2


def test_pump_creatures_you_control_until_eot_zero_zero_is_noop(synthetic_state):
    """0/0 short-circuits; no modifier written; effective P/T equals
    printed."""
    snap = synthetic_state.battlefield_snapshot()
    bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    pump_id = synthetic_state.register_and_inject_object(
        _pump_creatures_instant_dict(power_bonus=0, toughness_bonus=0),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()
    for cid in bear_ids:
        assert synthetic_state.effective_power(cid) == 2


def test_pump_creatures_you_control_until_eot_clears_at_cleanup(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    pump_id = synthetic_state.register_and_inject_object(
        _pump_creatures_instant_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()
    for cid in bear_ids:
        assert synthetic_state.effective_power(cid) == 4

    synthetic_state.cleanup_step_for_active_player()

    for cid in bear_ids:
        assert synthetic_state.effective_power(cid) == 2


def test_pump_creatures_you_control_until_eot_no_creatures_fizzles_silently(synthetic_state):
    """No eligible creatures on the controller's bf -> silent no-op
    (e.g. a board with only Forests). Source still resolves cleanly."""
    state = synthetic_state.clone_once()
    # Drain p0 of creatures (Grizzly Bears), leaving Forests.
    snap = state.battlefield_snapshot()
    bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    for bid in bear_ids:
        state.move_object(bid, 3, 0)  # ZONE_GRAVEYARD

    pump_id = state.register_and_inject_object(
        _pump_creatures_instant_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    state.push_to_stack(pump_id, 0)
    state.resolve_top_of_stack()  # should not raise


def test_pump_creatures_you_control_until_eot_clone_isolation(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    pump_id = synthetic_state.register_and_inject_object(
        _pump_creatures_instant_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    # Clone pumped all bears.
    for cid in bear_ids:
        assert cloned.effective_power(cid) == 5
    # Source unchanged.
    for cid in bear_ids:
        assert synthetic_state.effective_power(cid) == 2


# ---------------------------------------------------------------- PumpCreaturesOpponentsControlUntilEOT (r28)


def _curse_anthem_dict(power_bonus: int = -1, toughness_bonus: int = -1):
    """Debuff anthem: every creature opponent controls gets
    -power/-toughness UEOT."""
    return {
        "name": "Curse Anthem (synthetic)",
        "mana_cost": {"B": 1, "generic": 1},
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "pump_creatures_opponents_control_until_eot",
                "power_bonus": power_bonus,
                "toughness_bonus": toughness_bonus,
            }
        ],
    }


def test_register_pump_creatures_opponents_control_defaults(empty_registry):
    pid = empty_registry.register_printing(
        {
            "name": "default-curse",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "pump_creatures_opponents_control_until_eot"}],
        }
    )
    eff = empty_registry.get_printing_effects(pid)[0]
    assert eff["kind"] == "pump_creatures_opponents_control_until_eot"
    assert eff["power_bonus"] == 0
    assert eff["toughness_bonus"] == 0


def test_pump_creatures_opponents_control_debuffs_p1_creatures(synthetic_state):
    """Cast a debuff curse from p0 — every Grizzly Bears on p1's
    battlefield gets -1/-1; p0's creatures untouched."""
    snap = synthetic_state.battlefield_snapshot()
    p0_creature_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    ]
    p1_creature_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    assert len(p1_creature_ids) >= 1
    spell_id = synthetic_state.register_and_inject_object(
        _curse_anthem_dict(power_bonus=-1, toughness_bonus=-1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    # p1's creatures: 2/2 -> 1/1.
    for cid in p1_creature_ids:
        assert synthetic_state.effective_power(cid) == 1
        assert synthetic_state.effective_toughness(cid) == 1
    # p0's creatures untouched.
    for cid in p0_creature_ids:
        assert synthetic_state.effective_power(cid) == 2


def test_pump_creatures_opponents_control_zero_zero_is_noop(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    p1_bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    spell_id = synthetic_state.register_and_inject_object(
        _curse_anthem_dict(power_bonus=0, toughness_bonus=0), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    for cid in p1_bear_ids:
        assert synthetic_state.effective_power(cid) == 2


def test_pump_creatures_opponents_control_clears_at_cleanup(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    p1_bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    spell_id = synthetic_state.register_and_inject_object(
        _curse_anthem_dict(power_bonus=-1, toughness_bonus=-1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    for cid in p1_bear_ids:
        assert synthetic_state.effective_power(cid) == 1
    # Clear UEOT directly via the r27 primitive. (The modifier lands
    # on p1's bf — cleanup_step_for_active_player only drains the
    # active player's bf, so we use the engine-wide drain primitive.)
    synthetic_state.clear_ueot_modifiers_all()
    for cid in p1_bear_ids:
        assert synthetic_state.effective_power(cid) == 2


def test_pump_creatures_opponents_control_no_opponent_creatures_fizzles(synthetic_state):
    state = synthetic_state.clone_once()
    snap = state.battlefield_snapshot()
    p1_creatures = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    for cid in p1_creatures:
        state.move_object(cid, 3, 1)  # graveyard
    spell_id = state.register_and_inject_object(
        _curse_anthem_dict(power_bonus=-2, toughness_bonus=-2), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()  # should not raise


def test_pump_creatures_opponents_control_clone_isolation(synthetic_state):
    snap = synthetic_state.battlefield_snapshot()
    p1_bear_ids = [
        d["id"] for d in snap
        if d["controller_id"] == 1 and d["printing_name"] == "Grizzly Bears"
    ]
    spell_id = synthetic_state.register_and_inject_object(
        _curse_anthem_dict(power_bonus=-1, toughness_bonus=-1), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    cloned = synthetic_state.clone_once()
    cloned.resolve_top_of_stack()

    for cid in p1_bear_ids:
        assert cloned.effective_power(cid) == 1
        assert synthetic_state.effective_power(cid) == 2  # source unchanged


# ---------------------------------------------------------------- PumpTargetArtifactOrCreatureUntilEOT (r28)


def _pump_target_artifact_or_creature_dict(power_bonus: int = 2, toughness_bonus: int = 2):
    """Broader-filter pump instant — eligible on artifact OR creature."""
    return {
        "name": "Test Artifact-or-Creature Pump",
        "mana_cost": {"R": 1},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "pump_target_artifact_or_creature_until_eot",
                "power_bonus": power_bonus,
                "toughness_bonus": toughness_bonus,
            }
        ],
    }


def test_register_pump_target_artifact_or_creature_default_values(empty_registry):
    """Missing power_bonus / toughness_bonus default to 0."""
    pid = empty_registry.register_printing(
        {
            "name": "default-artifact-or-creature-pump",
            "card_types": ["Instant"],
            "effects": [{"kind": "pump_target_artifact_or_creature_until_eot"}],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert len(effects) == 1
    assert effects[0]["kind"] == "pump_target_artifact_or_creature_until_eot"
    assert effects[0]["power_bonus"] == 0
    assert effects[0]["toughness_bonus"] == 0


def test_register_pump_target_artifact_or_creature_negative_bonuses(empty_registry):
    """Negative bonuses allowed (debuff-shaped)."""
    pid = empty_registry.register_printing(
        {
            "name": "shrink-artifact-or-creature",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "pump_target_artifact_or_creature_until_eot",
                    "power_bonus": -2,
                    "toughness_bonus": -3,
                }
            ],
        }
    )
    effects = empty_registry.get_printing_effects(pid)
    assert effects[0]["power_bonus"] == -2
    assert effects[0]["toughness_bonus"] == -3


def test_pump_target_artifact_or_creature_pumps_first_creature(synthetic_state):
    """When the controller's bf has Forests + Grizzly Bears, the first
    eligible (Creature) is the first Grizzly Bears (Lands are NOT
    eligible since the filter is artifact OR creature)."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_artifact_or_creature_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.effective_power(target_id) == 4
    assert synthetic_state.effective_toughness(target_id) == 4


def test_pump_target_artifact_or_creature_pumps_artifact_when_no_creature(synthetic_state):
    """When the controller's bf has an Artifact but NO Creature, the
    artifact is the chosen target — broader filter than
    PumpTargetCreatureUntilEOT. Build a state with an artifact on p0
    bf and no creatures."""
    state = synthetic_state.clone_once()
    # Drain p0's battlefield to no creatures.
    while True:
        snap = state.battlefield_snapshot()
        my_creature_ids = [
            d["id"] for d in snap
            if d["controller_id"] == 0
            and d["printing_name"] == "Grizzly Bears"
        ]
        if not my_creature_ids:
            break
        state.move_object(my_creature_ids[0], 3, 0)  # → graveyard

    # Inject a basic artifact onto p0 bf.
    artifact_id = state.register_and_inject_object(
        {
            "name": "Test Vehicle",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "power": 1,
            "toughness": 1,
            "effects": [],
        },
        0,
        2,  # ZONE_BATTLEFIELD
    )

    pump_id = state.register_and_inject_object(
        _pump_target_artifact_or_creature_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    state.push_to_stack(pump_id, 0)
    state.resolve_top_of_stack()

    # The artifact got pumped — confirms the broader filter.
    assert state.effective_power(artifact_id) == 4
    assert state.effective_toughness(artifact_id) == 4


def test_pump_target_artifact_or_creature_zero_zero_is_noop(synthetic_state):
    """0/0 is a legal no-op; target keeps printed P/T."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_artifact_or_creature_dict(power_bonus=0, toughness_bonus=0),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.effective_power(target_id) == 2
    assert synthetic_state.effective_toughness(target_id) == 2


def test_pump_target_artifact_or_creature_no_eligible_target_fizzles(synthetic_state):
    """If controller's bf has NO artifacts and NO creatures (only Lands),
    fizzle silently."""
    state = synthetic_state.clone_once()
    while True:
        snap = state.battlefield_snapshot()
        my_non_land_ids = [
            d["id"] for d in snap
            if d["controller_id"] == 0
            and d["printing_name"] == "Grizzly Bears"
        ]
        if not my_non_land_ids:
            break
        state.move_object(my_non_land_ids[0], 3, 0)

    pump_id = state.register_and_inject_object(
        _pump_target_artifact_or_creature_dict(power_bonus=3, toughness_bonus=3),
        0,
        ZONE_HAND,
    )
    state.push_to_stack(pump_id, 0)
    # Resolve without raising; no modifier written anywhere.
    state.resolve_top_of_stack()


def test_pump_target_artifact_or_creature_clears_at_cleanup(synthetic_state):
    """UEOT modifier auto-clears at cleanup step."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    pump_id = synthetic_state.register_and_inject_object(
        _pump_target_artifact_or_creature_dict(power_bonus=2, toughness_bonus=2),
        0,
        ZONE_HAND,
    )
    synthetic_state.push_to_stack(pump_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.effective_power(target_id) == 4

    synthetic_state.cleanup_step_for_active_player()

    assert synthetic_state.effective_power(target_id) == 2
    assert synthetic_state.effective_toughness(target_id) == 2


# ---------------------------------------------------------------- GrantKeywordToTargetCreatureUntilEOT (r28)


def _grant_keyword_target_dict(keyword: str = "unblockable"):
    """Instant that grants `keyword` UEOT to the first creature on the
    controller's battlefield."""
    return {
        "name": f"Test Grant {keyword} UEOT",
        "mana_cost": {"U": 1},
        "card_types": ["Instant"],
        "effects": [
            {
                "kind": "grant_keyword_to_target_creature_until_eot",
                "keyword": keyword,
            }
        ],
    }


def test_register_grant_keyword_target_default_unblockable(empty_registry):
    """A grant-unblockable register-and-readback round-trip."""
    pid = empty_registry.register_printing(_grant_keyword_target_dict("unblockable"))
    effects = empty_registry.get_printing_effects(pid)
    assert len(effects) == 1
    assert effects[0]["kind"] == "grant_keyword_to_target_creature_until_eot"
    assert effects[0]["keyword"] == "unblockable"


def test_register_grant_keyword_target_missing_keyword_raises(empty_registry):
    """Missing `keyword` field rejected at register time."""
    with pytest.raises(ValueError):
        empty_registry.register_printing(
            {
                "name": "bad-grant",
                "card_types": ["Instant"],
                "effects": [{"kind": "grant_keyword_to_target_creature_until_eot"}],
            }
        )


def test_register_grant_keyword_target_empty_string_raises(empty_registry):
    """Empty-string keyword rejected at register time."""
    with pytest.raises(ValueError):
        empty_registry.register_printing(_grant_keyword_target_dict(keyword=""))


def test_grant_keyword_target_unblockable_pumps_first_creature(synthetic_state):
    """Resolving the spell grants 'unblockable' to the first creature on
    the source's controller's battlefield. has_keyword(target_id,
    'unblockable') flips to True."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    assert synthetic_state.has_keyword(target_id, "unblockable") is False

    spell_id = synthetic_state.register_and_inject_object(
        _grant_keyword_target_dict("unblockable"), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_keyword(target_id, "unblockable") is True


def test_grant_keyword_target_haste(synthetic_state):
    """The dispatcher is keyword-agnostic — passing 'haste' grants
    haste UEOT to the first creature."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    assert synthetic_state.has_keyword(target_id, "haste") is False

    spell_id = synthetic_state.register_and_inject_object(
        _grant_keyword_target_dict("haste"), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.has_keyword(target_id, "haste") is True


def test_grant_keyword_target_clears_at_cleanup(synthetic_state):
    """UEOT-granted keyword clears at the next cleanup step (CR 514.3
    via the r27 UEOT-clear pass)."""
    target_id = _first_creature_id_on_battlefield(synthetic_state, 0)
    spell_id = synthetic_state.register_and_inject_object(
        _grant_keyword_target_dict("unblockable"), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(spell_id, 0)
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.has_keyword(target_id, "unblockable") is True

    synthetic_state.cleanup_step_for_active_player()

    assert synthetic_state.has_keyword(target_id, "unblockable") is False


def test_grant_keyword_target_no_creature_fizzles(synthetic_state):
    """No creature on controller's bf → silent fizzle."""
    state = synthetic_state.clone_once()
    while True:
        snap = state.battlefield_snapshot()
        my_creature_ids = [
            d["id"] for d in snap
            if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
        ]
        if not my_creature_ids:
            break
        state.move_object(my_creature_ids[0], 3, 0)  # → graveyard

    spell_id = state.register_and_inject_object(
        _grant_keyword_target_dict("unblockable"), 0, ZONE_HAND
    )
    state.push_to_stack(spell_id, 0)
    # Resolves without raising; no modifier written.
    state.resolve_top_of_stack()
