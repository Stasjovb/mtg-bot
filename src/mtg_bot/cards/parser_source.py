"""Oracle-text parser card source.

Reads Scryfall JSON, decomposes each creature's oracle text into
recognized clauses, and produces a ``CardPrinting`` matching what
the hand-coded registry produces for the same card. Cards with any
unrecognized clause are silently skipped — only fully-parsed cards
appear in ``claimed_names`` and gate against the static registry
in ``tests/test_parser_parity.py``.

Slice 1 supports two clause forms:

- ``Flying`` (a keyword line) → contributes ``keywords={"flying"}``.
- ``When this creature enters, it deals N damage to any target.`` →
  contributes a single ETB-triggered ``DealDamageAnyTarget`` ability.

Cards whose oracle text uses only those clauses get claimed. Today
that is exactly one EoE card: Nebula Dragon.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mtg_bot.cards.base import (
    CardPrinting,
    DealDamageAnyTarget,
    TriggeredAbility,
    make_creature,
)


_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "edge_of_eternities.json"
)


@dataclass(frozen=True)
class _ParsedClause:
    """One oracle-text clause that successfully parsed.

    Fields are mutually exclusive — a clause contributes either a
    keyword string or a triggered ability, never both.
    """

    keyword: str | None = None
    trigger: TriggeredAbility | None = None


_KEYWORD_LINES: dict[str, str] = {"Flying": "flying"}

_ETB_DAMAGE_TO_ANY_TARGET = re.compile(
    r"^When this creature enters, it deals (\d+) damage to any target\.$"
)

_SUPERTYPES = frozenset({"Basic", "Legendary", "Snow", "World", "Ongoing"})

_TYPE_LINE_SEPARATOR = "—"  # em-dash, used by Scryfall


def _parse_type_line(
    text: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Split a Scryfall type line into ``(supertypes, card_types,
    subtypes)``. Empty tuple for any section not present.

    Examples: ``"Creature — Dragon"`` →
    ``((), ("Creature",), ("Dragon",))``;
    ``"Legendary Creature — Human Soldier"`` →
    ``(("Legendary",), ("Creature",), ("Human", "Soldier"))``;
    ``"Sorcery"`` → ``((), ("Sorcery",), ())``.
    """
    if _TYPE_LINE_SEPARATOR in text:
        left, right = text.split(_TYPE_LINE_SEPARATOR, 1)
    else:
        left, right = text, ""
    left_words = left.split()
    supertypes = tuple(w for w in left_words if w in _SUPERTYPES)
    card_types = tuple(w for w in left_words if w not in _SUPERTYPES)
    subtypes = tuple(right.split())
    return supertypes, card_types, subtypes


def _parse_clause(line: str) -> _ParsedClause | None:
    """Return a ``_ParsedClause`` for a recognized line, or ``None``
    if the parser doesn't know how to handle it. ``None`` causes the
    enclosing card to be skipped."""
    line = line.strip()
    if line in _KEYWORD_LINES:
        return _ParsedClause(keyword=_KEYWORD_LINES[line])
    m = _ETB_DAMAGE_TO_ANY_TARGET.match(line)
    if m is not None:
        return _ParsedClause(
            trigger=TriggeredAbility(
                trigger="etb",
                effect=DealDamageAnyTarget(amount=int(m.group(1))),
            )
        )
    return None


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
    text = card.get("oracle_text", "")
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_clause(line)
        if parsed is None:
            return None
        if parsed.keyword is not None:
            keywords.add(parsed.keyword)
        if parsed.trigger is not None:
            triggers.append(parsed.trigger)

    return make_creature(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        keywords=keywords,
        triggered_abilities=tuple(triggers),
        subtypes=subtypes,
        legendary="Legendary" in supertypes,
    )


def _load_scryfall_data() -> list[dict]:
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


class OracleParserCardSource:
    def __init__(self) -> None:
        printings: dict[str, CardPrinting] = {}
        for card in _load_scryfall_data():
            built = _build_creature_printing(card)
            if built is not None:
                printings[card["name"]] = built
        self._printings = printings

    @property
    def claimed_names(self) -> tuple[str, ...]:
        return tuple(self._printings)

    def get_printings(self) -> dict[str, CardPrinting]:
        return dict(self._printings)

    def build_mono_color_deck(
        self, color: str, seed: int | None = None
    ) -> list[str]:
        raise NotImplementedError(
            "parser source does not yet implement deck building; "
            "implement once it claims a deckable pool"
        )
