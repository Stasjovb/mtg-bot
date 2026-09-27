"""Creature oracle-line recognizers for the cube W/G creature bucket.

``creature_builder._build_creature_printing`` consults
:func:`parse_wg_creature_line` only for a line the pre-existing grammar
(printing keywords + ``clause._parse_clause``) declined, so nothing here
can change how an already-claimed card parses.

Each recognizer returns a :class:`WGLine` describing what the line adds
to the printing: ``CardPrinting`` field values, keywords and triggered /
activated / static abilities. Shapes (reminder text already stripped):

* ``Evoke—Exile a <filter> card from your hand.`` / ``Evoke {cost}`` —
  :mod:`mtg_bot.evoke` (the evoke sacrifice trigger rides along).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class WGLine:
    """What one recognized oracle line contributes to a creature
    printing."""

    fields: dict = field(default_factory=dict)
    keywords: tuple[str, ...] = ()
    triggers: tuple = ()
    activated: tuple = ()
    statics: tuple = ()


# ---------------------------------------------------------------------
# Evoke
# ---------------------------------------------------------------------

_EVOKE_LINE_RE = re.compile(
    r"^Evoke(?: (?P<mana>(?:\{[^}]+\})+)|—Exile (?P<desc>an? .+? card) "
    r"from your hand\.)$"
)


def _parse_evoke_line(line: str, card: dict) -> WGLine | None:
    m = _EVOKE_LINE_RE.match(line)
    if m is None:
        return None
    from mtg_bot.evoke import EVOKE_SACRIFICE_TRIGGER

    if m.group("mana") is not None:
        from mtg_bot.cards.base import parse_mana_cost

        fields = {
            "evoke_cost": parse_mana_cost(m.group("mana")),
            "evoke_cost_str": m.group("mana"),
        }
    else:
        from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor

        f = parse_card_descriptor(m.group("desc"))
        if f is None:
            return None
        fields = {"evoke_exile_from_hand": f}
    return WGLine(fields=fields, triggers=(EVOKE_SACRIFICE_TRIGGER,))


# ---------------------------------------------------------------------
# Ravenous / Mobilize
# ---------------------------------------------------------------------


def _parse_ravenous_line(line: str, card: dict) -> WGLine | None:
    """``Ravenous`` (CR 702.156): enters with X +1/+1 counters; draws a
    card on entering if X is 5 or more."""
    if line != "Ravenous":
        return None
    from mtg_bot.effects.generic.cube_creatures_wg import ravenous_draw_trigger

    return WGLine(
        fields={"enters_with_counters_from_x": "x"},
        triggers=(ravenous_draw_trigger(),),
    )


_MOBILIZE_RE = re.compile(r"^Mobilize (?P<n>\d+)$")


def _parse_mobilize_line(line: str, card: dict) -> WGLine | None:
    """``Mobilize N`` (CR 702.181): the attack trigger making N tapped and
    attacking 1/1 red Warriors sacrificed at the next end step."""
    m = _MOBILIZE_RE.match(line)
    if m is None:
        return None
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.cube_creatures_wg import Mobilize
    from mtg_bot.effects.predicates import Event, IsSelf

    return WGLine(triggers=(TriggeredAbility(
        event=Event.ATTACKS, predicate=IsSelf(),
        effect=Mobilize(n=int(m.group("n"))),
    ),))


# ---------------------------------------------------------------------
# Batched enters triggers
# ---------------------------------------------------------------------

_ONE_OR_MORE_ENTER_ONCE_PER_TURN_RE = re.compile(
    r"^Whenever one or more (?P<other>other )?(?P<noun>.+?) enter, "
    r"(?P<eff>.+)\. This ability triggers only once each turn\.$"
)


def _parse_one_or_more_enter_once_per_turn(line: str, card: dict) -> WGLine | None:
    """``Whenever one or more [other] <nouns> enter, <effect>. This
    ability triggers only once each turn.`` (Enduring Innocence). With
    the once-each-turn rider the batched "one or more" trigger fires
    exactly when the per-object ENTERS trigger first fires in a turn, so
    it is modeled as that trigger with ``once_per_turn``. (Without the
    rider the batch would need its own dispatch; that form isn't
    claimed.)"""
    m = _ONE_OR_MORE_ENTER_ONCE_PER_TURN_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.creature_wg_effects import trigger_subject
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf, Subject

    subject = trigger_subject(m.group("noun"))
    effect = _parse_effect_phrase(m.group("eff"))
    if subject is None or effect is None:
        return None
    pred, controlled = subject
    predicate = Subject(None, pred)
    if controlled is not None:
        predicate = predicate & controlled
    if m.group("other"):
        predicate = predicate & ~IsSelf()
    return WGLine(triggers=(TriggeredAbility(
        event=Event.ENTERS, predicate=predicate, effect=effect,
        once_per_turn=True,
    ),))


# ---------------------------------------------------------------------
# Rules-restricting statics (``mtg_bot.creature_statics_wg``)
# ---------------------------------------------------------------------

_STATIC_FLAG_LINES: dict[str, str] = {
    "Your opponents can't cast spells during your turn.": (
        "opponents_cant_cast_spells_during_your_turn"
    ),
    "Each player can't cast more than one spell each turn.": (
        "each_player_one_spell_per_turn"
    ),
    "Nonbasic lands your opponents control enter tapped.": (
        "opponents_nonbasic_lands_enter_tapped"
    ),
}


def _parse_static_flag_line(line: str, card: dict) -> WGLine | None:
    flag = _STATIC_FLAG_LINES.get(line)
    if flag is None:
        return None
    return WGLine(fields={flag: True})


_RECOGNIZERS = (
    _parse_evoke_line,
    _parse_ravenous_line,
    _parse_mobilize_line,
    _parse_static_flag_line,
    _parse_one_or_more_enter_once_per_turn,
)


# ---------------------------------------------------------------------
# Linked exile abilities (CR 607.2a)
# ---------------------------------------------------------------------


def _is_exiling_effect(effect) -> bool:
    from mtg_bot.effects.generic.exile import Exile, ExileTargetCardFromGraveyard

    return isinstance(effect, (Exile, ExileTargetCardFromGraveyard))


def _consumes_exile_link(ability) -> bool:
    effect = getattr(ability, "effect", None)
    condition = getattr(ability, "condition", None)
    return bool(
        getattr(effect, "consumes_exile_link", False)
        or getattr(condition, "consumes_exile_link", False)
    )


def link_exile_abilities(
    triggers: list, activated: list, statics: list,
) -> None:
    """When a card prints an ability that refers to "the exiled card" /
    "cards exiled with this creature", its exiling ability is the other
    half of a linked pair: wrap every exiling triggered / activated
    ability in ``LinkExiledCardsToSource`` (in place). A card without a
    link consumer is left untouched."""
    from dataclasses import replace

    from mtg_bot.effects.generic.cube_creatures_wg import (
        LinkExiledCardsToSource,
    )

    if not any(
        _consumes_exile_link(a) for a in (*triggers, *activated, *statics)
    ):
        return
    for abilities in (triggers, activated):
        for i, ability in enumerate(abilities):
            if _is_exiling_effect(ability.effect):
                abilities[i] = replace(
                    ability, effect=LinkExiledCardsToSource(ability.effect),
                )


def parse_wg_creature_line(line: str, card: dict) -> WGLine | None:
    """The :class:`WGLine` for ``line`` (one reminder-stripped oracle line
    of ``card``), or ``None`` when no W/G bucket recognizer claims it."""
    from mtg_bot.cards.parser.creature_wg_effects import wg_grammar_disabled

    if wg_grammar_disabled():
        return None
    for recognizer in _RECOGNIZERS:
        out = recognizer(line, card)
        if out is not None:
            return out
    return None
