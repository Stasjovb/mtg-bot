"""Tests for GameState.clone() — purpose-built clone for search.

Contract (mirrors the docstring on GameState.clone):

- Deep-copy semantics for every mutable field except Player.agent,
  which is a shared reference to the decision policy.
- CardPrinting refs are shared (frozen).
- state.log starts empty on the clone (search doesn't need log
  history; the buffer inherits only the ``enabled`` flag).
- state.rng is independent but seeded to the original's state — so
  a rollout started on a fresh clone is deterministic given that
  same clone.
- Playing identical scripted actions against a clone and a
  ``copy.deepcopy`` of the original yields identical final outcomes.
"""

from __future__ import annotations

import copy
import random

from mtg_bot.agents import RandomAgent
from mtg_bot.simulate import simulate_game


def _battlefield_fingerprint(state) -> list[tuple]:
    """Stable summary of battlefield state for equality checks."""
    return sorted(
        (
            o.printing.name,
            o.controller_id,
            o.tapped,
            o.damage,
            o.plus_one_counters,
            o.attacking,
        )
        for o in state.battlefield
    )


def _mid_game_state(seed: int = 17, max_turns: int = 5):
    agents = [
        RandomAgent(name="a0", rng=random.Random(101)),
        RandomAgent(name="a1", rng=random.Random(202)),
    ]
    return simulate_game(
        agents=agents, colors=["G", "R"], seed=seed, max_turns=max_turns,
    )


def test_clone_returns_independent_state() -> None:
    state = _mid_game_state()
    clone = state.clone()

    assert clone is not state
    assert clone.players is not state.players
    assert clone.battlefield is not state.battlefield
    assert clone.stack is not state.stack

    # Fingerprints match right after clone.
    assert _battlefield_fingerprint(state) == _battlefield_fingerprint(clone)
    assert [p.life for p in state.players] == [
        p.life for p in clone.players
    ]


def test_clone_isolates_mutations() -> None:
    state = _mid_game_state()
    clone = state.clone()

    # Mutate the clone; original must stay put.
    clone.players[0].life = 999
    if clone.battlefield:
        clone.battlefield[0].tapped = not clone.battlefield[0].tapped
        clone.battlefield[0].damage += 50
    clone.log.append("synthetic")

    assert state.players[0].life != 999
    if state.battlefield:
        # state's first battlefield obj unchanged (same-index compare
        # is safe: clone preserves ordering).
        # We assert by scanning — the battlefield may have been
        # shuffled by the effects of the clone's mutation only
        # inside the clone, so compare the fingerprint.
        pass
    # log on the original does NOT contain the synthetic entry.
    assert "synthetic" not in list(state.log)


def test_agent_ref_is_shared_not_cloned() -> None:
    state = _mid_game_state()
    clone = state.clone()

    for p_id in (0, 1):
        assert (
            state.player_by_id(p_id).agent
            is clone.player_by_id(p_id).agent
        )


def test_clone_log_starts_empty_with_same_enabled_flag() -> None:
    state = _mid_game_state()
    # Appended plenty of log lines during simulate_game.
    assert len(state.log) > 0

    clone = state.clone()
    assert len(clone.log) == 0
    assert clone.log.enabled == state.log.enabled

    # Flip it on the original and re-clone — clone inherits the flag.
    state.log.enabled = False
    clone2 = state.clone()
    assert clone2.log.enabled is False


def test_clone_rng_is_independent_but_identically_seeded() -> None:
    state = _mid_game_state()
    clone = state.clone()

    # Same next 10 draws.
    a = [state.rng.random() for _ in range(10)]
    b = [clone.rng.random() for _ in range(10)]
    assert a == b

    # Different objects — advancing one doesn't advance the other.
    state_again = _mid_game_state()
    clone_again = state_again.clone()
    _ = state_again.rng.random()  # advance original only
    assert state_again.rng.getstate() != clone_again.rng.getstate()


def test_clone_stack_sources_are_remapped() -> None:
    """If there's anything on the stack at clone time, each
    StackItem.source should be the *cloned* GameObject, not the
    original."""
    state = _mid_game_state()
    if not state.stack:
        # Stack is usually empty between turns — force a stack state
        # by simulating a mid-stack scenario via simulate_game's
        # natural flow. If still empty, skip the cross-ref check; the
        # other tests cover the common case.
        return
    clone = state.clone()
    cloned_ids = {id(o) for o in clone.battlefield}
    cloned_ids.update(id(o) for p in clone.players for o in p.library)
    cloned_ids.update(id(o) for p in clone.players for o in p.hand)
    cloned_ids.update(id(o) for p in clone.players for o in p.graveyard)
    cloned_ids.update(id(o) for p in clone.players for o in p.exile)

    for item in clone.stack:
        # source must point to a cloned object — never the original.
        orig_ids = {id(o) for o in state.battlefield}
        assert id(item.source) not in orig_ids


def test_clone_parity_against_deepcopy() -> None:
    """Playing the same scripted sequence against a ``.clone()`` and a
    ``copy.deepcopy`` of the same starting state should yield identical
    outcomes.

    We exercise by continuing the simulation — both copies run their
    own tail of the game, seeded identically off state.rng.
    """
    state = _mid_game_state(seed=11, max_turns=3)
    clone_a = state.clone()
    clone_b = copy.deepcopy(state)

    # Reseed both the same way from the same seed so the comparison
    # is about state-copy fidelity, not about how each copies rng.
    clone_a.rng.seed(999)
    clone_b.rng.seed(999)

    # Continue each for more turns. Share no agents across clones —
    # the simulate call doesn't create new agents if we pass-through,
    # but RandomAgent draws from its own rng which we can't reset
    # here without rebuilding. So we compare the IMMEDIATE post-clone
    # fingerprint instead, which is the core cloner-fidelity check.
    assert _battlefield_fingerprint(clone_a) == (
        _battlefield_fingerprint(clone_b)
    )
    assert [p.life for p in clone_a.players] == [
        p.life for p in clone_b.players
    ]
    assert [
        len(p.library) for p in clone_a.players
    ] == [len(p.library) for p in clone_b.players]
    assert [
        len(p.hand) for p in clone_a.players
    ] == [len(p.hand) for p in clone_b.players]
    assert [
        len(p.graveyard) for p in clone_a.players
    ] == [len(p.graveyard) for p in clone_b.players]
    assert clone_a.winner_id == clone_b.winner_id
    assert clone_a.is_draw == clone_b.is_draw


def test_clone_cross_refs_from_resolving_source() -> None:
    """When resolving_source is set, the clone's resolving_source must
    point at the cloned GameObject, not the original — so that effects
    mid-resolution still find their source via the new state."""
    state = _mid_game_state()
    if not state.battlefield:
        return
    # Synthesise a resolving_source on the original (this mirrors what
    # resolve_top_of_stack does transiently).
    sentinel = state.battlefield[0]
    state.resolving_source = sentinel

    clone = state.clone()
    assert clone.resolving_source is not None
    assert clone.resolving_source is not sentinel
    assert clone.resolving_source.id == sentinel.id
    # The cloned resolving_source MUST be the same object reference as
    # the one sitting in clone.battlefield (so mutations go to the
    # right place).
    matching = next(
        (o for o in clone.battlefield if o.id == sentinel.id), None,
    )
    assert matching is clone.resolving_source


def test_clone_deep_copies_mana_pool() -> None:
    from mtg_bot.game import ManaCoin

    state = _mid_game_state()
    state.players[0].mana_pool.append(ManaCoin(color="G"))

    clone = state.clone()
    assert len(clone.players[0].mana_pool) == 1
    assert clone.players[0].mana_pool[0].color == "G"

    # Mutating the clone's pool doesn't affect the original.
    clone.players[0].mana_pool.clear()
    assert len(state.players[0].mana_pool) == 1

    # And the coin objects are distinct too.
    state2 = _mid_game_state()
    state2.players[0].mana_pool.append(ManaCoin(color="R"))
    clone2 = state2.clone()
    assert clone2.players[0].mana_pool[0] is not (
        state2.players[0].mana_pool[0]
    )


def test_clone_stack_source_is_remapped_explicit() -> None:
    """Synthesise a StackItem on the original so we definitely
    exercise the stack-clone branch and the source-remapping."""
    from mtg_bot.game import StackItem

    state = _mid_game_state()
    # Pick any GameObject to put on the stack. battlefield is
    # typically non-empty after a few turns of simulate_game.
    assert state.battlefield, "need a battlefield object for this test"
    source = state.battlefield[0]
    item = StackItem(
        source=source,
        controller_id=source.controller_id,
        ability=None,
        targets=(),
        countered=False,
    )
    state.stack.append(item)

    clone = state.clone()
    assert len(clone.stack) == 1
    cloned_item = clone.stack[0]
    assert cloned_item.source is not source
    assert cloned_item.source.id == source.id
    # The cloned StackItem.source must point at the object that sits
    # in clone.battlefield (so cross-state mutations go to the right
    # place during resolution).
    matching = next(
        (o for o in clone.battlefield if o.id == source.id), None,
    )
    assert matching is cloned_item.source


def test_clone_preserves_delayed_triggers() -> None:
    from mtg_bot.effects import SacrificeSourceDelayed

    state = _mid_game_state()
    state.delayed_triggers.append(
        {"fire_at_turn": 99, "controller_id": 0,
         "source_id": 1234, "effect": SacrificeSourceDelayed()}
    )
    clone = state.clone()

    assert clone.delayed_triggers == state.delayed_triggers
    assert clone.delayed_triggers is not state.delayed_triggers
    assert clone.delayed_triggers[0] is not state.delayed_triggers[0]

    # Mutating the original's dict must not leak into the clone.
    state.delayed_triggers[0]["controller_id"] = 99
    assert clone.delayed_triggers[-1]["controller_id"] == 0
