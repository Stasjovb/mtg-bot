"""Generic, reusable effects — damage, life, counters, zone moves,
tokens, pumps, search, draw, tap/untap, etc. Card-agnostic primitives that
many printings reuse. Card-specific one-off effects live in ``bespoke.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mtg_bot.effects.base import (
    Effect, Target, TriggeredAbility,
    _apply_damage, _multicolored_permanents_count,
    _find_moonlit_replacement_source,
)

if TYPE_CHECKING:
    from mtg_bot.cards import ManaCost
    from mtg_bot.effects.formulas import Formula
    from mtg_bot.game import GameState


# DealDamage and its helpers moved earlier in the file (above
# DealDamageToTargetOpponent at line ~1620 in the pre-collapse
# layout) so the sugar subclasses can reference DealDamage at class-
# definition time. See the canonical DealDamage definition near the
# top of the module.



# ---------------------------------------------------------------------------
# Threaten core (gain control + untap + grant haste UEOT, on a single target)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Paired-target opposite-polarity pump/debuff (audit-monoist-chorale).
#
# Models a single resolving effect that picks TWO distinct creature
# targets — one matching ``positive_kind`` (e.g. ``"my_creature"``) and
# one matching ``negative_kind`` (e.g. ``"creature"`` for an opponent's
# creature) — and grants opposite UEOT P/T deltas keyed off a shared X
# computed at resolve time from a ``Formula``.
#
# Why not a ``Sequence``: the engine's ``Sequence`` combinator restricts
# itself to a SINGLE targeting sub-effect by design (the cast-time
# target-selection pipeline picks one target prompt per cast).
# Two-target paired-polarity bodies (Monoist Circuit-Feeder) need both
# slots filled atomically, with a shared X, in one trigger firing —
# decomposing into ``Sequence(PumpYourCreature, DebuffOppCreature)``
# would either double-prompt the targeting pipeline (illegal) or drop
# one of the targets (silent no-op, forbidden).
#
# Future direction (Option B in the audit notes): extend the
# ``Effect.targets`` grammar to declare ``targets: tuple[TargetSpec,
# ...]`` with multiple slots and wire the cast/activation pipeline to
# ask the agent for one target per slot. That refactor unblocks
# multi-target spells generally; until then this primitive is the
# contained "ship-now" answer for the paired-polarity shape.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Reanimate from defending player's graveyard, tapped + attacking
# (audit-monoist-chorale).
#
# Models the Chorale of the Void attacks-trigger reanimate body:
# "put target creature card from defending player's graveyard onto the
# battlefield under your control tapped and attacking".
#
# 2-player simplification: legal targets = any creature card in any
# opponent's graveyard. The engine's combat model doesn't thread the
# per-attacker defending-player identity into a slot the resolving
# effect can read, so the multi-defender / multiplayer / planeswalker-
# defender variants degrade to "any opponent's graveyard" — matching
# the printed text exactly in 2-player and approximating it elsewhere.
# When the engine grows a per-attacker defending-player slot, this
# primitive will read it; the public API doesn't need to change.
#
# The reanimated card enters tapped AND attacking. Combat-state
# bookkeeping marks the card ``attacking=True`` and clears
# ``summoning_sick`` so it's a "real" attacker for the rest of the
# combat phase. The engine's combat damage path reads
# ``obj.attacking`` and applies damage to the defending player by id
# (via the ``defending_player_id`` argument threaded from
# ``resolve_combat_damage``); the engine doesn't carry a
# per-attacker defender slot today, so the new attacker rides the
# combat phase's single defender id implicitly.
# ---------------------------------------------------------------------------


from mtg_bot.effects.generic.targets_helpers import (
    _eff_subtypes,
    _slot_target_still_legal,
    _fizzle_message,
    _describe_targets,
    _describe_filter,
    _bounce_to_hand,
)

from mtg_bot.effects.generic.damage import (
    DealDamage,
    DealDamageToTargetOpponent,
    DealDamageEachOpponent,
    DealNDamageToEachCreature,
    DealDamageToControllerAndAddMana,
    DealDamageEqualToSourcePowerAnyTarget,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DealDamageToTargetCreatureWithExcessLanderRider,
    DealDamageToOpponentCreatureByArtifactCount,
    DealDamageToOpponentCreatureByCardsInHand,
    DealDamageToTargetCreatureSpacecraftBoosted,
    DealDamageToOpponentCreature,
    DealDamageToTargetTappedCreature,
    MayHaveSourceDealDamageToTarget,
    DrawCardsAndLoseLifeEqualToResolvingDamage,
)

from mtg_bot.effects.generic.grant_keywords import (
    GrantUnblockable,
    GrantUnblockableUEOT,
    GrantTriggeredAbilityUEOT,
    GrantKeywords,
    GrantActivatedAbility,
    GrantTriggeredAbility,
)

from mtg_bot.effects.generic.pump import (
    Pump,
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    DoubleTargetCreaturesPowerUEOT,
    PumpTargetCreatureUntilEOT,
    SetBasePTUntilEOT,
    SetBasePTConditionalUntilEOT,
    PumpSelfUntilEOT,
    PumpCreaturesYouControlUntilEOT,
    PumpCreaturesOpponentsControlUntilEOT,
    PumpSelfXPowerUEOT,
    SwitchSourcePowerToughnessUEOT,
    PumpTargetArtifactOrCreatureUntilEOT,
    ThreatenTargetCreatureUEOT,
    _signed,
    PairedTargetPumpDebuffUEOT,
)

from mtg_bot.effects.generic.counters import (
    PutPlusOneCounters,
    PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    PutPlusOneCounterOnTargetCreature,
    PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnOpponentsCreature,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    PutChargeCountersOnTargetSpacecraftYouControl,
    PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    PutChargeCountersOnSelf,
    PutPoisonCountersOnTargetPlayer,
    PutStunCounterOnTappedCreature,
    PutLoyaltyCounterOnSelf,
    MoveSelfCountersToTargetCreatureYouControl,
    MovePlusOneCounterBetweenPermanentsYouControl,
)

from mtg_bot.effects.generic.destroy import (
    Destroy,
    DestroyTargetCreature,
    DestroyEnchantedPermanent,
    DestroyTargetArtifact,
    DestroyTargetNoncreaturePermanent,
    DestroyTargetLand,
    DestroyTargetNonlandPermanent,
    DestroyUpToOneTargetNonlandPermanent,
    RegenerateTargetCreature,
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    DestroyTargetArtifactOrTappedCreature,
    DestroyTargetArtifactEnchantmentOrFlyingCreature,
    DestroyAllCreatures,
    DestroyTargetNonlandPermanentWithLanderForController,
)

from mtg_bot.effects.generic.tap import (
    Tap,
    UntapTargetLand,
    IfGainedLifeThisTurnUntapSelf,
    TapTargetOpponentPermanentAndStunIt,
    TapAndStunUpToOneTargetCreature,
    TapAnotherTargetCreature,
    TapUpToOneTargetCreature,
    TapTargetArtifactOrCreature,
    UntapTargetOtherPermanent,
    PhaseOutEquippedCreature,
    TapEnchantedPermanent,
)

from mtg_bot.effects.generic.exile import (
    Exile,
    ExileTargetCreatureUntilSourceLeaves,
    ExileOpponentsNonlandPermanentUntilLeaves,
    ExileTargetCreature,
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    ExileTargetCardFromGraveyard,
    ExileTargetAttackingCreatureUntilEndStep,
    ExileEachOpponentsGraveyard,
    ExileAllGraveyards,
    ExileAllArtifactsWithManaValueAtMost,
    ExileAllCreaturesAndSpacecraft,
    ExileTopOfLibraryMayPlayThisTurn,
    ExileTopXOfLibraryMayPlayThisTurn,
    ExileAllMatchingUntilSourceLeaves,
    WarpExileSelf,
    ReturnExiledPermanentToOwnerTapped,
    MoveEachExiledWithSourceToOwnersGraveyard,
    CreateNTokensFromLastExileRecall,
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    ReanimateOneExiledWithSourceWithCounters,
    SacrificeSelf,
    SacrificeSelfPreservingExileLink,
)

from mtg_bot.effects.generic.bounce import (
    Bounce,
    ReturnTargetCreatureToOwnersHand,
    ReturnTargetPermanentYouControlToOwnersHand,
    ReturnUpToNTargetCreaturesToOwnersHands,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnUpToNCreaturesFromYourGraveyardToHand,
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    ReturnTargetLandFromGraveyardToHand,
    ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
)

from mtg_bot.effects.generic.delayed_actions import (
    SacrificeSourceDelayed,
    ScheduleSelfSacAtNextEndStep,
    RemoveChargeCountersFromSourceDelayed,
)

from mtg_bot.effects.generic.tokens import (
    CreateLanderAndScheduleSacrifice,
    CreateTokenAndAttachSelf,
    CreateTokenPerMulticoloredPermanent,
    CreateToken,
    CreateTokenCopyOfTargetCreatureYouControl,
    CreateXTokensOfTargetPermanentWithHasteEndStepSac,
)

from mtg_bot.effects.generic.mana import (
    AddManaToPool,
    AddNManaOfChosenColor,
    AddChargeCounterManaOfChosenColor,
    AddOneManaFromControlledLandsProductions,
    AddOneManaOfChosenPermanentColor,
)

from mtg_bot.effects.generic.search import (
    SearchLibraryForCard,
    SearchLibraryForBasicLandTapped,
    SearchLibraryForEquipmentToBattlefield,
    SearchLibraryForGreenCreatureWithMVAtMostX,
)

from mtg_bot.effects.generic.library_lookat import (
    LookAtTopNRevealOrCounter,
    LookAtTopTwoSplitHandGraveyard,
    LookTopNPutOneInHandRestToGraveyard,
    PeekTopMayBattlefieldIfLandElseHand,
    ManifestDread,
    ManifestDreadThenPutPlusOneCountersOnIt,
    ManifestDreadThenAttachSelf,
    Surveil,
    SelfMill,
)

from mtg_bot.effects.generic.life import (
    GainLife,
    SetLifeToHalfStartingRoundedUp,
    TargetPlayerLosesLife,
    EachOpponentDiscardsOrLosesLife,
    LoseLife,
    EachOpponentLosesLife,
    TargetOpponentLosesNYouGainN,
    TargetOpponentLosesLife,
    GrantLifeToEachOpponent,
    DefendingPlayerLosesHalfLifeRoundedUp,
)

from mtg_bot.effects.generic.discard import (
    DiscardSelf,
    DiscardHandThenDrawN,
    EachOpponentDiscards,
    EachOpponentExilesCardFromHandWithCastPermission,
    TargetOpponentDiscardsCasterChoice,
    TargetOpponentLookHandMayDiscard,
    TargetOpponentDiscards,
)

from mtg_bot.effects.generic.draw_mill import (
    EachOpponentMillsCards,
    DrawCardsEqualToResolvingCounterAmount,
    DrawCardsEqualToResolvingCombatDamage,
    DrawCardPerMulticoloredPermanent,
    MillTargetPlayer,
    DrawCards,
    EachPlayerDraws,
    DrawCardsByConditionMultiplier,
)

from mtg_bot.effects.generic.become_type import (
    BecomeType,
    BecomeLandCreatureUEOT,
    BecomesCopyOfTargetLand,
    TargetArtifactBecomesCreatureUEOT,
)

from mtg_bot.effects.generic.attach import (
    AttachToTargetCreatureYouControl,
    EquipToTargetCreatureYouControl,
)

from mtg_bot.effects.generic.graveyard import (
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnAllCreaturesFromYourGraveyardToBattlefield,
    PutCardFromGraveyardOnBottomOfLibrary,
    ReanimateTargetCreatureCardFromDefendersGraveyard,
)

from mtg_bot.effects.generic.zone_moves import (
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
    PutBasicLandFromHandOntoBattlefieldTapped,
    SacrificeNLandsYouControl,
    ShuffleZonesIntoLibrary,
)

from mtg_bot.effects.generic.control import (
    ControlTargetOpponentNextTurn,
    ChangeControllerToCombatDamageSource,
    GainControlOfTargetSliverPermanently,
)

from mtg_bot.effects.generic.stack_control import (
    CopyTargetInstantOrSorceryYouControl,
    CounterTargetSpell,
    TakeExtraTurnAfterThisOne,
    PreventAllCombatDamageThisTurn,
)

from mtg_bot.effects.generic.opponent_punishers import (
    EachOpponentSacrificesCreature,
    TargetOpponentSacrificesCreatureOtherThanEnchanted,
    EachOpponentExilesOwnCreature,
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
)

from mtg_bot.effects.generic.text_change import (
    MagicalHackTextChangeEffect,
    SleightOfMindTextChangeEffect,
)

from mtg_bot.effects.generic.misc import (
    CytoshapeBecomeCopyUEOT,
    ScuttlemuttColorChangeUEOT,
    LockOrUnlockDoorOfTargetRoomYouControl,
)
