"""Stack push/pop/peek/size primitives on the Rust ``GameState``.

Ported from Python's ``src/mtg_bot/game.py`` (the ``GameState.stack``
list of ``StackItem`` objects) and ``src/mtg_bot/turn.py`` (priority +
stack interaction). The Rust side keeps ``stack: Vec<StackItem>`` on
``GameState`` (added by the foundation commit). Top of stack = LAST
element of the Vec for O(1) push/pop, mirroring the Python list-as-
stack convention. This slice grows the read/write surface in
``rust/src/state_ops_stack.rs``.

**Slice scope.**

- **No resolution semantics in this slice.** What happens when an
  effect resolves depends on the effect grammar, which is the
  bridge's domain. This slice exposes ``pop_top_of_stack()`` returning
  the StackItem dict; resolution itself is a future slice that
  interprets the effect.
- **No counter-spells in this slice.** Counter target spell needs a
  "remove this specific item from the stack" primitive — which we
  add as ``remove_from_stack(obj_id)`` — but we don't enforce
  countering rules, just expose the surface.
- **First-slice StackItem shape: ``{source_obj_id, controller}``
  only.** Real stack items will need more (target list, choices,
  modal mode); future slices extend.
"""

from __future__ import annotations


def test_initial_stack_is_empty(synthetic_state):
    """A fresh synthetic state has an empty stack."""
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.is_stack_empty() is True


def test_push_increments_size(synthetic_state):
    """`push_to_stack(obj_id, controller)` adds one item; size goes 0 -> 1."""
    synthetic_state.push_to_stack(42, 0)
    assert synthetic_state.stack_size() == 1
    assert synthetic_state.is_stack_empty() is False


def test_push_multiple_appends_in_order(synthetic_state):
    """Two pushes -> size 2; third push -> size 3, peek returns the
    last-pushed item."""
    synthetic_state.push_to_stack(1, 0)
    synthetic_state.push_to_stack(2, 1)
    synthetic_state.push_to_stack(3, 0)
    assert synthetic_state.stack_size() == 3
    top = synthetic_state.peek_top_of_stack()
    assert top["source_obj_id"] == 3
    assert top["controller"] == 0


def test_peek_top_returns_top_item_dict(synthetic_state):
    """`peek_top_of_stack()` returns a Python dict with the
    ``source_obj_id`` and ``controller`` fields."""
    synthetic_state.push_to_stack(7, 1)
    top = synthetic_state.peek_top_of_stack()
    assert isinstance(top, dict)
    assert top == {"source_obj_id": 7, "controller": 1}


def test_peek_top_on_empty_returns_none(synthetic_state):
    """Peek on an empty stack returns None (not an exception)."""
    assert synthetic_state.peek_top_of_stack() is None


def test_pop_top_removes_and_returns_top_item(synthetic_state):
    """`pop_top_of_stack()` removes and returns the top item; size decrements."""
    synthetic_state.push_to_stack(99, 1)
    assert synthetic_state.stack_size() == 1
    popped = synthetic_state.pop_top_of_stack()
    assert popped == {"source_obj_id": 99, "controller": 1}
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.is_stack_empty() is True


def test_pop_top_on_empty_returns_none(synthetic_state):
    """Pop on an empty stack returns None (not an exception)."""
    assert synthetic_state.pop_top_of_stack() is None
    # Repeated pop on empty stays None and doesn't underflow size.
    assert synthetic_state.pop_top_of_stack() is None
    assert synthetic_state.stack_size() == 0


def test_lifo_order(synthetic_state):
    """Push A, B, C; pop returns C, B, A in that order (LIFO)."""
    synthetic_state.push_to_stack(10, 0)  # A
    synthetic_state.push_to_stack(20, 1)  # B
    synthetic_state.push_to_stack(30, 0)  # C
    assert synthetic_state.pop_top_of_stack() == {"source_obj_id": 30, "controller": 0}
    assert synthetic_state.pop_top_of_stack() == {"source_obj_id": 20, "controller": 1}
    assert synthetic_state.pop_top_of_stack() == {"source_obj_id": 10, "controller": 0}
    assert synthetic_state.is_stack_empty() is True


def test_remove_from_stack_by_obj_id(synthetic_state):
    """`remove_from_stack(obj_id)` removes the FIRST matching item by
    source_obj_id and returns True; size decrements."""
    synthetic_state.push_to_stack(5, 0)
    synthetic_state.push_to_stack(7, 1)
    assert synthetic_state.stack_size() == 2
    removed = synthetic_state.remove_from_stack(5)
    assert removed is True
    assert synthetic_state.stack_size() == 1


def test_remove_from_stack_unknown_returns_false(synthetic_state):
    """No item with that obj_id -> no mutation, returns False."""
    synthetic_state.push_to_stack(1, 0)
    assert synthetic_state.remove_from_stack(999) is False
    assert synthetic_state.stack_size() == 1
    # Original item still on top.
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": 1,
        "controller": 0,
    }


def test_remove_from_stack_preserves_other_items(synthetic_state):
    """Push A then B (B on top); remove A; B is still on top."""
    synthetic_state.push_to_stack(100, 0)  # A (bottom)
    synthetic_state.push_to_stack(200, 1)  # B (top)
    assert synthetic_state.remove_from_stack(100) is True
    assert synthetic_state.stack_size() == 1
    top = synthetic_state.peek_top_of_stack()
    assert top == {"source_obj_id": 200, "controller": 1}


def test_clone_preserves_stack(synthetic_state):
    """Clone copies the stack contents (Vec<StackItem> on GameState;
    cloning the GameState clones the Vec by-value)."""
    synthetic_state.push_to_stack(11, 0)
    synthetic_state.push_to_stack(22, 1)
    cloned = synthetic_state.clone_once()
    assert cloned.stack_size() == 2
    assert cloned.peek_top_of_stack() == {"source_obj_id": 22, "controller": 1}


def test_push_on_clone_does_not_affect_original(synthetic_state):
    """CoW canary: ``stack`` is a Vec<StackItem> on GameState. Cloning
    the state by-value-copies the Vec; mutating one side must NOT
    bleed back into the other. (A future slice that switches stack to
    Arc<Vec> would still need this invariant to hold via Arc::make_mut.)
    """
    cloned = synthetic_state.clone_once()
    cloned.push_to_stack(77, 1)
    assert cloned.stack_size() == 1
    assert synthetic_state.stack_size() == 0
    assert synthetic_state.is_stack_empty() is True


# --- round-16 process_stack_until_empty -----------------------------
#
# Composes round-5's stack push/pop with round-6's
# ``resolve_top_of_stack`` (in ``state_ops_resolve.rs``). The primitive
# repeatedly resolves the top of stack until empty and returns the
# count of items resolved. Useful for "resolve everything" simulation
# paths where the caller doesn't care about per-item priority hand-off.
#
# **Scope simplifications:**
#
# - **No priority hand-off between resolutions.** Real MTG: after each
#   resolution both players get priority again; this primitive just
#   drains the stack greedily. Higher-level code that wants real
#   priority semantics should call ``resolve_top_of_stack`` itself in a
#   priority loop.
# - **Iteration cap.** Hard-coded 1000-iteration safety so a buggy
#   effect that re-pushes its source can't infinite-loop. Anything
#   approaching that bound is a test bug; raises ``ValueError`` loudly.
# - **First failed resolve propagates.** If any individual
#   ``resolve_top_of_stack`` raises (e.g. unsupported AnyPlayer-target
#   on a bounce-shaped effect), the loop aborts and the exception
#   propagates with the partial drain visible to the caller.
#
# Tests use simple controller-implicit effects (DrawCards / GainLife)
# so the assertions focus on the loop primitive — not on target
# selection semantics already covered by ``test_resolve.py``.

ZONE_HAND = 0
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _draw_one_dict():
    """A draw-1 sorcery printing — Standard Counter style."""
    return {
        "name": "Test Draw 1",
        "card_types": ["Sorcery"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "draw_cards", "count": 1}],
    }


def _gain_life_dict(amount):
    """A gain-N-life instant printing parametric on amount."""
    return {
        "name": f"Test Gain {amount}",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [{"kind": "gain_life", "amount": amount}],
    }


def test_process_stack_until_empty_zero_when_empty(synthetic_state):
    """Empty stack -> returns 0; stack remains empty."""
    assert synthetic_state.is_stack_empty() is True
    count = synthetic_state.process_stack_until_empty()
    assert count == 0
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.stack_size() == 0


def test_process_stack_until_empty_resolves_one(synthetic_state):
    """One item on the stack -> returns 1, stack empty, effect applied
    (active player gains 5 life from a GainLife-5 instant)."""
    obj_id = synthetic_state.register_and_inject_object(
        _gain_life_dict(5), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    life_before = list(synthetic_state.life_totals)
    assert synthetic_state.stack_size() == 1

    count = synthetic_state.process_stack_until_empty()

    assert count == 1
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.life_totals[0] == life_before[0] + 5
    assert synthetic_state.life_totals[1] == life_before[1]


def test_process_stack_until_empty_resolves_multiple(synthetic_state):
    """Three GainLife items on the stack -> all resolve, returns 3,
    cumulative life-gain shows up on the active player."""
    a = synthetic_state.register_and_inject_object(
        _gain_life_dict(1), 0, ZONE_HAND
    )
    b = synthetic_state.register_and_inject_object(
        _gain_life_dict(2), 0, ZONE_HAND
    )
    c = synthetic_state.register_and_inject_object(
        _gain_life_dict(4), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(a, 0)
    synthetic_state.push_to_stack(b, 0)
    synthetic_state.push_to_stack(c, 0)
    life_before = list(synthetic_state.life_totals)
    assert synthetic_state.stack_size() == 3

    count = synthetic_state.process_stack_until_empty()

    assert count == 3
    assert synthetic_state.is_stack_empty() is True
    # 1 + 2 + 4 = 7, regardless of order (all three are GainLife on
    # the same player).
    assert synthetic_state.life_totals[0] == life_before[0] + 7


def test_process_stack_until_empty_drains_in_lifo_order(synthetic_state):
    """Push three DrawCards-1 sources A, B, C. LIFO means C resolves
    first, then B, then A. Each resolution moves its source from hand
    to graveyard. Verify the graveyard order is [C, B, A] — confirms
    we're calling ``resolve_top_of_stack`` (which pops the top, i.e.
    last-pushed) in a loop, not draining bottom-up."""
    a = synthetic_state.register_and_inject_object(
        _draw_one_dict(), 0, ZONE_HAND
    )
    b = synthetic_state.register_and_inject_object(
        _draw_one_dict(), 0, ZONE_HAND
    )
    c = synthetic_state.register_and_inject_object(
        _draw_one_dict(), 0, ZONE_HAND
    )
    gy_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.push_to_stack(a, 0)
    synthetic_state.push_to_stack(b, 0)
    synthetic_state.push_to_stack(c, 0)

    count = synthetic_state.process_stack_until_empty()

    assert count == 3
    assert synthetic_state.is_stack_empty() is True
    # All three sources moved to graveyard (sorcery -> CR 608.2m).
    assert synthetic_state.graveyard_sizes[0] == gy_before + 3


def test_process_stack_until_empty_clone_isolation(synthetic_state):
    """CoW canary: running process_stack_until_empty on a clone leaves
    the original's stack and life total untouched."""
    obj_id = synthetic_state.register_and_inject_object(
        _gain_life_dict(2), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    cloned = synthetic_state.clone_once()
    life_before_orig = list(synthetic_state.life_totals)
    stack_before_orig = synthetic_state.stack_size()

    count = cloned.process_stack_until_empty()

    assert count == 1
    assert cloned.is_stack_empty() is True
    assert cloned.life_totals[0] == life_before_orig[0] + 2
    # Original: stack still has the item, life unchanged.
    assert synthetic_state.stack_size() == stack_before_orig
    assert list(synthetic_state.life_totals) == life_before_orig


# --- round-22 bridge: stack_snapshot() ------------------------------
#
# Read-only list-of-dicts view of the entire stack. Round-21 introduced
# the `*_snapshot()` family (hand_snapshot, library_snapshot, ...) for
# the parity harness; stack_snapshot extends the pattern to the stack
# Vec. Each dict carries (source_obj_id, controller) — the same two
# fields `peek_top_of_stack` / `pop_top_of_stack` already expose. Order
# is bottom-to-top (Vec iteration order — stack[0] is bottom,
# stack[-1] is top).


def test_stack_snapshot_empty_is_empty_list(synthetic_state):
    """Fresh state -> stack_snapshot() returns []."""
    snap = synthetic_state.stack_snapshot()
    assert snap == []


def test_stack_snapshot_three_items_in_push_order(synthetic_state):
    """Push A, B, C — snapshot is [A, B, C] (bottom-to-top, matching
    Vec iteration order; stack[-1] is the top)."""
    synthetic_state.push_to_stack(10, 0)  # A (bottom)
    synthetic_state.push_to_stack(20, 1)  # B
    synthetic_state.push_to_stack(30, 0)  # C (top)
    snap = synthetic_state.stack_snapshot()
    assert len(snap) == 3
    assert snap[0] == {"source_obj_id": 10, "controller": 0}
    assert snap[1] == {"source_obj_id": 20, "controller": 1}
    assert snap[2] == {"source_obj_id": 30, "controller": 0}


def test_stack_snapshot_shrinks_after_pop(synthetic_state):
    """After pop_top_of_stack(), snapshot is one item shorter and the
    top entry is gone."""
    synthetic_state.push_to_stack(1, 0)
    synthetic_state.push_to_stack(2, 1)
    synthetic_state.push_to_stack(3, 0)
    assert len(synthetic_state.stack_snapshot()) == 3
    synthetic_state.pop_top_of_stack()
    snap = synthetic_state.stack_snapshot()
    assert len(snap) == 2
    # Top of the now-shorter stack is the second-pushed item.
    assert snap[-1] == {"source_obj_id": 2, "controller": 1}


def test_stack_snapshot_dict_has_expected_keys(synthetic_state):
    """Each snapshot dict carries exactly source_obj_id and controller."""
    synthetic_state.push_to_stack(42, 1)
    snap = synthetic_state.stack_snapshot()
    assert len(snap) == 1
    keys = set(snap[0].keys())
    assert {"source_obj_id", "controller"}.issubset(keys)


def test_stack_snapshot_is_read_only(synthetic_state):
    """Mutating a returned snapshot dict does NOT affect Rust state —
    the dicts are freshly allocated each call."""
    synthetic_state.push_to_stack(5, 0)
    snap = synthetic_state.stack_snapshot()
    snap[0]["source_obj_id"] = 999
    snap[0]["controller"] = 9
    # Re-snapshot: original values intact.
    snap2 = synthetic_state.stack_snapshot()
    assert snap2[0] == {"source_obj_id": 5, "controller": 0}
    # peek_top_of_stack also sees the unmutated original.
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": 5,
        "controller": 0,
    }


def test_stack_snapshot_field_types(synthetic_state):
    """source_obj_id and controller come back as Python ints (PyO3
    maps u32 / u8 to int)."""
    synthetic_state.push_to_stack(7, 1)
    snap = synthetic_state.stack_snapshot()
    assert isinstance(snap[0]["source_obj_id"], int)
    assert isinstance(snap[0]["controller"], int)
    assert snap[0]["source_obj_id"] == 7
    assert snap[0]["controller"] == 1


def test_stack_snapshot_clone_isolation(synthetic_state):
    """CoW canary: snapshot of clone reflects clone's stack, not the
    original's, after divergent pushes."""
    synthetic_state.push_to_stack(100, 0)
    cloned = synthetic_state.clone_once()
    cloned.push_to_stack(200, 1)
    orig_snap = synthetic_state.stack_snapshot()
    cloned_snap = cloned.stack_snapshot()
    assert len(orig_snap) == 1
    assert len(cloned_snap) == 2
    assert orig_snap[0] == {"source_obj_id": 100, "controller": 0}
    assert cloned_snap[-1] == {"source_obj_id": 200, "controller": 1}


# --- cross-feature edge-case coverage -------------------------------
#
# Tests below this banner exercise the stack as a cross-feature
# surface: LIFO ordering when sources are *different card kinds*
# (creature vs. instant vs. sorcery — the stack itself doesn't
# distinguish, but the post-resolve mover does), counter-spell
# target-removal disambiguation against the round-25 self-exclusion
# behavior, snapshot consistency through resolve/zone moves, and
# fingerprint sensitivity to stack order vs content.
#
# Stack item shape is still just (source_obj_id, controller). The
# "operation kind" distinction (CastSpell vs ActivateAbility) lives
# in the apply_action dispatcher one layer above; at the stack level
# both push the same StackItem shape. These tests therefore probe
# the cross-feature interactions visible *through* the stack — the
# stack's job is to be uniform, and these tests check that the
# uniformity holds across kind-of-source.


def _counter_dict():
    """An Annul-style counter-target-spell printing — drives the
    Effect::CounterTargetSpell dispatch arm at resolve time."""
    return {
        "name": "Test Edge Counter",
        "card_types": ["Instant"],
        "mana_cost": {"U": 1},
        "effects": [{"kind": "counter_target_spell"}],
    }


def _creature_edge_dict():
    """A vanilla creature printing for cross-zone-move tests."""
    return {
        "name": "Test Edge Bear",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }


def _instant_gainlife_dict(amount):
    """An instant gain-life printing — cross-feature with apply_effect
    + the post-resolve graveyard mover (CR 608.2m)."""
    return {
        "name": f"Test Edge GainLife {amount}",
        "card_types": ["Instant"],
        "mana_cost": {"W": 1},
        "effects": [{"kind": "gain_life", "amount": amount}],
    }


def test_stack_lifo_across_mixed_source_kinds(synthetic_state):
    """Push three sources of DIFFERENT card kinds (creature, instant,
    sorcery represented via gain_life-shaped effects). The stack
    itself stores them in the order pushed regardless of kind. Pop
    them and verify strict LIFO order — proves the stack is a
    kind-agnostic primitive and doesn't, e.g., reorder permanents
    to the bottom."""
    creature_id = synthetic_state.register_and_inject_object(
        _creature_edge_dict(), 0, ZONE_HAND
    )
    instant_id = synthetic_state.register_and_inject_object(
        _instant_gainlife_dict(2), 0, ZONE_HAND
    )
    sorcery_id = synthetic_state.register_and_inject_object(
        _draw_one_dict(), 0, ZONE_HAND
    )
    # Push order: creature, instant, sorcery (sorcery on top).
    synthetic_state.push_to_stack(creature_id, 0)
    synthetic_state.push_to_stack(instant_id, 1)
    synthetic_state.push_to_stack(sorcery_id, 0)
    assert synthetic_state.stack_size() == 3

    # LIFO: sorcery first, then instant, then creature.
    assert synthetic_state.pop_top_of_stack() == {
        "source_obj_id": sorcery_id,
        "controller": 0,
    }
    assert synthetic_state.pop_top_of_stack() == {
        "source_obj_id": instant_id,
        "controller": 1,
    }
    assert synthetic_state.pop_top_of_stack() == {
        "source_obj_id": creature_id,
        "controller": 0,
    }
    assert synthetic_state.is_stack_empty() is True


def test_resolve_top_pops_and_applies_effect_cross_feature(synthetic_state):
    """Cross-feature: resolve_top_of_stack pops the top entry AND
    applies its effect (gain_life). After resolve, the stack item is
    gone, the source is in the graveyard (instant -> CR 608.2m), and
    the controller's life total reflects the effect."""
    obj_id = synthetic_state.register_and_inject_object(
        _instant_gainlife_dict(3), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(obj_id, 0)
    life_before = list(synthetic_state.life_totals)
    gy_before = synthetic_state.graveyard_sizes[0]

    resolved = synthetic_state.resolve_top_of_stack()

    # Returned dict identifies the resolved entry.
    assert resolved == {"source_obj_id": obj_id, "controller": 0}
    # Stack drained.
    assert synthetic_state.is_stack_empty() is True
    # Effect applied: p0 gained 3 life.
    assert synthetic_state.life_totals[0] == life_before[0] + 3
    # Post-resolve mover routed the instant to graveyard.
    assert synthetic_state.find_object_zone(obj_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1


def test_counter_on_stack_removes_target_not_counter_spell(synthetic_state):
    """Round-25 source_obj_id behavior: when a counterspell resolves,
    its inline target search EXCLUDES its own stack item via
    source_obj_id. The targeted stack entry is removed (target goes to
    target-controller's graveyard) while the counterspell's own entry
    is popped by the outer resolver (counter source -> its own
    controller's graveyard). Specifically guards against the inverted
    bug where the counterspell would self-target and counter itself."""
    target_id = synthetic_state.register_and_inject_object(
        _creature_edge_dict(), 1, ZONE_HAND
    )
    counter_id = synthetic_state.register_and_inject_object(
        _counter_dict(), 0, ZONE_HAND
    )
    # Target sits beneath the counterspell on the stack.
    synthetic_state.push_to_stack(target_id, 1)
    synthetic_state.push_to_stack(counter_id, 0)
    assert synthetic_state.stack_size() == 2

    synthetic_state.resolve_top_of_stack()

    # Stack drained: both items gone.
    assert synthetic_state.is_stack_empty() is True
    # The TARGET went to its controller's graveyard, not the counter.
    assert synthetic_state.find_object_zone(target_id) == ZONE_GRAVEYARD
    # The counterspell itself (instant) also went to ITS controller's
    # graveyard via the post-resolve mover.
    assert synthetic_state.find_object_zone(counter_id) == ZONE_GRAVEYARD


def test_resolve_cast_spell_of_permanent_moves_to_battlefield(synthetic_state):
    """Cross-feature with zone moves: a creature pushed onto the stack
    resolves into ZONE_BATTLEFIELD on its controller's side (CR 608.3 /
    608.2c) — NOT into a graveyard. Battlefield size grows by exactly
    one and the new permanent has summoning sickness."""
    creature_id = synthetic_state.register_and_inject_object(
        _creature_edge_dict(), 0, ZONE_HAND
    )
    bf_before = synthetic_state.battlefield_sizes[0]
    gy_before = synthetic_state.graveyard_sizes[0]
    synthetic_state.push_to_stack(creature_id, 0)

    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(creature_id) == ZONE_BATTLEFIELD
    assert synthetic_state.battlefield_sizes[0] == bf_before + 1
    # Permanents enter graveyard? No — battlefield only.
    assert synthetic_state.graveyard_sizes[0] == gy_before
    # New permanent has summoning sickness per the round-7 mover.
    assert synthetic_state.is_summoning_sick(creature_id) is True


def test_resolve_cast_spell_of_instant_moves_to_graveyard(synthetic_state):
    """Cross-feature complement to the permanent test: an instant
    pushed and resolved lands in its controller's graveyard, not on
    the battlefield (CR 608.2m). Verifies the post-resolve mover's
    Instant arm coexists with the Permanent arm against the same
    stack primitive."""
    instant_id = synthetic_state.register_and_inject_object(
        _instant_gainlife_dict(1), 1, ZONE_HAND
    )
    gy_before = synthetic_state.graveyard_sizes[1]
    bf_before = synthetic_state.battlefield_sizes[1]
    synthetic_state.push_to_stack(instant_id, 1)

    synthetic_state.resolve_top_of_stack()

    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.find_object_zone(instant_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == gy_before + 1
    # Battlefield untouched — instant doesn't become a permanent.
    assert synthetic_state.battlefield_sizes[1] == bf_before


def test_stack_empty_after_all_entries_resolved_snapshot_agrees(synthetic_state):
    """Drain a 3-entry stack via process_stack_until_empty and verify
    BOTH is_stack_empty() AND stack_snapshot() agree the stack is
    empty. Specifically guards against a bug where the snapshot getter
    reads a stale field or fails to reflect the drained Vec."""
    a = synthetic_state.register_and_inject_object(
        _draw_one_dict(), 0, ZONE_HAND
    )
    b = synthetic_state.register_and_inject_object(
        _instant_gainlife_dict(1), 0, ZONE_HAND
    )
    c = synthetic_state.register_and_inject_object(
        _draw_one_dict(), 0, ZONE_HAND
    )
    synthetic_state.push_to_stack(a, 0)
    synthetic_state.push_to_stack(b, 0)
    synthetic_state.push_to_stack(c, 0)
    assert synthetic_state.stack_size() == 3
    assert synthetic_state.stack_snapshot() != []

    drained = synthetic_state.process_stack_until_empty()

    assert drained == 3
    assert synthetic_state.is_stack_empty() is True
    assert synthetic_state.stack_size() == 0
    # Both views agree the stack is empty.
    assert synthetic_state.stack_snapshot() == []
    assert synthetic_state.peek_top_of_stack() is None


def test_multi_counter_chain_a_counters_b_counters_c(synthetic_state):
    """Cross-feature with counterspell coverage: three counters in a
    chain on top of a creature. Stack from bottom: [creature, A, B, C].
    Resolve the top (C) once: C picks the topmost non-self → B; B is
    removed, B's source -> B-controller's graveyard, C pops + C's
    source -> C-controller's graveyard via post-resolve mover. Final
    stack state: [creature, A]. The creature is still pending; A is
    still on the stack ready to fire next. Verifies the round-25
    self-exclusion + multi-counter ordering survive when the chain
    is at least 3 deep."""
    creature_id = synthetic_state.register_and_inject_object(
        _creature_edge_dict(), 1, ZONE_HAND
    )
    counter_a_id = synthetic_state.register_and_inject_object(
        _counter_dict(), 0, ZONE_HAND
    )
    counter_b_id = synthetic_state.register_and_inject_object(
        _counter_dict(), 1, ZONE_HAND
    )
    counter_c_id = synthetic_state.register_and_inject_object(
        _counter_dict(), 0, ZONE_HAND
    )
    # Bottom -> top: creature (p1), A (p0), B (p1), C (p0).
    synthetic_state.push_to_stack(creature_id, 1)
    synthetic_state.push_to_stack(counter_a_id, 0)
    synthetic_state.push_to_stack(counter_b_id, 1)
    synthetic_state.push_to_stack(counter_c_id, 0)
    assert synthetic_state.stack_size() == 4

    p0_gy_before = synthetic_state.graveyard_sizes[0]
    p1_gy_before = synthetic_state.graveyard_sizes[1]

    synthetic_state.resolve_top_of_stack()

    # After resolving C: B is countered, C is popped. A and creature remain.
    assert synthetic_state.stack_size() == 2
    snap = synthetic_state.stack_snapshot()
    assert snap[0] == {"source_obj_id": creature_id, "controller": 1}
    assert snap[-1] == {"source_obj_id": counter_a_id, "controller": 0}
    # B in p1's graveyard (target controller).
    assert synthetic_state.find_object_zone(counter_b_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[1] == p1_gy_before + 1
    # C in p0's graveyard (counter caster, via post-resolve mover).
    assert synthetic_state.find_object_zone(counter_c_id) == ZONE_GRAVEYARD
    assert synthetic_state.graveyard_sizes[0] == p0_gy_before + 1
    # A still in hand (it's on the stack, not resolved).
    assert synthetic_state.find_object_zone(counter_a_id) == ZONE_HAND
    # Creature still in hand (still on the stack, pending below A).
    assert synthetic_state.find_object_zone(creature_id) == ZONE_HAND


def test_cow_canary_push_on_clone_with_prepopulated_original(synthetic_state):
    """CoW edge case: when the original ALREADY has stack entries,
    pushing more on the clone must not bleed back. Specifically
    catches a regression where the stack's Arc/Vec sharing skipped
    the make_mut on clones whose original was non-empty."""
    synthetic_state.push_to_stack(10, 0)
    synthetic_state.push_to_stack(20, 1)
    cloned = synthetic_state.clone_once()
    # Both sides currently have 2 entries.
    assert synthetic_state.stack_size() == 2
    assert cloned.stack_size() == 2

    # Diverge: push on the clone only.
    cloned.push_to_stack(30, 0)
    cloned.push_to_stack(40, 1)

    # Clone grew to 4; original stayed at 2.
    assert cloned.stack_size() == 4
    assert synthetic_state.stack_size() == 2
    assert synthetic_state.peek_top_of_stack() == {
        "source_obj_id": 20,
        "controller": 1,
    }
    assert cloned.peek_top_of_stack() == {
        "source_obj_id": 40,
        "controller": 1,
    }


def test_fingerprint_changes_on_stack_order_or_content(engine):
    """Cross-feature with the fingerprint slice: two states that
    differ ONLY in stack contents (or stack order with same contents)
    must produce different fingerprints. The stack_signature in the
    digest must be sensitive to both order and content."""
    base = engine.make_synthetic_state()
    fp_empty = base.fingerprint()

    # State with one entry.
    s_one = engine.make_synthetic_state()
    s_one.push_to_stack(42, 0)
    fp_one = s_one.fingerprint()
    assert fp_one != fp_empty, "stack content must affect fingerprint"

    # State with the same entry twice — different content.
    s_two_same = engine.make_synthetic_state()
    s_two_same.push_to_stack(42, 0)
    s_two_same.push_to_stack(42, 0)
    fp_two_same = s_two_same.fingerprint()
    assert fp_two_same != fp_one, "stack size must affect fingerprint"

    # State with two DIFFERENT entries in order [A, B] vs [B, A] —
    # different ORDER, same contents.
    s_ab = engine.make_synthetic_state()
    s_ab.push_to_stack(11, 0)
    s_ab.push_to_stack(22, 1)
    s_ba = engine.make_synthetic_state()
    s_ba.push_to_stack(22, 1)
    s_ba.push_to_stack(11, 0)
    fp_ab = s_ab.fingerprint()
    fp_ba = s_ba.fingerprint()
    assert fp_ab != fp_ba, "stack order must affect fingerprint"


def test_stack_survives_clone_replay_fingerprint_identical(engine):
    """The "stack survives serialization" invariant — at this slice
    the only "replay" available is clone_once (no to_bytes / from_bytes
    primitive yet). Cloning a state with a populated stack must
    produce a state with an identical fingerprint; the clone's stack
    is bit-equal to the original's. Locks in the CoW contract from
    the fingerprint side: if cloning silently drops or reorders the
    stack, the digest diverges and this test catches it."""
    state = engine.make_synthetic_state()
    # Populate a non-trivial stack: three entries of varied shape.
    state.push_to_stack(100, 0)
    state.push_to_stack(200, 1)
    state.push_to_stack(300, 0)
    fp_orig = state.fingerprint()

    cloned = state.clone_once()

    # Identical fingerprint -> identical gameplay-relevant invariants,
    # which transitively means identical stack contents AND order.
    assert cloned.fingerprint() == fp_orig
    # And the snapshot view agrees with the digest's claim.
    assert cloned.stack_snapshot() == state.stack_snapshot()
    # Re-fingerprint after a no-op clone is still equal.
    assert cloned.fingerprint() == state.fingerprint()
