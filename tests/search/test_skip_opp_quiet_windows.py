"""Tests for the skip-opp-quiet-windows priority short-circuit.

``docs/SEARCH_LIMITATIONS.md`` entry #17. Heuristic contract:

- When ``skip_opp_quiet_windows_enabled=True`` AND the stack is empty
  AND the step is UPKEEP, DRAW or PRECOMBAT_MAIN AND the NON-active
  player holds priority, ``legal_decisions`` returns
  ``[PassPriority()]`` without invoking ``legal.legal_actions`` -- even
  when that player holds an instant-speed activated ability (which the
  capability auto-pass, #3, would let through).
- It is a search-side policy: the rules engine's ``legal_actions``
  still offers the activation in those windows, and the policy mask
  (``legal_action_mask``) agrees with ``legal_decisions``.
- Kept windows: a non-empty stack in any step, the beginning of
  combat, combat steps with an attacker, the end step. With every
  production heuristic on, the non-active player is still offered the
  activation there.
- The active player's own windows are untouched (that is #6 / #11).
- Postcombat main stays under its own flag (#10); this skip doesn't
  cover it.
- Flag off -> never fires; the flag survives ``clone()``.
"""

from __future__ import annotations

import random
from dataclasses import replace
from unittest import mock

import pytest

from mtg_bot import legal as legal_mod
from mtg_bot.actions import ActivateAbility, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards.base import ActivatedAbility, ActivationCost, make_creature
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.game import StackItem, Zone
from mtg_bot.search import HeuristicsConfig, MtgGameStateAdapter
from mtg_bot.search.engine_adapter import (
    _COMBAT_ATTACKERS,
    _OPP_QUIET_WINDOW_STEPS,
)
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae
from mtg_bot.turn import Step
from tests._cube_artifact_helpers import put
from tests._test_decks import simple_test_decklists  # noqa: E402

_ONLY_THIS = HeuristicsConfig(
    phase_prune_enabled=False,
    force_landdrop_enabled=False,
    skip_empty_combat_enabled=False,
    skip_opp_postcombat_main_enabled=False,
    skip_dead_main1_enabled=False,
    skip_opp_quiet_windows_enabled=True,
)
_PRODUCTION = HeuristicsConfig()
_OFF = HeuristicsConfig(skip_opp_quiet_windows_enabled=False)
_QUIET_STEPS = [Step.UPKEEP, Step.DRAW, Step.PRECOMBAT_MAIN]


def _fresh_state(seed: int = 42):
    return setup_game(
        [RandomAgent(), RandomAgent()], decks=simple_test_decklists(),
        seed=seed,
    )


def _spy_legal_actions(monkeypatch):
    real = legal_mod.legal_actions
    spy = mock.Mock(wraps=real)
    monkeypatch.setattr(legal_mod, "legal_actions", spy)
    from mtg_bot.search import engine_adapter as ea_mod
    monkeypatch.setattr(ea_mod, "legal_actions", spy)
    monkeypatch.setattr(ae, "legal_actions", spy)
    return spy


def _force_step(adapter, step: Step, *, priority_idx: int) -> None:
    state = adapter.engine_state
    state.step = step
    state.priority_player_idx = priority_idx
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()


def _activator(state, controller: int):
    """A permanent with a free, plain (instant-speed) activated ability
    for ``controller`` -- the shape of the Manifold Key / Grindstone /
    Currency Converter windows that drove the search cost."""
    ability = ActivatedAbility(cost=ActivationCost(), effect=DrawCards(amount=1))
    printing = replace(
        make_creature("Quiet Activator", "{1}", 1, 1),
        activated_abilities=(ability,),
    )
    return put(state, printing, controller=controller)


def _opp_window(heuristics, step: Step):
    """Adapter at ``step`` with the NON-active player holding priority
    and an instant-speed activator on their side of the battlefield."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state, heuristics=heuristics)
    opp_idx = 1 - state.active_player_idx
    _force_step(adapter, step, priority_idx=opp_idx)
    obj = _activator(state, controller=state.players[opp_idx].id)
    adapter._invalidate_legal_actions_cache()
    return adapter, state.players[opp_idx].id, obj


def _push_stack_item(state) -> None:
    active_pid = state.players[state.active_player_idx].id
    dummy = state.new_object(
        make_creature("Stacked", "{1}", 1, 1), owner_id=active_pid,
        zone=Zone.STACK,
    )
    state.stack.append(StackItem(source=dummy, controller_id=active_pid))


def _attack_with_something(state) -> None:
    active_pid = state.players[state.active_player_idx].id
    attacker = put(
        state, make_creature("Attacker", "{1}", 2, 2), controller=active_pid,
    )
    attacker.attacking = True


# ---------------------------------------------------------------------
# Scope constant
# ---------------------------------------------------------------------


def test_scope_is_upkeep_draw_and_precombat_main():
    assert _OPP_QUIET_WINDOW_STEPS == frozenset({
        Step.UPKEEP, Step.DRAW, Step.PRECOMBAT_MAIN,
    })


# ---------------------------------------------------------------------
# Skipped windows auto-pass in search
# ---------------------------------------------------------------------


@pytest.mark.parametrize("step", _QUIET_STEPS)
def test_quiet_window_auto_passes_despite_an_activatable_ability(
    monkeypatch, step,
):
    adapter, opp_pid, obj = _opp_window(_PRODUCTION, step)
    # The rules engine offers the activation in this window ...
    assert ActivateAbility(obj.id, 0) in legal_mod.legal_actions(
        adapter.engine_state, opp_pid,
    )
    # ... and the capability check (#3) would let the player through.
    assert adapter._can_short_circuit_to_pass() is False

    adapter._invalidate_legal_actions_cache()
    spy = _spy_legal_actions(monkeypatch)
    assert adapter._should_skip_opp_quiet_window() is True
    assert adapter.legal_decisions() == [PassPriority()]
    assert spy.call_count == 0


@pytest.mark.parametrize("step", _QUIET_STEPS)
def test_only_this_flag_is_enough_to_skip(step):
    adapter, _, _ = _opp_window(_ONLY_THIS, step)
    assert adapter.legal_decisions() == [PassPriority()]


@pytest.mark.parametrize("step", _QUIET_STEPS)
def test_flag_off_offers_the_activation(step):
    adapter, _, obj = _opp_window(_OFF, step)
    assert adapter._should_skip_opp_quiet_window() is False
    decisions = adapter.legal_decisions()
    assert ActivateAbility(obj.id, 0) in decisions
    assert PassPriority() in decisions


def test_mask_agrees_with_the_skip():
    adapter, opp_pid, _ = _opp_window(_PRODUCTION, Step.UPKEEP)
    mask = ae.legal_action_mask(adapter, opp_pid)
    assert mask.sum() == 1
    assert mask[ae.encode(PassPriority(), adapter, opp_pid)]

    adapter_off, opp_pid_off, _ = _opp_window(_OFF, Step.UPKEEP)
    assert ae.legal_action_mask(adapter_off, opp_pid_off).sum() > 1


# ---------------------------------------------------------------------
# Kept windows still offer activations (every production heuristic on)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("step", [Step.BEGINNING_OF_COMBAT, Step.END])
def test_beginning_of_combat_and_end_step_are_kept(step):
    adapter, _, obj = _opp_window(_PRODUCTION, step)
    assert adapter._should_skip_opp_quiet_window() is False
    assert ActivateAbility(obj.id, 0) in adapter.legal_decisions()


@pytest.mark.parametrize("step", [
    Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS, Step.COMBAT_DAMAGE,
    Step.END_OF_COMBAT,
])
def test_combat_steps_with_an_attacker_are_kept(step):
    adapter, _, obj = _opp_window(_PRODUCTION, step)
    _attack_with_something(adapter.engine_state)
    adapter._invalidate_legal_actions_cache()
    assert adapter._should_skip_opp_quiet_window() is False
    assert ActivateAbility(obj.id, 0) in adapter.legal_decisions()


@pytest.mark.parametrize("step", _QUIET_STEPS)
def test_non_empty_stack_is_kept(step):
    adapter, _, obj = _opp_window(_PRODUCTION, step)
    _push_stack_item(adapter.engine_state)
    adapter._invalidate_legal_actions_cache()
    assert adapter._should_skip_opp_quiet_window() is False
    assert ActivateAbility(obj.id, 0) in adapter.legal_decisions()


def test_postcombat_main_is_left_to_its_own_flag():
    """Main 2 is #10's window: with #10 off, this flag doesn't skip it."""
    cfg = HeuristicsConfig(skip_opp_postcombat_main_enabled=False)
    adapter, _, obj = _opp_window(cfg, Step.POSTCOMBAT_MAIN)
    assert adapter._should_skip_opp_quiet_window() is False
    assert ActivateAbility(obj.id, 0) in adapter.legal_decisions()


# ---------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------


@pytest.mark.parametrize("step", _QUIET_STEPS)
def test_active_players_own_windows_are_untouched(step):
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state, heuristics=_ONLY_THIS)
    _force_step(adapter, step, priority_idx=state.active_player_idx)
    assert adapter._should_skip_opp_quiet_window() is False


def test_does_not_fire_during_factored_combat_decision():
    adapter, _, _ = _opp_window(_ONLY_THIS, Step.PRECOMBAT_MAIN)
    adapter._combat_phase = _COMBAT_ATTACKERS
    assert adapter._should_skip_opp_quiet_window() is False


def test_does_not_fire_during_resolution_pause():
    adapter, _, _ = _opp_window(_ONLY_THIS, Step.UPKEEP)
    adapter._resolution_paused = True
    assert adapter._should_skip_opp_quiet_window() is False


def test_does_not_fire_on_a_finished_game():
    adapter, _, _ = _opp_window(_ONLY_THIS, Step.UPKEEP)
    adapter.engine_state.winner_id = adapter.engine_state.players[0].id
    assert adapter._should_skip_opp_quiet_window() is False


def test_flag_propagates_through_clone():
    adapter_on, _, _ = _opp_window(_ONLY_THIS, Step.UPKEEP)
    assert adapter_on.clone()._should_skip_opp_quiet_window() is True
    adapter_off, _, _ = _opp_window(_OFF, Step.UPKEEP)
    clone_off = adapter_off.clone()
    assert clone_off._heuristics.skip_opp_quiet_windows_enabled is False
    assert clone_off._should_skip_opp_quiet_window() is False


# ---------------------------------------------------------------------
# A whole game through the adapter
# ---------------------------------------------------------------------


def test_every_quiet_opponent_window_in_a_game_is_a_forced_pass():
    """Drive real games through the adapter (production heuristics,
    random choices) and check every non-active empty-stack upkeep /
    draw / precombat-main priority moment exposes only the pass, while
    the rules engine kept generating those moments."""
    seen = 0
    for seed in (1, 2, 3):
        state = _fresh_state(seed)
        adapter = MtgGameStateAdapter(state, heuristics=_PRODUCTION)
        rng = random.Random(seed)
        for _ in range(600):
            if adapter.is_terminal():
                break
            decisions = adapter.legal_decisions()
            eng = adapter.engine_state
            if (
                adapter._combat_phase is None
                and not adapter._resolution_paused
                and eng.priority_player_idx != eng.active_player_idx
                and not eng.stack
                and eng.step in _OPP_QUIET_WINDOW_STEPS
            ):
                assert decisions == [PassPriority()], eng.step
                seen += 1
            adapter.apply(rng.choice(decisions))
    assert seen > 0
