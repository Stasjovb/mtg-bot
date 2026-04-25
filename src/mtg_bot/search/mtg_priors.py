"""MTG-specific decision-ordering priors for use with
``ProgressiveWidening``.

Progressive widening only pulls a few decisions from the prior at any
visit-cap level — early pulls dominate the tree under tight budgets.
Putting the most promising decisions first means MCTS spends its
visits on moves that are usually good, instead of expanding a
PassPriority before it's tried casting anything.

This module is **opinionated and heuristic**, not optimal. Each
heuristic is documented inline. Plug into MCTS via:

    MCTS(
        ...,
        expansion_policy=ProgressiveWidening(prior=mtg_default_prior),
    )

The single ``mtg_default_prior`` function dispatches by inspecting
the legal decisions — combat sub-decisions get sorted differently
from priority actions, etc.
"""

from __future__ import annotations

from typing import Iterable

from mtg_bot.actions import (
    ActivateAbility, ActivateStation, CastSpell, PassPriority, PlayLand,
)
from mtg_bot.game import effective_power, effective_toughness
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)
from mtg_bot.search.protocol import Decision, GameState


# Lower numbers come first.
_PRIORITY_ACTION_RANK = {
    PlayLand: 0,         # Tempo: lands first.
    CastSpell: 1,        # Develop the board.
    ActivateAbility: 2,  # Often less impactful than a fresh card.
    ActivateStation: 3,  # Niche.
    PassPriority: 4,     # Last — explore real moves before passing.
}


def _priority_action_key(action) -> tuple[int, int]:
    """Sort key for engine-level priority actions. Returns
    ``(class_rank, card_id_or_zero)`` so the order is stable across
    clones with the same id assignments."""
    rank = _PRIORITY_ACTION_RANK.get(type(action), 99)
    card_id = getattr(action, "card_id", 0)
    # Tiebreak: secondary fields differ across action types — pull
    # whatever's available to keep ordering deterministic.
    return (rank, card_id)


def attack_aggressive_prior(
    state: GameState, legal: list[Decision],
) -> Iterable[Decision]:
    """Order ``AttackerDecision``s with attack=True before
    attack=False. The aggressive baseline assumes attacking is
    usually good; MCTS explores not-attacking via the second pull.
    """
    return sorted(
        legal,
        key=lambda d: (
            0 if d.attack else 1,
            d.attacker_id,
        ),
    )


def block_biggest_attacker_first_prior(
    state: GameState, legal: list[Decision],
) -> Iterable[Decision]:
    """Order ``BlockerDecision``s by descending effective-power of
    the attacker being blocked. Don't-block ranks last. Rationale:
    the biggest attacker does the most damage; blocking it tends
    to be the most life-preserving move. MCTS will explore other
    options after.
    """
    engine = state.engine_state

    def key(d):
        if d.attacker_id is None:
            return (1, 0, d.blocker_id)
        attacker = next(
            (o for o in engine.battlefield if o.id == d.attacker_id),
            None,
        )
        if attacker is None:
            return (1, 0, d.blocker_id)
        # Negative power so DESCENDING order on ascending sort.
        return (0, -effective_power(engine, attacker), d.blocker_id)

    return sorted(legal, key=key)


def priority_action_prior(
    state: GameState, legal: list[Decision],
) -> Iterable[Decision]:
    """Order engine priority actions by class rank
    (``_PRIORITY_ACTION_RANK``). Within a rank, secondary sort by
    card_id for stability."""
    return sorted(legal, key=_priority_action_key)


def mtg_default_prior(state: GameState) -> Iterable[Decision]:
    """Top-level dispatch: pick the right per-decision-type prior
    based on what's in ``legal_decisions()`` right now.

    All combat-decision lists are homogeneous (the adapter only
    exposes one decision type at a time). Priority-action lists are
    mixed (PlayLand + CastSpell + PassPriority etc.) — those go
    through ``priority_action_prior``.
    """
    legal = list(state.legal_decisions())
    if not legal:
        return iter(())

    sample = legal[0]
    if isinstance(sample, AttackerDecision):
        return attack_aggressive_prior(state, legal)
    if isinstance(sample, BlockerDecision):
        return block_biggest_attacker_first_prior(state, legal)
    return priority_action_prior(state, legal)
