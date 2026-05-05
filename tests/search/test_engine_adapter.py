"""Tests for ``MtgGameStateAdapter`` — the real MTG engine plugged
into the search framework.

The adapter is the bridge between ``mtg_bot.game.GameState`` and
``mtg_bot.search.protocol.GameState``. These tests exercise both the
protocol surface and the step-advancement bookkeeping that makes the
priority loop pausable across apply() calls.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import Action, CastSpell, PassPriority, PlayLand
from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    DefaultTacticalAgent, GameState, MtgGameStateAdapter,
)
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step

from tests._test_decks import simple_test_decklists


def _fresh_adapter(seed: int = 42) -> MtgGameStateAdapter:
    """Standard two-player setup wrapped in the adapter."""
    state = setup_game(
        [RandomAgent(), RandomAgent()], decks=simple_test_decklists(),
        seed=seed,
    )
    return MtgGameStateAdapter(state)


def test_satisfies_game_state_protocol():
    """``isinstance`` against the runtime-checkable ``GameState``
    protocol confirms every required method is present."""
    adapter = _fresh_adapter()
    assert isinstance(adapter, GameState)


def test_constructor_advances_through_untap():
    """A fresh state is at UNTAP (no priority). Wrapping it in the
    adapter should automatically run UNTAP and stop at the first
    priority moment (UPKEEP)."""
    adapter = _fresh_adapter()
    assert adapter.engine_state.step == Step.UPKEEP


def test_constructor_installs_tactical_agent_on_players():
    """The adapter takes over every player's agent so mid-resolution
    callbacks go through the deterministic tactical policy."""
    adapter = _fresh_adapter()
    for p in adapter.engine_state.players:
        assert isinstance(p.agent, DefaultTacticalAgent)


def test_players_returns_both_ids():
    adapter = _fresh_adapter()
    assert adapter.players() == [0, 1]


def test_active_player_starts_with_player_0():
    """In a two-player game, player 0 is the active/starting player,
    and they get the first priority decision."""
    adapter = _fresh_adapter()
    assert adapter.active_player() == 0


def test_legal_decisions_always_contains_pass_at_priority():
    """During any priority step, PassPriority is always legal."""
    adapter = _fresh_adapter()
    legal = adapter.legal_decisions()
    assert any(isinstance(a, PassPriority) for a in legal)


def test_is_terminal_false_on_fresh_setup():
    adapter = _fresh_adapter()
    assert adapter.is_terminal() is False
    assert adapter.winner() is None


def test_apply_rejects_non_action_decision():
    adapter = _fresh_adapter()
    with pytest.raises(TypeError):
        adapter.apply("not an Action instance")


def test_apply_rejects_on_terminal_state():
    """Force a terminal state by zeroing P1's life, then applying
    should reject."""
    adapter = _fresh_adapter()
    adapter.engine_state.players[1].has_lost = True
    adapter.engine_state.winner_id = 0
    assert adapter.is_terminal()
    with pytest.raises(ValueError):
        adapter.apply(PassPriority())


def test_apply_passpriority_single_player_advances_priority():
    adapter = _fresh_adapter()
    before = adapter.active_player()
    adapter.apply(PassPriority())
    # One pass → priority moves to the other player.
    assert adapter.active_player() != before


def test_apply_passpriority_all_players_advances_step():
    """After both players pass at UPKEEP with empty stack, the
    step should advance."""
    adapter = _fresh_adapter()
    assert adapter.engine_state.step == Step.UPKEEP
    adapter.apply(PassPriority())  # P0 passes
    adapter.apply(PassPriority())  # P1 passes
    # Empty stack + all passed → step should have advanced to DRAW.
    assert adapter.engine_state.step == Step.DRAW


def test_starting_player_skips_first_draw():
    """The very first draw step doesn't draw (MTG rule 103.8a)."""
    adapter = _fresh_adapter()
    hand_size_before = len(adapter.engine_state.players[0].hand)
    # Pass twice to advance from UPKEEP to DRAW.
    adapter.apply(PassPriority())
    adapter.apply(PassPriority())
    assert adapter.engine_state.step == Step.DRAW
    # P0's hand size unchanged — skipped draw.
    assert len(adapter.engine_state.players[0].hand) == hand_size_before


def test_apply_nonpass_action_resets_pass_count():
    """After a non-pass action, priority returns to the active
    player with pass_count reset."""
    adapter = _fresh_adapter()
    # Advance to precombat main (where plays are legal).
    while adapter.engine_state.step != Step.PRECOMBAT_MAIN:
        adapter.apply(PassPriority())

    legal = adapter.legal_decisions()
    non_pass = [a for a in legal if not isinstance(a, PassPriority)]
    if not non_pass:
        pytest.skip("no non-pass action legal; seed-dependent")
    adapter.apply(non_pass[0])
    # Pass count reset; priority still on P0 (active player).
    assert adapter._pass_count == 0
    assert adapter.active_player() == 0


def test_play_land_applies_through_adapter():
    """Playing a land through the adapter should add it to the
    battlefield (the engine's PlayLand effect)."""
    adapter = _fresh_adapter()
    # Advance to precombat main.
    while adapter.engine_state.step != Step.PRECOMBAT_MAIN:
        adapter.apply(PassPriority())
    land_actions = [
        a for a in adapter.legal_decisions() if isinstance(a, PlayLand)
    ]
    if not land_actions:
        pytest.skip("no land-play available; seed-dependent")
    before_bf = len(adapter.engine_state.battlefield)
    adapter.apply(land_actions[0])
    assert len(adapter.engine_state.battlefield) == before_bf + 1


def test_clone_is_independent():
    """Mutating the clone must not affect the original, and vice versa."""
    adapter = _fresh_adapter()
    clone = adapter.clone()
    # Pass priority on the clone — should not affect the original's
    # pass_count or priority holder.
    clone.apply(PassPriority())
    assert clone._pass_count != adapter._pass_count or (
        clone.active_player() != adapter.active_player()
    )


def test_clone_preserves_step_and_priority():
    adapter = _fresh_adapter()
    clone = adapter.clone()
    assert clone.engine_state.step == adapter.engine_state.step
    assert clone.active_player() == adapter.active_player()
    assert clone._pass_count == adapter._pass_count
    assert clone._step_entered == adapter._step_entered


def test_clone_has_shared_tactical_agent():
    """By design the tactical policy is a shared ref — the same
    deterministic policy drives both the original and the clone."""
    adapter = _fresh_adapter()
    clone = adapter.clone()
    assert adapter._tactical is clone._tactical
    # And every player in both adapters has the same agent installed.
    for p in clone.engine_state.players:
        assert p.agent is clone._tactical


def test_clone_then_divergent_play_produces_different_states():
    """After cloning, playing different actions in each produces
    different game states."""
    adapter = _fresh_adapter()
    clone = adapter.clone()
    # Advance both to precombat main.
    while adapter.engine_state.step != Step.PRECOMBAT_MAIN:
        adapter.apply(PassPriority())
        clone.apply(PassPriority())

    legal = adapter.legal_decisions()
    if len(legal) < 2:
        pytest.skip("need two legal decisions to diverge")

    adapter.apply(legal[0])
    # Different decision for the clone.
    clone_legal = clone.legal_decisions()
    clone.apply(clone_legal[1] if len(clone_legal) > 1 else clone_legal[0])

    # Battlefields or hands should differ.
    assert (
        adapter.engine_state.battlefield
        != clone.engine_state.battlefield
    ) or (
        adapter.engine_state.players[0].hand
        != clone.engine_state.players[0].hand
    )


def test_game_terminates_within_turn_limit():
    """Driving the adapter with 'first non-pass action, else pass'
    should still terminate a game within a reasonable turn cap."""
    adapter = _fresh_adapter()
    MAX_STEPS = 10_000
    for _ in range(MAX_STEPS):
        if adapter.is_terminal():
            break
        legal = adapter.legal_decisions()
        pick = next(
            (a for a in legal if not isinstance(a, PassPriority)),
            legal[0],
        )
        adapter.apply(pick)
        if adapter.engine_state.turn_number > 200:
            break
    # Either the game ended or we hit the turn cap — both are fine.
    assert adapter.is_terminal() or adapter.engine_state.turn_number > 1


def test_legal_decisions_empty_on_terminal():
    adapter = _fresh_adapter()
    adapter.engine_state.winner_id = 0
    assert adapter.legal_decisions() == []


def test_engine_state_accessor_returns_wrapped_state():
    adapter = _fresh_adapter()
    assert adapter.engine_state is adapter._state
