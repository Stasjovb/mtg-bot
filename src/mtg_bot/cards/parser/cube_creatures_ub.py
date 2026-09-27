"""Oracle grammar for the PowerLSV cube's blue / black creatures.

Parameterized recognizers for shapes the U/B creature bucket
introduced: draw-observer trigger conditions ("whenever an opponent
draws a card [except the first one they draw in each of their draw
steps]", "... draws their second card each turn"), Amass, and friends.
Each entry point returns ``None`` for text it doesn't own so the
callers' fall-through order is unchanged.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect

_ORDINALS = {"second": 2, "third": 3, "fourth": 4}

# "<who> draws a card[ except the first one they draw in each of their
# draw steps]" / "<who> draws their <ordinal> card each turn"
_DRAWS_TRIGGER = re.compile(
    r"^(?P<who>you|an opponent|a player) draws? "
    r"(?:(?P<a>a card)(?P<except> except the first one (?:they|you) draw "
    r"in each of (?:their|your) draw steps)?"
    r"|(?:their|your) (?P<ord>second|third|fourth) card each turn)$"
)


_COMBAT_DAMAGE_TO_PLAYER_OR_PW = (
    "this creature deals combat damage to a player or planeswalker"
)


def parse_ub_trigger_phrase(phrase: str):
    """``(Event, Predicate)`` for the draw-observer conditions and the
    player-or-planeswalker combat-damage condition, else ``None``.
    Plain "you draw a card" stays with the pre-existing phrasebook
    (``effects_ext``), which is consulted first."""
    from mtg_bot.effects.object_predicates import (
        DrawIsFirstInOwnDrawStep,
        HasDrawnNCardsThisTurn,
        IsPlaneswalker,
        IsPlayer,
    )
    from mtg_bot.effects.predicates import (
        OPPONENT, YOU, Always, Controlled, Event, IsSelf, Subject,
    )

    if phrase == _COMBAT_DAMAGE_TO_PLAYER_OR_PW:
        return (
            Event.DEALS_COMBAT_DAMAGE,
            IsSelf(subject="source")
            & Subject("target", IsPlayer() | IsPlaneswalker()),
        )
    m = _DRAWS_TRIGGER.match(phrase)
    if m is None:
        return None
    who = m.group("who")
    if who == "you":
        pred = Controlled(YOU, subject="player")
    elif who == "an opponent":
        pred = Controlled(OPPONENT, subject="player")
    else:
        pred = Always()
    if m.group("except"):
        pred = pred & Subject("player", ~DrawIsFirstInOwnDrawStep())
    if m.group("ord"):
        pred = pred & Subject(
            "player", HasDrawnNCardsThisTurn(_ORDINALS[m.group("ord")]),
        )
    return (Event.DRAWS_CARD, pred)


# Effects whose "they" / "that player" reads ``targets[0]`` as the
# player; on a player-subject event the parser binds that player from
# the event (``BindEventPlayer``).
def bind_event_player_anaphora(event, effect: Effect) -> Effect:
    from mtg_bot.effects.generic.cube_creatures_ub import BindEventPlayer
    from mtg_bot.effects.generic.life import TargetPlayerLosesLife
    from mtg_bot.effects.predicates import Event

    if event is Event.DRAWS_CARD and isinstance(effect, TargetPlayerLosesLife):
        return BindEventPlayer(inner=effect)
    return effect


_AMASS = re.compile(r"^amass (?P<type>[A-Z][a-z]+?)s? (?P<n>\d+)$")
# "<sentence about this creature>. Tap it." -- "it" is the source.
_SELF_SENTENCE_THEN_TAP_IT = re.compile(
    r"^(?P<first>this creature [^.]+)\. [Tt]ap it$"
)
_REVEAL_TOP_TO_HAND_LOSE_MV = re.compile(
    r"^reveal the top card of your library and put (?:that card|it) into "
    r"your hand\. [Yy]ou lose life equal to (?:its|that card's) mana value$"
)


def parse_ub_effect(phrase: str) -> Effect | None:
    """Effect phrases introduced by the U/B creature bucket."""
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.cube_creatures_ub import (
        Amass,
        RevealTopCardToHandLoseLifeEqualMV,
        TapSelf,
    )

    m = _AMASS.match(phrase)
    if m is not None:
        return Amass(subtype=m.group("type"), amount=int(m.group("n")))
    m = _SELF_SENTENCE_THEN_TAP_IT.match(phrase)
    if m is not None:
        first = _parse_effect(m.group("first"))
        if first is not None and not first.requires_target():
            return Sequence(effects=(first, TapSelf()))
        return None
    if _REVEAL_TOP_TO_HAND_LOSE_MV.match(phrase):
        return RevealTopCardToHandLoseLifeEqualMV()
    return None


# ---------------------------------------------------------------------------
# Creature-line hook
# ---------------------------------------------------------------------------


class UBLine:
    """What one oracle line contributes to a creature printing: ability
    tuples the builder appends, plus ``fields`` -- printing-level
    attributes (``dataclasses.replace`` onto the built ``CardPrinting``)
    for keyword mechanics that live on the printing rather than on an
    ability (Ninjutsu, Emerge, ...)."""

    __slots__ = (
        "keywords", "triggers", "activated", "statics", "hand_abilities",
        "fields",
    )

    def __init__(
        self, *, keywords=(), triggers=(), activated=(), statics=(),
        hand_abilities=(), fields=None,
    ):
        self.keywords = tuple(keywords)
        self.triggers = tuple(triggers)
        self.activated = tuple(activated)
        self.statics = tuple(statics)
        self.hand_abilities = tuple(hand_abilities)
        self.fields = dict(fields or {})


# "If <who> would draw a card[ except ...], instead <effect>."
_DRAW_REPLACEMENT = re.compile(
    r"^If (?P<who>an opponent|you) would draw a card"
    r"(?P<except> except the first one (?:they|you) draw in each of "
    r"(?:their|your) draw steps)?, instead (?P<effect>.+)\.$"
)


def _parse_draw_replacement_line(line: str) -> UBLine | None:
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.modifiers import (
        EventPattern, InsteadForSourceController, ReplacementEffect,
    )
    from mtg_bot.effects.object_predicates import DrawIsFirstInOwnDrawStep
    from mtg_bot.effects.predicates import Event

    m = _DRAW_REPLACEMENT.match(line)
    if m is None:
        return None
    body = m.group("effect")
    effect = _parse_effect(body)
    if effect is None and body.startswith("you "):
        effect = _parse_effect(body[len("you "):])
    if effect is None or effect.requires_target():
        return None
    filters = {}
    if m.group("except"):
        filters["player"] = ~DrawIsFirstInOwnDrawStep()
    return UBLine(statics=(StaticAbility(
        scope=StaticScope.SELF,
        replacement_effect=ReplacementEffect(
            event_pattern=EventPattern(
                event=Event.WOULD_DRAW_A_CARD, subject_filters=filters,
            ),
            transform=InsteadForSourceController(effect=effect),
            affects="opponents" if m.group("who") == "an opponent" else "you",
        ),
    ),))


def _parse_hand_ability_line(line: str) -> UBLine | None:
    """``{cost}, Discard this card: <effect>.`` -- an ability that
    functions only from its owner's hand (Harvester of Misery). Routed
    to ``CardPrinting.hand_activated_abilities``."""
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ability = _parse_activated_ability_line(line, from_hand=True)
    if ability is None:
        return None
    return UBLine(hand_abilities=(ability,))


_MIN_BLOCKERS = re.compile(
    r"^This creature can't be blocked except by (?P<n>two|three|four) or "
    r"more creatures\.$"
)
_SMALL_NUMBERS = {"two": 2, "three": 3, "four": 4}


def _parse_min_blockers_line(line: str) -> UBLine | None:
    m = _MIN_BLOCKERS.match(line)
    if m is None:
        return None
    return UBLine(fields={"min_blockers": _SMALL_NUMBERS[m.group("n")]})


_LINE_PARSERS = (
    _parse_draw_replacement_line,
    _parse_hand_ability_line,
    _parse_min_blockers_line,
)


def parse_ub_creature_line(line: str, name: str) -> UBLine | None:
    """Try every U/B-bucket creature-line recognizer on ``line``."""
    for parser in _LINE_PARSERS:
        out = parser(line)
        if out is not None:
            return out
    return None
