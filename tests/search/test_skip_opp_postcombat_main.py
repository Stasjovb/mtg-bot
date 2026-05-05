"""Tests for the skip-opp-postcombat-main priority short-circuit.

Heuristic contract:
- When ``skip_opp_postcombat_main_enabled=True`` (default) AND the
  stack is empty AND step is POSTCOMBAT_MAIN AND it is the
  non-active player who has priority (i.e. it's opp's turn and we
  hold priority), ``legal_decisions`` returns ``[PassPriority()]``
  without invoking ``legal.legal_actions``.
- When the flag is False, the heuristic never fires.
- Disabled when active player has priority on their own main 2
  (that's a totally different case — the active player's main 2 is
  where they cast spells).
- Disabled outside POSTCOMBAT_MAIN.
- Disabled when the stack is non-empty.
- Disabled at a factored attacker/blocker decision moment.
"""

from __future__ import annotations

from unittest import mock

from mtg_bot import legal as legal_mod
from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search import HeuristicsConfig, MtgGameStateAdapter
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step


def _fresh_state(seed: int = 42):
    return setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )


def _spy_legal_actions(monkeypatch):
    real = legal_mod.legal_actions
    spy = mock.Mock(wraps=real)
    monkeypatch.setattr(legal_mod, "legal_actions", spy)
    from mtg_bot.search import engine_adapter as ea_mod
    monkeypatch.setattr(ea_mod, "legal_actions", spy)
    from mtg_bot.training import action_encoding as ae_mod
    monkeypatch.setattr(ae_mod, "legal_actions", spy)
    return spy


def _force_step(adapter, step: Step, *, priority_idx: int):
    state = adapter.engine_state
    state.step = step
    state.priority_player_idx = priority_idx
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()


# ---------------------------------------------------------------------
# Happy path: heuristic fires at opp's postcombat main with our priority
# ---------------------------------------------------------------------


def test_fires_at_opp_postcombat_main_when_we_hold_priority(monkeypatch):
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    opp_idx = 1 - state.active_player_idx
    _force_step(
        adapter, Step.POSTCOMBAT_MAIN, priority_idx=opp_idx,
    )

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0


# ---------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------


def test_does_not_fire_at_active_postcombat_main():
    """At ACTIVE player's postcombat main, this heuristic should NOT
    fire — that's the player's own main 2 where they cast spells."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(
        adapter, Step.POSTCOMBAT_MAIN,
        priority_idx=state.active_player_idx,
    )

    assert adapter._should_skip_opp_postcombat_main() is False


def test_does_not_fire_outside_postcombat_main():
    """Other steps are unaffected."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    opp_idx = 1 - state.active_player_idx
    for step in (
        Step.UPKEEP, Step.DRAW, Step.PRECOMBAT_MAIN,
        Step.DECLARE_ATTACKERS, Step.END,
    ):
        _force_step(adapter, step, priority_idx=opp_idx)
        assert adapter._should_skip_opp_postcombat_main() is False, (
            f"step {step}: should not fire (not POSTCOMBAT_MAIN)"
        )


def test_does_not_fire_with_non_empty_stack():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    opp_idx = 1 - state.active_player_idx
    _force_step(
        adapter, Step.POSTCOMBAT_MAIN, priority_idx=opp_idx,
    )
    state.stack.append(object())

    assert adapter._should_skip_opp_postcombat_main() is False


def test_does_not_fire_during_factored_combat_decision():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    opp_idx = 1 - state.active_player_idx
    _force_step(
        adapter, Step.POSTCOMBAT_MAIN, priority_idx=opp_idx,
    )
    from mtg_bot.search.engine_adapter import _COMBAT_ATTACKERS
    adapter._combat_phase = _COMBAT_ATTACKERS

    assert adapter._should_skip_opp_postcombat_main() is False


# ---------------------------------------------------------------------
# Disabled flag
# ---------------------------------------------------------------------


def test_disabled_flag():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state,
        heuristics=HeuristicsConfig(
            skip_opp_postcombat_main_enabled=False,
        ),
    )
    opp_idx = 1 - state.active_player_idx
    _force_step(
        adapter, Step.POSTCOMBAT_MAIN, priority_idx=opp_idx,
    )

    assert adapter._should_skip_opp_postcombat_main() is False


# ---------------------------------------------------------------------
# Default + clone propagation
# ---------------------------------------------------------------------


def test_flag_propagates_through_clone():
    state = _fresh_state()
    adapter_on = MtgGameStateAdapter(
        state,
        heuristics=HeuristicsConfig(
            skip_opp_postcombat_main_enabled=True,
        ),
    )
    clone_on = adapter_on.clone()
    assert clone_on._heuristics.skip_opp_postcombat_main_enabled is True

    state2 = _fresh_state()
    adapter_off = MtgGameStateAdapter(
        state2,
        heuristics=HeuristicsConfig(
            skip_opp_postcombat_main_enabled=False,
        ),
    )
    clone_off = adapter_off.clone()
    assert clone_off._heuristics.skip_opp_postcombat_main_enabled is False
