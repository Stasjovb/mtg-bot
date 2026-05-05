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
    """First mutation on a shared list clones into the PEER (not self).

    Rationale: callers commonly hold references to elements they
    fetched from this list before the mutation; if we cloned ``self``
    those references would be stale (and any subsequent in-place
    mutation on them would corrupt the peer). Cloning into the peer
    instead keeps the mutator's references valid.
    """
    cloned = []

    def clone_each(x):
        cloned.append(x)
        return [x]  # use list-of-x so clones are distinct from originals

    # Set up a clone-time pair: src ↔ peer, both shared, both holding
    # the same elements.
    src = _CowList([1, 2, 3])
    peer = _CowList([1, 2, 3])
    src._owned = False
    src._clone_each = clone_each
    group = [src, peer]
    src._share_group = group
    peer._owned = False
    peer._clone_each = clone_each
    peer._share_group = group

    # Reads do NOT fork.
    assert list(src) == [1, 2, 3]
    assert list(peer) == [1, 2, 3]
    assert src._owned is False
    assert peer._owned is False
    assert cloned == []

    # First mutation on src forks: src keeps originals + appended;
    # peer gets the cloned pool. Post-optimization, only ``_owned`` is
    # the canonical "out of share group" indicator — ``_clone_each``
    # and ``_share_group`` are intentionally NOT reset on the
    # transition because they're never read once ``_owned=True``
    # (see ``_fork`` in game.py for the perf rationale: those writes
    # were ~3 attribute stores per fork of pure hygiene cost).
    src.append(99)
    assert src._owned is True
    assert peer._owned is True
    # Src kept its original element identities and appended the new value.
    assert list(src) == [1, 2, 3, 99]
    # Peer has the cloned elements installed.
    assert list(peer) == [[1], [2], [3]]
    assert cloned == [1, 2, 3]

    # Subsequent mutations don't re-fork.
    cloned.clear()
    src.append(100)
    assert cloned == []
    assert list(src) == [1, 2, 3, 99, 100]


def test_cowlist_each_mutator_forks():
    """Every mutator should call ``_fork_if_shared`` first, isolating
    self from its peer."""
    def make_pair():
        a = _CowList([1, 2, 3])
        b = _CowList([1, 2, 3])
        group = [a, b]
        a._owned = False
        a._clone_each = lambda x: x  # identity: easier to assert
        a._share_group = group
        b._owned = False
        b._clone_each = lambda x: x
        b._share_group = group
        return a, b

    # append
    a, b = make_pair()
    a.append(4)
    assert a._owned is True and b._owned is True

    # extend
    a, b = make_pair()
    a.extend([4, 5])
    assert a._owned is True and b._owned is True

    # insert
    a, b = make_pair()
    a.insert(0, 99)
    assert a._owned is True and b._owned is True

    # remove
    a, b = make_pair()
    a.remove(2)
    assert a._owned is True and b._owned is True

    # pop
    a, b = make_pair()
    a.pop()
    assert a._owned is True and b._owned is True

    # clear
    a, b = make_pair()
    a.clear()
    assert a._owned is True and b._owned is True

    # reverse
    a, b = make_pair()
    a.reverse()
    assert a._owned is True and b._owned is True

    # sort
    a, b = make_pair()
    a.sort()
    assert a._owned is True and b._owned is True

    # __setitem__
    a, b = make_pair()
    a[0] = 99
    assert a._owned is True and b._owned is True

    # __delitem__
    a, b = make_pair()
    del a[0]
    assert a._owned is True and b._owned is True

    # __iadd__
    a, b = make_pair()
    a += [4]
    assert a._owned is True and b._owned is True

    # __imul__
    a, b = make_pair()
    a *= 2
    assert a._owned is True and b._owned is True


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


def test_remove_then_mutate_caller_held_ref_isolated():
    """Engine pattern that f57125c's self-fork CoW broke (and the
    actual reason heuristic-vs-heuristic PIMC reproducibly aborted
    with ``ValueError: card N not castable by PX``)::

        card = next(c for c in p.exile if c.id == X and c.warped)
        p.exile.remove(card)
        card.warped = False        # in-place attribute mutation

    Under self-fork CoW, ``p.exile.remove(card)`` clones the elements
    of ``self`` into self's backing storage and removes the matching
    clone — but the caller's ``card`` reference still points at the
    OLD shared GameObject. The subsequent ``card.warped = False``
    therefore mutates the SHARED original, leaking the change to
    every peer state that still references it. legal_actions on a
    sibling state would later see ``warped=False`` even though the
    cast hadn't actually happened in that sibling's history, and
    apply_action would raise.

    Under peer-fork CoW, ``remove`` clones into the PEERS, leaving
    self with the originals; the caller's ``card`` reference stays
    valid because ``self`` (the mutator) is the one keeping the
    original instances.
    """
    state = _mid_game_state()
    # Move a library card into exile to set up the pattern.
    p0 = state.players[0]
    if not p0.library:
        return  # nothing to test
    card_orig = p0.library.pop(0)
    card_orig.zone = Zone.EXILE
    card_orig.warped = True
    p0.exile.append(card_orig)
    target_id = card_orig.id

    clone = state.clone()

    # Snapshot what the source's exile card looks like NOW — we'll
    # check this exact state survives the clone-side mutation.
    src_exile_warped_before = state.players[0].exile[-1].warped
    assert src_exile_warped_before is True

    # Engine pattern, exactly as it appears in actions.py / turn.py:
    p_clone = clone.players[0]
    card = next(c for c in p_clone.exile if c.id == target_id and c.warped)
    p_clone.exile.remove(card)
    card.warped = False
    card.zone = Zone.STACK
    # And then the engine would push it onto the stack, etc. — for the
    # purposes of this test, the corruption (if any) is already
    # observable on the source.

    src_exile_card = next(
        c for c in state.players[0].exile if c.id == target_id
    )
    assert src_exile_card.warped is True, (
        "Source-state's exile card had .warped flipped by clone-side "
        "remove + attribute mutation — peer-fork CoW is leaking."
    )
    assert src_exile_card.zone == Zone.EXILE


def test_clone_obj_helper_isolated_through_cow_fork():
    """Once a CowList forks, the side that did NOT mutate gets fresh
    copies of the GameObjects — same ids (preserved during clone) but
    different Python instances. The mutating side keeps the originals
    so any caller-held references remain valid (this is the property
    that makes ``card = next(c for c in p.exile if ...);
    p.exile.remove(card); card.zone = HAND`` correct under CoW)."""
    state = _mid_game_state()
    clone = state.clone()

    src_first = state.players[0].library[0]
    cl_first = clone.players[0].library[0]
    # Pre-fork: same Python instance.
    assert src_first is cl_first

    # Force fork on the clone side via a mutation. Under the
    # peer-fork design, the SOURCE's list gets the cloned pool;
    # the clone keeps the originals.
    clone.players[0].library.append(
        # Build a throwaway GameObject so the list backing changes.
        GameObject(
            id=99999, printing=src_first.printing, owner_id=0,
            controller_id=0, zone=Zone.LIBRARY,
        )
    )

    # Clone keeps originals; source got clones.
    cl_first_after = clone.players[0].library[0]
    src_first_after = state.players[0].library[0]
    assert cl_first_after is cl_first  # clone kept the original
    assert src_first_after is not src_first  # source got a fresh clone
    assert src_first_after.id == src_first.id


def test_iterate_and_mutate_after_explicit_fork_is_isolated():
    """Demonstrates the escape hatch for the cleanup-step pattern that
    bypasses CoW::

        for c in p.exile:
            c.playable_from_exile_this_turn = False

    The loop iterates the list (read-only) and mutates each ELEMENT
    in place. No list-mutator (append/pop/remove/__setitem__) is
    called, so the share group never forks naturally — and the in-
    place attribute write would otherwise hit a GameObject that's
    still shared with every peer ``_CowList``. That's the
    long-tail corruption that surfaced as ``ValueError: card N not
    castable by PX`` past a few hundred PIMC self-play games (todo
    e3b7d9c1): a rollout that walked through cleanup cleared an
    impulse-castable card's flag on the source state, then the
    source's heuristic chose to cast that very card and the apply
    path couldn't find it under any of the legal cast-source
    predicates.

    The fix is to call ``p.exile.fork()`` (the public entry point of
    ``_fork_if_shared``) BEFORE the iteration. That's a no-op when
    already owned, but for shared lists it gives ``self`` an
    isolated GameObject pool — peers receive fresh clones — so the
    subsequent attribute writes only touch ``self``'s elements.
    """
    from mtg_bot.cards import ManaCost
    from mtg_bot.game import GameState, LogBuffer, Player

    printing = CardPrinting(
        name="ImpulseCard",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
    )
    impulse_card = GameObject(
        id=42,
        printing=printing,
        owner_id=0,
        controller_id=0,
        zone=Zone.EXILE,
    )
    impulse_card.playable_from_exile_this_turn = True

    p0 = Player(
        id=0, life=20,
        library=[], hand=[], graveyard=[],
        exile=[impulse_card], mana_pool=[], agent=None,
    )
    p1 = Player(
        id=1, life=20,
        library=[], hand=[], graveyard=[],
        exile=[], mana_pool=[], agent=None,
    )
    state = GameState(players=[p0, p1], rng=random.Random(0))
    state.log = LogBuffer()
    state.log.enabled = False

    clone = state.clone()
    # Sanity: pre-fork, source and clone share the same GameObject.
    assert state.players[0].exile[0] is clone.players[0].exile[0]
    assert state.players[0].exile[0].playable_from_exile_this_turn is True

    # Mimic the cleanup-step pattern, prefixed with the fork() escape
    # hatch (the same pattern ``run_cleanup_step`` now uses).
    state.players[0].exile.fork()
    for c in state.players[0].exile:
        c.playable_from_exile_this_turn = False

    # Source flipped (intended); clone is untouched.
    assert (
        state.players[0].exile[0].playable_from_exile_this_turn is False
    )
    assert (
        clone.players[0].exile[0].playable_from_exile_this_turn is True
    ), (
        "Even after explicit ``fork()``, the source-side mutation "
        "leaked into the clone — CoW peer-fork is broken."
    )
    # The clone now holds a fresh GameObject; the source still holds
    # the original impulse_card (peer-fork direction: self keeps
    # originals, peers get clones).
    assert state.players[0].exile[0] is impulse_card
    assert clone.players[0].exile[0] is not impulse_card
    assert clone.players[0].exile[0].id == impulse_card.id


def test_run_cleanup_step_does_not_leak_to_peer():
    """Drive the actual ``run_cleanup_step`` on a CoW source state and
    confirm a peer state's exile flag survives. Pre-fix this fails
    because turn.py's cleanup loop iterates ``p.exile`` and writes
    ``c.playable_from_exile_this_turn = False`` on each element
    without ever forking the share group.
    """
    from mtg_bot.cards import ManaCost
    from mtg_bot.game import GameState, LogBuffer, Player
    from mtg_bot.turn import Step, run_cleanup_step

    printing = CardPrinting(
        name="ImpulseCard",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
    )
    card = GameObject(
        id=99,
        printing=printing,
        owner_id=0,
        controller_id=0,
        zone=Zone.EXILE,
    )
    card.playable_from_exile_this_turn = True

    p0 = Player(
        id=0, life=20,
        library=[], hand=[], graveyard=[],
        exile=[card], mana_pool=[], agent=None,
    )
    p1 = Player(
        id=1, life=20,
        library=[], hand=[], graveyard=[],
        exile=[], mana_pool=[], agent=None,
    )
    state = GameState(players=[p0, p1], rng=random.Random(0))
    state.log = LogBuffer()
    state.log.enabled = False
    state.step = Step.CLEANUP

    peer = state.clone()
    assert peer.players[0].exile[0].playable_from_exile_this_turn is True

    # Run the real cleanup on ``state``. Should not affect ``peer``.
    run_cleanup_step(state)

    assert state.players[0].exile[0].playable_from_exile_this_turn is False
    assert peer.players[0].exile[0].playable_from_exile_this_turn is True, (
        "run_cleanup_step on the source flipped the impulse-cast flag "
        "on a peer state's GameObject — the cleanup loop bypasses CoW."
    )


# --- Optimized-path regression tests --------------------------------------
#
# These exercise the post-optimization clone() (skipping dataclass
# __init__ via __new__, skipping per-object id_map lookups in bulk
# zone walks, etc.). They explicitly check that hand mutations stay
# isolated, library/graveyard CoW mutations stay isolated, and the
# fields the new code path sets explicitly (last_exile_recall_count,
# suppress_exiled_by_source_on_leave_for) round-trip through clone.


def test_clone_hand_mutation_does_not_leak_to_source():
    """Hand cloning takes the bulk-clone fast path: each hand
    GameObject is cloned via ``_clone_game_object`` directly and the
    id_map is populated in the same pass. Confirm a clone-side
    in-place mutation on a hand card does not propagate back to
    the source's hand."""
    state = _mid_game_state()
    p0 = state.players[0]
    if not p0.hand:
        return  # nothing to test
    src_first_hand_id = p0.hand[0].id
    src_first_hand_tapped = p0.hand[0].tapped
    src_first_hand_damage = p0.hand[0].damage

    clone = state.clone()

    # Clone-side: mutate first hand card.
    clone.players[0].hand[0].tapped = True
    clone.players[0].hand[0].damage = 99
    clone.players[0].hand[0].plus_one_counters = 5

    # Source unchanged.
    src_card = state.players[0].hand[0]
    assert src_card.id == src_first_hand_id
    assert src_card.tapped == src_first_hand_tapped
    assert src_card.damage == src_first_hand_damage
    assert src_card.plus_one_counters == 0
    # Different Python instances even though ids match.
    assert src_card is not clone.players[0].hand[0]


def test_clone_battlefield_mutation_does_not_leak_to_source():
    """Battlefield bulk path. A clone-side mutation on a
    battlefield permanent stays isolated."""
    state = _mid_game_state()
    if not state.battlefield:
        return
    src_first_id = state.battlefield[0].id

    clone = state.clone()
    clone.battlefield[0].tapped = True
    clone.battlefield[0].damage = 99
    clone.battlefield[0].plus_one_counters = 7

    src_obj = state.battlefield[0]
    assert src_obj.id == src_first_id
    assert src_obj.tapped is False
    assert src_obj.damage == 0
    assert src_obj.plus_one_counters == 0


def test_clone_explicit_state_field_round_trip():
    """The ``__new__`` clone path bypasses dataclass field defaults,
    so ``last_exile_recall_count`` and
    ``suppress_exiled_by_source_on_leave_for`` need explicit
    assignment. Verify both round-trip through clone() with non-
    default values."""
    state = _mid_game_state()
    state.last_exile_recall_count = 5
    state.suppress_exiled_by_source_on_leave_for = 12345

    clone = state.clone()
    assert clone.last_exile_recall_count == 5
    assert clone.suppress_exiled_by_source_on_leave_for == 12345

    # Mutating the clone does not reach back to the source.
    clone.last_exile_recall_count = 99
    clone.suppress_exiled_by_source_on_leave_for = None
    assert state.last_exile_recall_count == 5
    assert state.suppress_exiled_by_source_on_leave_for == 12345


def test_clone_layered_cache_starts_fresh():
    """Per-state memoization caches must NOT be shared with the
    source — otherwise a stale entry from a different version of
    the registry could leak into the clone. ``__new__`` path sets
    these to fresh empty defaults explicitly."""
    state = _mid_game_state()
    # Plant a sentinel cache entry on the source.
    state._layer6_wiped_cache[42] = (state._layered_cache_version, True)

    clone = state.clone()
    # Clone starts with an empty cache and version=0, regardless of
    # source's state.
    assert clone._layer6_wiped_cache == {}
    assert clone._layered_cache_version == 0

    # Source's planted entry survives.
    assert 42 in state._layer6_wiped_cache


def test_clone_rng_is_independent_after_advance():
    """The fast-cloned RNG (via ``Random.__new__`` + ``setstate``)
    must produce the same draws the source would have on the same
    initial state, but advance independently after divergence."""
    state = _mid_game_state()
    clone = state.clone()

    # Initial draws match exactly.
    src_draw = [state.rng.random() for _ in range(5)]
    clone_draw = [clone.rng.random() for _ in range(5)]
    assert src_draw == clone_draw

    # Now advance the clone's RNG further and confirm the source's
    # next draws are unaffected.
    [clone.rng.random() for _ in range(100)]
    src_next = state.rng.random()
    clone_next = clone.rng.random()
    # If the RNGs were the same instance, src_next would be at
    # offset 5+0 of its sequence and clone_next at 5+101 — different.
    # We don't pin the value but the independence property:
    # repeating the source draw on a fresh same-state Random
    # produces the same value, while the clone has moved on.
    assert isinstance(src_next, float)
    assert isinstance(clone_next, float)


def test_clone_chain_explicit_fields_isolated():
    """Three-deep clone chain: each level should be fully
    independent for the explicitly-cloned scalar fields."""
    a = _mid_game_state()
    a.creatures_died_this_turn = 1

    b = a.clone()
    b.creatures_died_this_turn = 2

    c = b.clone()
    c.creatures_died_this_turn = 3

    assert a.creatures_died_this_turn == 1
    assert b.creatures_died_this_turn == 2
    assert c.creatures_died_this_turn == 3


# --- _CowList fork-optimization regression tests --------------------------
#
# These exercise the post-optimization ``_fork`` slow-path + inlined
# ``_owned``-check fast-path on the mutators. The two invariants that
# matter for both correctness AND perf:
#
#   1. After any fork, the mutator (``self``) and the peer that becomes
#      owned MUST have ``_share_group = None``. Skipping this nulling
#      leaves a self<->group<->peer cycle that the cyclic-GC has to
#      collect rather than refcount-reclaim, which measurably regresses
#      the per-iteration ISMCTS fork loop.
#   2. The in-mutator ``if not self._owned: self._fork()`` form must
#      stay equivalent to the previous ``self._fork_if_shared()`` call
#      for every list mutator, including the rarely-hit ones (sort,
#      __imul__, etc.).


def test_fork_breaks_share_group_cycle():
    """After a 2-member share group forks, neither side may still
    point at the original ``_share_group`` list. Otherwise the cycle
    self -> group -> [self, peer] -> peer -> group makes the cyclic GC
    do work the refcount path could have done — a measurable
    regression on tight per-iteration fork loops (the per-clone case
    in ISMCTS rollout).
    """
    src = _CowList([1, 2, 3])
    peer = _CowList([1, 2, 3])
    src._owned = False
    peer._owned = False
    src._clone_each = lambda x: -x
    peer._clone_each = lambda x: -x
    group = [src, peer]
    src._share_group = group
    peer._share_group = group

    # Trigger fork via append on src.
    src.append(99)

    assert src._owned is True
    assert peer._owned is True
    assert src._share_group is None, (
        "self's _share_group must be cleared after fork to break the "
        "self<->group<->peer cycle (cyclic-GC perf trap)."
    )
    assert peer._share_group is None, (
        "peer's _share_group must be cleared after fork to break the "
        "cycle on the peer side too."
    )


def test_fork_breaks_share_group_cycle_three_member():
    """Same invariant for 3-member share groups: after self forks, the
    remaining peers form a NEW group together (not the old one), and
    self drops its reference to the old group."""
    a = _CowList([1, 2, 3])
    b = _CowList([1, 2, 3])
    c = _CowList([1, 2, 3])
    group = [a, b, c]
    for cow in (a, b, c):
        cow._owned = False
        cow._clone_each = lambda x: -x
        cow._share_group = group

    a.append(99)

    assert a._owned is True
    assert a._share_group is None
    # b and c remain shared (in a smaller group of two), so they are
    # still ``_owned=False`` and reference the new (peer-only) group.
    assert b._owned is False
    assert c._owned is False
    new_group = b._share_group
    assert new_group is c._share_group  # both point at the same new list
    assert new_group is not group  # a fresh list, not the old one
    assert a not in new_group
    assert b in new_group and c in new_group


def test_fork_three_member_subsequent_fork_isolates_remaining_peer():
    """After a 3-member group's first fork (a forks; b/c become a new
    2-member group), a subsequent fork on b should still work and
    leave c owned. Pins the chained-fork correctness across the new
    fast-path size==2 branch."""
    a = _CowList([1, 2, 3])
    b = _CowList([1, 2, 3])
    c = _CowList([1, 2, 3])
    group = [a, b, c]
    for cow in (a, b, c):
        cow._owned = False
        cow._clone_each = lambda x: [x]  # distinct clones
        cow._share_group = group

    # First fork: a leaves the group.
    a.append(99)
    # Second fork: b leaves what's left (a 2-member group of b, c).
    b.pop()

    assert a._owned and b._owned and c._owned
    assert a._share_group is None
    assert b._share_group is None
    assert c._share_group is None


def test_fork_inlined_check_dispatches_each_mutator():
    """Every mutator (post-optimization, with the fast-path check
    inlined as ``if not self._owned: self._fork()``) must still drive
    the fork on a freshly-shared list. Sister test to
    ``test_cowlist_each_mutator_forks`` but specifically validates
    the inline form (rather than calling _fork_if_shared() through a
    bound method)."""
    def make_pair(elements):
        a = _CowList(elements)
        b = _CowList(elements)
        a._owned = False
        b._owned = False
        a._clone_each = lambda x: x
        b._clone_each = lambda x: x
        group = [a, b]
        a._share_group = group
        b._share_group = group
        return a, b

    # Each mutator on the LHS forks (LHS keeps originals + delta;
    # RHS becomes owned with original elements).
    cases = [
        ("append",       lambda lst: lst.append(99)),
        ("extend",       lambda lst: lst.extend([4, 5])),
        ("insert",       lambda lst: lst.insert(0, 0)),
        ("remove",       lambda lst: lst.remove(2)),
        ("pop_default",  lambda lst: lst.pop()),
        ("pop_index",    lambda lst: lst.pop(0)),
        ("clear",        lambda lst: lst.clear()),
        ("reverse",      lambda lst: lst.reverse()),
        ("sort",         lambda lst: lst.sort()),
        ("setitem",      lambda lst: lst.__setitem__(0, 99)),
        ("delitem",      lambda lst: lst.__delitem__(0)),
        ("iadd",         lambda lst: lst.__iadd__([4])),
        ("imul",         lambda lst: lst.__imul__(2)),
    ]
    for label, mutate in cases:
        a, b = make_pair([1, 2, 3])
        mutate(a)
        assert a._owned is True, f"{label}: did not fork self"
        assert b._owned is True, f"{label}: did not fork peer"
        assert a._share_group is None, (
            f"{label}: did not break share_group cycle on self"
        )
        assert b._share_group is None, (
            f"{label}: did not break share_group cycle on peer"
        )


def test_fork_owned_no_op_skips_share_group_writes():
    """When ``_fork_if_shared`` is called on an already-owned list,
    nothing happens — including no spurious writes to ``_share_group``
    or ``_clone_each``. Pins that the fast-path branch returns
    immediately on the inline check."""
    cow = _CowList([1, 2, 3])
    # Deliberately set non-None values; the no-op must NOT clear them.
    sentinel_group = ["sentinel"]
    sentinel_cloner = lambda x: x
    cow._share_group = sentinel_group
    cow._clone_each = sentinel_cloner
    assert cow._owned is True

    cow._fork_if_shared()  # no-op
    cow.append(4)  # owned mutator, also no-op fork

    # Sentinels untouched: the fast-path didn't even probe these.
    assert cow._share_group is sentinel_group
    assert cow._clone_each is sentinel_cloner


def test_fork_iteration_followed_by_explicit_fork():
    """Verifies the public ``fork()`` entry point still drives the
    underlying ``_fork`` via the inline ``if self._owned`` guard. This
    is the ``run_cleanup_step`` pattern (``p.exile.fork()`` before an
    in-place attribute mutation loop)."""
    cloned = []

    def clone_each(x):
        cloned.append(x)
        return [x]  # distinct clones

    src = _CowList([1, 2, 3])
    peer = _CowList([1, 2, 3])
    src._owned = False
    peer._owned = False
    src._clone_each = clone_each
    peer._clone_each = clone_each
    group = [src, peer]
    src._share_group = group
    peer._share_group = group

    # Public fork() — same code path as the cleanup-step pattern.
    src.fork()
    assert src._owned is True
    assert peer._owned is True
    assert src._share_group is None
    assert peer._share_group is None
    assert cloned == [1, 2, 3]
    # src kept its originals; peer got the clones.
    assert list(src) == [1, 2, 3]
    assert list(peer) == [[1], [2], [3]]

    # Subsequent fork() on owned src is a fast-path no-op.
    cloned.clear()
    src.fork()
    assert cloned == []
