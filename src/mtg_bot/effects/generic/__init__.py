"""Generic, reusable effects — damage, life, counters, zone moves,
tokens, pumps, search, draw, tap/untap, etc. Card-agnostic primitives that
many printings reuse. Card-specific one-off effects live in ``bespoke.py``.

This package is organised into per-cluster submodules (``damage``,
``pump``, ``counters``, ``destroy``, ``tap``, ``exile``, ``bounce``,
``tokens``, ``mana``, ``search``, ``library_lookat``, ``life``,
``discard``, ``draw_mill``, ``grant_keywords``, ``become_type``,
``attach``, ``graveyard``, ``zone_moves``, ``delayed_actions``,
``control``, ``stack_control``, ``opponent_punishers``, ``text_change``,
``misc``, plus the shared ``targets_helpers``). Every public name is
re-exported here, so consumers can keep doing
``from mtg_bot.effects.generic import X`` exactly as before.
"""

from __future__ import annotations

from mtg_bot.effects.generic.targets_helpers import (
    _bounce_to_hand,
    _describe_filter,
    _describe_targets,
    _eff_subtypes,
    _fizzle_message,
    _slot_target_still_legal,
)

from mtg_bot.effects.generic.damage import (
    DealDamage,
    DealDamageAnyTarget,
    DealDamageEachOpponent,
    DealDamageEqualToSourcePowerAnyTarget,
    DealDamageToControllerAndAddMana,
    DealDamageToOpponentCreature,
    DealDamageToOpponentCreatureByArtifactCount,
    DealDamageToOpponentCreatureByCardsInHand,
    DealDamageToTargetCreature,
    DealDamageToTargetCreatureSpacecraftBoosted,
    DealDamageToTargetCreatureWithExcessLanderRider,
    DealDamageToTargetOpponent,
    DealDamageToTargetTappedCreature,
    DealNDamageToEachCreature,
    DrawCardsAndLoseLifeEqualToResolvingDamage,
    FightTargetCreatureWithTargetCreature,
    MayHaveSourceDealDamageToTarget,
)

from mtg_bot.effects.generic.grant_keywords import (
    GrantActivatedAbility,
    GrantKeywords,
    GrantTriggeredAbility,
    GrantTriggeredAbilityUEOT,
    GrantUnblockable,
    GrantUnblockableUEOT,
)

from mtg_bot.effects.generic.pump import (
    DoubleTargetCreaturesPowerUEOT,
    PairedTargetPumpDebuffUEOT,
    Pump,
    PumpCreaturesOpponentsControlUntilEOT,
    PumpCreaturesYouControlUntilEOT,
    PumpSelfUntilEOT,
    PumpSelfXPowerUEOT,
    PumpTargetArtifactOrCreatureUntilEOT,
    PumpTargetCreatureUntilEOT,
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    SetBasePTConditionalUntilEOT,
    SetBasePTUntilEOT,
    SwitchSourcePowerToughnessUEOT,
    ThreatenTargetCreatureUEOT,
    _signed,
)

from mtg_bot.effects.generic.counters import (
    MovePlusOneCounterBetweenPermanentsYouControl,
    MoveSelfCountersToTargetCreatureYouControl,
    PutChargeCountersOnSelf,
    PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    PutChargeCountersOnTargetSpacecraftYouControl,
    PutLoyaltyCounterOnSelf,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    PutPlusOneCounterOnOpponentsCreature,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnTargetCreature,
    PutPlusOneCounters,
    PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    PutPoisonCountersOnTargetPlayer,
    PutStunCounterOnTappedCreature,
)

from mtg_bot.effects.generic.destroy import (
    Destroy,
    DestroyAllCreatures,
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    DestroyEnchantedPermanent,
    DestroyTargetArtifact,
    DestroyTargetArtifactEnchantmentOrFlyingCreature,
    DestroyTargetArtifactOrTappedCreature,
    DestroyTargetCreature,
    DestroyTargetLand,
    DestroyTargetNoncreaturePermanent,
    DestroyTargetNonlandPermanent,
    DestroyTargetNonlandPermanentWithLanderForController,
    DestroyUpToOneTargetNonlandPermanent,
    RegenerateTargetCreature,
)

from mtg_bot.effects.generic.tap import (
    IfGainedLifeThisTurnUntapSelf,
    PhaseOutEquippedCreature,
    Tap,
    TapAndStunUpToOneTargetCreature,
    TapAnotherTargetCreature,
    TapEnchantedPermanent,
    TapTargetArtifactOrCreature,
    TapTargetOpponentPermanentAndStunIt,
    TapUpToOneTargetCreature,
    Untap,
    UntapTargetLand,
    UntapTargetOtherPermanent,
)

from mtg_bot.effects.generic.exile import (
    CreateNTokensFromLastExileRecall,
    Exile,
    ExileAllArtifactsWithManaValueAtMost,
    ExileAllCreaturesAndSpacecraft,
    ExileAllGraveyards,
    ExileAllMatchingUntilSourceLeaves,
    ExileEachOpponentsGraveyard,
    ExileOpponentsNonlandPermanentUntilLeaves,
    ExileTargetAttackingCreatureUntilEndStep,
    ExileTargetCardFromGraveyard,
    ExileTargetCreature,
    ExileTargetCreatureUntilSourceLeaves,
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    ExileTopOfLibraryMayPlayThisTurn,
    ExileTopXOfLibraryMayPlayThisTurn,
    MoveEachExiledWithSourceToOwnersGraveyard,
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    ReanimateOneExiledWithSourceWithCounters,
    ReturnExiledPermanentToOwnerTapped,
    SacrificeSelf,
    SacrificeSelfPreservingExileLink,
    WarpExileSelf,
)

from mtg_bot.effects.generic.bounce import (
    Bounce,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
    ReturnTargetCreatureToOwnersHand,
    ReturnTargetLandFromGraveyardToHand,
    ReturnTargetPermanentYouControlToOwnersHand,
    ReturnUpToNCreaturesFromYourGraveyardToHand,
    ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
    ReturnUpToNTargetCreaturesToOwnersHands,
)

from mtg_bot.effects.generic.delayed_actions import (
    RemoveChargeCountersFromSourceDelayed,
    SacrificeSourceDelayed,
    ScheduleSelfSacAtNextEndStep,
)

from mtg_bot.effects.generic.tokens import (
    CreateLanderAndScheduleSacrifice,
    CreateToken,
    CreateTokenAndAttachSelf,
    CreateTokenCopyOfTargetCreatureYouControl,
    CreateTokenPerMulticoloredPermanent,
    CreateXTokensOfTargetPermanentWithHasteEndStepSac,
)

from mtg_bot.effects.generic.mana import (
    AddChargeCounterManaOfChosenColor,
    AddManaToPool,
    AddNManaOfChosenColor,
    AddOneManaFromControlledLandsProductions,
    AddOneManaOfChosenPermanentColor,
)

from mtg_bot.effects.generic.search import (
    SearchLibraryForBasicLandTapped,
    SearchLibraryForCard,
    SearchLibraryForEquipmentToBattlefield,
    SearchLibraryForGreenCreatureWithMVAtMostX,
)

from mtg_bot.effects.generic.library_lookat import (
    LookAtTopNRevealOrCounter,
    LookAtTopTwoSplitHandGraveyard,
    LookTopNPutOneInHandRestToGraveyard,
    ManifestDread,
    ManifestDreadThenAttachSelf,
    ManifestDreadThenPutPlusOneCountersOnIt,
    PeekTopMayBattlefieldIfLandElseHand,
    Scry,
    SelfMill,
    Surveil,
)

from mtg_bot.effects.generic.life import (
    DefendingPlayerLosesHalfLifeRoundedUp,
    EachOpponentDiscardsOrLosesLife,
    EachOpponentLosesLife,
    GainLife,
    GrantLifeToEachOpponent,
    LoseLife,
    SetLifeToHalfStartingRoundedUp,
    TargetOpponentLosesLife,
    TargetOpponentLosesNYouGainN,
    TargetPlayerLosesLife,
)

from mtg_bot.effects.generic.discard import (
    DiscardHandThenDrawN,
    DiscardSelf,
    EachOpponentDiscards,
    EachOpponentExilesCardFromHandWithCastPermission,
    TargetOpponentDiscards,
    TargetOpponentDiscardsCasterChoice,
    TargetOpponentLookHandMayDiscard,
)

from mtg_bot.effects.generic.draw_mill import (
    DrawCardPerMulticoloredPermanent,
    DrawCards,
    DrawCardsByConditionMultiplier,
    DrawCardsEqualToResolvingCombatDamage,
    DrawCardsEqualToResolvingCounterAmount,
    EachOpponentMillsCards,
    EachPlayerDraws,
    MillTargetPlayer,
)

from mtg_bot.effects.generic.become_type import (
    BecomeLandCreatureUEOT,
    BecomeType,
    BecomesCopyOfTargetLand,
    TargetArtifactBecomesCreatureUEOT,
)

from mtg_bot.effects.generic.attach import (
    AttachToTargetCreatureYouControl,
    EquipToTargetCreatureYouControl,
)

from mtg_bot.effects.generic.graveyard import (
    PutCardFromGraveyardOnBottomOfLibrary,
    ReanimateTargetCreatureCardFromDefendersGraveyard,
    ReturnAllCreaturesFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnFromGraveyard,
)

from mtg_bot.effects.generic.zone_moves import (
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
    PutBasicLandFromHandOntoBattlefieldTapped,
    SacrificeNLandsYouControl,
    ShuffleZonesIntoLibrary,
)

from mtg_bot.effects.generic.control import (
    ChangeControllerToCombatDamageSource,
    ControlTargetOpponentNextTurn,
    GainControlOfTargetSliverPermanently,
)

from mtg_bot.effects.generic.stack_control import (
    CopyTargetInstantOrSorceryYouControl,
    CounterTargetSpell,
    PreventAllCombatDamageThisTurn,
    TakeExtraTurnAfterThisOne,
)

from mtg_bot.effects.generic.opponent_punishers import (
    EachOpponentExilesOwnCreature,
    EachOpponentSacrificesCreature,
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
    TargetOpponentSacrificesCreatureOtherThanEnchanted,
)

from mtg_bot.effects.generic.text_change import (
    MagicalHackTextChangeEffect,
    SleightOfMindTextChangeEffect,
)

from mtg_bot.effects.generic.misc import (
    CytoshapeBecomeCopyUEOT,
    LockOrUnlockDoorOfTargetRoomYouControl,
    ScuttlemuttColorChangeUEOT,
)

__all__ = [
    # targets_helpers (private but historically importable for tests)
    "_bounce_to_hand",
    "_describe_filter",
    "_describe_targets",
    "_eff_subtypes",
    "_fizzle_message",
    "_slot_target_still_legal",
    "_signed",
    # damage
    "DealDamage",
    "DealDamageAnyTarget",
    "DealDamageEachOpponent",
    "DealDamageEqualToSourcePowerAnyTarget",
    "DealDamageToControllerAndAddMana",
    "DealDamageToOpponentCreature",
    "DealDamageToOpponentCreatureByArtifactCount",
    "DealDamageToOpponentCreatureByCardsInHand",
    "DealDamageToTargetCreature",
    "DealDamageToTargetCreatureSpacecraftBoosted",
    "DealDamageToTargetCreatureWithExcessLanderRider",
    "DealDamageToTargetOpponent",
    "DealDamageToTargetTappedCreature",
    "DealNDamageToEachCreature",
    "DrawCardsAndLoseLifeEqualToResolvingDamage",
    "MayHaveSourceDealDamageToTarget",
    # grant_keywords
    "GrantActivatedAbility",
    "GrantKeywords",
    "GrantTriggeredAbility",
    "GrantTriggeredAbilityUEOT",
    "GrantUnblockable",
    "GrantUnblockableUEOT",
    # pump
    "DoubleTargetCreaturesPowerUEOT",
    "PairedTargetPumpDebuffUEOT",
    "Pump",
    "PumpCreaturesOpponentsControlUntilEOT",
    "PumpCreaturesYouControlUntilEOT",
    "PumpSelfUntilEOT",
    "PumpSelfXPowerUEOT",
    "PumpTargetArtifactOrCreatureUntilEOT",
    "PumpTargetCreatureUntilEOT",
    "PumpTargetOtherCreatureByXOverXWhereXIsSourcePower",
    "SetBasePTConditionalUntilEOT",
    "SetBasePTUntilEOT",
    "SwitchSourcePowerToughnessUEOT",
    "ThreatenTargetCreatureUEOT",
    # counters
    "MovePlusOneCounterBetweenPermanentsYouControl",
    "MoveSelfCountersToTargetCreatureYouControl",
    "PutChargeCountersOnSelf",
    "PutChargeCountersOnTargetSpacecraftOrPlanetYouControl",
    "PutChargeCountersOnTargetSpacecraftYouControl",
    "PutLoyaltyCounterOnSelf",
    "PutPlusOneCounterOnCreatureYouControl",
    "PutPlusOneCounterOnEachCreatureYouControl",
    "PutPlusOneCounterOnEachOfUpToNTargetCreatures",
    "PutPlusOneCounterOnOpponentsCreature",
    "PutPlusOneCounterOnSelf",
    "PutPlusOneCounterOnTargetCreature",
    "PutPlusOneCounters",
    "PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl",
    "PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower",
    "PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact",
    "PutPoisonCountersOnTargetPlayer",
    "PutStunCounterOnTappedCreature",
    # destroy
    "Destroy",
    "DestroyAllCreatures",
    "DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters",
    "DestroyEnchantedPermanent",
    "DestroyTargetArtifact",
    "DestroyTargetArtifactEnchantmentOrFlyingCreature",
    "DestroyTargetArtifactOrTappedCreature",
    "DestroyTargetCreature",
    "DestroyTargetLand",
    "DestroyTargetNoncreaturePermanent",
    "DestroyTargetNonlandPermanent",
    "DestroyTargetNonlandPermanentWithLanderForController",
    "DestroyUpToOneTargetNonlandPermanent",
    "RegenerateTargetCreature",
    # tap
    "IfGainedLifeThisTurnUntapSelf",
    "PhaseOutEquippedCreature",
    "Tap",
    "TapAndStunUpToOneTargetCreature",
    "TapAnotherTargetCreature",
    "TapEnchantedPermanent",
    "TapTargetArtifactOrCreature",
    "TapTargetOpponentPermanentAndStunIt",
    "TapUpToOneTargetCreature",
    "Untap",
    "UntapTargetLand",
    "UntapTargetOtherPermanent",
    # exile
    "CreateNTokensFromLastExileRecall",
    "Exile",
    "ExileAllArtifactsWithManaValueAtMost",
    "ExileAllCreaturesAndSpacecraft",
    "ExileAllGraveyards",
    "ExileAllMatchingUntilSourceLeaves",
    "ExileEachOpponentsGraveyard",
    "ExileOpponentsNonlandPermanentUntilLeaves",
    "ExileTargetAttackingCreatureUntilEndStep",
    "ExileTargetCardFromGraveyard",
    "ExileTargetCreature",
    "ExileTargetCreatureUntilSourceLeaves",
    "ExileTargetCreatureWithPowerOrToughnessAtMost",
    "ExileTopOfLibraryMayPlayThisTurn",
    "ExileTopXOfLibraryMayPlayThisTurn",
    "MoveEachExiledWithSourceToOwnersGraveyard",
    "PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl",
    "ReanimateOneExiledWithSourceWithCounters",
    "ReturnExiledPermanentToOwnerTapped",
    "SacrificeSelf",
    "SacrificeSelfPreservingExileLink",
    "WarpExileSelf",
    # bounce / return-to-hand
    "Bounce",
    "ReturnCreatureFromYourGraveyardToHand",
    "ReturnTargetArtifactCardFromYourGraveyardToHand",
    "ReturnTargetCreatureToOwnersHand",
    "ReturnTargetLandFromGraveyardToHand",
    "ReturnTargetPermanentYouControlToOwnersHand",
    "ReturnUpToNCreaturesFromYourGraveyardToHand",
    "ReturnUpToNNonlandPermanentCardsFromGraveyardToHand",
    "ReturnUpToNSmallCreaturesFromGraveyardWithCounters",
    "ReturnUpToNTargetCreaturesToOwnersHands",
    # delayed_actions
    "RemoveChargeCountersFromSourceDelayed",
    "SacrificeSourceDelayed",
    "ScheduleSelfSacAtNextEndStep",
    # tokens
    "CreateLanderAndScheduleSacrifice",
    "CreateToken",
    "CreateTokenAndAttachSelf",
    "CreateTokenCopyOfTargetCreatureYouControl",
    "CreateTokenPerMulticoloredPermanent",
    "CreateXTokensOfTargetPermanentWithHasteEndStepSac",
    # mana
    "AddChargeCounterManaOfChosenColor",
    "AddManaToPool",
    "AddNManaOfChosenColor",
    "AddOneManaFromControlledLandsProductions",
    "AddOneManaOfChosenPermanentColor",
    # search
    "SearchLibraryForBasicLandTapped",
    "SearchLibraryForCard",
    "SearchLibraryForEquipmentToBattlefield",
    "SearchLibraryForGreenCreatureWithMVAtMostX",
    # library_lookat
    "LookAtTopNRevealOrCounter",
    "LookAtTopTwoSplitHandGraveyard",
    "LookTopNPutOneInHandRestToGraveyard",
    "ManifestDread",
    "ManifestDreadThenAttachSelf",
    "ManifestDreadThenPutPlusOneCountersOnIt",
    "PeekTopMayBattlefieldIfLandElseHand",
    "Scry",
    "SelfMill",
    "Surveil",
    # life
    "DefendingPlayerLosesHalfLifeRoundedUp",
    "EachOpponentDiscardsOrLosesLife",
    "EachOpponentLosesLife",
    "GainLife",
    "GrantLifeToEachOpponent",
    "LoseLife",
    "SetLifeToHalfStartingRoundedUp",
    "TargetOpponentLosesLife",
    "TargetOpponentLosesNYouGainN",
    "TargetPlayerLosesLife",
    # discard
    "DiscardHandThenDrawN",
    "DiscardSelf",
    "EachOpponentDiscards",
    "EachOpponentExilesCardFromHandWithCastPermission",
    "TargetOpponentDiscards",
    "TargetOpponentDiscardsCasterChoice",
    "TargetOpponentLookHandMayDiscard",
    # draw_mill
    "DrawCardPerMulticoloredPermanent",
    "DrawCards",
    "DrawCardsByConditionMultiplier",
    "DrawCardsEqualToResolvingCombatDamage",
    "DrawCardsEqualToResolvingCounterAmount",
    "EachOpponentMillsCards",
    "EachPlayerDraws",
    "MillTargetPlayer",
    # become_type
    "BecomeLandCreatureUEOT",
    "BecomeType",
    "BecomesCopyOfTargetLand",
    "TargetArtifactBecomesCreatureUEOT",
    # attach
    "AttachToTargetCreatureYouControl",
    "EquipToTargetCreatureYouControl",
    # graveyard
    "PutCardFromGraveyardOnBottomOfLibrary",
    "ReanimateTargetCreatureCardFromDefendersGraveyard",
    "ReturnAllCreaturesFromYourGraveyardToBattlefield",
    "ReturnCreatureFromYourGraveyardToBattlefield",
    "ReturnFromGraveyard",
    # zone_moves
    "OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary",
    "OwnerPutsTargetWarpedExileCardOnBottomOfLibrary",
    "PutBasicLandFromHandOntoBattlefieldTapped",
    "SacrificeNLandsYouControl",
    "ShuffleZonesIntoLibrary",
    # control
    "ChangeControllerToCombatDamageSource",
    "ControlTargetOpponentNextTurn",
    "GainControlOfTargetSliverPermanently",
    # stack_control
    "CopyTargetInstantOrSorceryYouControl",
    "CounterTargetSpell",
    "PreventAllCombatDamageThisTurn",
    "TakeExtraTurnAfterThisOne",
    # opponent_punishers
    "EachOpponentExilesOwnCreature",
    "EachOpponentSacrificesCreature",
    "EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage",
    "TargetOpponentSacrificesCreatureOtherThanEnchanted",
    # text_change
    "MagicalHackTextChangeEffect",
    "SleightOfMindTextChangeEffect",
    # misc
    "CytoshapeBecomeCopyUEOT",
    "LockOrUnlockDoorOfTargetRoomYouControl",
    "ScuttlemuttColorChangeUEOT",
]
