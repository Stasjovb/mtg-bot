"""Parser grammar for the Vintage Roto P5 package: board-state prison
and layers (``docs/ROTO_COVERAGE_PLAN.md`` section 3).

Three entry points, each the last fallback of a shared dispatcher, so
no phrase an older recognizer claims changes meaning:

* :func:`parse_roto_board_effect` -- effect phrases (after every other
  bucket in ``effects._parse_effect``);
* :func:`parse_roto_cost_piece` -- activation-cost atoms (after the
  cube creatures bucket in ``activated._classify_cost_piece``);
* :func:`parse_roto_board_line` -- whole oracle lines a permanent
  builder declined: printing-level statics, triggers whose condition
  the trigger tables don't know, ... (``BoardLine``).

Like the cube buckets, the grammar is switched off for printings that
exist only in the EoE-era dumps (the shared ``creature_rmc_grammar``
switch), so no EoE printing's parse can change. Every recognizer is
parameterized over the varying parts of its printed shape; engine
effects live in ``effects/generic/roto_board.py`` and the board-rule
statics in ``mtg_bot.roto_board_statics``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


@dataclass
class BoardLine:
    """What one recognized oracle line contributes to a printing."""

    fields: dict = field(default_factory=dict)
    keywords: tuple[str, ...] = ()
    triggers: tuple = ()
    activated: tuple = ()
    statics: tuple = ()


_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _n(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


# ---------------------------------------------------------------------------
# Noun phrases
# ---------------------------------------------------------------------------

_NON_SUBTYPE = re.compile(r"\bnon-(?P<sub>[A-Z][a-z]+) ")
_PT_MODIFIER = re.compile(r"^(?P<p>\d+)/(?P<t>\d+) (?P<rest>creatures?)$")


def permanent_phrase(np: str, *, plural: bool = False):
    """The compositional permanent grammar
    (``target_phrases.parse_permanent_phrase``) plus the modifiers this
    package's cards print and the base grammar lacks: ``legendary``
    (Minamo), ``non-<Subtype>`` (Emerald Charm's "non-Aura
    enchantment"), a ``P/T`` creature (Pendelhaven's "1/1 creature")
    and the plural controller ``your opponents control`` (Cryptic
    Command). ``None`` when any word is outside the grammar."""
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.generic.roto_board import (
        IsLegendaryPermanent,
        LacksSubtype,
    )
    from mtg_bot.effects.object_predicates import (
        ControlledByOpponent,
        HasPowerToughness,
    )

    np = np.strip()
    quals = []
    if np.endswith(" your opponents control"):
        np = np[: -len(" your opponents control")]
        quals.append(ControlledByOpponent())
    for m in list(_NON_SUBTYPE.finditer(np)):
        quals.append(LacksSubtype(m.group("sub")))
    np = _NON_SUBTYPE.sub("", np)
    if np.startswith("legendary "):
        np = np[len("legendary "):]
        quals.append(IsLegendaryPermanent())
    m = _PT_MODIFIER.match(np)
    if m is not None:
        quals.append(HasPowerToughness(int(m.group("p")), int(m.group("t"))))
        np = m.group("rest")
    base = parse_permanent_phrase(np, plural=plural)
    if base is None:
        return None
    for q in quals:
        base = base & q
    return base


# ---------------------------------------------------------------------------
# Effect phrases
# ---------------------------------------------------------------------------

# "deals damage to each player equal to [twice] the number of <np> that
# player controls" (Price of Progress).
_DAMAGE_EACH_PLAYER_PER_CONTROLLED = re.compile(
    r"^deals damage to each player equal to (?P<twice>twice )?the number of "
    r"(?P<np>.+?) that player controls$"
)
# "tap all <plural np>" (Cryptic Command).
_TAP_ALL = re.compile(r"^tap all (?P<np>.+)$")
# "destroy each <np> with mana value equal to the number of <kind>
# counters on this <permanent>" (Engineered Explosives, The Filigree
# Sylex -- whose self-name the clause grammar rewrites to "this
# creature").
_DESTROY_EACH_MV_EQUAL_COUNTERS = re.compile(
    r"^destroy each (?P<np>.+?) with mana value equal to the number of "
    r"(?P<kind>[a-z]+) counters on this "
    r"(?:artifact|creature|enchantment|land|permanent)$"
)
# "destroy each <a>, <b>, and <c> with mana value X or less" (Pernicious
# Deed): in the "each" frame an "and" list is a union.
_DESTROY_EACH_AND_LIST = re.compile(
    r"^(?P<verb>destroy|exile) each (?P<np>[a-z]+(?:, [a-z]+)*,? and [a-z]+)"
    r"(?P<rest> with mana value X or less)?$"
)


def parse_roto_board_effect(phrase: str) -> Effect | None:
    """Effect phrases of the P5 package (normalized: lower-cased first
    letter, no trailing period, source subject stripped)."""
    if _disabled():
        return None
    from mtg_bot.effects.generic import roto_board as rb

    m = _DAMAGE_EACH_PLAYER_PER_CONTROLLED.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"), plural=True)
        if f is None:
            return None
        return rb.DamageEachPlayerPerControlled(
            per_filter=f, multiplier=2 if m.group("twice") else 1,
            label=m.group("np"),
        )
    m = _TAP_ALL.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"), plural=True)
        if f is None:
            return None
        return rb.TapAllMatching(permanent_filter=f, label=m.group("np"))
    m = _DESTROY_EACH_MV_EQUAL_COUNTERS.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        from mtg_bot.effects.generic.targeted_removal import RemoveAllMatching

        return RemoveAllMatching(
            permanent_filter=f & rb.HasManaValueEqualToSourceCounters(
                m.group("kind"),
            ),
            action="destroy",
            label=(
                f"each {m.group('np')} with mana value equal to the number "
                f"of {m.group('kind')} counters on this permanent"
            ),
        )
    m = _DESTROY_EACH_AND_LIST.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.removal_phrases import parse_destroy_all

        union = m.group("np").replace(", and ", ", or ").replace(" and ", " or ")
        return parse_destroy_all(
            f"{m.group('verb')} each {union}{m.group('rest') or ''}"
        )
    return None


# ---------------------------------------------------------------------------
# Cost atoms
# ---------------------------------------------------------------------------

_SACRIFICE_SELF_PIECES = frozenset({"Sacrifice this enchantment"})
# "Remove ten oil counters from among permanents you control" (The
# Filigree Sylex).
_REMOVE_COUNTERS_FROM_AMONG = re.compile(
    r"^Remove (?P<n>\w+) (?P<kind>[a-z]+) counters? from among permanents "
    r"you control$"
)


def parse_roto_cost_piece(piece: str):
    """Activation-cost atoms of the P5 package -> ``activated._CostPiece``
    (``None`` when the piece isn't one)."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.activated import _CostPiece
    from mtg_bot.effects.generic import roto_board as rb
    from mtg_bot.effects.generic.cube_creatures_rmc import SacrificePermanentsCost
    from mtg_bot.effects.value_predicates import IsPermanent

    m = _REMOVE_COUNTERS_FROM_AMONG.match(piece)
    if m is not None and (m.group("n").isdigit() or m.group("n") in _NUMBER_WORDS):
        return _CostPiece(kind="extra", atom=rb.RemoveCountersFromAmongPermanentsCost(
            kind=m.group("kind"), count=_n(m.group("n")),
        ))
    if piece in _SACRIFICE_SELF_PIECES:
        # "Sacrifice this enchantment" (Seal of Cleansing, Pernicious
        # Deed): the enchantment self-reference of ``sacrifice_self``.
        return _CostPiece(kind="sacrifice_self")
    if piece == "Sacrifice a permanent":
        # Claws of Gix: any permanent you control, the source included.
        return _CostPiece(kind="extra", atom=SacrificePermanentsCost(
            permanent_filter=IsPermanent(), label="a permanent",
        ))
    return None


# ---------------------------------------------------------------------------
# Whole lines
# ---------------------------------------------------------------------------


# "<costs>, <cost atom> and sacrifice <this>: <effect>" -- the last two
# cost atoms joined by "and" instead of a comma (The Filigree Sylex's
# "Remove ten oil counters from among permanents you control and
# sacrifice The Filigree Sylex").
_AND_SACRIFICE_SELF_COST = re.compile(
    r"^(?P<costs>[^:]+?) and sacrifice this (?P<noun>creature|artifact|"
    r"enchantment|land): (?P<effect>.+)$"
)


def _activated_with_and_joined_sacrifice(line: str) -> BoardLine | None:
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    m = _AND_SACRIFICE_SELF_COST.match(line)
    if m is None:
        return None
    rewritten = (
        f"{m.group('costs')}, Sacrifice this {m.group('noun')}: "
        f"{m.group('effect')}"
    )
    ability = _parse_activated_ability_line(rewritten)
    if ability is None or not ability.cost.sacrifice_self:
        return None
    return BoardLine(activated=(ability,))


_LINE_RECOGNIZERS = (
    _activated_with_and_joined_sacrifice,
)


def parse_roto_board_line(line: str, card: dict) -> BoardLine | None:
    """A whole oracle line of a P5 permanent the builder's grammar
    declined (reminder text stripped)."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    line = _substitute_self_name(line.strip(), card.get("name", ""))
    for recognizer in _LINE_RECOGNIZERS:
        parsed = recognizer(line)
        if parsed is not None:
            return parsed
    return None


__all__ = [
    "BoardLine",
    "parse_roto_board_effect",
    "parse_roto_board_line",
    "parse_roto_cost_piece",
    "permanent_phrase",
]
