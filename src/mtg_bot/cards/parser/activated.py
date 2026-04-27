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
  * ``Pay N life`` — pure pay-life cost. Mana Confluence-style.
  * ``{T}, Pay N life`` (or reversed) — tap plus pay-life.
  * ``{mana}, Pay N life`` (or reversed) — mana plus pay-life.
  * ``Sacrifice another creature or artifact`` — pure
    sacrifice-another-creature-or-artifact cost. Matches Umbral
    Collar Zealot's ``Sacrifice another creature or artifact:
    Surveil 1.`` activated ability.

``<effect>`` is a single sentence parsed via the unified
``_parse_effect`` after lowercase + period stripping. Other cost
shapes (counter-removal, "tap another permanent", multi-comma costs
like tap + mana + sacrifice or tap + pay-life + sacrifice, …) are
out of scope this slice — the line falls through and causes the
card to be skipped.

After a successful parse, the resulting ``ActivatedAbility`` is
inspected: if its effect is a mana ability (e.g. ``AddManaToPool``
producing mana with no targets), the ability is rebuilt with
``is_mana_ability=True`` so the engine bypasses the stack at
activation time per CR 605.

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
from dataclasses import replace

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
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

# Pure sacrifice-another-creature-or-artifact cost piece. The exact
# literal phrase from Umbral Collar Zealot's
# ``Sacrifice another creature or artifact: Surveil 1.`` Stored as a
# single literal because (a) Scryfall always prints this exact
# wording and (b) the engine has a dedicated cost field
# ``ActivationCost.sacrifice_another_creature_or_artifact`` for it.
# Other "sacrifice another …" filters (artifact-only,
# artifact-or-land, land-only, Food, Desert) have their own engine
# fields too but no EoE card prints them as a single-piece cost
# today, so only this one phrase is wired here.
_SACRIFICE_ANOTHER_CREATURE_OR_ARTIFACT_PIECE = (
    "Sacrifice another creature or artifact"
)

# Pay-life cost piece. ``Pay 1 life``, ``Pay 2 life``, etc. The
# integer is captured into the ``pay_life`` field on ActivationCost.
_PAY_LIFE_PIECE = re.compile(r"^Pay (\d+) life$")


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
    * Pure pay-life: ``Pay 1 life`` → ``ActivationCost(pay_life=1)``.
    * Tap + pay-life (either order): ``{T}, Pay 1 life`` or
      ``Pay 1 life, {T}`` → ``ActivationCost(tap_self=True, pay_life=1)``.
    * Mana + pay-life (either order): ``{1}, Pay 2 life`` or
      ``Pay 2 life, {1}`` → ``ActivationCost(mana=…, mana_str=…, pay_life=2)``.
    * Pure sacrifice-another-creature-or-artifact: ``Sacrifice another
      creature or artifact`` → ``ActivationCost(
      sacrifice_another_creature_or_artifact=True)``.

    Anything else (counter removal, three-piece costs like
    tap + mana + sacrifice or tap + pay-life + sacrifice, etc.)
    returns ``None`` so the caller can skip the card.
    """
    cost_str = cost_str.strip()
    # Pure tap.
    if cost_str == "{T}":
        return ActivationCost(tap_self=True)
    # Pure sacrifice-self.
    if cost_str == _SACRIFICE_SELF_PIECE:
        return ActivationCost(sacrifice_self=True)
    # Pure sacrifice-another-creature-or-artifact. Strict literal
    # match — variant phrasings ("a creature or artifact",
    # "another nonland permanent", etc.) fall through. The
    # corresponding ``ActivationCost`` field gates legality on the
    # controller having at least one OTHER creature/artifact to sac.
    if cost_str == _SACRIFICE_ANOTHER_CREATURE_OR_ARTIFACT_PIECE:
        return ActivationCost(sacrifice_another_creature_or_artifact=True)
    # Pure pay-life.
    pay_life_match = _PAY_LIFE_PIECE.match(cost_str)
    if pay_life_match is not None:
        return ActivationCost(pay_life=int(pay_life_match.group(1)))
    # Two-piece comma-separated costs: tap + mana, tap + sacrifice,
    # mana + sacrifice, or any two-piece pay-life combo (in either
    # order for each pair).
    if "," in cost_str:
        pieces = [p.strip() for p in cost_str.split(",")]
        if len(pieces) != 2:
            return None
        # Tap + sacrifice-self (no mana).
        if "{T}" in pieces and _SACRIFICE_SELF_PIECE in pieces:
            return ActivationCost(tap_self=True, sacrifice_self=True)
        # Tap + pay-life (no mana, no sac).
        if "{T}" in pieces:
            other = pieces[0] if pieces[1] == "{T}" else pieces[1]
            other_pay_life = _PAY_LIFE_PIECE.match(other)
            if other_pay_life is not None:
                return ActivationCost(
                    tap_self=True, pay_life=int(other_pay_life.group(1))
                )
            # Tap + mana.
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
        # Mana + pay-life — neither piece is tap or sacrifice-self,
        # so one piece must be a pay-life phrase and the other a
        # bare mana cost.
        pay_life_idx = None
        for i, piece in enumerate(pieces):
            if _PAY_LIFE_PIECE.match(piece) is not None:
                pay_life_idx = i
                break
        if pay_life_idx is not None:
            pay_life_n = int(
                _PAY_LIFE_PIECE.match(pieces[pay_life_idx]).group(1)
            )
            other = pieces[1 - pay_life_idx]
            if _MANA_COST_ONLY.match(other) is None:
                return None
            try:
                mana = parse_mana_cost(other)
            except ValueError:
                return None
            return ActivationCost(
                mana=mana, mana_str=other, pay_life=pay_life_n
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


def _is_mana_ability_effect(effect) -> bool:
    """Return True iff ``effect`` is a mana ability for the purposes of
    CR 605: it produces mana and does not target.

    Today the only effect class that satisfies both is ``AddManaToPool``
    — it mints coins straight into the controller's mana pool with no
    target selection. ``AddNManaOfChosenColor`` and the various
    "permanent-color" / "land-could-produce" mana effects also belong
    here in principle but require an at-resolution choice and aren't
    yet emitted by the activated-ability grammar (no EoE single-line
    ``Add one mana of any color`` activated ability is parser-claimed
    today; when one becomes claimable, extend this predicate).

    Effects that would be excluded if they ever appeared (defense in
    depth): anything reporting ``requires_target() == True`` is not a
    mana ability per the rules — even if it adds mana, the targeting
    forces the ability to use the stack. Today no ``AddManaToPool``
    instance targets, but the explicit guard keeps future grammar
    additions honest.
    """
    if not isinstance(effect, AddManaToPool):
        return False
    if effect.requires_target():
        return False
    return True


def _parse_activated_ability_line(line: str) -> ActivatedAbility | None:
    """Return an ``ActivatedAbility`` for a ``{cost}: <effect>.`` line,
    or ``None`` if the line shape doesn't match, the cost shape isn't
    one of the supported pure-mana / tap / tap+mana forms, or the
    effect doesn't parse via the unified grammar.

    Also accepts the inline sorcery-speed rider variant
    ``{cost}: <effect>. Activate only as a sorcery.`` — the trailing
    rider is stripped, the remainder is parsed as a normal activation,
    and the resulting ability is marked ``sorcery_speed=True``.

    If the parsed effect is a mana ability (see
    ``_is_mana_ability_effect``), the returned ``ActivatedAbility`` is
    marked ``is_mana_ability=True`` so the engine bypasses the stack
    on activation per CR 605.
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
    ability = ActivatedAbility(
        cost=cost, effect=effect, sorcery_speed=sorcery_speed
    )
    if _is_mana_ability_effect(effect):
        ability = replace(ability, is_mana_ability=True)
    return ability


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
