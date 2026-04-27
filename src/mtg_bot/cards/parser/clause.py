"""Top-level clause dispatch.

A creature's oracle text is parsed line-by-line. Each line that
isn't a special pre-clause check (Warp, Ward, sorcery-speed rider —
those live in ``printing_keywords`` and ``activated``) goes through
``_parse_clause`` which dispatches to the per-clause-type parsers
in keyword/trigger/activated/static order.

The result, ``_ParsedClause``, is a small dataclass with mutually
exclusive populated fields — the creature builder consumes it by
inspecting which field is set.
"""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.cards.base import (
    ActivatedAbility,
    StaticAbility,
    TriggeredAbility,
)
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.keywords import _parse_keyword_line
from mtg_bot.cards.parser.statics import _parse_static_ability_line
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line


@dataclass(frozen=True)
class _ParsedClause:
    """One oracle-text clause that successfully parsed.

    Fields are mutually exclusive — a clause contributes either one
    or more keyword strings, a triggered ability, an activated
    ability, or a static ability, never more than one. A keyword-only
    line that lists several keywords joined by ``, `` parses to a
    single ``_ParsedClause`` whose ``keywords`` tuple holds every
    keyword on that line.
    """

    keywords: tuple[str, ...] = ()
    trigger: TriggeredAbility | None = None
    activated: ActivatedAbility | None = None
    static: StaticAbility | None = None

    @property
    def keyword(self) -> str | None:
        """Back-compat shim for callers that still want a single
        keyword. Returns ``None`` if no keywords or more than one
        — multi-keyword clauses must be consumed via ``keywords``.
        """
        if len(self.keywords) == 1:
            return self.keywords[0]
        return None


def _parse_clause(line: str) -> _ParsedClause | None:
    """Return a ``_ParsedClause`` for a recognized line, or ``None``
    if the parser doesn't know how to handle it. ``None`` causes the
    enclosing card to be skipped."""
    line = line.strip()
    keywords = _parse_keyword_line(line)
    if keywords is not None:
        return _ParsedClause(keywords=keywords)
    triggered = _parse_triggered_ability_line(line)
    if triggered is not None:
        return _ParsedClause(trigger=triggered)
    activated = _parse_activated_ability_line(line)
    if activated is not None:
        return _ParsedClause(activated=activated)
    static = _parse_static_ability_line(line)
    if static is not None:
        return _ParsedClause(static=static)
    return None
