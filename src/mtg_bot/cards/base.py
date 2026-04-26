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
    ConditionalIfYouControlAtLeast,
    ControlTargetOpponentNextTurn,
    DealDamageToControllerAndAddMana,
    BecomeLandCreatureUEOT,
    BecomesCopyOfTargetLand,
    ChangeControllerToCombatDamageSource,
    CopyTargetInstantOrSorceryYouControl,
    CreateTokenCopyOfTargetCreatureYouControl,
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    DestroyTargetLand,
    ExileAllGraveyards,
    ExileTargetAttackingCreatureUntilEndStep,
    GrantLifeToEachOpponent,
    PutBasicLandFromHandOntoBattlefieldTapped,
    ReturnTargetLandFromGraveyardToHand,
    SacrificeNLandsYouControl,
    UntapTargetLand,
    Sequence,
    AddManaToPool,
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
    DestroyEnchantedPermanent,
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
    MovePlusOneCounterBetweenPermanentsYouControl,
    MoveSelfCountersToTargetCreatureYouControl,
    RegenerateTargetCreature,
    UntapTargetOtherPermanent,
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    PutChargeCountersOnSelf,
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
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    GainControlOfTargetSliverPermanently,
    GainLife,
    IfGainedLifeThisTurnUntapSelf,
    LoseLife,
    PutCardFromGraveyardOnBottomOfLibrary,
    PumpCreaturesYouControlUntilEOT,
    PutPlusOneCounterOnOpponentsCreature,
    PumpSelfUntilEOT,
    PhaseOutEquippedCreature,
    PreventAllCombatDamageThisTurn,
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
    OptionalPutLandFromHandOntoBattlefield,
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
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    SelfMill,
    MillTargetPlayer,
    SearchLibraryForBasicLandTapped,
    SearchLibraryForCard,
    SearchLibraryForGreenCreatureWithMVAtMostX,
    TakeExtraTurnAfterThisOne,
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
    # Echoing Deeps: "You may have this land enter tapped as a copy of
    # any land card in a graveyard, except it's a Cave in addition to
    # its other types." When True, _play_land offers the controller's
    # agent a graveyard-land target. If they pick one, the played
    # land's printing is replaced with a Cave-injected copy of the
    # target and it enters tapped. If they decline (or no legal
    # target exists), the land enters per its normal rules.
    optional_copy_land_from_graveyard: bool = False
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
    # Spell-cast restriction: when any permanent with this flag is on
    # the battlefield (regardless of controller), each player may cast
    # at most one noncreature spell per turn. Matches Deafening Silence.
    # Enforced by legal.legal_actions — noncreature CastSpell actions
    # aren't proposed once the caster's
    # Player.noncreature_spells_cast_this_turn is already ≥ 1.
    restricts_noncreature_spells_to_one_per_turn: bool = False
    # Type-change flag: while any permanent with this flag is on the
    # battlefield, every nonbasic land's mana-production colors are
    # overridden to {R} and its activated abilities are suppressed —
    # the Magus of the Moon "Nonbasic lands are Mountains" static.
    # Consumed by game.effective_land_produces and
    # game.effective_activated_abilities. Simplification: subtypes
    # aren't rewritten, and already-animated manlands keep their
    # temp_is_creature state (no layers yet).
    nonbasic_lands_are_mountains: bool = False
    # Zone-change replacement: when this card would be put into a
    # graveyard from ANY zone the engine currently models, instead it
    # is shuffled into its owner's library. Consumed by
    # actions._send_to_graveyard_or_library at the spell-resolve,
    # spell-countered, and failed-cast graveyard sites. Matches
    # Nexus of Fate's "from anywhere" clause and Green Sun's Zenith's
    # self-shuffle rider (GSZ's oracle is effectively the same
    # replacement after its tutor effect resolves). Simplification:
    # discard-from-hand and mill-from-library graveyard paths aren't
    # hooked (those aren't hit by any currently-modeled card that
    # targets Nexus / GSZ specifically).
    shuffles_into_library_instead_of_graveyard: bool = False

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
    nonbasic_lands_are_mountains: bool = False,
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
        nonbasic_lands_are_mountains=nonbasic_lands_are_mountains,
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
    shuffles_into_library_instead_of_graveyard: bool = False,
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
        shuffles_into_library_instead_of_graveyard=(
            shuffles_into_library_instead_of_graveyard
        ),
    )


def make_sorcery(
    name: str, cost: str, effect: Effect,
    cost_reductions: tuple[CostReduction, ...] = (),
    additional_cost_sacrifice_creature_or_artifact: bool = False,
    shuffles_into_library_instead_of_graveyard: bool = False,
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
        shuffles_into_library_instead_of_graveyard=(
            shuffles_into_library_instead_of_graveyard
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
    restricts_noncreature_spells_to_one_per_turn: bool = False,
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
        restricts_noncreature_spells_to_one_per_turn=(
            restricts_noncreature_spells_to_one_per_turn
        ),
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


def make_utility_land(
    name: str,
    produces: "frozenset[str]" = frozenset(),
    subtypes_str: str = "",
    legendary: bool = False,
    triggered_abilities: tuple = (),
    activated_abilities: tuple = (),
    enters_tapped: bool = False,
    keywords: "frozenset[str] | set[str] | tuple[str, ...]" = (),
    optional_copy_land_from_graveyard: bool = False,
) -> CardPrinting:
    """Build a non-basic land with arbitrary activated/triggered
    abilities and an explicit produces set. Used by Stellar Sights."""
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
        produces=frozenset(produces),
        triggered_abilities=tuple(triggered_abilities),
        activated_abilities=tuple(activated_abilities),
        enters_tapped=enters_tapped,
        keywords=frozenset(keywords),
        optional_copy_land_from_graveyard=optional_copy_land_from_graveyard,
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
