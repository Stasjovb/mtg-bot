"""Edge of Eternities creature printings (set code ``eoe``).

The big creature registry. Every entry's comment records any
simplifications relative to the printed oracle text.
"""

from __future__ import annotations

from mtg_bot.cards.base import *  # noqa: F401,F403
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


EOE_CREATURES: dict[str, CardPrinting] = {
    c.name: c
    for c in [
        # White
        # ETB: +1/+1 counter on target creature you control. Also has a
        # death-watch trigger: whenever a nontoken creature you control
        # with a +1/+1 counter on it dies, make a 1/1 Soldier token.
        # Warp {1}{W}.
        make_creature(
            "Rayblade Trooper", "{2}{W}", 2, 2,
            warp="{1}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
                ),
                TriggeredAbility(
                    trigger="nontoken_creature_you_control_with_counter_dies",
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Human Soldier"],
                        count=1,
                    ),
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
        # ETB creates a 1/1 Human Soldier token. Warp {1}{W} — alt-cost
        # cast from hand, exiled at next end step, recastable later.
        make_creature(
            "Knight Luminary", "{3}{W}", 3, 2,
            warp="{1}{W}",
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
        # Quantum Riddler: Flying. ETB → draw a card. As long as you have
        # one or fewer cards in hand, "draw N" events draw N+1 instead.
        # Warp {1}{U}.
        make_creature(
            "Quantum Riddler", "{3}{U}{U}", 4, 6,
            keywords={"flying"},
            warp="{1}{U}",
            replaces_draw_with_extra_when_hand_at_most_one=True,
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
        # Specimen Freighter: {5}{U} 4/7 Spacecraft. ETB return up to two
        # target non-Spacecraft creatures to their owners' hands. Station
        # 9+ flying. Whenever this Spacecraft attacks, defending player
        # mills four cards (modeled as "each opponent mills 4" — exact in
        # 2-player). Spacecraft can only attack while stationed/animated,
        # so the attack trigger naturally only fires under that condition.
        make_spacecraft(
            "Specimen Freighter", "{5}{U}", 4, 7,
            station_threshold=9,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=ReturnUpToNTargetCreaturesToOwnersHands(
                        max_n=2, exclude_spacecraft=True,
                    ),
                ),
                TriggeredAbility(
                    trigger="attacks",
                    effect=EachOpponentMillsCards(amount=4),
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
        # up to one target creature. Station 7+ flying.
        make_spacecraft(
            "Pinnacle Kill-Ship", "{7}", 7, 7,
            station_threshold=7,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DealDamageToTargetCreature(amount=10, optional=True),
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
                TriggeredAbility(
                    trigger="sacrifice_artifact",
                    effect=DealDamageToTargetOpponent(amount=2),
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
        # Illvoi Infiltrator: {2}{U} 1/3.
        #   "This creature can't be blocked if you've cast two or more
        #    spells this turn." — modeled via the printing-level flag
        #    unblockable_if_two_spells_cast_this_turn, checked in
        #    combat.can_block / combat.declare_blockers against the
        #    controller's Player.spells_cast_this_turn counter.
        #   "Whenever this creature deals combat damage to a player,
        #    draw a card." — combat_damage_to_player trigger.
        make_creature(
            "Illvoi Infiltrator", "{2}{U}", 1, 3,
            unblockable_if_two_spells_cast_this_turn=True,
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
        # Timeline Culler: 2/2 Haste. Warp—{B}, Pay 2 life. Castable
        # from graveyard via the warp ability. (Stale prior comment
        # claimed an "attacks, mill 3 / return creature" rider, but
        # the printed oracle has no such trigger.)
        make_creature(
            "Timeline Culler", "{B}{B}", 2, 2,
            keywords={"haste"},
            warp="{B}",
            warp_additional_life_cost=2,
            warp_castable_from_graveyard=True,
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
        # turn costs {2} less to cast." External cost reduction granted
        # to OTHER spells the controller casts; stacks with the spell's
        # own cost_reductions (e.g. Gigastorm Titan's "{3} less if you've
        # already cast another spell this turn" → second spell of the
        # turn nets a 5-cost spell down to 0 generic when both apply).
        make_creature(
            "Uthros Psionicist", "{2}{U}", 2, 4,
            external_cost_reductions=(
                ExternalCostReduction(
                    amount=2,
                    condition="second_spell_this_turn",
                ),
            ),
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
        # with Defender. The "as long as an artifact entered the
        # battlefield under your control this turn, this creature can
        # attack as though it didn't have defender" clause is modeled
        # via the ``attack_bypass_if_artifact_entered_this_turn`` flag,
        # which combat.eligible_attackers checks against
        # Player.artifacts_entered_under_your_control_this_turn (which
        # actions.put_into_battlefield increments and run_cleanup_step
        # resets each turn).
        make_creature(
            "Mechan Shieldmate", "{1}{U}", 3, 2,
            artifact=True,
            keywords={"defender"},
            attack_bypass_if_artifact_entered_this_turn=True,
        ),
        # Mouth of the Storm: {6}{U} 6/6 Flying, Ward {2}. ETB:
        # "creatures your opponents control get -3/-0 until your next
        # turn." Simplification: the engine only tracks UEOT, not "until
        # your next turn," so the debuff is applied UEOT (clears at the
        # cleanup step of the casting player's turn). Practical impact is
        # similar — opponents' creatures still have full power back before
        # they can swing back at us next turn — but a true "until your
        # next turn" clause would persist through the OPPONENT's whole
        # next turn (relevant if the opponent attacks Mouth's controller's
        # planeswalker on their next turn before our next turn). Pump
        # durations across turns aren't modeled.
        make_creature(
            "Mouth of the Storm", "{6}{U}", 6, 6,
            keywords={"flying"},
            ward="{2}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=PumpCreaturesOpponentsControlUntilEOT(
                        power_bonus=-3,
                        toughness_bonus=0,
                    ),
                ),
            ),
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
                    effect=ReturnTargetPermanentYouControlToOwnersHand(
                        optional=True, exclude_self=True,
                    ),
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
        # Faller's Faithful: {2}{B} 3/1. ETB destroy target creature; if
        # that creature wasn't dealt damage this turn, its controller
        # draws two cards. Simplification: oracle says "up to one other
        # target creature" — we keep destruction required (no opt-out)
        # and ignore the "other" qualifier (irrelevant in practice
        # because Faithful entering itself isn't a legal target either
        # way for our targeting). The "wasn't dealt damage this turn"
        # rider is honored via GameObject.damaged_this_turn.
        make_creature(
            "Faller's Faithful", "{2}{B}", 3, 1,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=DestroyTargetCreature(
                        draw_if_undamaged_amount=2,
                    ),
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
        # put a +1/+1 counter on this creature." The "may" is treated as
        # auto-yes whenever the controller can afford {1}, matching the
        # OptionalSac/Kavaron Harrier precedent in this codebase.
        make_creature(
            "Oreplate Pangolin", "{1}{R}", 2, 2,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="artifact_enters_you_control",
                    effect=OptionalManaCostThenEffect(
                        cost_str="{1}",
                        inner_effect=PutPlusOneCounterOnSelf(amount=1),
                    ),
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
        # 1 life. At the beginning of your end step, draw a card if
        # you've gained 3 or more life this turn. Warp {W}.
        make_creature(
            "Haliya, Guided by Light", "{2}{W}", 2, 3,
            legendary=True,
            warp="{W}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="creature_or_artifact_enters_you_control",
                    effect=GainLife(amount=1),
                ),
                TriggeredAbility(
                    trigger="beginning_of_end_step",
                    effect=ConditionalIfYouGainedLifeAtLeast(
                        threshold=3,
                        inner=DrawCards(amount=1),
                    ),
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
        # Cryoshatter: {U} Aura. Enchanted creature gets -5/-0 and
        # "when enchanted creature becomes tapped or is dealt damage,
        # destroy it." Both halves are implemented:
        # - becomes-tapped: ``enchanted_permanent_becomes_tapped`` aura
        #   trigger fired by ``tap_permanent`` in turn.py.
        # - dealt-damage: ``enchanted_creature_dealt_damage`` aura
        #   trigger fired by ``_fire_enchanted_dealt_damage_triggers``
        #   in combat.py (for combat damage) and by ``_apply_damage``
        #   in effects/base.py (for direct damage from spells/abilities).
        make_aura(
            "Cryoshatter", "{U}",
            power_bonus=-5, toughness_bonus=0,
            triggered_abilities=(
                TriggeredAbility(
                    trigger="enchanted_permanent_becomes_tapped",
                    effect=DestroyEnchantedPermanent(),
                ),
                TriggeredAbility(
                    trigger="enchanted_creature_dealt_damage",
                    effect=DestroyEnchantedPermanent(),
                ),
            ),
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
        # Lander token. While on the battlefield, each creature you
        # control enters with an additional +1/+1 counter on it for
        # each land that entered the battlefield under your control
        # this turn. The ETB-counter rider is wired through the
        # ``grants_etb_counter_per_land_entered_this_turn`` flag,
        # which actions.put_into_battlefield consults when each
        # creature ETBs.
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
            grants_etb_counter_per_land_entered_this_turn=True,
        ),
        # Eusocial Engineering: {3}{G}{G} Enchantment. Landfall → create
        # a 2/2 Robot token. Warp {1}{G}.
        make_enchantment(
            "Eusocial Engineering", "{3}{G}{G}",
            warp="{1}{G}",
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

