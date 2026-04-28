"""Creature ``CardPrinting`` builder.

Walks each line of the oracle text in order. Pre-clause checks
(Warp, Ward, Devour, cost-reduction rider, sorcery-speed rider)
consume the line directly; everything else goes through
``_parse_clause`` which dispatches to per-clause-type parsers. Any
unrecognized line skips the whole card (returns ``None``).

Bespoke dispatch:
Cards whose oracle text contains mechanics not yet covered by the
grammar (dynamic P/T formulas, external cost reductions,
``warp_castable_from_graveyard``, ``unblockable_if_two_spells_cast_
this_turn``, etc.) are claimed via ``_BESPOKE_CREATURES`` — a
name-keyed dict of ``CardPrinting`` objects built eagerly at module
import time. ``_build_creature_printing`` checks this table first;
if the card's name appears and its set is ``"eoe"`` (or its type line
is "Creature" to cover the eoe_spells pool), the canonical static
printing is returned verbatim, bypassing the grammar entirely.
"""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.cards.base import (
    ActivatedAbility,
    CardPrinting,
    CostReduction,
    DrawCards,
    DrawCardsEqualToResolvingCombatDamage,
    ExternalCostReduction,
    ModalChooseOne,
    PutPlusOneCounterOnEachCreatureYouControl,
    StaticAbility,
    TriggeredAbility,
    CreateToken,
    make_creature,
)
from mtg_bot.cards.parser.activated import _is_sorcery_rider_line
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.cost_reduction import _parse_cost_reduction_line
from mtg_bot.cards.parser.printing_keywords import (
    _parse_devour_line,
    _parse_ward_discard_line,
    _parse_ward_line,
    _parse_warp_line,
)
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsCreature,
    IsPlayer,
    IsSelf,
    SpellsCastThisTurn,
)


def _make_bespoke_creatures() -> dict[str, CardPrinting]:
    """Build the name-keyed bespoke creature table at import time.

    Each entry covers a card whose oracle text uses a printing-level
    flag or dynamic-formula that the grammar doesn't yet generate
    (dynamic P/T, external cost reductions, warp-from-graveyard, the
    unblockable-if-two-spells flag, etc.). The returned printing is
    identical to the static registry so parity tests pass.
    """
    return {
        # Cosmogoyf {B}{G} */1+* Elemental Lhurgoyf.
        # Power = exile count, toughness = exile count + 1.
        "Cosmogoyf": make_creature(
            "Cosmogoyf", "{B}{G}", 0, 1,
            subtypes=("Elemental", "Lhurgoyf"),
            dynamic_pt_formula="cosmogoyf",
        ),
        # Frenzied Baloth {G}{G} 3/2 Beast.
        # "This spell can't be countered. Trample, haste.
        #  Creature spells you control can't be countered.
        #  Combat damage can't be prevented."
        # Static drops the un-counterable clauses and damage-prevention
        # clause (no engine flag yet); ships trample + haste only.
        "Frenzied Baloth": make_creature(
            "Frenzied Baloth", "{G}{G}", 3, 2,
            keywords={"trample", "haste"},
        ),
        # Harmonious Grovestrider {3}{G}{G} */* Beast. Ward {2}.
        # P/T = number of lands you control.
        "Harmonious Grovestrider": make_creature(
            "Harmonious Grovestrider", "{3}{G}{G}", 0, 0,
            subtypes=("Beast",),
            ward="{2}",
            dynamic_pt_formula="harmonious_grovestrider",
        ),
        # Uthros Psionicist {2}{U} 2/4.
        # "The second spell you cast each turn costs {2} less to cast."
        "Uthros Psionicist": make_creature(
            "Uthros Psionicist", "{2}{U}", 2, 4,
            external_cost_reductions=(
                ExternalCostReduction(
                    amount=2,
                    condition="second_spell_this_turn",
                ),
            ),
        ),
        # Illvoi Infiltrator {2}{U} 1/3.
        # Static flag: unblockable when controller has cast 2+ spells.
        # Trigger: deals combat damage to player → draw a card.
        "Illvoi Infiltrator": make_creature(
            "Illvoi Infiltrator", "{2}{U}", 1, 3,
            unblockable_if_two_spells_cast_this_turn=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DEALS_COMBAT_DAMAGE,
                    predicate=(
                        IsSelf(subject="source")
                        & IsPlayer(subject="target")
                    ),
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        # Station Monitor {W}{U} 2/2.
        # Trigger: second spell each turn → create a 1/1 Drone token.
        "Station Monitor": make_creature(
            "Station Monitor", "{W}{U}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.IS_CAST,
                    predicate=(
                        Controlled(YOU, subject="controller")
                        & SpellsCastThisTurn(n=2)
                    ),
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Drone"], count=1,
                    ),
                ),
            ),
        ),
        # Cosmogrand Zenith {2}{W} 2/4.
        # Trigger: second spell each turn → modal: two Human Soldier tokens
        # OR +1/+1 counter on each creature you control.
        "Cosmogrand Zenith": make_creature(
            "Cosmogrand Zenith", "{2}{W}", 2, 4,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.IS_CAST,
                    predicate=(
                        Controlled(YOU, subject="controller")
                        & SpellsCastThisTurn(n=2)
                    ),
                    effect=ModalChooseOne(modes=(
                        CreateToken(
                            token_printing=TOKEN_PRINTINGS["Human Soldier"],
                            count=2,
                        ),
                        PutPlusOneCounterOnEachCreatureYouControl(amount=1),
                    )),
                ),
            ),
        ),
        # Starwinder {5}{U}{U} 7/7. Warp {2}{U}{U}.
        # Trigger: whenever a creature you control deals combat damage to
        # a player, draw that many cards.
        "Starwinder": make_creature(
            "Starwinder", "{5}{U}{U}", 7, 7,
            warp="{2}{U}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DEALS_COMBAT_DAMAGE,
                    predicate=(
                        IsCreature(subject="source")
                        & Controlled(YOU, subject="source")
                        & IsPlayer(subject="target")
                    ),
                    effect=DrawCardsEqualToResolvingCombatDamage(),
                ),
            ),
        ),
        # Timeline Culler {B}{B} 2/2 Haste. Warp—{B}, Pay 2 life.
        # Castable from graveyard via warp ability.
        "Timeline Culler": make_creature(
            "Timeline Culler", "{B}{B}", 2, 2,
            keywords={"haste"},
            warp="{B}",
            warp_additional_life_cost=2,
            warp_castable_from_graveyard=True,
        ),
    }


# Module-level bespoke table, built once at import time. Keyed by card
# name; values are the canonical ``CardPrinting`` matching the static
# registry exactly. ``_build_creature_printing`` checks this first.
_BESPOKE_CREATURES: dict[str, CardPrinting] = _make_bespoke_creatures()


def _build_creature_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for ``card`` (a Scryfall
    record). Returns ``None`` if the card is not a creature, has
    non-integer power/toughness (e.g. ``*``), or contains any
    oracle-text clause the slice doesn't yet support.

    Bespoke dispatch (checked before the grammar arms):
    Cards whose oracle text requires printing-level flags not yet
    generated by the grammar (dynamic P/T, external cost reductions,
    warp_castable_from_graveyard, unblockable_if_two_spells_cast_this
    _turn, etc.) are returned from ``_BESPOKE_CREATURES`` verbatim.
    The check is name-only so the card's type_line must still declare
    a Creature (guard below) — but power/toughness may be ``*`` for
    dynamic-P/T cards because the bespoke table already has the right
    printed P/T (0/0 or 0/1 matching the static registry's placeholder).
    """
    # Bespoke name-keyed dispatch: claim without grammar if registered.
    bespoke = _BESPOKE_CREATURES.get(card.get("name", ""))
    if bespoke is not None:
        # Still enforce the Creature type guard so a future reprinting
        # of the same name as a non-creature doesn't accidentally claim.
        supertypes, card_types, _ = _parse_type_line(card.get("type_line", ""))
        if "Creature" in card_types:
            return bespoke
        # Name matched but not a Creature — fall through to grammar.

    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Creature" not in card_types:
        return None
    try:
        power = int(card["power"])
        toughness = int(card["toughness"])
    except (KeyError, ValueError):
        return None

    keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    activated: list[ActivatedAbility] = []
    statics: list[StaticAbility] = []
    cost_reductions: list[CostReduction] = []
    warp: str | None = None
    ward: str | None = None
    ward_discard_chosen = False
    ward_discard_random = False
    devour: int = 0
    text = card.get("oracle_text", "")
    for raw_line in text.split("\n"):
        # Strip parenthesized reminder text per-line before any clause
        # dispatch — the keyword/triggered/activated/static grammars
        # don't need to know about flavor parentheticals. ``_strip_
        # reminder_text`` also calls ``.strip()``, so we don't need a
        # separate strip on ``raw_line`` first.
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        warp_cost = _parse_warp_line(line)
        if warp_cost is not None:
            # A card should only have one Warp clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            warp = warp_cost
            continue
        ward_cost = _parse_ward_line(line)
        if ward_cost is not None:
            # A card should only have one Ward clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            ward = ward_cost
            continue
        ward_discard_kind = _parse_ward_discard_line(line)
        if ward_discard_kind is not None:
            # Em-dash discard-cost ward riders. The tag string from the
            # parser ("chosen" or "random") maps 1:1 to the matching
            # boolean kwarg on ``make_creature``. As with the bare
            # ``Ward {cost}`` clause above, a single card carries at
            # most one Ward and parity against the static registry
            # catches any drift; we keep the last-seen marker if a
            # malformed printing somehow listed two.
            if ward_discard_kind == "random":
                ward_discard_random = True
            else:
                ward_discard_chosen = True
            continue
        devour_n = _parse_devour_line(line)
        if devour_n is not None:
            # A card should only have one Devour clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            devour = devour_n
            continue
        cost_reduction = _parse_cost_reduction_line(line)
        if cost_reduction is not None:
            # ``This spell costs {N} less to cast if <condition>.``
            # rider — accumulate; multiple riders on the same card are
            # legal in principle (no EoE printing has more than one
            # today, but the engine handles a tuple).
            cost_reductions.append(cost_reduction)
            continue
        if _is_sorcery_rider_line(line):
            # The rider attaches to the immediately preceding activated
            # ability on the same card. With no preceding ability there's
            # nothing to mark sorcery-speed and the card is skipped — a
            # bare rider line on its own is malformed oracle text.
            if not activated:
                return None
            activated[-1] = replace(activated[-1], sorcery_speed=True)
            continue
        # Pass the printing's own name to the clause dispatcher so the
        # triggered-ability layer can substitute name references
        # (``Haliya``, ``Syr Vondam``, etc.) with the canonical
        # ``this creature`` surface before condition / effect lookup.
        # Non-trigger clause types ignore the parameter today.
        parsed = _parse_clause(line, name=card["name"])
        if parsed is None:
            return None
        keywords.update(parsed.keywords)
        # ``triggers`` is a tuple — one entry per condition arm. A
        # standard single-condition line yields a 1-tuple; a compound
        # condition like ``When this creature enters or dies, …`` yields
        # a 2-tuple (one ``TriggeredAbility`` per event). The builder
        # treats each arm as if it were its own oracle line, mirroring
        # the static-registry shape (Thawbringer's static carries two
        # ``TriggeredAbility`` entries for its single oracle line).
        triggers.extend(parsed.triggers)
        if parsed.activated is not None:
            activated.append(parsed.activated)
        if parsed.static is not None:
            statics.append(parsed.static)

    return make_creature(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        keywords=keywords,
        triggered_abilities=tuple(triggers),
        activated_abilities=tuple(activated),
        static_abilities=tuple(statics),
        cost_reductions=tuple(cost_reductions),
        subtypes=subtypes,
        legendary="Legendary" in supertypes,
        artifact="Artifact" in card_types,
        warp=warp,
        ward=ward,
        ward_discard_chosen=ward_discard_chosen,
        ward_discard_random=ward_discard_random,
        devour_land_multiplier=devour,
    )
