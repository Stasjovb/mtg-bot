# Rust-port parity discovery — empirical measurements

Gathered by `scripts/parity_discovery_*.py` (re-runnable). Three datasets follow:
1. Effect-class vocabulary across all loaded card pools (Dataset 1).
2. Action-class distribution in one self-played RandomAgent vs RandomAgent game (Dataset 2).
3. RNG and ordering-seam audit of the Python engine (Dataset 3).

---

## Dataset 1 — Effect vocabulary

- **Raw EoE Scryfall entries**: 266
- **Total printings claimed by parser** (across all loaded pools — eoe + stellar_sights + special_guests_eoe + duskmourn): 475
- **Failures during effect walk**: 0

### Cardinality
- **Total distinct Effect class names**: 228
- Classes appearing >= 10 times: **14**
- Classes appearing in exactly 1 card: **161**
- Generic effects: **170**, Bespoke effects: **37**, Other (combinators/ability dataclasses/conditions/etc.): **21**

### Generic effects (mtg_bot.effects.generic.*)

| Class | Count | Example card |
|---|---:|---|
| `DrawCards` | 45 | Alpharael, Dreaming Acolyte |
| `CreateToken` | 41 | Beamsaw Prospector |
| `AddManaToPool` | 33 | All-Fates Scroll |
| `PumpTargetCreatureUntilEOT` | 26 | Blinkmoth Nexus |
| `GainLife` | 23 | Cautious Survivor |
| `PutPlusOneCounterOnSelf` | 16 | Blade of the Swarm |
| `Surveil` | 16 | Appendage Amalgam |
| `SearchLibraryForBasicLandTapped` | 15 | Beamsaw Prospector |
| `EquipToTargetCreatureYouControl` | 14 | Atomic Microsizer |
| `BecomeLandCreatureUEOT` | 13 | Blinkmoth Nexus |
| `PumpSelfUntilEOT` | 12 | Attack-in-the-Box |
| `ManifestDread` | 10 | Bashful Beastie |
| `DestroyTargetCreature` | 9 | Come Back Wrong |
| `SearchLibraryForCard` | 9 | Demonic Counsel |
| `DealDamageToTargetCreature` | 8 | Bear Trap |
| `DiscardSelf` | 8 | Irreverent Gremlin |
| `ReturnCreatureFromYourGraveyardToBattlefield` | 8 | Emerge from the Cocoon |
| `CounterTargetSpell` | 7 | Annul |
| `DealDamageAnyTarget` | 7 | Debris Field Crusher |
| `LoseLife` | 7 | Decode Transmissions |
| `PutPlusOneCounterOnTargetCreature` | 7 | Drix Fatemaker |
| `EachOpponentLosesLife` | 6 | Balemurk Leech |
| `PumpCreaturesYouControlUntilEOT` | 6 | Contested War Zone |
| `AttachToTargetCreatureYouControl` | 5 | Baseball Bat |
| `AddNManaOfChosenColor` | 4 | Grove of the Burnwillows |
| `DealDamageEachOpponent` | 4 | Glassworks // Shattered Yard |
| `DestroyEnchantedPermanent` | 4 | Cracked Skull |
| `ExileOpponentsNonlandPermanentUntilLeaves` | 4 | Banishing Light |
| `DealNDamageToEachCreature` | 3 | Extinguisher Battleship |
| `DestroyAllCreatures` | 3 | Restricted Office // Lecture Hall |
| `ExileTargetCreature` | 3 | Archenemy's Charm |
| `ExileTargetCreatureUntilSourceLeaves` | 3 | All-Fates Stalker |
| `GrantUnblockableUEOT` | 3 | Clammy Prowler |
| `ManifestDreadThenAttachSelf` | 3 | Conductive Machete |
| `PutPlusOneCounterOnCreatureYouControl` | 3 | Haliya, Ascendant Cadet |
| `PutPlusOneCounterOnEachCreatureYouControl` | 3 | Atmospheric Greenhouse |
| `ReturnCreatureFromYourGraveyardToHand` | 3 | Fell Gravship |
| `ReturnTargetCreatureToOwnersHand` | 3 | Bottomless Pool // Locker Room |
| `SelfMill` | 3 | Fell Gravship |
| `CreateTokenCopyOfTargetCreatureYouControl` | 2 | Mirror Room // Fractured Realm |
| `DealDamageEqualToSourcePowerAnyTarget` | 2 | Infernal Phantom |
| `DealDamageToOpponentCreature` | 2 | Glassworks // Shattered Yard |
| `DestroyTargetArtifact` | 2 | Drill Too Deep |
| `DestroyTargetLand` | 2 | Dust Bowl |
| `DestroyTargetNonlandPermanent` | 2 | Drag to the Roots |
| `DrawCardsEqualToResolvingCombatDamage` | 2 | Fear of Failed Tests |
| `EachOpponentDiscards` | 2 | Let's Play a Game |
| `LookAtTopNRevealOrCounter` | 2 | Living Phone |
| `ManifestDreadThenPutPlusOneCountersOnIt` | 2 | Moldering Gym // Weight Room |
| `MillTargetPlayer` | 2 | Scrabbling Skullcrab |
| `MoveSelfCountersToTargetCreatureYouControl` | 2 | Broodguard Elite |
| `OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary` | 2 | Lost in Space |
| `PumpCreaturesOpponentsControlUntilEOT` | 2 | Let's Play a Game |
| `PutCardFromGraveyardOnBottomOfLibrary` | 2 | Chrome Companion |
| `PutChargeCountersOnSelf` | 2 | Blast Zone |
| `PutPlusOneCounterOnEachOfUpToNTargetCreatures` | 2 | Grand Entryway // Elegant Rotunda |
| `TapEnchantedPermanent` | 2 | Stay Hidden, Stay Silent |
| `TapTargetArtifactOrCreature` | 2 | Mental Modulation |
| `TargetOpponentLosesLife` | 2 | Dubious Delicacy |
| `AddChargeCounterManaOfChosenColor` | 1 | The Eternity Elevator |
| `AddOneManaFromControlledLandsProductions` | 1 | Reflecting Pool |
| `AddOneManaOfChosenPermanentColor` | 1 | Meteor Crater |
| `BecomeType` | 1 | Haunted Screen |
| `BecomesCopyOfTargetLand` | 1 | Thespian's Stage |
| `ChangeControllerToCombatDamageSource` | 1 | Contested War Zone |
| `CopyTargetInstantOrSorceryYouControl` | 1 | Mirrorpool |
| `CreateLanderAndScheduleSacrifice` | 1 | Kav Landseeker |
| `CreateNTokensFromLastExileRecall` | 1 | Pinnacle Starcage |
| `CreateTokenAndAttachSelf` | 1 | Auxiliary Boosters |
| `CreateTokenPerMulticoloredPermanent` | 1 | Infinite Guideline Station |
| `CreateXTokensOfTargetPermanentWithHasteEndStepSac` | 1 | Devastating Onslaught |
| `DealDamageToControllerAndAddMana` | 1 | Ancient Tomb |
| `DealDamageToOpponentCreatureByArtifactCount` | 1 | Warmaker Gunship |
| `DealDamageToOpponentCreatureByCardsInHand` | 1 | Roaring Furnace // Steaming Sauna |
| `DealDamageToTargetCreatureSpacecraftBoosted` | 1 | Invasive Maneuvers |
| `DealDamageToTargetCreatureWithExcessLanderRider` | 1 | Orbital Plunge |
| `DealDamageToTargetOpponent` | 1 | Biotech Specialist |
| `DealDamageToTargetTappedCreature` | 1 | Reroute Systems |
| `DefendingPlayerLosesHalfLifeRoundedUp` | 1 | Alpharael, Stonechosen |
| `DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters` | 1 | Blast Zone |
| `DestroyTargetArtifactEnchantmentOrFlyingCreature` | 1 | Shattered Wings |
| `DestroyTargetArtifactOrTappedCreature` | 1 | Radiant Strike |
| `DestroyTargetNoncreaturePermanent` | 1 | Extinguisher Battleship |
| `DestroyTargetNonlandPermanentWithLanderForController` | 1 | Emergency Eject |
| `DestroyUpToOneTargetNonlandPermanent` | 1 | Syr Vondam, Sunstar Exemplar |
| `DiscardHandThenDrawN` | 1 | Vaultguard Trooper |
| `DoubleTargetCreaturesPowerUEOT` | 1 | Mightform Harmonizer |
| `DrawCardPerMulticoloredPermanent` | 1 | Infinite Guideline Station |
| `DrawCardsAndLoseLifeEqualToResolvingDamage` | 1 | Requiem Monolith |
| `DrawCardsByConditionMultiplier` | 1 | All-Fates Scroll |
| `DrawCardsEqualToResolvingCounterAmount` | 1 | Terrasymbiosis |
| `EachOpponentDiscardsOrLosesLife` | 1 | Entropic Battlecruiser |
| `EachOpponentExilesCardFromHandWithCastPermission` | 1 | Lightstall Inquisitor |
| `EachOpponentExilesOwnCreature` | 1 | Sothera, the Supervoid |
| `EachOpponentMillsCards` | 1 | Specimen Freighter |
| `EachOpponentSacrificesCreature` | 1 | Susurian Dirgecraft |
| `EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage` | 1 | Osseous Sticktwister |
| `EachPlayerDraws` | 1 | Friendly Teddy |
| `ExileAllArtifactsWithManaValueAtMost` | 1 | Ruinous Rampage |
| `ExileAllCreaturesAndSpacecraft` | 1 | Beyond the Quiet |
| `ExileAllGraveyards` | 1 | Scavenger Grounds |
| `ExileAllMatchingUntilSourceLeaves` | 1 | Pinnacle Starcage |
| `ExileEachOpponentsGraveyard` | 1 | Dauntless Scrapbot |
| `ExileTargetAttackingCreatureUntilEndStep` | 1 | Mystifying Maze |
| `ExileTargetCardFromGraveyard` | 1 | Ghost Vacuum |
| `ExileTargetCreatureWithPowerOrToughnessAtMost` | 1 | Warping Wail |
| `ExileTopOfLibraryMayPlayThisTurn` | 1 | Charred Foyer // Warped Space |
| `ExileTopXOfLibraryMayPlayThisTurn` | 1 | Memorial Vault |
| `GainControlOfTargetSliverPermanently` | 1 | Sliver Overlord |
| `GrantLifeToEachOpponent` | 1 | Grove of the Burnwillows |
| `GrantTriggeredAbilityUEOT` | 1 | Requiem Monolith |
| `IfGainedLifeThisTurnUntapSelf` | 1 | Ragost, Deft Gastronaut |
| `LockOrUnlockDoorOfTargetRoomYouControl` | 1 | Keys to the House |
| `LookAtTopTwoSplitHandGraveyard` | 1 | Codecracker Hound |
| `LookTopNPutOneInHandRestToGraveyard` | 1 | Commune with Evil |
| `MayHaveSourceDealDamageToTarget` | 1 | Requiem Monolith |
| `MoveEachExiledWithSourceToOwnersGraveyard` | 1 | Pinnacle Starcage |
| `MovePlusOneCounterBetweenPermanentsYouControl` | 1 | Nesting Grounds |
| `OwnerPutsTargetWarpedExileCardOnBottomOfLibrary` | 1 | Blade of the Swarm |
| `PairedTargetPumpDebuffUEOT` | 1 | Monoist Circuit-Feeder |
| `PeekTopMayBattlefieldIfLandElseHand` | 1 | Wickerfolk Thresher |
| `PhaseOutEquippedCreature` | 1 | Robe of Stars |
| `PreventAllCombatDamageThisTurn` | 1 | Darkness |
| `PumpSelfXPowerUEOT` | 1 | Lavaclaw Reaches |
| `PumpTargetArtifactOrCreatureUntilEOT` | 1 | Reroute Systems |
| `PumpTargetOtherCreatureByXOverXWhereXIsSourcePower` | 1 | Hemosymbic Mite |
| `PutBasicLandFromHandOntoBattlefieldTapped` | 1 | Terrain Generator |
| `PutChargeCountersOnTargetSpacecraftOrPlanetYouControl` | 1 | Drill Too Deep |
| `PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl` | 1 | Ghost Vacuum |
| `PutLoyaltyCounterOnSelf` | 1 | Tezzeret, Cruel Captain |
| `PutPlusOneCounterOnOpponentsCreature` | 1 | Sunset Saboteur |
| `PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl` | 1 | Archenemy's Charm |
| `PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower` | 1 | Ouroboroid |
| `PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact` | 1 | Luxknight Breacher |
| `PutPoisonCountersOnTargetPlayer` | 1 | Virulent Silencer |
| `PutStunCounterOnTappedCreature` | 1 | Cryogen Relic |
| `ReanimateOneExiledWithSourceWithCounters` | 1 | Sothera, the Supervoid |
| `ReanimateTargetCreatureCardFromDefendersGraveyard` | 1 | Chorale of the Void |
| `RegenerateTargetCreature` | 1 | Swarmyard |
| `ReturnAllCreaturesFromYourGraveyardToBattlefield` | 1 | Funeral Room // Awakening Hall |
| `ReturnTargetArtifactCardFromYourGraveyardToHand` | 1 | Scour for Scrap |
| `ReturnTargetLandFromGraveyardToHand` | 1 | Petrified Field |
| `ReturnTargetPermanentYouControlToOwnersHand` | 1 | Exosuit Savior |
| `ReturnUpToNCreaturesFromYourGraveyardToHand` | 1 | Archenemy's Charm |
| `ReturnUpToNNonlandPermanentCardsFromGraveyardToHand` | 1 | Pull Through the Weft |
| `ReturnUpToNSmallCreaturesFromGraveyardWithCounters` | 1 | Scout for Survivors |
| `ReturnUpToNTargetCreaturesToOwnersHands` | 1 | Specimen Freighter |
| `SacrificeNLandsYouControl` | 1 | Lotus Field |
| `SacrificeSelf` | 1 | Pinnacle Starcage |
| `SacrificeSelfPreservingExileLink` | 1 | Sothera, the Supervoid |
| `ScheduleSelfSacAtNextEndStep` | 1 | Attack-in-the-Box |
| `SearchLibraryForEquipmentToBattlefield` | 1 | Honored Knight-Captain |
| `SearchLibraryForGreenCreatureWithMVAtMostX` | 1 | Green Sun's Zenith |
| `SetBasePTConditionalUntilEOT` | 1 | Genemorph Imago |
| `SetLifeToHalfStartingRoundedUp` | 1 | The Endstone |
| `ShuffleZonesIntoLibrary` | 1 | Weftwalking |
| `SwitchSourcePowerToughnessUEOT` | 1 | Wandering Fumarole |
| `TakeExtraTurnAfterThisOne` | 1 | Nexus of Fate |
| `TapAndStunUpToOneTargetCreature` | 1 | Meat Locker // Drowned Diner |
| `TapAnotherTargetCreature` | 1 | Starport Security |
| `TapTargetOpponentPermanentAndStunIt` | 1 | Mechanozoa |
| `TapUpToOneTargetCreature` | 1 | Baseball Bat |
| `TargetArtifactBecomesCreatureUEOT` | 1 | Synthesizer Labship |
| `TargetOpponentDiscardsCasterChoice` | 1 | Temporal Intervention |
| `TargetOpponentLookHandMayDiscard` | 1 | Cracked Skull |
| `TargetOpponentSacrificesCreatureOtherThanEnchanted` | 1 | Sporogenic Infection |
| `TargetPlayerLosesLife` | 1 | Entropic Battlecruiser |
| `ThreatenTargetCreatureUEOT` | 1 | Vengeful Possession |
| `UntapTargetLand` | 1 | Deserted Temple |
| `UntapTargetOtherPermanent` | 1 | Nanoform Sentinel |

### Bespoke effects (mtg_bot.effects.bespoke.*)

| Class | Count | Example card |
|---|---:|---|
| `AlpharaelDreamingAcolyteDiscardEffect` | 1 | Alpharael, Dreaming Acolyte |
| `AnticausalVestigeLeavesEffect` | 1 | Anticausal Vestige |
| `ArabellaAttackEffect` | 1 | Arabella, Abandoned Doll |
| `AstelliReclaimerETBEffect` | 1 | Astelli Reclaimer |
| `AtomicMicrosizerAttackEffect` | 1 | Atomic Microsizer |
| `BiosynthicBurstEffect` | 1 | Biosynthic Burst |
| `BoilerbilgesRipperETBEffect` | 1 | Boilerbilges Ripper |
| `CloseEncounterEffect` | 1 | Close Encounter |
| `ConsultTheStarChartsEffect` | 1 | Consult the Star Charts |
| `CoordinatedClobberingEffect` | 1 | Coordinated Clobbering |
| `CutPropulsionEffect` | 1 | Cut Propulsion |
| `DepressurizeEffect` | 1 | Depressurize |
| `DiplomaticRelationsEffect` | 1 | Diplomatic Relations |
| `DyadrineAttackEffect` | 1 | Dyadrine, Synthesis Amalgam |
| `EnchantedCreatureFightsTargetEffect` | 1 | Meltstrider's Resolve |
| `EnduringDiesReturnAsEnchantmentEffect` | 1 | Enduring Curiosity |
| `ExorciseEffect` | 1 | Exorcise |
| `FamishedWorldsireETBEffect` | 1 | Famished Worldsire |
| `FanaticOfTheHarrowingETBEffect` | 1 | Fanatic of the Harrowing |
| `FocusFireEffect` | 1 | Focus Fire |
| `HouseCartographerSurvivalEffect` | 1 | House Cartographer |
| `MutinousMassacreEffect` | 1 | Mutinous Massacre |
| `PainForAllDamageEchoEffect` | 1 | Pain for All |
| `PainForAllETBEffect` | 1 | Pain for All |
| `PerigeeBeckonerDiesReturnTappedEffect` | 1 | Perigee Beckoner |
| `PossibilityTechnicianETBEffect` | 1 | Possibility Technician |
| `RovingActuatorETBEffect` | 1 | Roving Actuator |
| `SawAttacksOptionalSacDrawEffect` | 1 | Saw |
| `SeedshipImpactEffect` | 1 | Seedship Impact |
| `SingularityRuptureEffect` | 1 | Singularity Rupture |
| `SurveyMechanActivationEffect` | 1 | Survey Mechan |
| `SystemsOverrideEffect` | 1 | Systems Override |
| `TannukEnsignLandfallEffect` | 1 | Tannuk, Memorial Ensign |
| `TerminalVelocityEffect` | 1 | Terminal Velocity |
| `TerrapactIntimidatorETBEffect` | 1 | Terrapact Intimidator |
| `TerritorialBruntarLandfallEffect` | 1 | Territorial Bruntar |
| `ZeroPointBalladEffect` | 1 | Zero Point Ballad |

### Other (combinators / ability dataclasses / conditions / etc.)

| Class | Count | Example card |
|---|---:|---|
| `Sequence` | 54 | Alpharael, Dreaming Acolyte |
| `ModalChooseOne` | 13 | Archenemy's Charm |
| `ConditionalOnTappedCreatures` | 6 | Dawnstrike Vanguard |
| `ConditionalIfVoid` | 4 | Decode Transmissions |
| `IfYouDo` | 4 | Attack-in-the-Box |
| `MayDo` | 4 | Attack-in-the-Box |
| `OptionalManaCostThenEffect` | 2 | Kavaron Harrier |
| `OptionalSacArtifactForEffect` | 2 | Lithobraking |
| `ConditionalIfCastFromHand` | 1 | Weftwalking |
| `ConditionalIfSourcePowerAtLeast` | 1 | Syr Vondam, Sunstar Exemplar |
| `ConditionalIfYouControlAtLeast` | 1 | Inventors' Fair |
| `ConditionalIfYouControlSubtype` | 1 | Unholy Annex // Ritual Chamber |
| `ConditionalIfYouGainedLifeAtLeast` | 1 | Haliya, Guided by Light |
| `IfNot` | 1 | Splitskin Doll |
| `OptionalPutCreatureFromHandOntoBattlefield` | 1 | Sledge-Class Seedship |
| `OptionalPutLandFromHandOntoBattlefield` | 1 | Burgeoning |
| `OptionalSacAnotherForEffect` | 1 | Swarm Culler |
| `OptionalSacAnotherForPumpSelfUEOT` | 1 | Comet Crawler |
| `OptionalSacLandOrLanderForBasicLandRamp` | 1 | Larval Scoutlander |
| `SacrificeSelfUnlessTapPermanent` | 1 | Command Bridge |
| `SacrificeSelfUnlessVoidActive` | 1 | Chorale of the Void |

---

## Dataset 2 — Action distribution in one self-played game

- **Seed**: 42
- **Deck setup**: synthetic mono-color G vs R via `simulate.simulate_game(colors=['G','R'])`
- **Agents**: two `RandomAgent`s
- **Turn cap**: 30
- **Total decisions** (agent-action returns + apply_action calls minus overlap): 420
- **Ended on turn**: 16
- **Outcome**: player 1 wins

### Action class frequency (apply_action + PassPriority decisions)

| Action class | Count | Sample repr |
|---|---:|---|
| `PassPriority` | 364 | `PassPriority()` |
| `CastSpell` | 17 | `CastSpell(card_id=16, use_warp=False, kicked=False, cast_for_free=False, use_...` |
| `DeclareAttackers` | 16 | `DeclareAttackers(attacker_ids=frozenset())` |
| `PlayLand` | 10 | `PlayLand(card_id=38)` |
| `ActivateAbility` | 8 | `ActivateAbility(source_id=16, ability_index=0)` |
| `DeclareBlockers` | 5 | `DeclareBlockers(assignments=())` |

---

## Dataset 3 — RNG and ordering seam audit

Audited engine files: `src/mtg_bot/{game,turn,simulate,actions,legal,combat,mulligan,engine,decks,serialize}.py` + `src/mtg_bot/effects/**/*.py` + `src/mtg_bot/cards/**/*.py`.

Caller-side files (`agents.py`, `recommend.py`, `replay.py`, `interactive.py`, `ui.py`, `search/`, `training/`, `cli/`, `training_ui/`) are NOT in scope — their RNG doesn't affect state-trajectory parity between the Python and Rust engines as long as both consume the same `(state, decision)` stream.

### 3.1 — RNG call sites in the engine

| File:line | Line |
|---|---|
| `src/mtg_bot/actions.py:1840` | `card = state.rng.choice(p.hand)` |
| `src/mtg_bot/effects/bespoke.py:1202` | `state.rng.shuffle(remaining)` |
| `src/mtg_bot/effects/bespoke.py:2718` | `state.rng.shuffle(revealed)` |
| `src/mtg_bot/effects/generic/library_lookat.py:136` | `state.rng.shuffle(remaining_examined)` |
| `src/mtg_bot/game.py:814` | `Always use this helper instead of calling ``state.rng.shuffle``` |
| `src/mtg_bot/game.py:820` | `state.rng.shuffle(p.library)` |
| `src/mtg_bot/game.py:3289` | `# ``random.Random()`` runs the C-level seed routine that draws` |
| `src/mtg_bot/simulate.py:130` | `state.rng.seed(seed)` |
| `src/mtg_bot/simulate.py:131` | `rng = random.Random(seed)` |
| `src/mtg_bot/simulate.py:138` | `rng.shuffle(p.library)` |
| `src/mtg_bot/simulate.py:166` | `rng.shuffle(p.library)` |
| `src/mtg_bot/simulate.py:472` | `rng = random.Random(seed)` |
| `src/mtg_bot/simulate.py:484` | `rng.shuffle(deck)` |
| `src/mtg_bot/simulate.py:540` | `rng = random.Random(seed)` |
| `src/mtg_bot/simulate.py:542` | `RandomAgent(rng=random.Random(rng.randint(0, 10**9)))` |
| `src/mtg_bot/simulate.py:554` | `rng = random.Random(seed)` |

**Seed source**: `simulate.setup_game(...)` calls `state.rng.seed(seed)` (simulate.py:130). Every in-game RNG draw flows through `state.rng` — the only setup-only local `rng = random.Random(seed)` (simulate.py:131, 472, 540, 554) is used for deck-shuffle and agent sub-seeds at game construction, not during play. Clone path (`game.py:3289-3294`) snapshots `state.rng.getstate()` via `Random.__new__` + `setstate` so two clones share an RNG history then diverge per-clone — important: a Rust port must match this same Mersenne-Twister stream for bit-identical parity, OR the parity gate compares trajectories where any RNG decision the Rust side makes differs deterministically. (Easier path: lift every RNG draw to a caller-supplied stream the test harness can replay, treating `state.rng` as a black-box oracle.)

### 3.2 — Order-sensitive iterations ("first match wins")

The engine iterates `state.battlefield` (a plain `list`, append-on-ETB), `p.hand`, `p.library`, `p.graveyard`, `p.exile` everywhere. Battlefield order = ETB order (move_off_battlefield removes, put_into_battlefield appends), so iteration order is **timestamp-by-ETB**. Sites where iteration order is observable in state mutation:

- `src/mtg_bot/legal.py:168` — legal_actions iterates p.hand and state.battlefield in zone-insertion order; the emitted CastSpell / ActivateAbility actions are ordered by that walk. Agents that pick the *first* legal in their search may be sensitive.
- `src/mtg_bot/legal.py:230 + 246-310` — Hand-zone PlayLand / CastSpell **dedup** is keyed on (printing.name, *modifier_tuple, **kwargs)** via _emit_hand_cast — two copies of the same card in hand collapse to one action. MAINTENANCE INVARIANT noted in source: if hand-zone per-object state is ever added, the dedup key must absorb it. Rust port must match this dedup or legal-action counts diverge.
- `src/mtg_bot/actions.py:3346` — dispatch_event snapshots `permanents = list(state.battlefield)` BEFORE walking, so triggers ETBing new permanents don't see them on the same dispatch pass. Order = battlefield iteration order.
- `src/mtg_bot/actions.py:3353-3399` — Trigger walk: `for source in permanents: for ability_index, ability in enumerate(source.printing.triggered_abilities)`. **No APNAP sort.** Push order = battlefield iteration order × ability index. Multiple simultaneous triggers land on the stack in that fixed order.
- `src/mtg_bot/turn.py:785-792` — `run_delayed_end_step_triggers` documents the stand-in: FIFO walk of `state.delayed_triggers`, pushed onto a LIFO stack → resolves **reverse-scheduling**. Source comment acknowledges APNAP is not modeled (single-controller queue makes it moot today, but the Rust port must match the same FIFO-push / LIFO-resolve ordering).
- `src/mtg_bot/turn.py:1146-1395` — `_state_based_actions_pass` iterates `state.battlefield` for planeswalker bury, legend-rule grouping (by `(controller_id, name)` dict-insertion order), destroyed-creature collection, saga age check, +1/+1 vs -1/-1 cancellation, aura legality, equipment legality. Each pass produces a deterministic list, but the *interleaving* across SBAs and the per-group `keep_id = group[0].id` fallback when agent is None (turn.py:1230) depend on iteration order.
- `src/mtg_bot/turn.py:1215-1239` — Legend-rule grouping uses `dict.setdefault((controller_id, name), [])` — Python dict insertion order is preserved (3.7+), so first-ETB-of-the-name comes first. The `keep_id` fallback (no agent) picks `group[0].id` = lowest ETB-timestamp by id; Rust port must match Python's `dict` insertion-order semantics here.
- `src/mtg_bot/combat.py` — Eligible-attackers / eligible-blockers walks battlefield order; declared-blockers assignment is a dict in defender-controlled iteration order. Combat damage assignment order = declared-blockers dict order.
- `src/mtg_bot/game.py:_compute_effective_pt + _static_bonuses` — Continuous-effect application walks `state.continuous_effects` in timestamp order (allocated by `state.next_timestamp` at `add_continuous_effect`). Multiple sources at the same layer are tie-broken by allocation order = registration order.

### 3.3 — State-based actions: literal application order

Single pass (`_state_based_actions_pass` at `src/mtg_bot/turn.py:1146`) applies the following SBAs **in this order**, then `state_based_actions` (turn.py:1125) loops until quiescent (cap `_SBA_MAX_PASSES = 50` at turn.py:1143):

- 1. Life ≤ 0 / poison ≥ 10 → has_lost  *(`src/mtg_bot/turn.py:1186-1194 (CR 704.5a / 704.5c)`)*
- 2. Planeswalker with 0 loyalty → graveyard  *(`src/mtg_bot/turn.py:1198-1208 (CR 704.5i)`)*
- 3. Legend rule (per (controller_id, name) dict-insertion order; agent.choose_legend_keep or group[0].id fallback)  *(`src/mtg_bot/turn.py:1215-1239 (CR 704.5j)`)*
- 4. Creature lethal/toughness pass: walks battlefield, picks targets with toughness ≤ 0 (NOT indestructible-saved), then damage ≥ toughness OR marked_lethal (saved by indestructible)  *(`src/mtg_bot/turn.py:1241-1254 (CR 704.5f/g/h)`)*
- 5. Regeneration shield consumption (CR 701.15) — runs inside the destroyed-pass loop at turn.py:1265-1278; toughness-≤-0 path is NOT regeneratable (gated on `tough > 0` at line 1265)  *(`src/mtg_bot/turn.py:1265-1278`)*
- 6. Move destroyed creatures → graveyard  *(`src/mtg_bot/turn.py:1280-1283`)*
- 7. Saga age (lore_counters ≥ chapter_count → sacrifice)  *(`src/mtg_bot/turn.py:1288-1298 (CR 704.5r audit)`)*
- 8. +1/+1 vs -1/-1 counter cancellation  *(`src/mtg_bot/turn.py:1308-1317 (CR 704.5r current CR)`)*
- 9. Aura on illegal target → graveyard (walks battlefield; aura_enchant_type ∈ {creature, artifact, land})  *(`src/mtg_bot/turn.py:1327-1358 (CR 704.5q current CR)`)*
- 10. Equipment on illegal target → unattach (stays on battlefield)  *(`src/mtg_bot/turn.py:1360-1381 (CR 704.5p audit)`)*
- 11. Alive-count → is_draw / winner_id  *(`src/mtg_bot/turn.py:1383-1393`)*

**Known gaps documented in source** (turn.py:1172-1182): world rule (704.5o), battle 0 defense (704.5u), 21+ commander damage, and non-battlefield token scrubbing are NOT implemented. The Rust port should match the same omissions for parity.

**Loop convergence**: `state_based_actions` re-runs the pass until no SBA fires; counter cancellation can drive toughness across 0, which is intentionally handled in the NEXT pass rather than interleaved (`for _ in range(_SBA_MAX_PASSES)` at turn.py:1136). Rust port must match the same per-pass / re-loop boundary.

### 3.4 — Trigger queue / stack ordering

No APNAP sort anywhere in the engine. Triggers are pushed onto `state.stack` in **the order they're discovered**, then resolved LIFO via `resolve_top_of_stack`. Discovery order is:

1. **`dispatch_event` (actions.py:3283)** — walks `permanents = list(state.battlefield)` (snapshotted before iteration), and for each source `enumerate(source.printing.triggered_abilities)`. For each match, calls `push_triggered_ability` (actions.py:3172-3280) which appends to `state.stack`. ETB multiplier (`etb_trigger_multiplier`, actions.py:3382) expands a single match to N pushes (Starfield Vocalist) in a tight loop — those N pushes are adjacent on the stack.
2. **Per-event legacy paths** (`turn._fire_dies_triggers` at turn.py:661, `combat._fire_*_triggers`, etc.) — same shape: iterate battlefield, push in order found. Migration is in progress (predicate-style is the new path; string-key style is legacy but still alive for some events).
3. **`run_delayed_end_step_triggers` (turn.py:773-840)** — walks `state.delayed_triggers` in FIFO scheduling order, pushes each onto the stack. Resolution is LIFO, so most recently scheduled fires first. Source comment (turn.py:789-792) explicitly notes this is a deterministic stand-in for APNAP.

**APNAP**: not modeled. Active player's triggers and non-active players' triggers go on the stack in **dispatch / battlefield iteration order**, not in APNAP order. Real MTG rule 603.3b says active player chooses order for their own triggers, then non-active players in turn order. Our engine's deterministic stand-in is good enough as long as Python and Rust agree on the battlefield iteration order. The grep for 'APNAP' returns exactly 2 hits, both comments in `turn.py:789` and `effects/generic/graveyard.py:403` — the latter is a comment on an iteration site where APNAP would matter but doesn't because the iteration is single-controller.

### 3.5 — Layered continuous-effect cache

Defined at `game.py:2760-2770`:

```
_layered_cache_version: int = 0
_layer6_wiped_cache: dict[int, tuple[int, bool]]  # source_id -> (version, result)
def _invalidate_layered_cache(self): self._layered_cache_version += 1
```

**Currently caches only `_source_layer6_wiped`** — the per-source answer to "is this source's printed abilities wiped by a lose-all-abilities layer-6 effect attached to it". Cache hit skips the inner doubly-nested `_static_bonuses` walk that dominates ~5% of a self-play game's profile (game.py:2754-2759 comment).

**Invalidation sites** (every write to `state.continuous_effects` must call this):

- `src/mtg_bot/game.py:2748` — `# Layered-walk memoization. Bumped by ``_invalidate_layered_cache```
- `src/mtg_bot/game.py:2765` — `def _invalidate_layered_cache(self) -> None:`
- `src/mtg_bot/game.py:2841` — `self._invalidate_layered_cache()`
- `src/mtg_bot/game.py:3034` — `self._invalidate_layered_cache()`
- `src/mtg_bot/game.py:3069` — `self._invalidate_layered_cache()`
- `src/mtg_bot/turn.py:309` — `state._invalidate_layered_cache()`
- `src/mtg_bot/effects/bespoke.py:2086` — `state._invalidate_layered_cache()`
- `src/mtg_bot/effects/bespoke.py:2155` — `state._invalidate_layered_cache()`

**What depends on coherence** (read path): only `_source_layer6_wiped` consults the cache today (single helper in `game.py`). The general mechanism is in place for future memoizations (`_static_bonuses`, `_compute_effective_pt`, `effective_keywords`) but they read directly from `state.continuous_effects` today.

**Per-clone semantics** (game.py:2752-2753 comment): cache is per-state, NOT shared across `state.clone()` calls — clone starts with `version=0` and empty `_layer6_wiped_cache`. The Rust port must match this clone-resets-cache behavior or shared-cache poisoning between MCTS-search branches will cause subtle wrong-trajectory bugs.

**Cleanup-step invalidation** (turn.py:309): the `move_off_battlefield` path filters `state.continuous_effects` to drop entries targeting the leaving object, then calls `state._invalidate_layered_cache()`. Cleanup-step expiry of `expires_at="cleanup"` UEOT entries similarly invalidates (via `run_cleanup_step` at turn.py:969 — see the function for the literal expiry walk and counter resets).
