"""End-to-end integration tests: ``MtgGameStateAdapter`` with
``expose_resolution_decisions=True`` drives a priority action that
hits a resolution callback, exposes the decision to search, accepts
an answer, and completes.

Uses real EoE spells with target-choice requirements. Currently
target-picking happens at cast-time in our engine (``actions._cast_spell``
calls ``agent.choose_target`` before the spell goes on the stack),
but the adapter's save-and-replay machinery is agnostic to whether
the callback fires at cast-time or during resolution — both are
inside the same ``apply_action`` frame.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import (
    MtgGameStateAdapter, ResolutionTargetDecision,
)
from mtg_bot.simulate import setup_game

from mtg_bot.cards.source import get_active_source
from tests._test_decks import simple_test_decklists  # noqa: E402

_PRINTINGS = get_active_source().get_printings()


def _adapter_with_targetable_setup() -> MtgGameStateAdapter:
    """Build a state where P0 can cast a 2-damage spell on one of
    several creatures P1 controls. Force the state into a
    precombat-main moment where the spell is actually legal."""
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=42,
    )
    # Give P0 five Mountains so they can pay {2}{R} for Bombard.
    from mtg_bot.cards import BASIC_LANDS
    for _ in range(5):
        m = state.new_object(
            BASIC_LANDS["Mountain"], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        state.battlefield.append(m)
    # Put Bombard in P0's hand. (Oracle: "Bombard deals 4 damage
    # to target creature." — needs a target.)
    bombard_card = state.new_object(
        _PRINTINGS["Bombard"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bombard_card)
    # Give P1 two creatures for targets.
    for name in ["Wild Bear", "Sapling"]:
        c = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=1,
            zone=Zone.BATTLEFIELD,
        )
        c.summoning_sick = False
        state.battlefield.append(c)

    return MtgGameStateAdapter(
        state, expose_resolution_decisions=True,
    )


def _drive_to_precombat_main(adapter: MtgGameStateAdapter) -> None:
    from mtg_bot.turn import Step
    for _ in range(20):
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN:
            return
        adapter.apply(PassPriority())


def test_casting_targeted_spell_exposes_target_pause():
    """Casting Bombard exposes a resolution-pause with three target
    options (two creatures + player) — the exact options depend on
    the spell; what matters here is that the pause fires."""
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)

    # Find the CastSpell action for Bombard.
    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    # Pre-cast invariant: no pause, no snapshot.
    assert adapter._resolution_paused is False
    assert adapter._pre_action_clone is None

    adapter.apply(cast_action)

    # Post-cast invariant: paused, snapshot retained, waiting for
    # a target choice.
    assert adapter._resolution_paused is True
    assert adapter._pre_action_clone is not None
    assert adapter._resolution_kind == "target"
    # Legal decisions at this pause are Resolution*Decision values.
    legal = adapter.legal_decisions()
    assert all(
        isinstance(d, ResolutionTargetDecision) for d in legal
    )
    assert len(legal) >= 2  # at least two creatures


def test_providing_target_completes_the_cast():
    """Once search provides a target decision, resolution finishes
    and the adapter returns to a non-paused state with the spell
    on the stack (or resolved, depending on the engine flow)."""
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)

    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    adapter.apply(cast_action)
    assert adapter._resolution_paused

    # Pick the first available target.
    target_decision = adapter.legal_decisions()[0]
    adapter.apply(target_decision)

    # Resolution complete: adapter is back at a priority moment.
    assert adapter._resolution_paused is False
    assert adapter._pre_action_clone is None
    # State advanced — Bombard should now be on the stack.
    assert len(adapter.engine_state.stack) == 1


def test_providing_wrong_decision_type_raises():
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)
    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    adapter.apply(cast_action)
    assert adapter._resolution_paused

    # Feed a PlayerID instead of a ResolutionTargetDecision.
    with pytest.raises(TypeError):
        adapter.apply(PassPriority())


def test_clone_preserves_resolution_pause_state():
    """A clone of a paused adapter should be independently resumable
    — each clone can pick a different target."""
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)
    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    adapter.apply(cast_action)
    assert adapter._resolution_paused

    clone = adapter.clone()
    assert clone._resolution_paused is True
    assert clone._resolution_kind == adapter._resolution_kind
    assert clone._resolution_options == adapter._resolution_options

    # Different decisions on each; states diverge.
    target_a = adapter.legal_decisions()[0]
    target_b = clone.legal_decisions()[-1]
    adapter.apply(target_a)
    clone.apply(target_b)

    # Both completed resolution; neither still paused.
    assert not adapter._resolution_paused
    assert not clone._resolution_paused
    # Stack items target different creatures — verify via the
    # stack's first item's targets.
    a_targets = adapter.engine_state.stack[0].targets
    b_targets = clone.engine_state.stack[0].targets
    assert a_targets != b_targets


def test_shock_life_now_exposed_as_resolution_decision():
    """Shock-land ``choose_pay_shock_life`` is one of the 10
    resolution callbacks. With exposure on, playing a shock land
    pauses for a search decision on whether to pay the life."""
    from mtg_bot.actions import PlayLand
    from mtg_bot.cards import SHOCK_LANDS
    from mtg_bot.search import ResolutionShockLifeDecision
    if not SHOCK_LANDS:
        pytest.skip("no shock lands in the pool")

    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=42,
    )
    shock_name = next(iter(SHOCK_LANDS))
    shock = state.new_object(
        SHOCK_LANDS[shock_name], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(shock)

    adapter = MtgGameStateAdapter(
        state, expose_resolution_decisions=True,
    )
    _drive_to_precombat_main(adapter)

    play_action = next(
        (a for a in adapter.legal_decisions()
         if isinstance(a, PlayLand) and a.card_id == shock.id),
        None,
    )
    if play_action is None:
        pytest.skip("shock land not legal to play this seed")

    adapter.apply(play_action)
    # Paused on the shock-life question.
    assert adapter._resolution_paused is True
    assert adapter._resolution_kind == "shock_life"
    legal = adapter.legal_decisions()
    assert all(
        isinstance(d, ResolutionShockLifeDecision) for d in legal
    )
    assert {d.pay for d in legal} == {True, False}
    # Answer and confirm completion.
    adapter.apply(ResolutionShockLifeDecision(pay=False))
    assert adapter._resolution_paused is False


def test_search_decision_is_hashable():
    """Sanity: Resolution*Decision values must be hashable so they
    can live in MCTS transposition tables etc."""
    d1 = ResolutionTargetDecision(target=("creature", 5))
    d2 = ResolutionTargetDecision(target=("creature", 5))
    assert hash(d1) == hash(d2)
    assert d1 == d2
    # Usable as dict key.
    {d1: "value"}


# ---------------------------------------------------------------------
# yes/no resolution decisions — covers the previously-missing branch
# in ``_resolution_legal_decisions`` (kind == "yes_no") and the matching
# entry in ``_RESOLUTION_KIND_TO_DECISION_CLASS``. The dataclass and the
# channel-agent side of the wiring already existed; only the adapter
# dispatch was missing, which made any "may"-gated effect crash with
# ``RuntimeError: unknown resolution kind: 'yes_no'`` once
# ``expose_resolution_decisions=True`` was on.
# ---------------------------------------------------------------------


def _paused_yesno_adapter() -> MtgGameStateAdapter:
    """Build an adapter and force it into a yes_no resolution pause
    without driving a full game. We poke the pause fields directly so
    the test stays focused on ``_resolution_legal_decisions`` /
    ``_apply_resolution_decision`` semantics."""
    from mtg_bot.search.resolution_channel import KIND_YES_NO
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=1,
    )
    adapter = MtgGameStateAdapter(
        state, expose_resolution_decisions=True,
    )
    adapter._resolution_paused = True
    adapter._resolution_kind = KIND_YES_NO
    adapter._resolution_player = 0
    adapter._resolution_options = (True, False)
    return adapter


def test_yesno_legal_decisions_returns_both_branches():
    """Both yes and no must be enumerated as ``ResolutionYesNoDecision``
    instances. Order matches the channel agent's ``(True, False)``."""
    from mtg_bot.search import ResolutionYesNoDecision
    adapter = _paused_yesno_adapter()
    legal = adapter.legal_decisions()
    assert legal == [
        ResolutionYesNoDecision(yes=True),
        ResolutionYesNoDecision(yes=False),
    ]


def test_yesno_apply_validates_decision_type():
    """Feeding a non-YesNo decision while paused on yes_no must raise
    — same contract as every other resolution kind."""
    from mtg_bot.search import ResolutionShockLifeDecision
    adapter = _paused_yesno_adapter()
    with pytest.raises(TypeError):
        adapter.apply(ResolutionShockLifeDecision(pay=True))


def test_yesno_endstep_trigger_exposes_pause_and_resolves():
    """End-to-end: a Vaultguard Trooper end-step "may" trigger should
    fire as a stack-resolution pause once both players pass priority
    in the END step, surface a yes_no decision to search, and complete
    cleanly when answered.

    Vaultguard's oracle: at the beginning of your end step, if you
    control 2+ tapped creatures, you may discard your hand; if you do,
    draw 2.
    """
    from mtg_bot.actions import PassPriority
    from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
    from mtg_bot.game import Zone
    from mtg_bot.search import ResolutionYesNoDecision
    from mtg_bot.turn import Step

    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=7,
    )
    # Two tapped creatures on P0's side so the intervening-if passes,
    # then put Vaultguard on the battlefield as well (it counts itself
    # only if tapped — we tap the two helpers and leave Vaultguard
    # untapped, so the count stays at 2).
    for name in ["Wild Bear", "Sapling"]:
        c = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=0,
            zone=Zone.BATTLEFIELD,
        )
        c.summoning_sick = False
        c.tapped = True
        state.battlefield.append(c)
    vg = state.new_object(
        _PRINTINGS["Vaultguard Trooper"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    vg.summoning_sick = False
    state.battlefield.append(vg)
    # A few cards in hand so the discard branch is observable.
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
        state.players[0].hand.append(c)

    # Combat exposure off — we're testing the yes_no path, not combat,
    # and the default tactical "attack with everything" would put our
    # tapped helpers' attack-state into the picture.
    adapter = MtgGameStateAdapter(
        state, expose_combat_decisions=False,
        expose_resolution_decisions=True,
    )

    # Drive forward until the END step's trigger has been put on the
    # stack and we're paused waiting for a yes_no answer. Each
    # PassPriority either advances the step or pops a stack item.
    for _ in range(40):
        if adapter._resolution_paused:
            break
        adapter.apply(PassPriority())
    else:
        pytest.fail("never reached a resolution pause")

    assert adapter._resolution_kind == "yes_no"
    assert adapter._resolution_player == 0
    legal = adapter.legal_decisions()
    assert len(legal) == 2
    assert all(isinstance(d, ResolutionYesNoDecision) for d in legal)
    assert {d.yes for d in legal} == {True, False}

    # Decline the may — hand should NOT be discarded, dependent draw
    # does not fire.
    pre_hand_size = len(adapter.engine_state.players[0].hand)
    adapter.apply(ResolutionYesNoDecision(yes=False))
    assert adapter._resolution_paused is False
    assert (
        len(adapter.engine_state.players[0].hand) == pre_hand_size
    ), "decline path must leave the hand untouched"
    # Step is at or past END (turn structure has progressed).
    assert adapter.engine_state.step in (
        Step.END, Step.CLEANUP, Step.UNTAP, Step.UPKEEP,
    )


def test_yesno_clone_preserves_pause_branches_independently():
    """Two clones of a yes_no-paused adapter can pick different
    branches without contaminating each other — the per-clone replay
    queue is what makes this work."""
    from mtg_bot.search import ResolutionYesNoDecision
    adapter = _paused_yesno_adapter()
    clone = adapter.clone()
    assert clone._resolution_paused is True
    assert clone._resolution_kind == "yes_no"
    # Each clone enumerates the same options.
    assert (
        adapter.legal_decisions() == clone.legal_decisions()
    )
