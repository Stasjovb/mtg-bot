"""Enumerate legal actions for the player who currently has priority."""

from __future__ import annotations

from mtg_bot.actions import Action, CastSpell, PassPriority, PlayLand, can_pay_cost
from mtg_bot.game import GameState
from mtg_bot.turn import MAIN_STEPS


def legal_actions(state: GameState, player_id: int) -> list[Action]:
    """Return all legal actions for ``player_id`` right now.

    Stage 1: sorcery-speed land plays and creature casts; otherwise only pass.
    """
    actions: list[Action] = [PassPriority()]

    sorcery_timing = (
        state.players[state.active_player_idx].id == player_id
        and state.step in MAIN_STEPS
        and not state.stack
        and state.players[state.priority_player_idx].id == player_id
    )
    if not sorcery_timing:
        return actions

    p = state.player_by_id(player_id)

    if p.lands_played_this_turn < 1:
        for card in p.hand:
            if card.printing.is_land:
                actions.append(PlayLand(card.id))

    for card in p.hand:
        if card.printing.is_creature and can_pay_cost(
            state, player_id, card.printing.mana_cost
        ):
            actions.append(CastSpell(card.id))

    return actions
