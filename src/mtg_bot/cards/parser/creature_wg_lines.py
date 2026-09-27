"""Creature oracle-line recognizers for the cube W/G creature bucket.

``creature_builder._build_creature_printing`` consults
:func:`parse_wg_creature_line` only for a line the pre-existing grammar
(printing keywords + ``clause._parse_clause``) declined, so nothing here
can change how an already-claimed card parses.

Each recognizer returns a :class:`WGLine` describing what the line adds
to the printing: ``CardPrinting`` field values, keywords and triggered /
activated / static abilities. Shapes (reminder text already stripped):

* ``Evoke—Exile a <filter> card from your hand.`` / ``Evoke {cost}`` —
  :mod:`mtg_bot.evoke` (the evoke sacrifice trigger rides along).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class WGLine:
    """What one recognized oracle line contributes to a creature
    printing."""

    fields: dict = field(default_factory=dict)
    keywords: tuple[str, ...] = ()
    triggers: tuple = ()
    activated: tuple = ()
    statics: tuple = ()


# ---------------------------------------------------------------------
# Evoke
# ---------------------------------------------------------------------

_EVOKE_LINE_RE = re.compile(
    r"^Evoke(?: (?P<mana>(?:\{[^}]+\})+)|—Exile (?P<desc>an? .+? card) "
    r"from your hand\.)$"
)


def _parse_evoke_line(line: str, card: dict) -> WGLine | None:
    m = _EVOKE_LINE_RE.match(line)
    if m is None:
        return None
    from mtg_bot.evoke import EVOKE_SACRIFICE_TRIGGER

    if m.group("mana") is not None:
        from mtg_bot.cards.base import parse_mana_cost

        fields = {
            "evoke_cost": parse_mana_cost(m.group("mana")),
            "evoke_cost_str": m.group("mana"),
        }
    else:
        from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor

        f = parse_card_descriptor(m.group("desc"))
        if f is None:
            return None
        fields = {"evoke_exile_from_hand": f}
    return WGLine(fields=fields, triggers=(EVOKE_SACRIFICE_TRIGGER,))


_RECOGNIZERS = (
    _parse_evoke_line,
)


# ---------------------------------------------------------------------
# Linked exile abilities (CR 607.2a)
# ---------------------------------------------------------------------


def _is_exiling_effect(effect) -> bool:
    from mtg_bot.effects.generic.exile import Exile, ExileTargetCardFromGraveyard

    return isinstance(effect, (Exile, ExileTargetCardFromGraveyard))


def _consumes_exile_link(ability) -> bool:
    effect = getattr(ability, "effect", None)
    condition = getattr(ability, "condition", None)
    return bool(
        getattr(effect, "consumes_exile_link", False)
        or getattr(condition, "consumes_exile_link", False)
    )


def link_exile_abilities(
    triggers: list, activated: list, statics: list,
) -> None:
    """When a card prints an ability that refers to "the exiled card" /
    "cards exiled with this creature", its exiling ability is the other
    half of a linked pair: wrap every exiling triggered / activated
    ability in ``LinkExiledCardsToSource`` (in place). A card without a
    link consumer is left untouched."""
    from dataclasses import replace

    from mtg_bot.effects.generic.cube_creatures_wg import (
        LinkExiledCardsToSource,
    )

    if not any(
        _consumes_exile_link(a) for a in (*triggers, *activated, *statics)
    ):
        return
    for abilities in (triggers, activated):
        for i, ability in enumerate(abilities):
            if _is_exiling_effect(ability.effect):
                abilities[i] = replace(
                    ability, effect=LinkExiledCardsToSource(ability.effect),
                )


def parse_wg_creature_line(line: str, card: dict) -> WGLine | None:
    """The :class:`WGLine` for ``line`` (one reminder-stripped oracle line
    of ``card``), or ``None`` when no W/G bucket recognizer claims it."""
    for recognizer in _RECOGNIZERS:
        out = recognizer(line, card)
        if out is not None:
            return out
    return None
