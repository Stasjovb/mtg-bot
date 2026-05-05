"""Tests for factored combat decisions exposed by
``MtgGameStateAdapter`` when ``expose_combat_decisions=True``.

Shape of the tests:

- Build a small mid-game-like state with some creatures on both
  sides of the battlefield.
- Wrap in the adapter with combat decisions exposed.
- Drive it through to DECLARE_ATTACKERS and verify the adapter
  enters the ``attackers`` combat phase, exposes per-attacker
  decisions, and finalizes with an engine ``DeclareAttackers`` once
  all per-attacker sub-decisions are made.
- Same for DECLARE_BLOCKERS with attackers on the battlefield.
"""

from __future__ import annotations

from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import (
    AttackerDecision, BlockerDecision, DefaultTacticalAgent,
    MtgGameStateAdapter,
)
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


def _setup_with_creatures(
    p0_creatures: list[str] | None = None,
    p1_creatures: list[str] | None = None,
    seed: int = 42,
    expose_combat: bool = True,
) -> MtgGameStateAdapter:
    """Build a fresh two-player game + drop specified creatures
    onto each player's battlefield (not summoning-sick, untapped)
    so they're combat-ready. Wrap in the adapter."""
    p0_creatures = p0_creatures or []
    p1_creatures = p1_creatures or []
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    for name in p0_creatures:
        obj = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        obj.summoning_sick = False
        state.battlefield.append(obj)
    for name in p1_creatures:
        obj = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=1, zone=Zone.BATTLEFIELD,
        )
        obj.summoning_sick = False
        state.battlefield.append(obj)
    return MtgGameStateAdapter(
        state, expose_combat_decisions=expose_combat,
    )


def _drive_to_step(adapter: MtgGameStateAdapter, target: Step) -> None:
    """Pass priority until the adapter reaches ``target`` or a
    non-priority decision moment. Safety cap to avoid runaway loops."""
    MAX = 100
    for _ in range(MAX):
        if adapter.is_terminal():
            return
        if adapter.engine_state.step == target:
            return
        # If we're mid-combat-phase, drive through it with default
        # AttackerDecision/BlockerDecision "do nothing" picks — but
        # tests that want to exercise combat should catch their
        # target step before reaching combat.
        for decision in adapter.legal_decisions():
            if isinstance(decision, PassPriority):
                adapter.apply(decision)
                break
        else:
            # No pass available — bail.
            return
    raise AssertionError(
        f"failed to reach {target} within {MAX} iterations (still at "
        f"{adapter.engine_state.step})"
    )


# =====================================================================
# Backward compatibility: default adapter behavior unchanged
# =====================================================================

def test_default_adapter_does_not_expose_combat():
    """Without opting in, the adapter handles combat via the
    tactical agent — combat phase is never entered."""
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"], expose_combat=False,
    )
    # Drive through to DECLARE_ATTACKERS via normal priority passes.
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # Adapter should be at priority within DECLARE_ATTACKERS, NOT in
    # a combat phase.
    assert adapter.combat_phase is None


def test_clone_preserves_combat_phase_state():
    adapter = _setup_with_creatures(p0_creatures=["Wild Bear"])
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    assert adapter.combat_phase == "attackers"

    clone = adapter.clone()
    assert clone.combat_phase == "attackers"
    assert clone._pending_attackers == adapter._pending_attackers
    assert clone._chosen_attackers == adapter._chosen_attackers
    # Applying to clone must not affect original.
    decision = clone.legal_decisions()[0]
    clone.apply(decision)
    assert adapter._pending_attackers != clone._pending_attackers or (
        adapter._chosen_attackers != clone._chosen_attackers
    )


# =====================================================================
# Attacker-decision phase
# =====================================================================

def test_declare_attackers_enters_combat_phase_with_exposure():
    adapter = _setup_with_creatures(p0_creatures=["Wild Bear"])
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    assert adapter.combat_phase == "attackers"


def test_active_player_during_attacker_phase_is_turn_holder():
    adapter = _setup_with_creatures(p0_creatures=["Wild Bear"])
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # Active player during attacker decisions is P0 (turn holder),
    # regardless of whose priority it nominally is.
    assert adapter.active_player() == 0


def test_attacker_phase_exposes_attack_or_not_per_attacker():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear", "Forest Giant"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    legal = adapter.legal_decisions()
    assert len(legal) == 2
    assert all(isinstance(d, AttackerDecision) for d in legal)
    # Same attacker, different attack flags.
    ids = {d.attacker_id for d in legal}
    flags = {d.attack for d in legal}
    assert len(ids) == 1
    assert flags == {True, False}


def test_attacker_phase_finalizes_after_all_decisions():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear", "Forest Giant"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # Two eligible attackers → two AttackerDecisions expected
    # before the phase finalizes.
    assert adapter.combat_phase == "attackers"
    for _ in range(2):
        # Always attack.
        d = next(
            d for d in adapter.legal_decisions()
            if isinstance(d, AttackerDecision) and d.attack
        )
        adapter.apply(d)
    # After both decisions: combat phase cleared, priority window
    # opened for DECLARE_ATTACKERS step.
    assert adapter.combat_phase is None
    assert adapter.engine_state.step == Step.DECLARE_ATTACKERS
    # Both creatures should be marked attacking.
    attacking = [
        o for o in adapter.engine_state.battlefield if o.attacking
    ]
    assert len(attacking) == 2


def test_attacker_phase_choosing_not_to_attack_works():
    adapter = _setup_with_creatures(p0_creatures=["Wild Bear"])
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # Pick "don't attack."
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and not d.attack
    )
    adapter.apply(d)
    # Phase cleared, no creature is attacking.
    assert adapter.combat_phase is None
    attacking = [
        o for o in adapter.engine_state.battlefield if o.attacking
    ]
    assert attacking == []


def test_attacker_decision_out_of_order_raises():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear", "Forest Giant"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # Construct an AttackerDecision for a DIFFERENT pending attacker
    # than the head — adapter should reject.
    head_id = adapter._pending_attackers[0]
    other_id = adapter._pending_attackers[1]
    bad = AttackerDecision(attacker_id=other_id, attack=True)
    import pytest
    with pytest.raises(ValueError):
        adapter.apply(bad)


def test_wrong_decision_type_during_attacker_phase_raises():
    adapter = _setup_with_creatures(p0_creatures=["Wild Bear"])
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # Feeding a PassPriority during attacker phase — wrong type.
    import pytest
    with pytest.raises(TypeError):
        adapter.apply(PassPriority())


def test_no_attackers_available_skips_phase():
    """No creatures on active player's side → no combat phase
    entered; adapter goes straight to priority in the step."""
    adapter = _setup_with_creatures(p0_creatures=[], p1_creatures=[])
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    assert adapter.combat_phase is None


# =====================================================================
# Blocker-decision phase
# =====================================================================

def test_declare_blockers_enters_combat_phase_when_attackers_exist():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"], p1_creatures=["Wild Bear"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # Have P0 attack with their Wild Bear.
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and d.attack
    )
    adapter.apply(d)
    # Drain priority through DECLARE_ATTACKERS then advance to
    # DECLARE_BLOCKERS.
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)
    assert adapter.combat_phase == "blockers"


def test_active_player_during_blocker_phase_is_defender():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"], p1_creatures=["Wild Bear"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and d.attack
    )
    adapter.apply(d)
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)
    # Defender = P1.
    assert adapter.active_player() == 1


def test_blocker_phase_exposes_block_or_none_per_blocker():
    """With one attacker and one eligible blocker, the blocker
    decision has exactly two options: block that attacker, or
    don't block."""
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"], p1_creatures=["Sapling"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and d.attack
    )
    adapter.apply(d)
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)

    legal = adapter.legal_decisions()
    assert all(isinstance(d, BlockerDecision) for d in legal)
    assert len(legal) == 2
    attacker_ids_seen = {d.attacker_id for d in legal}
    assert None in attacker_ids_seen  # don't-block option present


def test_blocker_phase_finalizes_after_all_decisions():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"],
        p1_creatures=["Sapling", "Wild Bear"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # P0 attacks with their bear.
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and d.attack
    )
    adapter.apply(d)
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)
    assert adapter.combat_phase == "blockers"

    # Two eligible blockers — two BlockerDecisions to commit.
    for _ in range(2):
        legal = adapter.legal_decisions()
        # Take the "don't block" option every time for simplicity.
        d = next(
            d for d in legal
            if isinstance(d, BlockerDecision) and d.attacker_id is None
        )
        adapter.apply(d)

    assert adapter.combat_phase is None


def test_blocker_phase_skipped_when_no_attackers():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"], p1_creatures=["Sapling"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    # P0 DECLINES to attack.
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and not d.attack
    )
    adapter.apply(d)
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)
    # No attackers → no blocker phase.
    assert adapter.combat_phase is None


def test_blocker_decision_out_of_order_raises():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"],
        p1_creatures=["Sapling", "Wild Bear"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and d.attack
    )
    adapter.apply(d)
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)

    head_id = adapter._pending_blockers[0]
    other_id = adapter._pending_blockers[1]
    bad = BlockerDecision(blocker_id=other_id, attacker_id=None)
    import pytest
    with pytest.raises(ValueError):
        adapter.apply(bad)


def test_wrong_decision_type_during_blocker_phase_raises():
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"], p1_creatures=["Sapling"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and d.attack
    )
    adapter.apply(d)
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)

    import pytest
    with pytest.raises(TypeError):
        adapter.apply(PassPriority())


def test_blockers_applied_actually_block():
    """Apply the engine-level DeclareBlockers via the factored path
    — the blocker's ``blocking`` field should be set after
    finalization."""
    adapter = _setup_with_creatures(
        p0_creatures=["Wild Bear"], p1_creatures=["Sapling"],
    )
    _drive_to_step(adapter, Step.DECLARE_ATTACKERS)
    d = next(
        d for d in adapter.legal_decisions()
        if isinstance(d, AttackerDecision) and d.attack
    )
    adapter.apply(d)
    _drive_to_step(adapter, Step.DECLARE_BLOCKERS)
    # Block the bear with the sapling.
    legal = adapter.legal_decisions()
    block_decision = next(
        d for d in legal
        if isinstance(d, BlockerDecision) and d.attacker_id is not None
    )
    adapter.apply(block_decision)

    sapling = next(
        o for o in adapter.engine_state.battlefield
        if o.printing.name == "Sapling"
    )
    assert sapling.blocking is not None
