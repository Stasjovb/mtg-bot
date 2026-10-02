"""Oracle-line recognizers for the Vintage Roto P1 package (stack &
restrictions): spell taxes, cast and activation prohibitions, counter-
spell variants and cast triggers.

Two hook points, each consulted only after every older grammar
declined, so no claimed card's parse changes:

* :func:`parse_roto_stack_line` -- whole permanent oracle lines (the
  creature / artifact / cube-enchantment builders' last fallback),
  returning a :class:`~mtg_bot.cards.parser.creature_wg_lines.WGLine`
  (printing fields, keywords, triggered / activated / static
  abilities). Tuple-valued fields from several lines are merged by
  :func:`merge_fields`.
* :func:`parse_roto_stack_effect` -- the very last fallback of
  ``effects._parse_effect`` (normalized phrases: no trailing period,
  lower-cased first letter).

Like the cube buckets, the grammar is switched off for printings that
exist only in the EoE-era dumps (``creature_rmc_grammar``'s switch).
Engine statics live in :mod:`mtg_bot.roto_restrictions`; effects in
:mod:`mtg_bot.effects.generic.roto_stack`.
"""

from __future__ import annotations

import re

from mtg_bot.cards.parser.creature_wg_lines import WGLine
from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


# Printing fields whose values are tuples that several oracle lines may
# each contribute to.
_TUPLE_FIELDS = frozenset({
    "roto_statics", "spell_cost_increases", "locks_activated_abilities_of",
})


def merge_fields(into: dict, fields: dict) -> None:
    """Fold one line's printing ``fields`` into ``into`` (tuple-valued
    fields concatenate; everything else is set)."""
    for key, value in fields.items():
        if key in _TUPLE_FIELDS and key in into:
            into[key] = tuple(into[key]) + tuple(value)
        else:
            into[key] = value


# ---------------------------------------------------------------------
# Spell taxes and the cost floor
# ---------------------------------------------------------------------

_SPELLS_COST_MORE_RE = re.compile(
    r"^(?:(?P<desc>[A-Z][a-z]+(?:, [a-z]+)*) spells|Spells) cost "
    r"\{(?P<n>\d+)\} more to cast\.$"
)


def _spells_cost_more(line: str, card: dict) -> WGLine | None:
    """``[<Descriptor>] spells cost {N} more to cast.`` (Sphere of
    Resistance, Thorn of Amethyst) -> ``spell_cost_increases`` (every
    player's matching spells; Thalia's field)."""
    m = _SPELLS_COST_MORE_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.card_flow_grammar import _parse_descriptor_body
    from mtg_bot.effects.generic.card_flow import CardFilter

    desc = m.group("desc")
    f = CardFilter() if desc is None else _parse_descriptor_body(desc.lower())
    if f is None:
        return None
    return WGLine(fields={"spell_cost_increases": ((f, int(m.group("n"))),)})


_EACH_SPELL_COSTS_MORE_EXCEPT_RE = re.compile(
    r"^Each spell costs \{(?P<n>\d+)\} more to cast except during its "
    r"controller's turn\.$"
)


def _each_spell_costs_more_except_controllers_turn(
    line: str, card: dict,
) -> WGLine | None:
    """``Each spell costs {N} more to cast except during its controller's
    turn.`` (Defense Grid)."""
    m = _EACH_SPELL_COSTS_MORE_EXCEPT_RE.match(line)
    if m is None:
        return None
    from mtg_bot.roto_restrictions import SpellTax

    return WGLine(fields={"roto_statics": (
        SpellTax(amount=int(m.group("n")), except_during_casters_turn=True),
    )})


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
}
_MINIMUM_COST_RE = re.compile(
    r"^(?P<untapped>As long as this (?:artifact|creature|permanent) is "
    r"untapped, )?(?:e|E)ach spell that would cost less than (?P<n>\w+) "
    r"mana to cast costs (?P<n2>\w+) mana to cast\.$"
)


def _minimum_spell_cost(line: str, card: dict) -> WGLine | None:
    """``[As long as this artifact is untapped, ]each spell that would
    cost less than N mana to cast costs N mana to cast.`` (Trinisphere)."""
    m = _MINIMUM_COST_RE.match(line)
    if m is None or m.group("n") != m.group("n2"):
        return None
    n = _NUMBER_WORDS.get(m.group("n"))
    if n is None:
        return None
    from mtg_bot.roto_restrictions import MinimumSpellCost

    return WGLine(fields={"roto_statics": (
        MinimumSpellCost(total=n, while_untapped=bool(m.group("untapped"))),
    )})


# ---------------------------------------------------------------------
# Prohibitions shared with the cube W/G statics
# ---------------------------------------------------------------------


def _activation_lock(line: str, card: dict) -> WGLine | None:
    """``Activated abilities of <types> can't be activated.`` (Null Rod,
    Stony Silence) -- Clarion Conqueror's ``locks_activated_abilities_of``
    (mana abilities included, as printed)."""
    from mtg_bot.cards.parser.creature_wg_lines import (
        _parse_activation_lock_line,
    )

    return _parse_activation_lock_line(line, card)


def _static_flag(line: str, card: dict) -> WGLine | None:
    """The W/G bucket's rules-restricting flag lines on a noncreature
    permanent ("Each player can't cast more than one spell each turn." --
    High Noon)."""
    from mtg_bot.cards.parser.creature_wg_lines import _parse_static_flag_line

    return _parse_static_flag_line(line, card)


_LINE_RECOGNIZERS = (
    _spells_cost_more,
    _each_spell_costs_more_except_controllers_turn,
    _minimum_spell_cost,
    _activation_lock,
    _static_flag,
)


def parse_roto_stack_line(line: str, card: dict) -> WGLine | None:
    """The :class:`WGLine` for one reminder-stripped permanent oracle
    ``line`` of ``card``, or ``None`` when no P1 recognizer claims it."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    line = _substitute_self_name(line.strip(), card.get("name", ""))
    for recognizer in _LINE_RECOGNIZERS:
        out = recognizer(line, card)
        if out is not None:
            return out
    return None


# ---------------------------------------------------------------------
# Effect phrases
# ---------------------------------------------------------------------

_EFFECT_RECOGNIZERS: tuple = ()


def parse_roto_stack_effect(phrase: str) -> Effect | None:
    """A P1 effect phrase (normalized), or ``None``."""
    if _disabled():
        return None
    for recognizer in _EFFECT_RECOGNIZERS:
        eff = recognizer(phrase)
        if eff is not None:
            return eff
    return None


__all__ = [
    "merge_fields",
    "parse_roto_stack_effect",
    "parse_roto_stack_line",
]
