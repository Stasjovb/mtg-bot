"""Spell cost-reduction rider parser.

Recognizes a single oracle-text line of the shape::

    This spell costs {N} less to cast if <condition>.

and produces a ``CostReduction(amount=N, condition=<engine-key>)``
that callers attach to a ``CardPrinting`` via the ``cost_reductions``
kwarg on ``make_creature`` / ``make_instant`` / ``make_sorcery``.

The same rider appears on both creatures (Gigastorm Titan, Lashwhip
Predator) and noncreature spells (Dark Endurance, Temporal
Intervention), so the recognizer is factored out here and reused by
both the creature builder and the spell builder.

Out of scope this slice:

* ``This spell costs {X} less to cast, where X is …`` —  variable
  reductions like Fungal Colossus's per-differently-named-land
  count. Different surface shape and would need a per-condition
  ``per_land_group=True`` (or similar) flag on the parsed
  ``CostReduction``.
* ``Affinity for <type> (This spell costs {1} less to cast for each
  …)`` — Thrumming Hivepool. Different surface shape (the rider is
  inside the parenthesized reminder of the Affinity keyword).
* Rider-only conditions used by activated abilities (Thaumaton
  Torpedo's ``This ability costs {3} less to activate if …``) —
  those live on ``ActivatedAbility.cost_reductions``, parsed
  elsewhere.

Adding a new condition: extend ``_COST_REDUCTION_CONDITIONS`` with
the verbatim oracle phrase mapped to the engine condition key. The
engine key must already be implemented in
``mtg_bot.actions.apply_cost_reductions`` — otherwise the parser
would silently produce a no-op rule that diverges from the static
implementation.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import CostReduction


# Surface form: ``This spell costs {N} less to cast if <condition>.``
# (with the ``if`` clause) and ``This spell costs {N} less to cast
# <connector-phrase>.`` (without ``if``, e.g. ``...less to cast during
# your turn.``). Two regexes rather than one regex with optional ``if``
# because a missing ``if`` puts the connector right after ``cast`` and
# the recognized connector list is a closed set — keeping them
# separate makes the lookup against the closed set explicit.
# ``N`` is restricted to one or more digits; the ``{X}``/per-land-group
# variants don't match and fall through to the static side.
#
# A leading ``Void — `` prefix on the rider (Temporal Intervention) is
# stripped via a third regex variant; the body's ``if`` clause body is
# the canonical Void-state phrase, which the recognizer maps to the
# ``void_active`` engine condition key. The Void-prefix variant is its
# own regex (rather than letting the ``if`` clause body match a
# free-form Void description) because the prefix and the engine key
# are tightly coupled — a future Void-prefixed cost-reduction with a
# different body would still want the ``void_active`` mapping, since
# every Void rider gates on the same state.
_COST_REDUCTION_LINE = re.compile(
    r"^This spell costs \{(\d+)\} less to cast if (?P<condition>.+)\.$"
)
_COST_REDUCTION_LINE_NO_IF = re.compile(
    r"^This spell costs \{(\d+)\} less to cast (?P<condition>.+)\.$"
)
_COST_REDUCTION_LINE_VOID_PREFIX = re.compile(
    r"^Void — This spell costs \{(\d+)\} less to cast "
    r"if a nonland permanent left the battlefield this turn "
    r"or a spell was warped this turn\.$"
)


# Conditions recognized as cost-reduction triggers. The mapping is from
# the verbatim oracle-text phrase (after the ``if`` and before the
# trailing period) to the engine condition key on
# ``CostReduction.condition``. Each key MUST have a matching branch in
# ``mtg_bot.actions.apply_cost_reductions``; if not, the parser would
# silently produce a rule the engine ignores, diverging from the
# static implementation.
_COST_REDUCTION_CONDITIONS: dict[str, str] = {
    "you've cast another spell this turn": "another_spell_cast_this_turn",
    "your opponents control three or more creatures": (
        "opponents_control_three_or_more_creatures"
    ),
    "it targets a blocking creature": "target_is_blocking_creature",
    # Seized from Slumber (Duskmourn) — parallel to ``it targets a
    # blocking creature`` shape but for the tapped state.
    "it targets a tapped creature": "target_is_tapped_creature",
}


# Conditions on the no-``if`` shape — same condition→engine-key
# mapping, but the surface text reads naturally without the ``if``
# (e.g. ``"during your turn"`` rather than ``"if it's your turn"``).
# Keys are the verbatim text between ``cast `` and the trailing
# period. Each engine key MUST have a matching branch in
# ``mtg_bot.actions._evaluate_cost_reduction``.
_COST_REDUCTION_CONDITIONS_NO_IF: dict[str, str] = {
    "during your turn": "during_your_turn",
}


def _parse_cost_reduction_line(line: str) -> CostReduction | None:
    """Return a ``CostReduction`` for a single oracle-text line of the
    shape ``This spell costs {N} less to cast if <condition>.``,
    ``This spell costs {N} less to cast <connector>.`` (Mental
    Modulation's ``...less to cast during your turn.``), or
    ``Void — This spell costs {N} less to cast if a nonland
    permanent left the battlefield this turn or a spell was warped
    this turn.`` (Temporal Intervention), or ``None`` if the line
    shape doesn't match or the condition phrase isn't on the
    recognized whitelist.

    The caller is responsible for stripping reminder text and trimming
    surrounding whitespace before calling this helper, matching the
    convention used elsewhere in the parser.
    """
    stripped = line.strip()
    # Void-prefix shape (Temporal Intervention). Tried first because
    # the ``Void — `` prefix is a unique gate; recognizing the whole
    # rider in one shot keeps the canonical Void-state mapping
    # adjacent to the prefix detection. The ``if`` clause body is
    # part of the regex literal so a non-canonical body wouldn't
    # silently map to ``void_active``.
    m = _COST_REDUCTION_LINE_VOID_PREFIX.match(stripped)
    if m is not None:
        return CostReduction(
            amount=int(m.group(1)), condition="void_active",
        )
    m = _COST_REDUCTION_LINE.match(stripped)
    if m is not None:
        condition_phrase = m.group("condition").strip()
        engine_condition = _COST_REDUCTION_CONDITIONS.get(condition_phrase)
        if engine_condition is None:
            return None
        return CostReduction(
            amount=int(m.group(1)), condition=engine_condition,
        )
    # No-``if`` shape (Mental Modulation): the closed connector list
    # gates which surface phrases qualify so an unknown trailing
    # phrase falls through and the spell is left unclaimed rather
    # than silently mapping to a nonsense engine condition key.
    m = _COST_REDUCTION_LINE_NO_IF.match(stripped)
    if m is None:
        return None
    condition_phrase = m.group("condition").strip()
    engine_condition = _COST_REDUCTION_CONDITIONS_NO_IF.get(condition_phrase)
    if engine_condition is None:
        return None
    return CostReduction(
        amount=int(m.group(1)), condition=engine_condition,
    )
