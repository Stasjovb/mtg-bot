"""Static-ability grammar.

A static-ability line of the form ``As long as <condition>, this
creature gets +N/+N[ and has <keyword>].`` becomes a self-scoped
``StaticAbility`` with the condition's gate kwarg, the P/T modifier,
and an optional granted keyword. Recognized conditions today:

* ``you control an artifact`` →
  ``requires_artifact_you_control=True`` (Cloudsculpt Technician,
  Gravblade Heavy in EoE).
* ``you've cast two or more spells this turn`` →
  ``requires_spells_cast_this_turn=2``. Forward-looking grammar; the
  one EoE printing that uses this engine gate (Mm'menon, Uthros
  Exile) has its own surface form with the rider trailing the P/T
  modifier rather than leading it, so no EoE card is unlocked yet —
  but the phrasebook entry is here for cards whose oracle text uses
  the leading-``As long as`` shape.

Other "As long as" conditions (entered-this-turn, void, you-control-a-
creature, ``it's your turn``, etc.) either have no matching engine
gate or are pinned as out-of-scope by an existing parser-source test;
they intentionally don't match and the card falls through.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import StaticAbility, StaticScope
from mtg_bot.cards.parser.keywords import _KEYWORD_LINES


_STATIC_ABILITY_LINE = re.compile(
    r"^As long as (?P<condition>.+?), this creature gets "
    r"\+(?P<power>\d+)/\+(?P<toughness>\d+)"
    r"(?: and has (?P<keyword>[A-Za-z ]+))?\.$"
)

# Conditions recognized as gates on the static ability. The mapping is
# from the surface phrase (matched verbatim, no normalization) to the
# kwargs passed to ``StaticAbility``. Each phrase corresponds 1:1 to a
# gate field on ``StaticAbility``; if no field exists for a given
# condition, we deliberately leave it out so the ability falls through
# and the card gets skipped rather than being silently mis-modeled.
_STATIC_CONDITION_KWARGS: dict[str, dict[str, object]] = {
    "you control an artifact": {"requires_artifact_you_control": True},
    "you've cast two or more spells this turn": {
        "requires_spells_cast_this_turn": 2
    },
}


def _parse_static_ability_line(line: str) -> StaticAbility | None:
    """Return a ``StaticAbility`` for a single ``As long as <condition>,
    this creature gets +N/+N[ and has <keyword>].`` line, or ``None`` if
    the line shape doesn't match, the condition isn't recognized, or the
    granted keyword isn't a known evergreen.

    The static ability is always self-scoped (``StaticScope.SELF``); the
    "this creature gets" subject in the surface form is what makes that
    explicit.
    """
    m = _STATIC_ABILITY_LINE.match(line.strip())
    if m is None:
        return None
    condition = m.group("condition").strip()
    cond_kwargs = _STATIC_CONDITION_KWARGS.get(condition)
    if cond_kwargs is None:
        return None
    granted: frozenset[str] = frozenset()
    keyword = m.group("keyword")
    if keyword is not None:
        engine_keyword = _KEYWORD_LINES.get(keyword.strip().capitalize())
        if engine_keyword is None:
            return None
        granted = frozenset({engine_keyword})
    return StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=int(m.group("power")),
        toughness_bonus=int(m.group("toughness")),
        granted_keywords=granted,
        **cond_kwargs,
    )
