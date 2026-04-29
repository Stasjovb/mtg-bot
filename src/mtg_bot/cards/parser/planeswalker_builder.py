"""Planeswalker ``CardPrinting`` builder — oracle-text driven.

The engine doesn't yet model loyalty-activated abilities (the printed
``+N``/``-N`` cost type), so this builder strips loyalty-activation
lines and parses the surviving lines through the unified triggered-
ability grammar. Cards whose only printed abilities are loyalty
activations come through with an empty ``triggered_abilities`` tuple;
cards with one or more parseable triggered abilities (Tezzeret, Cruel
Captain's "Whenever an artifact you control enters, put a loyalty
counter on Tezzeret.") carry those abilities verbatim.

Loyalty activation lines are recognized by the leading
``[+−-]?<digit(s)>:`` cost prefix — Scryfall prints the negative-cost
sign as the U+2212 minus character (``−``) and the positive-cost sign
as ``+``; bare zero is just ``0:``. Any line outside the loyalty-
activation prefix or the supported triggered-ability grammar causes
the whole card to fall through (returns ``None``) so the planeswalker
isn't silently shipped with a partially-parsed body.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    CardPrinting,
    TriggeredAbility,
    make_planeswalker,
)
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.cards.parser.type_line import _parse_type_line


# Loyalty-activation cost prefix on a printed planeswalker line.
# Scryfall renders the negative sign as U+2212 (``−``); ``+`` and the
# bare-zero ``0:`` form share the same regex via the optional sign
# group. The cost-then-colon-then-space pattern is anchored at the
# start of the line so a colon embedded mid-effect (e.g. inside a
# triggered-ability body) doesn't accidentally match.
_LOYALTY_ACTIVATION_PREFIX = re.compile(r"^[+\-−]?\d+: ")


def _build_planeswalker_printing(card: dict) -> CardPrinting | None:
    """Parse a Scryfall planeswalker record into a ``CardPrinting`` via
    oracle-text recognition.

    Returns ``None`` if the card isn't a Planeswalker, has more than
    one printed subtype (the engine takes a single-subtype string),
    has no printed loyalty, or contains an unparseable non-loyalty
    line.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Planeswalker" not in card_types:
        return None
    if len(subtypes) != 1:
        return None
    loyalty_str = card.get("loyalty")
    if loyalty_str is None:
        return None
    try:
        loyalty = int(loyalty_str)
    except (TypeError, ValueError):
        return None

    triggers: list[TriggeredAbility] = []
    for raw_line in card.get("oracle_text", "").split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        # Loyalty-activated abilities aren't modeled — drop the line so
        # the printed body stays consistent with the static-side
        # simplification.
        if _LOYALTY_ACTIVATION_PREFIX.match(line):
            continue
        parsed = _parse_triggered_ability_line(line, name=card["name"])
        if parsed is None:
            return None
        if isinstance(parsed, tuple):
            triggers.extend(parsed)
        else:
            triggers.append(parsed)

    return make_planeswalker(
        name=card["name"],
        cost=card.get("mana_cost", ""),
        loyalty=loyalty,
        subtype=subtypes[0],
        legendary="Legendary" in supertypes,
        triggered_abilities=tuple(triggers),
    )
