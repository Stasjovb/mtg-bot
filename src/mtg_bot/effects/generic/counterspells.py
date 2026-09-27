"""Filter-driven counterspells: "counter target <spell np> [unless its
controller pays {N}]", with the "If that spell is countered this way,
<put it somewhere else> instead" destination riders and the Pyroblast
"counter target spell if it's <color>" resolution condition.

The engine counters a spell by flagging its ``StackItem`` (``countered``)
and moving the card when the item is popped
(``actions.resolve_top_of_stack``). :class:`CounterSpell` additionally
records ``StackItem.countered_destination`` so Memory Lapse (top of
library), Remand (hand), and Force of Negation / No More Lies (exile)
send the card to the printed zone instead of the graveyard.

Targeting mirrors the legacy :class:`CounterTargetSpell`: targets are
``("stack", index)`` pairs over spell items (abilities excluded) that
aren't already countered and can be countered (CR 101.2), filtered by
``spell_filter`` (an ``ObjectPredicate`` tested against the spell's
card). Legality is re-checked on resolution (CR 608.2b).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.effects.object_predicates import ObjectPredicate
    from mtg_bot.game import GameState, StackItem


COUNTER_DESTINATIONS = ("graveyard", "exile", "library_top", "hand")


def _is_uncounterable(state: "GameState", item: "StackItem") -> bool:
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell

    return CounterTargetSpell._is_uncounterable(state, item)


def spell_mana_value(item: "StackItem") -> int:
    """CR 202.3e: a spell's mana value on the stack counts X as the
    chosen value."""
    cost = item.source.printing.mana_cost
    return cost.total + cost.x_pips * item.x_value


@dataclass(frozen=True)
class CounterSpell(Effect):
    """Counter target spell matching ``spell_filter`` (``None`` = any
    spell).

    ``unless_pays`` ("{3}") gives the spell's controller the option to
    pay that cost on resolution; if they can and do (``choose_yes_no``),
    the spell isn't countered. ``only_if`` is a resolution-time
    condition on the targeted spell ("if it's blue") — the target is
    legal regardless, but the counter only happens when it holds.
    ``destination`` is where the countered card goes.
    """

    spell_filter: "ObjectPredicate | None" = None
    unless_pays: str = ""
    only_if: "ObjectPredicate | None" = None
    destination: str = "graveyard"
    label: str = "spell"

    def __post_init__(self) -> None:
        if self.destination not in COUNTER_DESTINATIONS:
            raise ValueError(f"unknown counter destination: {self.destination!r}")

    def requires_target(self) -> bool:
        return True

    def _matches(self, state: "GameState", item: "StackItem") -> bool:
        if self.spell_filter is None:
            return True
        return self.spell_filter.test(item.source, state)

    def legal_targets(
        self, state: "GameState", controller_id: int,
    ) -> list[Target]:
        out: list[Target] = []
        for i, item in enumerate(state.stack):
            if item.ability is not None or item.countered:
                continue
            if _is_uncounterable(state, item):
                continue
            if not self._matches(state, item):
                continue
            out.append(("stack", i))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import auto_tap_for_cost, can_pay_cost
        from mtg_bot.cards import parse_mana_cost

        if not targets:
            return
        kind, idx = targets[0]
        if kind != "stack" or not (0 <= idx < len(state.stack)):
            return
        item = state.stack[idx]
        name = item.source.printing.name
        if item.ability is not None or item.countered:
            return
        if not self._matches(state, item):
            state.log.append(
                f"counterspell fizzles: {name} is no longer a legal target"
            )
            return
        if _is_uncounterable(state, item):
            state.log.append(f"counterspell fizzles: {name} can't be countered")
            return
        if self.only_if is not None and not self.only_if.test(item.source, state):
            state.log.append(f"{name} doesn't meet the condition — not countered")
            return
        if self.unless_pays:
            payer_id = item.controller_id
            payer = state.player_by_id(payer_id)
            cost = parse_mana_cost(self.unless_pays)
            if can_pay_cost(state, payer_id, cost) and (
                payer.agent is None or payer.agent.choose_yes_no(
                    state, payer_id,
                    f"pay {self.unless_pays} so {name} isn't countered",
                )
            ):
                auto_tap_for_cost(state, payer_id, cost)
                state.log.append(
                    f"P{payer_id} pays {self.unless_pays}; {name} "
                    f"isn't countered"
                )
                return
        item.countered = True
        item.countered_destination = self.destination
        state.log.append(f"counterspell: {name} is countered")

    def describe(self) -> str:
        text = f"counter target {self.label}"
        if self.unless_pays:
            text += f" unless its controller pays {self.unless_pays}"
        if self.destination != "graveyard":
            text += f"; it goes to {self.destination.replace('_', ' ')} instead"
        return text


__all__ = [
    "COUNTER_DESTINATIONS",
    "CounterSpell",
    "spell_mana_value",
]
