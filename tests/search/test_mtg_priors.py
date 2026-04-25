"""Tests for MTG-specific priors used by ``ProgressiveWidening``."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility, ActivateStation, CastSpell, PassPriority, PlayLand,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import (
    AttackerDecision, BlockerDecision, MtgGameStateAdapter,
)
from mtg_bot.search.mtg_priors import (
    attack_aggressive_prior, block_biggest_attacker_first_prior,
    mtg_default_prior, priority_action_prior,
)
from mtg_bot.simulate import setup_game


def _adapter(seed: int = 42, expose_combat: bool = True):
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state, expose_combat_decisions=expose_combat)


def _adapter_with_creatures(p0=None, p1=None, seed=42):
    p0 = p0 or []
    p1 = p1 or []
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    for name in p0:
        obj = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        obj.summoning_sick = False
        state.battlefield.append(obj)
    for name in p1:
        obj = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=1, zone=Zone.BATTLEFIELD,
        )
        obj.summoning_sick = False
        state.battlefield.append(obj)
    return MtgGameStateAdapter(state, expose_combat_decisions=True)


# =====================================================================
# priority_action_prior
# =====================================================================

def test_priority_action_prior_orders_by_class_rank():
    """PlayLand → CastSpell → ActivateAbility → ActivateStation →
    PassPriority."""
    actions = [
        PassPriority(),
        ActivateAbility(source_id=10, ability_index=0),
        CastSpell(card_id=5),
        PlayLand(card_id=2),
    ]
    ordered = list(priority_action_prior(state=None, legal=actions))
    types = [type(a) for a in ordered]
    assert types == [PlayLand, CastSpell, ActivateAbility, PassPriority]


def test_priority_action_prior_secondary_by_card_id():
    """Within PlayLand: ascending card_id (deterministic)."""
    actions = [PlayLand(card_id=10), PlayLand(card_id=2), PlayLand(card_id=5)]
    ordered = list(priority_action_prior(state=None, legal=actions))
    assert [a.card_id for a in ordered] == [2, 5, 10]


def test_priority_action_prior_does_not_drop_decisions():
    """Sorting must not lose or duplicate any decision."""
    actions = [
        PassPriority(),
        PlayLand(card_id=1),
        CastSpell(card_id=2),
        ActivateAbility(source_id=3, ability_index=0),
    ]
    ordered = list(priority_action_prior(state=None, legal=actions))
    assert sorted(actions, key=str) == sorted(ordered, key=str)


# =====================================================================
# attack_aggressive_prior
# =====================================================================

def test_attack_aggressive_prior_attack_true_first():
    decisions = [
        AttackerDecision(attacker_id=5, attack=False),
        AttackerDecision(attacker_id=5, attack=True),
    ]
    ordered = list(attack_aggressive_prior(state=None, legal=decisions))
    assert ordered[0].attack is True
    assert ordered[1].attack is False


def test_attack_aggressive_prior_secondary_by_attacker_id():
    decisions = [
        AttackerDecision(attacker_id=10, attack=True),
        AttackerDecision(attacker_id=2, attack=True),
        AttackerDecision(attacker_id=10, attack=False),
        AttackerDecision(attacker_id=2, attack=False),
    ]
    ordered = list(attack_aggressive_prior(state=None, legal=decisions))
    # Attack=True ones first (sorted by attacker_id), then attack=False.
    assert [d.attacker_id for d in ordered[:2]] == [2, 10]
    assert all(d.attack for d in ordered[:2])
    assert [d.attacker_id for d in ordered[2:]] == [2, 10]
    assert all(not d.attack for d in ordered[2:])


# =====================================================================
# block_biggest_attacker_first_prior
# =====================================================================

def test_block_prior_biggest_attacker_first():
    """With two attackers — one big (Forest Giant 3/3), one small
    (Wild Bear 2/2) — blocking the giant should sort first."""
    from mtg_bot.turn import Step

    adapter = _adapter_with_creatures(
        p0=["Forest Giant", "Wild Bear"],  # active player attacks
        p1=["Sapling"],                    # eligible blocker
    )
    # Drive into attacker phase, attack with both, then into blocker phase.
    while adapter.engine_state.step != Step.DECLARE_ATTACKERS:
        adapter.apply(PassPriority())
    while adapter.combat_phase == "attackers":
        d = next(
            x for x in adapter.legal_decisions()
            if isinstance(x, AttackerDecision) and x.attack
        )
        adapter.apply(d)
    while adapter.engine_state.step != Step.DECLARE_BLOCKERS:
        adapter.apply(PassPriority())
    assert adapter.combat_phase == "blockers"

    legal = adapter.legal_decisions()
    ordered = list(
        block_biggest_attacker_first_prior(state=adapter, legal=legal)
    )
    # First should block an attacker (not the don't-block option).
    assert ordered[0].attacker_id is not None
    # And it should be the bigger attacker.
    giant = next(
        o for o in adapter.engine_state.battlefield
        if o.printing.name == "Forest Giant"
    )
    assert ordered[0].attacker_id == giant.id
    # Don't-block option is last.
    assert ordered[-1].attacker_id is None


def test_block_prior_dont_block_last():
    """When only one attacker exists, the prior still puts
    don't-block after the block-the-only-attacker option."""
    from mtg_bot.turn import Step

    adapter = _adapter_with_creatures(
        p0=["Wild Bear"], p1=["Sapling"],
    )
    while adapter.engine_state.step != Step.DECLARE_ATTACKERS:
        adapter.apply(PassPriority())
    d = next(
        x for x in adapter.legal_decisions()
        if isinstance(x, AttackerDecision) and x.attack
    )
    adapter.apply(d)
    while adapter.engine_state.step != Step.DECLARE_BLOCKERS:
        adapter.apply(PassPriority())

    legal = adapter.legal_decisions()
    ordered = list(
        block_biggest_attacker_first_prior(state=adapter, legal=legal)
    )
    assert ordered[0].attacker_id is not None
    assert ordered[-1].attacker_id is None


# =====================================================================
# mtg_default_prior dispatcher
# =====================================================================

def test_mtg_default_prior_priority_actions():
    """Non-combat priority moments dispatch to priority_action_prior."""
    adapter = _adapter()  # fresh game, at UPKEEP — only PassPriority legal
    ordered = list(mtg_default_prior(adapter))
    # Just one option — but it should still come back, not crash.
    assert len(ordered) == 1
    assert isinstance(ordered[0], PassPriority)


def test_mtg_default_prior_attacker_decisions():
    """Attacker phase dispatches to attack_aggressive_prior."""
    from mtg_bot.turn import Step

    adapter = _adapter_with_creatures(p0=["Wild Bear"])
    while adapter.engine_state.step != Step.DECLARE_ATTACKERS:
        adapter.apply(PassPriority())
    assert adapter.combat_phase == "attackers"

    ordered = list(mtg_default_prior(adapter))
    assert all(isinstance(d, AttackerDecision) for d in ordered)
    assert ordered[0].attack is True
    assert ordered[-1].attack is False


def test_mtg_default_prior_blocker_decisions():
    from mtg_bot.turn import Step

    adapter = _adapter_with_creatures(
        p0=["Wild Bear"], p1=["Sapling"],
    )
    while adapter.engine_state.step != Step.DECLARE_ATTACKERS:
        adapter.apply(PassPriority())
    d = next(
        x for x in adapter.legal_decisions()
        if isinstance(x, AttackerDecision) and x.attack
    )
    adapter.apply(d)
    while adapter.engine_state.step != Step.DECLARE_BLOCKERS:
        adapter.apply(PassPriority())

    ordered = list(mtg_default_prior(adapter))
    assert all(isinstance(d, BlockerDecision) for d in ordered)


def test_mtg_default_prior_empty_legal_returns_empty():
    """A terminal state has no legal decisions; prior must not
    crash and must return an empty iterable."""
    adapter = _adapter()
    adapter.engine_state.winner_id = 0
    ordered = list(mtg_default_prior(adapter))
    assert ordered == []


# =====================================================================
# Integration: prior plugged into ProgressiveWidening + MCTS
# =====================================================================

def test_mtg_prior_plugs_into_progressive_widening():
    """End-to-end smoke: progressive widening using the MTG prior
    runs MCTS without crashing on a real adapter."""
    import random
    from mtg_bot.search import (
        Budget, MCTS, ProgressiveWidening, RandomRolloutEvaluator,
    )

    adapter = _adapter()
    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=10),
        rng=random.Random(1),
        expansion_policy=ProgressiveWidening(prior=mtg_default_prior),
    )
    pick = mcts.choose(adapter, adapter.active_player())
    assert pick in adapter.legal_decisions()
