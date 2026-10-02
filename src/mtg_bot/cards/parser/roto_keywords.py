"""Roto package P6 grammar: keyword mechanics, face-changing & pregame.

Line recognizers for the Vintage Roto cards P6 claims
(``docs/ROTO_COVERAGE_PLAN.md`` section 6). Recognizers are
parameterized over the printed shape (the two literals say why); the
engine side lives in ``mtg_bot.conspiracies``, ``mtg_bot.opening_hand``
and ``mtg_bot.effects.generic.roto_keywords``.

Entry points, each called from one hook:

* :func:`parse_conspiracy_rule_line` -- ``conspiracy_builder`` (CR 313):
  "You are the starting player. ..." (Power Play), "Your minimum deck
  size is reduced|increased by <N>." (Advantageous Proclamation).
* :func:`build_with_p6_lines` -- ``source.build_card_record``:
  printing-level lines peeled off before the per-type builders run (like
  the cycling family) and attached to the built printing -- pregame
  actions (``opening_hand_action``: Chancellor of the Tangle's
  opening-hand reveal, Serum Powder's mulligan-window exchange) and hand
  keyword abilities (Transmute).
* :func:`parse_hand_keyword_line` -- also ``land_lines`` (Tolaria West).
* :func:`parse_p6_effect` -- last in ``effects._parse_effect``.
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


# ── Effect phrases (hooked last into ``effects._parse_effect``) ─────────

_CARD_TYPE_WORDS = {
    "artifact": "Artifact", "creature": "Creature", "enchantment": "Enchantment",
    "instant": "Instant", "land": "Land", "planeswalker": "Planeswalker",
    "sorcery": "Sorcery",
}
_LOOK_MAY_REVEAL_RE = re.compile(
    r"^look at the top card of your library\. you may reveal that card\. "
    r"if an? (?P<types>[a-z]+(?: or [a-z]+)*) card is revealed this way, "
    r"(?P<then>.+)$",
    re.IGNORECASE,
)


def _card_types_phrase(text: str) -> tuple[str, ...] | None:
    """``"instant or sorcery"`` -> ``("Instant", "Sorcery")``."""
    words = text.lower().split(" or ")
    if not all(w in _CARD_TYPE_WORDS for w in words):
        return None
    return tuple(_CARD_TYPE_WORDS[w] for w in words)


def parse_p6_effect(phrase: str):
    """A normalized effect phrase (lowercased first letter, no final
    period) the P6 grammar models, else ``None``."""
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.generic.card_flow import CardFilter
    from mtg_bot.effects.generic.roto_keywords import LookAtTopMayRevealIfMatches

    m = _LOOK_MAY_REVEAL_RE.match(phrase)
    if m is not None:
        types = _card_types_phrase(m.group("types"))
        then = _parse_effect(m.group("then"))
        if types is None or then is None or then.requires_target():
            return None
        return LookAtTopMayRevealIfMatches(
            card_filter=CardFilter(any_types=types), then=then,
        )
    return None


# ── Hand keyword lines (abilities that work from the hand) ─────────────

_TRANSMUTE_RE = re.compile(r"^Transmute (?P<cost>(?:\{[^}]+\})+)$")


def parse_hand_keyword_line(line: str, card: dict):
    """The hand-activated ``ActivatedAbility`` a keyword line states, or
    ``None``.

    Transmute {cost} (CR 702.53): "{cost}, Discard this card: Search
    your library for a card with the same mana value as the discarded
    card, reveal it, put it into your hand, then shuffle. Transmute only
    as a sorcery." The discarded card is this card, so its mana value is
    the printed one."""
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost, parse_mana_cost
    from mtg_bot.effects.generic.card_flow import SearchLibrary
    from mtg_bot.effects.generic.roto_keywords import ManaValueCardFilter

    m = _TRANSMUTE_RE.match(line.strip())
    if m is not None:
        cost_str = m.group("cost")
        mana_value = parse_mana_cost(card.get("mana_cost") or "").total
        return ActivatedAbility(
            cost=ActivationCost(
                mana=parse_mana_cost(cost_str),
                mana_str=cost_str,
                discard_self=True,
            ),
            effect=SearchLibrary(
                card_filter=ManaValueCardFilter(mana_value=mana_value),
                destination="hand",
                reveal=True,
            ),
            sorcery_speed=True,
        )
    return None


# ── The printing-line pre-pass ─────────────────────────────────────────

def _attach_opening_hand_action(printing, action):
    if printing.opening_hand_action is not None:
        return None  # one opening-hand slot: two such lines aren't claimed
    return replace(printing, opening_hand_action=action)


def _attach_hand_ability(printing, ability):
    return replace(
        printing,
        hand_activated_abilities=(
            tuple(printing.hand_activated_abilities) + (ability,)
        ),
    )


def _line_patch(line: str, card: dict):
    """A ``CardPrinting -> CardPrinting | None`` patch for a P6
    printing-level line, or ``None`` when the line isn't one."""
    action = parse_pregame_line(line, card["name"])
    if action is not None:
        return lambda p: _attach_opening_hand_action(p, action)
    ability = parse_hand_keyword_line(line, card)
    if ability is not None:
        return lambda p: _attach_hand_ability(p, ability)
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
    level lines (pregame actions, hand keyword abilities), then apply
    each line's patch. Any patch refusing (``None``) leaves the card
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
    "parse_hand_keyword_line",
    "parse_pregame_line",
]
