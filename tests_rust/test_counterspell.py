"""Counter target spell on the Rust ``GameState``.

Composes round-5's stack slice (``push_to_stack`` / ``stack_size`` /
``is_stack_empty``) and round-1's zone slice (``move_object``) to
implement counter-spell semantics: remove a stack item by source
obj_id and move the source GameObject to its controller's graveyard
(CR 701.6 — countered spells are placed in their owner's graveyard).

Ported from ``tests/test_counter_cancellation.py`` is a misnomer —
that file is about +1/+1 / -1/-1 counter cancellation SBA, not
about the counter-target-spell action. The semantic source of truth
for the *spell-counter* operation is
``src/mtg_bot/effects/generic/stack_control.py:CounterTargetSpell``
(it sets ``item.countered = True`` and the resolution layer later
short-circuits the spell, sending the source to the graveyard).

**Slice scope simplifications** (mirrored in
``rust/src/state_ops_counterspell.rs``):

- **No "can't be countered" enforcement.** A future slice will add
  ``cant_be_countered`` to ``CardPrinting`` and reject here. For
  now we trust the caller picked a legal target.
- **Caller picks the target obj_id.** No verification that the
  source is itself a "counter spell" effect — that's a parser
  decision, not an engine primitive.
- **Source goes to controller's graveyard.** The stack item carries
  the controller; we look up the source GameObject in any zone and
  hand it to ``move_object`` with ``ZONE_GRAVEYARD`` and
  ``stack_item.controller`` as the destination. Real MTG would
  send it to the *owner's* graveyard (which equals controller for
  spells the player cast themselves) — owner tracking is a future
  slice.
- **Duplicate-source semantics: FIFO.** If two stack items share a
  source obj_id (rare but possible — e.g. a copy-this-spell
  effect that re-uses the source), ``counter_spell`` removes the
  bottom-most one (smallest stack index). Matches the existing
  ``remove_from_stack`` primitive's bottom-to-top scan.
- **No replacement effects, no triggers.** "When a spell is
  countered..." triggers (Wickerbough Elder etc.) are deferred.
"""

from __future__ import annotations


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _vanilla_dict():
    """A no-effects printing — we don't need an effect for the
    counter-spell tests because resolve isn't being called. The source
    just needs to exist so the move-to-graveyard step can find it."""
    return {
        "name": "Test Spell",
        "card_types": ["Instant"],
        "mana_cost": {"generic": 1, "U": 1},
        "effects": [],
    }


# --- core remove-from-stack semantics --------------------------------


def test_counter_target_removes_stack_item(synthetic_state):
    """A stack item whose source is obj_id 42 vanishes on counter."""
    synthetic_state.push_to_stack(42, 0)
    assert synthetic_state.stack_size() == 1
    synthetic_state.counter_spell(42)
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.is_stack_empty() is True


def test_counter_target_returns_true_on_success(synthetic_state):
    """``counter_spell`` returns True iff a matching stack item was
    found and removed."""
    synthetic_state.push_to_stack(42, 0)
    assert synthetic_state.counter_spell(42) is True


def test_counter_target_unknown_obj_id_returns_false(synthetic_state):
    """No stack item with the given source -> False, no mutation."""
    synthetic_state.push_to_stack(11, 0)
    assert synthetic_state.counter_spell(99) is False
    # Stack untouched.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": 11,
        "controller": 0,
    }


def test_counter_target_only_removes_one_item_when_duplicates(synthetic_state):
    """Two stack items share source_obj_id 42. ``counter_spell(42)``
    removes ONE — specifically the bottom-most (FIFO, smallest stack
    index), per the underlying ``remove_from_stack`` primitive's
    bottom-to-top scan. The other stays on the stack."""
    synthetic_state.push_to_stack(42, 0)  # bottom
    synthetic_state.push_to_stack(42, 1)  # top
    assert synthetic_state.stack_size() == 2

    assert synthetic_state.counter_spell(42) is True
    assert synthetic_state.stack_size() == 1
    # The remaining item is the one that was pushed second (controller=1)
    # because the bottom one (controller=0) was removed.
    remaining = synthetic_state.peek_top_of_stack()
    assert remaining == {"source_obj_id": 42, "controller": 1}


def test_counter_target_preserves_other_stack_items(synthetic_state):
    """Push A, B, C; counter B; verify A, C remain in original order."""
    synthetic_state.push_to_stack(10, 0)  # A: bottom
    synthetic_state.push_to_stack(20, 1)  # B: middle
    synthetic_state.push_to_stack(30, 0)  # C: top
    assert synthetic_state.stack_size() == 3

    assert synthetic_state.counter_spell(20) is True
    assert synthetic_state.stack_size() == 2
    # Top is still C (30).
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": 30,
        "controller": 0,
    }
    # Pop C and confirm A is now the top.
    synthetic_state.pop_top_of_stack()
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": 10,
        "controller": 0,
    }


# --- source-to-graveyard movement ------------------------------------


def test_counter_target_moves_source_to_graveyard(synthetic_state):
    """End-to-end: register a printing for player 0, inject a
    GameObject onto the battlefield (the spell's "source" — a
    stand-in for whatever zone the spell originated from — for first
    slice we just route to graveyard regardless), push it on the
    stack, counter it. Stack should empty AND the source should
    land in player 0's graveyard."""
    src_obj_id = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_obj_id, 0)
    p0_graveyard_before = synthetic_state.graveyard_sizes[0]

    assert synthetic_state.counter_spell(src_obj_id) is True

    # (a) stack drained.
    assert synthetic_state.is_stack_empty() is True
    # (b) source object in p0's graveyard now.
    assert synthetic_state.find_object_zone(src_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_graveyard_before + 1


def test_counter_does_not_affect_other_players_graveyard(synthetic_state):
    """Controller of countered spell is player 0 -> only p0's
    graveyard size grows; p1's stays put."""
    src_obj_id = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_obj_id, 0)
    p1_graveyard_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.counter_spell(src_obj_id)

    assert synthetic_state.graveyard_sizes[1] == p1_graveyard_before


# --- CoW canary ------------------------------------------------------


def test_clone_then_counter_does_not_affect_original(synthetic_state):
    """Counter on a clone must not bleed into the original — neither
    the stack nor the source's zone on the original side should
    change. Load-bearing CoW test."""
    src_obj_id = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_obj_id, 0)
    cloned = synthetic_state.clone_once()

    assert cloned.counter_spell(src_obj_id) is True
    # Clone: stack drained, source in graveyard.
    assert cloned.is_stack_empty() is True
    assert cloned.find_object_zone(src_obj_id) == ZONE_GRAVEYARD

    # Original: stack still has the item, source still on battlefield.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.find_object_zone(src_obj_id) == ZONE_BATTLEFIELD


# --- cross-feature: primitive (round-7) + Effect::CounterTargetSpell -
# (round-24) dispatch -----------------------------------------------
#
# The tests below span both the `counter_spell(obj_id)` primitive on
# `state_ops_counterspell.rs` (round-7) AND the `Effect::CounterTargetSpell`
# dispatch arm on `state_ops_resolve.rs` (round-24). The dispatch arm
# INLINES the counter logic (per the recurring per-slice file-isolation
# pattern) and uses `source_obj_id` (round-23 `apply_effect` parameter)
# to exclude the resolving counterspell itself from its own target
# search.
#
# Helpers mirror `test_resolve.py`'s `_annul_dict` / `_bombard_for_counter_dict`
# but kept local so this file remains self-contained.


def _annul_dict():
    """An Annul-style counter-target-spell printing dict — drives the
    `Effect::CounterTargetSpell` dispatch arm at resolve time. Instant-typed
    so the post-resolve mover routes the resolved counterspell source to
    its own controller's graveyard (CR 608.2m)."""
    return {
        "name": "Test Annul",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "counter_target_spell"}],
    }


def _vanilla_creature_dict():
    """A target-spell printing for the counterspell to point at. No
    effects — when countered, there's no resolution-time mutation we
    have to worry about. Sorcery-typed so if (against expectation) it
    DID resolve, post-resolve would still route it to a graveyard,
    keeping failure modes loud rather than silent."""
    return {
        "name": "Test Target Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
    }


# --- (1) Effect-driven counterspell: full round-trip through dispatch


def test_effect_counters_creature_beneath_routes_correct_graveyards(
    synthetic_state,
):
    """p1 cast a creature (target on stack below); p0 then casts
    Annul-style counter (on top). Resolve top → the creature gets
    countered → goes to p1's graveyard. The counter source goes to p0's
    graveyard via the post-resolve mover (CR 608.2m). Verifies the
    end-to-end round-24 dispatch arm AND the cross-controller routing
    that round-7 inlines."""
    creature_obj_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(creature_obj_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)
    assert synthetic_state.stack_size() == 2

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.resolve_top_of_stack()

    # Stack drained.
    assert synthetic_state.is_stack_empty() is True
    # Countered creature in p1's graveyard.
    assert synthetic_state.find_object_zone(creature_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1
    # Counter source in p0's graveyard (post-resolve mover).
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1


# --- (2) CounterTargetSpell self-exclusion: source_obj_id-based skip


def test_effect_only_self_on_stack_silent_fizzle_post_resolve_still_moves(
    synthetic_state,
):
    """Stack has ONLY the counterspell. The round-24 dispatch's
    source_obj_id exclusion means the only stack item (self) is skipped
    → no target → silent fizzle. But `resolve_top_of_stack` still pops
    the counterspell's stack item AND routes its source to the
    graveyard via the CR 608.2m post-resolve mover."""
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(counter_obj_id, 0)

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    resolved = synthetic_state.resolve_top_of_stack()
    assert resolved == {"source_obj_id": counter_obj_id, "controller": 0}

    # Stack popped (one item was on stack, fizzle didn't double-pop).
    assert synthetic_state.is_stack_empty() is True
    # Counter source landed in p0's graveyard via post-resolve mover.
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1
    # p1 untouched.
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before


# --- (3) Multiple items on stack: top-down non-self target selection


def test_effect_multiple_items_counters_topmost_non_self(synthetic_state):
    """Stack from bottom: [item_a, item_b, counter]. The dispatch scans
    top-down and picks the FIRST non-self → that's item_b. item_a
    remains pending on the stack."""
    item_a_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    item_b_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(item_a_id, 1)
    synthetic_state.push_to_stack(item_b_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)
    assert synthetic_state.stack_size() == 3

    synthetic_state.resolve_top_of_stack()

    # item_a remains as the lone stack item (counter resolved + popped,
    # item_b countered + removed).
    assert synthetic_state.stack_size() == 1
    top = synthetic_state.peek_top_of_stack()
    assert top == {"source_obj_id": item_a_id, "controller": 1}
    # item_b countered to p1's graveyard; item_a still in hand.
    assert synthetic_state.find_object_zone(item_b_id) == ZONE_GRAVEYARD
    assert synthetic_state.find_object_zone(item_a_id) == ZONE_HAND


# --- (4) Primitive directly: round-7 path, NOT via Effect dispatch


def test_primitive_removes_non_top_item_with_multiple_on_stack(synthetic_state):
    """Push 2 items; call the primitive directly on the BOTTOM one. The
    primitive's bottom-up FIFO scan picks the matching item by obj_id
    regardless of stack position — the top item is untouched."""
    bottom_src_id = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 0, ZONE_BATTLEFIELD
    )
    top_src_id = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 1, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(bottom_src_id, 0)
    synthetic_state.push_to_stack(top_src_id, 1)

    assert synthetic_state.counter_spell(bottom_src_id) is True

    # One item left on the stack — the top one.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": top_src_id,
        "controller": 1,
    }
    # Countered source in p0's graveyard.
    assert synthetic_state.find_object_zone(bottom_src_id) == ZONE_GRAVEYARD
    # Untouched source still on battlefield.
    assert synthetic_state.find_object_zone(top_src_id) == ZONE_BATTLEFIELD


def test_primitive_nonexistent_id_with_items_on_stack_returns_false(
    synthetic_state,
):
    """Push items; call `counter_spell(non_matching_id)`. Returns False
    per the primitive's contract (state_ops_counterspell.rs:127:
    `match self.stack.iter().position(...) { None => return false }`).
    Stack untouched."""
    src_id = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 0, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_id, 0)
    p0_gy_before = synthetic_state.graveyard_sizes[0]

    assert synthetic_state.counter_spell(9999) is False

    # Stack and zones unchanged.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.find_object_zone(src_id) == ZONE_BATTLEFIELD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before


# --- (5) Cross-feature: CR 400.6 / 701.6 — countered spell to ITS
#       controller's graveyard (target controller, NOT counter caster)


def test_effect_countered_spell_routes_to_target_controller_not_caster(
    synthetic_state,
):
    """The countered spell goes to ITS controller's graveyard (the
    target's controller), NOT the counter-caster's. Round-24 reads
    `item.controller` for the target's stack item and routes the
    countered source there. CR 400.6/701.6 + round-7 routing
    convention. With p0 controlling the counterspell and p1
    controlling the targeted spell, the targeted spell lands in p1's
    graveyard."""
    target_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(target_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.resolve_top_of_stack()

    # Target lands in p1's graveyard.
    assert synthetic_state.find_object_zone(target_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1
    # Counter source lands in p0's graveyard (post-resolve mover).
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1


# --- (6) Stack state post-counter via Effect dispatch: snapshot reflects
#       the removal


def test_effect_stack_snapshot_reflects_removal_after_dispatch(synthetic_state):
    """After the round-24 dispatch arm runs, `stack_snapshot()` shows
    the stack with the target removed (the dispatch removed it inline)
    AND with the counter's own stack item popped (the outer
    `resolve_top_of_stack` post-pops). Verifies the bridge-level
    snapshot view stays consistent with the inlined Vec::remove."""
    item_a_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    item_b_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(item_a_id, 1)
    synthetic_state.push_to_stack(item_b_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)

    snap_before = synthetic_state.stack_snapshot()
    assert len(snap_before) == 3
    assert [s["source_obj_id"] for s in snap_before] == [
        item_a_id,
        item_b_id,
        counter_obj_id,
    ]

    synthetic_state.resolve_top_of_stack()

    snap_after = synthetic_state.stack_snapshot()
    # Only item_a remains (item_b countered, counter popped).
    assert len(snap_after) == 1
    assert snap_after[0] == {"source_obj_id": item_a_id, "controller": 1}


# --- (7) Empty stack beneath: same as (2) but verified explicitly via
#       the resolve return value's preservation of the popped item


def test_effect_resolve_returns_counter_item_when_fizzle(synthetic_state):
    """`resolve_top_of_stack()` returns the popped item dict. When the
    counter fizzles (nothing-to-counter), the return value is still the
    counter's stack item — not None, not the countered item (since
    there isn't one). Guards against an off-by-one where the fizzle
    path accidentally pops twice or returns a stale dict."""
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(counter_obj_id, 0)

    resolved = synthetic_state.resolve_top_of_stack()

    assert resolved == {"source_obj_id": counter_obj_id, "controller": 0}
    assert synthetic_state.is_stack_empty() is True


# --- (8) Multiple counterspells in sequence: counter_B counters counter_A


def test_effect_counter_counters_other_counter_creature_remains(synthetic_state):
    """Stack from bottom: [creature, counter_A, counter_B]. Resolve top
    (counter_B) → counter_B picks the topmost non-self → counter_A.
    counter_A's stack item is removed and counter_A's source moves to
    its controller's graveyard (p0). counter_B's own stack item is then
    popped by the outer resolver and its source moves to its
    controller's graveyard (p1) via the post-resolve mover. The
    creature remains on the stack, pending."""
    creature_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    counter_a_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    counter_b_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 1, ZONE_HAND
    )
    # Stack bottom→top: creature (p1), counter_A (p0), counter_B (p1).
    synthetic_state.push_to_stack(creature_id, 1)
    synthetic_state.push_to_stack(counter_a_id, 0)
    synthetic_state.push_to_stack(counter_b_id, 1)

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.resolve_top_of_stack()

    # Stack has just the creature left.
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": creature_id,
        "controller": 1,
    }
    # Creature still in hand (not resolved).
    assert synthetic_state.find_object_zone(creature_id) == ZONE_HAND
    # counter_A countered → p0's graveyard.
    assert synthetic_state.find_object_zone(counter_a_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1
    # counter_B post-resolved → p1's graveyard.
    assert synthetic_state.find_object_zone(counter_b_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1


# --- bonus: Effect-driven counter with CoW: parallels the primitive's
#       clone canary but exercises the Effect dispatch path


def test_effect_clone_then_resolve_counter_does_not_affect_original(
    synthetic_state,
):
    """CoW canary across the Effect dispatch arm. Resolving the
    counterspell on a clone removes the target from the clone's stack,
    routes both sources to the clone's graveyards, but the original's
    stack and zones are untouched. Load-bearing because the inline
    counter logic in `Effect::CounterTargetSpell` calls Arc::make_mut
    on multiple zones."""
    target_id = synthetic_state.register_and_inject_object(
        _vanilla_creature_dict(), 1, ZONE_HAND
    )
    counter_obj_id = synthetic_state.register_and_inject_object(
        _annul_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(target_id, 1)
    synthetic_state.push_to_stack(counter_obj_id, 0)
    cloned = synthetic_state.clone_once()

    cloned.resolve_top_of_stack()

    # Clone: stack drained, both sources in respective graveyards.
    assert cloned.is_stack_empty() is True
    assert cloned.find_object_zone(target_id) == ZONE_GRAVEYARD
    assert cloned.find_object_zone(counter_obj_id) == ZONE_GRAVEYARD

    # Original: stack still has 2, both sources still in hand.
    assert synthetic_state.stack_size() == 2
    assert synthetic_state.find_object_zone(target_id) == ZONE_HAND
    assert synthetic_state.find_object_zone(counter_obj_id) == ZONE_HAND


# --- bonus: primitive returning False does NOT touch the source on
#       battlefield (zone unchanged)


def test_primitive_returns_false_does_not_move_unrelated_objects(
    synthetic_state,
):
    """When `counter_spell(unknown_id)` returns False, no GameObject
    moves. Specifically guards against a bug where the primitive would
    speculatively route SOMETHING to a graveyard before the
    found/not-found check."""
    src_a = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 0, ZONE_BATTLEFIELD
    )
    src_b = synthetic_state.register_and_inject_object(
        _vanilla_dict(), 1, ZONE_BATTLEFIELD
    )
    synthetic_state.push_to_stack(src_a, 0)
    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    assert synthetic_state.counter_spell(9999) is False

    # Neither source moved; graveyard sizes unchanged.
    assert synthetic_state.find_object_zone(src_a) == ZONE_BATTLEFIELD
    assert synthetic_state.find_object_zone(src_b) == ZONE_BATTLEFIELD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before
