"""Lines of the Forgetful Fish cards (pool ``fish``) the other grammars
don't claim. Effects live in ``mtg_bot.effects.generic.fish_cards``.

Creature lines (Dandân):

* ``This creature can't attack unless defending player controls an
  <basic land type>.`` -> a ``CantAttackUnless`` board rule.
* ``When you control no <basic land type>s, <effect>.`` -> a state
  trigger (CR 603.8) on ``YouControlNoLandType``.

Both keep the land type as a word the text-changing effects rewrite.
"""

from __future__ import annotations

import re

_SELF = r"(?:this creature|{name})"
_LAND = r"(?P<type>Plains|Island|Swamp|Mountain|Forest)"
_LANDS = r"(?P<types>Plains|Islands|Swamps|Mountains|Forests)"


def _singular(plural: str) -> str:
    return plural if plural == "Plains" else plural[:-1]


def _cant_attack_unless_defender_controls(line: str, name: str):
    from mtg_bot.effects.generic.fish_cards import (
        CantAttackUnless, DefendingPlayerControlsNoLandType,
    )

    m = re.fullmatch(
        _SELF.format(name=re.escape(name))
        + r" can't attack unless defending player controls an? " + _LAND + r"\.",
        line.strip(), flags=re.IGNORECASE,
    )
    if m is None:
        return None
    rule = CantAttackUnless(
        condition=DefendingPlayerControlsNoLandType(m.group("type").capitalize()),
        self_only=True,
    )
    return {"board_rules": (rule,)}


def _when_you_control_no_land_type(line: str, name: str):
    from mtg_bot import roto_board_statics as rs
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.cards.parser.triggers import _substitute_self_name
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.fish_cards import YouControlNoLandType

    m = re.fullmatch(
        r"When you control no " + _LANDS + r", (?P<eff>.+)\.", line.strip(),
    )
    if m is None:
        return None
    effect = _parse_effect(_substitute_self_name(m.group("eff"), name))
    if effect is None:
        return None
    return {"board_rules": (rs.StateTrigger(
        condition=YouControlNoLandType(_singular(m.group("types"))),
        ability=TriggeredAbility(effect=effect),
    ),)}


_CREATURE_PARSERS = (_cant_attack_unless_defender_controls, _when_you_control_no_land_type)


def parse_fish_creature_line(line: str, name: str) -> dict | None:
    """The printing fields ``line`` contributes to a creature, or ``None``
    when no Fish recognizer claims it."""
    for parse in _CREATURE_PARSERS:
        out = parse(line, name)
        if out is not None:
            return out
    return None


# ---------------------------------------------------------------------------
# Effect phrases (the last ``_parse_effect`` fallback)
# ---------------------------------------------------------------------------

# "draw cards equal to the number of cards named <name> in all graveyards"
# (Accumulated Knowledge; "all graveyards" = every distinct graveyard, the
# shared one once in Fish).
_DRAW_PER_NAMED_IN_GRAVEYARDS = re.compile(
    r"draw cards equal to the number of cards named (?P<name>.+?) in "
    r"(?:all|each) graveyards?"
)


def _draw_per_named_in_graveyards(phrase: str):
    from mtg_bot.effects.generic.roto_mana import CardsNamedInAllGraveyards
    from mtg_bot.effects.generic.roto_walkers import DrawCardsEqualTo

    m = _DRAW_PER_NAMED_IN_GRAVEYARDS.fullmatch(phrase)
    if m is None:
        return None
    return DrawCardsEqualTo(count=CardsNamedInAllGraveyards(m.group("name")))


_NUMBER = r"(?P<{g}>a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _n(token: str) -> int:
    return _NUMBERS[token] if token in _NUMBERS else int(token)


# "choose a card name, then target player mills N cards. If a card with
# the chosen name was milled this way, you draw X cards. Otherwise, you
# draw Y cards" (Predict).
_NAME_MILL_DRAW = re.compile(
    r"choose a card name, then target player mills " + _NUMBER.format(g="mill")
    + r" cards?\. If a card with the chosen name was milled this way, you draw "
    + _NUMBER.format(g="hit") + r" cards?\. Otherwise, you draw "
    + _NUMBER.format(g="miss") + r" cards?"
)


def _name_mill_draw(phrase: str):
    from mtg_bot.effects.generic.fish_cards import NameThenMillDrawOnHit

    m = _NAME_MILL_DRAW.fullmatch(phrase)
    if m is None:
        return None
    return NameThenMillDrawOnHit(
        mill=_n(m.group("mill")), hit=_n(m.group("hit")), miss=_n(m.group("miss")),
    )


# "look at the top N cards of target player's library, then put them back
# in any order[. You may have that player shuffle]" (Portent).
_REORDER_TARGET_TOP = re.compile(
    r"look at the top " + _NUMBER.format(g="n") + r" cards of target player's "
    r"library, then put them back in any order(?P<shuffle>\. You may have that "
    r"player shuffle)?"
)


def _reorder_target_top(phrase: str):
    from mtg_bot.effects.generic.fish_cards import ReorderTargetPlayersTopCards

    m = _REORDER_TARGET_TOP.fullmatch(phrase)
    if m is None:
        return None
    return ReorderTargetPlayersTopCards(
        count=_n(m.group("n")), may_shuffle=m.group("shuffle") is not None,
    )


# Ray of Command. Literal: the only card in the pools with this shape
# (Threaten's sentences in another order plus a lose-control rider);
# broader grammar deferred until a second example exists.
_RAY_OF_COMMAND = (
    "untap target creature an opponent controls and gain control of it until "
    "end of turn. That creature gains haste until end of turn. When you lose "
    "control of the creature, tap it"
)


def _ray_of_command(phrase: str):
    from mtg_bot.effects.generic.fish_cards import UntapGainControlHasteTapWhenLost

    return UntapGainControlHasteTapWhenLost() if phrase == _RAY_OF_COMMAND else None


# Supplant Form. Literal: the only card in the pools with this shape;
# broader grammar (other bounce-then-copy nouns) deferred until a second
# example exists.
_SUPPLANT_FORM = (
    "return target creature to its owner's hand. You create a token that's "
    "a copy of that creature"
)


def _supplant_form(phrase: str):
    from mtg_bot.effects.generic.fish_cards import BounceTargetThenTokenCopy

    return BounceTargetThenTokenCopy() if phrase == _SUPPLANT_FORM else None


# "put target permanent an opponent controls on top of its owner's library.
# That opponent may put an <type>, <type>, or <type> card from their hand
# onto the battlefield" (Metamorphose).
_TUCK_THEY_MAY_PUT = re.compile(
    r"put target permanent an opponent controls on top of its owner's "
    r"library\. That opponent may put an? (?P<types>[a-z, ]+?) card from "
    r"their hand onto the battlefield"
)
_CARD_TYPE_WORDS = {"artifact", "creature", "enchantment", "land", "planeswalker"}


def _tuck_they_may_put(phrase: str):
    from mtg_bot.effects.generic.fish_cards import TuckOpponentsPermanentTheyMayPutOne

    m = _TUCK_THEY_MAY_PUT.fullmatch(phrase)
    if m is None:
        return None
    words = [w for w in re.split(r",? or |, ", m.group("types")) if w]
    if not words or any(w not in _CARD_TYPE_WORDS for w in words):
        return None
    return TuckOpponentsPermanentTheyMayPutOne(
        card_types=tuple(w.capitalize() for w in words),
    )


# "until end of turn, target creature you control becomes a <color>
# <Subtypes> with base power and toughness P/T, loses all abilities, and
# gains <keyword>" (Dance of the Skywise).
_COLOR_LETTERS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_BECOMES_UEOT = re.compile(
    r"until end of turn, target creature you control becomes an? "
    r"(?P<color>white|blue|black|red|green) (?P<subs>[A-Z][a-z]+(?: [A-Z][a-z]+)*) "
    r"with base power and toughness (?P<p>\d+)/(?P<t>\d+)"
    r"(?P<lose>, loses all abilities)?,? and gains (?P<kw>[a-z]+)"
)


def _becomes_ueot(phrase: str):
    from mtg_bot.cards.parser.keywords import _parse_keyword_line
    from mtg_bot.effects.generic.fish_cards import TargetYouControlBecomesUEOT

    m = _BECOMES_UEOT.fullmatch(phrase)
    if m is None:
        return None
    kws = _parse_keyword_line(m.group("kw").capitalize())
    if not kws or len(kws) != 1:
        return None
    return TargetYouControlBecomesUEOT(
        colors=frozenset({_COLOR_LETTERS[m.group("color")]}),
        creature_subtypes=tuple(m.group("subs").split(" ")),
        base_pt=(int(m.group("p")), int(m.group("t"))),
        lose_all_abilities=bool(m.group("lose")),
        keywords=(kws[0],),
    )


# "change the text of target [spell or ]permanent by replacing all
# instances of one color word with another or one basic land type with
# another[ until end of turn]" (Mind Bend, Crystal Spray; Mind Bend's
# reminder text is stripped before effect parsing).
_CHANGE_TEXT = re.compile(
    r"change the text of target (?P<what>spell or permanent|permanent) by "
    r"replacing all instances of one color word with another or one basic "
    r"land type with another(?P<eot> until end of turn)?"
)


def _change_text(phrase: str):
    from mtg_bot.effects.generic.fish_cards import ChangeTextOfTarget

    m = _CHANGE_TEXT.fullmatch(phrase)
    if m is None:
        return None
    return ChangeTextOfTarget(
        spells=m.group("what") == "spell or permanent",
        until_end_of_turn=m.group("eot") is not None,
    )


# Vision Charm's modes. Literals: the only cards in the pools with these
# shapes; broader grammar deferred until a second example exists.
_LAND_TYPE_SWAP = (
    "choose a land type and a basic land type. Each land of the first chosen "
    "type becomes the second chosen type until end of turn"
)


def _land_type_swap(phrase: str):
    from mtg_bot.effects.generic.fish_cards import LandsOfChosenTypeBecomeBasicTypeUEOT

    return LandsOfChosenTypeBecomeBasicTypeUEOT() if phrase == _LAND_TYPE_SWAP else None


def _artifact_phases_out(phrase: str):
    from mtg_bot.effects.generic.fish_cards import TargetArtifactPhasesOut

    return TargetArtifactPhasesOut() if phrase == "target artifact phases out" else None


# "each player shuffles their hand and graveyard into their library. You
# exile the top N cards of your library. Then each player draws up to M
# cards" (Diminishing Returns): Timetwister's shuffle, then the exile,
# then the optional draws.
_SHUFFLE_EXILE_DRAW_UP_TO = re.compile(
    r"each player shuffles their hand and graveyard into their library\. You "
    r"exile the top " + _NUMBER.format(g="exile") + r" cards of your library\. "
    r"Then each player draws up to " + _NUMBER.format(g="draw") + r" cards"
)


def _shuffle_exile_draw_up_to(phrase: str):
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.card_flow import EachPlayerShufflesZonesIntoLibrary
    from mtg_bot.effects.generic.fish_cards import EachPlayerDrawsUpTo
    from mtg_bot.effects.generic.roto_mana import ExileTopCardsOfYourLibrary

    m = _SHUFFLE_EXILE_DRAW_UP_TO.fullmatch(phrase)
    if m is None:
        return None
    return Sequence(effects=(
        EachPlayerShufflesZonesIntoLibrary(),
        ExileTopCardsOfYourLibrary(count=_n(m.group("exile"))),
        EachPlayerDrawsUpTo(amount=_n(m.group("draw"))),
    ))


_EFFECT_PARSERS = (
    _draw_per_named_in_graveyards, _name_mill_draw, _reorder_target_top, _ray_of_command,
    _supplant_form, _tuck_they_may_put, _becomes_ueot, _change_text, _land_type_swap,
    _artifact_phases_out, _shuffle_exile_draw_up_to,
)


def parse_fish_effect(phrase: str):
    """An ``Effect`` for a Fish-only effect phrase, or ``None``."""
    for parse in _EFFECT_PARSERS:
        eff = parse(phrase)
        if eff is not None:
            return eff
    return None
