"""Activated-ability grammar.

An activated-ability line of the form ``{cost}: <effect>.`` where
``cost`` is one of:

  * One or more brace-wrapped mana symbols (``{1}{R}``, ``{2}``, …) —
    pure mana cost.
  * ``{T}`` — pure tap cost (no mana).
  * ``{T}, {mana}`` — tap plus a mana cost. The two pieces are
    comma-separated.
  * ``Sacrifice this creature`` — pure sacrifice-self cost.
  * ``{T}, Sacrifice this creature`` (or reversed) — tap plus
    sacrifice-self.
  * ``{mana}, Sacrifice this creature`` (or reversed) — mana plus
    sacrifice-self.

``<effect>`` is a single sentence parsed via the unified
``_parse_effect`` after lowercase + period stripping. Other cost
shapes (pay-life, counter-removal, "tap another permanent",
multi-comma costs like tap + mana + sacrifice, …) are out of scope
this slice — the line falls through and causes the card to be
skipped.

The ``Activate only as a sorcery.`` rider has two surface shapes:

  * **Inline** — ``{cost}: <effect>. Activate only as a sorcery.`` is a
    single oracle line ending in the rider. ``_parse_activated_ability_line``
    strips the trailing rider and parses the remainder as a normal
    activation, returning an ``ActivatedAbility(..., sorcery_speed=True)``.
    This is the only shape EoE actually uses.
  * **Standalone** — a separate ``Activate only as a sorcery.`` line that
    attaches to the immediately preceding activated ability on the same
    card. Recognized by ``_is_sorcery_rider_line`` and handled by the
    creature builder, not here. Currently unused by EoE but kept for
    completeness.
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

# Pure sacrifice-self cost piece. The oracle text always says
# "Sacrifice this creature" for a creature's own activated ability.
_SACRIFICE_SELF_PIECE = "Sacrifice this creature"


def _parse_activation_cost(cost_str: str) -> ActivationCost | None:
    """Parse the cost segment of an activated-ability line into an
    ``ActivationCost``. Recognized shapes:

    * Pure mana: ``{1}{R}`` etc. → ``ActivationCost(mana=…, mana_str=…)``.
    * Tap-only: ``{T}`` → ``ActivationCost(tap_self=True)``.
    * Tap + mana (in either order): ``{T}, {1}{R}`` or ``{1}{R}, {T}``
      → ``ActivationCost(mana=…, mana_str=…, tap_self=True)``.
    * Pure sacrifice-self: ``Sacrifice this creature``
      → ``ActivationCost(sacrifice_self=True)``.
    * Tap + sacrifice-self (either order): ``{T}, Sacrifice this creature``
      or ``Sacrifice this creature, {T}``
      → ``ActivationCost(tap_self=True, sacrifice_self=True)``.
    * Mana + sacrifice-self (either order): ``{1}{R}, Sacrifice this
      creature`` or ``Sacrifice this creature, {1}{R}``
      → ``ActivationCost(mana=…, mana_str=…, sacrifice_self=True)``.

    Anything else (pay-life, counter removal, three-piece costs like
    tap + mana + sacrifice, etc.) returns ``None`` so the caller can
    skip the card.
    """
    cost_str = cost_str.strip()
    # Pure tap.
    if cost_str == "{T}":
        return ActivationCost(tap_self=True)
    # Pure sacrifice-self.
    if cost_str == _SACRIFICE_SELF_PIECE:
        return ActivationCost(sacrifice_self=True)
    # Two-piece comma-separated costs: tap + mana, tap + sacrifice,
    # or mana + sacrifice (in either order for each pair).
    if "," in cost_str:
        pieces = [p.strip() for p in cost_str.split(",")]
        if len(pieces) != 2:
            return None
        # Tap + sacrifice-self (no mana).
        if "{T}" in pieces and _SACRIFICE_SELF_PIECE in pieces:
            return ActivationCost(tap_self=True, sacrifice_self=True)
        # Tap + mana.
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
        # Mana + sacrifice-self.
        if _SACRIFICE_SELF_PIECE in pieces:
            other = (
                pieces[0]
                if pieces[1] == _SACRIFICE_SELF_PIECE
                else pieces[1]
            )
            if _MANA_COST_ONLY.match(other) is None:
                return None
            try:
                mana = parse_mana_cost(other)
            except ValueError:
                return None
            return ActivationCost(
                mana=mana, mana_str=other, sacrifice_self=True
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


# Inline sorcery-speed rider: ``Activate only as a sorcery.`` glued to
# the end of the same line as the activation, with a single space
# separator after the effect's terminating period. This is the only
# shape EoE actually uses (e.g. Intrepid Tenderfoot's
# ``{3}: Put a +1/+1 counter on this creature. Activate only as a sorcery.``).
_INLINE_SORCERY_RIDER_SUFFIX = " Activate only as a sorcery."


def _parse_activated_ability_line(line: str) -> ActivatedAbility | None:
    """Return an ``ActivatedAbility`` for a ``{cost}: <effect>.`` line,
    or ``None`` if the line shape doesn't match, the cost shape isn't
    one of the supported pure-mana / tap / tap+mana forms, or the
    effect doesn't parse via the unified grammar.

    Also accepts the inline sorcery-speed rider variant
    ``{cost}: <effect>. Activate only as a sorcery.`` — the trailing
    rider is stripped, the remainder is parsed as a normal activation,
    and the resulting ability is marked ``sorcery_speed=True``.
    """
    stripped = line.strip()
    sorcery_speed = False
    if stripped.endswith(_INLINE_SORCERY_RIDER_SUFFIX):
        # Drop the rider but keep the effect's terminating period so
        # the standard ``{cost}: <effect>.`` shape still matches.
        stripped = stripped[: -len(_INLINE_SORCERY_RIDER_SUFFIX)]
        sorcery_speed = True
    m = _ACTIVATED_ABILITY_LINE.match(stripped)
    if m is None:
        return None
    cost = _parse_activation_cost(m.group(1))
    if cost is None:
        return None
    effect = _parse_effect(_normalize_activated_effect_phrase(m.group(2)))
    if effect is None:
        return None
    return ActivatedAbility(cost=cost, effect=effect, sorcery_speed=sorcery_speed)


# A standalone ``Activate only as a sorcery.`` clause attaches to the
# immediately preceding activated ability on the same card and marks
# it sorcery-speed. The exact-match recognizer is intentionally narrow:
# any other rider phrasing falls through and causes the card to skip.
# EoE doesn't actually use this shape (the rider is always inline — see
# ``_INLINE_SORCERY_RIDER_SUFFIX`` above), but the standalone recognizer
# is kept in place as a harmless safety net for any future printings.
_SORCERY_RIDER_LINE = "Activate only as a sorcery."


def _is_sorcery_rider_line(line: str) -> bool:
    """Return True iff ``line`` is the standalone sorcery-speed rider
    ``Activate only as a sorcery.`` (whitespace-stripped, exact match)."""
    return line.strip() == _SORCERY_RIDER_LINE
