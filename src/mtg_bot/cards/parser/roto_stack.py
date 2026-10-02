"""Oracle-line recognizers for the Vintage Roto P1 package (stack &
restrictions): spell taxes, cast and activation prohibitions, counter-
spell variants and cast triggers.

Two hook points, each consulted only after every older grammar
declined, so no claimed card's parse changes:

* :func:`parse_roto_stack_line` -- whole permanent oracle lines (the
  creature / artifact / cube-enchantment builders' last fallback),
  returning a :class:`~mtg_bot.cards.parser.creature_wg_lines.WGLine`
  (printing fields, keywords, triggered / activated / static
  abilities). Tuple-valued fields from several lines are merged by
  :func:`merge_fields`.
* :func:`parse_roto_stack_effect` -- the very last fallback of
  ``effects._parse_effect`` (normalized phrases: no trailing period,
  lower-cased first letter).

Like the cube buckets, the grammar is switched off for printings that
exist only in the EoE-era dumps (``creature_rmc_grammar``'s switch).
Engine statics live in :mod:`mtg_bot.roto_restrictions`; effects in
:mod:`mtg_bot.effects.generic.roto_stack`.
"""

from __future__ import annotations

import re

from mtg_bot.cards.parser.creature_wg_lines import WGLine
from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


# Printing fields whose values are tuples that several oracle lines may
# each contribute to.
_TUPLE_FIELDS = frozenset({
    "roto_statics", "spell_cost_increases", "locks_activated_abilities_of",
})


def merge_fields(into: dict, fields: dict) -> None:
    """Fold one line's printing ``fields`` into ``into`` (tuple-valued
    fields concatenate; everything else is set)."""
    for key, value in fields.items():
        if key in _TUPLE_FIELDS and key in into:
            into[key] = tuple(into[key]) + tuple(value)
        else:
            into[key] = value


# ---------------------------------------------------------------------
# Spell taxes and the cost floor
# ---------------------------------------------------------------------

_SPELLS_COST_MORE_RE = re.compile(
    r"^(?:(?P<desc>[A-Z][a-z]+(?:, [a-z]+)*) spells|Spells) cost "
    r"\{(?P<n>\d+)\} more to cast\.$"
)


def _spells_cost_more(line: str, card: dict) -> WGLine | None:
    """``[<Descriptor>] spells cost {N} more to cast.`` (Sphere of
    Resistance, Thorn of Amethyst) -> ``spell_cost_increases`` (every
    player's matching spells; Thalia's field)."""
    m = _SPELLS_COST_MORE_RE.match(line)
    if m is None:
        return None
    from mtg_bot.cards.parser.card_flow_grammar import _parse_descriptor_body
    from mtg_bot.effects.generic.card_flow import CardFilter

    desc = m.group("desc")
    f = CardFilter() if desc is None else _parse_descriptor_body(desc.lower())
    if f is None:
        return None
    return WGLine(fields={"spell_cost_increases": ((f, int(m.group("n"))),)})


_EACH_SPELL_COSTS_MORE_EXCEPT_RE = re.compile(
    r"^Each spell costs \{(?P<n>\d+)\} more to cast except during its "
    r"controller's turn\.$"
)


def _each_spell_costs_more_except_controllers_turn(
    line: str, card: dict,
) -> WGLine | None:
    """``Each spell costs {N} more to cast except during its controller's
    turn.`` (Defense Grid)."""
    m = _EACH_SPELL_COSTS_MORE_EXCEPT_RE.match(line)
    if m is None:
        return None
    from mtg_bot.roto_restrictions import SpellTax

    return WGLine(fields={"roto_statics": (
        SpellTax(amount=int(m.group("n")), except_during_casters_turn=True),
    )})


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
}
_MINIMUM_COST_RE = re.compile(
    r"^(?P<untapped>As long as this (?:artifact|creature|permanent) is "
    r"untapped, )?(?:e|E)ach spell that would cost less than (?P<n>\w+) "
    r"mana to cast costs (?P<n2>\w+) mana to cast\.$"
)


def _minimum_spell_cost(line: str, card: dict) -> WGLine | None:
    """``[As long as this artifact is untapped, ]each spell that would
    cost less than N mana to cast costs N mana to cast.`` (Trinisphere)."""
    m = _MINIMUM_COST_RE.match(line)
    if m is None or m.group("n") != m.group("n2"):
        return None
    n = _NUMBER_WORDS.get(m.group("n"))
    if n is None:
        return None
    from mtg_bot.roto_restrictions import MinimumSpellCost

    return WGLine(fields={"roto_statics": (
        MinimumSpellCost(total=n, while_untapped=bool(m.group("untapped"))),
    )})


# ---------------------------------------------------------------------
# Prohibitions shared with the cube W/G statics
# ---------------------------------------------------------------------


def _activation_lock(line: str, card: dict) -> WGLine | None:
    """``Activated abilities of <types> can't be activated.`` (Null Rod,
    Stony Silence) -- Clarion Conqueror's ``locks_activated_abilities_of``
    (mana abilities included, as printed)."""
    from mtg_bot.cards.parser.creature_wg_lines import (
        _parse_activation_lock_line,
    )

    return _parse_activation_lock_line(line, card)


def _static_flag(line: str, card: dict) -> WGLine | None:
    """The W/G bucket's rules-restricting flag lines on a noncreature
    permanent ("Each player can't cast more than one spell each turn." --
    High Noon)."""
    from mtg_bot.cards.parser.creature_wg_lines import _parse_static_flag_line

    return _parse_static_flag_line(line, card)


_LINE_RECOGNIZERS = (
    _spells_cost_more,
    _each_spell_costs_more_except_controllers_turn,
    _minimum_spell_cost,
    _activation_lock,
    _static_flag,
)


def parse_roto_stack_line(line: str, card: dict) -> WGLine | None:
    """The :class:`WGLine` for one reminder-stripped permanent oracle
    ``line`` of ``card``, or ``None`` when no P1 recognizer claims it."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    line = _substitute_self_name(line.strip(), card.get("name", ""))
    for recognizer in _LINE_RECOGNIZERS:
        out = recognizer(line, card)
        if out is not None:
            return out
    return None


_ENTERS_WITH_MINUS_COUNTERS_RE = re.compile(
    r"^This (?:creature|artifact|permanent) enters with "
    r"(?P<n>a|an|one|two|three|four|five|\d+) -1/-1 counters? on it\.$"
)


def _enters_with_minus_one_counters(line: str, card: dict) -> WGLine | None:
    """``This creature enters with a -1/-1 counter on it.`` (Glen Elendra
    Guardian) -> ``enters_with_named_counters``."""
    m = _ENTERS_WITH_MINUS_COUNTERS_RE.match(line)
    if m is None:
        return None
    n = m.group("n")
    count = 1 if n in ("a", "an") else (int(n) if n.isdigit() else _NUMBER_WORDS[n])
    return WGLine(fields={"enters_with_named_counters": (("-1/-1", count),)})


_LINE_RECOGNIZERS = _LINE_RECOGNIZERS + (_enters_with_minus_one_counters,)


# ---------------------------------------------------------------------
# Cost pieces
# ---------------------------------------------------------------------

_REMOVE_ANY_COUNTER_PIECE = re.compile(
    r"^Remove a counter from this (?:creature|artifact|permanent)$"
)


def parse_roto_cost_piece(piece: str):
    """A composable ``ActivationCost.extra_costs`` atom (the last fallback
    of ``activated._classify_cost_piece``), or ``None``."""
    if _disabled():
        return None
    if _REMOVE_ANY_COUNTER_PIECE.match(piece):
        from mtg_bot.effects.generic.roto_stack import (
            RemoveAnyCounterFromSelfCost,
        )

        return RemoveAnyCounterFromSelfCost()
    return None


# ---------------------------------------------------------------------
# Effect phrases: counterspell variants
# ---------------------------------------------------------------------

# Plural subtypes whose singular isn't the regular English one.
_IRREGULAR_PLURAL_SUBTYPES = {
    "Faeries": "Faerie", "Zombies": "Zombie", "Pixies": "Pixie",
}


def _plural_permanent_noun(noun: str):
    """``Faeries`` / ``artifacts`` / ``Elves`` -> an ObjectPredicate."""
    from mtg_bot.cards.parser.creature_rmc_grammar import (
        _permanent_noun_predicate,
    )
    from mtg_bot.effects.object_predicates import HasSubtype

    if noun in _IRREGULAR_PLURAL_SUBTYPES:
        return HasSubtype(_IRREGULAR_PLURAL_SUBTYPES[noun])
    return _permanent_noun_predicate(noun, plural=True)


_COUNTER_WITH_MV_RE = re.compile(
    r"^counter target (?P<np>.+?) with mana value (?P<n>\d+)$"
)


def _counter_with_mana_value(phrase: str) -> Effect | None:
    """``counter target <spell np> with mana value N`` (Mental Misstep,
    Spell Snare) -- X counts on the stack."""
    m = _COUNTER_WITH_MV_RE.match(phrase)
    if m is None:
        return None
    from mtg_bot.cards.parser.target_phrases import parse_spell_phrase
    from mtg_bot.effects.generic.counterspells import CounterSpell
    from mtg_bot.effects.generic.roto_stack import SpellManaValueIs

    ok, f = parse_spell_phrase(m.group("np"))
    if not ok:
        return None
    mv = SpellManaValueIs(int(m.group("n")))
    return CounterSpell(
        spell_filter=mv if f is None else f & mv,
        label=f"{m.group('np')} with mana value {m.group('n')}",
    )


_COUNTER_MV_AT_MOST_COUNT_RE = re.compile(
    r"^counter target (?P<np>.+?) with mana value X or less, where X is the "
    r"number of (?P<noun>.+) you control$"
)


def _counter_mv_at_most_count(phrase: str) -> Effect | None:
    """``counter target <spell np> with mana value X or less, where X is
    the number of <permanents> you control`` (Spellstutter Sprite)."""
    m = _COUNTER_MV_AT_MOST_COUNT_RE.match(phrase)
    if m is None:
        return None
    from mtg_bot.cards.parser.target_phrases import parse_spell_phrase
    from mtg_bot.effects.generic.roto_stack import CounterSpellMVAtMostCount

    ok, f = parse_spell_phrase(m.group("np"))
    pred = _plural_permanent_noun(m.group("noun"))
    if not ok or pred is None:
        return None
    return CounterSpellMVAtMostCount(
        spell_filter=f, count_predicate=pred,
        label=f"{m.group('np')} with mana value X or less",
    )


_COUNTER_THEN_CONTROLLER_RE = re.compile(
    r"^(?P<counter>counter target [^.]+)\. Its controller "
    r"(?P<verb>creates) (?P<rest>.+)$"
)


def _counter_then_controller(phrase: str) -> Effect | None:
    """``<counter target ...>. Its controller creates <token>`` (Swan
    Song, Strix Serenade). The "Its controller draws a card" sibling
    (Glen Elendra Guardian) is the U/B bucket's ``ThenItsControllerDraws``."""
    m = _COUNTER_THEN_CONTROLLER_RE.match(phrase)
    if m is None:
        return None
    from mtg_bot.cards.parser.counter_phrases import parse_counter
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.generic.counterspells import CounterSpell
    from mtg_bot.effects.generic.roto_stack import (
        CounterSpellThenControllerEffect,
    )

    counter = parse_counter(m.group("counter"))
    if not isinstance(counter, CounterSpell):
        return None
    rider = _parse_effect(f"create {m.group('rest')}")
    if rider is None or rider.requires_target():
        return None
    return CounterSpellThenControllerEffect(counter=counter, rider=rider)


def _return_spell_or_permanent(phrase: str) -> Effect | None:
    """``return target spell or permanent to its owner's hand`` (Venser,
    Shaper Savant)."""
    if phrase != "return target spell or permanent to its owner's hand":
        return None
    from mtg_bot.effects.generic.roto_stack import (
        ReturnTargetSpellOrPermanentToHand,
    )

    return ReturnTargetSpellOrPermanentToHand()


def _exile_any_number_of_spells(phrase: str) -> Effect | None:
    """``exile any number of target spells`` (Mindbreak Trap)."""
    if phrase != "exile any number of target spells":
        return None
    from mtg_bot.effects.generic.roto_stack import ExileTargetSpells

    return ExileTargetSpells()


# ---------------------------------------------------------------------
# "Instead" riders (``conditional_phrases.parse_instead_rider`` hooks)
# ---------------------------------------------------------------------

_CONTROL_CREATURE_POWER_RE = re.compile(
    r"^you control a creature with power (?P<n>\d+) or greater$"
)


def roto_rider_condition(text: str):
    """``you control a creature with power N or greater`` (Ferocious) ->
    a ``Condition`` checked on resolution, or ``None``."""
    if _disabled():
        return None
    m = _CONTROL_CREATURE_POWER_RE.match(text)
    if m is None:
        return None
    from mtg_bot.effects.conditions import ControlPermanent
    from mtg_bot.effects.object_predicates import HasPowerAtLeast, IsCreature

    return ControlPermanent(IsCreature() & HasPowerAtLeast(int(m.group("n"))))


def roto_counter_variant(eff_text: str, base):
    """``counter that spell`` restating a taxed counterspell without its
    tax (Stubborn Denial), or ``None``."""
    if _disabled() or eff_text != "counter that spell":
        return None
    from mtg_bot.effects.generic.counterspells import CounterSpell

    if not isinstance(base, CounterSpell) or not base.unless_pays:
        return None
    import dataclasses

    return dataclasses.replace(base, unless_pays="")


# ---------------------------------------------------------------------
# Alternative-cost gates (``spell_cost_lines`` hook)
# ---------------------------------------------------------------------

_OPPONENT_CAST_N_SPELLS_RE = re.compile(
    r"^an opponent cast (?P<n>\w+) or more spells this turn$"
)


def roto_alt_cost_condition(text: str):
    """``an opponent cast N or more spells this turn`` (Mindbreak Trap) ->
    :class:`~mtg_bot.effects.generic.roto_stack.OpponentCastSpellsThisTurn`."""
    if _disabled():
        return None
    m = _OPPONENT_CAST_N_SPELLS_RE.match(text)
    if m is None:
        return None
    n = m.group("n")
    n = int(n) if n.isdigit() else _NUMBER_WORDS.get(n)
    if n is None:
        return None
    from mtg_bot.effects.generic.roto_stack import OpponentCastSpellsThisTurn

    return OpponentCastSpellsThisTurn(n)


# ---------------------------------------------------------------------
# Cost-reduction conditions (``cost_reduction`` hook)
# ---------------------------------------------------------------------

_TARGETS_SPELL_RE = re.compile(r"^it targets an? (?P<np>.+ spell)$")


def roto_cost_reduction_condition(text: str):
    """``it targets a <spell np>`` (Mystical Dispute: "a blue spell") ->
    :class:`~mtg_bot.effects.generic.roto_stack.TargetsSpellMatching`."""
    if _disabled():
        return None
    m = _TARGETS_SPELL_RE.match(text)
    if m is None:
        return None
    from mtg_bot.cards.parser.target_phrases import parse_spell_phrase
    from mtg_bot.effects.generic.roto_stack import TargetsSpellMatching

    ok, f = parse_spell_phrase(m.group("np"))
    if not ok or f is None:
        return None
    return TargetsSpellMatching(f)


_COUNTER_ABILITY_OR_SPELL_RE = re.compile(r"^counter target (?P<items>.+)$")
_ABILITY_KINDS = {
    "activated ability": ("activated",),
    "triggered ability": ("triggered",),
    "ability": ("activated", "triggered"),
}


def _counter_ability_or_spell(phrase: str) -> Effect | None:
    """``counter target triggered ability or colorless spell`` (Consign
    to Memory): stack-object kinds where the spell kind carries a filter
    (``colorless`` included)."""
    m = _COUNTER_ABILITY_OR_SPELL_RE.match(phrase)
    if m is None:
        return None
    from mtg_bot.cards.parser.target_phrases import parse_spell_phrase
    from mtg_bot.effects.generic.roto_stack import (
        CounterTargetStackObjectFiltered,
        IsColorless,
    )

    kinds: list[str] = []
    spell_filter = None
    has_spell = False
    for item in re.split(r", or |, | or ", m.group("items")):
        if item in _ABILITY_KINDS:
            kinds.extend(_ABILITY_KINDS[item])
            continue
        if has_spell or not item.endswith("spell"):
            return None
        has_spell = True
        colorless = item.startswith("colorless ")
        if colorless:
            item = item[len("colorless "):]
        ok, f = parse_spell_phrase(item)
        if not ok:
            return None
        if colorless:
            f = IsColorless() if f is None else f & IsColorless()
        spell_filter = f
        kinds.append("spell")
    if not has_spell or len(kinds) < 2 or spell_filter is None:
        # Plain spell counters and pure ability counters belong to the
        # base / U/B grammars.
        return None
    return CounterTargetStackObjectFiltered(
        kinds=tuple(kinds), spell_filter=spell_filter,
    )


_EFFECT_RECOGNIZERS: tuple = (
    _counter_with_mana_value,
    _counter_mv_at_most_count,
    _counter_then_controller,
    _return_spell_or_permanent,
    _exile_any_number_of_spells,
    _counter_ability_or_spell,
)


def parse_roto_stack_effect(phrase: str) -> Effect | None:
    """A P1 effect phrase (normalized), or ``None``."""
    if _disabled():
        return None
    for recognizer in _EFFECT_RECOGNIZERS:
        eff = recognizer(phrase)
        if eff is not None:
            return eff
    return None


__all__ = [
    "merge_fields",
    "parse_roto_cost_piece",
    "parse_roto_stack_effect",
    "parse_roto_stack_line",
    "roto_alt_cost_condition",
    "roto_cost_reduction_condition",
    "roto_counter_variant",
    "roto_rider_condition",
]
