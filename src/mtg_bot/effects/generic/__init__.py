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



@dataclass(frozen=True)
class CytoshapeBecomeCopyUEOT(Effect):
    """Cytoshape (Saviors of Kamigawa, simplified): "Until end of
    turn, target creature becomes a copy of another target
    creature." Layer 1 copy effect with ``expires_at="cleanup"``.

    The architectural payoff over Clone (which is permanent /
    ``expires_at=None``): the printing mutation must REVERT at
    cleanup. Wired via the new ``revert_printing_if_no_layer1_copies``
    helper called from ``run_cleanup_step`` after layer-1 entries
    expire.

    Demo simplifications:
    - Drops the real card's "Sacrifice a Spirit" cost.
    - Drops the "except it isn't a Spirit" rider on the resulting
      copy.
    - Activate-as-sorcery is moot because we ship as a sorcery
      directly.

    Two creature targets: slot 0 is the creature being changed;
    slot 1 is the source whose printing is copied. The two must
    differ ("another target creature") — fizzles if same.
    """

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (2, 2)

    def target_slot_kinds(self) -> tuple[str, ...]:
        return ("creature", "creature")

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if len(targets) < 2:
            return
        first_id = targets[0][1]
        second_id = targets[1][1]
        if first_id == second_id:
            state.log.append(
                "Cytoshape fizzles: targets must be different creatures"
            )
            return
        first = next(
            (o for o in state.battlefield if o.id == first_id), None,
        )
        second = next(
            (o for o in state.battlefield if o.id == second_id), None,
        )
        if first is None or second is None:
            return
        if first.original_printing is None:
            first.original_printing = first.printing
        copied_printing = second.printing
        first.printing = copied_printing
        src = state.resolving_source
        source_id = src.id if src is not None else first.id
        state.add_continuous_effect(
            source_id=source_id,
            layer=1,
            kind="is_copy",
            target_id=first.id,
            params=(copied_printing,),
            expires_at="cleanup",
            description=(
                f"{first.original_printing.name} becomes a copy of "
                f"{copied_printing.name} UEOT"
            ),
        )
        state.log.append(
            f"{first.original_printing.name} becomes a copy of "
            f"{copied_printing.name} until end of turn"
        )

    def describe(self) -> str:
        return (
            "until end of turn, target creature becomes a copy of "
            "another target creature"
        )



@dataclass(frozen=True)
class ScuttlemuttColorChangeUEOT(Effect):
    """Scuttlemutt: '{T}: Target creature becomes the color or colors
    of your choice until end of turn.' Layer 5 color-changing effect.

    Demo scope: picks exactly one color via ``choose_mana_color``.
    Real Scuttlemutt allows zero, one, or multiple colors; the demo
    keeps it to a single color since that's enough to exercise
    block legality with protection-from-color.

    Resolution writes a layer-5 ``"set_colors"`` registry entry
    sourced by Scuttlemutt with ``params=(frozenset({chosen}),)``
    and ``expires_at="cleanup"``. The entry REPLACES the target's
    color set (matching real-card "becomes" semantics, not
    "becomes ... in addition to"). At cleanup the entry is dropped
    via ``expire_continuous_effects("cleanup")`` and the target
    reverts to its printed colors.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        _, target_id = targets[0]
        target = next(
            (o for o in state.battlefield if o.id == target_id), None,
        )
        if target is None:
            return
        chosen = state.players[controller_id].agent.choose_mana_color(
            state, controller_id, ["W", "U", "B", "R", "G"],
        )
        if chosen not in ("W", "U", "B", "R", "G"):
            return
        src = state.resolving_source
        source_id = src.id if src is not None else target.id
        state.add_continuous_effect(
            source_id=source_id,
            layer=5,
            kind="set_colors",
            target_id=target.id,
            params=(frozenset({chosen}),),
            expires_at="cleanup",
            description=(
                f"{target.printing.name} becomes {chosen} until end "
                f"of turn"
            ),
        )
        state.log.append(
            f"{target.printing.name} becomes {chosen} until end of turn"
        )

    def describe(self) -> str:
        return (
            "target creature becomes the color of your choice until "
            "end of turn"
        )



@dataclass(frozen=True)
class LockOrUnlockDoorOfTargetRoomYouControl(Effect):
    """Keys to the House: "Lock or unlock a door of target Room you
    control. Activate only as a sorcery."

    Resolves on a target Room permanent the controller controls. The
    controller chooses one of the Room's two doors to toggle (via
    ``choose_target`` over the legal-target pool — Rooms — and then
    ``choose_mode`` over a per-Room ``["lock <X>", "unlock <X>", ...]``
    label list). The chosen half flips its membership in
    ``GameObject.unlocked_halves``: a locked half being unlocked is
    added to the set; an unlocked half being locked is removed.

    The ``Activate only as a sorcery.`` rider is honored at the
    activated-ability level (``sorcery_speed=True``), not in the
    effect; the effect itself is happy to resolve at any point.

    Unlike the printed ``UnlockRoomHalf`` action (sorcery-speed special
    action that pays the half's mana cost), this effect skips the cost
    payment — the controller's "Keys" sacrifice already paid for the
    privilege. The unlock side-effects (Eerie observers, etc.) follow
    the same path the action takes: the predicate-style ENTERS event
    on a half-name filter does NOT re-fire here because the engine
    layer's ``_unlock_room_half_with_triggers`` is the canonical entry
    point. We mirror its observable state change (modify
    ``unlocked_halves``) without re-firing the per-half on-unlock
    triggered abilities — keeps the effect surgical.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.controller_id == controller_id
            and o.printing.is_room
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or obj.controller_id != controller_id:
            return
        if not obj.printing.is_room:
            return
        # Build the choose_mode label list: one entry per door, each
        # pre-prefixed with "lock" or "unlock" depending on the door's
        # current state. The controller's pick maps directly to the
        # door name and the new state.
        labels: list[str] = []
        actions: list[tuple[str, str]] = []  # (door_name, "lock"/"unlock")
        for half in obj.printing.room_halves:
            if half.name in obj.unlocked_halves:
                labels.append(f"lock {half.name}")
                actions.append((half.name, "lock"))
            else:
                labels.append(f"unlock {half.name}")
                actions.append((half.name, "unlock"))
        if not labels:
            return
        p = state.player_by_id(controller_id)
        pick = 0
        if p.agent is not None:
            pick = p.agent.choose_mode(state, controller_id, labels)
            pick = max(0, min(pick, len(labels) - 1))
        door_name, op = actions[pick]
        if op == "unlock":
            obj.unlocked_halves = obj.unlocked_halves | {door_name}
            state.log.append(
                f"P{controller_id} unlocks {door_name} on "
                f"{obj.printing.name}"
            )
        else:
            obj.unlocked_halves = obj.unlocked_halves - {door_name}
            state.log.append(
                f"P{controller_id} locks {door_name} on "
                f"{obj.printing.name}"
            )

    def describe(self) -> str:
        return "lock or unlock a door of target Room you control"



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
