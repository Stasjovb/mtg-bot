"""Effect-phrase grammar for pool-wide keyword actions and
designations: investigate (CR 701.36), explore (CR 701.44), the
monarch (CR 724) and the initiative (CR 725).

``_parse_keyword_action_effect`` takes a *normalized* effect phrase
(no trailing period, lowercased first letter — see
``effects._parse_effect``) and returns an engine ``Effect`` or
``None``.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect

_INVESTIGATE = re.compile(
    r"^investigate(?: (?P<n>twice|\d+ times|one|two|three|four|five)(?: times)?)?$"
)
_COUNT_WORDS = {
    "twice": 2, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}


def _investigate_count(raw: str | None) -> int:
    if raw is None:
        return 1
    if raw in _COUNT_WORDS:
        return _COUNT_WORDS[raw]
    return int(raw.split()[0])


def _parse_keyword_action_effect(phrase: str) -> Effect | None:
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.keyword_actions import Explore
    from mtg_bot.effects.generic.tokens import CreateToken

    m = _INVESTIGATE.match(phrase)
    if m is not None:
        return CreateToken(
            token_printing=TOKEN_PRINTINGS["Clue"],
            count=_investigate_count(m.group("n")),
        )
    if phrase == "this creature explores":
        return Explore()
    if phrase == "target creature you control explores":
        return Explore(target=True)
    return None
