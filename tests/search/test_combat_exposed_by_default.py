"""Pin: ``MtgGameStateAdapter`` exposes combat as search nodes by
default — ``expose_combat_decisions`` defaults to True so callers
get ``AttackerDecision`` / ``BlockerDecision`` branching at combat
steps without opting in. The flag is still honored when explicitly
set to False (auto-resolve via DefaultTacticalAgent's "attack-all,
block-nothing" policy)."""

from __future__ import annotations

from mtg_bot.actions import DeclareAttackers, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import AttackerDecision, MtgGameStateAdapter
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


def _state_with_attacker(seed: int = 42):
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear.summoning_sick = False
    state.battlefield.append(bear)
    return state


def _drive_to(adapter: MtgGameStateAdapter, step: Step) -> None:
    for _ in range(200):
        if adapter.is_terminal():
            return
        if adapter.engine_state.step == step:
            return
        legal = adapter.legal_decisions()
        pass_pick = next(
            (d for d in legal if isinstance(d, PassPriority)), None,
        )
        if pass_pick is None:
            return
        adapter.apply(pass_pick)


def test_default_constructor_exposes_combat_decisions():
    """No flag passed → AttackerDecision shows up in legal_decisions
    at the declare-attackers step."""
    adapter = MtgGameStateAdapter(_state_with_attacker())
    _drive_to(adapter, Step.DECLARE_ATTACKERS)
    legal = adapter.legal_decisions()
    assert any(isinstance(d, AttackerDecision) for d in legal), (
        "expected AttackerDecision in legal_decisions when combat "
        "exposure is on by default"
    )


def test_explicit_opt_out_still_works():
    """Passing ``expose_combat_decisions=False`` restores the
    auto-resolve path — the adapter applies the tactical agent's
    declare_attackers internally and search never sees per-creature
    attack decisions."""
    adapter = MtgGameStateAdapter(
        _state_with_attacker(),
        expose_combat_decisions=False,
    )
    _drive_to(adapter, Step.DECLARE_ATTACKERS)
    legal = adapter.legal_decisions()
    # No AttackerDecision should be exposed.
    assert not any(isinstance(d, AttackerDecision) for d in legal)
    # The adapter either auto-resolved combat (advancing past the
    # step) or surfaced ordinary priority actions; either way no
    # per-creature AttackerDecision is in legal_decisions.
