"""Triggered-ability grammar.

A triggered-ability line of the form ``When/Whenever <condition>,
<effect>.`` decomposes into a condition phrase and an effect phrase.
Each is handled by its own parser — the condition by
``_parse_trigger_phrase`` (a literal-phrase lookup against
``_TRIGGER_PHRASES``), the effect by ``_parse_effect_phrase`` from
``effects``. Adding a new condition or effect grows its respective
grammar without touching the line-level pattern.
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
}


def _parse_trigger_phrase(phrase: str) -> str | None:
    return _TRIGGER_PHRASES.get(phrase.strip())


def _parse_triggered_ability_line(line: str) -> TriggeredAbility | None:
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
