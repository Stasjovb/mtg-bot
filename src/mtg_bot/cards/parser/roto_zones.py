"""Parser recognizers for the Vintage Roto P2 package: library,
graveyard and hand (``docs/ROTO_COVERAGE_PLAN.md`` section 2).

Effect phrases (:func:`parse_roto_zones_effect`) are the very last
fallback of ``effects._parse_effect``, after every cube bucket, so no
phrase an older recognizer claims changes meaning. Like the cube
buckets, the grammar is switched off for printings that exist only in
the EoE-era dumps (the shared ``creature_rmc_grammar`` switch), so no
EoE printing's parse can change. Every recognizer is parameterized over
the varying parts of its printed shape; engine effects live in
:mod:`mtg_bot.effects.generic.roto_zones`.
"""

from __future__ import annotations

import dataclasses
import re

from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


_CARDINALS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "thirteen": 13, "twenty": 20,
}


def _count(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _CARDINALS.get(token)


# ---------------------------------------------------------------------
# Card descriptors
# ---------------------------------------------------------------------

# "<base descriptor>[ with power|toughness N or less]" -- the stat bound
# is the roto extension; the base goes through the shared card-flow
# descriptor grammar.
_STAT_BOUND_RE = re.compile(
    r"^(?P<base>.+?) with (?P<stat>power|toughness) (?P<n>\d+) or less$"
)
# Supertype words the shared grammar doesn't read: "basic" (a supertype
# the card must have) and "nonlegendary" (one it must not have).
_SUPERTYPE_WORDS = {"basic": "Basic", "legendary": "Legendary"}


def parse_roto_descriptor(text: str):
    """``a nonlegendary card`` / ``a creature card with power 2 or
    less`` / ``a basic land card`` -> ``RotoCardFilter`` (``None`` if
    unrecognized). Plural descriptors are the caller's job."""
    from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
    from mtg_bot.effects.generic.roto_zones import RotoCardFilter

    max_power = max_toughness = None
    m = _STAT_BOUND_RE.match(text)
    if m is not None:
        text = m.group("base")
        if m.group("stat") == "power":
            max_power = int(m.group("n"))
        else:
            max_toughness = int(m.group("n"))
    words = text.split(" ")
    excluded: list[str] = []
    required: str | None = None
    kept: list[str] = []
    for word in words:
        if word.startswith("non") and word[3:] in _SUPERTYPE_WORDS:
            excluded.append(_SUPERTYPE_WORDS[word[3:]])
        elif word == "basic" and required is None:
            required = "Basic"
        else:
            kept.append(word)
    if len(kept) >= 2 and kept[0] in ("a", "an"):
        kept[0] = "an" if kept[1][0] in "aeiou" else "a"
    base = parse_card_descriptor(" ".join(kept))
    if base is None:
        return None
    if required is not None:
        if base.supertype is not None:
            return None
        base = dataclasses.replace(base, supertype=required)
    return RotoCardFilter(
        **{f.name: getattr(base, f.name) for f in dataclasses.fields(base)},
        excluded_supertypes=tuple(excluded),
        max_power=max_power,
        max_toughness=max_toughness,
    )


# ---------------------------------------------------------------------
# Tutors (F10)
# ---------------------------------------------------------------------

_SEARCH_TO_ZONE_RE = re.compile(
    r"^search your library for (?P<desc>an? .+?)(?P<reveal>, reveal "
    r"(?:it|that card))?, put (?:it|that card) (?P<dest>into your hand|"
    r"into your graveyard|onto the battlefield)(?P<tapped> tapped)?, "
    r"then shuffle$"
)
_SEARCH_DISCARD_RANDOM_RE = re.compile(
    r"^search your library for (?P<desc>an? .+?), put that card into your "
    r"hand, discard a card at random, then shuffle$"
)
_SEARCH_UNTAP_IF_LANDS_RE = re.compile(
    r"^search your library for (?P<desc>an? .+?), put it onto the "
    r"battlefield tapped, then shuffle\. Then if you control "
    r"(?P<n>\w+) or more lands, untap that land$"
)
_REMOVAL_CONTROLLER_MAY_SEARCH_RE = re.compile(
    r"^(?P<removal>(?:destroy|exile) target .+?)\. Its controller may "
    r"search their library for (?P<desc>an? .+?), put it onto the "
    r"battlefield(?P<tapped> tapped)?, then shuffle$"
)
_SEARCH_ANY_NUMBER_TOTAL_MV_RE = re.compile(
    r"^search your library for any number of (?P<desc>.+?) cards with "
    r"total mana value (?P<n>\d+) or less, put them onto the battlefield, "
    r"then shuffle$"
)
# "you may exile it. If you do, <effect>" -- a dies trigger exiling the
# card that died (Academy Rector, Arena Rector). Kept to the tutor
# consequent so the bare pronoun can't be read in another context.
_MAY_EXILE_IT_IF_YOU_DO_SEARCH_RE = re.compile(
    r"^you may exile it\. If you do, (?P<then>search your library for .+)$"
)


def _parse_tutors(phrase: str) -> Effect | None:
    from mtg_bot.effects.generic.card_flow import SearchLibrary
    from mtg_bot.effects.generic.roto_zones import (
        SearchAnyNumberTotalManaValueOntoBattlefield,
        SearchOntoBattlefieldTappedUntapIfLands,
        SearchToHandDiscardAtRandomThenShuffle,
    )

    m = _SEARCH_TO_ZONE_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        if f is None:
            return None
        dest = {
            "into your hand": "hand", "into your graveyard": "graveyard",
            "onto the battlefield": "battlefield",
        }[m.group("dest")]
        if m.group("tapped") and dest != "battlefield":
            return None
        return SearchLibrary(
            card_filter=f, destination=dest,
            reveal=m.group("reveal") is not None,
            tapped=m.group("tapped") is not None,
        )
    m = _SEARCH_DISCARD_RANDOM_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        if f is None:
            return None
        return SearchToHandDiscardAtRandomThenShuffle(card_filter=f)
    m = _SEARCH_UNTAP_IF_LANDS_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        n = _count(m.group("n"))
        if f is None or n is None:
            return None
        return SearchOntoBattlefieldTappedUntapIfLands(card_filter=f, min_lands=n)
    m = _SEARCH_ANY_NUMBER_TOTAL_MV_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(f"a {m.group('desc')} card")
        if f is None:
            return None
        return SearchAnyNumberTotalManaValueOntoBattlefield(
            card_filter=f, max_total_mv=int(m.group("n")),
        )
    m = _REMOVAL_CONTROLLER_MAY_SEARCH_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.removal_phrases import parse_targeted_removal
        from mtg_bot.effects.generic.roto_zones import (
            ControllerMaySearchOntoBattlefield,
        )
        from mtg_bot.effects.generic.targeted_removal import (
            RemoveTargetPermanents,
        )

        removal = parse_targeted_removal(m.group("removal"))
        f = parse_roto_descriptor(m.group("desc"))
        if (
            not isinstance(removal, RemoveTargetPermanents)
            or removal.rider is not None or f is None
        ):
            return None
        return dataclasses.replace(
            removal, rider=ControllerMaySearchOntoBattlefield(
                card_filter=f, tapped=m.group("tapped") is not None,
            ),
        )
    m = _MAY_EXILE_IT_IF_YOU_DO_SEARCH_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect
        from mtg_bot.effects.combinators import IfYouDo, MayDo
        from mtg_bot.effects.generic.roto_zones import ExileSourceCardFromGraveyard

        then = _parse_effect(m.group("then"))
        if then is None or then.requires_target():
            return None
        return IfYouDo(
            do_action=MayDo(inner=ExileSourceCardFromGraveyard()),
            then_action=then,
        )
    return None


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

_EFFECT_PARSERS = (
    _parse_tutors,
)


def parse_roto_zones_effect(phrase: str) -> Effect | None:
    """Last-resort effect recognizers for the P2 package (see module
    doc)."""
    if _disabled():
        return None
    for parser in _EFFECT_PARSERS:
        eff = parser(phrase)
        if eff is not None:
            return eff
    return None
