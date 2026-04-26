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
    if card.printing.additional_cost_choose_your_creature:
        # "Choose a creature you control or a warped creature card you
        # own in exile." Either source satisfies the cost.
        have_battlefield = any(
            o for o in state.battlefield
            if o.controller_id == player_id and o.printing.is_creature
        )
        if not have_battlefield:
            p = state.player_by_id(player_id)
            have_exiled = any(
                o for o in p.exile
                if o.owner_id == player_id
                and o.warped
                and o.printing.is_creature
            )
            if not have_exiled:
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
    from mtg_bot.cards import ManaCost

    def _effective_cost(card, base_cost):
        return apply_cost_reductions(card.printing, state, player_id, base_cost)

    def _cost_plus_kicker(card, base_cost):
        """Combined base + kicker cost (colored pips merged)."""
        kc = card.printing.kicker_cost
        if kc is None:
            return base_cost
        merged: dict[str, int] = dict(base_cost.colored)
        for color, n in kc.colored:
            merged[color] = merged.get(color, 0) + n
        return ManaCost(
            generic=base_cost.generic + kc.generic,
            colored=tuple(sorted(merged.items())),
            x_pips=base_cost.x_pips,
        )

    # Weftwalking-style "first spell each player casts during each of
    # their turns may be cast without paying its mana cost." Only
    # offered to the active player when they haven't yet cast a spell
    # this turn AND any battlefield permanent grants it.
    free_first_cast_active = (
        state.players[state.active_player_idx].id == player_id
        and p.spells_cast_this_turn == 0
        and any(
            o.printing.grants_first_spell_each_turn_free
            for o in state.battlefield
        )
    )

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
            # Kicked variant: can_pay the combined cost.
            if card.printing.kicker_cost is not None and can_pay_cost(
                state, player_id,
                _cost_plus_kicker(
                    card, _effective_cost(card, card.printing.mana_cost)
                ),
            ):
                actions.append(CastSpell(card.id, kicked=True))
        if (
            card.printing.warp_cost is not None
            and can_pay_cost(
                state, player_id,
                _effective_cost(card, card.printing.warp_cost),
            )
            and _targets_are_satisfiable(state, player_id, card)
            and _additional_costs_payable(state, player_id, card)
            and p.life > card.printing.warp_additional_life_cost
        ):
            actions.append(CastSpell(card.id, use_warp=True))
        # Weftwalking free-cast variant. Skips the mana-cost payable
        # check (it's free) but still gates on targets / additional
        # non-mana costs.
        if (
            free_first_cast_active
            and _targets_are_satisfiable(state, player_id, card)
            and _additional_costs_payable(state, player_id, card)
        ):
            actions.append(CastSpell(card.id, cast_for_free=True))

    if not _is_sorcery_timing(state, player_id):
        return actions

    # Land plays per turn at sorcery speed. Base = 1, increased by
    # permanents granting "you may play an additional land" (Icetill
    # Explorer).
    max_lands = 1 + sum(
        o.printing.grants_additional_land_per_turn
        for o in state.battlefield
        if o.controller_id == player_id
    )
    if p.lands_played_this_turn < max_lands:
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
                if card.printing.kicker_cost is not None and can_pay_cost(
                    state, player_id,
                    _cost_plus_kicker(
                        card, _effective_cost(
                            card, card.printing.mana_cost
                        ),
                    ),
                ):
                    actions.append(CastSpell(card.id, kicked=True))
            if (
                card.printing.warp_cost is not None
                and can_pay_cost(
                    state, player_id,
                    _effective_cost(card, card.printing.warp_cost),
                )
                and _targets_are_satisfiable(state, player_id, card)
                and _additional_costs_payable(state, player_id, card)
                and p.life > card.printing.warp_additional_life_cost
            ):
                actions.append(CastSpell(card.id, use_warp=True))
            # Weftwalking free-cast variant for this sorcery-speed
            # spell. Skips the mana-cost payable check (it's free)
            # but still gates on targets / additional non-mana costs.
            if (
                free_first_cast_active
                and _targets_are_satisfiable(state, player_id, card)
                and _additional_costs_payable(state, player_id, card)
            ):
                actions.append(CastSpell(card.id, cast_for_free=True))

    # Warp-cast from graveyard. Timeline Culler grants this; see
    # warp_castable_from_graveyard. Currently only sorcery-speed since
    # all such cards in the pool are creatures.
    for card in p.graveyard:
        if not card.printing.warp_castable_from_graveyard:
            continue
        if card.printing.warp_cost is None:
            continue
        if card.printing.is_instant:
            continue  # extend if a future card needs instant-speed grave warp
        if (
            can_pay_cost(
                state, player_id,
                _effective_cost(card, card.printing.warp_cost),
            )
            and _targets_are_satisfiable(state, player_id, card)
            and _additional_costs_payable(state, player_id, card)
            and p.life > card.printing.warp_additional_life_cost
        ):
            actions.append(CastSpell(card.id, use_warp=True))
        # Weftwalking free-cast variant for sorcery-speed spells.
        if (
            free_first_cast_active
            and _targets_are_satisfiable(state, player_id, card)
            and _additional_costs_payable(state, player_id, card)
        ):
            actions.append(CastSpell(card.id, cast_for_free=True))

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

    # Impulse-cast: cards in exile marked playable_from_exile_this_turn
    # (Territorial Bruntar landfall, Memorial Vault activated) — or
    # marked play_from_exile_requires_kavu (Possibility Technician),
    # which persists until the card leaves exile but is gated on the
    # controller currently controlling a Kavu. Both pay normal mana
    # cost and respect sorcery-speed rules. Lands use PlayLand;
    # non-land permanents / sorceries use CastSpell.
    controls_kavu = any(
        o.controller_id == player_id and "Kavu" in o.printing.subtypes
        for o in state.battlefield
    )
    for card in p.exile:
        impulse = card.playable_from_exile_this_turn
        kavu_gate = card.play_from_exile_requires_kavu and controls_kavu
        if not (impulse or kavu_gate):
            continue
        if card.warped:
            continue  # already handled above
        if card.printing.is_land:
            if p.lands_played_this_turn < (
                1 + sum(
                    o.printing.grants_additional_land_per_turn
                    for o in state.battlefield
                    if o.controller_id == player_id
                )
            ):
                actions.append(PlayLand(card.id))
            continue
        if card.printing.is_instant:
            # Instant speed — always castable if cost payable.
            if can_pay_cost(
                state, player_id,
                _effective_cost(card, card.printing.mana_cost),
            ) and _targets_are_satisfiable(state, player_id, card):
                actions.append(CastSpell(card.id))
            continue
        # Sorcery-speed cards: main phase, empty stack only.
        if not _is_sorcery_timing(state, player_id):
            continue
        if can_pay_cost(
            state, player_id,
            _effective_cost(card, card.printing.mana_cost),
        ) and _targets_are_satisfiable(state, player_id, card) and _additional_costs_payable(state, player_id, card):
            actions.append(CastSpell(card.id))

    # Cast-from-library (top card only): Mm'menon, the Right Hand.
    # "You may cast artifact spells from the top of your library."
    # Offered when the controller has any permanent with the grant
    # flag AND the top card is an artifact at sorcery speed.
    has_cast_artifact_top = any(
        o.printing.grants_cast_artifact_from_top_of_library
        for o in state.battlefield
        if o.controller_id == player_id
    )
    if has_cast_artifact_top and p.library:
        top = p.library[0]
        if top.printing.is_artifact and not top.printing.is_creature:
            # Sorcery timing check for non-instant tops.
            if _is_sorcery_timing(state, player_id) and can_pay_cost(
                state, player_id,
                _effective_cost(top, top.printing.mana_cost),
                spell_kind="artifact_spell",
            ) and _targets_are_satisfiable(state, player_id, top):
                actions.append(CastSpell(top.id))
        elif top.printing.is_artifact and top.printing.is_creature:
            if _is_sorcery_timing(state, player_id) and can_pay_cost(
                state, player_id,
                _effective_cost(top, top.printing.mana_cost),
                spell_kind="artifact_spell",
            ) and _targets_are_satisfiable(state, player_id, top):
                actions.append(CastSpell(top.id))

    # Activated abilities on permanents this player controls.
    for obj in state.battlefield:
        if obj.controller_id != player_id:
            continue
        from mtg_bot.game import effective_activated_abilities
        for idx, ability in enumerate(
            effective_activated_abilities(state, obj)
        ):
            if ability.sorcery_speed and not _is_sorcery_timing(state, player_id):
                continue
            # Cost payability checks. Apply ability-level mana
            # reductions (Dominion Bracelet: {X} less where X is
            # equipped creature's power) before checking.
            if ability.cost.mana is not None:
                from mtg_bot.actions import _effective_ability_mana_cost
                effective_mana = _effective_ability_mana_cost(state, obj, ability)
                # Match the spell_kind tagging used by _activate_ability
                # so artifact-restricted coins are seen as payable for
                # artifact-source ability activations (and similarly for
                # colorless-Eldrazi Temple's gate on Eldrazi activations).
                ability_spell_kind = "spell"
                if (
                    "Eldrazi" in obj.printing.subtypes
                    and not obj.printing.mana_cost.colored
                ):
                    ability_spell_kind = "colorless_eldrazi_ability"
                elif obj.printing.is_artifact:
                    ability_spell_kind = "artifact_activation"
                if not can_pay_cost(
                    state, player_id, effective_mana,
                    spell_kind=ability_spell_kind,
                ):
                    continue
            if ability.cost.tap_self:
                if obj.tapped:
                    continue
                # Creatures tapping as part of a cost can't while summoning-sick.
                from mtg_bot.game import is_creature_now
                if is_creature_now(obj) and obj.summoning_sick:
                    continue
            if ability.cost.sacrifice_another_creature_or_artifact:
                has_another = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and o2.id != obj.id
                    and (o2.printing.is_creature or o2.printing.is_artifact)
                )
                if not has_another:
                    continue
            if ability.cost.sacrifice_another_artifact_or_land:
                has_another = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and o2.id != obj.id
                    and (o2.printing.is_artifact or o2.printing.is_land)
                )
                if not has_another:
                    continue
            if ability.cost.sacrifice_another_artifact:
                has_another = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and o2.id != obj.id
                    and o2.printing.is_artifact
                )
                if not has_another:
                    continue
            if ability.cost.remove_plus_one_counter_from_your_creature:
                has_counter_creature = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and o2.printing.is_creature
                    and o2.plus_one_counters > 0
                )
                if not has_counter_creature:
                    continue
            if ability.cost.sacrifice_food:
                from mtg_bot.game import effective_subtypes
                has_food = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and "Food" in effective_subtypes(state, o2)
                )
                if not has_food:
                    continue
            if ability.cost.pay_life:
                if p.life <= ability.cost.pay_life:
                    # MTG lets you pay to 0 life (it kills you) but
                    # pragmatically our bot avoids that line — gate
                    # strictly to require surviving the payment.
                    continue
            if ability.cost.sacrifice_a_land:
                has_land = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and o2.printing.is_land
                    and o2.id != obj.id
                )
                if not has_land:
                    continue
            if ability.cost.sacrifice_a_desert:
                has_desert = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and "Desert" in o2.printing.subtypes
                )
                if not has_desert:
                    continue
            if ability.cost.requires_own_creature_power_at_least:
                from mtg_bot.game import effective_power
                threshold = ability.cost.requires_own_creature_power_at_least
                has_big = any(
                    o2 for o2 in state.battlefield
                    if o2.controller_id == player_id
                    and o2.printing.is_creature
                    and effective_power(state, o2) >= threshold
                )
                if not has_big:
                    continue
            if ability.cost.exile_granting_equipment:
                # The granting equipment must still be attached to
                # the source. Legal when there's any equipment with
                # a matching grant-flag attached to obj.
                has_granter = any(
                    eq for eq in state.battlefield
                    if eq.attached_to == obj.id
                    and eq.printing.grants_control_opponent_ability_when_equipped
                )
                if not has_granter:
                    continue
            # If the effect requires a target, at least one must be legal.
            # Set resolving_source so effects with self-exclusion filters
            # (e.g. "another target creature") compute the correct legal
            # pool during legality-check. Cleared immediately afterward.
            if ability.effect.requires_target():
                state.resolving_source = obj
                try:
                    has_legal = bool(
                        ability.effect.legal_targets(state, player_id)
                    )
                finally:
                    state.resolving_source = None
                if not has_legal:
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

    # Deafening Silence gate: post-filter CastSpell actions so
    # noncreature casts beyond the per-turn limit of 1 are removed
    # when any permanent with the restriction is on the battlefield.
    # Kept as a post-filter because CastSpell is proposed from many
    # sites (hand, warp-exile, impulse-exile, cast-from-library) and
    # touching every site would risk drift.
    if any(
        o.printing.restricts_noncreature_spells_to_one_per_turn
        for o in state.battlefield
    ):
        p = state.player_by_id(player_id)
        if p.noncreature_spells_cast_this_turn >= 1:
            filtered: list[Action] = []
            for action in actions:
                if isinstance(action, CastSpell):
                    card = _find_card_by_id(state, player_id, action.card_id)
                    if card is not None and not card.printing.is_creature:
                        continue
                filtered.append(action)
            actions = filtered

    return actions


def _find_card_by_id(state: GameState, player_id: int, card_id: int):
    """Look up a card by id across zones where CastSpell can source
    from: hand, exile (warp / impulse), and library (cast-from-top).
    Returns None if not found — defensive; CastSpell proposals should
    always reference a card the caster can see."""
    p = state.player_by_id(player_id)
    for zone in (p.hand, p.exile):
        for c in zone:
            if c.id == card_id:
                return c
    if p.library and p.library[0].id == card_id:
        return p.library[0]
    return None
