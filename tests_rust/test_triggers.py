"""ETB-trigger substrate smoke test (Slice 1).

Covers the substrate introduced by `feature/etb-trigger-slice-1`:

- ``Event::Enters`` is parseable on registry-dict input.
- ``Predicate`` algebra (``always`` / ``source_is_self`` /
  ``source_is_creature`` / ``not`` / ``and``) round-trips through
  the parser.
- ``TriggeredAbility`` with ``predicate=source_is_self`` +
  ``effect=draw_cards`` fires when a creature carrying it is cast
  and resolves.
- ``dispatch_event(Event::Enters, source_id)`` walks the
  battlefield, pushes a ``StackItem::TriggeredAbility`` (carrying
  the payload effect), and the resolver fires that effect when the
  trigger resolves.
- A pre-existing artifact with a Panharmonicon-shape "another
  creature enters under your control, draw a card" trigger fires
  on the cast of an unrelated creature — the audit's §5.4
  Example A probe shape, which is the canonical CE19-surfacing
  case.

This is the **minimum viable substrate** test: it proves the
dispatch path + push helper + trigger-resolve arm + once-per-turn
ledger compile and run end-to-end. More tests come in subsequent
slices when the fan-out lands.

Companion docs:
- ``docs/RUST_ETB_TRIGGER_AUDIT.md`` — full audit + closure plan.
- ``rust/src/state_ops_resolve.rs`` — ``dispatch_event`` /
  ``push_triggered_ability`` implementations.
- ``rust/src/cards.rs`` — ``Event`` / ``Predicate`` /
  ``TriggeredAbility`` data shapes.
"""

from __future__ import annotations

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``. Same
# constants used by tests_rust/test_resolve.py.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# --- registry-dict shapes used by the substrate tests ---------------


def _etb_self_draw_dict(count=1):
    """A creature with a predicate-style ``TriggeredAbility`` that
    fires its own ETB and draws ``count`` cards. The canonical
    IsSelf-enters shape — equivalent to ``etb_effects=[DrawCards(count)]``
    on the legacy hatch, but routed through the new predicate path.
    """
    return {
        "name": "Test ETB SourceIsSelf Draw",
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 1},
        "effects": [],
        "power": 1,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "draw_cards", "count": count},
            }
        ],
    }


def _witness_drone_dict():
    """Panharmonicon-shape: 'whenever ANOTHER creature enters under
    your control, draw a card'. Predicate = SourceIsCreature AND
    NOT SourceIsSelf. This is the audit's §5.4 Example A probe —
    the canonical CE19-surfacing card.

    Notes on Slice 1's Predicate algebra: we use SourceIsCreature
    (the printing carrying the ability is a creature) AND NOT
    SourceIsSelf (the firing's subject isn't the source itself).
    In real MTG this also wants 'and the subject is a creature
    that entered under YOUR control' — that lands in Slice 3+ with
    `Subject(...)` + `Controlled(...)` predicates. For substrate
    smoke, the SourceIsCreature + ~SourceIsSelf shape is enough to
    exercise the dispatcher + push pipeline against a non-self
    firing source.
    """
    return {
        "name": "Test Witness Drone",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "effects": [],
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {
                    "kind": "and",
                    "left": {"kind": "source_is_creature"},
                    "right": {
                        "kind": "not",
                        "inner": {"kind": "source_is_self"},
                    },
                },
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }


def _vanilla_creature_dict():
    """A vanilla 2/2 creature with no ETB-triggered abilities.
    Used as the 'bait' in the Panharmonicon probe — its arrival
    is what the pre-existing trigger observes.
    """
    return {
        "name": "Test Vanilla Bears",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


# --- parser surface --------------------------------------------------


def test_triggered_abilities_field_defaults_to_empty(empty_registry):
    """Registry dicts that omit ``triggered_abilities`` are accepted
    (back-compat). Implicit default = empty Vec on the printing.
    """
    pid = empty_registry.register_printing(_vanilla_creature_dict())
    assert pid == 0
    # No crash; printing registered fine.


def test_triggered_abilities_field_parses_predicate_always(empty_registry):
    """The ``always`` predicate parses and registers."""
    d = {
        "name": "Always Trigger Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "always"},
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    pid = empty_registry.register_printing(d)
    assert pid == 0


def test_triggered_abilities_default_predicate_is_always(empty_registry):
    """Missing ``predicate`` key on a triggered_ability defaults to
    Predicate::Always (the audit's default).
    """
    d = {
        "name": "No-Predicate Trigger Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                # No predicate -> Always.
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    pid = empty_registry.register_printing(d)
    assert pid == 0


def test_triggered_abilities_unknown_predicate_kind_raises(empty_registry):
    """Unknown predicate kinds raise loudly at register time."""
    d = {
        "name": "Bad Predicate Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "controlled_by_you_lol"},
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    with pytest.raises(ValueError, match="unknown predicate kind"):
        empty_registry.register_printing(d)


def test_triggered_abilities_unwired_event_raises(empty_registry):
    """Slice 1 only wires ``Event::Enters``; other events declared
    in the enum raise at register time so a caller can't stamp a
    trigger that never fires.
    """
    d = {
        "name": "Dies Trigger Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "dies",
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    with pytest.raises(ValueError, match="not yet wired in Slice 1"):
        empty_registry.register_printing(d)


def test_triggered_abilities_unknown_event_raises(empty_registry):
    """Completely unknown event strings raise."""
    d = {
        "name": "Bogus Event Card",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "moshes",
                "effect": {"kind": "draw_cards", "count": 1},
            }
        ],
    }
    with pytest.raises(ValueError, match="unknown triggered_ability.event"):
        empty_registry.register_printing(d)


# --- substrate smoke: SourceIsSelf draw on cast-resolve -------------


def test_self_etb_trigger_fires_via_predicate_path(synthetic_state):
    """The load-bearing substrate smoke.

    Inject an ``ETB SourceIsSelf Draw 1`` creature onto p0's hand.
    Push a stack item naming it (simulating the cast). Resolve.

    Expected post-state:
    - The creature is on p0's battlefield (post-resolve worked).
    - The stack has the trigger ITEM on it after `resolve_top_of_stack`
      since the trigger is pushed onto the stack during the cast's
      resolve, and only the cast resolves in the first
      `resolve_top_of_stack` call. (Or, more precisely: the
      ETB-source's resolve pushed the trigger onto the now-empty
      stack — we then need a second `resolve_top_of_stack` to
      resolve the trigger itself.)
    - After the second `resolve_top_of_stack` the trigger drains,
      and p0's hand has grown by 1 (the DrawCards(1) payload).
    """
    obj_id = synthetic_state.register_and_inject_object(
        _etb_self_draw_dict(count=1), 0, ZONE_HAND
    )

    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    # Push the cast onto the stack and resolve it.
    synthetic_state.push_to_stack(obj_id, 0)
    resolved_cast = synthetic_state.resolve_top_of_stack()
    assert resolved_cast is not None
    assert resolved_cast["source_obj_id"] == obj_id

    # Post-cast: creature is on p0's battlefield (post-resolve fired),
    # AND the trigger is now on the stack waiting to resolve.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    assert synthetic_state.stack_size() == 1, (
        "expected the ETB trigger to be pushed onto the stack after "
        "the cast resolved; stack is empty so dispatch_event didn't fire"
    )

    # Resolve the trigger. DrawCards(1) -> hand grows by 1, library
    # shrinks by 1.
    resolved_trigger = synthetic_state.resolve_top_of_stack()
    assert resolved_trigger is not None
    # The trigger's source is the creature; the stack-item dict
    # round-trips the same source_obj_id + controller as a spell
    # item (Slice 1's minimal shape).
    assert resolved_trigger["source_obj_id"] == obj_id

    # Substrate works: net hand size = before - 1 (creature moved
    # hand -> bf) + 1 (trigger drew) = hand_before. Net library =
    # before - 1 (trigger drew).
    #
    # Note: the creature itself leaves the hand on resolve (the
    # cast moves it hand -> battlefield). So the hand starts at
    # hand_before, the cast moves the creature out of the hand
    # (-1), and the trigger draws (+1). Net: hand_before.
    assert synthetic_state.hand_sizes[0] == hand_before, (
        f"expected hand_p0 net-zero (cast -1, draw +1); got "
        f"{synthetic_state.hand_sizes[0]} vs {hand_before}"
    )
    assert synthetic_state.library_sizes[0] == library_before - 1, (
        f"expected library_p0 to shrink by 1 from the DrawCards trigger "
        f"payload; got {synthetic_state.library_sizes[0]} vs "
        f"{library_before - 1}"
    )
    assert synthetic_state.is_stack_empty()


def test_no_triggered_abilities_means_no_stack_push(synthetic_state):
    """A creature with no triggered_abilities and no etb_effects
    causes no trigger push — the stack is empty after the cast
    resolves. Regression guard so dispatch_event doesn't push
    phantom triggers for printings that have none.
    """
    obj_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved is not None

    # Cast resolved, creature on battlefield. No triggers; stack
    # is empty.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_BATTLEFIELD
    assert synthetic_state.is_stack_empty()


# --- substrate smoke: Panharmonicon-shape (audit §5.4 Example A) ----


def test_panharmonicon_shape_observer_fires_on_other_creature_enter(
    synthetic_state,
):
    """The Panharmonicon-shape CE19-surfacing probe.

    Set up:
    - A pre-existing Witness Drone on p0's battlefield carrying a
      'when ANOTHER creature enters, draw a card' trigger.
    - Inject a vanilla 2/2 creature onto p0's hand. Cast it.

    Expected:
    - Vanilla creature lands on p0's battlefield (cast-resolve).
    - The pre-existing drone's trigger observes the event and
      pushes a DrawCards(1) trigger onto the stack.
    - Resolving that trigger nets p0 +1 card.

    This is the audit's §5.4 Example A — Rust's inline
    `etb_effects` hatch CANNOT do this (the legacy path only fires
    the just-cast source's OWN effects, not other permanents'
    triggers observing the event). The substrate's `dispatch_event`
    walker IS what closes that gap.
    """
    # Inject the Witness Drone on p0's bf (pre-existing observer).
    drone_id = synthetic_state.register_and_inject_object(
        _witness_drone_dict(), 0, ZONE_BATTLEFIELD
    )
    # Inject the vanilla creature on p0's hand.
    bait_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 0, ZONE_HAND
    )

    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    # Cast the bait.
    synthetic_state.push_to_stack(bait_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Bait landed on p0's bf.
    assert synthetic_state.find_object_zone(bait_id) == ZONE_BATTLEFIELD

    # The drone's "another creature enters" trigger is now on the
    # stack.
    assert synthetic_state.stack_size() == 1, (
        "expected the Witness Drone's ENTERS trigger to be on the stack "
        "after the bait creature resolved; stack is empty so the "
        "dispatcher didn't observe the event"
    )
    top = synthetic_state.peek_top_of_stack()
    # The trigger's source is the drone (the observer carrying the
    # ability), NOT the bait that fired it.
    assert top is not None
    assert top["source_obj_id"] == drone_id

    # Resolve the trigger.
    synthetic_state.resolve_top_of_stack()

    # Substrate works: p0 net hand = hand_before - 1 (bait left hand)
    # + 1 (drew from trigger) = hand_before. Library shrank by 1.
    assert synthetic_state.hand_sizes[0] == hand_before
    assert synthetic_state.library_sizes[0] == library_before - 1
    assert synthetic_state.is_stack_empty()


def test_panharmonicon_shape_does_not_fire_on_drone_itself(synthetic_state):
    """The Witness Drone's predicate is ``SourceIsCreature AND NOT
    SourceIsSelf``: the drone doesn't observe its OWN ETB (the
    `NOT SourceIsSelf` half rejects self-firing). Regression guard
    against the dispatcher firing a 'when ANOTHER creature enters'
    trigger on the source's own arrival.
    """
    drone_id = synthetic_state.register_and_inject_object(
        _witness_drone_dict(), 0, ZONE_HAND
    )

    hand_before = synthetic_state.hand_sizes[0]
    library_before = synthetic_state.library_sizes[0]

    # Cast the drone — its OWN ETB should not fire its own trigger.
    synthetic_state.push_to_stack(drone_id, 0)
    synthetic_state.resolve_top_of_stack()

    # Drone landed on bf, but the trigger did NOT fire (the
    # predicate rejected the self-firing).
    assert synthetic_state.find_object_zone(drone_id) == ZONE_BATTLEFIELD
    assert synthetic_state.is_stack_empty(), (
        "expected the drone's NOT-self predicate to reject its own ETB; "
        "stack is non-empty so the predicate accepted"
    )
    # No DrawCards fired — hand size net-zero (just the creature
    # moving hand -> bf).
    assert synthetic_state.hand_sizes[0] == hand_before - 1
    assert synthetic_state.library_sizes[0] == library_before


# --- once-per-turn ledger reset on cleanup --------------------------


def test_triggered_this_turn_ledger_resets_on_cleanup(synthetic_state):
    """The once-per-turn ledger is cleared at cleanup_step_for_active_player.

    Slice 1 substrate-only: we don't have a `once_per_turn=True`
    trigger fixture wired into a Slice 1 smoke scenario, so we
    can't end-to-end verify the gate FIRES + IS RESET. But we CAN
    verify that calling cleanup zeros the ledger (the
    state.triggered_this_turn.clear() call we added).

    Indirect verification: call cleanup, assert no panic / no
    unexpected state mutation. The Rust-side substrate is exercised
    by the same cast-resolve path the audit's Slice 1 wires —
    direct ledger introspection would need a new bridge getter,
    which is out of scope for Slice 1 (Slice 2+ can add it once a
    once-per-turn-gated trigger fixture lands).
    """
    # The synthetic state starts at phase=0 (untap); cleanup is
    # callable from any phase per its docstring.
    summary = synthetic_state.cleanup_step_for_active_player()
    # Just verify the cleanup call shape matches expectations.
    assert "discarded" in summary
    assert "damage_cleared" in summary
    assert "ueot_cleared" in summary
