"""Enumerate legal actions for the player who currently has priority."""

from __future__ import annotations

from mtg_bot.actions import Action, CastSpell, PassPriority, PlayLand, can_pay_cost
from mtg_bot.game import GameObject, GameState
from mtg_bot.turn import MAIN_STEPS


def _has_priority(state: GameState, player_id: int) -> bool:
    return state.players[state.priority_player_idx].id == player_id


def _is_sorcery_timing(state: GameState, player_id: int) -> bool:
    """Sorcery timing: your turn, main phase, empty stack, you have priority."""
    return (
        state.players[state.active_player_idx].id == player_id
        and state.step in MAIN_STEPS
        and not state.stack
        and _has_priority(state, player_id)
    )


def _targets_are_satisfiable(
    state: GameState, player_id: int, card: GameObject
) -> bool:
    """For spells with targeted spell_effects, check at least one legal target
    exists. Non-targeting spells and creatures without spell_effect trivially
    satisfy this."""
    effect = card.printing.spell_effect
    if effect is None or not effect.requires_target():
        return True
    return bool(effect.legal_targets(state, player_id))


def legal_actions(state: GameState, player_id: int) -> list[Action]:
    """Return all legal actions for ``player_id`` right now.

    At any priority moment (on or off your turn), instants in hand whose cost
    is payable and whose targets are satisfiable are legal. At sorcery timing
    (your main phase, stack empty, your priority) creatures, sorceries, and
    one land play per turn are also legal.
    """
    actions: list[Action] = [PassPriority()]

    if not _has_priority(state, player_id):
        return actions

    p = state.player_by_id(player_id)

    # Instants: legal any time you have priority.
    for card in p.hand:
        if (
            card.printing.is_instant
            and can_pay_cost(state, player_id, card.printing.mana_cost)
            and _targets_are_satisfiable(state, player_id, card)
        ):
            actions.append(CastSpell(card.id))

    if not _is_sorcery_timing(state, player_id):
        return actions

    # One land play per turn at sorcery speed.
    if p.lands_played_this_turn < 1:
        for card in p.hand:
            if card.printing.is_land:
                actions.append(PlayLand(card.id))

    # Creature and sorcery casts at sorcery speed.
    for card in p.hand:
        if card.printing.is_creature or card.printing.is_sorcery:
            if can_pay_cost(
                state, player_id, card.printing.mana_cost
            ) and _targets_are_satisfiable(state, player_id, card):
                actions.append(CastSpell(card.id))

    return actions
