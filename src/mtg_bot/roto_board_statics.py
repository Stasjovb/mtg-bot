"""Board-rule statics of the Vintage Roto P5 package (board-state prison
& layers): the rule objects a printing carries in
``CardPrinting.board_rules`` and the engine reads that consult them.

A board rule is a static ability that changes how the game is played
rather than a characteristic of an object: who may attack or block,
what untaps during the untap step, ... Every read goes through
:func:`rules_in_play`, which skips a source whose abilities are gone:

* a layer-6 ``"lose_all_abilities"`` registry entry on the source
  (Lignify-style Auras, Oko's Elk);
* a creature source while a "creatures lose all abilities" permanent
  is on the battlefield (``CardPrinting.wipes_all_creature_abilities``);
* a land source whose basic land type is set by Blood Moon-style
  effects (CR 305.7: it loses the abilities from its rules text).

Consumers (one hook each): ``combat.eligible_attackers`` /
``combat.eligible_blockers``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------------------
# Source suppression
# ---------------------------------------------------------------------------


def abilities_suppressed(state: "GameState", source: "GameObject") -> bool:
    """Whether ``source`` currently has none of its printed abilities
    (see the module docstring for the three ways)."""
    from mtg_bot.game import (
        _has_basic_land_type_set_effect,
        _source_layer6_wiped,
        is_creature_now,
    )

    if state.continuous_effects and _source_layer6_wiped(state, source):
        return True
    if is_creature_now(source):
        for o in state.battlefield:
            if o.printing.wipes_all_creature_abilities:
                return True
    if source.printing.is_land and _has_basic_land_type_set_effect(state, source):
        return True
    return False


def rules_in_play(state: "GameState", kind: type) -> Iterator[tuple]:
    """``(source, rule)`` for every active board rule of type ``kind``
    on the battlefield."""
    for source in state.battlefield:
        rules = source.printing.board_rules
        if not rules:
            continue
        matching = [r for r in rules if isinstance(r, kind)]
        if not matching or abilities_suppressed(state, source):
            continue
        for rule in matching:
            yield source, rule


def any_rules(state: "GameState") -> bool:
    for o in state.battlefield:
        if o.printing.board_rules:
            return True
    return False


# ---------------------------------------------------------------------------
# Combat restrictions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WithoutKeyword:
    """"without <keyword>" (Moat: "Creatures without flying")."""

    keyword: str

    def holds(self, state, source, creature) -> bool:
        from mtg_bot.game import effective_keywords

        return self.keyword not in effective_keywords(state, creature)

    def describe(self) -> str:
        return f"without {self.keyword}"


@dataclass(frozen=True)
class PowerGreaterThanControllersHandSize:
    """"with power greater than the number of cards in your hand"
    (Ensnaring Bridge; "your" is the source's controller)."""

    def holds(self, state, source, creature) -> bool:
        from mtg_bot.game import effective_power

        hand = len(state.player_by_id(source.controller_id).hand)
        return effective_power(state, creature) > hand

    def describe(self) -> str:
        return "with power greater than the number of cards in your hand"


@dataclass(frozen=True)
class CantAttack:
    """"Creatures [<condition>] can't attack." (``self_only=False``,
    every creature on the battlefield) / "This creature can't attack."
    (``self_only=True``)."""

    condition: object = None
    self_only: bool = False

    def applies(self, state, source, creature) -> bool:
        if self.self_only and creature.id != source.id:
            return False
        return self.condition is None or self.condition.holds(
            state, source, creature,
        )

    def describe(self) -> str:
        who = "This creature" if self.self_only else "Creatures"
        cond = f" {self.condition.describe()}" if self.condition else ""
        return f"{who}{cond} can't attack."


@dataclass(frozen=True)
class CantBlock:
    """"This creature can't block." (``self_only=True``) / "Creatures
    [<condition>] can't block." """

    condition: object = None
    self_only: bool = False

    def applies(self, state, source, creature) -> bool:
        if self.self_only and creature.id != source.id:
            return False
        return self.condition is None or self.condition.holds(
            state, source, creature,
        )

    def describe(self) -> str:
        who = "This creature" if self.self_only else "Creatures"
        cond = f" {self.condition.describe()}" if self.condition else ""
        return f"{who}{cond} can't block."


def _forbidden(state, creatures: list, kind: type) -> list:
    if not creatures or not any_rules(state):
        return creatures
    active = list(rules_in_play(state, kind))
    if not active:
        return creatures
    return [
        c for c in creatures
        if not any(rule.applies(state, src, c) for src, rule in active)
    ]


def filter_attackers(state: "GameState", creatures: list) -> list:
    """Drop the creatures a "can't attack" board rule forbids."""
    return _forbidden(state, creatures, CantAttack)


def filter_blockers(state: "GameState", creatures: list) -> list:
    """Drop the creatures a "can't block" board rule forbids."""
    return _forbidden(state, creatures, CantBlock)


__all__ = [
    "CantAttack",
    "CantBlock",
    "PowerGreaterThanControllersHandSize",
    "WithoutKeyword",
    "abilities_suppressed",
    "any_rules",
    "filter_attackers",
    "filter_blockers",
    "rules_in_play",
]
