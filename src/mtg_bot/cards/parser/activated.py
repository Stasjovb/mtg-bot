"""Activated-ability grammar.

An activated-ability line of the form ``{cost}: <effect>.`` where
``cost`` is one of:

  * One or more brace-wrapped mana symbols (``{1}{R}``, ``{2}``, …) —
    pure mana cost.
  * ``{T}`` — pure tap cost (no mana).
  * ``{T}, {mana}`` — tap plus a mana cost. The two pieces are
    comma-separated.

``<effect>`` is a single sentence parsed via the unified
``_parse_effect`` after lowercase + period stripping. Other cost
shapes (sacrifice, pay-life, counter-removal, "tap another permanent",
…) are out of scope this slice — the line falls through and causes
the card to be skipped.

A standalone ``Activate only as a sorcery.`` clause attaches to the
immediately preceding activated ability on the same card and marks
it sorcery-speed (handled by the creature builder, not here).
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    parse_mana_cost,
)
from mtg_bot.cards.parser.effects import _parse_effect


_ACTIVATED_ABILITY_LINE = re.compile(
    r"^([^:]+): (.+\.)$"
)

# A bare mana cost is one or more brace-wrapped mana symbols, no commas.
_MANA_COST_ONLY = re.compile(r"^(\{[^}]+\})+$")


def _parse_activation_cost(cost_str: str) -> ActivationCost | None:
    """Parse the cost segment of an activated-ability line into an
    ``ActivationCost``. Recognized shapes:

    * Pure mana: ``{1}{R}`` etc. → ``ActivationCost(mana=…, mana_str=…)``.
    * Tap-only: ``{T}`` → ``ActivationCost(tap_self=True)``.
    * Tap + mana (in either order): ``{T}, {1}{R}`` or ``{1}{R}, {T}``
      → ``ActivationCost(mana=…, mana_str=…, tap_self=True)``.

    Anything else (sacrifice, pay-life, counter removal, multi-comma
    costs, etc.) returns ``None`` so the caller can skip the card.
    """
    cost_str = cost_str.strip()
    # Pure tap.
    if cost_str == "{T}":
        return ActivationCost(tap_self=True)
    # Tap + mana (or mana + tap), comma-separated, exactly two pieces.
    if "," in cost_str:
        pieces = [p.strip() for p in cost_str.split(",")]
        if len(pieces) != 2:
            return None
        if "{T}" in pieces:
            other = pieces[0] if pieces[1] == "{T}" else pieces[1]
            if _MANA_COST_ONLY.match(other) is None:
                return None
            try:
                mana = parse_mana_cost(other)
            except ValueError:
                return None
            return ActivationCost(
                mana=mana, mana_str=other, tap_self=True
            )
        return None
    # Pure mana — everything else with no comma must be a pure brace
    # sequence. ``{T}`` was handled above; anything containing ``{T}``
    # but no comma (e.g. ``{T}{T}``) is malformed/out-of-scope.
    if _MANA_COST_ONLY.match(cost_str) is None:
        return None
    try:
        mana = parse_mana_cost(cost_str)
    except ValueError:
        return None
    return ActivationCost(mana=mana, mana_str=cost_str)


def _normalize_activated_effect_phrase(phrase: str) -> str:
    """Strip the trailing period and lowercase the first letter so the
    activated-ability surface form (``Put a +1/+1 counter on target
    creature.``) matches the unified normalized grammar."""
    phrase = phrase.strip()
    if phrase.endswith("."):
        phrase = phrase[:-1]
    if phrase and phrase[0].isupper():
        phrase = phrase[0].lower() + phrase[1:]
    return phrase


def _parse_activated_ability_line(line: str) -> ActivatedAbility | None:
    """Return an ``ActivatedAbility`` for a ``{cost}: <effect>.`` line,
    or ``None`` if the line shape doesn't match, the cost shape isn't
    one of the supported pure-mana / tap / tap+mana forms, or the
    effect doesn't parse via the unified grammar.
    """
    m = _ACTIVATED_ABILITY_LINE.match(line.strip())
    if m is None:
        return None
    cost = _parse_activation_cost(m.group(1))
    if cost is None:
        return None
    effect = _parse_effect(_normalize_activated_effect_phrase(m.group(2)))
    if effect is None:
        return None
    return ActivatedAbility(cost=cost, effect=effect)


# A standalone ``Activate only as a sorcery.`` clause attaches to the
# immediately preceding activated ability on the same card and marks
# it sorcery-speed. The exact-match recognizer is intentionally narrow:
# any other rider phrasing falls through and causes the card to skip.
_SORCERY_RIDER_LINE = "Activate only as a sorcery."


def _is_sorcery_rider_line(line: str) -> bool:
    """Return True iff ``line`` is the standalone sorcery-speed rider
    ``Activate only as a sorcery.`` (whitespace-stripped, exact match)."""
    return line.strip() == _SORCERY_RIDER_LINE
