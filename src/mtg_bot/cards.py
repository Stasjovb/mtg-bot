"""Card printings, mana cost parsing, basic lands, and the Stage-1 synthetic pool.

Real Edge of Eternities cards are sitting in `data/edge_of_eternities.json` but
none are playable yet — they all require keywords/triggers that Stage 1 doesn't
support. Stage 1 plays with invented vanilla creatures instead.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from mtg_bot.effects import (
    CreateToken,
    DealDamageAnyTarget,
    DealDamageToOpponentCreature,
    DealDamageToTargetCreature,
    DestroyTargetCreature,
    DrawCards,
    EachOpponentDiscards,
    EachPlayerDraws,
    Effect,
    ExileTargetCreature,
    GainLife,
    PutPlusOneCounterOnCreatureYouControl,
    TargetOpponentDiscards,
    TriggeredAbility,
)


COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")


@dataclass(frozen=True)
class ManaCost:
    generic: int = 0
    colored: tuple[tuple[str, int], ...] = ()

    @property
    def total(self) -> int:
        return self.generic + sum(n for _, n in self.colored)

    @property
    def colors(self) -> frozenset[str]:
        return frozenset(c for c, _ in self.colored)


def parse_mana_cost(s: str) -> ManaCost:
    if not s:
        return ManaCost()
    generic = 0
    colored: dict[str, int] = {}
    for sym in re.findall(r"\{([^}]+)\}", s):
        if sym.isdigit():
            generic += int(sym)
        elif sym in COLORS:
            colored[sym] = colored.get(sym, 0) + 1
        elif sym == "C":
            generic += 1
        else:
            raise ValueError(f"unsupported mana symbol: {{{sym}}}")
    return ManaCost(generic=generic, colored=tuple(sorted(colored.items())))


@dataclass(frozen=True)
class CardPrinting:
    name: str
    mana_cost_str: str
    mana_cost: ManaCost
    type_line: str
    supertypes: tuple[str, ...]
    card_types: tuple[str, ...]
    subtypes: tuple[str, ...]
    power: int | None = None
    toughness: int | None = None
    produces: frozenset[str] = frozenset()
    keywords: frozenset[str] = frozenset()
    triggered_abilities: tuple[TriggeredAbility, ...] = ()
    # For instants and sorceries: the effect that runs when the spell
    # resolves. After resolution the spell goes to its owner's graveyard.
    # None for creatures, lands, and spells whose effect is implicit (rare).
    spell_effect: Effect | None = None

    @property
    def is_land(self) -> bool:
        return "Land" in self.card_types

    @property
    def is_creature(self) -> bool:
        return "Creature" in self.card_types

    @property
    def is_basic_land(self) -> bool:
        return self.is_land and "Basic" in self.supertypes

    @property
    def is_token(self) -> bool:
        return "Token" in self.supertypes

    @property
    def is_instant(self) -> bool:
        return "Instant" in self.card_types

    @property
    def is_sorcery(self) -> bool:
        return "Sorcery" in self.card_types


_KNOWN_SUPERTYPES = {"Basic", "Legendary", "Snow", "World", "Token"}


def _parse_type_line(
    type_line: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    left, _, right = type_line.partition("—")
    left_words = left.strip().split()
    subtypes = tuple(right.strip().split()) if right else ()
    supertypes = tuple(w for w in left_words if w in _KNOWN_SUPERTYPES)
    card_types = tuple(w for w in left_words if w not in _KNOWN_SUPERTYPES)
    return supertypes, card_types, subtypes


def make_creature(
    name: str,
    cost: str,
    power: int,
    toughness: int,
    keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
) -> CardPrinting:
    type_line = "Creature"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str=cost,
        mana_cost=parse_mana_cost(cost),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        power=power,
        toughness=toughness,
        keywords=frozenset(keywords),
        triggered_abilities=tuple(triggered_abilities),
    )


def make_instant(name: str, cost: str, effect: Effect) -> CardPrinting:
    type_line = "Instant"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str=cost,
        mana_cost=parse_mana_cost(cost),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        spell_effect=effect,
    )


def make_sorcery(name: str, cost: str, effect: Effect) -> CardPrinting:
    type_line = "Sorcery"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str=cost,
        mana_cost=parse_mana_cost(cost),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        spell_effect=effect,
    )


def make_token_creature(
    name: str,
    power: int,
    toughness: int,
    subtypes: tuple[str, ...] = (),
    keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> CardPrinting:
    """Build a CardPrinting representing a creature token.

    Tokens have no mana cost; they're created by effects rather than cast.
    The "Token" supertype distinguishes them so the engine can remove them
    from any non-battlefield zone per MTG rule 704.5d.
    """
    subtypes_str = " ".join(subtypes)
    type_line = f"Token Creature — {subtypes_str}" if subtypes else "Token Creature"
    supertypes, card_types, subtypes_tup = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes_tup,
        power=power,
        toughness=toughness,
        keywords=frozenset(keywords),
    )


def make_basic_land(name: str, color: str) -> CardPrinting:
    type_line = f"Basic Land — {name}"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        produces=frozenset({color}),
    )


BASIC_LANDS: dict[str, CardPrinting] = {
    "Plains": make_basic_land("Plains", "W"),
    "Island": make_basic_land("Island", "U"),
    "Swamp": make_basic_land("Swamp", "B"),
    "Mountain": make_basic_land("Mountain", "R"),
    "Forest": make_basic_land("Forest", "G"),
}


# Token printings reused by effects. Not part of CREATURE_POOL — tokens are
# never cast or drawn, only created by effects resolving on the battlefield.
TOKEN_PRINTINGS: dict[str, CardPrinting] = {
    "Human Soldier": make_token_creature(
        "Human Soldier", 1, 1, subtypes=("Human", "Soldier")
    ),
}

_COLOR_TO_BASIC: dict[str, str] = {
    "W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest",
}


SYNTHETIC_CREATURES: dict[str, CardPrinting] = {
    c.name: c
    for c in [
        # White
        make_creature("Battlefield Recruit", "{W}", 1, 2),
        make_creature("Trained Soldier", "{1}{W}", 2, 2),
        make_creature("Stalwart Knight", "{2}{W}", 3, 3),
        make_creature("Sky Sentinel", "{1}{W}", 1, 3, keywords={"flying"}),
        make_creature("Vigilant Guard", "{2}{W}", 2, 3, keywords={"vigilance"}),
        make_creature("Wall of Stone", "{1}{W}", 0, 5, keywords={"defender"}),
        make_creature("Cleric of Dawn", "{2}{W}", 2, 2, keywords={"lifelink"}),
        make_creature(
            "Healing Wisp", "{W}", 1, 1,
            triggered_abilities=(
                TriggeredAbility(trigger="etb", effect=GainLife(amount=2)),
            ),
        ),
        # Blue
        make_creature("Coastal Scout", "{U}", 1, 2),
        make_creature("Tidal Warrior", "{1}{U}", 2, 2),
        make_creature("Deep Leviathan", "{3}{U}", 4, 4),
        make_creature("Scale Drake", "{2}{U}", 2, 3, keywords={"flying"}),
        make_creature(
            "Inquisitive Scholar", "{2}{U}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(trigger="etb", effect=DrawCards(amount=1)),
            ),
        ),
        make_creature(
            "Court Archivist", "{3}{U}", 2, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb", effect=EachPlayerDraws(amount=1)
                ),
            ),
        ),
        # Black
        make_creature("Cemetery Rat", "{B}", 2, 1),
        make_creature("Grave Brute", "{1}{B}", 2, 2),
        make_creature("Infernal Horror", "{2}{B}{B}", 4, 4),
        make_creature("Ebon Bat", "{1}{B}", 2, 1, keywords={"flying"}),
        make_creature("Venomous Serpent", "{1}{B}", 1, 1, keywords={"deathtouch"}),
        # Red
        make_creature("Raging Goblin", "{R}", 2, 1),
        make_creature("Blood Warrior", "{1}{R}", 2, 2),
        make_creature("Stone Ogre", "{2}{R}", 3, 3),
        make_creature("Dragon Whelp", "{2}{R}", 2, 2, keywords={"flying"}),
        make_creature("Goblin Runner", "{R}", 2, 1, keywords={"haste"}),
        make_creature("Charging Warrior", "{2}{R}", 3, 2, keywords={"haste"}),
        make_creature("Pack Brute", "{2}{R}", 3, 2, keywords={"menace"}),
        # Green
        make_creature("Sapling", "{G}", 1, 2),
        make_creature("Wild Bear", "{1}{G}", 2, 2),
        make_creature("Forest Giant", "{2}{G}", 3, 3),
        make_creature("Great Wurm", "{3}{G}{G}", 6, 6),
        make_creature("Spider Sentinel", "{2}{G}", 1, 4, keywords={"reach"}),
        make_creature("Cliff Elk", "{3}{G}", 3, 4, keywords={"vigilance"}),
        make_creature("Charging Rhino", "{2}{G}", 3, 3, keywords={"trample"}),
    ]
}


# Real Edge of Eternities cards. These match actual Scryfall oracle text (set
# code: eoe) using the Stage-3 primitives we've built. More EoE cards unlock
# as we add new keywords, effects, and mechanics.
EOE_CREATURES: dict[str, CardPrinting] = {
    c.name: c
    for c in [
        # White
        make_creature(
            "Rayblade Trooper", "{2}{W}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
                ),
            ),
        ),
        # Honored Knight-Captain also has a {4}{W}{W}, Sacrifice: search
        # your library for an Equipment activated ability — not yet
        # implemented (no activated-ability or sacrifice framework).
        make_creature(
            "Honored Knight-Captain", "{1}{W}", 1, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Human Soldier"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Knight Luminary has warp {1}{W} — warp is not implemented yet, so
        # Luminary only plays at its regular cost.
        make_creature(
            "Knight Luminary", "{3}{W}", 3, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Human Soldier"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Black
        make_creature("Hullcarver", "{B}", 1, 1, keywords={"deathtouch"}),
        make_creature("Monoist Sentry", "{B}", 4, 1, keywords={"defender"}),
        make_creature(
            "Virus Beetle", "{1}{B}", 1, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb", effect=EachOpponentDiscards(count=1)
                ),
            ),
        ),
        # Blue
        make_creature(
            "Quantum Riddler", "{3}{U}{U}", 4, 6,
            triggered_abilities=(
                TriggeredAbility(trigger="etb", effect=DrawCards(amount=1)),
            ),
        ),
        # Red
        make_creature(
            "Nebula Dragon", "{6}{R}", 4, 4,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb", effect=DealDamageAnyTarget(amount=3)
                ),
            ),
        ),
        # Nova Hellkite has warp {2}{R} on the real card; warp isn't
        # implemented yet, so here it only plays at its regular cost.
        make_creature(
            "Nova Hellkite", "{3}{R}{R}", 4, 5,
            keywords={"flying", "haste"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DealDamageToOpponentCreature(amount=1),
                ),
            ),
        ),
        # Green
        make_creature(
            "Germinating Wurm", "{4}{G}", 5, 5,
            triggered_abilities=(
                TriggeredAbility(trigger="etb", effect=GainLife(amount=2)),
            ),
        ),
    ]
}


# Real EoE instants and sorceries. Non-permanent spells that resolve via
# their spell_effect and then go to their owner's graveyard.
EOE_SPELLS: dict[str, CardPrinting] = {
    c.name: c
    for c in [
        make_sorcery(
            "Plasma Bolt", "{R}", effect=DealDamageAnyTarget(amount=2),
        ),
        make_instant(
            "Bombard", "{2}{R}", effect=DealDamageToTargetCreature(amount=4),
        ),
        # Real Vote Out has Convoke (pay cost with creatures tapping as mana)
        # in addition to its mana cost. Convoke isn't implemented, so this
        # plays at its full printed cost only.
        make_sorcery(
            "Vote Out", "{3}{B}", effect=DestroyTargetCreature(),
        ),
        # Real Gravkill reads "exile target creature or Spacecraft" — since
        # Spacecraft aren't implemented yet, ours only targets creatures.
        make_instant(
            "Gravkill", "{3}{B}", effect=ExileTargetCreature(),
        ),
    ]
}


# Everything non-land that's playable — creatures + instants + sorceries.
# Drawn into decks, castable from hand.
NONLAND_POOL: dict[str, CardPrinting] = {
    **SYNTHETIC_CREATURES, **EOE_CREATURES, **EOE_SPELLS,
}
# Back-compat alias — some tests and the deck builder still reference the
# creature-only name. Kept so that the existing test signatures don't need
# to change; new code should read NONLAND_POOL.
CREATURE_POOL: dict[str, CardPrinting] = NONLAND_POOL


def all_printings() -> dict[str, CardPrinting]:
    return {**BASIC_LANDS, **NONLAND_POOL}


def build_mono_color_deck(color: str, seed: int | None = None) -> list[str]:
    """60 cards: 24 basics of the chosen color + 36 non-land cards of that color."""
    if color not in _COLOR_TO_BASIC:
        raise ValueError(f"unknown color: {color}")
    rng = random.Random(seed)
    land_name = _COLOR_TO_BASIC[color]
    creatures = [
        name
        for name, p in NONLAND_POOL.items()
        if color in p.mana_cost.colors
    ]
    if not creatures:
        raise ValueError(f"no creatures in color {color}")
    deck: list[str] = [creatures[i % len(creatures)] for i in range(36)]
    deck.extend([land_name] * 24)
    rng.shuffle(deck)
    return deck
