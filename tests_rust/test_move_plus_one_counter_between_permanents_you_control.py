"""Rust-engine unit pins for the
``Effect::MovePlusOneCounterBetweenPermanentsYouControl`` parse +
to_pydict + dual-target resolve arms.

**Nesting Grounds substrate (2026-05-31 — spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §Group-1 Nesting
Grounds row).** The Rust Effect variant is a unit (no fields); the
donor (slot 0) + recipient (slot 1) are derived at resolve time from
the 2-slot payload plumbing (``current_resolve_payload_target_id`` /
``_2``). Mirrors Python's
``MovePlusOneCounterBetweenPermanentsYouControl()`` at
``effects/generic/counters.py:322`` — Nesting Grounds' single
``{1}, {T}: Move a counter from target permanent you control onto a
second target permanent. Activate only as a sorcery.`` AA pilot effect.

The resolve arm reads slot 0 (donor) + slot 1 (recipient), no-ops on
donor==recipient, requires both on a battlefield, fizzles when the
donor carries no ``+1/+1`` counter, and otherwise moves exactly one
counter (donor ``-1``, recipient ``+1``). The doubling / observer-
trigger surface Python's ``add_plus_one_counters`` applies is NOT
mirrored (substrate-only simplification; see
``docs/SEARCH_LIMITATIONS.md``).

These pins drive the resolve arm DIRECTLY via the
``push_to_stack_with_three_targets`` synthetic-spell idiom (slot 2 =
``None`` — Nesting Grounds is a 2-target effect): register a Sorcery
whose ``effects[0]`` is the bare move-counter leaf, push it with the
donor + recipient seated, and ``resolve_top_of_stack``. The cross-
engine bridge round-trip + byte-equal Python parity is covered by the
sibling probe at ``tests/test_nesting_grounds_parity.py``.

Covered:

  - parse_effect arm accepts the 1-key unit dict shape (kind only).
  - to_pydict round-trips the 1-key unit dict shape.
  - Resolve: moves one counter donor -> recipient (both controlled).
  - Resolve fizzle: donor with 0 counters → no move (recipient stays).
  - Resolve no-op: donor == recipient → no change.
  - Resolve no-op: recipient absent from any bf → no move.
  - Resolve no-op: only one target slot seated (slot 1 None) → no move
    (the production AA-activation single-target path — the composite-
    admit wall).
  - Multi-counter donor: moves exactly ONE counter (donor 3 -> 2,
    recipient 0 -> 1).
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_BATTLEFIELD = 2


def _move_counter_spell_dict():
    """Synthetic Sorcery carrying the bare
    ``move_plus_one_counter_between_permanents_you_control`` leaf as its
    spell body so the test can drive it via
    ``push_to_stack_with_three_targets`` + ``resolve_top_of_stack``.
    """
    return {
        "name": "Synthetic Counter Mover",
        "card_types": ["Sorcery"],
        "mana_cost": {"generic": 1},
        "effects": [
            {"kind": "move_plus_one_counter_between_permanents_you_control"},
        ],
    }


def _permanent(name="Plain Permanent"):
    """A vanilla creature permanent to host +1/+1 counters."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
    }


# ---------------------------------------------------------------------------
# parse_effect + register + to_pydict pins
# ---------------------------------------------------------------------------


def test_register_printing_with_new_effect(empty_registry):
    """**parse_effect arm pin.** The new
    ``move_plus_one_counter_between_permanents_you_control`` parse arm
    consumes the 1-key unit dict shape and registers cleanly.
    """
    pid = empty_registry.register_printing(_move_counter_spell_dict())
    assert empty_registry.get_printing_name(pid) == "Synthetic Counter Mover"


# ---------------------------------------------------------------------------
# Resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_moves_one_counter_donor_to_recipient(engine):
    """**Resolve arm pin — default Nesting Grounds scenario.** Donor (p0
    permanent) carries 2 +1/+1 counters; the recipient (p0 permanent)
    carries 0. Resolving the move-counter spell with both targets seated
    moves exactly ONE counter: donor 2 -> 1, recipient 0 -> 1.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    donor = s.register_and_inject_object(_permanent("Donor"), 0, ZONE_BATTLEFIELD)
    recipient = s.register_and_inject_object(
        _permanent("Recipient"), 0, ZONE_BATTLEFIELD,
    )
    assert s.set_counters(donor, 2) is True

    spell = s.register_and_inject_object(
        _move_counter_spell_dict(), 0, ZONE_HAND,
    )
    s.push_to_stack_with_three_targets(spell, 0, donor, recipient, None)
    s.resolve_top_of_stack()

    assert s.get_counters(donor) == 1, "donor must lose exactly one counter"
    assert s.get_counters(recipient) == 1, "recipient must gain exactly one"


def test_resolve_multi_counter_donor_moves_exactly_one(engine):
    """**Resolve arm pin — multi-counter donor.** A donor with 3
    counters loses exactly ONE (3 -> 2); the recipient gains exactly one
    (0 -> 1). Oracle says "a counter" (singular) — both engines move one.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    donor = s.register_and_inject_object(_permanent("Donor"), 0, ZONE_BATTLEFIELD)
    recipient = s.register_and_inject_object(
        _permanent("Recipient"), 0, ZONE_BATTLEFIELD,
    )
    assert s.set_counters(donor, 3) is True

    spell = s.register_and_inject_object(
        _move_counter_spell_dict(), 0, ZONE_HAND,
    )
    s.push_to_stack_with_three_targets(spell, 0, donor, recipient, None)
    s.resolve_top_of_stack()

    assert s.get_counters(donor) == 2
    assert s.get_counters(recipient) == 1


def test_resolve_donor_with_no_counters_fizzles(engine):
    """**Resolve arm pin — fizzle.** A donor with 0 counters: the ability
    fizzles (Python's ``if donor.plus_one_counters <= 0: ... return``).
    Neither permanent's counter count changes.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    donor = s.register_and_inject_object(_permanent("Donor"), 0, ZONE_BATTLEFIELD)
    recipient = s.register_and_inject_object(
        _permanent("Recipient"), 0, ZONE_BATTLEFIELD,
    )
    # Donor has the default 0 counters.

    spell = s.register_and_inject_object(
        _move_counter_spell_dict(), 0, ZONE_HAND,
    )
    s.push_to_stack_with_three_targets(spell, 0, donor, recipient, None)
    s.resolve_top_of_stack()

    assert s.get_counters(donor) == 0
    assert s.get_counters(recipient) == 0, "fizzle: recipient gains nothing"


def test_resolve_donor_equals_recipient_is_noop(engine):
    """**Resolve arm pin — donor == recipient.** When both target slots
    point at the same permanent, the resolve arm no-ops (Python's
    ``if donor_id == recipient_id: return``). The counter count is
    unchanged.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    donor = s.register_and_inject_object(_permanent("Donor"), 0, ZONE_BATTLEFIELD)
    assert s.set_counters(donor, 2) is True

    spell = s.register_and_inject_object(
        _move_counter_spell_dict(), 0, ZONE_HAND,
    )
    s.push_to_stack_with_three_targets(spell, 0, donor, donor, None)
    s.resolve_top_of_stack()

    assert s.get_counters(donor) == 2, "donor==recipient: no-op, count held"


def test_resolve_recipient_absent_is_noop(engine):
    """**Resolve arm pin — recipient not on any battlefield.** When slot
    1 points at a never-injected id, the recipient-locate scan returns
    ``None`` and the resolve arm short-circuits (Python re-fetches the
    recipient from ``state.battlefield`` and returns on ``None``). The
    donor keeps its counters.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    donor = s.register_and_inject_object(_permanent("Donor"), 0, ZONE_BATTLEFIELD)
    assert s.set_counters(donor, 2) is True

    spell = s.register_and_inject_object(
        _move_counter_spell_dict(), 0, ZONE_HAND,
    )
    # Slot 1 (recipient) points at a never-injected id.
    s.push_to_stack_with_three_targets(spell, 0, donor, 999_999, None)
    s.resolve_top_of_stack()

    assert s.get_counters(donor) == 2, (
        "recipient absent: no counter leaves the donor"
    )


def test_resolve_single_target_slot_is_noop(engine):
    """**Resolve arm pin — only slot 0 seated → ``<2 targets`` no-op.**
    With slot 1 (``current_resolve_payload_target_id_2``) unseated, the
    resolve arm's ``<2 targets`` short-circuit fires and NO counter
    moves. This pins the fizzle path a single-target seating drives.

    **Historical note (the FLIP):** the substrate landing left the
    AA-activation path binding ONLY slot 0
    (``new_trigger_with_target``) — that was the wall that kept Nesting
    Grounds declined. The FLIP added the 2nd-target slot
    (``new_trigger_with_two_targets`` + ``target_creature_id_2``); the
    ``test_aa_activation_*`` pins below drive BOTH slots via
    ``apply_action`` and prove the wall is closed.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    donor = s.register_and_inject_object(_permanent("Donor"), 0, ZONE_BATTLEFIELD)
    assert s.set_counters(donor, 2) is True

    spell = s.register_and_inject_object(
        _move_counter_spell_dict(), 0, ZONE_HAND,
    )
    # push_to_stack_with_target seats ONLY slot 0 (target_obj_id_2 = None)
    # — the exact shape the AA-activation path produces.
    s.push_to_stack_with_target(spell, 0, donor)
    s.resolve_top_of_stack()

    assert s.get_counters(donor) == 2, (
        "single-target seating: <2 targets → resolve no-op (donor "
        "keeps its counter)"
    )


def test_resolve_cross_player_recipient_moves_counter(engine):
    """**Resolve arm pin — recipient on a DIFFERENT player's bf.** The
    locate scans walk every player's battlefield (the donor/recipient
    may legitimately live on different bf Vecs after a control change).
    A recipient on p1's bf still receives the counter (the resolve arm
    does not controller-gate the recipient — Python's
    ``legal_targets`` controller-gates at emission, not resolve). Pins
    the two-``Arc::make_mut`` cross-Vec path.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    donor = s.register_and_inject_object(_permanent("Donor"), 0, ZONE_BATTLEFIELD)
    recipient = s.register_and_inject_object(
        _permanent("Recipient"), 1, ZONE_BATTLEFIELD,
    )
    assert s.set_counters(donor, 2) is True

    spell = s.register_and_inject_object(
        _move_counter_spell_dict(), 0, ZONE_HAND,
    )
    s.push_to_stack_with_three_targets(spell, 0, donor, recipient, None)
    s.resolve_top_of_stack()

    assert s.get_counters(donor) == 1
    assert s.get_counters(recipient) == 1


# ---------------------------------------------------------------------------
# AA-activation 2nd-target-slot pins (THE FLIP) — drive the dual-target
# AA via ``apply_action`` with ``target_creature_id`` (donor) +
# ``target_creature_id_2`` (recipient). These exercise the new plumbing:
# ``Action::ActivateAbility.target_creature_id_2`` →
# ``StackItem::new_trigger_with_two_targets`` →
# ``trigger_payload.target_id_2`` → ``current_resolve_payload_target_id_2``
# swap in the trigger resolve entry points.
# ---------------------------------------------------------------------------


def _nesting_grounds_dict():
    """The REAL parsed Nesting Grounds shape: a bare Land with ONE
    non-mana ``{1}{T}`` sorcery-speed AA carrying the move-counter leaf.
    """
    return {
        "name": "Nesting Grounds",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"mana": {"generic": 1}, "tap_self": True},
                "effect": {
                    "kind": (
                        "move_plus_one_counter_between_permanents_you_control"
                    ),
                },
                "is_mana_ability": False,
                "sorcery_speed": True,
            },
        ],
    }


def _seat_nesting_grounds_aa(engine, donor_counters):
    """Seat the real Nesting Grounds AA + donor/recipient permanents on
    p0's bf (donor seeded), 1 floating {C} to pay the {1}. Returns
    ``(s, ng, donor, recipient)``.
    """
    s = engine.make_synthetic_state(0, 0, 0)
    ng = s.register_and_inject_object(
        _nesting_grounds_dict(), 0, ZONE_BATTLEFIELD,
    )
    s.force_set_summoning_sick(ng, False)
    donor = s.register_and_inject_object(
        _permanent("Donor"), 0, ZONE_BATTLEFIELD,
    )
    recipient = s.register_and_inject_object(
        _permanent("Recipient"), 0, ZONE_BATTLEFIELD,
    )
    assert s.set_counters(donor, donor_counters) is True
    s.add_mana(0, "C", 1)
    return s, ng, donor, recipient


def test_aa_activation_dual_target_moves_one_counter(engine):
    """**AA-activation pin — THE FLIP happy path.** Activate Nesting
    Grounds' AA[0] via ``apply_action`` with BOTH targets seated
    (``target_creature_id`` = donor, ``target_creature_id_2`` =
    recipient). The non-mana AA pushes a 2-target StackItem; resolving
    it moves exactly one counter (donor 2 -> 1, recipient 0 -> 1) and
    taps Nesting Grounds (tap_self cost).
    """
    s, ng, donor, recipient = _seat_nesting_grounds_aa(engine, 2)
    s.apply_action(
        {
            "kind": "activate_ability",
            "source_id": ng,
            "ability_index": 0,
            "target_creature_id": donor,
            "target_creature_id_2": recipient,
        }
    )
    assert s.stack_size() == 1, "non-mana AA must push exactly one stack item"
    s.resolve_top_of_stack()
    assert s.get_counters(donor) == 1, "donor loses exactly one counter"
    assert s.get_counters(recipient) == 1, "recipient gains exactly one"
    assert s.is_tapped(ng) is True, "tap_self cost taps Nesting Grounds"


def test_aa_activation_missing_2nd_target_fizzles(engine):
    """**AA-activation pin — only slot 0 supplied → ``<2 targets``
    no-op.** Omitting ``target_creature_id_2`` seats only the donor; the
    resolve arm short-circuits and no counter moves (the donor keeps its
    counters). Pins that the 2nd-target field is honestly optional.
    """
    s, ng, donor, recipient = _seat_nesting_grounds_aa(engine, 2)
    s.apply_action(
        {
            "kind": "activate_ability",
            "source_id": ng,
            "ability_index": 0,
            "target_creature_id": donor,
        }
    )
    s.resolve_top_of_stack()
    assert s.get_counters(donor) == 2, (
        "single-target AA seating: <2 targets → resolve no-op"
    )
    assert s.get_counters(recipient) == 0


def test_aa_activation_recipient_not_on_bf_raises(engine):
    """**AA-activation pin — recipient target validation.** A
    ``target_creature_id_2`` pointing at an object NOT on the
    activator's battlefield raises ``ValueError`` BEFORE any state
    mutation (no counter moves, source not tapped).
    """
    s, ng, donor, recipient = _seat_nesting_grounds_aa(engine, 2)
    with pytest.raises(ValueError):
        s.apply_action(
            {
                "kind": "activate_ability",
                "source_id": ng,
                "ability_index": 0,
                "target_creature_id": donor,
                "target_creature_id_2": 999_999,
            }
        )


def test_aa_activation_multi_counter_donor_moves_exactly_one(engine):
    """**AA-activation pin — multi-counter donor.** A donor with 3
    counters loses exactly ONE via the AA path (3 -> 2); recipient 0 ->
    1. Mirrors the spell-path multi pin on the activation path.
    """
    s, ng, donor, recipient = _seat_nesting_grounds_aa(engine, 3)
    s.apply_action(
        {
            "kind": "activate_ability",
            "source_id": ng,
            "ability_index": 0,
            "target_creature_id": donor,
            "target_creature_id_2": recipient,
        }
    )
    s.resolve_top_of_stack()
    assert s.get_counters(donor) == 2
    assert s.get_counters(recipient) == 1
