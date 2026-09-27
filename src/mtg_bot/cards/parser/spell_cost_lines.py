"""Spell cost lines: printed alternative costs and one-of additional
costs on instants / sorceries.

Recognized lines (each is its own oracle line)::

    [If <gate>, ]you may <alt cost> rather than pay this spell's mana cost.
        gate     := it's your turn | it's not your turn
                  | you control a[n] <Subtype>
        alt cost := <piece>( and <piece>)*
        piece    := pay N life | pay {mana}
                  | exile a <color> card from your hand
                  | return a[n] <Subtype> you control to its owner's hand
                  | sacrifice a[n] <Subtype>

    As an additional cost to cast this spell, <arm>( or <arm>)*.
        arm := discard a card | discard N cards | pay N life
             | sacrifice a[n] <permanent np>

The lines contribute no ``Effect``; ``spell_builder`` drops them from
the effect-clause stream and threads the parsed costs onto the
``CardPrinting`` (``alternative_costs`` / ``additional_cost_options``).
An additional-cost line whose body is already handled by the legacy
per-body flag table in ``spell_builder`` is left to that table.
"""

from __future__ import annotations

import re

from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.spell_costs import AdditionalCostOption, AlternativeCost


_COLOR_LETTERS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
_NUMBER_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3}

_ALT_COST_RE = re.compile(
    r"^(?:If (?P<gate>it's your turn|it's not your turn"
    r"|you control an? (?P<ctrl>[A-Z][a-z]+)), you may|You may) "
    r"(?P<cost>.+) rather than pay this spell's mana cost\.$"
)
_PAY_LIFE_RE = re.compile(r"^pay (\d+) life$")
_PAY_MANA_RE = re.compile(r"^pay ((?:\{[^}]+\})+)$")
_EXILE_COLOR_RE = re.compile(
    r"^exile an? (white|blue|black|red|green) card from your hand$"
)
_RETURN_SUBTYPE_RE = re.compile(
    r"^return an? ([A-Z][a-z]+) you control to its owner's hand$"
)
_SACRIFICE_SUBTYPE_RE = re.compile(r"^sacrifice an? ([A-Z][a-z]+)$")


_OVERLOAD_RE = re.compile(r"^Overload (?P<cost>(?:\{[^}]+\})+)$")


def parse_alternative_cost_line(line: str) -> AlternativeCost | None:
    line = _strip_reminder_text(line.strip())
    m = _OVERLOAD_RE.match(line)
    if m is not None:
        return AlternativeCost(mana=m.group("cost"), overload=True)
    m = _ALT_COST_RE.match(line)
    if m is None:
        return None
    fields: dict = {}
    gate = m.group("gate")
    if gate == "it's your turn":
        fields["turn"] = "yours"
    elif gate == "it's not your turn":
        fields["turn"] = "not_yours"
    elif gate is not None:
        fields["requires_control_subtype"] = m.group("ctrl")
    for piece in m.group("cost").split(" and "):
        if (pm := _PAY_LIFE_RE.match(piece)) and "pay_life" not in fields:
            fields["pay_life"] = int(pm.group(1))
        elif (pm := _PAY_MANA_RE.match(piece)) and "mana" not in fields:
            fields["mana"] = pm.group(1)
        elif (pm := _EXILE_COLOR_RE.match(piece)) and "exile_card_color" not in fields:
            fields["exile_card_color"] = _COLOR_LETTERS[pm.group(1)]
        elif (pm := _RETURN_SUBTYPE_RE.match(piece)) and "return_subtype" not in fields:
            fields["return_subtype"] = pm.group(1)
        elif (pm := _SACRIFICE_SUBTYPE_RE.match(piece)) and (
            "sacrifice_subtype" not in fields
        ):
            fields["sacrifice_subtype"] = pm.group(1)
        else:
            return None
    return AlternativeCost(**fields)


_ADDITIONAL_COST_RE = re.compile(
    r"^As an additional cost to cast this spell, (?P<body>.+)\.$"
)
_DISCARD_RE = re.compile(r"^discard (a|one|two|three) cards?$")
_SACRIFICE_NP_RE = re.compile(r"^sacrifice an? (?P<np>.+)$")


def _parse_arm(arm: str) -> AdditionalCostOption | None:
    if m := _DISCARD_RE.match(arm):
        return AdditionalCostOption(kind="discard", amount=_NUMBER_WORDS[m.group(1)])
    if m := _PAY_LIFE_RE.match(arm):
        return AdditionalCostOption(kind="pay_life", amount=int(m.group(1)))
    if m := _SACRIFICE_NP_RE.match(arm):
        f = parse_permanent_phrase(m.group("np"))
        if f is None:
            return None
        return AdditionalCostOption(
            kind="sacrifice", permanent_filter=f, label=m.group("np"),
        )
    return None


def parse_additional_cost_line(
    line: str,
) -> tuple[AdditionalCostOption, ...] | None:
    m = _ADDITIONAL_COST_RE.match(line.strip())
    if m is None:
        return None
    body = m.group("body")
    # A single arm ("sacrifice a creature", "pay X life") is the casting
    # substrate's (spell_builder._substrate_additional_cost_fields); only
    # the one-of shape "A or B" is modeled here.
    if _parse_arm(body) is not None:
        return None
    arms = []
    for piece in body.split(" or "):
        arm = _parse_arm(piece)
        if arm is None:
            return None
        arms.append(arm)
    return tuple(arms) if len(arms) > 1 else None


# "This spell can't be countered." (CR 101.2) -> the printing's
# ``spell_is_uncounterable`` flag, which every counter effect honors.
UNCOUNTERABLE_LINE = "This spell can't be countered."


_REPLICATE_RE = re.compile(r"^Replicate (?P<cost>(?:\{[^}]+\})+)$")


def parse_replicate_line(line: str) -> str | None:
    """``Replicate {cost}`` (reminder text stripped) -> the cost."""
    m = _REPLICATE_RE.match(_strip_reminder_text(line.strip()))
    return m.group("cost") if m else None


_TEAMWORK_RE = re.compile(r"^Teamwork (?P<n>\d+)$")


def parse_teamwork_line(line: str) -> int | None:
    """``Teamwork N`` (reminder text stripped) -> N."""
    m = _TEAMWORK_RE.match(_strip_reminder_text(line.strip()))
    return int(m.group("n")) if m else None


def is_spell_cost_line(line: str) -> bool:
    """Whether ``line`` is a spell-printing line (alternative cost incl.
    Overload, additional cost, or "This spell can't be countered.")
    that contributes no ``Effect``."""
    return (
        line.strip() == UNCOUNTERABLE_LINE
        or parse_replicate_line(line) is not None
        or parse_teamwork_line(line) is not None
        or parse_alternative_cost_line(line) is not None
        or parse_additional_cost_line(line) is not None
    )


def detect_spell_costs(
    text: str, *, legacy_line=lambda line: False,
) -> tuple[tuple[AlternativeCost, ...], tuple[AdditionalCostOption, ...]]:
    """Every alternative cost and the additional-cost arms printed in
    ``text`` (one oracle line each). Lines for which ``legacy_line``
    is true are owned by ``spell_builder``'s legacy flag table and
    skipped."""
    alts: list[AlternativeCost] = []
    arms: tuple[AdditionalCostOption, ...] = ()
    for raw in text.split("\n"):
        line = raw.strip()
        if legacy_line(line):
            continue
        alt = parse_alternative_cost_line(line)
        if alt is not None:
            alts.append(alt)
            continue
        parsed = parse_additional_cost_line(line)
        if parsed is not None:
            arms = arms + parsed
    return tuple(alts), arms


def detect_spell_line_fields(
    text: str, *, legacy_line=lambda line: False,
) -> dict:
    """``CardPrinting`` field updates implied by the spell-printing
    lines in ``text`` (empty dict when there are none)."""
    alts, arms = detect_spell_costs(text, legacy_line=legacy_line)
    fields: dict = {}
    if alts:
        fields["alternative_costs"] = alts
    if arms:
        fields["additional_cost_options"] = arms
    if any(raw.strip() == UNCOUNTERABLE_LINE for raw in text.split("\n")):
        fields["spell_is_uncounterable"] = True
    for raw in text.split("\n"):
        rep = parse_replicate_line(raw)
        if rep is not None:
            fields["replicate_cost"] = rep
        teamwork = parse_teamwork_line(raw)
        if teamwork is not None:
            fields["teamwork_power"] = teamwork
    return fields


_TARGET_WORD_RE = re.compile(r"\btarget\b")


def apply_overload(effect, text: str, name: str, parse_text):
    """If ``text`` prints an Overload cost, wrap ``effect`` (the
    "target" version) as ``IfConditionElse(AlternativeCostWasPaid(),
    <each-version>, effect)``, parsing the each-version with
    ``parse_text`` from the effect lines with "target" rewritten to
    "each" (CR 702.96b). Returns ``None`` if the rewritten text doesn't
    parse; ``effect`` unchanged when there is no Overload line."""
    from mtg_bot.effects.combinators import IfConditionElse
    from mtg_bot.effects.generic.cast_conditionals import (
        AlternativeCostWasPaid,
    )

    lines = text.split("\n")
    overload = [
        alt for alt in (parse_alternative_cost_line(line) for line in lines)
        if alt is not None and alt.overload
    ]
    if not overload:
        return effect
    effect_lines = [line for line in lines if not is_spell_cost_line(line)]
    rewritten = _TARGET_WORD_RE.sub("each", "\n".join(effect_lines))
    overloaded = parse_text(rewritten, name)
    if overloaded is None or overloaded.requires_target():
        return None
    return IfConditionElse(
        condition=AlternativeCostWasPaid(),
        then_effect=overloaded,
        else_effect=effect,
    )


__all__ = [
    "UNCOUNTERABLE_LINE",
    "parse_replicate_line",
    "parse_teamwork_line",
    "apply_overload",
    "detect_spell_costs",
    "detect_spell_line_fields",
    "is_spell_cost_line",
    "parse_additional_cost_line",
    "parse_alternative_cost_line",
]
