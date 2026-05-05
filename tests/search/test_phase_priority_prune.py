"""Tests for the phase-based active-priority prune.

Heuristic contract:
- When ``phase_prune_enabled=True`` (default) AND the active player
  has priority AND the stack is empty AND the current step is one of
  UPKEEP / DRAW / BEGINNING_OF_COMBAT / END, ``legal_decisions``
  returns ``[PassPriority()]`` without invoking ``legal.legal_actions``.
- When ``phase_prune_enabled=False``, the prune never fires — the
  adapter behaves as if the heuristic didn't exist.
- The prune is ACTIVE-only; opp's priority during these same steps
  routes through the existing opp-capability auto-pass instead.
- Main phases (PRECOMBAT_MAIN / POSTCOMBAT_MAIN) and the rest of the
  combat sub-steps are NOT pruned.
- A non-empty stack disables the prune (the player may want to
  respond to a triggered ability waiting to resolve).
- The phase-prune short-circuit fires BEFORE the opp-capability path,
  so when both would apply (active priority during a pruned step) the
  phase rule is the one that fires; the opp-capability hash is never
  computed for that decision moment.
"""

from __future__ import annotations

from unittest import mock

from mtg_bot import legal as legal_mod
from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search import HeuristicsConfig, MtgGameStateAdapter
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _fresh_state(seed: int = 42):
    return setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )


def _spy_legal_actions(monkeypatch):
    """Patch every entry point so call counting catches all calls.
    Mirrors the helper in ``test_opp_capability_autopass``."""
    real = legal_mod.legal_actions
    spy = mock.Mock(wraps=real)
    monkeypatch.setattr(legal_mod, "legal_actions", spy)
    from mtg_bot.search import engine_adapter as ea_mod
    monkeypatch.setattr(ea_mod, "legal_actions", spy)
    from mtg_bot.training import action_encoding as ae_mod
    monkeypatch.setattr(ae_mod, "legal_actions", spy)
    return spy


def _disable_capability_short_circuit(monkeypatch, adapter):
    """Force ``_can_short_circuit_to_pass`` to False so the only
    short-circuit under test is phase-prune. Without this, the
    capability auto-pass (merged earlier) fires before phase-prune
    can be observed via the spy on ``legal_actions``."""
    monkeypatch.setattr(
        adapter, "_can_short_circuit_to_pass", lambda: False,
    )


def _force_step(adapter: MtgGameStateAdapter, step: Step) -> None:
    """Force the adapter into ``step`` by setting engine fields directly.

    This bypasses the natural step progression because we want each
    test to start in a known step without relying on phase-by-phase
    pass-priority hammering through other prunable steps. Priority is
    set to the active player and the stack is left as-is (caller can
    populate or clear).
    """
    state = adapter.engine_state
    state.step = step
    state.priority_player_idx = state.active_player_idx
    # Adapter bookkeeping: pretend the step's pre-priority logic has
    # already run, so a follow-up apply() doesn't re-enter the step.
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()


# ---------------------------------------------------------------------
# Per-step prune coverage (active player, empty stack, default flag)
# ---------------------------------------------------------------------


def test_phase_prune_active_upkeep_empty_stack_returns_pass_only(
    monkeypatch,
):
    """Active player priority at own UPKEEP step, empty stack →
    ``[PassPriority()]`` without consulting ``legal_actions``."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.UPKEEP)
    assert adapter.engine_state.stack == []

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0


def test_phase_prune_active_draw_empty_stack_returns_pass_only(
    monkeypatch,
):
    """Active player priority at own DRAW step, empty stack."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.DRAW)
    assert adapter.engine_state.stack == []

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0


def test_phase_prune_active_boc_empty_stack_returns_pass_only(
    monkeypatch,
):
    """Active player priority at own BEGINNING_OF_COMBAT step,
    empty stack."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.BEGINNING_OF_COMBAT)
    assert adapter.engine_state.stack == []

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0


def test_phase_prune_active_endstep_empty_stack_returns_pass_only(
    monkeypatch,
):
    """Active player priority at own END step, empty stack."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.END)
    assert adapter.engine_state.stack == []

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    assert decisions == [PassPriority()]
    assert spy.call_count == 0


# ---------------------------------------------------------------------
# Negative cases — prune must NOT fire
# ---------------------------------------------------------------------


def test_phase_prune_active_main_phase_does_NOT_prune(monkeypatch):
    """Main phases (PRECOMBAT_MAIN, POSTCOMBAT_MAIN) are NOT pruned —
    the active player's main phase is where they actually play stuff.
    """
    for step in (Step.PRECOMBAT_MAIN, Step.POSTCOMBAT_MAIN):
        state = _fresh_state()
        adapter = MtgGameStateAdapter(state)
        _force_step(adapter, step)

        spy = _spy_legal_actions(monkeypatch)
        adapter.legal_decisions()

        assert spy.call_count == 1, (
            f"main phase {step} must not prune; got call_count="
            f"{spy.call_count}"
        )
        # Reset spy for next iteration.
        monkeypatch.undo()


def test_phase_prune_active_combat_substeps_do_NOT_prune(monkeypatch):
    """Other combat sub-steps (DECLARE_BLOCKERS, COMBAT_DAMAGE,
    END_OF_COMBAT) are NOT pruned. Only BEGINNING_OF_COMBAT is in
    the prune set; the rest expose meaningful priority windows."""
    # We test the priority-bearing combat steps that aren't BoC.
    # DECLARE_ATTACKERS / DECLARE_BLOCKERS use the factored combat
    # path so we skip them here (their priority window is gated on
    # combat_phase, which the adapter handles separately) — focus on
    # COMBAT_DAMAGE and END_OF_COMBAT.
    for step in (Step.COMBAT_DAMAGE, Step.END_OF_COMBAT):
        state = _fresh_state()
        # Disable skip-empty-combat too — with no attacking creatures
        # in the fresh fixture, that heuristic would also fire and
        # mask the spy call we're asserting.
        adapter = MtgGameStateAdapter(state)
        _force_step(adapter, step)
        _disable_capability_short_circuit(monkeypatch, adapter)

        spy = _spy_legal_actions(monkeypatch)
        adapter.legal_decisions()

        assert spy.call_count == 1, (
            f"combat sub-step {step} must not prune; got "
            f"call_count={spy.call_count}"
        )
        monkeypatch.undo()


def test_phase_prune_non_empty_stack_does_NOT_prune(monkeypatch):
    """When the stack has spells / abilities waiting to resolve, the
    active player MAY want to respond — even at upkeep. Stay engaged.
    """
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.UPKEEP)
    # Synthesize a fake stack item so ``len(state.stack) > 0`` is
    # True. The contents don't have to be a real spell — the prune
    # check only inspects ``len(stack)``, never the items themselves.
    adapter.engine_state.stack.append(object())
    _disable_capability_short_circuit(monkeypatch, adapter)

    spy = _spy_legal_actions(monkeypatch)
    adapter.legal_decisions()

    assert spy.call_count == 1, (
        "non-empty stack must disable the phase prune"
    )


def test_phase_prune_opp_priority_does_NOT_prune():
    """Active-only: the phase prune helper returns False when the
    player with priority is NOT the active player, regardless of step.

    (At opp's priority during these steps, the opp-capability
    auto-pass is what may fire — but that's a different code path.
    This test pins the active-only condition on the phase prune
    helper itself.)
    """
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.UPKEEP)
    # Move priority to the non-active player.
    apidx = adapter.engine_state.active_player_idx
    opp_idx = (apidx + 1) % len(adapter.engine_state.players)
    adapter.engine_state.priority_player_idx = opp_idx

    # The phase prune is active-only: helper returns False even though
    # step + stack-empty conditions are met.
    assert adapter._should_phase_prune_priority() is False


# ---------------------------------------------------------------------
# Flag wiring
# ---------------------------------------------------------------------


def test_phase_prune_disabled_via_flag(monkeypatch):
    """When ``phase_prune_enabled=False``, the prune never fires —
    the adapter enumerates ``legal_actions`` even at the prunable
    steps with empty stack."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(phase_prune_enabled=False),
    )
    _force_step(adapter, Step.UPKEEP)
    _disable_capability_short_circuit(monkeypatch, adapter)

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    # legal_actions was called.
    assert spy.call_count == 1
    # And the decisions list is the full enumeration, not the single-
    # element ``[PassPriority()]`` we'd see if the prune fired.
    # (At upkeep with empty stack, the only legal action is
    # PassPriority, but that comes from legal_actions itself, not from
    # the heuristic short-circuit. The discriminator is the spy count
    # — the prune path produces ``[PassPriority()]`` with zero spy
    # calls; the natural path produces a list containing PassPriority
    # with one spy call.)
    assert any(isinstance(d, PassPriority) for d in decisions)


def test_phase_prune_flag_propagates_through_clone():
    """``phase_prune_enabled`` survives ``clone()`` — both source and
    clone use the same heuristic setting. This matters for ISMCTS,
    which clones the root adapter many times per descent."""
    state = _fresh_state()
    adapter_on = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(phase_prune_enabled=True),
    )
    clone_on = adapter_on.clone()
    assert clone_on._heuristics.phase_prune_enabled is True

    state2 = _fresh_state()
    adapter_off = MtgGameStateAdapter(
        state2,
        heuristics=HeuristicsConfig(phase_prune_enabled=False),
    )
    clone_off = adapter_off.clone()
    assert clone_off._heuristics.phase_prune_enabled is False


# ---------------------------------------------------------------------
# Composition with opp-capability auto-pass
# ---------------------------------------------------------------------


def test_phase_prune_combined_with_capability_check_no_double_short_circuit(
    monkeypatch,
):
    """When the phase prune fires, the opp-capability hash is NOT
    computed (the phase prune check returns first). This is a
    performance pin: the cheaper check runs first and the more
    expensive check is skipped on a phase-prune hit.

    We assert this by patching ``opp_capability_hash`` and confirming
    it's NEVER called during a phase-prune-eligible decision moment.
    """
    from mtg_bot.search import _opp_capabilities as oc_mod
    from mtg_bot.search import engine_adapter as ea_mod

    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.UPKEEP)

    # Spy on opp_capability_hash via the adapter's import alias.
    hash_spy = mock.Mock(wraps=oc_mod.opp_capability_hash)
    monkeypatch.setattr(
        ea_mod, "opp_capability_hash", hash_spy,
    )
    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    # Phase prune fired: PassPriority only, no legal_actions.
    assert decisions == [PassPriority()]
    assert spy.call_count == 0
    # And the opp-capability hash never ran. The phase prune is the
    # one that short-circuited; the opp-capability path was never
    # entered (priority was on the active player anyway, but the
    # important thing here is that ordering puts phase-prune first).
    assert hash_spy.call_count == 0


def test_phase_prune_composes_with_opp_capability_for_opp_at_upkeep(
    monkeypatch,
):
    """A nuance: opp's priority at active player's upkeep can ALSO
    be auto-passed — but via the opp-capability path, not the phase
    prune. Pin that the right path fires (legal_actions still skipped
    for an opp with nothing castable; spy count stays at 0)."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.UPKEEP)
    apidx = adapter.engine_state.active_player_idx
    opp_idx = (apidx + 1) % len(adapter.engine_state.players)
    adapter.engine_state.priority_player_idx = opp_idx
    # Strip opp so opp-capability auto-pass fires.
    opp = adapter.engine_state.players[opp_idx]
    adapter.engine_state.battlefield = [
        o for o in adapter.engine_state.battlefield
        if o.controller_id != opp.id and o.owner_id != opp.id
    ]
    opp.hand = []
    opp.graveyard = []
    opp.exile = []
    opp.mana_pool = []
    adapter._invalidate_legal_actions_cache()

    spy = _spy_legal_actions(monkeypatch)
    decisions = adapter.legal_decisions()

    # Opp-capability fired (not phase prune — phase prune is
    # active-only). Either way the observable result is the same:
    # PassPriority only, no legal_actions enumeration.
    assert decisions == [PassPriority()]
    assert spy.call_count == 0


# ---------------------------------------------------------------------
# Cleanup-step edge case
# ---------------------------------------------------------------------


def test_phase_prune_cleanup_step_does_NOT_prune(monkeypatch):
    """CLEANUP is not in ``STEPS_WITH_PRIORITY`` (the adapter never
    surfaces a priority moment there), and not in the prune set
    either. This test pins that the prune check returns False for
    CLEANUP — exercising the ``step in _PHASE_PRUNE_STEPS`` branch
    on the False side for a non-priority step.

    We invoke the helper directly because the adapter would never
    actually present CLEANUP as a decision moment to a search caller.
    """
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _force_step(adapter, Step.CLEANUP)
    assert adapter._should_phase_prune_priority() is False


# ---------------------------------------------------------------------
# Self-test: the helper itself
# ---------------------------------------------------------------------


def test_should_phase_prune_priority_returns_false_when_disabled():
    """Direct unit test of the helper: when the flag is off, the
    helper returns False even if every other condition is met."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(phase_prune_enabled=False),
    )
    _force_step(adapter, Step.UPKEEP)
    assert adapter._should_phase_prune_priority() is False


def test_should_phase_prune_priority_returns_true_when_all_conditions_met():
    """Direct unit test: helper returns True at active-player
    upkeep / empty stack."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(phase_prune_enabled=True),
    )
    _force_step(adapter, Step.UPKEEP)
    assert adapter._should_phase_prune_priority() is True
