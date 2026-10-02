"""Roto package P6 grammar: keyword mechanics, face-changing & pregame.

Line recognizers for the Vintage Roto cards P6 claims
(``docs/ROTO_COVERAGE_PLAN.md`` section 6). Recognizers are
parameterized over the printed shape (the two literals say why); the
engine side lives in ``mtg_bot.conspiracies`` and
``mtg_bot.opening_hand``.

Entry points, each called from one hook:

* :func:`parse_conspiracy_rule_line` -- ``conspiracy_builder`` (CR 313):
  "You are the starting player. ..." (Power Play), "Your minimum deck
  size is reduced|increased by <N>." (Advantageous Proclamation).
* :func:`build_with_p6_lines` -- ``source.build_card_record``:
  printing-level lines peeled off before the per-type builders run (like
  the cycling family) and attached to the built printing -- pregame
  actions (``opening_hand_action``: Chancellor of the Tangle's
  opening-hand reveal, Serum Powder's mulligan-window exchange).
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Callable

from mtg_bot.conspiracies import MinimumDeckSizeChange, YouAreTheStartingPlayer
from mtg_bot.opening_hand import ExchangeHandWhileMulliganing, RevealFromOpeningHand

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def number_word(text: str) -> int | None:
    """``"five"`` / ``"5"`` -> 5; ``None`` for anything else."""
    if text.isdigit():
        return int(text)
    return _NUMBER_WORDS.get(text.lower())


# ── Conspiracy rules (CR 313) ──────────────────────────────────────────

_STARTING_PLAYER_LINE = (
    "You are the starting player. If multiple players would be the "
    "starting player, one of those players is chosen at random."
)
_MINIMUM_DECK_SIZE_RE = re.compile(
    r"^Your minimum deck size is (?P<dir>reduced|increased) by "
    r"(?P<n>\w+)\.$"
)


def parse_conspiracy_rule_line(line: str):
    """The conspiracy rule a (reminder-stripped) line states, or
    ``None``. The deck-size line is parameterized over direction and
    amount. The starting-player sentence pair is a literal: Power Play
    is the only card in the pool with it and the text has no variable
    part; a broader grammar is deferred until a second example exists
    (parser CLAUDE.md single-card exception)."""
    line = line.strip()
    if line == _STARTING_PLAYER_LINE:
        return YouAreTheStartingPlayer()
    m = _MINIMUM_DECK_SIZE_RE.match(line)
    if m is not None:
        n = number_word(m.group("n"))
        if n is None:
            return None
        return MinimumDeckSizeChange(-n if m.group("dir") == "reduced" else n)
    return None


# ── Pregame lines (CR 103.5 mulligan window, CR 103.6) ─────────────────

_REVEAL_FROM_OPENING_HAND_RE = re.compile(
    r"^You may reveal this card from your opening hand\. If you do, at "
    r"the beginning of your first main phase of the game, (?P<effect>.+)\.$"
)
# Literal: Serum Powder is the only card in the pool with a mulligan-
# window action, and the sentence has no variable part; a broader
# grammar is deferred until a second example exists.
_EXCHANGE_HAND_WHILE_MULLIGANING_LINE = (
    "Any time you could mulligan and this card is in your hand, you may "
    "exile all the cards from your hand, then draw that many cards."
)


def parse_pregame_line(line: str, card_name: str):
    """The pregame action a reminder-stripped line states, or ``None``."""
    line = line.strip()
    if line == _EXCHANGE_HAND_WHILE_MULLIGANING_LINE:
        return ExchangeHandWhileMulliganing()
    m = _REVEAL_FROM_OPENING_HAND_RE.match(line)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_spell_effect_phrase

        effect = _parse_spell_effect_phrase(m.group("effect") + ".", card_name)
        if effect is None or effect.requires_target():
            return None
        return RevealFromOpeningHand(effect)
    return None


# ── The printing-line pre-pass ─────────────────────────────────────────

def _attach_opening_hand_action(printing, action):
    if printing.opening_hand_action is not None:
        return None  # one opening-hand slot: two such lines aren't claimed
    return replace(printing, opening_hand_action=action)


def _line_patch(line: str, card: dict):
    """A ``CardPrinting -> CardPrinting | None`` patch for a P6
    printing-level line, or ``None`` when the line isn't one."""
    action = parse_pregame_line(line, card["name"])
    if action is not None:
        return lambda p: _attach_opening_hand_action(p, action)
    return None


def _split_p6_lines(card: dict) -> tuple[dict, list]:
    """``(card without its P6 printing-level lines, [patches])``. Lands
    (``land_lines`` parses their keyword lines itself) and multi-face
    records are left untouched."""
    from mtg_bot.cards.parser.text import _strip_reminder_text

    text = card.get("oracle_text")
    if (
        not text or card.get("card_faces")
        or "Land" in card.get("type_line", "")
    ):
        return card, []
    kept: list[str] = []
    patches = []
    for raw in text.split("\n"):
        patch = _line_patch(_strip_reminder_text(raw), card)
        if patch is None:
            kept.append(raw)
        else:
            patches.append(patch)
    if not patches:
        return card, []
    stripped = dict(card)
    stripped["oracle_text"] = "\n".join(kept)
    return stripped, patches


def build_with_p6_lines(card: dict, build: Callable[[dict], object]):
    """Build ``card`` with ``build`` after peeling off its P6 printing-
    level lines (pregame actions), then apply each line's patch. Any patch refusing (``None``) leaves the card
    unclaimed."""
    body, patches = _split_p6_lines(card)
    built = build(body)
    for patch in patches:
        if built is None:
            return None
        built = patch(built)
    return built


__all__ = [
    "build_with_p6_lines",
    "number_word",
    "parse_conspiracy_rule_line",
    "parse_pregame_line",
]
