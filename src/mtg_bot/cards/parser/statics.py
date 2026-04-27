"""Static-ability grammar.

Two surface forms of the same semantics are recognized:

* **Leading** ``As long as <condition>, this creature gets +N/+N[ and has
  <keyword>].`` — the original shape. Cloudsculpt Technician and
  Gravblade Heavy in EoE.
* **Trailing** ``This creature gets +N/+N[ and has <keyword>] as long as
  <condition>.`` — the rider trails the P/T modifier. Brightspear
  Zealot in EoE prints in this form.

Both shapes share the same condition phrasebook and produce identical
``StaticAbility`` outputs; the parser tries the leading regex first
and falls back to the trailing regex.

Recognized conditions today:

* ``you control an artifact`` →
  ``requires_artifact_you_control=True`` (Cloudsculpt Technician,
  Gravblade Heavy).
* ``you've cast two or more spells this turn`` →
  ``requires_spells_cast_this_turn=2`` (Brightspear Zealot, via the
  trailing shape).
* ``you've cast three or more spells this turn`` →
  ``requires_spells_cast_this_turn=3``. Batch-11 forward-looking
  variant of the existing ``two or more`` phrase — same engine gate
  field with a higher threshold. No EoE printing today uses this
  threshold but the engine accepts any ``int >= 0`` and the surface
  phrasing is the natural one-word substitution from the ``two``
  variant; adding it keeps the parser ready for printings that
  raise the bar (and makes the threshold-vs-phrase mapping explicit
  in the phrasebook rather than implicit in regex generality).
* ``it's your turn`` → ``active_turn_only=True``. Forward-looking
  grammar coverage; no EoE card prints in the leading/trailing static
  shape with this condition today (Memorial Team Leader uses the
  separate ``During your turn`` rider on an anthem scope, which a
  different builder handles), but the engine field exists and the
  surface phrase is unambiguous.

Other "As long as" conditions (entered-this-turn, void, you-control-a-
creature, etc.) have no matching engine gate; they intentionally don't
match and the card falls through.
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

# The trailing surface form: same semantics, rider after the P/T
# modifier instead of before it. The optional ``and has <keyword>``
# tail lives between the P/T modifier and the ``as long as`` clause,
# matching how MTG oracle text would print a keyword-granting
# trailing-rider line.
_STATIC_ABILITY_LINE_TRAILING = re.compile(
    r"^This creature gets "
    r"\+(?P<power>\d+)/\+(?P<toughness>\d+)"
    r"(?: and has (?P<keyword>[A-Za-z ]+))?"
    r" as long as (?P<condition>.+?)\.$"
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
    # Batch 11 — forward-looking N=3 variant. Same engine gate as the
    # ``two or more`` entry above with a higher threshold; the engine
    # accepts any non-negative integer for ``requires_spells_cast_this_
    # turn`` and the surface phrasing is the natural one-word
    # substitution. No EoE card prints this threshold today.
    "you've cast three or more spells this turn": {
        "requires_spells_cast_this_turn": 3
    },
    "it's your turn": {"active_turn_only": True},
}


def _parse_static_ability_line(line: str) -> StaticAbility | None:
    """Return a ``StaticAbility`` for a single static-ability line in
    either the leading (``As long as <condition>, this creature gets
    +N/+N[ and has <keyword>].``) or trailing (``This creature gets
    +N/+N[ and has <keyword>] as long as <condition>.``) shape, or
    ``None`` if the line shape doesn't match, the condition isn't
    recognized, or the granted keyword isn't a known evergreen.

    The two shapes are semantically identical and produce identical
    ``StaticAbility`` outputs. The leading regex is tried first; the
    trailing regex is the fallback.

    The static ability is always self-scoped (``StaticScope.SELF``); the
    "this creature gets" subject in the surface form is what makes that
    explicit.
    """
    stripped = line.strip()
    m = _STATIC_ABILITY_LINE.match(stripped)
    if m is None:
        m = _STATIC_ABILITY_LINE_TRAILING.match(stripped)
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
