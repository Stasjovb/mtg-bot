"""Unified effect grammar shared by creature triggered abilities and
spells.

Each shape's regex matches the *normalized* effect phrase — no
source-subject prefix (``it`` for creature triggers or ``<Name>``
for spells), no trailing period, first letter lowercased. Surface
preprocessing (the ``_normalize_*`` helpers below) strips the
per-context noise before dispatch, so both contexts share one
effect grammar — adding a new effect here makes it available to
creature triggered abilities and to spells (single-line and
multi-line) at the same time.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    CounterTargetSpell,
    CreateToken,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DestroyTargetArtifact,
    DestroyTargetCreature,
    DestroyTargetLand,
    DestroyTargetNoncreaturePermanent,
    DrawCards,
    EachOpponentLosesLife,
    Effect,
    ExileTargetCreature,
    GainLife,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnTargetCreature,
    SelfMill,
    Surveil,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


# Spelled-out small-cardinal lookup for oracle phrasings like
# ``mill three cards``. Scryfall consistently spells out 1–10 as words
# in mill-style effects (e.g. "mill three cards" on Lithic Hierograph).
# Larger amounts use digits, so the table tops out at ten — extend if a
# future card ships an oracle line with "mill twelve cards".
_SMALL_CARDINAL_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_SMALL_CARDINAL_PATTERN = "|".join(_SMALL_CARDINAL_WORDS)


_DEAL_DAMAGE_ANY_TARGET = re.compile(
    r"^deals (\d+) damage to any target$"
)
_DEAL_DAMAGE_TARGET_CREATURE = re.compile(
    r"^deals (\d+) damage to target creature$"
)
_DRAW_A_CARD = re.compile(r"^draw a card$")
_DRAW_N_CARDS = re.compile(r"^draw (\d+) cards$")
_YOU_GAIN_N_LIFE = re.compile(r"^you gain (\d+) life$")
_PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on target creature$"
)
_PUT_PLUS_ONE_COUNTER_ON_THIS_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on this creature$"
)
_DESTROY_TARGET_CREATURE = re.compile(r"^destroy target creature$")
_COUNTER_TARGET_SPELL = re.compile(r"^counter target spell$")
_EXILE_TARGET_CREATURE = re.compile(r"^exile target creature$")
_EACH_OPPONENT_LOSES_N_LIFE = re.compile(
    r"^each opponent loses (\d+) life$"
)
# Narrow handler for Gravpack Monoist's exact token-creation payload.
# Generalizes once another card needs a similar slice with different
# color/power/toughness/subtype.
_CREATE_TAPPED_2_2_ROBOT = re.compile(
    r"^create a tapped 2/2 colorless Robot artifact creature token$"
)
_SURVEIL_N = re.compile(r"^surveil (\d+)$")
# Mill is "mill <amount> cards" where the amount is either a digit or
# one of the spelled-out small cardinals (Scryfall printing convention).
# Singular "mill 1 card" / "mill one card" is intentionally unsupported
# — no EoE card prints that surface form. Add it the day one ships.
_MILL_N_CARDS = re.compile(
    rf"^mill (\d+|{_SMALL_CARDINAL_PATTERN}) cards$"
)
_DESTROY_TARGET_ARTIFACT = re.compile(r"^destroy target artifact$")
_DESTROY_TARGET_LAND = re.compile(r"^destroy target land$")
_DESTROY_TARGET_NONCREATURE_PERMANENT = re.compile(
    r"^destroy target noncreature permanent$"
)


def _parse_amount(token: str) -> int:
    """Convert a Scryfall amount token (digit or spelled-out small
    cardinal) into the integer N. Assumes the token already passed a
    regex that matched either ``\\d+`` or one of
    ``_SMALL_CARDINAL_WORDS``."""
    if token.isdigit():
        return int(token)
    return _SMALL_CARDINAL_WORDS[token]


def _parse_effect(phrase: str) -> Effect | None:
    """Parse a *normalized* effect phrase into an ``Effect``.

    Normalized form has no source-subject prefix, no trailing period,
    and a lowercased first letter — see ``_normalize_*`` helpers below
    for the per-context surface stripping.
    """
    m = _DEAL_DAMAGE_ANY_TARGET.match(phrase)
    if m is not None:
        return DealDamageAnyTarget(amount=int(m.group(1)))
    m = _DEAL_DAMAGE_TARGET_CREATURE.match(phrase)
    if m is not None:
        return DealDamageToTargetCreature(amount=int(m.group(1)))
    if _DRAW_A_CARD.match(phrase) is not None:
        return DrawCards(amount=1)
    m = _DRAW_N_CARDS.match(phrase)
    if m is not None:
        return DrawCards(amount=int(m.group(1)))
    m = _YOU_GAIN_N_LIFE.match(phrase)
    if m is not None:
        return GainLife(amount=int(m.group(1)))
    if _PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnTargetCreature(amount=1)
    if _PUT_PLUS_ONE_COUNTER_ON_THIS_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnSelf(amount=1)
    if _DESTROY_TARGET_CREATURE.match(phrase) is not None:
        return DestroyTargetCreature()
    if _COUNTER_TARGET_SPELL.match(phrase) is not None:
        return CounterTargetSpell()
    if _EXILE_TARGET_CREATURE.match(phrase) is not None:
        return ExileTargetCreature()
    m = _EACH_OPPONENT_LOSES_N_LIFE.match(phrase)
    if m is not None:
        return EachOpponentLosesLife(amount=int(m.group(1)))
    if _CREATE_TAPPED_2_2_ROBOT.match(phrase) is not None:
        return CreateToken(
            token_printing=TOKEN_PRINTINGS["Robot"],
            count=1,
            tapped=True,
        )
    m = _SURVEIL_N.match(phrase)
    if m is not None:
        return Surveil(amount=int(m.group(1)))
    m = _MILL_N_CARDS.match(phrase)
    if m is not None:
        return SelfMill(amount=_parse_amount(m.group(1)))
    if _DESTROY_TARGET_ARTIFACT.match(phrase) is not None:
        return DestroyTargetArtifact()
    if _DESTROY_TARGET_LAND.match(phrase) is not None:
        return DestroyTargetLand()
    if _DESTROY_TARGET_NONCREATURE_PERMANENT.match(phrase) is not None:
        return DestroyTargetNoncreaturePermanent()
    return None


def _normalize_creature_effect_phrase(phrase: str) -> str:
    """Strip the ``it`` source-subject pronoun if present, leaving the
    normalized phrase ready for ``_parse_effect``."""
    phrase = phrase.strip()
    if phrase.startswith("it "):
        phrase = phrase[len("it "):]
    return phrase


def _normalize_spell_effect_phrase(phrase: str, name: str) -> str:
    """Strip the ``<Name>`` source-subject prefix (if present), trailing
    period, and lowercase the first letter — leaving the normalized
    phrase ready for ``_parse_effect``."""
    phrase = phrase.strip()
    if phrase.endswith("."):
        phrase = phrase[:-1]
    prefix = name + " "
    if phrase.startswith(prefix):
        phrase = phrase[len(prefix):]
    if phrase and phrase[0].isupper():
        phrase = phrase[0].lower() + phrase[1:]
    return phrase


def _parse_effect_phrase(phrase: str) -> Effect | None:
    """Parse a creature-triggered-ability effect phrase. Surface form
    is ``it deals N damage…`` / ``draw a card`` / etc. Delegates to
    the unified ``_parse_effect`` after stripping the ``it`` prefix."""
    return _parse_effect(_normalize_creature_effect_phrase(phrase))


def _parse_spell_effect_phrase(phrase: str, name: str) -> Effect | None:
    """Parse a spell's full-sentence effect text.

    ``phrase`` is one sentence (period included) of oracle text. ``name``
    is the card's own name and is stripped if it appears as the subject.
    Delegates to the unified ``_parse_effect`` after normalization, so
    every effect available to creature triggered abilities is also
    available to spells (and vice versa).
    """
    return _parse_effect(_normalize_spell_effect_phrase(phrase, name))
