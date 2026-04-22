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
    raise ValueError(f"unknown action: {action!r}")


def _play_land(state: GameState, player_id: int, card_id: int) -> None:
    p = state.player_by_id(player_id)
    card = next(c for c in p.hand if c.id == card_id)
    p.hand.remove(card)
    card.zone = Zone.BATTLEFIELD
    card.controller_id = player_id
    card.tapped = False
    state.battlefield.append(card)
    p.lands_played_this_turn += 1
    state.log.append(f"P{player_id} plays {card.printing.name}")


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

    auto_tap_for_cost(state, player_id, cost)
    card.zone = Zone.STACK
    card.controller_id = player_id

    # If this spell has a targeted spell_effect, select a target now.
    targets: tuple[tuple[str, int], ...] = ()
    spell_effect = card.printing.spell_effect
    if spell_effect is not None and spell_effect.requires_target():
        legal = spell_effect.legal_targets(state, player_id)
        if legal:
            chosen = p.agent.choose_target(state, player_id, legal)
            if chosen is not None:
                targets = (chosen,)

    state.stack.append(
        StackItem(source=card, controller_id=player_id, targets=targets)
    )
    mode = " (warp)" if use_warp else ""
    state.log.append(f"P{player_id} casts {card.printing.name}{mode}")


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
        if not can_block(blockers_on_bf[blocker_id], attackers[attacker_id]):
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

    # Triggered-ability resolution
    if item.ability is not None:
        state.log.append(
            f"{item.source.printing.name}'s triggered ability resolves"
        )
        item.ability.effect.resolve(state, item.controller_id, item.targets)
        return

    # Spell resolution
    card = item.source
    if card.printing.is_permanent and not (
        card.printing.is_instant or card.printing.is_sorcery
    ):
        state.log.append(f"{card.printing.name} resolves onto the battlefield")
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
    """
    obj.zone = Zone.BATTLEFIELD
    obj.controller_id = controller_id
    obj.tapped = False
    obj.summoning_sick = True
    state.battlefield.append(obj)
    _trigger_etb_abilities(state, obj)


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
        if effect.requires_target():
            legal = effect.legal_targets(state, controller_id)
            if not legal:
                state.log.append(
                    f"{creature.printing.name}'s ETB has no legal targets; "
                    f"trigger fizzles"
                )
                continue
            controller = state.player_by_id(controller_id)
            chosen = controller.agent.choose_target(state, controller_id, legal)
            if chosen is None:
                state.log.append(
                    f"{creature.printing.name}'s ETB had no target chosen; "
                    f"trigger fizzles"
                )
                continue
            targets = (chosen,)
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
