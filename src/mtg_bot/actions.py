"""Action types, mana payment, and action application."""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.cards import ManaCost
from mtg_bot.game import GameObject, GameState, StackItem, Zone


@dataclass(frozen=True)
class Action:
    pass


@dataclass(frozen=True)
class PassPriority(Action):
    pass


@dataclass(frozen=True)
class PlayLand(Action):
    card_id: int


@dataclass(frozen=True)
class CastSpell(Action):
    card_id: int
    # If True, cast from hand for the card's warp alt-cost (and trigger an
    # end-of-turn exile). If False (default), cast at the normal cost — from
    # hand OR from the "warped" exile zone if the card is sitting there.
    use_warp: bool = False


@dataclass(frozen=True)
class ActivateAbility(Action):
    """Activate the N-th activated ability on a permanent the player
    controls. Pays the cost and puts the ability on the stack. Ineligibility
    (can't pay, creature summoning-sick for tap-cost abilities, etc.) is
    filtered in ``legal_actions`` and silently no-ops here as defense.
    """

    source_id: int
    ability_index: int


@dataclass(frozen=True)
class ActivateStation(Action):
    """Activate the Station ability of a Spacecraft.

    Cost: tap ``crew_id`` (another untapped creature the player controls).
    Effect: add charge counters to ``spacecraft_id`` equal to the crew's
    power. Sorcery-speed only (enforced by ``legal_actions``).
    """

    spacecraft_id: int
    crew_id: int


@dataclass(frozen=True)
class DeclareAttackers(Action):
    """Declare a set of creatures as attackers during the declare-attackers step.

    Ineligible ids (summoning-sick creatures, tapped creatures, etc.) are
    silently filtered during application.
    """
    attacker_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class DeclareBlockers(Action):
    """Declare block assignments during the declare-blockers step.

    ``assignments`` is a tuple of (blocker_id, attacker_id) pairs (tuples
    instead of a dict so the action itself is hashable). Illegal pairs are
    silently filtered during application.
    """
    assignments: tuple[tuple[int, int], ...] = ()


def _untapped_lands(state: GameState, player_id: int) -> list[GameObject]:
    return [
        o for o in state.battlefield
        if o.controller_id == player_id and o.printing.is_land and not o.tapped
    ]


def can_pay_cost(state: GameState, player_id: int, cost: ManaCost) -> bool:
    """Check whether the player can pay ``cost`` by tapping untapped lands they control."""
    lands = _untapped_lands(state, player_id)
    used: set[int] = set()
    for color, count in cost.colored:
        matching = [l for l in lands if color in l.printing.produces and l.id not in used]
        if len(matching) < count:
            return False
        for l in matching[:count]:
            used.add(l.id)
    remaining = [l for l in lands if l.id not in used]
    return len(remaining) >= cost.generic


def apply_cost_reductions(
    printing: "CardPrinting",
    state: GameState,
    caster_id: int,
    base_cost: ManaCost,
) -> ManaCost:
    """Walk ``printing.cost_reductions`` and return a ManaCost with
    generic mana reduced accordingly. Unknown conditions are treated as
    False (no reduction), which is safe and warns via a log entry.

    Known conditions:
      - ``another_spell_cast_this_turn``: caster's spells_cast_this_turn
        is already ≥ 1 (this spell will be their 2nd or later).
      - ``attacked_with_spacecraft_this_turn``: caster attacked with any
        Spacecraft earlier this turn.
      - ``per_differently_named_land`` (with ``per_land_group=True``):
        amount is multiplied by the number of distinct basic-land names
        the caster controls.
    """
    cost = base_cost
    for rule in printing.cost_reductions:
        reduction = 0
        if rule.condition == "another_spell_cast_this_turn":
            if state.player_by_id(caster_id).spells_cast_this_turn >= 1:
                reduction = rule.amount
        elif rule.condition == "attacked_with_spacecraft_this_turn":
            if state.player_by_id(
                caster_id
            ).attacked_with_spacecraft_this_turn:
                reduction = rule.amount
        elif rule.condition == "void_active":
            from mtg_bot.game import is_void_active

            if is_void_active(state):
                reduction = rule.amount
        elif rule.condition == "per_differently_named_land":
            if rule.per_land_group:
                names: set[str] = set()
                for o in state.battlefield:
                    if (
                        o.controller_id == caster_id
                        and o.printing.is_land
                    ):
                        names.add(o.printing.name)
                reduction = rule.amount * len(names)
        else:
            state.log.append(
                f"unknown cost-reduction condition {rule.condition!r}; "
                f"treating as no reduction"
            )
        if reduction > 0:
            cost = cost.reduced(reduction)
            state.log.append(
                f"cost reduced by {reduction} ({rule.condition})"
            )
    return cost


def auto_tap_for_cost(
    state: GameState, player_id: int, cost: ManaCost
) -> list[GameObject]:
    """Tap untapped lands to pay the cost. Returns lands tapped (and mutates them)."""
    lands = _untapped_lands(state, player_id)
    used: set[int] = set()
    tapped: list[GameObject] = []
    for color, count in cost.colored:
        matching = [l for l in lands if color in l.printing.produces and l.id not in used]
        for l in matching[:count]:
            used.add(l.id)
            tapped.append(l)
    remaining = [l for l in lands if l.id not in used]
    for l in remaining[: cost.generic]:
        tapped.append(l)
    for l in tapped:
        l.tapped = True
    return tapped


def apply_action(state: GameState, player_id: int, action: Action) -> None:
    if isinstance(action, PassPriority):
        return
    if isinstance(action, PlayLand):
        _play_land(state, player_id, action.card_id)
        return
    if isinstance(action, CastSpell):
        _cast_spell(state, player_id, action.card_id, use_warp=action.use_warp)
        return
    if isinstance(action, DeclareAttackers):
        _declare_attackers(state, player_id, action.attacker_ids)
        return
    if isinstance(action, DeclareBlockers):
        _declare_blockers(state, player_id, action.assignments)
        return
    if isinstance(action, ActivateStation):
        _activate_station(state, player_id, action.spacecraft_id, action.crew_id)
        return
    if isinstance(action, ActivateAbility):
        _activate_ability(
            state, player_id, action.source_id, action.ability_index
        )
        return
    raise ValueError(f"unknown action: {action!r}")


def _play_land(state: GameState, player_id: int, card_id: int) -> None:
    from mtg_bot.turn import fire_landfall_triggers

    p = state.player_by_id(player_id)
    card = next(c for c in p.hand if c.id == card_id)
    p.hand.remove(card)
    card.zone = Zone.BATTLEFIELD
    card.controller_id = player_id
    card.tapped = False
    # Shock land: optional life payment on ETB. Agent decides; if they
    # can't/won't pay, the land enters tapped.
    life_cost = card.printing.shock_land_life_cost
    if life_cost > 0 and p.agent is not None:
        pay = p.agent.choose_pay_shock_life(state, player_id, life_cost)
        if pay:
            p.life -= life_cost
            state.log.append(
                f"P{player_id} pays {life_cost} life for "
                f"{card.printing.name} (life: {p.life})"
            )
        else:
            card.tapped = True
            state.log.append(
                f"P{player_id} declines shock life — "
                f"{card.printing.name} enters tapped"
            )
    state.battlefield.append(card)
    p.lands_played_this_turn += 1
    state.log.append(f"P{player_id} plays {card.printing.name}")
    fire_landfall_triggers(state, card)


def _cast_spell(
    state: GameState, player_id: int, card_id: int, use_warp: bool = False
) -> None:
    p = state.player_by_id(player_id)

    # A spell can be cast from the hand (normal or warp cost) or from the
    # "warped" exile zone (normal cost only).
    card = next((c for c in p.hand if c.id == card_id), None)
    if card is not None:
        cost = (
            card.printing.warp_cost
            if use_warp
            else card.printing.mana_cost
        )
        p.hand.remove(card)
        # Mark the spell as warp-cast so it triggers the end-step exile once
        # it resolves onto the battlefield.
        card.cast_via_warp = bool(use_warp)
        if use_warp:
            state.spell_warped_this_turn = True
    else:
        # Cast from exile: only legal for cards previously exiled by warp
        # (warped=True), and only at their normal cost.
        card = next(
            (c for c in p.exile if c.id == card_id and c.warped), None
        )
        if card is None:
            raise ValueError(
                f"card {card_id} not castable by P{player_id}"
            )
        cost = card.printing.mana_cost
        p.exile.remove(card)
        card.warped = False
        # A warp-exile recast pays its normal cost and is a plain cast — it
        # does NOT re-trigger the warp-exile cycle.
        card.cast_via_warp = False

    # Apply cost reductions (e.g., "costs {3} less if you've cast another
    # spell this turn"). Warp costs are reduced too — the rules don't
    # special-case this.
    cost = apply_cost_reductions(card.printing, state, player_id, cost)
    auto_tap_for_cost(state, player_id, cost)
    # Additional cost: sacrifice a creature or artifact. Legal_actions
    # already gated casting on a valid sac target existing; here we
    # just pay by calling sacrifice() on the agent's pick.
    if card.printing.additional_cost_sacrifice_creature_or_artifact:
        sac_options = [
            o for o in state.battlefield
            if o.controller_id == player_id
            and (o.printing.is_creature or o.printing.is_artifact)
        ]
        if sac_options:
            from mtg_bot.turn import sacrifice as _sacrifice

            chosen = sac_options[0]
            if p.agent is not None:
                pick_id = p.agent.choose_sacrifice(
                    state, player_id, [o.id for o in sac_options]
                )
                chosen = next(
                    (o for o in sac_options if o.id == pick_id),
                    sac_options[0],
                )
            state.log.append(
                f"additional cost: P{player_id} sacrifices "
                f"{chosen.printing.name}"
            )
            _sacrifice(state, chosen)
    card.zone = Zone.STACK
    card.controller_id = player_id

    # If this spell has a targeted spell_effect, select target(s) now.
    # Supports multi-target via Effect.target_count_range() → (min, max).
    targets: tuple[tuple[str, int], ...] = ()
    spell_effect = card.printing.spell_effect
    if spell_effect is not None:
        min_t, max_t = spell_effect.target_count_range()
        if max_t > 0:
            legal = spell_effect.legal_targets(state, player_id)
            chosen_list: list[tuple[str, int]] = []
            remaining = list(legal)
            for _ in range(max_t):
                if not remaining:
                    break
                pick = p.agent.choose_target(state, player_id, remaining)
                if pick is None:
                    # Agent declines; stop picking iff min already reached.
                    if len(chosen_list) >= min_t:
                        break
                    # Forced pick to satisfy min_t.
                    pick = remaining[0]
                if pick not in remaining:
                    # Agent picked an out-of-range target; ignore.
                    break
                chosen_list.append(pick)
                remaining.remove(pick)
            targets = tuple(chosen_list)
    # Auras pick their enchanted-creature target at cast time. The target
    # is recorded on the StackItem and consumed at resolution to set
    # attached_to. "Enchant creature" is the only scope we model.
    if card.printing.is_aura:
        legal = [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]
        if legal:
            chosen = p.agent.choose_target(state, player_id, legal)
            if chosen is not None:
                targets = (chosen,)

    countered = _apply_ward_check(state, player_id, targets)
    state.stack.append(
        StackItem(
            source=card, controller_id=player_id, targets=targets,
            countered=countered,
        )
    )
    mode = " (warp)" if use_warp else ""
    state.log.append(f"P{player_id} casts {card.printing.name}{mode}")

    # Track cast-count for "whenever you cast your Nth spell" triggers.
    p.spells_cast_this_turn += 1
    if p.spells_cast_this_turn == 2:
        _fire_second_spell_triggers(state, player_id)


def _fire_second_spell_triggers(state: GameState, caster_id: int) -> None:
    """Fire "whenever you cast your second spell each turn" triggers on
    permanents the caster controls. Fired directly (no stack) for
    consistency with our other trigger events.
    """
    for obj in list(state.battlefield):
        if obj.controller_id != caster_id:
            continue
        for ability in obj.printing.triggered_abilities:
            if ability.trigger != "second_spell_each_turn":
                continue
            state.log.append(
                f"{obj.printing.name}'s second-spell trigger fires"
            )
            state.resolving_source = obj
            try:
                ability.effect.resolve(state, caster_id, ())
            finally:
                state.resolving_source = None


def _apply_ward_check(
    state: GameState, caster_id: int,
    targets: tuple[tuple[str, int], ...],
) -> bool:
    """Apply Ward at cast time. For each creature target controlled by an
    opponent with Ward {cost}, the caster auto-pays the cost by tapping
    additional lands. If they can't pay, the spell is countered and this
    returns True.

    Simplified: no pay-or-counter decision — caster always pays if they
    can. No player-choice surface; Ward is essentially an additional mana
    cost on top of the spell's printed cost.
    """
    for kind, tid in targets:
        if kind != "creature":
            continue
        obj = next((o for o in state.battlefield if o.id == tid), None)
        if obj is None:
            continue
        if obj.controller_id == caster_id:
            continue  # ward doesn't fire on your own permanents
        ward = obj.printing.ward_cost
        if ward is None:
            continue
        if can_pay_cost(state, caster_id, ward):
            auto_tap_for_cost(state, caster_id, ward)
            state.log.append(
                f"P{caster_id} pays Ward {obj.printing.ward_cost_str} "
                f"for {obj.printing.name}"
            )
        else:
            state.log.append(
                f"Spell countered by {obj.printing.name}'s Ward "
                f"{obj.printing.ward_cost_str} (unpaid)"
            )
            return True
    return False


def _activate_ability(
    state: GameState, player_id: int, source_id: int, ability_index: int
) -> None:
    """Pay an activated ability's cost and put it on the stack."""
    from mtg_bot.turn import move_off_battlefield

    source = next((o for o in state.battlefield if o.id == source_id), None)
    if source is None or source.controller_id != player_id:
        return
    abilities = source.printing.activated_abilities
    if ability_index < 0 or ability_index >= len(abilities):
        return
    ability = abilities[ability_index]

    # Pay mana first (auto-tap lands).
    if ability.cost.mana is not None:
        auto_tap_for_cost(state, player_id, ability.cost.mana)

    # Tap-self (if cost requires it).
    if ability.cost.tap_self:
        from mtg_bot.turn import tap_permanent
        tap_permanent(state, source)

    # Target selection for the effect (if it targets).
    targets: tuple[tuple[str, int], ...] = ()
    if ability.effect.requires_target():
        legal = ability.effect.legal_targets(state, player_id)
        if legal:
            p = state.player_by_id(player_id)
            chosen = p.agent.choose_target(state, player_id, legal)
            if chosen is not None:
                targets = (chosen,)

    # Sacrifice-self is paid LAST so the source is still on the battlefield
    # for target selection — the Lander case where the ability's effect
    # doesn't reference the source but the controller needs to still own it.
    if ability.cost.sacrifice_self:
        from mtg_bot.turn import sacrifice as _sacrifice

        state.log.append(
            f"P{player_id} sacrifices {source.printing.name}"
        )
        _sacrifice(state, source)

    # Put the ability on the stack using the existing StackItem shape.
    state.stack.append(
        StackItem(
            source=source,
            controller_id=player_id,
            ability=ability,
            targets=targets,
        )
    )
    state.log.append(
        f"P{player_id} activates {source.printing.name}'s ability"
    )


def _activate_station(
    state: GameState, player_id: int, spacecraft_id: int, crew_id: int
) -> None:
    """Validate and apply a Station activation. Silently no-ops on invalid
    inputs (crew isn't eligible, spacecraft isn't under our control, etc.)."""
    from mtg_bot.game import effective_power

    spacecraft = next(
        (o for o in state.battlefield if o.id == spacecraft_id), None
    )
    crew = next((o for o in state.battlefield if o.id == crew_id), None)
    if spacecraft is None or crew is None:
        return
    if not spacecraft.printing.is_spacecraft:
        return
    if spacecraft.controller_id != player_id:
        return
    if crew.controller_id != player_id:
        return
    if crew.id == spacecraft.id:
        return  # "another creature"
    if not crew.printing.is_creature:
        return  # spacecraft can't crew another spacecraft in Stage 3
    if crew.tapped:
        return
    if crew.summoning_sick:
        # Activated abilities with tap in their cost can't be used on
        # summoning-sick creatures, even for Station.
        return

    from mtg_bot.turn import tap_permanent

    added = effective_power(state, crew)
    tap_permanent(state, crew)
    spacecraft.charge_counters += added
    state.log.append(
        f"{crew.printing.name} stations {spacecraft.printing.name} "
        f"(+{added} counters, now {spacecraft.charge_counters})"
    )


def _declare_attackers(
    state: GameState, player_id: int, attacker_ids: frozenset[int]
) -> None:
    from mtg_bot.combat import declare_attackers, eligible_attackers

    eligible_ids = {o.id for o in eligible_attackers(state, player_id)}
    valid = [oid for oid in attacker_ids if oid in eligible_ids]
    declare_attackers(state, valid)


def _declare_blockers(
    state: GameState,
    player_id: int,
    assignments: tuple[tuple[int, int], ...],
) -> None:
    from mtg_bot.combat import can_block, declare_blockers, eligible_blockers

    eligible_ids = {o.id for o in eligible_blockers(state, player_id)}
    attackers = {o.id: o for o in state.battlefield if o.attacking}
    blockers_on_bf = {o.id: o for o in state.battlefield}

    validated: dict[int, int] = {}
    for blocker_id, attacker_id in assignments:
        if blocker_id not in eligible_ids:
            continue
        if attacker_id not in attackers:
            continue
        if blocker_id not in blockers_on_bf:
            continue
        if not can_block(state, blockers_on_bf[blocker_id], attackers[attacker_id]):
            continue
        validated[blocker_id] = attacker_id

    # Menace: if an attacker has menace and was assigned exactly one blocker,
    # the block is illegal — drop it so the attacker goes through unblocked.
    blockers_by_attacker: dict[int, list[int]] = {}
    for bid, aid in validated.items():
        blockers_by_attacker.setdefault(aid, []).append(bid)
    for aid, blocker_ids in blockers_by_attacker.items():
        if (
            "menace" in attackers[aid].printing.keywords
            and len(blocker_ids) < 2
        ):
            for bid in blocker_ids:
                validated.pop(bid, None)

    declare_blockers(state, validated)


def resolve_top_of_stack(state: GameState) -> None:
    item = state.stack.pop()

    # Countered spells: no effects, no ETBs; the card goes to its owner's
    # graveyard (permanents and non-permanents alike) per rule 701.5a.
    if item.countered:
        state.log.append(f"{item.source.printing.name} is countered")
        card = item.source
        card.zone = Zone.GRAVEYARD
        state.player_by_id(card.owner_id).graveyard.append(card)
        return

    # Triggered-ability resolution
    if item.ability is not None:
        state.log.append(
            f"{item.source.printing.name}'s triggered ability resolves"
        )
        state.resolving_source = item.source
        try:
            item.ability.effect.resolve(state, item.controller_id, item.targets)
        finally:
            state.resolving_source = None
        return

    # Spell resolution
    card = item.source
    if card.printing.is_permanent and not (
        card.printing.is_instant or card.printing.is_sorcery
    ):
        # Aura: check the cast-time target is still a legal creature. If
        # not, the Aura fizzles to its owner's graveyard without entering.
        if card.printing.is_aura:
            target_obj = None
            if item.targets:
                kind, target_id = item.targets[0]
                if kind == "creature":
                    target_obj = next(
                        (o for o in state.battlefield
                         if o.id == target_id and o.printing.is_creature),
                        None,
                    )
            if target_obj is None:
                state.log.append(
                    f"{card.printing.name} fizzles (no legal enchant target)"
                )
                card.zone = Zone.GRAVEYARD
                state.player_by_id(card.owner_id).graveyard.append(card)
                return
            card.attached_to = target_obj.id
            state.log.append(
                f"{card.printing.name} enters attached to "
                f"{target_obj.printing.name}"
            )
        else:
            state.log.append(
                f"{card.printing.name} resolves onto the battlefield"
            )
        put_into_battlefield(state, card, item.controller_id)
        return
    if card.printing.is_instant or card.printing.is_sorcery:
        state.log.append(f"{card.printing.name} resolves")
        if card.printing.spell_effect is not None:
            card.printing.spell_effect.resolve(
                state, item.controller_id, item.targets
            )
        # Non-permanent spells go to their owner's graveyard.
        card.zone = Zone.GRAVEYARD
        state.player_by_id(card.owner_id).graveyard.append(card)
        return
    raise ValueError(f"don't know how to resolve {card.printing.name}")


def put_into_battlefield(
    state: GameState, obj: "GameObject", controller_id: int
) -> None:
    """Move ``obj`` onto the battlefield and fire any ETB triggers.

    Shared by spell resolution and token-creation effects so both flows go
    through the same state transition and trigger pipeline.

    After the object's own ETB triggers, fires "whenever another artifact
    you control enters" triggers on other permanents the controller
    controls if the entering object is an artifact.
    """
    obj.zone = Zone.BATTLEFIELD
    obj.controller_id = controller_id
    obj.tapped = False
    obj.summoning_sick = True
    state.battlefield.append(obj)
    _trigger_etb_abilities(state, obj)
    if obj.printing.is_artifact:
        _fire_artifact_enters_triggers(state, obj)
    if obj.printing.is_creature or obj.printing.is_artifact:
        _fire_creature_or_artifact_enters_triggers(state, obj)


def _fire_creature_or_artifact_enters_triggers(
    state: GameState, new_obj: "GameObject"
) -> None:
    """Fire 'whenever another creature or artifact you control enters'
    triggers on other permanents the controller controls. Excludes the
    entering object itself.
    """
    from mtg_bot.turn import should_fire_trigger

    controller = new_obj.controller_id
    for obj in list(state.battlefield):
        if obj.id == new_obj.id:
            continue
        if obj.controller_id != controller:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "creature_or_artifact_enters_you_control":
                continue
            if not should_fire_trigger(state, obj.id, i, ability):
                continue
            state.log.append(
                f"{obj.printing.name}'s creature-or-artifact-enters "
                f"trigger fires"
            )
            state.resolving_source = obj
            try:
                ability.effect.resolve(state, controller, ())
            finally:
                state.resolving_source = None


def _fire_artifact_enters_triggers(
    state: GameState, new_artifact: "GameObject"
) -> None:
    """Fire "whenever another artifact you control enters" triggers on
    permanents the new artifact's controller controls. Fires directly
    (no stack) — matches our other trigger events.
    """
    from mtg_bot.turn import should_fire_trigger

    controller = new_artifact.controller_id
    for obj in list(state.battlefield):
        if obj.id == new_artifact.id:
            continue
        if obj.controller_id != controller:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "artifact_enters_you_control":
                continue
            if not should_fire_trigger(state, obj.id, i, ability):
                continue
            state.log.append(
                f"{obj.printing.name}'s artifact-enters trigger fires"
            )
            state.resolving_source = obj
            try:
                ability.effect.resolve(state, controller, ())
            finally:
                state.resolving_source = None


def _trigger_etb_abilities(state: GameState, creature: "GameObject") -> None:
    """Push any ETB triggers from ``creature`` onto the stack, in printing order.

    If an ability requires a target, legal targets are gathered and the
    controller's agent picks one as the ability goes on the stack. If there
    are no legal targets, the ability fizzles (doesn't go on the stack at
    all), per the simplified Stage-3 targeting model.
    """
    from mtg_bot.game import StackItem

    for ability in creature.printing.triggered_abilities:
        if ability.trigger != "etb":
            continue
        controller_id = creature.controller_id
        effect = ability.effect
        targets: tuple[tuple[str, int], ...] = ()
        min_t, max_t = effect.target_count_range()
        if max_t > 0:
            legal = effect.legal_targets(state, controller_id)
            if not legal and min_t > 0:
                state.log.append(
                    f"{creature.printing.name}'s ETB has no legal targets; "
                    f"trigger fizzles"
                )
                continue
            controller = state.player_by_id(controller_id)
            chosen_list: list[tuple[str, int]] = []
            remaining = list(legal)
            for _ in range(max_t):
                if not remaining:
                    break
                pick = controller.agent.choose_target(
                    state, controller_id, remaining
                )
                if pick is None:
                    if len(chosen_list) >= min_t:
                        break
                    pick = remaining[0]
                if pick not in remaining:
                    break
                chosen_list.append(pick)
                remaining.remove(pick)
            if len(chosen_list) < min_t:
                state.log.append(
                    f"{creature.printing.name}'s ETB had no target chosen; "
                    f"trigger fizzles"
                )
                continue
            targets = tuple(chosen_list)
        state.stack.append(
            StackItem(
                source=creature,
                controller_id=controller_id,
                ability=ability,
                targets=targets,
            )
        )
        state.log.append(
            f"{creature.printing.name}'s ETB trigger goes on the stack"
        )
