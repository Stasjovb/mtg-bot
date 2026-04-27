"""Triggered-ability grammar.

A triggered-ability line of the form ``When/Whenever <condition>,
<effect>.`` decomposes into a condition phrase and an effect phrase.
Each is handled by its own parser — the condition by
``_parse_trigger_phrase`` (a literal-phrase lookup against
``_TRIGGER_PHRASES``), the effect by ``_parse_effect_phrase`` from
``effects``. Adding a new condition or effect grows its respective
grammar without touching the line-level pattern.

Some triggered-ability lines are prefixed by a keyword-ability label
followed by an em-dash (e.g. ``Landfall — Whenever a land you
control enters, …``). The prefix is reminder text — the substance is
the ``Whenever …`` clause that follows. ``_strip_keyword_prefix``
recognizes the narrow set of keyword prefixes we currently support
and strips them so the body parses through the normal grammar.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import TriggeredAbility
from mtg_bot.cards.parser.effects import _parse_effect_phrase


_TRIGGERED_ABILITY_LINE = re.compile(
    r"^(?:When|Whenever) (.+?), (.+)\.$"
)


# Trigger-condition phrases → engine-level trigger key.
_TRIGGER_PHRASES: dict[str, str] = {
    "this creature enters": "etb",
    "this creature dies": "dies",
    "this creature attacks": "attacks",
    # Landfall: the inner ``Whenever a land you control enters`` body
    # is the ability's trigger condition. The engine uses ``landfall``
    # as the canonical trigger key (see ``eoe_creatures.py``), so the
    # phrase maps directly to that key. The keyword-prefix label is
    # stripped by ``_strip_keyword_prefix`` before this lookup runs.
    "a land you control enters": "landfall",
}


# Keyword-prefix labels we recognize at the start of a triggered-ability
# line. The prefix is reminder text wrapping the substantive
# ``Whenever …`` body. Only Landfall is supported in this slice — other
# keyword-prefixed triggered abilities (Saga, Magecraft, etc.) fall
# through and the enclosing card is skipped, as expected.
_KEYWORD_PREFIXES: frozenset[str] = frozenset({"Landfall"})


def _strip_keyword_prefix(line: str) -> str:
    """Strip a recognized ``<Keyword> — `` prefix from ``line``.

    Returns the unprefixed line if a recognized keyword label precedes
    an em-dash (U+2014) with surrounding spaces; otherwise returns
    ``line`` unchanged. The em-dash is the same character used as the
    type-line separator in Scryfall data.
    """
    for keyword in _KEYWORD_PREFIXES:
        prefix = f"{keyword} — "
        if line.startswith(prefix):
            return line[len(prefix):]
    return line


def _parse_trigger_phrase(phrase: str) -> str | None:
    return _TRIGGER_PHRASES.get(phrase.strip())


def _parse_triggered_ability_line(line: str) -> TriggeredAbility | None:
    line = _strip_keyword_prefix(line)
    m = _TRIGGERED_ABILITY_LINE.match(line)
    if m is None:
        return None
    trigger = _parse_trigger_phrase(m.group(1))
    if trigger is None:
        return None
    effect = _parse_effect_phrase(m.group(2))
    if effect is None:
        return None
    return TriggeredAbility(trigger=trigger, effect=effect)
