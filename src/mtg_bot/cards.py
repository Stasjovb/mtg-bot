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
    ActivatedAbility,
    ActivationCost,
    ConditionalIfOpponentHasMoreLands,
    ConditionalIfVoid,
    ConditionalOnTappedCreatures,
    CounterTargetSpell,
    CreateToken,
    DealDamageAnyTarget,
    DealDamageEachOpponent,
    DealDamageToOpponentCreature,
    DealDamageToOpponentCreatureByArtifactCount,
    DealDamageToTargetCreature,
    DestroyAllCreatures,
    DestroyTargetArtifact,
    DestroyTargetCreature,
    DestroyTargetNonlandPermanent,
    MoveSelfCountersToTargetCreatureYouControl,
    UntapTargetOtherPermanent,
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    PutChargeCountersOnTargetSpacecraftYouControl,
    DiscardSelf,
    DrawCards,
    EachOpponentDiscards,
    EachOpponentSacrificesCreature,
    EachOpponentLosesLife,
    EachPlayerDraws,
    Effect,
    ExileEachOpponentsGraveyard,
    ExileTargetCreature,
    GainLife,
    LoseLife,
    PumpCreaturesYouControlUntilEOT,
    PumpSelfUntilEOT,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnTargetCreature,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnTargetCreatureToOwnersHand,
    ReturnTargetPermanentYouControlToOwnersHand,
    DestroyTargetNonlandPermanentWithLanderForController,
    DestroyTargetArtifactOrTappedCreature,
    TapTargetArtifactOrCreature,
    DepressurizeEffect,
    DestroyTargetArtifactEnchantmentOrFlyingCreature,
    CutPropulsionEffect,
    DealDamageToTargetCreatureSpacecraftBoosted,
    ExileAllArtifactsWithManaValueAtMost,
    ExileAllCreaturesAndSpacecraft,
    ModalChooseOne,
    FocusFireEffect,
    SelfMill,
    MillTargetPlayer,
    SearchLibraryForBasicLandTapped,
    Sequence,
    StaticAbility,
    StaticScope,
    Surveil,
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
    # Edge of Eternities "warp" alt-cost. If set, the card may be cast from
    # hand for this cost instead of its normal cost; when cast via warp it's
    # exiled at the next end step and can then be cast from exile at its
    # normal cost on a later turn.
    warp_cost: ManaCost | None = None
    warp_cost_str: str = ""
    # EoE Spacecraft Station mechanic. For a Spacecraft card: once it has
    # station_threshold or more charge counters on it, it becomes an artifact
    # creature with its printed P/T and gains stationed_keywords. None on
    # non-Spacecraft cards.
    station_threshold: int | None = None
    stationed_keywords: frozenset[str] = frozenset()
    # Ward {cost}: when this creature becomes the target of a spell or
    # ability an opponent controls, counter that spell/ability unless the
    # controller pays this cost. We simplify to "caster auto-pays if they
    # can; otherwise the spell is countered at cast time" — no player
    # choice, no pay-or-counter trigger on the stack.
    ward_cost: ManaCost | None = None
    ward_cost_str: str = ""
    # Continuous abilities that buff other permanents while this permanent
    # is on the battlefield (anthems, keyword grants).
    static_abilities: tuple[StaticAbility, ...] = ()
    # Abilities the controller may activate by paying a cost.
    activated_abilities: tuple["ActivatedAbility", ...] = ()

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

    @property
    def is_artifact(self) -> bool:
        return "Artifact" in self.card_types

    @property
    def is_spacecraft(self) -> bool:
        return "Spacecraft" in self.subtypes

    @property
    def is_permanent(self) -> bool:
        """Resolves onto the battlefield when cast."""
        return (
            self.is_creature
            or self.is_artifact
            or self.is_land
            or "Enchantment" in self.card_types
            or "Planeswalker" in self.card_types
        )


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
    static_abilities: tuple[StaticAbility, ...] = (),
    activated_abilities: tuple[ActivatedAbility, ...] = (),
    warp: str | None = None,
    legendary: bool = False,
    ward: str | None = None,
    artifact: bool = False,
) -> CardPrinting:
    prefix = "Legendary " if legendary else ""
    artifact_word = "Artifact " if artifact else ""
    type_line = f"{prefix}{artifact_word}Creature"
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
        ward_cost=parse_mana_cost(ward) if ward else None,
        ward_cost_str=ward or "",
        triggered_abilities=tuple(triggered_abilities),
        static_abilities=tuple(static_abilities),
        activated_abilities=tuple(activated_abilities),
        warp_cost=parse_mana_cost(warp) if warp else None,
        warp_cost_str=warp or "",
    )


def cost(
    mana: str = "", tap_self: bool = False, sacrifice_self: bool = False
) -> ActivationCost:
    """Small constructor for ``ActivationCost`` that handles mana parsing."""
    return ActivationCost(
        mana=parse_mana_cost(mana) if mana else None,
        mana_str=mana,
        tap_self=tap_self,
        sacrifice_self=sacrifice_self,
    )


def make_spacecraft(
    name: str,
    cost: str,
    power: int,
    toughness: int,
    station_threshold: int,
    stationed_keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
    legendary: bool = False,
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
    static_abilities: tuple[StaticAbility, ...] = (),
    activated_abilities: tuple[ActivatedAbility, ...] = (),
) -> CardPrinting:
    """Build a Spacecraft card (Artifact — Spacecraft).

    Spacecraft enter as non-creature artifacts. Once they accumulate
    ``station_threshold`` charge counters they become artifact creatures
    with the printed ``power``/``toughness`` and ``stationed_keywords``.
    Tier-gated static abilities (like Lumen-Class Frigate's "2+ anthem")
    use StaticAbility(tier_threshold=N).
    """
    prefix = "Legendary " if legendary else ""
    type_line = f"{prefix}Artifact — Spacecraft"
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
        station_threshold=station_threshold,
        stationed_keywords=frozenset(stationed_keywords),
        triggered_abilities=tuple(triggered_abilities),
        static_abilities=tuple(static_abilities),
        activated_abilities=tuple(activated_abilities),
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


def make_artifact(
    name: str,
    cost: str,
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
    static_abilities: tuple[StaticAbility, ...] = (),
    activated_abilities: tuple[ActivatedAbility, ...] = (),
    legendary: bool = False,
    keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> CardPrinting:
    """Build a non-creature, non-Spacecraft Artifact permanent."""
    prefix = "Legendary " if legendary else ""
    type_line = f"{prefix}Artifact"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str=cost,
        mana_cost=parse_mana_cost(cost),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        keywords=frozenset(keywords),
        triggered_abilities=tuple(triggered_abilities),
        static_abilities=tuple(static_abilities),
        activated_abilities=tuple(activated_abilities),
    )


def make_enchantment(
    name: str,
    cost: str,
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
    static_abilities: tuple[StaticAbility, ...] = (),
    activated_abilities: tuple[ActivatedAbility, ...] = (),
    legendary: bool = False,
) -> CardPrinting:
    """Build a non-Aura Enchantment permanent. Casts onto the battlefield
    like any other permanent and sits there firing triggers or providing
    static bonuses. Auras (enchant creature) aren't modeled yet.
    """
    prefix = "Legendary " if legendary else ""
    type_line = f"{prefix}Enchantment"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str=cost,
        mana_cost=parse_mana_cost(cost),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        triggered_abilities=tuple(triggered_abilities),
        static_abilities=tuple(static_abilities),
        activated_abilities=tuple(activated_abilities),
    )


def make_token_creature(
    name: str,
    power: int,
    toughness: int,
    subtypes: tuple[str, ...] = (),
    keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
    artifact: bool = False,
    activated_abilities: tuple[ActivatedAbility, ...] = (),
) -> CardPrinting:
    """Build a CardPrinting representing a creature token.

    Tokens have no mana cost; they're created by effects rather than cast.
    The "Token" supertype distinguishes them so the engine can remove them
    from any non-battlefield zone per MTG rule 704.5d. Setting
    ``artifact=True`` adds the Artifact card type (e.g. for EoE's colorless
    Robot tokens).
    """
    subtypes_str = " ".join(subtypes)
    extra_type = "Artifact " if artifact else ""
    type_line = (
        f"Token {extra_type}Creature — {subtypes_str}"
        if subtypes else f"Token {extra_type}Creature"
    )
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
        activated_abilities=tuple(activated_abilities),
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
def _make_lander_token() -> CardPrinting:
    """EoE Lander: a colorless artifact token with an activated ability.

    "{2}, Sacrifice this artifact: Search your library for a basic land
    card, put it onto the battlefield tapped, then shuffle."
    """
    type_line = "Token Artifact — Lander"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name="Lander",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}"),
                    mana_str="{2}",
                    sacrifice_self=True,
                ),
                effect=SearchLibraryForBasicLandTapped(),
            ),
        ),
    )


TOKEN_PRINTINGS: dict[str, CardPrinting] = {
    "Human Soldier": make_token_creature(
        "Human Soldier", 1, 1, subtypes=("Human", "Soldier")
    ),
    # 2/2 colorless Robot artifact creature — EoE's generic Robot token,
    # created by many Spacecraft ETBs and dies-triggered creatures.
    "Robot": make_token_creature(
        "Robot", 2, 2, subtypes=("Robot",), artifact=True
    ),
    # Lander — artifact token (not a creature) with a sacrifice-to-ramp
    # activated ability. Created by many EoE spells and triggers.
    "Lander": _make_lander_token(),
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
        # Starfighter Pilot: surveil 1 whenever this becomes tapped.
        make_creature(
            "Starfighter Pilot", "{1}{W}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="becomes_tapped",
                    effect=Surveil(amount=1),
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
        # Dual-Sun Adepts: "Double strike. {5}: Creatures you control get
        # +1/+1 until end of turn."
        make_creature(
            "Dual-Sun Adepts", "{2}{W}", 2, 2,
            keywords={"double strike"},
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(mana="{5}"),
                    effect=PumpCreaturesYouControlUntilEOT(
                        power_bonus=1, toughness_bonus=1,
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
        # EoE Void: "At the beginning of your end step, if a nonland permanent
        # left the battlefield this turn or a spell was warped this turn, put
        # a +1/+1 counter on this creature."
        make_creature(
            "Insatiable Skittermaw", "{2}{B}", 2, 2,
            keywords={"menace"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=PutPlusOneCounterOnSelf(amount=1),
                    requires_void=True,
                ),
            ),
        ),
        # Flying + dies trigger to create a tapped 2/2 Robot.
        make_creature(
            "Gravpack Monoist", "{2}{B}", 2, 1,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="dies",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        count=1,
                        tapped=True,
                    ),
                ),
            ),
        ),
        # Edge Rover: real card is an Artifact Creature (we don't model the
        # dual-type difference — it's a 2/2 reach for our purposes).
        # "When this creature dies, each player creates a Lander token."
        make_creature(
            "Edge Rover", "{G}", 2, 2,
            keywords={"reach"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="dies",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                        each_player=True,
                    ),
                ),
            ),
        ),
        # Beamsaw Prospector: "When this creature dies, create a Lander token."
        make_creature(
            "Beamsaw Prospector", "{1}{B}", 2, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="dies",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Galactic Wayfarer: "When this creature enters, create a Lander token."
        make_creature(
            "Galactic Wayfarer", "{2}{G}", 3, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Eumidian Terrabotanist: Landfall — gain 1 life.
        make_creature(
            "Eumidian Terrabotanist", "{1}{G}", 2, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=GainLife(amount=1),
                ),
            ),
        ),
        # Intrepid Tenderfoot: "{3}: Put a +1/+1 counter on this creature.
        # Activate only as a sorcery."
        make_creature(
            "Intrepid Tenderfoot", "{1}{G}", 2, 2,
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(mana="{3}"),
                    effect=PutPlusOneCounterOnSelf(amount=1),
                    sorcery_speed=True,
                ),
            ),
        ),
        # Thawbringer: surveil 1 on ETB or dies.
        make_creature(
            "Thawbringer", "{2}{G}", 4, 2,
            triggered_abilities=(
                TriggeredAbility(trigger="etb", effect=Surveil(amount=1)),
                TriggeredAbility(trigger="dies", effect=Surveil(amount=1)),
            ),
        ),
        # Dauntless Scrapbot {3} 3/1 colorless — "ETB exile each opponent's
        # graveyard. Create a Lander token."
        make_creature(
            "Dauntless Scrapbot", "{3}", 3, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Sequence(effects=(
                        ExileEachOpponentsGraveyard(),
                        CreateToken(
                            token_printing=TOKEN_PRINTINGS["Lander"],
                            count=1,
                        ),
                    )),
                ),
            ),
        ),
        # Glacier Godmaw: Trample; ETB create a Lander; Landfall pumps +1/+1
        # and grants vigilance+haste until end of turn.
        make_creature(
            "Glacier Godmaw", "{5}{G}{G}", 6, 6,
            keywords={"trample"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                    ),
                ),
                TriggeredAbility(
                    trigger="landfall",
                    effect=PumpCreaturesYouControlUntilEOT(
                        power_bonus=1, toughness_bonus=1,
                        granted_keywords=frozenset({"vigilance", "haste"}),
                    ),
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
        # Illvoi Galeblade: Flash + Flying + "{2}, Sacrifice this creature:
        # Draw a card." First card to exercise the flash keyword.
        make_creature(
            "Illvoi Galeblade", "{U}", 1, 1,
            keywords={"flash", "flying"},
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(mana="{2}", sacrifice_self=True),
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        # Mechan Navigator: becomes-tapped → draw, discard.
        make_creature(
            "Mechan Navigator", "{1}{U}", 2, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="becomes_tapped",
                    effect=Sequence(effects=(
                        DrawCards(amount=1),
                        DiscardSelf(amount=1),
                    )),
                ),
            ),
        ),
        # Starbreach Whale: Flying + ETB surveil 2 + warp {1}{U}
        make_creature(
            "Starbreach Whale", "{4}{U}", 3, 5,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Surveil(amount=2),
                ),
            ),
            warp="{1}{U}",
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
        make_creature(
            "Nova Hellkite", "{3}{R}{R}", 4, 5,
            keywords={"flying", "haste"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DealDamageToOpponentCreature(amount=1),
                ),
            ),
            warp="{2}{R}",
        ),
        # Real Tannuk's second clause ("Artifact cards and red creature cards
        # in your hand have warp {2}{R}") is a weird grant-on-cards-in-hand
        # effect we don't model. This version ships only the first line.
        make_creature(
            "Tannuk, Steadfast Second", "{2}{R}{R}", 3, 5,
            legendary=True,
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                    granted_keywords=frozenset({"haste"}),
                ),
            ),
        ),
        make_creature(
            "Red Tiger Mechan", "{3}{R}", 3, 3,
            keywords={"haste"},
            warp="{1}{R}",
        ),
        # Molecular Modifier: "At the beginning of combat on your turn,
        # target creature you control gets +1/+0 and gains first strike
        # until end of turn."
        make_creature(
            "Molecular Modifier", "{2}{R}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_combat",
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=1, toughness_bonus=0,
                        granted_keywords=frozenset({"first strike"}),
                        you_control_only=True,
                    ),
                ),
            ),
        ),
        # Sami, Wildcat Captain — Legendary double-strike+vigilance body.
        # Real card also has "Spells you cast have affinity for artifacts"
        # (cost reduction based on artifact count) which we don't model.
        make_creature(
            "Sami, Wildcat Captain", "{4}{R}{W}", 4, 4,
            keywords={"double strike", "vigilance"},
            legendary=True,
        ),
        # Memorial Team Leader: "During your turn, other creatures you
        # control get +1/+0. Warp {1}{R}."
        make_creature(
            "Memorial Team Leader", "{3}{R}", 4, 3,
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                    power_bonus=1, toughness_bonus=0,
                    active_turn_only=True,
                ),
            ),
            warp="{1}{R}",
        ),
        # Bygone Colossus is colorless ({9}) so it shows up in every deck
        # thanks to the colorless-inclusion rule in build_mono_color_deck.
        make_creature(
            "Bygone Colossus", "{9}", 9, 9,
            warp="{3}",
        ),
        # First real Spacecraft. At 3+ charge counters it becomes an
        # artifact creature with flying + haste. Station = tap a creature
        # you control to add that creature's power in charge counters.
        make_spacecraft(
            "Galvanizing Sawship", "{5}{R}", 6, 5,
            station_threshold=3,
            stationed_keywords={"flying", "haste"},
        ),
        # Lumen-Class Frigate: two-tiered Spacecraft.
        # 2+ | Other creatures you control get +1/+1.  (anthem, no creature yet)
        # 12+ | Flying, lifelink — and it becomes an artifact creature.
        make_spacecraft(
            "Lumen-Class Frigate", "{1}{W}", 3, 5,
            station_threshold=12,
            stationed_keywords={"flying", "lifelink"},
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                    power_bonus=1, toughness_bonus=1,
                    tier_threshold=2,
                ),
            ),
        ),
        # Wedgelight Rammer: ETB creates a 2/2 Robot, 9+ it's a creature
        # with flying + first strike.
        make_spacecraft(
            "Wedgelight Rammer", "{3}{W}", 3, 4,
            station_threshold=9,
            stationed_keywords={"flying", "first strike"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Debris Field Crusher: ETB 3 damage to any target, 8+ flying,
        # "{1}{R}: This Spacecraft gets +2/+0 until end of turn."
        make_spacecraft(
            "Debris Field Crusher", "{4}{R}", 1, 5,
            station_threshold=8,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DealDamageAnyTarget(amount=3),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(mana="{1}{R}"),
                    effect=PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0),
                ),
            ),
        ),
        # Atmospheric Greenhouse: ETB puts a +1/+1 counter on each creature
        # you control, 8+ flying+trample.
        make_spacecraft(
            "Atmospheric Greenhouse", "{4}{G}", 5, 4,
            station_threshold=8,
            stationed_keywords={"flying", "trample"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnEachCreatureYouControl(amount=1),
                ),
            ),
        ),
        # Uthros Scanship: ETB "draw two cards, then discard a card", 8+ flying.
        make_spacecraft(
            "Uthros Scanship", "{3}{U}", 4, 4,
            station_threshold=8,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Sequence(effects=(
                        DrawCards(amount=2),
                        DiscardSelf(amount=1),
                    )),
                ),
            ),
        ),
        # Rescue Skiff: ETB return target creature from your graveyard to
        # the battlefield. Real card also allows enchantments; we only
        # model creatures.
        make_spacecraft(
            "Rescue Skiff", "{5}{W}", 5, 6,
            station_threshold=10,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ReturnCreatureFromYourGraveyardToBattlefield(),
                ),
            ),
        ),
        # Wurmwall Sweeper: {2} 2/2 Spacecraft. ETB Surveil 2. Station 4+
        # grants flying.
        make_spacecraft(
            "Wurmwall Sweeper", "{2}", 2, 2,
            station_threshold=4,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Surveil(amount=2),
                ),
            ),
        ),
        # Susurian Dirgecraft: {4}{B} 4/3 Spacecraft. ETB each opponent
        # sacrifices a nontoken creature of their choice. Station 7+ for
        # Menace (simplified to just Menace when stationed — real card has
        # additional abilities we skip).
        make_spacecraft(
            "Susurian Dirgecraft", "{4}{B}", 4, 3,
            station_threshold=7,
            stationed_keywords={"menace"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=EachOpponentSacrificesCreature(),
                ),
            ),
        ),
        # Warmaker Gunship: {2}{R} 4/3 Spacecraft. ETB deals damage equal
        # to your artifacts to opponent's creature. Station 6+ flying.
        make_spacecraft(
            "Warmaker Gunship", "{2}{R}", 4, 3,
            station_threshold=6,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DealDamageToOpponentCreatureByArtifactCount(),
                ),
            ),
        ),
        # Pinnacle Kill-Ship: {7} 7/7 Spacecraft. ETB deals 10 damage to
        # up to one target creature. Station 7+ flying. Simplification:
        # we treat "up to one target" as a required target — trigger
        # fizzles if there are no creatures on the battlefield.
        make_spacecraft(
            "Pinnacle Kill-Ship", "{7}", 7, 7,
            station_threshold=7,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DealDamageToTargetCreature(amount=10),
                ),
            ),
        ),
        # Synthesizer Labship: {U} 4/4 Spacecraft. Station 9+ flying.
        # Simplified: drops the "2+ tier" ability (tiered triggered
        # abilities aren't modeled — tiers currently only gate statics).
        make_spacecraft(
            "Synthesizer Labship", "{U}", 4, 4,
            station_threshold=9,
            stationed_keywords={"flying"},
        ),
        # Sledge-Class Seedship: {2}{G} 4/5 Spacecraft. Station 7+ flying.
        # Simplified: drops the "7+ | whenever it attacks, put a creature
        # from hand onto the battlefield" tiered trigger.
        make_spacecraft(
            "Sledge-Class Seedship", "{2}{G}", 4, 5,
            station_threshold=7,
            stationed_keywords={"flying"},
        ),
        # Fell Gravship: {2}{B} 3/2 Spacecraft. ETB mill 3 then return a
        # creature card from your graveyard to your hand. Station 8+ gives
        # flying + lifelink. Real card says "creature or Spacecraft card"
        # — we restrict to creature for now.
        make_spacecraft(
            "Fell Gravship", "{2}{B}", 3, 2,
            station_threshold=8,
            stationed_keywords={"flying", "lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Sequence(effects=(
                        SelfMill(amount=3),
                        ReturnCreatureFromYourGraveyardToHand(),
                    )),
                ),
            ),
        ),
        # Interceptor Mechan: {2}{B}{R} 3/3 Flying. ETB return creature card
        # from your graveyard to hand. Void — end step: +1/+1 counter.
        # Real card allows "artifact or creature" — we restrict to creature
        # for now.
        make_creature(
            "Interceptor Mechan", "{2}{B}{R}", 3, 3,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ReturnCreatureFromYourGraveyardToHand(),
                ),
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    requires_void=True,
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
            ),
        ),
        # Biotech Specialist: {R}{G} 1/3. ETB create a Lander token.
        # Simplified: drop the "whenever you sacrifice an artifact, deals
        # 2 damage to an opponent" trigger (sac-your-own-artifact as a
        # trigger type isn't modeled yet).
        make_creature(
            "Biotech Specialist", "{R}{G}", 1, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Kav Landseeker: {3}{R} 4/3 Menace. ETB create a Lander token.
        # Simplified: drop the "at the beginning of the end step on your
        # next turn, sacrifice that token" delayed trigger (token-tracking
        # delayed triggers aren't modeled). The token persists until a
        # player naturally sacrifices it for ramp.
        make_creature(
            "Kav Landseeker", "{3}{R}", 4, 3,
            keywords={"menace"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Elegy Acolyte: 4/4 Lifelink. Real card also has "whenever creatures
        # you control deal combat damage to a player, draw + lose 1" — we
        # skip that combat-damage-to-player trigger (not yet implemented)
        # and keep the Void end-step Robot token trigger.
        make_creature(
            "Elegy Acolyte", "{2}{B}{B}", 4, 4,
            keywords={"lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    requires_void=True,
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Blue
        # Brightspear Zealot: {2}{W} 2/4 Vigilance. +2/+0 while you've
        # cast 2+ spells this turn. Conditional self-buff static.
        make_creature(
            "Brightspear Zealot", "{2}{W}", 2, 4,
            keywords={"vigilance"},
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.SELF,
                    power_bonus=2,
                    requires_spells_cast_this_turn=2,
                ),
            ),
        ),
        # Cosmogrand Zenith: {2}{W} 2/4. Modal second-spell trigger: two
        # Human Soldier tokens OR +1/+1 counter on each creature you
        # control.
        make_creature(
            "Cosmogrand Zenith", "{2}{W}", 2, 4,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="second_spell_each_turn",
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
        # Mechan Assembler: {4}{U} 4/4 Artifact Creature — Robot.
        # Whenever another artifact you control enters, create a 2/2
        # Robot token. Once per turn (prevents infinite-Robot loops).
        make_creature(
            "Mechan Assembler", "{4}{U}", 4, 4,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="artifact_enters_you_control",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        count=1,
                    ),
                    once_per_turn=True,
                ),
            ),
        ),
        # Nanoform Sentinel: {2}{U} 3/2 Artifact Creature — Robot.
        # Whenever this creature becomes tapped, untap another target
        # permanent. Once per turn.
        make_creature(
            "Nanoform Sentinel", "{2}{U}", 3, 2,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="becomes_tapped",
                    effect=UntapTargetOtherPermanent(),
                    once_per_turn=True,
                ),
            ),
        ),
        # Illvoi Operative: {1}{U} 2/1. Whenever you cast your second
        # spell each turn, put a +1/+1 counter on this creature.
        make_creature(
            "Illvoi Operative", "{1}{U}", 2, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="second_spell_each_turn",
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
            ),
        ),
        # Sunstar Lightsmith: {3}{W} 3/3. Whenever you cast your second
        # spell each turn, put a +1/+1 counter on this creature and draw
        # a card.
        make_creature(
            "Sunstar Lightsmith", "{3}{W}", 3, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="second_spell_each_turn",
                    effect=Sequence(effects=(
                        PutPlusOneCounterOnSelf(amount=1),
                        DrawCards(amount=1),
                    )),
                ),
            ),
        ),
        # Illvoi Infiltrator: {2}{U} 1/3. Whenever this creature deals
        # combat damage to a player, draw a card. Simplified: drops the
        # "can't be blocked if you've cast 2+ spells this turn" clause
        # (conditional unblockable not yet modeled).
        make_creature(
            "Illvoi Infiltrator", "{2}{U}", 1, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="combat_damage_to_player",
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        # Mouth of the Storm: {6}{U} 6/6 Flying, Ward {2}. Simplified:
        # drops the "creatures your opponents control get -3/-0 until your
        # next turn" ETB since "until your next turn" pump durations
        # aren't tracked.
        make_creature(
            "Mouth of the Storm", "{6}{U}", 6, 6,
            keywords={"flying"},
            ward="{2}",
        ),
        # Cloudsculpt Technician: {2}{U} 1/4 Flying. +1/+0 as long as you
        # control an artifact.
        make_creature(
            "Cloudsculpt Technician", "{2}{U}", 1, 4,
            keywords={"flying"},
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.SELF,
                    power_bonus=1,
                    requires_artifact_you_control=True,
                ),
            ),
        ),
        # Gravblade Heavy: {3}{B} 3/4. +1/+0 and deathtouch as long as you
        # control an artifact.
        make_creature(
            "Gravblade Heavy", "{3}{B}", 3, 4,
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.SELF,
                    power_bonus=1,
                    granted_keywords=frozenset({"deathtouch"}),
                    requires_artifact_you_control=True,
                ),
            ),
        ),
        # Luxknight Breacher: {3}{W} 2/2. Enters with a +1/+1 counter for
        # each other creature and/or artifact you control.
        make_creature(
            "Luxknight Breacher", "{3}{W}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact(),
                ),
            ),
        ),
        # Exosuit Savior: {2}{W} 2/2 Flying. ETB bounce a permanent you
        # control to its owner's hand. Simplification: "up to one other"
        # → required target; self-targeting allowed (no "other"
        # exclusion). Small flexibility loss, major code simplicity win.
        make_creature(
            "Exosuit Savior", "{2}{W}", 2, 2,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ReturnTargetPermanentYouControlToOwnersHand(),
                ),
            ),
        ),
        # Sunstar Expansionist: {1}{W} 2/3. ETB conditional create Lander
        # + Landfall self-pump. The ETB fires only if an opponent controls
        # more lands than you.
        make_creature(
            "Sunstar Expansionist", "{1}{W}", 2, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ConditionalIfOpponentHasMoreLands(
                        effect=CreateToken(
                            token_printing=TOKEN_PRINTINGS["Lander"],
                            count=1,
                        ),
                    ),
                ),
                TriggeredAbility(
                    trigger="landfall",
                    effect=PumpSelfUntilEOT(power_bonus=1),
                ),
            ),
        ),
        # Dockworker Drone: {1}{W} 1/1 Artifact Creature — Robot. Enters
        # with a +1/+1 counter (modeled via ETB trigger, since the engine
        # doesn't have native "enters with counters" replacement
        # effects). When it dies, its counters move to target creature
        # you control.
        make_creature(
            "Dockworker Drone", "{1}{W}", 1, 1,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
                TriggeredAbility(
                    trigger="dies",
                    effect=MoveSelfCountersToTargetCreatureYouControl(),
                ),
            ),
        ),
        # Flight-Deck Coordinator: 3/3. "At the beginning of your end step,
        # if you control two or more tapped creatures, you gain 2 life."
        make_creature(
            "Flight-Deck Coordinator", "{2}{W}", 3, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=ConditionalOnTappedCreatures(
                        effect=GainLife(amount=2),
                        min_count=2,
                    ),
                ),
            ),
        ),
        # Sunstar Chaplain: 3/2. Conditional EoT +1/+1 on target creature
        # you control. Skips its activated "remove-counter → tap" because
        # remove-counter costs aren't modeled yet.
        make_creature(
            "Sunstar Chaplain", "{1}{W}", 3, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=ConditionalOnTappedCreatures(
                        effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
                        min_count=2,
                    ),
                ),
            ),
        ),
        # Dawnstrike Vanguard: 4/5 Lifelink. Conditional EoT: put +1/+1
        # counter on each other creature you control. Oracle says "each
        # creature you control other than this creature"; we simplify by
        # counting itself too — the functional upside is minor since it
        # also has lifelink-enabled stats. Tracked simplification.
        make_creature(
            "Dawnstrike Vanguard", "{5}{W}", 4, 5,
            keywords={"lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=ConditionalOnTappedCreatures(
                        effect=PutPlusOneCounterOnEachCreatureYouControl(
                            amount=1,
                        ),
                        min_count=2,
                    ),
                ),
            ),
        ),
        # Xu-Ifit, Osteoharmonist: {1}{B}{B} 2/3 Legendary. Activated
        # tap+sorcery-speed reanimate — simplified (oracle says the
        # returned creature becomes a Skeleton with no abilities; we just
        # return it as-is since "has no abilities" suppression is not
        # modeled yet).
        make_creature(
            "Xu-Ifit, Osteoharmonist", "{1}{B}{B}", 2, 3,
            legendary=True,
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=ReturnCreatureFromYourGraveyardToBattlefield(),
                    sorcery_speed=True,
                ),
            ),
        ),
        # Faller's Faithful: {2}{B} 3/1. ETB destroy target creature.
        # Simplification: real card says "up to one" and includes a
        # conditional "if that creature wasn't dealt damage this turn,
        # controller draws two". We drop the optionality and the "not
        # damaged this turn" draw rider (damage-this-turn tracking isn't
        # modeled).
        make_creature(
            "Faller's Faithful", "{2}{B}", 3, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DestroyTargetCreature(),
                ),
            ),
        ),
        # Lightless Evangel: {1}{B} 2/2. Whenever you sacrifice another
        # creature or artifact, put a +1/+1 counter on this creature.
        make_creature(
            "Lightless Evangel", "{1}{B}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="sacrifice_creature_or_artifact",
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
            ),
        ),
        # Voidforged Titan: 5/4 Robot Warrior. "Void — At the beginning of
        # your end step, if [void active], you draw a card and lose 1 life."
        # We model artifact-ness as a plain creature (same shortcut as Edge
        # Rover) because nothing currently implemented cares.
        make_creature(
            "Voidforged Titan", "{4}{B}", 5, 4,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    requires_void=True,
                    effect=Sequence(effects=(
                        DrawCards(amount=1),
                        LoseLife(amount=1),
                    )),
                ),
            ),
        ),
        # Red
        # Thaumaton Torpedo: {1} Artifact. {6}, {T}, Sacrifice: Destroy
        # target nonland permanent. Simplified: drops the "{3} less if
        # you attacked with a Spacecraft this turn" cost-reduction
        # rider (cost modification not yet modeled).
        make_artifact(
            "Thaumaton Torpedo", "{1}",
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{6}"), mana_str="{6}",
                        tap_self=True,
                        sacrifice_self=True,
                    ),
                    effect=DestroyTargetNonlandPermanent(),
                ),
            ),
        ),
        # Dubious Delicacy: {2}{B} Artifact — Food. Flash + ETB -3/-3 UEOT
        # + one of two "2 tap sac" modes for life-swing. Simplifications:
        # "up to one" target → required target; only the gain-life
        # activation kept (the "target opponent loses 3 life" variant
        # collapses into EachOpponentLosesLife which has similar flavor).
        make_artifact(
            "Dubious Delicacy", "{2}{B}",
            keywords={"flash"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=-3, toughness_bonus=-3,
                    ),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{2}"), mana_str="{2}",
                        tap_self=True,
                        sacrifice_self=True,
                    ),
                    effect=GainLife(amount=3),
                ),
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{2}"), mana_str="{2}",
                        tap_self=True,
                        sacrifice_self=True,
                    ),
                    effect=EachOpponentLosesLife(amount=3),
                ),
            ),
        ),
        # Melded Moxite: {1}{R} Artifact. ETB loot (discard 1 → draw 2);
        # {3}, Sac: create a tapped 2/2 Robot token. Simplification: the
        # real card's ETB is "you MAY discard; if you do, draw two" — we
        # make it unconditional, so an empty-hand cast still draws 2
        # (slightly stronger than printed). Agents always prefer looting.
        make_artifact(
            "Melded Moxite", "{1}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Sequence(effects=(
                        DiscardSelf(amount=1),
                        DrawCards(amount=2),
                    )),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{3}"), mana_str="{3}",
                        sacrifice_self=True,
                    ),
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        count=1,
                        tapped=True,
                    ),
                ),
            ),
        ),
        # Oreplate Pangolin: {1}{R} 2/2 Artifact Creature. "Whenever
        # another artifact you control enters, you may pay {1}. If you do,
        # put a +1/+1 counter on this creature." Simplified: drop the
        # optional {1} payment.
        make_creature(
            "Oreplate Pangolin", "{1}{R}", 2, 2,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="artifact_enters_you_control",
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
            ),
        ),
        # Frontline War-Rager: {2}{R} 2/3. Conditional-EoT +1/+1 counter
        # when you control two or more tapped creatures.
        make_creature(
            "Frontline War-Rager", "{2}{R}", 2, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=ConditionalOnTappedCreatures(
                        effect=PutPlusOneCounterOnSelf(amount=1),
                        min_count=2,
                    ),
                ),
            ),
        ),
        # Kavaron Turbodrone: {2}{R} 2/3 Artifact Creature — Robot. {T}:
        # target creature you control gets +1/+1 and haste UEOT.
        # Sorcery-speed activation.
        make_creature(
            "Kavaron Turbodrone", "{2}{R}", 2, 3,
            artifact=True,
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=1, toughness_bonus=1,
                        granted_keywords=frozenset({"haste"}),
                        you_control_only=True,
                    ),
                    sorcery_speed=True,
                ),
            ),
        ),
        # Meltstrider Eulogist: {2}{G} 3/3. Whenever a creature you
        # control with a +1/+1 counter on it dies, draw a card.
        make_creature(
            "Meltstrider Eulogist", "{2}{G}", 3, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="creature_you_control_with_counter_dies",
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        # Kavaron Skywarden: 4/5 Reach. Void — at your end step, put a
        # +1/+1 counter on this creature.
        make_creature(
            "Kavaron Skywarden", "{4}{R}", 4, 5,
            keywords={"reach"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    requires_void=True,
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
            ),
        ),
        # Remnant Elemental: 0/4 Reach + Landfall +2/+0 UEOT self-pump.
        make_creature(
            "Remnant Elemental", "{1}{R}", 0, 4,
            keywords={"reach"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=PumpSelfUntilEOT(power_bonus=2),
                ),
            ),
        ),
        # Icecave Crasher: 4/4 Trample + Landfall +1/+0 UEOT self-pump.
        make_creature(
            "Icecave Crasher", "{3}{G}", 4, 4,
            keywords={"trample"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=PumpSelfUntilEOT(power_bonus=1),
                ),
            ),
        ),
        # Eusocial Engineering: {3}{G}{G} Enchantment. Landfall → create
        # a 2/2 Robot token. Simplification: drops Warp (our warp mechanic
        # is creature-only; enchantment warps would need the flow wired
        # for non-creature permanents).
        make_enchantment(
            "Eusocial Engineering", "{3}{G}{G}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Blooming Stinger: 2/2 Deathtouch. ETB grants another creature
        # you control deathtouch UEOT. "Another" means not itself — we
        # model target selection by excluding self via resolving_source
        # isn't wired yet, so for simplicity a self-target is legal here;
        # this is a minor simplification noted for future cleanup.
        make_creature(
            "Blooming Stinger", "{1}{G}", 2, 2,
            keywords={"deathtouch"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=0, toughness_bonus=0,
                        granted_keywords=frozenset({"deathtouch"}),
                        you_control_only=True,
                    ),
                ),
            ),
        ),
        # Seedship Agrarian: 3/3 Green. Whenever this creature becomes
        # tapped, create a Lander token; Landfall — put a +1/+1 counter
        # on this creature.
        make_creature(
            "Seedship Agrarian", "{3}{G}", 3, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="becomes_tapped",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                    ),
                ),
                TriggeredAbility(
                    trigger="landfall",
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
            ),
        ),
        # Seedship Broodtender: {B}{G} 2/3. ETB mill 3; activated
        # sorcery-speed reanimate (mana + sac self). Real card says
        # "creature or Spacecraft" graveyard card — we restrict to
        # creature for now.
        make_creature(
            "Seedship Broodtender", "{B}{G}", 2, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=SelfMill(amount=3),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{3}{B}{G}"),
                        mana_str="{3}{B}{G}",
                        sacrifice_self=True,
                    ),
                    effect=ReturnCreatureFromYourGraveyardToBattlefield(),
                    sorcery_speed=True,
                ),
            ),
        ),
        # Biomechan Engineer: {G}{U} 2/2 ETB create Lander + activated
        # {8}: Draw two + create Robot token.
        make_creature(
            "Biomechan Engineer", "{G}{U}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Lander"],
                        count=1,
                    ),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{8}"), mana_str="{8}"
                    ),
                    effect=Sequence(effects=(
                        DrawCards(amount=2),
                        CreateToken(
                            token_printing=TOKEN_PRINTINGS["Robot"],
                            count=1,
                        ),
                    )),
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
        # Honor: "Put a +1/+1 counter on target creature. Draw a card."
        make_sorcery(
            "Honor", "{W}", effect=Sequence(effects=(
                PutPlusOneCounterOnTargetCreature(amount=1),
                DrawCards(amount=1),
            )),
        ),
        # Decode Transmissions: "You draw two cards and lose 2 life.
        # Void — instead you draw two cards and each opponent loses 2 life."
        # Modeled as: always draw 2; life-loss switches based on Void.
        make_sorcery(
            "Decode Transmissions", "{2}{B}",
            effect=Sequence(effects=(
                DrawCards(amount=2),
                ConditionalIfVoid(
                    then_effect=EachOpponentLosesLife(amount=2),
                    else_effect=LoseLife(amount=2),
                ),
            )),
        ),
        # Hymn of the Faller: "Surveil 1, then you draw a card and lose 1
        # life. Void — draw another card."
        make_sorcery(
            "Hymn of the Faller", "{1}{B}",
            effect=Sequence(effects=(
                Surveil(amount=1),
                DrawCards(amount=1),
                LoseLife(amount=1),
                ConditionalIfVoid(then_effect=DrawCards(amount=1)),
            )),
        ),
        # Sami's Curiosity: "You gain 2 life. Create a Lander token."
        make_sorcery(
            "Sami's Curiosity", "{G}",
            effect=Sequence(effects=(
                GainLife(amount=2),
                CreateToken(
                    token_printing=TOKEN_PRINTINGS["Lander"],
                    count=1,
                ),
            )),
        ),
        # Tragic Trajectory: "Target creature gets -2/-2 UEOT. Void — That
        # creature gets -10/-10 UEOT instead..."
        make_sorcery(
            "Tragic Trajectory", "{B}",
            effect=ConditionalIfVoid(
                then_effect=PumpTargetCreatureUntilEOT(
                    power_bonus=-10, toughness_bonus=-10,
                ),
                else_effect=PumpTargetCreatureUntilEOT(
                    power_bonus=-2, toughness_bonus=-2,
                ),
            ),
        ),
        # Zealous Display: "Creatures you control get +2/+0 until end of
        # turn. If it's not your turn, untap those creatures." We ship
        # the pump part; the conditional untap rider (a niche combat
        # trick) is flagged and skipped for now.
        make_instant(
            "Zealous Display", "{2}{W}",
            effect=PumpCreaturesYouControlUntilEOT(
                power_bonus=2, toughness_bonus=0,
            ),
        ),
        # Rig for War: "Target creature gets +3/+0 and gains first strike
        # and reach until end of turn."
        make_instant(
            "Rig for War", "{1}{R}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=3, toughness_bonus=0,
                granted_keywords=frozenset({"first strike", "reach"}),
            ),
        ),
        # Dual-Sun Technique: "Target creature you control gains double
        # strike until end of turn." Real card also has a "If it has a
        # +1/+1 counter on it, draw a card" rider — skipped here (would
        # need conditional-draw-based-on-target-state).
        make_instant(
            "Dual-Sun Technique", "{1}{W}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=0, toughness_bonus=0,
                granted_keywords=frozenset({"double strike"}),
                you_control_only=True,
            ),
        ),
        # Desculpting Blast — real card says "nonland permanent"; we
        # simplify to creatures only. The "if it was attacking, create
        # a Drone token" rider is also skipped.
        make_instant(
            "Desculpting Blast", "{1}{U}",
            effect=ReturnTargetCreatureToOwnersHand(),
        ),
        # Emergency Eject — destroy any nonland permanent; its controller
        # creates a Lander token as consolation ramp.
        make_instant(
            "Emergency Eject", "{2}{W}",
            effect=DestroyTargetNonlandPermanentWithLanderForController(),
        ),
        # Radiant Strike — destroy an artifact or a tapped creature, and
        # gain 3 life as a rider.
        make_instant(
            "Radiant Strike", "{3}{W}",
            effect=Sequence(effects=(
                DestroyTargetArtifactOrTappedCreature(),
                GainLife(amount=3),
            )),
        ),
        # Depressurize — -3/-0 UEOT + if power <=0, destroy.
        make_instant(
            "Depressurize", "{1}{B}",
            effect=DepressurizeEffect(power_penalty=3),
        ),
        # Annul — counter target artifact or enchantment spell. Uses the
        # new "stack" target kind.
        make_instant(
            "Annul", "{U}",
            effect=CounterTargetSpell(
                filter_types=frozenset({"Artifact", "Enchantment"})
            ),
        ),
        # Cerebral Download — Surveil X + draw 3. X = your artifact count.
        make_instant(
            "Cerebral Download", "{4}{U}",
            effect=Sequence(effects=(
                Surveil(use_artifact_count=True),
                DrawCards(amount=3),
            )),
        ),
        # Ruinous Rampage — modal: 3 to each opponent OR mass-exile small
        # artifacts.
        make_sorcery(
            "Ruinous Rampage", "{1}{R}{R}",
            effect=ModalChooseOne(modes=(
                DealDamageEachOpponent(amount=3),
                ExileAllArtifactsWithManaValueAtMost(max_mv=3),
            )),
        ),
        # Drill Too Deep — modal: charge counters on a Spacecraft you
        # control OR destroy target artifact. "Planet" mode simplified out.
        make_instant(
            "Drill Too Deep", "{1}{R}",
            effect=ModalChooseOne(modes=(
                PutChargeCountersOnTargetSpacecraftYouControl(amount=5),
                DestroyTargetArtifact(),
            )),
        ),
        # Reroute Systems — modal instant. Simplifications: first mode
        # says "target artifact or creature" (we restrict to creature),
        # second mode says "target tapped creature" (we drop the tapped
        # restriction). Both still resolve via the creature target kind.
        make_instant(
            "Reroute Systems", "{W}",
            effect=ModalChooseOne(modes=(
                PumpTargetCreatureUntilEOT(
                    granted_keywords=frozenset({"indestructible"}),
                ),
                DealDamageToTargetCreature(amount=2),
            )),
        ),
        # Mental Modulation — tap target artifact or creature, then draw a
        # card. Skips the "costs {1} less during your turn" rider (cost
        # modification during casting isn't modeled yet).
        make_instant(
            "Mental Modulation", "{1}{U}",
            effect=Sequence(effects=(
                TapTargetArtifactOrCreature(),
                DrawCards(amount=1),
            )),
        ),
        # Shattered Wings — destroy artifact/enchantment/creature-with-flying,
        # then Surveil 1.
        make_sorcery(
            "Shattered Wings", "{2}{G}",
            effect=Sequence(effects=(
                DestroyTargetArtifactEnchantmentOrFlyingCreature(),
                Surveil(amount=1),
            )),
        ),
        # Space-Time Anomaly — target player mills cards equal to YOUR life.
        make_sorcery(
            "Space-Time Anomaly", "{2}{W}{U}",
            effect=MillTargetPlayer(use_controller_life=True),
        ),
        # Beyond the Quiet — wrath variant that exiles all creatures AND
        # Spacecraft (dodges Fires-of-Vengeance style "when dies" triggers).
        make_sorcery(
            "Beyond the Quiet", "{3}{W}{W}",
            effect=ExileAllCreaturesAndSpacecraft(),
        ),
        # Singularity Rupture — simplified to just "destroy all creatures".
        # Dropped: the "any number of target players each mill half their
        # library" rider (multi-target player selection not supported).
        make_sorcery(
            "Singularity Rupture", "{3}{U}{B}{B}",
            effect=DestroyAllCreatures(),
        ),
        # Focus Fire — combat damage spike: 2 + your creatures/Spacecraft.
        make_instant(
            "Focus Fire", "{W}",
            effect=FocusFireEffect(base=2),
        ),
        # Cut Propulsion — creature self-damage; flying 2x (anti-air blast).
        make_instant(
            "Cut Propulsion", "{2}{R}",
            effect=CutPropulsionEffect(),
        ),
        # Invasive Maneuvers — 3 damage burst, 5 with a Spacecraft.
        make_instant(
            "Invasive Maneuvers", "{1}{R}",
            effect=DealDamageToTargetCreatureSpacecraftBoosted(
                base=3, boosted=5
            ),
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
    """60 cards: 24 basics of the chosen color + 36 non-land cards in that color.

    "In that color" includes colorless cards (empty ``mana_cost.colors``) since
    colorless generic costs can be paid from any basic land.
    """
    if color not in _COLOR_TO_BASIC:
        raise ValueError(f"unknown color: {color}")
    rng = random.Random(seed)
    land_name = _COLOR_TO_BASIC[color]
    creatures = [
        name
        for name, p in NONLAND_POOL.items()
        if color in p.mana_cost.colors or not p.mana_cost.colors
    ]
    if not creatures:
        raise ValueError(f"no creatures in color {color}")
    deck: list[str] = [creatures[i % len(creatures)] for i in range(36)]
    deck.extend([land_name] * 24)
    rng.shuffle(deck)
    return deck
