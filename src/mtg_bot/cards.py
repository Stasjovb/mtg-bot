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
    ConditionalIfSourcePowerAtLeast,
    ConditionalIfVoid,
    ControlTargetOpponentNextTurn,
    ConditionalOnTappedCreatures,
    CounterTargetSpell,
    CreateToken,
    DealDamageAnyTarget,
    DealDamageEachOpponent,
    DefendingPlayerLosesHalfLifeRoundedUp,
    DealDamageToOpponentCreature,
    DealDamageToOpponentCreatureByArtifactCount,
    DealDamageToTargetCreature,
    DestroyAllCreatures,
    DestroyTargetArtifact,
    DestroyTargetCreature,
    DestroyTargetNonlandPermanent,
    ExileOpponentsNonlandPermanentUntilLeaves,
    ChoraleReanimateDefenderGraveCreatureEffect,
    KavaronHarrierAttackEffect,
    PainForAllDamageEchoEffect,
    PainForAllETBEffect,
    MemorialVaultActivatedEffect,
    PossibilityTechnicianETBEffect,
    TerritorialBruntarLandfallEffect,
    TractorBeamETBEffect,
    SacrificeSelfUnlessVoidActive,
    WeftwalkingETBEffect,
    PinnacleStarcageETBEffect,
    SotheraEndStepReanimateEffect,
    SotheraExileOpponentCreatureEffect,
    PinnacleStarcageSacEffect,
    RequiemMonolithActivatedEffect,
    RovingActuatorETBEffect,
    PutStunCounterOnTappedCreature,
    TapTargetOpponentPermanentAndStunIt,
    ExileTargetCreatureUntilSourceLeaves,
    SeedshipImpactEffect,
    MoveSelfCountersToTargetCreatureYouControl,
    UntapTargetOtherPermanent,
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    PutChargeCountersOnTargetSpacecraftYouControl,
    DiscardSelf,
    DrawCards,
    DrawCardsEqualToResolvingCombatDamage,
    DrawCardsEqualToResolvingCounterAmount,
    EachOpponentDiscards,
    EachOpponentSacrificesCreature,
    EachOpponentLosesLife,
    EachPlayerDraws,
    Effect,
    ExileEachOpponentsGraveyard,
    ExileTargetCreature,
    GainLife,
    IfGainedLifeThisTurnUntapSelf,
    LoseLife,
    PutCardFromGraveyardOnBottomOfLibrary,
    PumpCreaturesYouControlUntilEOT,
    PutPlusOneCounterOnOpponentsCreature,
    PumpSelfUntilEOT,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnTargetCreature,
    PutPoisonCountersOnTargetPlayer,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnTargetCreatureToOwnersHand,
    ReturnTargetPermanentYouControlToOwnersHand,
    ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
    ReturnUpToNTargetCreaturesToOwnersHands,
    DestroyTargetNonlandPermanentWithLanderForController,
    DestroyTargetArtifactOrTappedCreature,
    TapAnotherTargetCreature,
    TapTargetArtifactOrCreature,
    DepressurizeEffect,
    DestroyTargetArtifactEnchantmentOrFlyingCreature,
    CutPropulsionEffect,
    DealDamageToTargetCreatureSpacecraftBoosted,
    DealDamageToTargetCreatureWithExcessLanderRider,
    ExileAllArtifactsWithManaValueAtMost,
    AnticausalVestigeLeavesEffect,
    AddManaToPool,
    AllFatesScrollDrawEffect,
    AstelliReclaimerETBEffect,
    AtomicMicrosizerAttackEffect,
    AttachToTargetCreatureYouControl,
    BiosynthicBurstEffect,
    CreateLanderAndScheduleSacrifice,
    CreateTokenAndAttachSelf,
    CloseEncounterEffect,
    ConsultTheStarChartsEffect,
    CreateTokenPerMulticoloredPermanent,
    DrawCardPerMulticoloredPermanent,
    DyadrineAttackEffect,
    EachOpponentDiscardsOrLosesLife,
    FamishedWorldsireETBEffect,
    PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    OptionalSacLandOrLanderForBasicLandRamp,
    OptionalPutCreatureFromHandOntoBattlefield,
    CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    DealNDamageToEachCreature,
    DestroyTargetNoncreaturePermanent,
    DiscardHandThenDrawN,
    DoubleTargetCreaturesPowerUEOT,
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    TargetOpponentLosesNYouGainN,
    TargetPlayerLosesLife,
    ExileAllCreaturesAndSpacecraft,
    OptionalSacArtifactForEffect,
    PumpTargetOtherArtifactYouControlUEOT,
    PutLoyaltyCounterOnSelf,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
    SetLifeToHalfStartingRoundedUp,
    SingularityRuptureEffect,
    SystemsOverrideEffect,
    TerrapactIntimidatorETBEffect,
    ZeroPointBalladEffect,
    ModalChooseOne,
    MonoistCircuitFeederETBEffect,
    FocusFireEffect,
    OptionalSacAnotherForEffect,
    OptionalSacAnotherForPumpSelfUEOT,
    SelfMill,
    MillTargetPlayer,
    SearchLibraryForBasicLandTapped,
    SearchLibraryForCard,
    SelfcraftMechanETBEffect,
    TannukEnsignLandfallEffect,
    Sequence,
    StaticAbility,
    StaticScope,
    LookAtTopNRevealOrCounter,
    LookAtTopTwoSplitHandGraveyard,
    MutinousMassacreEffect,
    Surveil,
    TargetOpponentDiscards,
    TargetOpponentDiscardsCasterChoice,
    TriggeredAbility,
)


COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")


@dataclass(frozen=True)
class ManaCost:
    generic: int = 0
    colored: tuple[tuple[str, int], ...] = ()
    # Number of {X} symbols in the printed cost. The actual generic mana
    # paid at cast time is ``generic + x_pips * X`` where X is the
    # caster's chosen value. Stored separately so a card's "templated"
    # cost stays distinct from its paid cost.
    x_pips: int = 0

    @property
    def total(self) -> int:
        return self.generic + sum(n for _, n in self.colored)

    @property
    def colors(self) -> frozenset[str]:
        return frozenset(c for c, _ in self.colored)

    def reduced(self, amount: int) -> "ManaCost":
        """Return a new ManaCost with ``amount`` generic mana removed
        (minimum 0; colored costs unchanged — MTG rule 601.2f)."""
        if amount <= 0:
            return self
        return ManaCost(
            generic=max(0, self.generic - amount),
            colored=self.colored,
        )


@dataclass(frozen=True)
class CostReduction:
    """A rule that reduces the generic-mana portion of a spell's cost.

    ``condition`` names a known predicate checked against game state
    at cast time. ``amount`` is the flat generic reduction; when
    ``per_land_group`` is True the amount is multiplied by the number
    of differently-named lands the caster controls (Fungal Colossus).

    Adding a new condition requires a matching branch in
    ``apply_cost_reductions`` (actions.py).
    """

    amount: int
    condition: str
    per_land_group: bool = False


def parse_mana_cost(s: str) -> ManaCost:
    if not s:
        return ManaCost()
    generic = 0
    colored: dict[str, int] = {}
    x_pips = 0
    for sym in re.findall(r"\{([^}]+)\}", s):
        if sym.isdigit():
            generic += int(sym)
        elif sym in COLORS:
            colored[sym] = colored.get(sym, 0) + 1
        elif sym == "C":
            generic += 1
        elif sym == "X":
            x_pips += 1
        else:
            raise ValueError(f"unsupported mana symbol: {{{sym}}}")
    return ManaCost(
        generic=generic,
        colored=tuple(sorted(colored.items())),
        x_pips=x_pips,
    )


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
    # "Kicker {cost}" — an optional additional mana cost the caster may
    # pay while casting. If paid, the StackItem is marked kicked and
    # the resolving effect can branch on state.resolving_kicked.
    kicker_cost: ManaCost | None = None
    kicker_cost_str: str = ""
    # Planeswalker starting loyalty. None on non-planeswalkers. When
    # the planeswalker enters the battlefield it starts with this many
    # loyalty counters on it (GameObject.loyalty_counters).
    loyalty: int | None = None
    # Devour land N: "As this creature enters, you may sacrifice any
    # number of lands. It enters with N times that many +1/+1 counters
    # on it." Non-zero enables the replacement in put_into_battlefield.
    # 0 = no devour. Matches Famished Worldsire (N=3).
    devour_land_multiplier: int = 0
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
    # "You may play an additional land on each of your turns." Non-zero
    # value contributes to the land-per-turn cap via legal_actions.
    # Icetill Explorer has this at 1.
    grants_additional_land_per_turn: int = 0
    # "If a permanent entering the battlefield causes a triggered
    # ability of a permanent you control to trigger, that ability
    # triggers an additional time." Starfield Vocalist. Summed across
    # permanents the acting player controls by etb_trigger_multiplier
    # — each one adds 1 extra firing.
    extra_etb_trigger: int = 0
    # "Enchanted/equipped permanent doesn't untap during its
    # controller's untap step." Tractor Beam's don't-untap clause.
    # When True on an aura/equipment attached to a permanent, the
    # untap step skips that permanent.
    attached_prevents_untap: bool = False
    # "The first time you would create one or more tokens each turn,
    # you may instead create that many tokens that are copies of
    # enchanted permanent." Moonlit Meditation. Aura-only flag.
    replaces_first_tokens_with_copies: bool = False
    # "You may cast artifact spells from the top of your library."
    # Mm'menon, the Right Hand. legal_actions offers a CastSpell for
    # the controller's top-of-library card when it's an artifact and
    # this flag is present on any permanent they control.
    grants_cast_artifact_from_top_of_library: bool = False
    # "Artifacts you control are Foods in addition to their other
    # types." Ragost, Deft Gastronaut. Consumed by
    # game.effective_subtypes to inject "Food" into artifact subtypes.
    grants_food_to_your_artifacts: bool = False
    # "Artifacts you control have '{2}, {T}, Sacrifice this artifact:
    # You gain 3 life.'" Ragost's companion ability-grant clause.
    # Consumed by game.effective_activated_abilities to append the
    # pre-built RAGOST_FOOD_GRANTED_ABILITY to artifact activations.
    grants_food_ability_to_your_artifacts: bool = False
    # Equipment flag. When this equipment is attached to a creature,
    # that creature gains an activated ability to control the next
    # turn of a target opponent (The Dominion Bracelet). The full
    # ability is DOMINION_BRACELET_GRANTED_ABILITY.
    grants_control_opponent_ability_when_equipped: bool = False
    # Ward—Discard a card at random (non-mana ward). Alpharael, Stonechosen.
    # When True, the caster must randomly discard a card to pay the ward;
    # if their hand is empty, the spell is countered.
    ward_discard_random: bool = False
    # Equipment: continuous bonuses granted to the equipped creature.
    # Tuple (power_bonus, toughness_bonus, granted_keywords). None on
    # non-Equipment cards. Consumed by game._static_bonuses.
    equipment_bonuses: tuple[int, int, frozenset[str]] | None = None
    # Shock-land-style optional ETB life cost. When nonzero, _play_land
    # asks the controller's agent whether to pay; yes pays the life and
    # enters untapped, no enters tapped. 0 means "no choice — enters
    # per its usual rules".
    shock_land_life_cost: int = 0
    # When True, this card always enters the battlefield tapped
    # (Planet-style utility lands and other "enters tapped" permanents).
    enters_tapped: bool = False
    # Additional cost to cast: sacrifice a creature or artifact the
    # caster controls (other than any source-of-the-spell). Matches
    # Embrace Oblivion's "As an additional cost to cast this spell,
    # sacrifice an artifact or creature."
    additional_cost_sacrifice_creature_or_artifact: bool = False
    # Additional cost to cast: designate one of your creatures. The
    # chosen creature's id is stored on the StackItem and exposed via
    # state.resolving_additional_cost_choice_id for the effect to use
    # (e.g. Close Encounter's damage-equal-to-power).
    additional_cost_choose_your_creature: bool = False
    # Cost reductions: rules that lower this spell's generic mana cost
    # when specific conditions hold at cast time (e.g., "costs {3} less
    # if you've cast another spell this turn"). Consumed by
    # actions.apply_cost_reductions().
    cost_reductions: tuple[CostReduction, ...] = ()
    # Continuous abilities that buff other permanents while this permanent
    # is on the battlefield (anthems, keyword grants).
    static_abilities: tuple[StaticAbility, ...] = ()
    # Abilities the controller may activate by paying a cost.
    activated_abilities: tuple["ActivatedAbility", ...] = ()
    # "Enters with +1/+1 counters" replacement effects tied to the cast-time
    # choice of X. Consumed by actions.put_into_battlefield.
    #   ``"x"`` — enters with state.resolving_x_value counters (Broodguard).
    #   ``"mana_spent"`` — enters with counters equal to total mana paid,
    #     i.e. X + base generic + colored pips (Dyadrine).
    #   None — no such replacement.
    enters_with_counters_from_x: str | None = None
    # Aura enchant restriction. Auras default to enchanting creatures;
    # Hardlight Containment enchants artifacts (and our machinery
    # wouldn't find a legal target otherwise). Accepts "creature" or
    # "artifact". Only consumed when is_aura is True.
    aura_enchant_type: str = "creature"
    # Dynamic power/toughness formula. When set, overrides the printed
    # power/toughness inside effective_power and effective_toughness.
    # Currently supported:
    #   "cosmogoyf": power = number of cards the controller owns in
    #     exile; toughness = that number + 1.
    #   "harmonious_grovestrider": power = toughness = number of lands
    #     the controller controls.
    #   "emissary_escort": +X/+0 where X is the greatest mana value
    #     among OTHER artifacts the controller controls; base stays
    #     printed (0/4).
    # None = use printed P/T (default).
    dynamic_pt_formula: str | None = None
    # Replacement-effect flag: when any permanent with this flag is on
    # the battlefield under the token-creator's control, the number of
    # tokens created is doubled. Matches Exalted Sunborn.
    is_token_doubler: bool = False
    # Replacement-effect flag: when any permanent with this flag is on
    # the battlefield under the counter-recipient's control, +1/+1
    # counters going onto creatures (and Spacecraft) they control are
    # doubled. Matches Loading Zone. Multiple doublers stack
    # multiplicatively via add_plus_one_counters().
    is_counter_doubler: bool = False

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
    def is_aura(self) -> bool:
        return "Aura" in self.subtypes

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

    @property
    def is_planeswalker(self) -> bool:
        return "Planeswalker" in self.card_types


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
    ward_discard_random: bool = False,
    grants_additional_land_per_turn: int = 0,
    extra_etb_trigger: int = 0,
    grants_cast_artifact_from_top_of_library: bool = False,
    grants_food_to_your_artifacts: bool = False,
    grants_food_ability_to_your_artifacts: bool = False,
    artifact: bool = False,
    cost_reductions: tuple[CostReduction, ...] = (),
    enters_with_counters_from_x: str | None = None,
    subtypes: tuple[str, ...] = (),
    dynamic_pt_formula: str | None = None,
    is_token_doubler: bool = False,
    devour_land_multiplier: int = 0,
) -> CardPrinting:
    prefix = "Legendary " if legendary else ""
    artifact_word = "Artifact " if artifact else ""
    subtype_suffix = f" — {' '.join(subtypes)}" if subtypes else ""
    type_line = f"{prefix}{artifact_word}Creature{subtype_suffix}"
    supertypes, card_types, parsed_subtypes = _parse_type_line(type_line)
    subtypes = parsed_subtypes
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
        ward_discard_random=ward_discard_random,
        grants_additional_land_per_turn=grants_additional_land_per_turn,
        extra_etb_trigger=extra_etb_trigger,
        grants_cast_artifact_from_top_of_library=(
            grants_cast_artifact_from_top_of_library
        ),
        grants_food_to_your_artifacts=grants_food_to_your_artifacts,
        grants_food_ability_to_your_artifacts=(
            grants_food_ability_to_your_artifacts
        ),
        triggered_abilities=tuple(triggered_abilities),
        static_abilities=tuple(static_abilities),
        activated_abilities=tuple(activated_abilities),
        warp_cost=parse_mana_cost(warp) if warp else None,
        warp_cost_str=warp or "",
        cost_reductions=tuple(cost_reductions),
        enters_with_counters_from_x=enters_with_counters_from_x,
        dynamic_pt_formula=dynamic_pt_formula,
        is_token_doubler=is_token_doubler,
        devour_land_multiplier=devour_land_multiplier,
    )


def cost(
    mana: str = "",
    tap_self: bool = False,
    sacrifice_self: bool = False,
    remove_plus_one_counter_from_your_creature: bool = False,
) -> ActivationCost:
    """Small constructor for ``ActivationCost`` that handles mana parsing."""
    return ActivationCost(
        remove_plus_one_counter_from_your_creature=(
            remove_plus_one_counter_from_your_creature
        ),
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


def make_instant(
    name: str, cost: str, effect: Effect,
    cost_reductions: tuple[CostReduction, ...] = (),
    kicker: str | None = None,
    additional_cost_choose_your_creature: bool = False,
) -> CardPrinting:
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
        cost_reductions=tuple(cost_reductions),
        kicker_cost=parse_mana_cost(kicker) if kicker else None,
        kicker_cost_str=kicker or "",
        additional_cost_choose_your_creature=(
            additional_cost_choose_your_creature
        ),
    )


def make_sorcery(
    name: str, cost: str, effect: Effect,
    cost_reductions: tuple[CostReduction, ...] = (),
    additional_cost_sacrifice_creature_or_artifact: bool = False,
) -> CardPrinting:
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
        cost_reductions=tuple(cost_reductions),
        additional_cost_sacrifice_creature_or_artifact=(
            additional_cost_sacrifice_creature_or_artifact
        ),
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


def make_equipment(
    name: str,
    cost: str,
    power_bonus: int = 0,
    toughness_bonus: int = 0,
    granted_keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
    keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
    activated_abilities: tuple[ActivatedAbility, ...] = (),
    grants_control_opponent_ability_when_equipped: bool = False,
    legendary: bool = False,
) -> CardPrinting:
    """Build an Artifact — Equipment card.

    ``power_bonus``/``toughness_bonus``/``granted_keywords`` define the
    continuous bonus granted to the equipped creature via the Equipment
    subsystem. ``keywords`` are on the Equipment itself (e.g., Flash).
    Most EoE Equipment cards have an ETB "attach to target creature you
    control" trigger and no Equip activated ability in our simplified
    model (Equip as an activated ability isn't yet wired).
    """
    prefix = "Legendary " if legendary else ""
    type_line = f"{prefix}Artifact — Equipment"
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
        activated_abilities=tuple(activated_abilities),
        grants_control_opponent_ability_when_equipped=(
            grants_control_opponent_ability_when_equipped
        ),
        equipment_bonuses=(
            power_bonus, toughness_bonus, frozenset(granted_keywords)
        ),
    )


def make_aura(
    name: str,
    cost: str,
    power_bonus: int = 0,
    toughness_bonus: int = 0,
    granted_keywords: frozenset[str] | set[str] | tuple[str, ...] = (),
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
    aura_enchant_type: str = "creature",
    attached_prevents_untap: bool = False,
    replaces_first_tokens_with_copies: bool = False,
) -> CardPrinting:
    """Build an Enchantment — Aura card that attaches to a creature.

    ``power_bonus``/``toughness_bonus``/``granted_keywords`` define the
    continuous bonus granted to the enchanted creature; we reuse the
    Equipment bonus machinery (equipment_bonuses) so effective_* helpers
    pick them up automatically.

    Simplified Aura behavior: cast-time target must be a creature; on
    resolution the Aura enters attached to that target (or goes to the
    graveyard if the target is no longer legal). When the enchanted
    creature leaves the battlefield, the Aura is sent to the graveyard
    (unlike Equipment, which falls off but stays).
    """
    type_line = "Enchantment — Aura"
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
        equipment_bonuses=(
            power_bonus, toughness_bonus, frozenset(granted_keywords)
        ),
        aura_enchant_type=aura_enchant_type,
        attached_prevents_untap=attached_prevents_untap,
        replaces_first_tokens_with_copies=replaces_first_tokens_with_copies,
    )


def make_planeswalker(
    name: str,
    cost: str,
    loyalty: int,
    subtype: str,
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
    static_abilities: tuple[StaticAbility, ...] = (),
    activated_abilities: tuple[ActivatedAbility, ...] = (),
    legendary: bool = True,
) -> CardPrinting:
    """Build a Legendary Planeswalker card. Loyalty is the printed
    starting loyalty; it initializes ``GameObject.loyalty_counters``
    when the planeswalker enters the battlefield. SBAs send it to
    graveyard at 0 loyalty.

    Simplifications: loyalty-activated abilities aren't modeled yet
    (Tezzeret's 0/−3/−7 abilities are dropped); damage redirection
    to planeswalkers isn't modeled; attacking a planeswalker isn't
    modeled. Triggered abilities on the walker still fire normally.
    """
    prefix = "Legendary " if legendary else ""
    type_line = f"{prefix}Planeswalker — {subtype}"
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
        loyalty=loyalty,
    )


def make_enchantment(
    name: str,
    cost: str,
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
    static_abilities: tuple[StaticAbility, ...] = (),
    activated_abilities: tuple[ActivatedAbility, ...] = (),
    legendary: bool = False,
    is_counter_doubler: bool = False,
    is_token_doubler: bool = False,
    warp: str | None = None,
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
        is_counter_doubler=is_counter_doubler,
        is_token_doubler=is_token_doubler,
        warp_cost=parse_mana_cost(warp) if warp else None,
        warp_cost_str=warp or "",
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


def make_planet_land(
    name: str, color: str,
) -> CardPrinting:
    """EoE Planet land: enters tapped, taps for a single color.
    Simplification: drops the Station mechanic and all tiered abilities
    (Planets with Station are functionally a non-creature Spacecraft —
    not modeled for Planets here).
    """
    type_line = f"Land — Planet"
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
        enters_tapped=True,
    )


def make_colorless_land(
    name: str, subtypes_str: str = "", legendary: bool = False,
) -> CardPrinting:
    """A non-basic land that taps for {C} only. Useful for utility
    lands whose activated abilities aren't modeled — taps-for-generic
    still works via auto_tap_for_cost's generic-mana fallback.
    """
    prefix = "Legendary " if legendary else ""
    type_line = (
        f"{prefix}Land — {subtypes_str}" if subtypes_str else f"{prefix}Land"
    )
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        produces=frozenset(),  # generic-only
    )


def make_shock_land(
    name: str, colors: tuple[str, str], subtypes_str: str,
    life_cost: int = 2,
) -> CardPrinting:
    """Build a shock-land-style dual. ``subtypes_str`` is the type-line
    suffix (e.g. "Forest Island"). The land produces both ``colors`` and
    enters tapped unless the controller pays ``life_cost`` life on ETB.
    """
    type_line = f"Land — {subtypes_str}"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        produces=frozenset(colors),
        shock_land_life_cost=life_cost,
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


# Shock-land cycle from EoE. Each is Land — L1 L2 producing both colors,
# "As this land enters, you may pay 2 life. If you don't, it enters
# tapped."
PLANET_LANDS: dict[str, CardPrinting] = {
    "Adagia, Windswept Bastion": make_planet_land(
        "Adagia, Windswept Bastion", "W",
    ),
    "Uthros, Titanic Godcore": make_planet_land(
        "Uthros, Titanic Godcore", "U",
    ),
    "Susur Secundi, Void Altar": make_planet_land(
        "Susur Secundi, Void Altar", "B",
    ),
    "Kavaron, Memorial World": make_planet_land(
        "Kavaron, Memorial World", "R",
    ),
    "Evendo, Waking Haven": make_planet_land(
        "Evendo, Waking Haven", "G",
    ),
}


UTILITY_LANDS: dict[str, CardPrinting] = {
    # Secluded Starforge: simplified to just a {T}: Add {C} utility
    # land. Dropped: the "{2},{T}, Tap X artifacts: +X/+0 UEOT" and
    # "{5},{T}: create a Robot token" activated abilities (tap-X-things
    # cost + Robot-token activated not worth wiring for one card).
    "Secluded Starforge": make_colorless_land("Secluded Starforge"),
    # Command Bridge: simplified to just a {T}: Add {C} utility land.
    # Dropped: "enters tapped + sac-unless-tap-permanent" ETB (ETB
    # replacement with an alt cost isn't modeled) and the "tap for
    # any color" rider.
    "Command Bridge": make_colorless_land("Command Bridge"),
}


SHOCK_LANDS: dict[str, CardPrinting] = {
    "Breeding Pool": make_shock_land(
        "Breeding Pool", ("G", "U"), "Forest Island",
    ),
    "Godless Shrine": make_shock_land(
        "Godless Shrine", ("W", "B"), "Plains Swamp",
    ),
    "Sacred Foundry": make_shock_land(
        "Sacred Foundry", ("R", "W"), "Mountain Plains",
    ),
    "Stomping Ground": make_shock_land(
        "Stomping Ground", ("R", "G"), "Mountain Forest",
    ),
    "Watery Grave": make_shock_land(
        "Watery Grave", ("U", "B"), "Island Swamp",
    ),
}


# Edge of Eternities: Stellar Sights (Scryfall set `eos`). Bonus-sheet
# reprints of 45 famous Magic lands included in EoE boosters. Each
# entry below starts as a colorless-only stand-in (`# dropped X` per
# the same pattern used to track EOE_CREATURES restoration progress);
# incremental branches restore the real oracle ability.
STELLAR_SIGHTS_LANDS: dict[str, CardPrinting] = {
    "Ancient Tomb": make_colorless_land(  # dropped {T}: Add {C}{C}. Deals 2 to you.
        "Ancient Tomb",
    ),
    "Blast Zone": make_colorless_land(  # dropped enters-with-counters + sac-mass-destroy.
        "Blast Zone",
    ),
    "Blinkmoth Nexus": make_colorless_land(  # dropped manland activation.
        "Blinkmoth Nexus",
    ),
    "Bonders' Enclave": make_colorless_land(  # dropped draw-if-4+-power.
        "Bonders' Enclave",
    ),
    "Cascading Cataracts": make_colorless_land(  # dropped 5-color rainbow + all-five activated.
        "Cascading Cataracts",
    ),
    "Cathedral of War": make_colorless_land(  # dropped Exalted.
        "Cathedral of War",
    ),
    "Celestial Colonnade": make_colorless_land(  # dropped manland activation (enters tapped too).
        "Celestial Colonnade",
    ),
    "Contested War Zone": make_colorless_land(  # dropped attackers-get-+1/+0 + gain-control.
        "Contested War Zone",
    ),
    "Creeping Tar Pit": make_colorless_land(  # dropped manland activation + unblockable.
        "Creeping Tar Pit",
    ),
    "Crystal Quarry": make_colorless_land(  # dropped pay-5-to-add-WUBRG activated.
        "Crystal Quarry",
    ),
    "Deserted Temple": make_colorless_land(  # dropped untap-target-land activated.
        "Deserted Temple",
    ),
    "Dust Bowl": make_colorless_land(  # dropped sac-land-for-destroy-nonbasic.
        "Dust Bowl",
    ),
    "Echoing Deeps": make_colorless_land(  # dropped ETB choose-to-become-copy.
        "Echoing Deeps", subtypes_str="Cave",
    ),
    "Eldrazi Temple": make_colorless_land(  # dropped tap-for-2-when-casting-Eldrazi.
        "Eldrazi Temple",
    ),
    "Endless Sands": make_colorless_land(  # dropped exile-creature-return activated.
        "Endless Sands", subtypes_str="Desert",
    ),
    "Gemstone Caverns": make_colorless_land(  # dropped opening-hand luck-counter + any-color.
        "Gemstone Caverns", legendary=True,
    ),
    "Grove of the Burnwillows": make_colorless_land(  # dropped {T}: Add {R} or {G}; each opp gains 1.
        "Grove of the Burnwillows",
    ),
    "High Market": make_colorless_land(  # dropped sac-creature-gain-1.
        "High Market",
    ),
    "Hissing Quagmire": make_colorless_land(  # dropped manland deathtouch.
        "Hissing Quagmire",
    ),
    "Inkmoth Nexus": make_colorless_land(  # dropped manland flying + infect.
        "Inkmoth Nexus",
    ),
    "Inventors' Fair": make_colorless_land(  # dropped gain-1-upkeep + tutor-artifact activated.
        "Inventors' Fair", legendary=True,
    ),
    "Lavaclaw Reaches": make_colorless_land(  # dropped manland + X/1 pump.
        "Lavaclaw Reaches",
    ),
    "Lotus Field": make_colorless_land(  # dropped ETB-sac-two-lands + tap-for-3-any.
        "Lotus Field",
    ),
    "Lumbering Falls": make_colorless_land(  # dropped manland hexproof.
        "Lumbering Falls",
    ),
    "Mana Confluence": make_colorless_land(  # dropped pay-1-for-any-color.
        "Mana Confluence",
    ),
    "Meteor Crater": make_colorless_land(  # dropped tap-for-color-of-creature-you-control.
        "Meteor Crater",
    ),
    "Mirrorpool": make_colorless_land(  # dropped copy-spell / copy-creature activated.
        "Mirrorpool",
    ),
    "Mutavault": make_colorless_land(  # dropped manland X/X-creature-type.
        "Mutavault",
    ),
    "Mystifying Maze": make_colorless_land(  # dropped exile-attacker-return-EoT activated.
        "Mystifying Maze",
    ),
    "Needle Spires": make_colorless_land(  # dropped manland double strike (enters tapped too).
        "Needle Spires",
    ),
    "Nesting Grounds": make_colorless_land(  # dropped move-a-counter-from-X-to-Y activated.
        "Nesting Grounds",
    ),
    "Petrified Field": make_colorless_land(  # dropped return-land-from-graveyard activated.
        "Petrified Field",
    ),
    "Plaza of Heroes": make_colorless_land(  # dropped legendary-tribal + pay-2-any.
        "Plaza of Heroes",
    ),
    # Power Depot is an Artifact Land — both card types. Built inline
    # so the card_types tuple is ("Artifact", "Land") instead of the
    # make_colorless_land default ("Land",).
    "Power Depot": CardPrinting(
        # dropped 2-mode tap (W/U/B/R/G or {C}{C}) + artifact tribal.
        name="Power Depot",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Artifact Land",
        supertypes=(),
        card_types=("Artifact", "Land"),
        subtypes=(),
        produces=frozenset(),
    ),
    "Raging Ravine": make_colorless_land(  # dropped manland attacks-enters-counter.
        "Raging Ravine",
    ),
    "Reflecting Pool": make_colorless_land(  # dropped tap-for-color-your-lands-produce.
        "Reflecting Pool",
    ),
    "Scavenger Grounds": make_colorless_land(  # dropped sac-Desert-exile-graveyards activated.
        "Scavenger Grounds", subtypes_str="Desert",
    ),
    "Shambling Vent": make_colorless_land(  # dropped manland lifelink (enters tapped too).
        "Shambling Vent",
    ),
    "Stirring Wildwood": make_colorless_land(  # dropped manland reach (enters tapped too).
        "Stirring Wildwood",
    ),
    "Strip Mine": make_colorless_land(  # dropped sac-to-destroy-target-land.
        "Strip Mine",
    ),
    "Sunken Citadel": make_colorless_land(  # dropped cave-discount-tap-for-2.
        "Sunken Citadel", subtypes_str="Cave",
    ),
    "Swarmyard": make_colorless_land(  # dropped regenerate-Rats/Spiders/etc.
        "Swarmyard",
    ),
    "Terrain Generator": make_colorless_land(  # dropped pay-2-tap-put-basic-tapped.
        "Terrain Generator",
    ),
    "Thespian's Stage": make_colorless_land(  # dropped {2},{T}: become-copy-of-target-land.
        "Thespian's Stage",
    ),
    "Wandering Fumarole": make_colorless_land(  # dropped manland swap-P-and-T.
        "Wandering Fumarole",
    ),
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


# Pre-built activated ability granted to artifacts by Ragost, Deft
# Gastronaut's static "{2}, {T}, Sacrifice this artifact: You gain 3
# life." Exposed here so game.effective_activated_abilities can append
# it without each call-site re-importing effect classes.
RAGOST_FOOD_GRANTED_ABILITY = ActivatedAbility(
    cost=ActivationCost(
        mana=parse_mana_cost("{2}"),
        mana_str="{2}",
        tap_self=True,
        sacrifice_self=True,
    ),
    effect=GainLife(amount=3),
)


# Pre-built activated ability granted to the equipped creature by
# The Dominion Bracelet: "{15}, Exile The Dominion Bracelet: You
# control target opponent during their next turn. This ability costs
# {X} less to activate, where X is this creature's power. Activate
# only as a sorcery."
DOMINION_BRACELET_GRANTED_ABILITY = ActivatedAbility(
    cost=ActivationCost(
        mana=parse_mana_cost("{15}"),
        mana_str="{15}",
        exile_granting_equipment=True,
        mana_reduced_by_source_power=True,
    ),
    effect=ControlTargetOpponentNextTurn(),
    sorcery_speed=True,
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
    # 1/1 colorless Drone artifact creature with flying. Created by
    # Pinnacle Emissary and other EoE artifact triggers. The printed
    # "can block only creatures with flying" restriction isn't
    # modeled here (block-restriction machinery would need a new
    # hook); kept as a plain flying 1/1.
    "Drone": make_token_creature(
        "Drone", 1, 1, subtypes=("Drone",), artifact=True,
        keywords=frozenset({"flying"}),
    ),
    # Lander — artifact token (not a creature) with a sacrifice-to-ramp
    # activated ability. Created by many EoE spells and triggers.
    "Lander": _make_lander_token(),
    # 1/1 colorless Sliver creature token — Thrumming Hivepool's upkeep
    # trigger.
    "Sliver": make_token_creature(
        "Sliver", 1, 1, subtypes=("Sliver",),
    ),
    # Munitions: colorless artifact token created by Weapons Manufacturing.
    # "When this token leaves the battlefield, it deals 2 damage to any
    # target." Modeled via a leaves-battlefield trigger on the token.
    "Munitions": CardPrinting(
        name="Munitions",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Token Artifact — Munitions",
        supertypes=("Token",),
        card_types=("Artifact",),
        subtypes=("Munitions",),
        triggered_abilities=(
            TriggeredAbility(
                trigger="leaves_battlefield",
                effect=DealDamageAnyTarget(amount=2),
            ),
        ),
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
        # Specimen Freighter: {5}{U} 4/7 Spacecraft. ETB return up to
        # two target creatures to their owners' hands. Station 9+ flying.
        # Simplified: dropped the "non-Spacecraft" target restriction
        # (target filter complexity), and dropped the "9+ | whenever this
        # attacks, create a copy of target permanent" tiered trigger.
        make_spacecraft(
            "Specimen Freighter", "{5}{U}", 4, 7,
            station_threshold=9,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ReturnUpToNTargetCreaturesToOwnersHands(max_n=2),
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
        # All-Fates Stalker: {3}{W} 2/3 Drix Assassin. ETB exile target
        # non-Assassin creature until Stalker leaves. Warp {1}{W}.
        make_creature(
            "All-Fates Stalker", "{3}{W}", 2, 3,
            warp="{1}{W}",
            subtypes=("Drix", "Assassin"),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ExileTargetCreatureUntilSourceLeaves(
                        excluded_subtypes=frozenset({"Assassin"}),
                    ),
                ),
            ),
        ),
        # The Seriema: {1}{W}{W} 5/5 Legendary Spacecraft.
        # - ETB: search library for a legendary creature card → hand,
        #   shuffle.
        # - Station 7+ Flying.
        # - 7+ | Other tapped legendary creatures you control have
        #   indestructible.
        make_spacecraft(
            "The Seriema", "{1}{W}{W}", 5, 5,
            station_threshold=7,
            stationed_keywords={"flying"},
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=SearchLibraryForCard(
                        filter_name="legendary_creature",
                        may_fail=False,
                    ),
                ),
            ),
            static_abilities=(
                StaticAbility(
                    scope=(
                        StaticScope
                        .OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL
                    ),
                    granted_keywords=frozenset({"indestructible"}),
                    tier_threshold=7,
                ),
            ),
        ),
        # Starfield Shepherd: {3}{W}{W} 3/2 Flying. ETB tutor a basic
        # Plains OR a creature card with MV ≤ 1 to hand. Simplified:
        # only one mode — creature with MV ≤ 1. (Basic-Plains fetch is
        # less useful here since we already have the dedicated
        # SearchLibraryForBasicLandTapped for Landers.)
        make_creature(
            "Starfield Shepherd", "{3}{W}{W}", 3, 2,
            keywords={"flying"},
            warp="{1}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=SearchLibraryForCard(
                        filter_name="creature_small",
                        max_mv=1,
                        may_fail=False,
                    ),
                ),
            ),
        ),
        # Entropic Battlecruiser `{3}{B}` 3/10 Spacecraft.
        # - Station 8+ Flying + Deathtouch.
        # - 1+ | Whenever an opponent discards a card, they lose 3 life.
        # - Whenever this Spacecraft attacks, each opponent discards a
        #   card. Each opponent who can't loses 3 life.
        make_spacecraft(
            "Entropic Battlecruiser", "{3}{B}", 3, 10,
            station_threshold=8,
            stationed_keywords={"flying", "deathtouch"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="opponent_discards_a_card",
                    effect=TargetPlayerLosesLife(amount=3),
                    tier_threshold=1,
                ),
                TriggeredAbility(
                    trigger="attacks",
                    effect=EachOpponentDiscardsOrLosesLife(life_if_cant=3),
                ),
            ),
        ),
        # Synthesizer Labship: {U} 4/4 Spacecraft. Station 9+ flying.
        # 2+ | At the beginning of combat on your turn, up to one other
        # target artifact you control becomes an artifact creature with
        # base P/T 2/2 and gains flying until end of turn.
        # Simplification: we can't make a non-creature artifact "become"
        # a creature (needs layered continuous effects). We approximate
        # by restricting the target to artifacts that are already
        # creatures and pumping +2/+2 + flying UEOT on them.
        make_spacecraft(
            "Synthesizer Labship", "{U}", 4, 4,
            station_threshold=9,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_combat",
                    effect=PumpTargetOtherArtifactYouControlUEOT(
                        power_bonus=2, toughness_bonus=2,
                        granted_keywords=frozenset({"flying"}),
                    ),
                    tier_threshold=2,
                ),
            ),
        ),
        # Sledge-Class Seedship: {2}{G} 4/5 Spacecraft. Station 7+ flying.
        # "Whenever this Spacecraft attacks, you may put a creature card
        # from your hand onto the battlefield." (No explicit tier gate
        # — the Spacecraft can only attack once stationed at 7+, which
        # makes the attack the de-facto gate.)
        make_spacecraft(
            "Sledge-Class Seedship", "{2}{G}", 4, 5,
            station_threshold=7,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="attacks",
                    effect=OptionalPutCreatureFromHandOntoBattlefield(),
                ),
            ),
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
        # Kav Landseeker: {3}{R} 4/3 Menace. ETB create a Lander token
        # with a delayed-trigger sacrifice at the controller's next end
        # step.
        make_creature(
            "Kav Landseeker", "{3}{R}", 4, 3,
            keywords={"menace"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateLanderAndScheduleSacrifice(),
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
        # Mm'menon, Uthros Exile: {1}{U}{R} 1/3 Legendary Flying.
        # Whenever an artifact you control enters, put a +1/+1 counter
        # on target creature. Multicolor — in the pool but
        # build_mono_color_deck won't pull it; legit for mixed scenarios.
        make_creature(
            "Mm'menon, Uthros Exile", "{1}{U}{R}", 1, 3,
            keywords={"flying"},
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="artifact_enters_you_control",
                    effect=PutPlusOneCounterOnTargetCreature(amount=1),
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
        # -- Batch #3 of vanilla-simplified creatures. Each drops its
        # complex text to ship as keyword-only (or pure vanilla / vanilla
        # + Warp). Simplification noted per card.
        # Mm'menon, the Right Hand `{3}{U}{U}` 3/4 Legendary Creature.
        # Real oracle: "Flying. You may look at the top card of your
        # library any time. You may cast artifact spells from the top
        # of your library. Artifacts you control have '{T}: Add {U}.
        # Spend this mana only to cast a spell from anywhere other
        # than your hand.'"
        # Implemented: flying + cast-artifact-from-top-of-library.
        # Dropped: (1) the "look at top any time" info ability (our
        # engine doesn't gate information anyway), (2) the static
        # artifacts-have-mana-ability clause (engine has no
        # static-grants-activated-ability plumbing yet).
        make_creature(  # Mm'menon, the Right Hand
            "Mm'menon, the Right Hand", "{3}{U}{U}", 3, 4,
            keywords={"flying"},
            legendary=True,
            grants_cast_artifact_from_top_of_library=True,
        ),
        # Alpharael, Stonechosen `{3}{B}{B}` 3/3 Legendary Creature.
        # Warp `{2}{B}`. Real oracle: "Ward—Discard a card at random.
        # Void — Whenever Alpharael attacks, if a nonland permanent
        # left the battlefield this turn or a spell was warped this
        # turn, defending player loses half their life, rounded up."
        make_creature(
            "Alpharael, Stonechosen", "{3}{B}{B}", 3, 3,
            legendary=True,
            warp="{2}{B}",
            ward_discard_random=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="attacks",
                    effect=DefendingPlayerLosesHalfLifeRoundedUp(),
                    requires_void=True,
                ),
            ),
        ),
        # Blade of the Swarm `{3}{B}` 3/1 Creature. Warp `{1}{B}`.
        # Real oracle ETB: "Choose one —
        #   • Put two +1/+1 counters on this creature.
        #   • Put target exiled card with warp on the bottom of its
        #     owner's library."
        # Simplification: the second mode (bottom a warped exile card)
        # isn't implemented — we'd need a zone-aware target filter
        # for warped-exile cards. We expose only the first mode via
        # PutPlusOneCounterOnSelf; the modal machinery stays intact
        # for future extension.
        make_creature(
            "Blade of the Swarm", "{3}{B}", 3, 1,
            warp="{1}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnSelf(amount=2),
                ),
            ),
        ),
        # Monoist Circuit-Feeder `{4}{B}{B}` 4/4 Artifact Creature.
        # Real oracle: "Flying. When this creature enters, until end of
        # turn, target creature you control gets +X/+0 and target
        # creature an opponent controls gets -0/-X, where X is the
        # number of artifacts you control."
        make_creature(
            "Monoist Circuit-Feeder", "{4}{B}{B}", 4, 4,
            artifact=True,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=MonoistCircuitFeederETBEffect(),
                ),
            ),
        ),
        # Perigee Beckoner `{4}{B}` 4/5 Creature. Warp `{1}{B}` (real
        # warp cost per oracle — note previous build had `{2}{B}`).
        # "When this creature enters, until end of turn, another target
        # creature you control gets +2/+0 and gains 'When this creature
        # dies, return it to the battlefield tapped under its owner's
        # control.'"
        # Simplification: the granted "dies → return tapped" rider is
        # dropped (requires granted-triggered-ability infrastructure).
        # The +2/+0 UEOT pump is kept.
        make_creature(
            "Perigee Beckoner", "{4}{B}", 4, 5,
            warp="{1}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=2, toughness_bonus=0,
                        you_control_only=True,
                    ),
                ),
            ),
        ),
        # Susurian Voidborn `{2}{B}` 2/2 Creature. Warp `{B}`. Real
        # oracle: "Whenever this creature or another creature or
        # artifact you control dies, target opponent loses 1 life and
        # you gain 1 life."
        make_creature(
            "Susurian Voidborn", "{2}{B}", 2, 2,
            warp="{B}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="your_creature_or_artifact_dies",
                    effect=TargetOpponentLosesNYouGainN(amount=1),
                ),
            ),
        ),
        # Kavaron Harrier `{R}` 2/1 Artifact Creature. Real oracle:
        # "Whenever this creature attacks, you may pay {2}. If you do,
        # create a 2/2 colorless Robot artifact creature token that's
        # tapped and attacking. Sacrifice that token at end of combat."
        make_creature(
            "Kavaron Harrier", "{R}", 2, 1,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="attacks",
                    effect=KavaronHarrierAttackEffect(),
                ),
            ),
        ),
        # Possibility Technician `{2}{R}` 3/3 Creature. Warp `{R}`.
        # Real oracle: "Whenever this creature or another Kavu you
        # control enters, exile the top card of your library. For as
        # long as that card remains exiled, you may play it if you
        # control a Kavu." Stand-in comment was stale (non-oracle).
        # Simplifications: (a) Kavu-scoped observer trigger narrowed
        # to self-ETB only; (b) "for as long as" persistence narrowed
        # to this-turn-only via the impulse-cast flag.
        make_creature(
            "Possibility Technician", "{2}{R}", 3, 3,
            warp="{R}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PossibilityTechnicianETBEffect(),
                ),
            ),
        ),
        # Roving Actuator `{3}{R}` 3/4 Artifact Creature. Warp `{1}{R}`.
        # Real oracle: "Void — When this creature enters, if a nonland
        # permanent left the battlefield this turn or a spell was
        # warped this turn, exile up to one target instant or sorcery
        # card with mana value 2 or less from your graveyard. Copy it.
        # You may cast the copy without paying its mana cost."
        make_creature(  # Roving Actuator
            "Roving Actuator", "{3}{R}", 3, 4,
            artifact=True,
            warp="{1}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=RovingActuatorETBEffect(),
                    requires_void=True,
                ),
            ),
        ),
        # Terrapact Intimidator `{1}{R}` 2/1 Creature. Real oracle:
        # "When this creature enters, target opponent may have you
        # create two Lander tokens. If they don't, put two +1/+1
        # counters on this creature."
        make_creature(
            "Terrapact Intimidator", "{1}{R}", 2, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=TerrapactIntimidatorETBEffect(),
                ),
            ),
        ),
        # Territorial Bruntar `{4}{R}{R}` 6/6 Creature. Real oracle:
        # "Reach. Landfall — Whenever a land you control enters, exile
        # cards from the top of your library until you exile a nonland
        # card. You may cast that card this turn."
        make_creature(
            "Territorial Bruntar", "{4}{R}{R}", 6, 6,
            keywords={"reach"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=TerritorialBruntarLandfallEffect(),
                ),
            ),
        ),
        # Vaultguard Trooper `{4}{R}` 5/5 Creature. Real oracle:
        # "At the beginning of your end step, if you control two or
        # more tapped creatures, you may discard your hand. If you do,
        # draw two cards."
        # Simplification: the "may" is always yes (consistent with
        # other OptionalSac-style effects). The tapped-creatures
        # threshold is honored via ConditionalOnTappedCreatures.
        make_creature(
            "Vaultguard Trooper", "{4}{R}", 5, 5,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=ConditionalOnTappedCreatures(
                        effect=DiscardHandThenDrawN(amount=2),
                        min_count=2,
                    ),
                ),
            ),
        ),
        # Hemosymbic Mite `{G}` 1/1 Creature. Real oracle:
        # "Whenever this creature becomes tapped, another target
        # creature you control gets +X/+X until end of turn, where X
        # is this creature's power."
        # Note: previous comment mentioned deathtouch + dies/Lander,
        # neither of which is in the printed card.
        make_creature(
            "Hemosymbic Mite", "{G}", 1, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="becomes_tapped",
                    effect=(
                        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()
                    ),
                ),
            ),
        ),
        # Icetill Explorer `{2}{G}{G}` 2/4 Creature. Real oracle:
        # "You may play an additional land on each of your turns. You
        # may play lands from your graveyard. Landfall — Whenever a
        # land you control enters, mill a card."
        # Simplification: play-lands-from-graveyard is dropped (would
        # require extending legal.py's land-source scan to graveyards).
        make_creature(
            "Icetill Explorer", "{2}{G}{G}", 2, 4,
            grants_additional_land_per_turn=1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=SelfMill(amount=1),
                ),
            ),
        ),
        # Mightform Harmonizer `{2}{G}{G}` 4/4 Creature. Warp `{2}{G}`.
        # Real oracle: "Landfall — Whenever a land you control enters,
        # double the power of target creature you control until end
        # of turn."
        make_creature(
            "Mightform Harmonizer", "{2}{G}{G}", 4, 4,
            warp="{2}{G}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=DoubleTargetCreaturesPowerUEOT(),
                ),
            ),
        ),
        # Ouroboroid `{2}{G}{G}` 1/3 Creature.
        # "At the beginning of combat on your turn, put X +1/+1
        # counters on each creature you control, where X is this
        # creature's power." (Pump engine — counters on Ouroboroid
        # cascade across the whole team each turn.)
        make_creature(
            "Ouroboroid", "{2}{G}{G}", 1, 3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_combat",
                    effect=(
                        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()
                    ),
                ),
            ),
        ),
        # Alpharael, Dreaming Acolyte `{1}{U}{B}` 2/3 Legendary Creature.
        # Real oracle:
        # - "When Alpharael enters, draw two cards. Then discard two
        #   cards unless you discard an artifact card."
        # - "During your turn, Alpharael has deathtouch."
        # Simplifications retained: the "unless you discard an artifact"
        # dodge isn't modeled — the caster just discards two cards
        # unconditionally.
        make_creature(
            "Alpharael, Dreaming Acolyte", "{1}{U}{B}", 2, 3,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Sequence(effects=(
                        DrawCards(amount=2),
                        DiscardSelf(amount=2),
                    )),
                ),
            ),
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.SELF,
                    granted_keywords=frozenset({"deathtouch"}),
                    active_turn_only=True,
                ),
            ),
        ),
        # Haliya, Ascendant Cadet `{2}{G}{W}{W}` 3/3 Legendary Creature.
        # Real oracle:
        # - "Whenever Haliya enters or attacks, put a +1/+1 counter on
        #   target creature you control."
        # - "Whenever one or more creatures you control with +1/+1
        #   counters on them deal combat damage to a player, draw a
        #   card."
        # Simplification: the second, combat-damage-observer trigger
        # needs a "your creature with counter dealt damage to player"
        # observer — not modeled yet, so dropped. The first (etb +
        # attacks) is fully restored.
        make_creature(
            "Haliya, Ascendant Cadet", "{2}{G}{W}{W}", 3, 3,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
                ),
                TriggeredAbility(
                    trigger="attacks",
                    effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
                ),
            ),
        ),
        # Pinnacle Emissary `{1}{U}{R}` 3/3 Artifact Creature.
        # Real oracle: "Whenever you cast an artifact spell, create a
        # 1/1 colorless Drone artifact creature token with flying and
        # 'This token can block only creatures with flying.'"
        # Warp `{U/R}` — modeled as `{U}{R}` since hybrid mana isn't
        # a separate cost structure in our engine.
        # Simplification: the Drone's block-restriction is dropped.
        make_creature(
            "Pinnacle Emissary", "{1}{U}{R}", 3, 3,
            artifact=True,
            warp="{U}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="cast_artifact_spell",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Drone"], count=1,
                    ),
                ),
            ),
        ),
        # Ragost, Deft Gastronaut `{R}{W}` 2/2 Legendary Creature.
        # Real oracle: "Artifacts you control are Foods in addition to
        # their other types and have '{2}, {T}, Sacrifice this
        # artifact: You gain 3 life.' {1}, {T}, Sacrifice a Food:
        # Ragost deals 3 damage to each opponent. At the beginning of
        # each end step, if you gained life this turn, untap Ragost."
        # Statics are consumed by game.effective_subtypes +
        # effective_activated_abilities; the activated Food-sac deal-3
        # ability is wired directly; the untap trigger uses the new
        # beginning_of_each_end_step firing path.
        make_creature(
            "Ragost, Deft Gastronaut", "{R}{W}", 2, 2,
            legendary=True,
            grants_food_to_your_artifacts=True,
            grants_food_ability_to_your_artifacts=True,
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{1}"),
                        mana_str="{1}",
                        tap_self=True,
                        sacrifice_food=True,
                    ),
                    effect=DealDamageEachOpponent(amount=3),
                ),
            ),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_each_end_step",
                    effect=IfGainedLifeThisTurnUntapSelf(),
                ),
            ),
        ),
        # Sami, Ship's Engineer `{2}{R}{W}` 2/4 Legendary Creature.
        # Real oracle: "At the beginning of your end step, if you
        # control two or more tapped creatures, create a tapped 2/2
        # colorless Robot artifact creature token."
        make_creature(
            "Sami, Ship's Engineer", "{2}{R}{W}", 2, 4,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=ConditionalOnTappedCreatures(
                        effect=CreateToken(
                            token_printing=TOKEN_PRINTINGS["Robot"],
                            count=1, tapped=True,
                        ),
                        min_count=2,
                    ),
                ),
            ),
        ),
        # Station Monitor `{W}{U}` 2/2 Creature. Real oracle:
        # "Whenever you cast your second spell each turn, create a
        # 1/1 colorless Drone artifact creature token with flying
        # and 'This token can block only creatures with flying.'"
        # Simplification: block-restriction on the Drone is dropped.
        make_creature(
            "Station Monitor", "{W}{U}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="second_spell_each_turn",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Drone"], count=1,
                    ),
                ),
            ),
        ),
        # Syr Vondam, Sunstar Exemplar `{W}{B}` 2/2 Legendary Creature.
        # Real oracle: "Vigilance, menace. Whenever another creature you
        # control dies or is put into exile, put a +1/+1 counter on Syr
        # Vondam and you gain 1 life. When Syr Vondam dies or is put
        # into exile while its power is 4 or greater, destroy up to
        # one target nonland permanent."
        # The self death-rider uses leaves_battlefield — it already
        # fires on graveyard and exile paths and skips bounce-to-hand.
        make_creature(
            "Syr Vondam, Sunstar Exemplar", "{W}{B}", 2, 2,
            legendary=True,
            keywords={"vigilance", "menace"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="another_creature_you_control_dies_or_exiled",
                    effect=Sequence(effects=(
                        PutPlusOneCounterOnSelf(amount=1),
                        GainLife(amount=1),
                    )),
                ),
                TriggeredAbility(
                    trigger="leaves_battlefield",
                    effect=ConditionalIfSourcePowerAtLeast(
                        effect=DestroyTargetNonlandPermanent(),
                        threshold=4,
                    ),
                ),
            ),
        ),
        # Syr Vondam, the Lucent `{2}{W}{B}{B}` 4/4 Legendary Creature.
        # Real oracle: "Deathtouch, lifelink. Whenever Syr Vondam enters
        # or attacks, other creatures you control get +1/+0 and gain
        # deathtouch until end of turn."
        make_creature(
            "Syr Vondam, the Lucent", "{2}{W}{B}{B}", 4, 4,
            legendary=True,
            keywords={"deathtouch", "lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PumpCreaturesYouControlUntilEOT(
                        power_bonus=1, toughness_bonus=0,
                        granted_keywords=frozenset({"deathtouch"}),
                        exclude_source=True,
                    ),
                ),
                TriggeredAbility(
                    trigger="attacks",
                    effect=PumpCreaturesYouControlUntilEOT(
                        power_bonus=1, toughness_bonus=0,
                        granted_keywords=frozenset({"deathtouch"}),
                        exclude_source=True,
                    ),
                ),
            ),
        ),
        # Tannuk, Memorial Ensign `{1}{R}{G}` 2/4 Legendary Creature.
        # Real oracle: "Landfall — Whenever a land you control enters,
        # Tannuk deals 1 damage to each opponent. If this is the second
        # time this ability has resolved this turn, draw a card."
        # (Earlier preview text showed a different ability — ignore.)
        make_creature(
            "Tannuk, Memorial Ensign", "{1}{R}{G}", 2, 4,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="landfall",
                    effect=TannukEnsignLandfallEffect(),
                ),
            ),
        ),
        # Chrome Companion `{2}` 2/1 Artifact Creature. Real oracle:
        # "Whenever this creature becomes tapped, you gain 1 life.
        # {2}, {T}: Put target card from a graveyard on the bottom of
        # its owner's library."
        make_creature(
            "Chrome Companion", "{2}", 2, 1,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="becomes_tapped",
                    effect=GainLife(amount=1),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{2}"),
                        mana_str="{2}",
                        tap_self=True,
                    ),
                    effect=PutCardFromGraveyardOnBottomOfLibrary(),
                ),
            ),
        ),
        # -- Batch #2 of vanilla-simplified creatures. Dropped complex
        # text for each; shipped as keyword-only (or literal vanilla)
        # bodies.
        # Anticausal Vestige `{6}` 7/5 Creature. Warp `{4}`.
        # Real oracle: "When this creature leaves the battlefield, draw
        # a card, then you may put a permanent card with mana value
        # less than or equal to the number of lands you control from
        # your hand onto the battlefield tapped."
        make_creature(
            "Anticausal Vestige", "{6}", 7, 5,
            warp="{4}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="leaves_battlefield",
                    effect=AnticausalVestigeLeavesEffect(),
                ),
            ),
        ),
        # Astelli Reclaimer `{3}{W}{W}` 5/4 Creature. Warp `{2}{W}`.
        # Real oracle: "Flying. When this creature enters, return
        # target noncreature, nonland permanent card with mana value X
        # or less from your graveyard to the battlefield, where X is
        # the mana spent to cast this creature."
        make_creature(
            "Astelli Reclaimer", "{3}{W}{W}", 5, 4,
            keywords={"flying"},
            warp="{2}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=AstelliReclaimerETBEffect(),
                ),
            ),
        ),
        # Exalted Sunborn `{3}{W}{W}` 4/5 Angel Wizard — Flying, lifelink.
        # "If one or more tokens would be created under your control,
        # twice that many of those tokens are created instead."
        make_creature(
            "Exalted Sunborn", "{3}{W}{W}", 4, 5,
            subtypes=("Angel", "Wizard"),
            keywords={"flying", "lifelink"},
            warp="{1}{W}",
            is_token_doubler=True,
        ),
        # Pulsar Squadron Ace: {1}{W} 1/2 Human Pilot. ETB — look at the
        # top five cards of your library, may reveal a Spacecraft card
        # and put it into your hand, rest to the bottom in a random
        # order. If no card was put into your hand this way, put a
        # +1/+1 counter on this creature.
        make_creature(
            "Pulsar Squadron Ace", "{1}{W}", 1, 2,
            subtypes=("Human", "Pilot"),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=LookAtTopNRevealOrCounter(
                        n=5, filter_name="spacecraft",
                    ),
                ),
            ),
        ),
        # Starport Security `{W}` 1/1 Artifact Creature. Activated
        # ability `{3}{W}, {T}: Tap another target creature.`
        # Simplification: drops the conditional "-{2} if you control a
        # creature with a +1/+1 counter" reduction (activated-ability
        # cost reductions aren't modeled yet).
        make_creature(
            "Starport Security", "{W}", 1, 1,
            artifact=True,
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(mana="{3}{W}", tap_self=True),
                    effect=TapAnotherTargetCreature(),
                ),
            ),
        ),
        # Weftblade Enhancer `{5}{W}` 3/4 Creature. Warp `{2}{W}`.
        # Real oracle: "When this creature enters, put a +1/+1 counter
        # on each of up to two target creatures."
        make_creature(
            "Weftblade Enhancer", "{5}{W}", 3, 4,
            warp="{2}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnEachOfUpToNTargetCreatures(
                        max_n=2,
                    ),
                ),
            ),
        ),
        # Emissary Escort `{1}{U}` 0/4 Artifact Creature — Robot Soldier.
        # "This creature gets +X/+0, where X is the greatest mana value
        # among other artifacts you control."
        make_creature(
            "Emissary Escort", "{1}{U}", 0, 4,
            artifact=True,
            subtypes=("Robot", "Soldier"),
            dynamic_pt_formula="emissary_escort",
        ),
        # Mechanozoa `{4}{U}{U}` 5/5 Artifact Creature. Warp `{2}{U}`.
        # Real oracle ETB: "When this creature enters, tap target
        # artifact or creature an opponent controls and put a stun
        # counter on it."
        make_creature(
            "Mechanozoa", "{4}{U}{U}", 5, 5,
            artifact=True,
            warp="{2}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=TapTargetOpponentPermanentAndStunIt(),
                ),
            ),
        ),
        # Selfcraft Mechan `{3}{U}` 3/4 Artifact Creature. Real oracle:
        # "When this creature enters, you may sacrifice an artifact.
        # When you do, put a +1/+1 counter on target creature and draw
        # a card." Simplification: "may" is always yes when an artifact
        # exists; otherwise the rider fizzles.
        make_creature(
            "Selfcraft Mechan", "{3}{U}", 3, 4,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=SelfcraftMechanETBEffect(),
                ),
            ),
        ),
        # Sinister Cryologist `{2}{U}` 2/3 Creature. Warp `{U}`.
        # Real oracle ETB: "When this creature enters, target creature
        # an opponent controls gets -3/-0 until end of turn."
        make_creature(
            "Sinister Cryologist", "{2}{U}", 2, 3,
            warp="{U}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=-3, toughness_bonus=0,
                        opponents_only=True,
                    ),
                ),
            ),
        ),
        # Starfield Vocalist `{3}{U}` 3/4 Creature. Warp `{1}{U}`.
        # Real oracle: "If a permanent entering the battlefield causes
        # a triggered ability of a permanent you control to trigger,
        # that ability triggers an additional time." Implemented via
        # CardPrinting.extra_etb_trigger, summed by
        # game.etb_trigger_multiplier at every ETB-caused firing site.
        make_creature(
            "Starfield Vocalist", "{3}{U}", 3, 4,
            warp="{1}{U}",
            extra_etb_trigger=1,
        ),
        # Starwinder `{5}{U}{U}` 7/7 Creature. Warp `{2}{U}{U}`.
        # Real oracle: "Whenever a creature you control deals combat
        # damage to a player, you may draw that many cards."
        make_creature(
            "Starwinder", "{5}{U}{U}", 7, 7,
            warp="{2}{U}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="your_creature_combat_damage_to_player",
                    effect=DrawCardsEqualToResolvingCombatDamage(),
                ),
            ),
        ),
        # Steelswarm Operator `{1}{U}` 1/1 Artifact Creature. Real
        # oracle: "Flying. {T}: Add {U}. Spend this mana only to cast
        # an artifact spell. {T}: Add {U}{U}. Spend this mana only to
        # activate abilities of artifact sources."
        # Simplification: both mana abilities use the same cost ({T}),
        # so a turn only activates one. The second (Add {U}{U}, spend
        # on artifact-activation-abilities) is dropped — the engine
        # doesn't model "artifact_activation" spend restrictions.
        make_creature(
            "Steelswarm Operator", "{1}{U}", 1, 1,
            artifact=True,
            keywords={"flying"},
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(
                        produces=(("U", 1),),
                        spend_restriction="artifact_spell",
                    ),
                    is_mana_ability=True,
                ),
            ),
        ),
        # -- Batch #1 of vanilla-simplified creatures. Each drops its
        # non-keyword text to ship a keyword-only version. Simplification
        # status is noted in-line; functional Magic is preserved, the
        # cards are just weaker than printed.
        make_creature(  # Lightstall Inquisitor — drops the ETB "each opponent exiles a card..." clause.
            "Lightstall Inquisitor", "{W}", 2, 1,
            keywords={"vigilance"},
        ),
        make_creature(  # Timeline Culler — drops "when this attacks, mill 3 / return creature" rider.
            "Timeline Culler", "{B}{B}", 2, 2,
            keywords={"haste"},
        ),
        make_creature(  # Rust Harvester — drops its "discard a card, sacrifice an artifact" trigger.
            "Rust Harvester", "{R}", 1, 1,
            keywords={"menace"},
        ),
        make_creature(  # Frenzied Baloth — drops "{R}: this creature gets +1/+0" activated.
            "Frenzied Baloth", "{G}{G}", 3, 2,
            keywords={"trample", "haste"},
        ),
        make_creature(  # Tapestry Warden — drops conditional counter pump on dying friends.
            "Tapestry Warden", "{3}{G}", 3, 4,
            keywords={"vigilance"},
        ),
        make_creature(  # Genemorph Imago — drops Landfall "base P/T 3/3 or 6/6" rider.
            "Genemorph Imago", "{G}{U}", 1, 3,
            keywords={"flying"},
        ),
        make_creature(  # Survey Mechan — drops search-library ETB rider.
            "Survey Mechan", "{4}", 1, 3,
            artifact=True,
            keywords={"flying"},
        ),
        # Uthros Psionicist: {2}{U} 2/4. "The second spell you cast each
        # turn costs {2} less to cast." This is a STATIC ability (it's
        # not a cost reduction on the Psionicist itself) but our cost-
        # reduction framework is card-local. Simplification retained:
        # the static buff to other spells isn't modeled; Psionicist
        # ships as a plain 2/4.
        make_creature(
            "Uthros Psionicist", "{2}{U}", 2, 4,
        ),
        # Gigastorm Titan: {4}{U} 4/4. Costs {3} less to cast if you've
        # already cast another spell this turn.
        make_creature(
            "Gigastorm Titan", "{4}{U}", 4, 4,
            cost_reductions=(
                CostReduction(
                    amount=3,
                    condition="another_spell_cast_this_turn",
                ),
            ),
        ),
        # Mechan Shieldmate: {1}{U} 3/2 Artifact Creature — Robot Soldier
        # with Defender. Simplified: drops the conditional "can attack
        # as though it didn't have defender if an artifact entered this
        # turn" clause (conditional defender-override not modeled).
        make_creature(
            "Mechan Shieldmate", "{1}{U}", 3, 2,
            artifact=True,
            keywords={"defender"},
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
        # Codecracker Hound: {2}{U} 2/1. ETB look at top 2; one to
        # hand, one to graveyard. Ships with Warp {2}{U}.
        make_creature(
            "Codecracker Hound", "{2}{U}", 2, 1,
            warp="{2}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=LookAtTopTwoSplitHandGraveyard(),
                ),
            ),
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
        # you control + activated `{2}, Remove a +1/+1 counter from a
        # creature you control: Tap target artifact or creature.`
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
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(
                        mana="{2}",
                        remove_plus_one_counter_from_your_creature=True,
                    ),
                    effect=TapTargetArtifactOrCreature(),
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
        # Swarm Culler: {3}{B} 2/4 Flying. Becomes-tapped → may
        # sacrifice another creature or artifact for a draw.
        make_creature(
            "Swarm Culler", "{3}{B}", 2, 4,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="becomes_tapped",
                    effect=OptionalSacAnotherForEffect(
                        inner_effect=DrawCards(amount=1),
                    ),
                ),
            ),
        ),
        # Comet Crawler: {2}{B} 2/3 Lifelink. Attacks → may sacrifice
        # another creature or artifact for +2/+0 UEOT.
        make_creature(
            "Comet Crawler", "{2}{B}", 2, 3,
            keywords={"lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="attacks",
                    effect=OptionalSacAnotherForPumpSelfUEOT(
                        power_bonus=2, toughness_bonus=0,
                    ),
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
        # Sunset Saboteur: {1}{B} 4/1 Menace. Attacks-trigger puts a
        # +1/+1 counter on a creature an opponent controls (unusual
        # flavor — buffing their threat). Dropped: Ward—Discard a card
        # (non-mana ward costs not modeled).
        make_creature(
            "Sunset Saboteur", "{1}{B}", 4, 1,
            keywords={"menace"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="attacks",
                    effect=PutPlusOneCounterOnOpponentsCreature(amount=1),
                ),
            ),
        ),
        # Umbral Collar Zealot: {1}{B} 3/2. Activated ability:
        # "Sacrifice another creature or artifact: Surveil 1."
        make_creature(
            "Umbral Collar Zealot", "{1}{B}", 3, 2,
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        sacrifice_another_creature_or_artifact=True,
                    ),
                    effect=Surveil(amount=1),
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
        # Auxiliary Boosters: {4}{W} Equipment. ETB create a 2/2 Robot
        # token and auto-attach to it. Equipped creature gets +1/+2 and
        # flying. Dropped: Equip {3} activated ability.
        make_equipment(
            "Auxiliary Boosters", "{4}{W}",
            power_bonus=1, toughness_bonus=2,
            granted_keywords=frozenset({"flying"}),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateTokenAndAttachSelf(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                    ),
                ),
            ),
        ),
        # Hylderblade: {B} Equipment. Equipped creature gets +3/+1.
        # Void — end step: attach this to target creature you control.
        # Dropped: Equip {4} activated ability.
        make_equipment(
            "Hylderblade", "{B}",
            power_bonus=3, toughness_bonus=1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    requires_void=True,
                    effect=AttachToTargetCreatureYouControl(),
                ),
            ),
        ),
        # Meltstrider's Gear: {G} Equipment. ETB auto-attach; equipped
        # creature gets +2/+1 and reach. Dropped: the Equip {5} activated
        # ability (Equip costs aren't modeled — the ETB attachment is
        # permanent in this simplified model).
        make_equipment(
            "Meltstrider's Gear", "{G}",
            power_bonus=2, toughness_bonus=1,
            granted_keywords=frozenset({"reach"}),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=AttachToTargetCreatureYouControl(),
                ),
            ),
        ),
        # Squire's Lightblade: {W} Equipment with Flash. ETB auto-attach;
        # equipped creature gets +1/+0. Dropped: the one-shot "gains
        # first strike UEOT" on ETB (would be a separate Sequence effect,
        # skipped for clarity), and the Equip {3} activated ability.
        make_equipment(
            "Squire's Lightblade", "{W}",
            power_bonus=1, toughness_bonus=0,
            keywords={"flash"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=AttachToTargetCreatureYouControl(),
                ),
            ),
        ),
        # Illvoi Light Jammer: {1}{U} Equipment with Flash. ETB
        # auto-attach; equipped creature gets +1/+2. Dropped: "that
        # creature gains hexproof UEOT" rider (hexproof not yet modeled)
        # and the Equip {3} activated ability.
        make_equipment(
            "Illvoi Light Jammer", "{1}{U}",
            power_bonus=1, toughness_bonus=2,
            keywords={"flash"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=AttachToTargetCreatureYouControl(),
                ),
            ),
        ),
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
        # Cryogen Relic: {1}{U} Artifact. Enters-OR-leaves draw 1.
        # {1}{U}, Sacrifice: put a stun counter on up to one target
        # tapped creature.
        make_artifact(
            "Cryogen Relic", "{1}{U}",
            triggered_abilities=(
                TriggeredAbility(trigger="etb", effect=DrawCards(amount=1)),
                TriggeredAbility(
                    trigger="leaves_battlefield",
                    effect=DrawCards(amount=1),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{1}{U}"),
                        mana_str="{1}{U}",
                        sacrifice_self=True,
                    ),
                    effect=PutStunCounterOnTappedCreature(),
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
        # Slagdrill Scrapper: {R} 1/2 Artifact Creature — Robot Scout.
        # Activated: {2}, {T}, Sacrifice another artifact or land: Draw a card.
        make_creature(
            "Slagdrill Scrapper", "{R}", 1, 2,
            artifact=True,
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{2}"), mana_str="{2}",
                        tap_self=True,
                        sacrifice_another_artifact_or_land=True,
                    ),
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        # Zookeeper Mechan: {1}{R} 1/3 Artifact Creature — Robot.
        # Activated {6}{R}, sorcery-speed pump +4/+0 UEOT on target
        # creature you control. Dropped: the {T}: Add {R} mana ability
        # (creature mana abilities aren't modeled).
        make_creature(
            "Zookeeper Mechan", "{1}{R}", 1, 3,
            artifact=True,
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{6}{R}"), mana_str="{6}{R}",
                    ),
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=4, toughness_bonus=0,
                        you_control_only=True,
                    ),
                    sorcery_speed=True,
                ),
            ),
        ),
        # Skystinger: {2}{G} 3/3 Reach. Whenever this creature blocks a
        # creature with flying, it gets +5/+0 until end of turn.
        make_creature(
            "Skystinger", "{2}{G}", 3, 3,
            subtypes=("Insect", "Warrior"),
            keywords={"reach"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="blocks_creature_with_flying",
                    effect=PumpSelfUntilEOT(
                        power_bonus=5, toughness_bonus=0,
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
        # Weftstalker Ardent: {2}{R} 3/2. Whenever another creature or
        # artifact you control enters, this creature deals 1 damage to
        # each opponent. Dropped: Warp {R} (would work but printed text
        # is the main card; skipping to keep the change tight).
        make_creature(
            "Weftstalker Ardent", "{2}{R}", 3, 2,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="creature_or_artifact_enters_you_control",
                    effect=DealDamageEachOpponent(amount=1),
                ),
            ),
            warp="{R}",
        ),
        # Haliya, Guided by Light: {2}{W} 2/3 Legendary. Whenever Haliya
        # or another creature or artifact you control enters, you gain
        # 1 life. Dropped the "draw if you've gained 3 life this turn"
        # EoT rider + Warp {W} (life-gained-this-turn tracking not yet
        # modeled).
        make_creature(
            "Haliya, Guided by Light", "{2}{W}", 2, 3,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="creature_or_artifact_enters_you_control",
                    effect=GainLife(amount=1),
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
        # Cryoshatter: {U} Aura. Enchanted creature gets -5/-0.
        # Simplified: drops the "when enchanted creature becomes tapped
        # or is dealt damage, destroy it" compound trigger.
        make_aura(
            "Cryoshatter", "{U}",
            power_bonus=-5, toughness_bonus=0,
        ),
        # Meltstrider's Resolve: {G} Aura. Enchanted creature gets +0/+2
        # and has menace (modeling "can't be blocked by more than one
        # creature"). Dropped: "when this Aura enters, enchanted creature
        # fights up to one target creature an opponent controls" ETB.
        make_aura(
            "Meltstrider's Resolve", "{G}",
            power_bonus=0, toughness_bonus=2,
            granted_keywords=frozenset({"menace"}),
        ),
        # Banishing Light: {2}{W} Enchantment. Oblivion-Ring-style ETB
        # exile target nonland permanent an opponent controls; returns
        # when this enchantment leaves the battlefield.
        make_enchantment(
            "Banishing Light", "{2}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ExileOpponentsNonlandPermanentUntilLeaves(),
                ),
            ),
        ),
        # Seam Rip: {W} Enchantment. Same shape as Banishing Light but
        # only targets MV 2 or less.
        make_enchantment(
            "Seam Rip", "{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ExileOpponentsNonlandPermanentUntilLeaves(
                        max_mv=2,
                    ),
                ),
            ),
        ),
        # Weapons Manufacturing: {1}{R} Enchantment. Whenever a nontoken
        # artifact you control enters, create a Munitions token; that
        # token's leaves-battlefield trigger deals 2 damage to any
        # target when the token leaves play.
        make_enchantment(
            "Weapons Manufacturing", "{1}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="nontoken_artifact_enters_you_control",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Munitions"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Bioengineered Future: {1}{G}{G} Enchantment. ETB create a
        # Lander token. Simplified: drops the "each creature you control
        # enters with an additional +1/+1 counter" replacement effect
        # (replacement effects aren't modeled).
        make_enchantment(
            "Bioengineered Future", "{1}{G}{G}",
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
        # Drix Fatemaker: {3}{G} 3/2. ETB +1/+1 counter on target
        # creature; creatures you control with a +1/+1 counter have
        # trample. Ships with Warp {1}{G} to match the printed card.
        make_creature(
            "Drix Fatemaker", "{3}{G}", 3, 2,
            warp="{1}{G}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnTargetCreature(amount=1),
                ),
            ),
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.CREATURES_YOU_CONTROL_WITH_COUNTER,
                    granted_keywords=frozenset({"trample"}),
                ),
            ),
        ),
        # Lashwhip Predator: {4}{G}{G} 5/7 Reach. Costs {2} less if
        # your opponents control three or more creatures.
        make_creature(
            "Lashwhip Predator", "{4}{G}{G}", 5, 7,
            keywords={"reach"},
            cost_reductions=(
                CostReduction(
                    amount=2,
                    condition="opponents_control_three_or_more_creatures",
                ),
            ),
        ),
        # Fungal Colossus: {6}{G} 5/5. Costs {X} less where X = number
        # of differently-named lands you control.
        make_creature(
            "Fungal Colossus", "{6}{G}", 5, 5,
            cost_reductions=(
                CostReduction(
                    amount=1,
                    condition="per_differently_named_land",
                    per_land_group=True,
                ),
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
        # Tezzeret, Cruel Captain `{3}` Legendary Planeswalker — Tezzeret.
        # Loyalty 4. Restored abilities:
        #   - Whenever an artifact you control enters, put a loyalty
        #     counter on Tezzeret.
        # Remaining simplifications:
        #   - The three loyalty abilities (0/−3/−7) aren't modeled
        #     (loyalty-activated abilities need their own cost type).
        #   - Planeswalkers can't be attacked or targeted; damage to
        #     the controller isn't redirected.
        #   - The emblem from the −7 ability is dropped.
        make_planeswalker(
            "Tezzeret, Cruel Captain", "{3}",
            loyalty=4,
            subtype="Tezzeret",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="artifact_enters_you_control",
                    effect=PutLoyaltyCounterOnSelf(amount=1),
                ),
            ),
        ),
        # -- Final batch: remaining cards shipped as heavy simplifications
        # (empty bodies, vanilla bodies, or small placeholder effects).
        # Each card is noted per-item. These are pool-completeness ships;
        # they're playable but functionally much weaker than printed.
        # Broodguard Elite `{X}{G}{G}`:
        # - Enters with X +1/+1 counters on it.
        # - When this creature leaves the battlefield, put its counters
        #   on target creature you control.
        # - Warp `{X}{G}`.
        make_creature(
            "Broodguard Elite", "{X}{G}{G}", 0, 0,
            subtypes=("Insect", "Knight"),
            warp="{X}{G}",
            enters_with_counters_from_x="x",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="leaves_battlefield",
                    effect=MoveSelfCountersToTargetCreatureYouControl(),
                ),
            ),
        ),
        # Famished Worldsire `{5}{G}{G}{G}` Creature — Leviathan.
        # - Ward {3}.
        # - Devour land 3: "As this creature enters, you may sacrifice
        #   any number of lands. It enters with three times that many
        #   +1/+1 counters on it."
        # - ETB: "Look at the top X cards of your library, where X is
        #   this creature's power. Put any number of land cards from
        #   among them onto the battlefield tapped, then shuffle."
        make_creature(
            "Famished Worldsire", "{5}{G}{G}{G}", 6, 6,
            subtypes=("Leviathan",),
            ward="{3}",
            devour_land_multiplier=3,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=FamishedWorldsireETBEffect(),
                ),
            ),
        ),
        make_creature(  # Gene Pollinator — mana ability. Ship as vanilla Artifact Creature 1/2.
            "Gene Pollinator", "{G}", 1, 2,
            artifact=True,
        ),
        # Harmonious Grovestrider `{3}{G}{G}` Creature — Beast. Ward {2}.
        # "Power and toughness are each equal to the number of lands
        # you control." Printed `*/*`; we override via dynamic P/T.
        # Simplification retained: the printed card has no Reach — we
        # previously shipped it with Reach as a placeholder, now
        # removed to match the real card.
        make_creature(
            "Harmonious Grovestrider", "{3}{G}{G}", 0, 0,
            subtypes=("Beast",),
            ward="{2}",
            dynamic_pt_formula="harmonious_grovestrider",
        ),
        # Cosmogoyf `{B}{G}` Creature — Elemental Lhurgoyf.
        # Power = cards you own in exile. Toughness = that + 1. Printed
        # P/T is `*/1+*`; we ignore the printed power/toughness fields
        # at effective-P/T time when dynamic_pt_formula is set.
        make_creature(
            "Cosmogoyf", "{B}{G}", 0, 1,
            subtypes=("Elemental", "Lhurgoyf"),
            dynamic_pt_formula="cosmogoyf",
        ),
        # Dyadrine, Synthesis Amalgam `{X}{G}{W}`:
        # - Trample.
        # - Enters with +1/+1 counters equal to the amount of mana
        #   spent to cast it (X + base generic + colored pips).
        # - Whenever you attack, you may remove a +1/+1 counter from
        #   each of two creatures you control. If you do, draw a card
        #   and create a 2/2 colorless Robot artifact creature token.
        make_creature(
            "Dyadrine, Synthesis Amalgam", "{X}{G}{W}", 0, 1,
            artifact=True,
            legendary=True,
            subtypes=("Construct",),
            keywords={"trample"},
            enters_with_counters_from_x="mana_spent",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="attacks",
                    effect=DyadrineAttackEffect(),
                ),
            ),
        ),
        # Virulent Silencer `{3}` 2/3 Artifact Creature — Robot Assassin.
        # "Whenever a nontoken artifact creature you control deals combat
        # damage to a player, that player gets two poison counters."
        # (Players with 10+ poison counters lose the game.)
        make_creature(
            "Virulent Silencer", "{3}", 2, 3,
            artifact=True,
            subtypes=("Robot", "Assassin"),
            triggered_abilities=(
                TriggeredAbility(
                    trigger=(
                        "your_nontoken_artifact_creature_"
                        "combat_damage_to_player"
                    ),
                    effect=PutPoisonCountersOnTargetPlayer(amount=2),
                ),
            ),
        ),
        # Larval Scoutlander `{2}{G}` 3/3 Spacecraft. Real card:
        # - ETB: "When this Spacecraft enters, you may sacrifice a
        #   land or Lander. If you do, search your library for up to
        #   two basic land cards, put them onto the battlefield
        #   tapped, then shuffle."
        # - Station 7+ Flying.
        make_spacecraft(
            "Larval Scoutlander", "{2}{G}", 3, 3,
            station_threshold=7,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=OptionalSacLandOrLanderForBasicLandRamp(
                        land_count=2,
                    ),
                ),
            ),
        ),
        # Infinite Guideline Station `{W}{U}{B}{R}{G}` 7/15 Legendary
        # Spacecraft. Real card:
        # - ETB: create a tapped 2/2 colorless Robot token for each
        #   multicolored permanent you control.
        # - Station 12+ Flying.
        # - Whenever it attacks, draw a card for each multicolored
        #   permanent you control.
        # Note: previously shipped station_threshold=10 — corrected to 12.
        make_spacecraft(
            "Infinite Guideline Station", "{W}{U}{B}{R}{G}", 7, 15,
            station_threshold=12,
            stationed_keywords={"flying"},
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=CreateTokenPerMulticoloredPermanent(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        tapped=True,
                    ),
                ),
                TriggeredAbility(
                    trigger="attacks",
                    effect=DrawCardPerMulticoloredPermanent(),
                ),
            ),
        ),
        # Dawnsire, Sunstar Dreadnought: {5} 20/20 Legendary Spacecraft.
        # Station 20+ flying. 10+ | Whenever you attack, Dawnsire deals
        # 100 damage to up to one target creature or planeswalker.
        # Simplifications: "whenever you attack" is modeled as "whenever
        # this attacks" (close enough — Dawnsire is usually part of the
        # attack). "Up to one target creature or planeswalker" narrows
        # to "target creature" since we don't have planeswalkers yet;
        # the "up to" aspect is approximated — if there's no legal
        # target the trigger fizzles (functionally the same: no damage).
        make_spacecraft(
            "Dawnsire, Sunstar Dreadnought", "{5}", 20, 20,
            station_threshold=20,
            stationed_keywords={"flying"},
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="attacks",
                    effect=DealDamageToTargetCreature(amount=100),
                    tier_threshold=10,
                ),
            ),
        ),
        # Extinguisher Battleship `{8}` Spacecraft. Real card:
        # "When this Spacecraft enters, destroy target noncreature
        # permanent. Then this Spacecraft deals 4 damage to each
        # creature."
        # Station 5+ Flying + Trample. Note: our previous ship had
        # station_threshold=7; the real card is 5+.
        make_spacecraft(
            "Extinguisher Battleship", "{8}", 10, 10,
            station_threshold=5,
            stationed_keywords={"flying", "trample"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=Sequence(effects=(
                        DestroyTargetNoncreaturePermanent(),
                        DealNDamageToEachCreature(amount=4),
                    )),
                ),
            ),
        ),
        # The Eternity Elevator is a Spacecraft with no base P/T
        # (special card) — ship as no-frills colorless land-like artifact.
        make_artifact(
            "The Eternity Elevator", "{5}",
            legendary=True,
        ),
        # Auras — ship as simplified "enchant creature, small bonus" placeholders.
        # Hardlight Containment `{W}` Aura — Enchant artifact you
        # control. ETB exile target creature an opponent controls until
        # this Aura leaves the battlefield.
        # Simplification: the printed "Enchanted permanent has ward {1}"
        # static is dropped (equipment-granted wards aren't modeled);
        # granted_keywords=() to avoid unintended side bonuses.
        make_aura(
            "Hardlight Containment", "{W}",
            aura_enchant_type="artifact",
            power_bonus=0, toughness_bonus=0,
            granted_keywords=frozenset(),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ExileTargetCreatureUntilSourceLeaves(
                        opponents_only=True,
                    ),
                ),
            ),
        ),
        # Moonlit Meditation `{2}{U}` Enchantment — Aura. Real oracle:
        # "Enchant artifact or creature you control. The first time
        # you would create one or more tokens each turn, you may
        # instead create that many tokens that are copies of enchanted
        # permanent." Replacement effect wired via
        # replaces_first_tokens_with_copies + state.players_who_
        # created_tokens_this_turn (cleared at cleanup). Stand-in's
        # placeholder +1/+1 P/T bonus dropped — real card has none.
        make_aura(
            "Moonlit Meditation", "{2}{U}",
            replaces_first_tokens_with_copies=True,
        ),
        # Tractor Beam `{2}{U}{U}` Enchantment — Aura. Real oracle:
        # "Enchant creature or Spacecraft. When this Aura enters, tap
        # enchanted permanent. You control enchanted permanent.
        # Enchanted permanent doesn't untap during its controller's
        # untap step."
        # Partial implementation: ETB tap + don't-untap clause
        # (attached_prevents_untap). The gain-control clause is NOT
        # modeled — the enchanted permanent remains under its original
        # controller even while Tractor Beam is on it. Stand-in's
        # placeholder +2/+2 bonus dropped (real card has none).
        make_aura(
            "Tractor Beam", "{2}{U}{U}",
            attached_prevents_untap=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=TractorBeamETBEffect(),
                ),
            ),
        ),
        # Chorale of the Void `{3}{B}` Enchantment — Aura. Real oracle:
        # "Enchant creature you control. Whenever enchanted creature
        # attacks, put target creature card from defending player's
        # graveyard onto the battlefield under your control tapped and
        # attacking. Void — At the beginning of your end step,
        # sacrifice this Aura unless [Void active]."
        # No printed P/T bonus (stand-in had placeholder +2/+2).
        make_aura(
            "Chorale of the Void", "{3}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="enchanted_creature_attacks",
                    effect=ChoraleReanimateDefenderGraveCreatureEffect(),
                ),
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=SacrificeSelfUnlessVoidActive(),
                ),
            ),
        ),
        # Pain for All `{2}{R}` Enchantment — Aura. Real oracle:
        # "Enchant creature you control. When this Aura enters,
        # enchanted creature deals damage equal to its power to any
        # other target. Whenever enchanted creature is dealt damage,
        # it deals that much damage to each opponent."
        # No printed P/T bonus (stand-in placeholder +3/+0 dropped).
        make_aura(
            "Pain for All", "{2}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PainForAllETBEffect(),
                ),
                TriggeredAbility(
                    trigger="enchanted_creature_dealt_damage",
                    effect=PainForAllDamageEchoEffect(),
                ),
            ),
        ),
        # Artifacts — ship as empty/inert bodies, dropping complex text.
        # Pinnacle Starcage `{1}{W}{W}` Artifact. Real oracle:
        # "When this artifact enters, exile all artifacts and creatures
        # with mana value 2 or less until this artifact leaves the
        # battlefield. {6}{W}{W}: Put each card exiled with this
        # artifact into its owner's graveyard, then create a 2/2
        # colorless Robot artifact creature token for each card put
        # into a graveyard this way. Sacrifice this artifact."
        make_artifact(
            "Pinnacle Starcage", "{1}{W}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PinnacleStarcageETBEffect(),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{6}{W}{W}"),
                        mana_str="{6}{W}{W}",
                    ),
                    effect=PinnacleStarcageSacEffect(),
                ),
            ),
        ),
        # Requiem Monolith `{2}{B}` Artifact. Real oracle:
        # "{T}: Until end of turn, target creature gains 'Whenever this
        # creature is dealt damage, you draw that many cards and lose
        # that much life.' That creature's controller may have this
        # artifact deal 1 damage to it. Activate only as a sorcery."
        # Simplified to a one-shot: ping 1, draw 1, lose 1 (the UEOT
        # grant is not modeled — see effect docstring).
        make_artifact(
            "Requiem Monolith", "{2}{B}",
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=RequiemMonolithActivatedEffect(),
                    sorcery_speed=True,
                ),
            ),
        ),
        # Memorial Vault `{3}{R}` Artifact. Real oracle: "{T},
        # Sacrifice another artifact: Exile the top X cards of your
        # library, where X is one plus the mana value of the
        # sacrificed artifact. You may play those cards this turn."
        # Simplification: uses sacrifice_another_creature_or_artifact
        # (slightly wider than oracle's "another artifact").
        make_artifact(
            "Memorial Vault", "{3}{R}",
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        tap_self=True,
                        sacrifice_another_creature_or_artifact=True,
                    ),
                    effect=MemorialVaultActivatedEffect(),
                ),
            ),
        ),
        # All-Fates Scroll `{3}` Artifact. Real oracle: "{T}: Add one
        # mana of any color. {7}, {T}, Sacrifice this artifact: Draw X
        # cards, where X is the number of differently named lands you
        # control." Now that the engine has a mana pool the first
        # ability is implemented as AddManaToPool(any-color). Each
        # ability uses {T} so activating one locks out the other on
        # a given turn.
        make_artifact(
            "All-Fates Scroll", "{3}",
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(produces=(("any", 1),)),
                    is_mana_ability=True,
                ),
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{7}"),
                        mana_str="{7}",
                        tap_self=True,
                        sacrifice_self=True,
                    ),
                    effect=AllFatesScrollDrawEffect(),
                ),
            ),
        ),
        # The Endstone `{7}` Legendary Artifact:
        # - Whenever you play a land or cast a spell, draw a card.
        # - At the beginning of your end step, your life total becomes
        #   half your starting life total, rounded up.
        make_artifact(
            "The Endstone", "{7}",
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="cast_spell_or_play_land",
                    effect=DrawCards(amount=1),
                ),
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=SetLifeToHalfStartingRoundedUp(),
                ),
            ),
        ),
        # Nutrient Block `{1}` Artifact — Food.
        # - Indestructible.
        # - {2}, {T}, Sacrifice this artifact: You gain 3 life.
        # - When this artifact is put into a graveyard from the
        #   battlefield, draw a card. Modeled via leaves_battlefield
        #   (slightly looser — also fires if exiled, but that's a rare
        #   edge case).
        make_artifact(
            "Nutrient Block", "{1}",
            keywords={"indestructible"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="leaves_battlefield",
                    effect=DrawCards(amount=1),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(
                        mana="{2}", tap_self=True, sacrifice_self=True,
                    ),
                    effect=GainLife(amount=3),
                ),
            ),
        ),
        # Thrumming Hivepool `{6}` Artifact. Real oracle: "Affinity for
        # Slivers. Slivers you control have double strike and haste.
        # At the beginning of your upkeep, create two 1/1 colorless
        # Sliver creature tokens."
        # Simplifications: Affinity (cost reduction) is dropped; the
        # upkeep trigger is wired to beginning_of_end_step (the engine
        # has no beginning_of_upkeep trigger yet). The Sliver anthem
        # grants double strike + haste via a SLIVERS_YOU_CONTROL static.
        make_artifact(
            "Thrumming Hivepool", "{6}",
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.SLIVERS_YOU_CONTROL,
                    granted_keywords=frozenset({"double strike", "haste"}),
                ),
            ),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Sliver"],
                        count=2,
                    ),
                ),
            ),
        ),
        # The Dominion Bracelet `{2}` Legendary Artifact — Equipment.
        # Real oracle: "Equipped creature gets +1/+1 and has '{15},
        # Exile The Dominion Bracelet: You control target opponent
        # during their next turn. This ability costs {X} less to
        # activate, where X is this creature's power. Activate only
        # as a sorcery.' Equip {1}"
        # The granted ability (DOMINION_BRACELET_GRANTED_ABILITY) is
        # appended via game.effective_activated_abilities when the
        # Bracelet is attached.
        make_equipment(
            "The Dominion Bracelet", "{2}",
            legendary=True,
            power_bonus=1, toughness_bonus=1,
            grants_control_opponent_ability_when_equipped=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=AttachToTargetCreatureYouControl(),
                ),
            ),
        ),
        # Atomic Microsizer `{U}` Artifact — Equipment. Real oracle:
        # "Equipped creature gets +1/+0. Whenever equipped creature
        # attacks, choose up to one target creature. That creature
        # can't be blocked this turn and has base power and toughness
        # 1/1 until end of turn. Equip {2}"
        make_equipment(
            "Atomic Microsizer", "{U}",
            power_bonus=1, toughness_bonus=0,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=AttachToTargetCreatureYouControl(),
                ),
                TriggeredAbility(
                    trigger="equipped_creature_attacks",
                    effect=AtomicMicrosizerAttackEffect(),
                ),
            ),
        ),
        # Enchantments — ship as empty or minimal.
        # Weftwalking `{4}{U}{U}` Enchantment. Real oracle: "When this
        # enchantment enters, if you cast it, shuffle your hand and
        # graveyard into your library, then draw seven cards. The
        # first spell each player casts during each of their turns may
        # be cast without paying its mana cost." Simplification: the
        # second (static, alt-cast) ability is NOT modeled.
        make_enchantment(
            "Weftwalking", "{4}{U}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=WeftwalkingETBEffect(),
                ),
            ),
        ),
        # Sothera, the Supervoid `{2}{B}{B}` Legendary Enchantment.
        # Real oracle: "Whenever a creature you control dies, each
        # opponent chooses a creature they control and exiles it. At
        # the beginning of your end step, if a player controls no
        # creatures, sacrifice Sothera, then put a creature card
        # exiled with it onto the battlefield under your control with
        # two additional +1/+1 counters on it."
        make_enchantment(
            "Sothera, the Supervoid", "{2}{B}{B}",
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="your_creature_or_artifact_dies",
                    effect=SotheraExileOpponentCreatureEffect(),
                ),
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=SotheraEndStepReanimateEffect(),
                ),
            ),
        ),
        # Loading Zone `{3}{G}` Enchantment. Warp `{G}`.
        # "If one or more counters would be put on a creature,
        # Spacecraft, or Planet you control, twice that many of each
        # of those kinds of counters are put on it instead."
        # Simplification: only +1/+1 counters on creatures/Spacecraft
        # you control get doubled. Other counter kinds (charge, stun,
        # loyalty) aren't doubled; the "Planet" type isn't modeled.
        make_enchantment(
            "Loading Zone", "{3}{G}",
            warp="{G}",
            is_counter_doubler=True,
        ),
        # Terrasymbiosis `{2}{G}` Enchantment. Real oracle: "Whenever
        # you put one or more +1/+1 counters on a creature you control,
        # you may draw that many cards. Do this only once each turn."
        make_enchantment(
            "Terrasymbiosis", "{2}{G}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="counters_added_to_your_creature",
                    effect=DrawCardsEqualToResolvingCounterAmount(),
                    once_per_turn=True,
                ),
            ),
        ),
        # Instants — remaining ones shipped as minimal approximations.
        make_instant(  # Archenemy's Charm — simplified to just exile-target-creature mode.
            "Archenemy's Charm", "{B}{B}{B}",
            effect=ExileTargetCreature(),
        ),
        # Close Encounter `{1}{G}` Instant:
        # "As an additional cost to cast this spell, choose a creature
        # you control or a warped creature card you own in exile.
        # Close Encounter deals damage equal to the power of the chosen
        # creature or card to target creature."
        # Simplification: the "warped creature card in exile" branch
        # of the additional-cost pick is dropped; the cost is
        # "designate a creature you control". Still a significant
        # improvement over the plain 3-damage shipped version.
        make_instant(
            "Close Encounter", "{1}{G}",
            effect=CloseEncounterEffect(),
            additional_cost_choose_your_creature=True,
        ),
        make_instant(  # Diplomatic Relations — simplified to +1/+0+vigilance pump-only.
            "Diplomatic Relations", "{2}{G}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=1, toughness_bonus=0,
                granted_keywords=frozenset({"vigilance"}),
                you_control_only=True,
            ),
        ),
        # Scour for Scrap `{3}{U}` Instant — "Choose one or both":
        #   • Search your library for an artifact card, reveal it, put it
        #     into your hand, then shuffle.
        #   • Return target artifact card from your graveyard to your hand.
        # Simplification: modeled as "choose one" (not both) via
        # ModalChooseOne; dropping the "or both" clause.
        make_instant(
            "Scour for Scrap", "{3}{U}",
            effect=ModalChooseOne(modes=(
                SearchLibraryForCard(
                    filter_name="artifact", may_fail=True,
                ),
                ReturnTargetArtifactCardFromYourGraveyardToHand(),
            )),
        ),
        # Sorceries — remaining ones shipped as minimal approximations.
        # Zero Point Ballad `{X}{B}` — full effect: destroy creatures
        # with toughness ≤ X, caster loses X life, if X ≥ 6 return a
        # creature card put into a graveyard this way.
        make_sorcery(
            "Zero Point Ballad", "{X}{B}",
            effect=ZeroPointBalladEffect(),
        ),
        # Devastating Onslaught `{X}{X}{R}` — create X tokens that are
        # copies of target artifact or creature you control; they gain
        # haste until end of turn and are sacrificed at the next end step.
        make_sorcery(
            "Devastating Onslaught", "{X}{X}{R}",
            effect=CreateXTokensOfTargetPermanentWithHasteEndStepSac(),
        ),
        # Systems Override `{2}{R}` Sorcery: gain control of target
        # artifact or creature UEOT, untap it, haste UEOT. If it's a
        # Spacecraft, put ten charge counters on it, then remove ten
        # at the beginning of the next end step.
        make_sorcery(
            "Systems Override", "{2}{R}",
            effect=SystemsOverrideEffect(),
        ),
        make_sorcery(  # Terminal Velocity — put-card-from-hand + haste. Ship as token creation.
            "Terminal Velocity", "{4}{R}{R}",
            effect=CreateToken(
                token_printing=TOKEN_PRINTINGS["Robot"], count=2
            ),
        ),
        make_sorcery(  # Pull Through the Weft — multi-target GY return. Ship as single-target GY-to-hand.
            "Pull Through the Weft", "{3}{G}{G}",
            effect=ReturnCreatureFromYourGraveyardToHand(),
        ),
        # Mutinous Massacre `{3}{B}{B}{R}{R}`:
        # "Choose odd or even. Destroy each creature with mana value of
        # the chosen quality. Then gain control of all creatures until
        # end of turn. Untap them. They gain haste until end of turn."
        make_sorcery(
            "Mutinous Massacre", "{3}{B}{B}{R}{R}",
            effect=MutinousMassacreEffect(),
        ),
        # -- Batch of simplified spells. Each drops complex riders in
        # favor of a minimal usable effect. Simplifications noted.
        # Consult the Star Charts `{1}{U}` with Kicker `{1}{U}`:
        # Look at the top X cards of your library (X = lands you
        # control). Put one of those cards into your hand (two if
        # kicked). Put the rest on the bottom in a random order.
        make_instant(
            "Consult the Star Charts", "{1}{U}",
            effect=ConsultTheStarChartsEffect(),
            kicker="{1}{U}",
        ),
        make_instant(  # Divert Disaster — drops pay-{2}-or-lander rider; ships as plain counter.
            "Divert Disaster", "{1}{U}",
            effect=CounterTargetSpell(),
        ),
        make_instant(  # Lost in Space — drops bounce-to-library; ships as Surveil 1.
            "Lost in Space", "{3}{U}",
            effect=Surveil(amount=1),
        ),
        make_instant(  # Unravel — drops the draw-card rider; ships as plain counter.
            "Unravel", "{1}{U}{U}",
            effect=CounterTargetSpell(),
        ),
        make_sorcery(  # Scrounge for Eternity — drops the Lander rider; creature-card-only graveyard return.
            "Scrounge for Eternity", "{2}{B}",
            effect=ReturnCreatureFromYourGraveyardToBattlefield(),
            additional_cost_sacrifice_creature_or_artifact=True,
        ),
        # Lithobraking `{2}{R}` — "Create a Lander token. Then you may
        # sacrifice an artifact. When you do, Lithobraking deals 2
        # damage to each creature."
        # Simplification: the "may" decision is always yes (no decline
        # option on choose_sacrifice); this matches the same treatment
        # in OptionalSacAnotherForEffect and is often the right call.
        make_instant(
            "Lithobraking", "{2}{R}",
            effect=Sequence(effects=(
                CreateToken(
                    token_printing=TOKEN_PRINTINGS["Lander"], count=1
                ),
                OptionalSacArtifactForEffect(
                    inner_effect=DealNDamageToEachCreature(amount=2),
                ),
            )),
        ),
        # Orbital Plunge `{3}{R}` — deals 6 damage to target creature.
        # If excess damage was dealt this way, create a Lander token.
        make_sorcery(
            "Orbital Plunge", "{3}{R}",
            effect=DealDamageToTargetCreatureWithExcessLanderRider(
                amount=6,
            ),
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
        # Embrace Oblivion — {B} Sorcery with an additional-cost sac.
        # Destroy target creature or Spacecraft. Our DestroyTargetCreature
        # handles creatures; we drop the "or Spacecraft" option (a
        # stationed Spacecraft is a creature and IS a legal target via
        # is_creature_now, so the only loss is unstationed Spacecraft).
        make_sorcery(
            "Embrace Oblivion", "{B}",
            effect=DestroyTargetCreature(),
            additional_cost_sacrifice_creature_or_artifact=True,
        ),
        # Temporal Intervention — directed discard with a Void cost
        # reduction rider.
        make_sorcery(
            "Temporal Intervention", "{2}{B}",
            effect=TargetOpponentDiscardsCasterChoice(),
            cost_reductions=(
                CostReduction(amount=2, condition="void_active"),
            ),
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
        # Dark Endurance — +2/+0 and indestructible UEOT. Simplified:
        # drops the "costs {1} less if it targets a blocking creature"
        # rider (cost modification not yet modeled).
        make_instant(
            "Dark Endurance", "{1}{B}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=2, toughness_bonus=0,
                granted_keywords=frozenset({"indestructible"}),
            ),
        ),
        # Full Bore — +3/+2 UEOT on target creature you control.
        # Simplified: drops the "if it was cast for its warp cost, also
        # gains trample and haste UEOT" rider (warp-cast detection would
        # be easy to add but the rider rarely matters in a mono-red deck).
        make_instant(
            "Full Bore", "{R}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=3, toughness_bonus=2,
                you_control_only=True,
            ),
        ),
        # Seedship Impact — destroy artifact/enchantment; if MV ≤ 2,
        # create a Lander.
        make_instant(
            "Seedship Impact", "{1}{G}",
            effect=SeedshipImpactEffect(),
        ),
        # Biosynthic Burst — +1/+1 counter + reach/trample/indestructible
        # UEOT + untap.
        make_instant(
            "Biosynthic Burst", "{1}{G}",
            effect=BiosynthicBurstEffect(),
        ),
        # Scout for Survivors — reanimate up to 3 small creatures with
        # +1/+1 counter on each. Simplified: real card says "total mana
        # value 3 or less" (sum); we use per-card filter instead.
        make_sorcery(
            "Scout for Survivors", "{2}{W}",
            effect=ReturnUpToNSmallCreaturesFromGraveyardWithCounters(
                max_n=3, max_mv=3,
            ),
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
        # Singularity Rupture `{3}{U}{B}{B}`:
        # "Destroy all creatures, then any number of target players
        # each mill half their library, rounded down."
        make_sorcery(
            "Singularity Rupture", "{3}{U}{B}{B}",
            effect=SingularityRuptureEffect(),
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
    return {
        **BASIC_LANDS,
        **SHOCK_LANDS,
        **UTILITY_LANDS,
        **PLANET_LANDS,
        **STELLAR_SIGHTS_LANDS,
        **NONLAND_POOL,
    }


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
