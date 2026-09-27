"""Line-composed builder for the PowerLSV cube's enchantments
(``feature/cube-enchantments``).

The EoE/DSK enchantment builders in :mod:`enchantment_builder` are gated
on per-name allowlists whose grammar predates the unified clause
orchestrator. This builder follows the artifact builder's shape instead:
every oracle line goes through a small set of enchantment-specific
per-line recognizers, then the unified :func:`_parse_clause` grammar
(keywords / triggers / activated abilities / statics). A card is claimed
only when EVERY line is recognized — an unrecognized line returns
``None`` so nothing is ever silently dropped.

Enchantment-specific line recognizers (each parameterized; the cards
that motivated them are named in the comments):

* ``Fading N`` (CR 702.32) — enters with N fade counters plus the
  "remove one at your upkeep, or sacrifice it" trigger (Parallax Wave).
* ``[Domain — ]This spell costs {N} less to cast for each <count>.`` —
  via :func:`cost_reduction._parse_cost_reduction_line` (Leyline Binding).
* ``You may play any number of lands on each of your turns.`` (Fastbond).
* ``Each nonland card in your graveyard has escape. The escape cost is
  equal to the card's mana cost plus exile <N> other cards from your
  graveyard.`` (Underworld Breach).
* ``<Ability word> — <cost incl. Discard this card>: <effect>.`` —
  hand-activated abilities (Channel on Touch the Spirit Realm).
* ``Enchant creature card in a graveyard`` plus the Animate Dead
  reanimation trigger, and Necromancy's "becomes an Aura" trigger and
  its as-though-flash cast permission.

Effect bodies specific to this bucket (``exile ... until this
enchantment leaves the battlefield``, ``add one mana of any type the
sacrificed land could produce``, ...) are phrase recognizers in
:mod:`mtg_bot.cards.parser.enchantment_phrases`, reachable from the
unified effect grammar.

Claims are gated on :data:`CUBE_ENCHANTMENT_NAMES` (the same explicit
opt-in the EoE allowlists use) so no EoE/DSK enchantment's parse can
change through this path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from mtg_bot.cards.base import (
    ActivatedAbility,
    CardPrinting,
    CostReduction,
    StaticAbility,
    TriggeredAbility,
    make_aura,
    make_enchantment,
)
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.cost_reduction import _parse_cost_reduction_line
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.effects.predicates import YOU, Controlled, Event


# Cards claimed through this builder. Explicit opt-in per name, like
# ``enchantment_builder._UNIFIED_ENCHANTMENT_NAMES``.
CUBE_ENCHANTMENT_NAMES: frozenset[str] = frozenset({
    "Animate Dead",
    "Fastbond",
    "Goblin Bombardment",
    "Leyline Binding",
    "Necromancy",
    "Oath of Druids",
    "Parallax Wave",
    "Sneak Attack",
    "Squandered Resources",
    "Touch the Spirit Realm",
    "Underworld Breach",
})


# "Any number" of land plays: the land-drop allowance is an int summed
# over permanents (``CardPrinting.grants_additional_land_per_turn``,
# read by ``legal.py`` and the search capability check alike). A value
# no game can exhaust (a player can't play more lands than they have
# land cards) is exactly "any number" without a second code path.
ANY_NUMBER_OF_LAND_PLAYS = 1_000_000


@dataclass
class _Accumulator:
    keywords: set[str] = field(default_factory=set)
    triggers: list[TriggeredAbility] = field(default_factory=list)
    activated: list[ActivatedAbility] = field(default_factory=list)
    statics: list[StaticAbility] = field(default_factory=list)
    hand_abilities: list[ActivatedAbility] = field(default_factory=list)
    cost_reductions: list[CostReduction] = field(default_factory=list)
    named_counters: list[tuple[str, int]] = field(default_factory=list)
    printing_fields: dict = field(default_factory=dict)
    enchant_type: str | None = None
    power_bonus: int = 0
    toughness_bonus: int = 0


# ---------------------------------------------------------------------------
# Per-line recognizers. Each takes (line, acc) and returns True when it
# consumed the line.
# ---------------------------------------------------------------------------

_FADING_LINE = re.compile(r"^Fading (\d+)$")


def _fading(line: str, acc: _Accumulator) -> bool:
    """``Fading N`` (CR 702.32a): "This permanent enters with N fade
    counters on it. At the beginning of your upkeep, remove a fade
    counter from it. If you can't, sacrifice it." """
    from mtg_bot.effects.generic.enchantment_mechanics import (
        RemoveNamedCounterFromSelfOrSacrifice,
    )

    m = _FADING_LINE.match(line)
    if m is None:
        return False
    acc.named_counters.append(("fade", int(m.group(1))))
    acc.triggers.append(TriggeredAbility(
        event=Event.BEGINNING_OF_UPKEEP,
        predicate=Controlled(YOU),
        effect=RemoveNamedCounterFromSelfOrSacrifice(kind="fade"),
    ))
    return True


def _cost_reduction(line: str, acc: _Accumulator) -> bool:
    reduction = _parse_cost_reduction_line(line)
    if reduction is None:
        return False
    acc.cost_reductions.append(reduction)
    return True


_ANY_NUMBER_OF_LANDS_LINE = (
    "You may play any number of lands on each of your turns."
)


def _any_number_of_lands(line: str, acc: _Accumulator) -> bool:
    """Fastbond. Literal: the only "any number of lands" surface in the
    pool (the "an additional land" family is parsed by the creature
    builder's printing keywords)."""
    if line != _ANY_NUMBER_OF_LANDS_LINE:
        return False
    acc.printing_fields["grants_additional_land_per_turn"] = (
        ANY_NUMBER_OF_LAND_PLAYS
    )
    return True


_GRAVEYARD_ESCAPE_LINE = re.compile(
    r"^Each nonland card in your graveyard has escape\. The escape cost is "
    r"equal to the card's mana cost plus exile (?P<n>one|two|three|four|"
    r"five|\d+) other cards? from your graveyard\.$"
)
_CARDINALS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _graveyard_escape(line: str, acc: _Accumulator) -> bool:
    """Underworld Breach's escape grant (CR 702.138): each nonland card
    in the controller's graveyard may be cast for its mana cost plus
    exiling ``n`` other graveyard cards."""
    m = _GRAVEYARD_ESCAPE_LINE.match(line)
    if m is None:
        return False
    token = m.group("n")
    acc.printing_fields["grants_graveyard_escape_exile_count"] = (
        int(token) if token.isdigit() else _CARDINALS[token]
    )
    return True


_HAND_ABILITY_WORD = re.compile(r"^[A-Z][a-z]+ — (?=\{)")


def _hand_ability(line: str, acc: _Accumulator) -> bool:
    """``Channel — {cost}, Discard this card: <effect>.`` — an ability
    that functions from the hand (routed to ``hand_activated_abilities``;
    the activated grammar's ``from_hand`` mode requires the
    ``Discard this card`` cost atom)."""
    if "Discard this card" not in line:
        return False
    ability = _parse_activated_ability_line(line, from_hand=True)
    if ability is None:
        return False
    acc.hand_abilities.append(ability)
    return True


_ENCHANT_CREATURE_CARD_IN_GRAVEYARD = "Enchant creature card in a graveyard"


def _enchant_graveyard_card(line: str, acc: _Accumulator) -> bool:
    if line != _ENCHANT_CREATURE_CARD_IN_GRAVEYARD:
        return False
    acc.enchant_type = "creature_card_in_graveyard"
    return True


_ENCHANTED_CREATURE_GETS = re.compile(
    r"^Enchanted creature gets ([+-]\d+)/([+-]\d+)\.$"
)


def _enchanted_creature_gets(line: str, acc: _Accumulator) -> bool:
    m = _ENCHANTED_CREATURE_GETS.match(line)
    if m is None:
        return False
    acc.power_bonus += int(m.group(1))
    acc.toughness_bonus += int(m.group(2))
    return True


def _reanimation_aura_lines(line: str, acc: _Accumulator) -> bool:
    from mtg_bot.cards.parser.enchantment_phrases import (
        parse_reanimation_aura_line,
    )

    parsed = parse_reanimation_aura_line(line)
    if parsed is None:
        return False
    triggers, fields = parsed
    acc.triggers.extend(triggers)
    if "flash" in fields:
        acc.keywords.add("flash")
        fields = {k: v for k, v in fields.items() if k != "flash"}
    acc.printing_fields.update(fields)
    return True


_LINE_RECOGNIZERS = (
    _fading,
    _cost_reduction,
    _any_number_of_lands,
    _graveyard_escape,
    _hand_ability,
    _enchant_graveyard_card,
    _enchanted_creature_gets,
    _reanimation_aura_lines,
)


def build_cube_enchantment(card: dict) -> CardPrinting | None:
    """Claim a cube enchantment (non-creature, non-land, non-artifact,
    single-faced) whose every oracle line is recognized."""
    name = card.get("name", "")
    if name not in CUBE_ENCHANTMENT_NAMES:
        return None
    if card.get("card_faces") or card.get("layout", "normal") != "normal":
        return None
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if tuple(card_types) != ("Enchantment",):
        return None
    acc = _Accumulator()
    for raw in card.get("oracle_text", "").split("\n"):
        line = _strip_reminder_text(raw).strip()
        if not line:
            continue
        if any(rec(line, acc) for rec in _LINE_RECOGNIZERS):
            continue
        clause = _parse_clause(line, name=name)
        if clause is None:
            return None
        if clause.keywords:
            acc.keywords.update(clause.keywords)
        elif clause.triggers:
            acc.triggers.extend(clause.triggers)
        elif clause.activated is not None:
            acc.activated.append(clause.activated)
        elif clause.statics:
            acc.statics.extend(clause.statics)
        else:  # pragma: no cover - _parse_clause never returns empty
            return None
    return _assemble(card, supertypes, subtypes, acc)


def _link_exiles_to_source(acc: _Accumulator) -> None:
    """CR 607 linked abilities: when one of the card's abilities refers
    to cards "exiled with it" (Parallax Wave's leaves trigger), the
    card's own bare "Exile target ..." abilities exile *with* it — swap
    those effects for the linked variant that records the link."""
    from mtg_bot.effects.generic.enchantment_mechanics import (
        EachPlayerReturnsCardsExiledWithSource,
        ExileLinkedToSource,
    )
    from mtg_bot.effects.generic.exile import Exile

    if not any(
        isinstance(t.effect, EachPlayerReturnsCardsExiledWithSource)
        for t in acc.triggers
    ):
        return

    def link(effect):
        if type(effect) is Exile:
            return ExileLinkedToSource(targets=effect.targets)
        return effect

    acc.activated = [replace(a, effect=link(a.effect)) for a in acc.activated]
    acc.triggers = [replace(t, effect=link(t.effect)) for t in acc.triggers]


def _assemble(card, supertypes, subtypes, acc: _Accumulator) -> CardPrinting:
    _link_exiles_to_source(acc)
    name = card["name"]
    cost = card.get("mana_cost", "")
    if "Aura" in subtypes:
        printing = make_aura(
            name=name,
            cost=cost,
            power_bonus=acc.power_bonus,
            toughness_bonus=acc.toughness_bonus,
            keywords=frozenset(acc.keywords),
            triggered_abilities=tuple(acc.triggers),
            aura_enchant_type=acc.enchant_type or "creature",
        )
        if acc.activated or acc.statics:
            printing = replace(
                printing,
                activated_abilities=tuple(acc.activated),
                static_abilities=tuple(acc.statics),
            )
    else:
        printing = make_enchantment(
            name=name,
            cost=cost,
            legendary="Legendary" in supertypes,
            triggered_abilities=tuple(acc.triggers),
            activated_abilities=tuple(acc.activated),
            static_abilities=tuple(acc.statics),
        )
        if acc.keywords:
            printing = replace(printing, keywords=frozenset(acc.keywords))
    updates = dict(acc.printing_fields)
    if acc.cost_reductions:
        updates["cost_reductions"] = tuple(acc.cost_reductions)
    if acc.named_counters:
        updates["enters_with_named_counters"] = tuple(acc.named_counters)
    if acc.hand_abilities:
        updates["hand_activated_abilities"] = tuple(acc.hand_abilities)
    if updates:
        printing = replace(printing, **updates)
    return printing


__all__ = [
    "ANY_NUMBER_OF_LAND_PLAYS",
    "CUBE_ENCHANTMENT_NAMES",
    "build_cube_enchantment",
]
