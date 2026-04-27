"""Static-ability grammar.

A static-ability line of the form ``As long as <condition>, this
creature gets +N/+N[ and has <keyword>].`` becomes a self-scoped
``StaticAbility`` with the condition's gate kwarg, the P/T modifier,
and an optional granted keyword. Today only one condition is wired
up: ``you control an artifact``. Other "As long as" conditions
(entered-this-turn, spells-cast counters, etc.) are out of scope and
intentionally don't match — those cards fall through and get skipped.
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
# kwargs passed to ``StaticAbility``. Today only one entry — the
# artifacts-matter rider on Cloudsculpt Technician and Gravblade Heavy.
_STATIC_CONDITION_KWARGS: dict[str, dict[str, object]] = {
    "you control an artifact": {"requires_artifact_you_control": True},
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
