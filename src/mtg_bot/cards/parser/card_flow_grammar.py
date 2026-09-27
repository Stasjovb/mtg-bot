"""Effect grammar for card-flow spell shapes: targeted draw, tutors,
hand disruption, library look-and-select, wheels, mass zone moves and
a few mana / library primitives.

Hooked into ``effects._parse_effect`` as the LAST dispatch step (after
every pre-existing recognizer), so no phrase an older recognizer
already claims changes meaning; these recognizers only claim phrases
nothing else did. Everything here is parameterized — the varying parts
of a printed shape (amounts, card descriptors, destinations, the
"may" rider) are capture groups — and multi-sentence shapes recurse
into ``_parse_effect`` for their trailing sentences, so a new card with
the same shape costs zero code.

Every phrase reaching this module is *normalized* (see
``effects._normalize_spell_effect_phrase``): no trailing period and a
lower-cased first letter. Later sentences inside a multi-sentence
phrase keep their original capitalization, hence the ``[Yy]ou`` style
alternations.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect
from mtg_bot.effects.generic.card_flow import (
    ANY_CARD,
    CardFilter,
    EachPlayerDiscardsHand,
    EachPlayerShufflesZonesIntoLibrary,
    ExileThisSpell,
    LookAtTargetPlayersHand,
    LookAtTopCardsPutIntoHand,
    PutCardsFromHandOnTopOfLibrary,
    ReorderTopCards,
    ReturnAllPermanentsToOwnersHands,
    ReturnTargetSpellToOwnersHand,
    SearchLibrary,
    ShuffleYourLibrary,
    TargetPlayerDiscardsAtRandom,
    TargetPlayerDraws,
    TargetPlayerRevealsHandYouChooseDiscard,
    TargetPlayerTakesExtraTurn,
    UntapUpToNLands,
)


_CARDINALS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_AMT = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|X)"


def _amount(token: str):
    """Digit / spelled cardinal -> int; ``X`` -> ``ResolvingX()``."""
    if token == "X":
        from mtg_bot.effects.formulas import ResolvingX

        return ResolvingX()
    if token.isdigit():
        return int(token)
    return _CARDINALS[token]


# ---------------------------------------------------------------------
# Card-descriptor grammar ("a green creature card", "a noncreature,
# nonland card", "an instant or sorcery card", ...)
# ---------------------------------------------------------------------

_TYPE_WORDS: dict[str, str] = {
    "artifact": "Artifact", "creature": "Creature",
    "enchantment": "Enchantment", "instant": "Instant",
    "sorcery": "Sorcery", "land": "Land", "planeswalker": "Planeswalker",
    "battle": "Battle", "permanent": "Permanent",
}
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
_SUPERTYPE_WORDS: dict[str, str] = {"legendary": "Legendary"}

_DESCRIPTOR_RE = re.compile(
    r"^(?:a|an) (?:(?P<body>.+?) )?card"
    r"(?: with mana value (?P<mv>\d+) or less)?$"
)
_PERMANENT_DESCRIPTOR_RE = re.compile(r"^(?:a|an) (?P<body>.+)$")


def _parse_descriptor_body(body: str) -> CardFilter | None:
    """Parse the adjective / type words of a card descriptor.

    Comma-separated parts are conjunctive ("noncreature, nonland"); a
    part may hold an ``or`` alternation of types ("instant or
    sorcery"). Recognized words: ``non<type>`` exclusions, colors,
    ``legendary``, and card types (``permanent`` is a pseudo-type).
    Anything else rejects the descriptor.
    """
    any_types: list[str] = []
    excluded: list[str] = []
    color = None
    supertype = None
    for part in body.split(", "):
        alternatives = part.split(" or ")
        if len(alternatives) > 1:
            for alt in alternatives:
                t = _TYPE_WORDS.get(alt)
                if t is None:
                    return None
                any_types.append(t)
            continue
        for word in part.split(" "):
            if word.startswith("non") and word[3:] in _TYPE_WORDS:
                excluded.append(_TYPE_WORDS[word[3:]])
            elif word in _COLOR_WORDS and color is None:
                color = _COLOR_WORDS[word]
            elif word in _SUPERTYPE_WORDS and supertype is None:
                supertype = _SUPERTYPE_WORDS[word]
            elif word in _TYPE_WORDS and not any_types:
                any_types.append(_TYPE_WORDS[word])
            else:
                return None
    return CardFilter(
        any_types=tuple(any_types),
        excluded_types=tuple(excluded),
        color=color,
        supertype=supertype,
    )


def parse_card_descriptor(text: str) -> CardFilter | None:
    """``a card`` / ``an artifact card`` / ``a nonland card with mana
    value 3 or less`` ... -> ``CardFilter`` (``None`` if unrecognized)."""
    m = _DESCRIPTOR_RE.match(text)
    if m is None:
        return None
    body = m.group("body")
    f = ANY_CARD if body is None else _parse_descriptor_body(body)
    if f is None:
        return None
    if m.group("mv") is not None:
        f = CardFilter(
            any_types=f.any_types, excluded_types=f.excluded_types,
            max_mv=int(m.group("mv")), color=f.color, supertype=f.supertype,
        )
    return f


def parse_permanent_descriptor(text: str) -> CardFilter | None:
    """``a land`` / ``an artifact`` / ``a green creature`` (permanent
    descriptors in sacrifice costs) -> ``CardFilter``."""
    m = _PERMANENT_DESCRIPTOR_RE.match(text)
    if m is None or m.group("body").endswith(" card"):
        return None
    f = _parse_descriptor_body(m.group("body"))
    if f is None or not (f.any_types or f.excluded_types):
        return None
    return f


# ---------------------------------------------------------------------
# Recognizers
# ---------------------------------------------------------------------

_TARGET_PLAYER_DRAWS_RE = re.compile(
    rf"^target player draws (?P<n>{_AMT}) cards?$"
)
_TARGET_PLAYER_EXTRA_TURN_RE = re.compile(
    r"^target player takes an extra turn after this one$"
)
_TARGET_PLAYER_DISCARDS_AT_RANDOM_RE = re.compile(
    rf"^target player discards (?P<n>{_AMT}) cards? at random$"
)
# Thoughtseize / Inquisition / Duress — three printed sentences, with an
# optional trailing sentence (Thoughtseize's "You lose 2 life.") parsed
# recursively.
_REVEAL_HAND_YOU_CHOOSE_DISCARD_RE = re.compile(
    r"^target (?P<who>player|opponent) reveals their hand\. "
    r"[Yy]ou choose (?P<desc>.+?) from it(?P<mv> with mana value \d+ or less)?\. "
    r"[Tt]hat player discards that card(?:\. (?P<rest>.+))?$"
)
_SEARCH_TO_ZONE_RE = re.compile(
    r"^search your library for (?P<desc>.+? card)(?P<reveal>, reveal it)?, "
    r"put (?:that card|it) (?P<dest>into your hand|into your graveyard|"
    r"onto the battlefield), then shuffle$"
)
_SEARCH_TO_TOP_RE = re.compile(
    r"^search your library for (?P<desc>.+? card)(?P<reveal>, reveal it)?, "
    r"then shuffle and put (?:that|the) card on top$"
)
_PUT_FROM_HAND_ON_TOP_RE = re.compile(
    rf"^put (?P<n>{_AMT}) cards? from your hand on top of your library "
    r"in any order$"
)
# Look at / reveal the top N, then a selection sentence (and optionally a
# "put the rest ..." sentence), then optional trailing sentences.
_LOOK_TOP_N_HEAD_RE = re.compile(
    rf"^(?P<verb>look at|reveal) the top (?P<n>{_AMT}) cards of your library"
    r"(?:, where X is (?P<xdef>.+?))?\. (?P<sel>.+)$"
)
_SEL_PUT_K_REST_RE = re.compile(
    rf"^[Pp]ut (?P<k>{_AMT}) of them into your hand and the rest "
    r"(?P<rest>on the bottom of your library in (?:any|a random) order|"
    r"into your graveyard)(?:\. (?P<tail>.+))?$"
)
_SEL_MAY_TAKE_RE = re.compile(
    r"^[Yy]ou may (?:reveal (?P<desc_r>.+? card) from among them and put it "
    r"into your hand|put (?P<desc_p>.+? card) from among them into your hand)"
    r"\. [Pp]ut the rest (?P<rest>on the bottom of your library in "
    r"(?:any|a random) order|into your graveyard)(?:\. (?P<tail>.+))?$"
)
_X_DEFINITION_TWICE_LANDS = "twice the number of lands you control"
_REORDER_TOP_N_RE = re.compile(
    rf"^look at the top (?P<n>{_AMT}) cards of your library, then put them "
    r"back in any order$"
)
_SHUFFLE_RE = re.compile(r"^(?P<may>you may )?shuffle$")
_EACH_PLAYER_THEN_DRAWS_RE = re.compile(
    r"^each player (?P<act>discards their hand|shuffles their hand and "
    r"graveyard into their library), then draws "
    rf"(?P<n>{_AMT}) cards$"
)
_UNTAP_UP_TO_N_LANDS_RE = re.compile(
    rf"^(?:you )?untap up to (?P<n>{_AMT}) lands$"
)
_RETURN_ALL_PERMANENTS_RE = re.compile(
    r"^return all permanents to their owners' hands$"
)
_RETURN_TARGET_SPELL_TO_HAND_RE = re.compile(
    r"^return target spell to its owner's hand$"
)
_SCRY_N_RE = re.compile(r"^scry (?P<n>\d+)$")
_EXILE_THIS_SPELL_RE = re.compile(r"^exile this spell$")
_LOOK_AT_TARGET_PLAYERS_HAND_RE = re.compile(r"^look at target player's hand$")
# ``add {B}{B}{B}`` / ``add {U}{R}`` — any run of three or more colored
# (or colorless) pips. One- and two-pip forms are claimed earlier by the
# pre-existing mana recognizers.
_ADD_MANA_PIPS_RE = re.compile(r"^add (?P<pips>(?:\{[WUBRGC]\}){3,})$")
_ADD_N_MANA_ANY_COMBINATION_RE = re.compile(
    rf"^add (?P<n>{_AMT}) mana in any combination of colors$"
)


def _rest_fields(rest: str) -> tuple[str, bool]:
    if rest == "into your graveyard":
        return "graveyard", False
    return "bottom", rest.endswith("a random order")


def _with_tail(effect: Effect, tail: str | None) -> Effect | None:
    """Sequence ``effect`` with a recursively parsed trailing phrase."""
    if tail is None:
        return effect
    from mtg_bot.cards.base import Sequence
    from mtg_bot.cards.parser.effects import _parse_effect

    tail = tail[0].lower() + tail[1:]
    tail_effect = _parse_effect(tail)
    if tail_effect is None:
        return None
    return Sequence(effects=(effect, tail_effect))


def _parse_look_top_n(m: re.Match) -> Effect | None:
    count = _amount(m.group("n"))
    xdef = m.group("xdef")
    if xdef is not None:
        if m.group("n") != "X" or xdef != _X_DEFINITION_TWICE_LANDS:
            return None
        from mtg_bot.effects.formulas import CountControlledMatching, Scaled
        from mtg_bot.effects.object_predicates import IsLand

        count = Scaled(inner=CountControlledMatching(IsLand()), factor=2)
    elif not isinstance(count, int):
        return None
    reveal = m.group("verb") == "reveal"
    sel = m.group("sel")
    sm = _SEL_PUT_K_REST_RE.match(sel)
    if sm is not None:
        k = _amount(sm.group("k"))
        if not isinstance(k, int):
            return None
        rest_zone, rest_random = _rest_fields(sm.group("rest"))
        eff = LookAtTopCardsPutIntoHand(
            count=count, take=k, reveal=reveal,
            rest_zone=rest_zone, rest_random=rest_random,
        )
        return _with_tail(eff, sm.group("tail"))
    sm = _SEL_MAY_TAKE_RE.match(sel)
    if sm is not None:
        desc = sm.group("desc_r") or sm.group("desc_p")
        f = parse_card_descriptor(desc)
        if f is None:
            return None
        rest_zone, rest_random = _rest_fields(sm.group("rest"))
        eff = LookAtTopCardsPutIntoHand(
            count=count, take=1, take_filter=f, optional=True,
            reveal=reveal, reveal_taken=sm.group("desc_r") is not None,
            rest_zone=rest_zone, rest_random=rest_random,
        )
        return _with_tail(eff, sm.group("tail"))
    return None


def parse_card_flow_effect(phrase: str) -> Effect | None:
    """Dispatch ``phrase`` (normalized) over the card-flow recognizers."""
    m = _TARGET_PLAYER_DRAWS_RE.match(phrase)
    if m is not None:
        return TargetPlayerDraws(amount=_amount(m.group("n")))
    if _TARGET_PLAYER_EXTRA_TURN_RE.match(phrase) is not None:
        return TargetPlayerTakesExtraTurn()
    m = _TARGET_PLAYER_DISCARDS_AT_RANDOM_RE.match(phrase)
    if m is not None:
        return TargetPlayerDiscardsAtRandom(amount=_amount(m.group("n")))
    m = _REVEAL_HAND_YOU_CHOOSE_DISCARD_RE.match(phrase)
    if m is not None:
        desc = m.group("desc")
        if m.group("mv") is not None:
            desc += m.group("mv")
        f = parse_card_descriptor(desc)
        if f is None:
            return None
        eff = TargetPlayerRevealsHandYouChooseDiscard(
            card_filter=f, opponent_only=m.group("who") == "opponent",
        )
        return _with_tail(eff, m.group("rest"))
    m = _SEARCH_TO_ZONE_RE.match(phrase)
    if m is not None:
        f = parse_card_descriptor(m.group("desc"))
        if f is None:
            return None
        dest = {
            "into your hand": "hand",
            "into your graveyard": "graveyard",
            "onto the battlefield": "battlefield",
        }[m.group("dest")]
        return SearchLibrary(
            card_filter=f, destination=dest, reveal=m.group("reveal") is not None,
        )
    m = _SEARCH_TO_TOP_RE.match(phrase)
    if m is not None:
        f = parse_card_descriptor(m.group("desc"))
        if f is None:
            return None
        return SearchLibrary(
            card_filter=f, destination="top", reveal=m.group("reveal") is not None,
        )
    m = _PUT_FROM_HAND_ON_TOP_RE.match(phrase)
    if m is not None:
        n = _amount(m.group("n"))
        if not isinstance(n, int):
            return None
        return PutCardsFromHandOnTopOfLibrary(amount=n)
    m = _REORDER_TOP_N_RE.match(phrase)
    if m is not None:
        n = _amount(m.group("n"))
        if not isinstance(n, int):
            return None
        return ReorderTopCards(count=n)
    m = _LOOK_TOP_N_HEAD_RE.match(phrase)
    if m is not None:
        return _parse_look_top_n(m)
    m = _SHUFFLE_RE.match(phrase)
    if m is not None:
        return ShuffleYourLibrary(optional=m.group("may") is not None)
    m = _EACH_PLAYER_THEN_DRAWS_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.base import EachPlayerDraws, Sequence

        n = _amount(m.group("n"))
        if not isinstance(n, int):
            return None
        first: Effect = (
            EachPlayerDiscardsHand()
            if m.group("act") == "discards their hand"
            else EachPlayerShufflesZonesIntoLibrary(zones=("hand", "graveyard"))
        )
        return Sequence(effects=(first, EachPlayerDraws(amount=n)))
    m = _UNTAP_UP_TO_N_LANDS_RE.match(phrase)
    if m is not None:
        n = _amount(m.group("n"))
        if not isinstance(n, int):
            return None
        return UntapUpToNLands(amount=n)
    if _RETURN_ALL_PERMANENTS_RE.match(phrase) is not None:
        return ReturnAllPermanentsToOwnersHands()
    if _RETURN_TARGET_SPELL_TO_HAND_RE.match(phrase) is not None:
        return ReturnTargetSpellToOwnersHand()
    m = _SCRY_N_RE.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.library_lookat import Scry

        return Scry(amount=int(m.group("n")), bottom_choice=True)
    if _EXILE_THIS_SPELL_RE.match(phrase) is not None:
        return ExileThisSpell()
    if _LOOK_AT_TARGET_PLAYERS_HAND_RE.match(phrase) is not None:
        return LookAtTargetPlayersHand()
    m = _ADD_MANA_PIPS_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.base import AddManaToPool

        counts: dict[str, int] = {}
        for c in re.findall(r"\{([WUBRGC])\}", m.group("pips")):
            counts[c] = counts.get(c, 0) + 1
        return AddManaToPool(produces=tuple(counts.items()))
    m = _ADD_N_MANA_ANY_COMBINATION_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.base import AddManaToPool

        n = _amount(m.group("n"))
        if not isinstance(n, int):
            return None
        return AddManaToPool(produces=(("any", n),))
    return None
