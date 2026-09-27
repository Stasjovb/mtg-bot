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
# ``you get {E}{E}`` / ``get {E}`` (the second arm of a compound
# ``you gain 1 life and get {E}``).
_GET_ENERGY = re.compile(r"^(?:you )?get ((?:\{E\})+)$")
# ``scry N`` (CR 701.18) and ``each opponent mills N cards`` (CR 701.13).
_SCRY_N = re.compile(r"^scry (\d+|one|two|three|four|five)$")
_EACH_OPPONENT_MILLS = re.compile(
    r"^each opponent mills (\d+|a|one|two|three|four|five|six|seven|eight|nine|ten) cards?$"
)


def _amount(raw: str) -> int:
    words = {
        "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    return int(raw) if raw.isdigit() else words[raw]


_COUNT_WORDS = {
    "twice": 2, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}


def _investigate_count(raw: str | None) -> int:
    if raw is None:
        return 1
    if raw in _COUNT_WORDS:
        return _COUNT_WORDS[raw]
    return int(raw.split()[0])


# ``[another ]target creature you control gains protection from
# [colorless or from ]the color of your choice until end of turn``.
_PROTECTION_OF_CHOICE = re.compile(
    r"^(?P<another>another )?target creature you control gains protection "
    r"from (?P<colorless>colorless or from )?the color of your choice "
    r"until end of turn$"
)
# ``target creature you control gains <keywords> until end of turn``.
_TARGET_YOU_CONTROL_GAINS = re.compile(
    r"^target creature you control gains (?P<body>.+) until end of turn$"
)
# ``[other ]creatures you control gain <keywords> until end of turn`` /
# ``creature tokens you control gain <keywords> until end of turn``.
_GROUP_GAINS = re.compile(
    r"^(?P<other>other )?creature(?P<tokens> tokens)?s? you control gain "
    r"(?P<body>.+) until end of turn$"
)


def _parse_keyword_grant_effect(phrase: str) -> Effect | None:
    """Keyword grants the older per-shape regexes in ``effects`` don't
    cover: protection of a chosen color, a you-control target grant,
    and whole-group grants."""
    from mtg_bot.cards.parser.effects import _parse_keyword_grant_body
    from mtg_bot.effects.generic.keyword_actions import (
        GrantProtectionOfChoiceUEOT,
    )
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
        PumpTargetCreatureUntilEOT,
    )

    m = _PROTECTION_OF_CHOICE.match(phrase)
    if m is not None:
        return GrantProtectionOfChoiceUEOT(
            exclude_self=m.group("another") is not None,
            allow_colorless=m.group("colorless") is not None,
        )
    m = _TARGET_YOU_CONTROL_GAINS.match(phrase)
    if m is not None:
        kws = _parse_keyword_grant_body(m.group("body"))
        if kws is None:
            return None
        return PumpTargetCreatureUntilEOT(
            granted_keywords=kws, you_control_only=True,
        )
    m = _GROUP_GAINS.match(phrase)
    if m is not None:
        if m.group("other") and m.group("tokens"):
            return None
        kws = _parse_keyword_grant_body(m.group("body"))
        if kws is None:
            return None
        return PumpCreaturesYouControlUntilEOT(
            granted_keywords=kws,
            exclude_source=m.group("other") is not None,
            tokens_only=m.group("tokens") is not None,
        )
    return None


def _parse_keyword_action_effect(phrase: str) -> Effect | None:
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.keyword_actions import (
        BecomeMonarch, Explore, GetEnergy, TakeInitiative,
    )
    from mtg_bot.effects.generic.tokens import CreateToken

    m = _SCRY_N.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.library_lookat import Scry

        # Real CR 701.18 decision (keep / bottom per card) — the parsed
        # surface never used the keep-all-on-top first-slice shortcut
        # the Rust ``ScryN`` arm mirrors for the EoE bridge.
        return Scry(amount=_amount(m.group(1)), bottom_choice=True)
    m = _EACH_OPPONENT_MILLS.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.draw_mill import EachOpponentMillsCards

        return EachOpponentMillsCards(amount=_amount(m.group(1)))
    m = _GET_ENERGY.match(phrase)
    if m is not None:
        return GetEnergy(amount=m.group(1).count("{E}"))
    m = _INVESTIGATE.match(phrase)
    if m is not None:
        return CreateToken(
            token_printing=TOKEN_PRINTINGS["Clue"],
            count=_investigate_count(m.group("n")),
        )
    if phrase == "you become the monarch":
        return BecomeMonarch()
    if phrase == "you take the initiative":
        return TakeInitiative()
    if phrase == "this creature explores":
        return Explore()
    if phrase == "target creature you control explores":
        return Explore(target=True)
    return _parse_keyword_grant_effect(phrase)


# ── Creature tokens described by their printed characteristics ───────
#
# ``create <count> [tapped ]<P>/<T> <colors> <Subtypes> [artifact ]
# [enchantment ]creature token[s][ that's tapped and attacking]
# [ with <keywords>]`` — when the subtype phrase isn't a registered
# ``TOKEN_PRINTINGS`` entry, the token printing is built from the text
# itself (CR 111.4: a token's characteristics are exactly what the
# effect that created it says). Only keyword riders are accepted after
# ``with``; a quoted granted ability or ``named <Name>`` keeps the card
# unclaimed.
_COLOR_WORD = r"(?:white|blue|black|red|green)"
_SYNTH_TOKEN = re.compile(
    r"^create (?P<count>a|an|\d+|one|two|three|four|five|six|seven|eight|nine|ten) "
    r"(?P<tapped>tapped )?(?P<p>\d+)/(?P<t>\d+) "
    rf"(?P<colors>colorless|{_COLOR_WORD}(?:(?:, | and |, and ){_COLOR_WORD})*) "
    r"(?P<subtypes>[A-Z][A-Za-z'-]*(?: [A-Z][A-Za-z'-]*)*) "
    r"(?P<artifact>artifact )?(?P<enchantment>enchantment )?creature tokens?"
    r"(?P<attacking> that's tapped and attacking)?"
    r"(?: with (?:(?P<body>[^\"]+?)|(?P<quoted>\"[^\"]*\")))?"
    r"(?P<attacking_after> that's tapped and attacking)?$"
)
# Quoted token abilities modeled as printing fields: Reckoner
# Bankbuster's Pilot, "This token crews Vehicles as though its power
# were N greater." -> ``CardPrinting.crew_power_bonus = N``. Any other
# quoted ability keeps the card unclaimed.
_TOKEN_CREW_BONUS_RIDER = re.compile(
    r'^"This token crews Vehicles as though its power were (\d+) greater\."$'
)
_COLOR_LETTER = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_CARDINALS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _parse_token_keyword_list(body: str) -> frozenset[str] | None:
    """``flying`` / ``trample and haste`` / ``flying, vigilance, and
    lifelink`` -> engine keyword set, or None on any unknown piece."""
    from mtg_bot.cards.parser.keywords import _parse_granted_keyword_piece

    normalized = body.replace(", and ", ", ").replace(" and from ", "\x00")
    pieces = [
        p.strip().replace("\x00", " and from ")
        for chunk in normalized.split(", ")
        for p in chunk.split(" and ")
    ]
    out: set[str] = set()
    for piece in pieces:
        parsed = _parse_granted_keyword_piece(piece)
        if parsed is None:
            return None
        out.update(parsed)
    return frozenset(out)


def _synthesize_creature_token_effect(phrase: str) -> Effect | None:
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.effects.generic.tokens import CreateToken

    m = _SYNTH_TOKEN.match(phrase)
    if m is None:
        return None
    keywords: frozenset[str] = frozenset()
    if m.group("body") is not None:
        parsed = _parse_token_keyword_list(m.group("body"))
        if parsed is None:
            return None
        keywords = parsed
    crew_bonus = 0
    if m.group("quoted") is not None:
        crew_m = _TOKEN_CREW_BONUS_RIDER.match(m.group("quoted"))
        if crew_m is None:
            return None
        crew_bonus = int(crew_m.group(1))
    raw_count = m.group("count")
    count = int(raw_count) if raw_count.isdigit() else _CARDINALS[raw_count]
    colors = frozenset(
        _COLOR_LETTER[w] for w in re.findall(_COLOR_WORD, m.group("colors"))
    )
    subtypes = tuple(m.group("subtypes").split(" "))
    printing = make_token_creature(
        m.group("subtypes"), int(m.group("p")), int(m.group("t")),
        subtypes=subtypes, keywords=keywords,
        artifact=m.group("artifact") is not None,
        enchantment=m.group("enchantment") is not None,
        colors=colors,
    )
    if crew_bonus:
        from dataclasses import replace
        printing = replace(printing, crew_power_bonus=crew_bonus)
    attacking = (
        m.group("attacking") is not None
        or m.group("attacking_after") is not None
    )
    return CreateToken(
        token_printing=printing, count=count,
        tapped=m.group("tapped") is not None or attacking,
        attacking=attacking,
    )
