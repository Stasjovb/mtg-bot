"""Regression tests for the copy-on-write list zones in
``GameState.clone()``.

Background
----------
``GameState.clone()`` wraps each player's ``library``, ``graveyard``,
and ``exile`` zones in a ``_CowList`` (see ``src/mtg_bot/game.py``).
The wrapper lets the parent state and the clone share the same
GameObject instances right after clone, deferring the per-element
deep-clone to the first in-place mutation on either side.

The tricky failure mode (and the bug behind the original revert in
commit ``2864cc2``) is that the engine's draw / mill / exile-from-
library paths look like::

    card = p.library.pop(0)
    p.hand.append(card)
    card.zone = HAND   # <-- in-place mutation AFTER list pop

Without copy-on-write at the list level, the in-place ``card.zone =
HAND`` leaks across the parent/clone boundary because the popped
GameObject is the same instance both states reference. These tests
construct exactly that pattern at unit-test scale and confirm the
parent state stays uncorrupted.
"""

from __future__ import annotations

import pickle
import random

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import CardPrinting
from mtg_bot.game import GameObject, Zone, _CowList
from mtg_bot.simulate import simulate_game


def _mid_game_state(seed: int = 17, max_turns: int = 5):
    agents = [
        RandomAgent(name="a0", rng=random.Random(101)),
        RandomAgent(name="a1", rng=random.Random(202)),
    ]
    return simulate_game(
        agents=agents, colors=["G", "R"], seed=seed, max_turns=max_turns,
    )


# --- _CowList unit tests --------------------------------------------------


def test_cowlist_owned_init_is_independent():
    cow = _CowList([1, 2, 3])
    assert cow._owned is True
    assert cow._clone_each is None
    assert list(cow) == [1, 2, 3]
    cow.append(4)
    assert list(cow) == [1, 2, 3, 4]


def test_cowlist_shared_forks_on_first_mutation():
    cloned = []

    def clone_each(x):
        cloned.append(x)
        return [x]  # use list-of-x so clones are distinct from originals

    src = _CowList([1, 2, 3])
    src._owned = False
    src._clone_each = clone_each

    # Reads do NOT fork.
    assert list(src) == [1, 2, 3]
    assert src._owned is False
    assert cloned == []

    # First mutation forks.
    src.append(99)
    assert src._owned is True
    assert src._clone_each is None
    # The forked list contains the cloned-then-original element.
    assert list(src) == [[1], [2], [3], 99]
    assert cloned == [1, 2, 3]

    # Subsequent mutations don't re-fork.
    cloned.clear()
    src.append(100)
    assert cloned == []
    assert list(src) == [[1], [2], [3], 99, 100]


def test_cowlist_each_mutator_forks():
    """Every mutator should call ``_fork_if_shared`` first."""
    def make_shared():
        cow = _CowList([1, 2, 3])
        cow._owned = False
        cow._clone_each = lambda x: x  # identity: easier to assert
        return cow

    # append
    c = make_shared()
    c.append(4)
    assert c._owned is True

    # extend
    c = make_shared()
    c.extend([4, 5])
    assert c._owned is True

    # insert
    c = make_shared()
    c.insert(0, 99)
    assert c._owned is True

    # remove
    c = make_shared()
    c.remove(2)
    assert c._owned is True

    # pop
    c = make_shared()
    c.pop()
    assert c._owned is True

    # clear
    c = make_shared()
    c.clear()
    assert c._owned is True

    # reverse
    c = make_shared()
    c.reverse()
    assert c._owned is True

    # sort
    c = make_shared()
    c.sort()
    assert c._owned is True

    # __setitem__
    c = make_shared()
    c[0] = 99
    assert c._owned is True

    # __delitem__
    c = make_shared()
    del c[0]
    assert c._owned is True

    # __iadd__
    c = make_shared()
    c += [4]
    assert c._owned is True

    # __imul__
    c = make_shared()
    c *= 2
    assert c._owned is True


def test_cowlist_pickles_round_trip():
    cow = _CowList([1, 2, 3])
    cow.append(4)
    blob = pickle.dumps(cow)
    restored = pickle.loads(blob)
    assert isinstance(restored, _CowList)
    assert list(restored) == [1, 2, 3, 4]
    assert restored._owned is True


def test_cowlist_is_a_list():
    """``isinstance(cow, list)`` must hold so engine code that does
    ``isinstance(zone, list)`` checks still passes."""
    cow = _CowList([1, 2])
    assert isinstance(cow, list)


# --- GameState.clone() integration tests ---------------------------------


def test_clone_library_uses_cowlist():
    state = _mid_game_state()
    clone = state.clone()
    for p in state.players:
        assert isinstance(p.library, _CowList)
        assert isinstance(p.graveyard, _CowList)
        assert isinstance(p.exile, _CowList)
    for p in clone.players:
        assert isinstance(p.library, _CowList)
        assert isinstance(p.graveyard, _CowList)
        assert isinstance(p.exile, _CowList)


def test_clone_pop_then_mutate_does_not_leak_to_source():
    """The exact pattern from the original cow-library bug:
    pop a card off the clone's library, mutate its ``zone`` in place,
    confirm the source state's view is unaffected."""
    state = _mid_game_state()
    # Pre-condition: both players have a non-empty library at turn 5.
    assert all(len(p.library) > 0 for p in state.players)

    src_lib_ids_before = [c.id for c in state.players[0].library]
    src_top_zone_before = state.players[0].library[0].zone

    clone = state.clone()
    # Clone draws (pop + zone mutation).
    drawn = clone.players[0].library.pop(0)
    drawn.zone = Zone.HAND
    drawn.tapped = True
    drawn.damage = 7
    clone.players[0].hand.append(drawn)

    # Source library still has the card with original zone.
    src_lib_ids_after = [c.id for c in state.players[0].library]
    assert src_lib_ids_after == src_lib_ids_before
    src_top = state.players[0].library[0]
    assert src_top.zone == src_top_zone_before
    assert src_top.zone == Zone.LIBRARY
    # Critically: the source's top card was NOT the same instance as
    # the one mutated on the clone.
    assert src_top.tapped is False
    assert src_top.damage == 0


def test_clone_source_pop_then_mutate_does_not_leak_to_clone():
    """Mirror direction: source mutates first; clone view stays clean."""
    state = _mid_game_state()
    clone = state.clone()

    clone_lib_ids_before = [c.id for c in clone.players[0].library]
    clone_top_zone_before = clone.players[0].library[0].zone

    drawn = state.players[0].library.pop(0)
    drawn.zone = Zone.HAND
    drawn.tapped = True
    state.players[0].hand.append(drawn)

    clone_lib_ids_after = [c.id for c in clone.players[0].library]
    assert clone_lib_ids_after == clone_lib_ids_before
    clone_top = clone.players[0].library[0]
    assert clone_top.zone == clone_top_zone_before
    assert clone_top.zone == Zone.LIBRARY
    assert clone_top.tapped is False


def test_clone_graveyard_pop_then_mutate_isolated():
    """Engine pattern: ``card = p.graveyard.pop(...); card.zone = HAND``
    (e.g. return-to-hand effects). The pop must fork before returning,
    so the popped card is a CLONE — its post-pop in-place mutation
    must not leak."""
    state = _mid_game_state()
    p0 = state.players[0]
    if not p0.library:
        return  # nothing to test
    card = p0.library.pop(0)
    card.zone = Zone.GRAVEYARD
    p0.graveyard.append(card)

    clone = state.clone()
    src_gy_top_id = state.players[0].graveyard[-1].id

    # Clone returns the top of GY to its hand.
    returned = clone.players[0].graveyard.pop()
    returned.zone = Zone.HAND
    returned.damage = 42
    returned.tapped = True
    clone.players[0].hand.append(returned)

    src_gy_top = state.players[0].graveyard[-1]
    assert src_gy_top.id == src_gy_top_id
    assert src_gy_top.zone == Zone.GRAVEYARD
    assert src_gy_top.damage == 0
    assert src_gy_top.tapped is False


def test_clone_exile_pop_then_mutate_isolated():
    """Same as above but for the exile zone."""
    state = _mid_game_state()
    p0 = state.players[0]
    if not p0.library:
        return
    card = p0.library.pop(0)
    card.zone = Zone.EXILE
    p0.exile.append(card)

    clone = state.clone()
    src_top_id = state.players[0].exile[-1].id

    popped = clone.players[0].exile.pop()
    popped.zone = Zone.GRAVEYARD
    popped.damage = 99
    popped.tapped = True

    src_top = state.players[0].exile[-1]
    assert src_top.id == src_top_id
    assert src_top.zone == Zone.EXILE
    assert src_top.damage == 0
    assert src_top.tapped is False


def test_clone_chain_three_states_isolated():
    """A cloned state can itself be cloned. All three should remain
    independent under mutation."""
    a = _mid_game_state()
    b = a.clone()
    c = b.clone()

    # Mutate a's library top: should not affect b or c.
    a_drawn = a.players[0].library.pop(0)
    a_drawn.zone = Zone.HAND
    a_drawn.tapped = True

    assert b.players[0].library[0].zone == Zone.LIBRARY
    assert b.players[0].library[0].tapped is False
    assert c.players[0].library[0].zone == Zone.LIBRARY
    assert c.players[0].library[0].tapped is False

    # Mutate c's library top: should not affect b.
    c_drawn = c.players[0].library.pop(0)
    c_drawn.zone = Zone.GRAVEYARD
    c_drawn.damage = 50

    assert b.players[0].library[0].zone == Zone.LIBRARY
    assert b.players[0].library[0].damage == 0


def test_clone_multiple_clones_off_one_source():
    """Clone-twice pattern (MCTS expanding two children from the same
    parent). Both children must be independent and the parent must be
    independent of both."""
    parent = _mid_game_state()
    child_a = parent.clone()
    child_b = parent.clone()

    parent_lib_ids = [c.id for c in parent.players[0].library]

    # Mutate child A.
    a_drawn = child_a.players[0].library.pop(0)
    a_drawn.zone = Zone.HAND
    a_drawn.tapped = True

    # Mutate child B.
    b_drawn = child_b.players[0].library.pop(0)
    b_drawn.zone = Zone.GRAVEYARD
    b_drawn.damage = 33

    # Parent's library is still intact.
    assert [c.id for c in parent.players[0].library] == parent_lib_ids
    assert parent.players[0].library[0].zone == Zone.LIBRARY
    assert parent.players[0].library[0].tapped is False
    assert parent.players[0].library[0].damage == 0

    # The two child mutations didn't cross-pollute either.
    assert child_a.players[0].library[0].tapped is False
    assert child_a.players[0].library[0].damage == 0
    assert child_b.players[0].library[0].tapped is False
    assert child_b.players[0].library[0].damage == 0


def test_mcts_on_mtg_does_not_corrupt_state():
    """Synthetic-but-realistic regression: drive MCTS through the
    real engine over a shared ``MtgGameStateAdapter`` for a non-
    trivial number of nodes. With the original cow-library bug, this
    reliably aborted partway through with ``ValueError: card N not
    castable by PX``. With proper CoW it should run clean."""
    from mtg_bot.search import (
        MCTS, Budget, MtgGameStateAdapter, RandomRolloutEvaluator,
    )
    from mtg_bot.simulate import setup_game

    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=42,
    )
    adapter = MtgGameStateAdapter(state)
    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(7)),
        budget_factory=lambda: Budget(max_nodes=50),
        rng=random.Random(8),
    )
    decision = mcts.choose(adapter, adapter.active_player())
    assert decision in adapter.legal_decisions()


def test_pre_existing_cowlist_is_reused_at_clone():
    """If a player's library is already a ``_CowList`` (from a prior
    clone), cloning again reuses it rather than re-wrapping."""
    state = _mid_game_state()
    clone1 = state.clone()
    # Both source and clone1 should have CowLists already.
    assert isinstance(state.players[0].library, _CowList)
    src_lib_id = id(state.players[0].library)

    clone2 = state.clone()
    # The source's library is the same object across multiple clones.
    assert id(state.players[0].library) == src_lib_id
    # Each clone gets its own _CowList instance though.
    assert clone1.players[0].library is not clone2.players[0].library
    assert clone1.players[0].library is not state.players[0].library


def test_clone_obj_helper_isolated_through_cow_fork():
    """Once a CowList forks, the resulting GameObjects are fresh
    copies — their ids match originals (preserved during clone) but
    they are different Python instances."""
    state = _mid_game_state()
    clone = state.clone()

    src_first = state.players[0].library[0]
    cl_first = clone.players[0].library[0]
    # Pre-fork: same Python instance.
    assert src_first is cl_first

    # Force fork on the clone side via a mutation.
    clone.players[0].library.append(
        # Build a throwaway GameObject so the list backing changes.
        GameObject(
            id=99999, printing=src_first.printing, owner_id=0,
            controller_id=0, zone=Zone.LIBRARY,
        )
    )

    # After fork, clone.library[0] is a *clone* of the original.
    cl_first_after = clone.players[0].library[0]
    assert cl_first_after is not src_first
    assert cl_first_after.id == src_first.id
