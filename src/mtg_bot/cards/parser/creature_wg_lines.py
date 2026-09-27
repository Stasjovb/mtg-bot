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
    "If a nontoken creature would enter and it wasn't cast, exile it "
    "instead.": "exiles_uncast_nontoken_creatures_entering",
    "Your opponents can't cast spells during your turn.": (
        "opponents_cant_cast_spells_during_your_turn"
    ),
    "Each player can't cast more than one spell each turn.": (
        "each_player_one_spell_per_turn"
    ),
    "Nonbasic lands your opponents control enter tapped.": (
        "opponents_nonbasic_lands_enter_tapped"
    ),
    "During your turn, nonland permanent cards in your graveyard have "
    "retrace.": "grants_retrace_to_nonland_permanents_during_your_turn",
}


def _parse_static_flag_line(line: str, card: dict) -> WGLine | None:
    flag = _STATIC_FLAG_LINES.get(line)
    if flag is None:
        return None
    return WGLine(fields={flag: True})


# ---------------------------------------------------------------------
# Cost increases / combat statics / graveyard-arrival triggers
# ---------------------------------------------------------------------

_SPELLS_COST_MORE_RE = re.compile(
    r"^(?P<desc>[A-Z][a-z]+(?:, [a-z]+)*) spells cost \{(?P<n>\d+)\} more to "
    r"cast\.$"
)


def _parse_spells_cost_more_line(line: str, card: dict) -> WGLine | None:
    """``<Filter> spells cost {N} more to cast.`` (Thalia) ->
    ``spell_cost_increases`` (every player's matching spells)."""
    m = _SPELLS_COST_MORE_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.card_flow_grammar import _parse_descriptor_body

    f = _parse_descriptor_body(m.group("desc").lower())
    if f is None:
        return None
    return WGLine(fields={"spell_cost_increases": ((f, int(m.group("n"))),)})


_CANT_BE_BLOCKED_BY_RE = re.compile(
    r"^[Tt]his creature can't be blocked by (?P<noun>creatures with .+)\.$"
)


def _parse_cant_be_blocked_by_line(line: str, card: dict) -> WGLine | None:
    """``<This> can't be blocked by creatures with <qualifier>.``
    (Questing Beast) -> ``cant_be_blocked_by``."""
    m = _CANT_BE_BLOCKED_BY_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.creature_wg_effects import trigger_subject

    subject = trigger_subject(m.group("noun"))
    if subject is None or subject[1] is not None:
        return None
    return WGLine(fields={"cant_be_blocked_by": subject[0]})


_YOUR_CREATURES_DAMAGE_UNPREVENTABLE = (
    "Combat damage that would be dealt by creatures you control can't be "
    "prevented."
)


def _parse_your_creatures_damage_unpreventable_line(
    line: str, card: dict,
) -> WGLine | None:
    if line != _YOUR_CREATURES_DAMAGE_UNPREVENTABLE:
        return None
    return WGLine(fields={
        "your_creatures_combat_damage_cant_be_prevented": True,
    })


_PUT_INTO_GRAVEYARD_FROM_ANYWHERE_RE = re.compile(
    r"^When this creature is put into a graveyard from anywhere, "
    r"(?P<eff>.+)\.$"
)


def _parse_graveyard_arrival_line(line: str, card: dict) -> WGLine | None:
    """``When <this> is put into a graveyard from anywhere, <effect>.``
    (Worldspine Wurm) -> ``graveyard_arrival_triggers`` (the triggers
    fire from the graveyard, not the battlefield dispatch)."""
    m = _PUT_INTO_GRAVEYARD_FROM_ANYWHERE_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Always, Event

    effect = _parse_effect_phrase(m.group("eff"))
    if effect is None or not getattr(effect, "rearms_graveyard_arrival", False):
        return None
    return WGLine(fields={"graveyard_arrival_triggers": (TriggeredAbility(
        event=Event.DIES, predicate=Always(), effect=effect,
    ),)})


# ---------------------------------------------------------------------
# Enters with named / keyword counters
# ---------------------------------------------------------------------

_ENTERS_WITH_COUNTERS_RE = re.compile(
    r"^[Tt]his creature enters (?P<tapped>tapped )?with (?P<counters>.+?) on "
    r"(?:it|her|him)\.$"
)


def _parse_enters_with_counters_line(line: str, card: dict) -> WGLine | None:
    """``<This> enters with an indestructible counter on her.`` (Arwen,
    Leatherhead) -> ``enters_with_named_counters``."""
    m = _ENTERS_WITH_COUNTERS_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.creature_wg_effects import parse_counter_list

    counters = parse_counter_list(m.group("counters"))
    if counters is None:
        return None
    fields: dict = {"enters_with_named_counters": counters}
    if m.group("tapped"):
        fields["enters_tapped"] = True
    return WGLine(fields=fields)


# ---------------------------------------------------------------------
# "As long as ... cards exiled with this creature" (Keen-Eyed Curator)
# ---------------------------------------------------------------------

_EXILED_WITH_CARD_TYPES_STATIC_RE = re.compile(
    r"^As long as there are (?P<n>two|three|four|five|\d+) or more card "
    r"types among cards exiled with this creature, it gets "
    r"\+(?P<p>\d+)/\+(?P<t>\d+)(?: and has (?P<kw>.+))?\.$"
)
_SMALL_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5}


def _parse_exiled_with_card_types_static(line: str, card: dict) -> WGLine | None:
    """``As long as there are N or more card types among cards exiled with
    this creature, it gets +P/+T[ and has <keywords>].`` -> a SELF static
    gated by :class:`CardTypesAmongExiledWithSourceAtLeast` (which also
    links the card's exiling abilities)."""
    m = _EXILED_WITH_CARD_TYPES_STATIC_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.effects_ext import _keywords
    from mtg_bot.effects.base import StaticAbility, StaticScope
    from mtg_bot.effects.generic.cube_creatures_wg import (
        CardTypesAmongExiledWithSourceAtLeast,
    )

    kws = _keywords(m.group("kw"))
    if kws is None:
        return None
    n = m.group("n")
    return WGLine(statics=(StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=int(m.group("p")),
        toughness_bonus=int(m.group("t")),
        granted_keywords=kws,
        condition=CardTypesAmongExiledWithSourceAtLeast(
            n=int(n) if n.isdigit() else _SMALL_NUMBERS[n],
        ),
    ),))


# ---------------------------------------------------------------------
# Lines ending in a quoted ability
# ---------------------------------------------------------------------


def _parse_quote_final_line(line: str, card: dict) -> WGLine | None:
    """A line whose last sentence is a quoted ability ends in ``."``
    (the period inside the quote -- Mole Man's ``... with "Whenever this
    token attacks, you may mill a card."``); the clause grammar expects
    the sentence period last. Re-parse with the period moved outside."""
    if not line.endswith('."'):
        return None
    from mtg_bot.cards.parser.clause import _parse_clause

    parsed = _parse_clause(line[:-2] + '".', name=card["name"])
    if parsed is None:
        return None
    return WGLine(
        keywords=tuple(parsed.keywords),
        triggers=tuple(parsed.triggers),
        activated=(parsed.activated,) if parsed.activated is not None else (),
        statics=tuple(parsed.statics),
    )


_ACTIVATION_LOCK_RE = re.compile(
    r"^Activated abilities of (?P<types>[a-z, ]+?) can't be activated\.$"
)
_PLURAL_TYPES = {
    "artifacts": "Artifact", "creatures": "Creature",
    "planeswalkers": "Planeswalker", "enchantments": "Enchantment",
    "lands": "Land", "battles": "Battle",
}


def _parse_activation_lock_line(line: str, card: dict) -> WGLine | None:
    """``Activated abilities of <types> can't be activated.`` (Clarion
    Conqueror) -> ``locks_activated_abilities_of`` (mana abilities
    included, as printed)."""
    m = _ACTIVATION_LOCK_RE.match(line)
    if m is None:
        return None
    words = re.split(r", and |, or |, | and | or ", m.group("types"))
    if not words or not all(w in _PLURAL_TYPES for w in words):
        return None
    return WGLine(fields={
        "locks_activated_abilities_of": tuple(_PLURAL_TYPES[w] for w in words),
    })


# ---------------------------------------------------------------------
# Backup N (CR 702.165)
# ---------------------------------------------------------------------

_BACKUP_RE = re.compile(r"^Backup (?P<n>\d+)$")


def _parse_backup_line(line: str, card: dict) -> WGLine | None:
    """``Backup N``: the ETB trigger putting N +1/+1 counters on target
    creature; if it's another creature it gains "the following
    abilities" -- every line printed after Backup, which must all be
    keyword lines (those keywords are also the card's own)."""
    m = _BACKUP_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.keywords import _parse_keyword_line
    from mtg_bot.cards.parser.text import _strip_reminder_text
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.cube_creatures_wg import Backup
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.targets import TargetSpec

    lines = [
        _strip_reminder_text(raw) for raw in card.get("oracle_text", "").split("\n")
    ]
    stripped = [ln for ln in lines if ln]
    if line not in stripped:
        return None
    following = stripped[stripped.index(line) + 1:]
    keywords: list[str] = []
    for ln in following:
        kws = _parse_keyword_line(ln)
        if kws is None:
            return None
        keywords.extend(kws)
    return WGLine(triggers=(TriggeredAbility(
        event=Event.ENTERS, predicate=IsSelf(),
        effect=Backup(
            n=int(m.group("n")), keywords=frozenset(keywords),
            targets=(TargetSpec(filter=IsCreature()),),
        ),
    ),))


_ONCE_PER_TURN_GRAVEYARD_PLAY_RE = re.compile(
    r"^Once during each of your turns, you may play a land from your "
    r"graveyard or cast a permanent spell with mana value (?P<mv>\d+) or "
    r"less from your graveyard\. If you do, it gains \"When this permanent "
    r"is put into a graveyard from the battlefield, exile it and you gain "
    r"2 life\.\"$"
)


def _parse_once_per_turn_graveyard_play(line: str, card: dict) -> WGLine | None:
    """Serra Paragon's graveyard permission (``mtg_bot.
    graveyard_casting_wg``). The granted rider's life amount is the
    printed 2; the recognizer declines any other rider."""
    m = _ONCE_PER_TURN_GRAVEYARD_PLAY_RE.match(line)
    if m is None or int(m.group("mv")) < 1:
        return None
    return WGLine(fields={
        "grants_once_per_turn_graveyard_play_mv": int(m.group("mv")),
    })


_CHOOSE_NAME_AS_ENTERS_LINE = (
    "As this creature enters, look at an opponent's hand, then choose any "
    "card name."
)
_NAMED_SPELLS_COST_MORE_RE = re.compile(
    r"^Spells your opponents cast with the chosen name cost \{(?P<n>\d+)\} "
    r"more to cast\.$"
)
_NAMED_ABILITIES_COST_MORE_RE = re.compile(
    r"^Activated abilities of sources with the chosen name cost "
    r"\{(?P<n>\d+)\} more to activate unless they're mana abilities\.$"
)


def _parse_named_card_lines(line: str, card: dict) -> WGLine | None:
    """Anointed Peacekeeper's three lines: the as-enters name choice and
    the two named-card taxes (``creature_statics_wg``)."""
    if line == _CHOOSE_NAME_AS_ENTERS_LINE:
        return WGLine(fields={"chooses_card_name_as_enters": True})
    m = _NAMED_SPELLS_COST_MORE_RE.match(line)
    if m is not None:
        return WGLine(fields={"named_spell_cost_increase": int(m.group("n"))})
    m = _NAMED_ABILITIES_COST_MORE_RE.match(line)
    if m is not None:
        return WGLine(fields={"named_ability_cost_increase": int(m.group("n"))})
    return None


_RECOGNIZERS = (
    _parse_evoke_line,
    _parse_ravenous_line,
    _parse_mobilize_line,
    _parse_static_flag_line,
    _parse_one_or_more_enter_once_per_turn,
    _parse_spells_cost_more_line,
    _parse_cant_be_blocked_by_line,
    _parse_your_creatures_damage_unpreventable_line,
    _parse_graveyard_arrival_line,
    _parse_enters_with_counters_line,
    _parse_exiled_with_card_types_static,
    _parse_quote_final_line,
    _parse_activation_lock_line,
    _parse_backup_line,
    _parse_once_per_turn_graveyard_play,
    _parse_named_card_lines,
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


# ---------------------------------------------------------------------
# Hand-activated abilities (``source._split_hand_abilities``)
# ---------------------------------------------------------------------

_EXILE_FROM_HAND_ABILITY_RE = re.compile(
    r"^Exile this card from your hand: (?P<eff>.+)\.$"
)


def parse_wg_hand_ability_line(line: str):
    """``Exile this card from your hand: <effect>.`` (Elvish Spirit Guide)
    -> a hand-activated ``ActivatedAbility`` paying ``exile_self`` (a
    mana effect makes it a mana ability, CR 605)."""
    m = _EXILE_FROM_HAND_ABILITY_RE.match(line.strip())
    if m is None:
        return None
    from mtg_bot.cards.parser.activated import _is_mana_ability_effect
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost

    effect = _parse_effect_phrase(m.group("eff")[0].lower() + m.group("eff")[1:])
    if effect is None:
        return None
    return ActivatedAbility(
        cost=ActivationCost(exile_self=True),
        effect=effect,
        is_mana_ability=_is_mana_ability_effect(effect),
    )


# ---------------------------------------------------------------------
# Dynamic P/T (``printing_keywords._parse_dynamic_pt_formula_line``)
# ---------------------------------------------------------------------

_POWER_EQUALS_COUNT_RE = re.compile(
    r"^(?:This creature|[A-Z][^.]*?)'s power is equal to the number of "
    r"(?P<noun>[a-z][a-z ]*)\.$"
)


def parse_wg_dynamic_pt_line(line: str):
    """``<This>'s power is equal to the number of <permanents you
    control>.`` (Adeline) -> a structured ``dynamic_pt_formula``
    (:class:`PowerEqualsCount`); ``None`` otherwise."""
    from mtg_bot.cards.parser.creature_wg_effects import (
        _controlled,
        wg_grammar_disabled,
    )

    if wg_grammar_disabled():
        return None
    m = _POWER_EQUALS_COUNT_RE.match(line)
    if m is None:
        return None
    f = _controlled(m.group("noun"))
    if f is None:
        return None
    from mtg_bot.effects.generic.cube_creatures_wg import PowerEqualsCount

    return PowerEqualsCount(count_filter=f)


def parse_wg_creature_line(line: str, card: dict) -> WGLine | None:
    """The :class:`WGLine` for ``line`` (one reminder-stripped oracle line
    of ``card``), or ``None`` when no W/G bucket recognizer claims it."""
    from mtg_bot.cards.parser.creature_wg_effects import wg_grammar_disabled

    if wg_grammar_disabled():
        return None
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    line = _substitute_self_name(line, card["name"])
    for recognizer in _RECOGNIZERS:
        out = recognizer(line, card)
        if out is not None:
            return out
    return None
