"""Tests for the skip-empty-combat priority short-circuit.

Heuristic contract:
- When ``skip_empty_combat_enabled=True`` (default) AND the stack is
  empty AND the step is one of DECLARE_ATTACKERS / DECLARE_BLOCKERS
  / COMBAT_DAMAGE / END_OF_COMBAT AND no creature on the battlefield
  is currently attacking, ``legal_decisions`` returns
  ``[PassPriority()]`` without invoking ``legal.legal_actions``.
- Fires for BOTH active and opponent priority windows.
- When ``skip_empty_combat_enabled=False``, the heuristic never fires.
- Disabled by the presence of any attacking creature on the
  battlefield, even if other conditions match.
- Disabled by a non-empty stack.
- Disabled outside the four combat sub-steps.
- Disabled at a factored attacker/blocker decision moment (those
  use ``_combat_phase`` and aren't priority windows).
"""

from __future__ import annotations

from unittest import mock

from mtg_bot import legal as legal_mod
from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search import MtgGameStateAdapter
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


def _force_step(adapter, step: Step, *, priority_idx: int | None = None):
    state = adapter.engine_state
    state.step = step
    state.priority_player_idx = (
        priority_idx if priority_idx is not None
        else state.active_player_idx
    )
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()


def _clear_attacking_flags(state):
    """Make sure no creature is marked as attacking. Default state from
    setup_game has no attacking flags set, but be defensive."""
    for o in state.battlefield:
        o.attacking = False


# ---------------------------------------------------------------------
# Per-step happy path: heuristic fires at all 4 combat sub-steps
# ---------------------------------------------------------------------


def test_fires_at_each_combat_substep_with_no_attackers(monkeypatch):
    """All 4 combat sub-steps short-circuit when no attacking creatures
    are on the battlefield."""
    for step in (
        Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS,
        Step.COMBAT_DAMAGE, Step.END_OF_COMBAT,
    ):
        state = _fresh_state()
        adapter = MtgGameStateAdapter(state)
        _clear_attacking_flags(state)
        _force_step(adapter, step)

        spy = _spy_legal_actions(monkeypatch)
        decisions = adapter.legal_decisions()

        assert decisions == [PassPriority()], (
            f"step {step}: expected [PassPriority], got {decisions}"
        )
        assert spy.call_count == 0, (
            f"step {step}: legal_actions should not be called"
        )
        monkeypatch.undo()


def test_fires_at_opp_priority_during_combat(monkeypatch):
    """Heuristic fires at OPP priority during combat sub-steps too —
    not just active. With no attackers, opp's instant-speed window is
    also dead."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _clear_attacking_flags(state)
    _force_step(
        adapter, Step.COMBAT_DAMAGE,
        priority_idx=1 - state.active_player_idx,
    )

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0


# ---------------------------------------------------------------------
# Negative cases: each guard
# ---------------------------------------------------------------------


def test_does_not_fire_when_creature_is_attacking(monkeypatch):
    """If any creature on the battlefield is attacking, the heuristic
    does NOT fire — there are real combat tricks to consider."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _clear_attacking_flags(state)
    # Synthesize an attacking flag on some creature. If no creatures
    # exist in the fresh state, materialize one.
    creatures = [o for o in state.battlefield if o.printing.is_creature]
    if not creatures:
        from mtg_bot.cards import SYNTHETIC_CREATURES
        from mtg_bot.game import Zone
        bear = state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"],
            owner_id=state.active_player().id, zone=Zone.BATTLEFIELD,
        )
        bear.controller_id = state.active_player().id
        bear.summoning_sick = False
        state.battlefield.append(bear)
        creatures = [bear]
    creatures[0].attacking = True
    _force_step(adapter, Step.COMBAT_DAMAGE)

    assert adapter._should_skip_empty_combat() is False


def test_does_not_fire_with_non_empty_stack(monkeypatch):
    """Non-empty stack disables the heuristic — there's something
    to potentially respond to."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _clear_attacking_flags(state)
    _force_step(adapter, Step.COMBAT_DAMAGE)
    state.stack.append(object())

    assert adapter._should_skip_empty_combat() is False


def test_does_not_fire_outside_combat_substeps(monkeypatch):
    """Steps outside the 4 combat sub-steps are unaffected — UPKEEP /
    DRAW / MAIN / END / etc. fall through to other heuristics."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _clear_attacking_flags(state)
    for step in (
        Step.UPKEEP, Step.DRAW, Step.PRECOMBAT_MAIN,
        Step.POSTCOMBAT_MAIN, Step.END,
    ):
        _force_step(adapter, step)
        assert adapter._should_skip_empty_combat() is False, (
            f"step {step}: should not fire (not a combat sub-step)"
        )


def test_does_not_fire_during_factored_combat_decision(monkeypatch):
    """When ``_combat_phase`` is set (factored attacker/blocker
    decision phase), the heuristic does NOT fire — those are
    pre-priority decision windows, not the post-declaration priority
    windows the heuristic targets."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _clear_attacking_flags(state)
    _force_step(adapter, Step.DECLARE_ATTACKERS)
    # Simulate the per-attacker decision phase.
    from mtg_bot.search.engine_adapter import _COMBAT_ATTACKERS
    adapter._combat_phase = _COMBAT_ATTACKERS

    assert adapter._should_skip_empty_combat() is False


# ---------------------------------------------------------------------
# Disabled flag
# ---------------------------------------------------------------------


def test_disabled_flag(monkeypatch):
    """``skip_empty_combat_enabled=False`` disables the short-circuit
    — legal_decisions enumerates legal_actions normally."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state, skip_empty_combat_enabled=False)
    _clear_attacking_flags(state)
    _force_step(adapter, Step.COMBAT_DAMAGE)

    assert adapter._should_skip_empty_combat() is False


# ---------------------------------------------------------------------
# Default flag value pin
# ---------------------------------------------------------------------


def test_flag_propagates_through_clone():
    """``skip_empty_combat_enabled`` survives ``clone()`` — both source
    and clone use the same heuristic setting. ISMCTS clones the root
    adapter many times per descent."""
    state = _fresh_state()
    adapter_on = MtgGameStateAdapter(state, skip_empty_combat_enabled=True)
    clone_on = adapter_on.clone()
    assert clone_on._skip_empty_combat_enabled is True

    state2 = _fresh_state()
    adapter_off = MtgGameStateAdapter(state2, skip_empty_combat_enabled=False)
    clone_off = adapter_off.clone()
    assert clone_off._skip_empty_combat_enabled is False
