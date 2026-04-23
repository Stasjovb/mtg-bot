"""Enumerate legal actions for the player who currently has priority."""

from __future__ import annotations

from mtg_bot.actions import (
    Action,
    ActivateAbility,
    ActivateStation,
    CastSpell,
    PassPriority,
    PlayLand,
    can_pay_cost,
)
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


def _additional_costs_payable(
    state: GameState, player_id: int, card: GameObject
) -> bool:
    """Check that any cast-time additional costs on ``card`` can be paid.
    Currently: additional_cost_sacrifice_creature_or_artifact requires a
    creature or artifact the caster controls.
    """
    if card.printing.additional_cost_sacrifice_creature_or_artifact:
        have_sac = any(
            o for o in state.battlefield
            if o.controller_id == player_id
            and (o.printing.is_creature or o.printing.is_artifact)
        )
        if not have_sac:
            return False
    return True


def legal_actions(state: GameState, player_id: int) -> list[Action]:
    """Return all legal actions for ``player_id`` right now.

    At any priority moment (on or off your turn), instants in hand whose cost
    is payable and whose targets are satisfiable are legal. At sorcery timing
    (your main phase, stack empty, your priority) creatures, sorceries, land
    plays, and warp-exile recasts are also legal. A card in hand with a warp
    cost can be cast either at its normal cost or for its warp alt-cost
    whenever a normal cast would be legal — proposed separately.
    """
    actions: list[Action] = [PassPriority()]

    if not _has_priority(state, player_id):
        return actions

    p = state.player_by_id(player_id)

    from mtg_bot.actions import apply_cost_reductions

    def _effective_cost(card, base_cost):
        return apply_cost_reductions(card.printing, state, player_id, base_cost)

    # Instant-speed-castable: instants AND any permanent spell with flash.
    for card in p.hand:
        instant_speed = (
            card.printing.is_instant or "flash" in card.printing.keywords
        )
        if not instant_speed:
            continue
        if can_pay_cost(
            state, player_id, _effective_cost(card, card.printing.mana_cost)
        ) and _targets_are_satisfiable(state, player_id, card) and _additional_costs_payable(state, player_id, card):
            actions.append(CastSpell(card.id))
        if card.printing.warp_cost is not None and can_pay_cost(
            state, player_id,
            _effective_cost(card, card.printing.warp_cost),
        ) and _targets_are_satisfiable(state, player_id, card) and _additional_costs_payable(state, player_id, card):
            actions.append(CastSpell(card.id, use_warp=True))

    if not _is_sorcery_timing(state, player_id):
        return actions

    # One land play per turn at sorcery speed.
    if p.lands_played_this_turn < 1:
        for card in p.hand:
            if card.printing.is_land:
                actions.append(PlayLand(card.id))

    # Creature / sorcery / other permanent (artifact, spacecraft, ...) casts
    # at sorcery speed. Creatures/permanents with flash were already proposed
    # in the instant-speed block above, so skip them here to avoid duplicate
    # CastSpell actions.
    def _is_sorcery_speed_spell(card) -> bool:
        pr = card.printing
        return (
            pr.is_creature
            or pr.is_sorcery
            or (pr.is_permanent and not pr.is_instant and not pr.is_land)
        )

    for card in p.hand:
        if "flash" in card.printing.keywords:
            continue
        if card.printing.is_instant:
            continue
        if _is_sorcery_speed_spell(card):
            if can_pay_cost(
                state, player_id,
                _effective_cost(card, card.printing.mana_cost),
            ) and _targets_are_satisfiable(state, player_id, card) and _additional_costs_payable(state, player_id, card):
                actions.append(CastSpell(card.id))
            if card.printing.warp_cost is not None and can_pay_cost(
                state, player_id,
                _effective_cost(card, card.printing.warp_cost),
            ) and _targets_are_satisfiable(state, player_id, card) and _additional_costs_payable(state, player_id, card):
                actions.append(CastSpell(card.id, use_warp=True))

    # Warp-exile recasts at sorcery speed (for creatures / sorceries).
    # Instants in warp-exile could be recast at instant speed, but we don't
    # have any such cards yet — extend if/when we do.
    for card in p.exile:
        if not card.warped:
            continue
        if card.printing.is_instant:
            continue  # handled above at instant speed (none yet in the pool)
        if can_pay_cost(
            state, player_id,
            _effective_cost(card, card.printing.mana_cost),
        ) and _targets_are_satisfiable(state, player_id, card) and _additional_costs_payable(state, player_id, card):
            actions.append(CastSpell(card.id))

    # Activated abilities on permanents this player controls.
    for obj in state.battlefield:
        if obj.controller_id != player_id:
            continue
        for idx, ability in enumerate(obj.printing.activated_abilities):
            if ability.sorcery_speed and not _is_sorcery_timing(state, player_id):
                continue
            # Cost payability checks.
            if ability.cost.mana is not None and not can_pay_cost(
                state, player_id, ability.cost.mana
            ):
                continue
            if ability.cost.tap_self:
                if obj.tapped:
                    continue
                # Creatures tapping as part of a cost can't while summoning-sick.
                from mtg_bot.game import is_creature_now
                if is_creature_now(obj) and obj.summoning_sick:
                    continue
            # If the effect requires a target, at least one must be legal.
            if ability.effect.requires_target() and not ability.effect.legal_targets(
                state, player_id
            ):
                continue
            actions.append(
                ActivateAbility(source_id=obj.id, ability_index=idx)
            )

    # Station activations: for each Spacecraft this player controls, each
    # untapped non-sick creature they control (not the Spacecraft itself) is
    # a legal crew choice.
    spacecraft = [
        o for o in state.battlefield
        if o.controller_id == player_id and o.printing.is_spacecraft
    ]
    if spacecraft:
        crew_candidates = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and o.printing.is_creature
            and not o.tapped
            and not o.summoning_sick
        ]
        for ship in spacecraft:
            for crew in crew_candidates:
                if crew.id == ship.id:
                    continue
                actions.append(
                    ActivateStation(spacecraft_id=ship.id, crew_id=crew.id)
                )

    return actions
