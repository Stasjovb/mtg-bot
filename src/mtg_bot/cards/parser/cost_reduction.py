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
* ``This spell costs {1} less to cast during your turn.`` — engine
  has no matching condition today; the recognizer would need a new
  phrase-to-condition entry once the engine grows the gate.
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
# ``N`` is restricted to one or more digits; the ``{X}``/per-land-group
# variants don't match and fall through to the static side.
_COST_REDUCTION_LINE = re.compile(
    r"^This spell costs \{(\d+)\} less to cast if (?P<condition>.+)\.$"
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
}


def _parse_cost_reduction_line(line: str) -> CostReduction | None:
    """Return a ``CostReduction`` for a single oracle-text line of the
    shape ``This spell costs {N} less to cast if <condition>.``, or
    ``None`` if the line shape doesn't match or the condition phrase
    isn't on the recognized whitelist.

    The caller is responsible for stripping reminder text and trimming
    surrounding whitespace before calling this helper, matching the
    convention used elsewhere in the parser.
    """
    m = _COST_REDUCTION_LINE.match(line.strip())
    if m is None:
        return None
    condition_phrase = m.group("condition").strip()
    engine_condition = _COST_REDUCTION_CONDITIONS.get(condition_phrase)
    if engine_condition is None:
        return None
    return CostReduction(
        amount=int(m.group(1)), condition=engine_condition,
    )
