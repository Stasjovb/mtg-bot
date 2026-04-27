"""Creature ``CardPrinting`` builder.

Walks each line of the oracle text in order. Pre-clause checks
(Warp, Ward, sorcery-speed rider) consume the line directly; everything
else goes through ``_parse_clause`` which dispatches to per-clause-type
parsers. Any unrecognized line skips the whole card (returns ``None``).
"""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.cards.base import (
    ActivatedAbility,
    CardPrinting,
    StaticAbility,
    TriggeredAbility,
    make_creature,
)
from mtg_bot.cards.parser.activated import _is_sorcery_rider_line
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.printing_keywords import (
    _parse_ward_line,
    _parse_warp_line,
)
from mtg_bot.cards.parser.type_line import _parse_type_line


def _build_creature_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for ``card`` (a Scryfall
    record). Returns ``None`` if the card is not a creature, has
    non-integer power/toughness (e.g. ``*``), or contains any
    oracle-text clause the slice doesn't yet support."""
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Creature" not in card_types:
        return None
    try:
        power = int(card["power"])
        toughness = int(card["toughness"])
    except (KeyError, ValueError):
        return None

    keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    activated: list[ActivatedAbility] = []
    statics: list[StaticAbility] = []
    warp: str | None = None
    ward: str | None = None
    text = card.get("oracle_text", "")
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        warp_cost = _parse_warp_line(line)
        if warp_cost is not None:
            # A card should only have one Warp clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            warp = warp_cost
            continue
        ward_cost = _parse_ward_line(line)
        if ward_cost is not None:
            # A card should only have one Ward clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            ward = ward_cost
            continue
        if _is_sorcery_rider_line(line):
            # The rider attaches to the immediately preceding activated
            # ability on the same card. With no preceding ability there's
            # nothing to mark sorcery-speed and the card is skipped — a
            # bare rider line on its own is malformed oracle text.
            if not activated:
                return None
            activated[-1] = replace(activated[-1], sorcery_speed=True)
            continue
        parsed = _parse_clause(line)
        if parsed is None:
            return None
        keywords.update(parsed.keywords)
        if parsed.trigger is not None:
            triggers.append(parsed.trigger)
        if parsed.activated is not None:
            activated.append(parsed.activated)
        if parsed.static is not None:
            statics.append(parsed.static)

    return make_creature(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        keywords=keywords,
        triggered_abilities=tuple(triggers),
        activated_abilities=tuple(activated),
        static_abilities=tuple(statics),
        subtypes=subtypes,
        legendary="Legendary" in supertypes,
        artifact="Artifact" in card_types,
        warp=warp,
        ward=ward,
    )
