"""Parser recognizers for the Vintage Roto P4 package: planeswalkers,
copies, control changes and turn structure.

Every hook here is a *last* fallback of the shared grammar it extends
(``effects._parse_effect``, ``statics._parse_static_ability_line``, the
planeswalker builder), so no phrase an older recognizer claims changes
meaning. Like the cube buckets, the grammar is switched off for
printings that exist only in the EoE-era dumps (the shared
``creature_rmc_grammar`` switch), so no EoE printing's parse can
change. Engine effects live in ``effects/generic/roto_walkers.py`` and
the turn-structure rules in ``mtg_bot.roto_turns``.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import StaticAbility, StaticScope


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


# ---------------------------------------------------------------------------
# Statics
# ---------------------------------------------------------------------------

# "Skip your draw step." (Necropotence, Yawgmoth's Bargain; CR 614.10).
_SKIP_DRAW_STEP_LINE = "Skip your draw step."


def parse_roto_static_line(line: str) -> tuple[StaticAbility, ...]:
    """``StaticAbility`` tuple for a static line the shared static
    grammar declined, or ``()``."""
    if _disabled():
        return ()
    if line == _SKIP_DRAW_STEP_LINE:
        return (StaticAbility(
            scope=StaticScope.SELF, skips_your_draw_step=True,
        ),)
    return ()


# ---------------------------------------------------------------------------
# Effect phrases (last fallback of ``effects._parse_effect``)
# ---------------------------------------------------------------------------

_CARDINALS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_N = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)"


def _n(token: str) -> int:
    return int(token) if token.isdigit() else _CARDINALS[token]


# "exile the top [<N>] card(s) of your library[ face down]. Put that card
# / them into your hand at the beginning of your next end step"
# (Necropotence).
_EXILE_TOP_TO_HAND_AT_NEXT_END_STEP_RE = re.compile(
    rf"^exile the top (?:(?P<n>{_N}) )?cards? of your library"
    r"(?P<down> face down)?\. Put (?:that card|them|it) into your hand at "
    r"the beginning of your next end step$"
)


# "if it's your turn, <effect>" (Day's Undoing).
_IF_YOUR_TURN_RE = re.compile(r"^if it's your turn, (?P<eff>.+)$")
# "take an extra turn after this one. At the beginning of that turn's end
# step, <effect>" (Final Fortune).
_EXTRA_TURN_THEN_END_STEP_RE = re.compile(
    r"^take an extra turn after this one\. At the beginning of that turn's "
    r"end step, (?P<eff>.+)$"
)


# "you may reveal <a card descriptor> you own from outside the game and
# put it into your hand" (Burning Wish; the wishes).
_WISH_RE = re.compile(
    r"^you may reveal (?P<desc>an? .+? card) you own from outside the game "
    r"and put it into your hand$"
)


def parse_roto_effect(phrase: str):
    """``Effect`` for a normalized phrase every older grammar declined,
    or ``None``."""
    if _disabled():
        return None
    from mtg_bot.effects.generic import roto_walkers as rw

    from mtg_bot.cards.parser.effects import _parse_effect

    if phrase == "end the turn":
        return rw.EndTheTurn()
    if phrase == "you lose the game":
        return rw.LoseTheGame()
    m = _IF_YOUR_TURN_RE.match(phrase)
    if m is not None:
        from mtg_bot.effects.combinators import IfConditionElse
        from mtg_bot.effects.conditions import DuringYourTurn

        inner = _parse_effect(m.group("eff"))
        if inner is None or inner.requires_target():
            return None
        return IfConditionElse(condition=DuringYourTurn(), then_effect=inner)
    m = _EXTRA_TURN_THEN_END_STEP_RE.match(phrase)
    if m is not None:
        inner = _parse_effect(m.group("eff"))
        if inner is None or inner.requires_target():
            return None
        return rw.TakeExtraTurnWithEndStepTrigger(inner=inner)
    m = _WISH_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor

        card_filter = parse_card_descriptor(m.group("desc"))
        if card_filter is None:
            return None
        return rw.PutCardFromOutsideTheGameIntoHand(card_filter=card_filter)
    m = _EXILE_TOP_TO_HAND_AT_NEXT_END_STEP_RE.match(phrase)
    if m is not None:
        return rw.ExileTopCardsToHandAtYourNextEndStep(
            count=_n(m.group("n")) if m.group("n") else 1,
            face_down=bool(m.group("down")),
        )
    return None
