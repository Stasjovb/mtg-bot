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
