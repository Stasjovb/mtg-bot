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
