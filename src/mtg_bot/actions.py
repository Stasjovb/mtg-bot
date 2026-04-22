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
class CastCreature(Action):
    card_id: int


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
    if isinstance(action, CastCreature):
        _cast_creature(state, player_id, action.card_id)
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


def _cast_creature(state: GameState, player_id: int, card_id: int) -> None:
    p = state.player_by_id(player_id)
    card = next(c for c in p.hand if c.id == card_id)
    p.hand.remove(card)
    auto_tap_for_cost(state, player_id, card.printing.mana_cost)
    card.zone = Zone.STACK
    card.controller_id = player_id
    state.stack.append(StackItem(source=card, controller_id=player_id))
    state.log.append(f"P{player_id} casts {card.printing.name}")


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
    card = item.source
    if card.printing.is_creature:
        card.zone = Zone.BATTLEFIELD
        card.controller_id = item.controller_id
        card.tapped = False
        card.summoning_sick = True
        state.battlefield.append(card)
        state.log.append(f"{card.printing.name} resolves onto the battlefield")
        return
    raise ValueError(f"don't know how to resolve {card.printing.name}")
