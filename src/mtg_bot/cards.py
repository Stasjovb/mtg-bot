"""Card printings, mana cost parsing, basic lands, and the Stage-1 synthetic pool.

Real Edge of Eternities cards are sitting in `data/edge_of_eternities.json` but
none are playable yet — they all require keywords/triggers that Stage 1 doesn't
support. Stage 1 plays with invented vanilla creatures instead.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass


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

    @property
    def is_land(self) -> bool:
        return "Land" in self.card_types

    @property
    def is_creature(self) -> bool:
        return "Creature" in self.card_types

    @property
    def is_basic_land(self) -> bool:
        return self.is_land and "Basic" in self.supertypes


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
        # Blue
        make_creature("Coastal Scout", "{U}", 1, 2),
        make_creature("Tidal Warrior", "{1}{U}", 2, 2),
        make_creature("Deep Leviathan", "{3}{U}", 4, 4),
        make_creature("Scale Drake", "{2}{U}", 2, 3, keywords={"flying"}),
        # Black
        make_creature("Cemetery Rat", "{B}", 2, 1),
        make_creature("Grave Brute", "{1}{B}", 2, 2),
        make_creature("Infernal Horror", "{2}{B}{B}", 4, 4),
        make_creature("Ebon Bat", "{1}{B}", 2, 1, keywords={"flying"}),
        # Red
        make_creature("Raging Goblin", "{R}", 2, 1),
        make_creature("Blood Warrior", "{1}{R}", 2, 2),
        make_creature("Stone Ogre", "{2}{R}", 3, 3),
        make_creature("Dragon Whelp", "{2}{R}", 2, 2, keywords={"flying"}),
        # Green
        make_creature("Sapling", "{G}", 1, 2),
        make_creature("Wild Bear", "{1}{G}", 2, 2),
        make_creature("Forest Giant", "{2}{G}", 3, 3),
        make_creature("Great Wurm", "{3}{G}{G}", 6, 6),
        make_creature("Spider Sentinel", "{2}{G}", 1, 4, keywords={"reach"}),
        make_creature("Cliff Elk", "{3}{G}", 3, 4, keywords={"vigilance"}),
    ]
}


def all_printings() -> dict[str, CardPrinting]:
    return {**BASIC_LANDS, **SYNTHETIC_CREATURES}


def build_mono_color_deck(color: str, seed: int | None = None) -> list[str]:
    """60 cards: 24 basics of the chosen color + 36 creatures of that color."""
    if color not in _COLOR_TO_BASIC:
        raise ValueError(f"unknown color: {color}")
    rng = random.Random(seed)
    land_name = _COLOR_TO_BASIC[color]
    creatures = [
        name
        for name, p in SYNTHETIC_CREATURES.items()
        if color in p.mana_cost.colors
    ]
    if not creatures:
        raise ValueError(f"no synthetic creatures in color {color}")
    deck: list[str] = [creatures[i % len(creatures)] for i in range(36)]
    deck.extend([land_name] * 24)
    rng.shuffle(deck)
    return deck
