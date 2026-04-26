"""Edge of Eternities instant and sorcery printings (set code ``eoe``).

Non-permanent spells that resolve via their ``spell_effect`` and then go
to their owner's graveyard.
"""

from __future__ import annotations

from mtg_bot.cards.base import *  # noqa: F401,F403
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


EOE_SPELLS: dict[str, CardPrinting] = {
    c.name: c
    for c in [
        # Plasma Bolt: "Deals 2 damage to any target. Void — deals 3
        # instead." Same target either way; ConditionalIfVoid switches
        # the damage amount at resolution.
        make_sorcery(
            "Plasma Bolt", "{R}",
            effect=ConditionalIfVoid(
                then_effect=DealDamageAnyTarget(amount=3),
                else_effect=DealDamageAnyTarget(amount=2),
            ),
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
        # turn. If it's not your turn, untap those creatures." Both the
        # pump and the conditional-untap rider are wired through
        # PumpCreaturesYouControlUntilEOT.also_untap_if_not_your_turn.
        make_instant(
            "Zealous Display", "{2}{W}",
            effect=PumpCreaturesYouControlUntilEOT(
                power_bonus=2, toughness_bonus=0,
                also_untap_if_not_your_turn=True,
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
        # strike until end of turn. If it has a +1/+1 counter on it,
        # draw a card." The conditional-draw rider is wired through
        # ``PumpTargetCreatureUntilEOT.draw_if_target_has_plus_one_counter``.
        make_instant(
            "Dual-Sun Technique", "{1}{W}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=0, toughness_bonus=0,
                granted_keywords=frozenset({"double strike"}),
                you_control_only=True,
                draw_if_target_has_plus_one_counter=1,
            ),
        ),
        # Desculpting Blast — return target nonland permanent to its
        # owner's hand. If it was attacking, create a 1/1 colorless
        # Drone artifact creature token (with flying + the Drone block
        # restriction). Both clauses now wired through
        # ReturnTargetCreatureToOwnersHand's allow_nonland_permanent
        # and create_drone_if_was_attacking flags.
        make_instant(
            "Desculpting Blast", "{1}{U}",
            effect=ReturnTargetCreatureToOwnersHand(
                allow_nonland_permanent=True,
                create_drone_if_was_attacking=True,
            ),
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
        # this Aura leaves the battlefield. Enchanted permanent has
        # ward {1} (wired via attached_grants_ward — see
        # game.effective_ward_cost and actions._apply_ward_check).
        make_aura(
            "Hardlight Containment", "{W}",
            aura_enchant_type="artifact",
            power_bonus=0, toughness_bonus=0,
            granted_keywords=frozenset(),
            attached_grants_ward="{1}",
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
        # created_tokens_this_turn (cleared at cleanup). No P/T bonus
        # — real card grants none.
        make_aura(
            "Moonlit Meditation", "{2}{U}",
            replaces_first_tokens_with_copies=True,
        ),
        # Tractor Beam `{2}{U}{U}` Enchantment — Aura. Real oracle:
        # "Enchant creature or Spacecraft. When this Aura enters, tap
        # enchanted permanent. You control enchanted permanent.
        # Enchanted permanent doesn't untap during its controller's
        # untap step."
        # All three clauses wired: ETB tap + don't-untap rider
        # (``attached_prevents_untap``) + continuous-while-attached
        # control swap (``TractorBeamETBEffect`` records the prior
        # controller in ``controller_id_before_aura_swap`` and
        # ``move_off_battlefield`` reverts when the aura leaves play).
        # No P/T bonus — real card grants none.
        make_aura(
            "Tractor Beam", "{2}{U}{U}",
            attached_prevents_untap=True,
            attached_grants_control=True,
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
        # No P/T bonus — real card grants none.
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
        # Memorial Vault `{3}{R}` Artifact. Oracle: "{T}, Sacrifice
        # another artifact: Exile the top X cards of your library,
        # where X is one plus the mana value of the sacrificed
        # artifact. You may play those cards this turn." Modeled with
        # the strict ``sacrifice_another_artifact`` cost (artifact-only
        # filter), so creatures and lands are excluded; X is read from
        # the most-recently-graveyarded artifact at resolution time.
        make_artifact(
            "Memorial Vault", "{3}{R}",
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        tap_self=True,
                        sacrifice_another_artifact=True,
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
        # Slivers (This spell costs {1} less to cast for each Sliver
        # you control.). Slivers you control have double strike and
        # haste. At the beginning of your upkeep, create two 1/1
        # colorless Sliver creature tokens."
        # Affinity wired via a CostReduction with the new
        # "affinity_for_slivers" condition (amount * Sliver count).
        # The Sliver anthem grants double strike + haste via a
        # SLIVERS_YOU_CONTROL static.
        make_artifact(
            "Thrumming Hivepool", "{6}",
            cost_reductions=(
                CostReduction(
                    amount=1, condition="affinity_for_slivers",
                ),
            ),
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.SLIVERS_YOU_CONTROL,
                    granted_keywords=frozenset({"double strike", "haste"}),
                ),
            ),
            triggered_abilities=(
                TriggeredAbility(
                    trigger="beginning_of_upkeep",
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
        # Weftwalking `{4}{U}{U}` Enchantment. Oracle: "When this
        # enchantment enters, if you cast it, shuffle your hand and
        # graveyard into your library, then draw seven cards. The
        # first spell each player casts during each of their turns may
        # be cast without paying its mana cost." The second (static,
        # alt-cast) ability is plumbed through the
        # grants_first_spell_each_turn_free flag — legal_actions
        # offers a CastSpell(cast_for_free=True) variant to the active
        # player while they haven't cast a spell this turn and any
        # battlefield permanent has this flag.
        make_enchantment(
            "Weftwalking", "{4}{U}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    trigger="etb",
                    effect=WeftwalkingETBEffect(),
                ),
            ),
            grants_first_spell_each_turn_free=True,
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
        # The doubling is gated through ``_counter_doubling_factor``
        # in game.py, which is consulted by ``add_plus_one_counters``,
        # ``add_charge_counters``, and ``add_stun_counters``. The
        # "Planet" type isn't modeled yet (no Planet-typed permanents
        # in the EoE pool we care about), so the scope is narrowed to
        # creature/Spacecraft.
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
        # Archenemy's Charm `{B}{B}{B}` Instant — Choose one:
        #   • Exile target creature or planeswalker.
        #   • Return one or two target creature and/or planeswalker
        #     cards from your graveyard to your hand.
        #   • Put two +1/+1 counters on target creature you control. It
        #     gains lifelink until end of turn.
        # Planeswalkers aren't fully modeled in our card pool yet — the
        # creature-only target pools are exhaustive in practice.
        make_instant(
            "Archenemy's Charm", "{B}{B}{B}",
            effect=ModalChooseOne(modes=(
                ExileTargetCreature(),
                ReturnUpToNCreaturesFromYourGraveyardToHand(
                    max_n=2, min_n=1,
                ),
                PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
                    amount=2,
                    granted_keywords=frozenset({"lifelink"}),
                ),
            )),
        ),
        # Close Encounter `{1}{G}` Instant:
        # "As an additional cost to cast this spell, choose a creature
        # you control or a warped creature card you own in exile.
        # Close Encounter deals damage equal to the power of the chosen
        # creature or card to target creature."
        # Both branches of the additional cost are honored — see the
        # ``additional_cost_choose_your_creature`` plumbing in
        # ``actions._cast_spell`` and the exile fallback in
        # ``CloseEncounterEffect.resolve``.
        make_instant(
            "Close Encounter", "{1}{G}",
            effect=CloseEncounterEffect(),
            additional_cost_choose_your_creature=True,
        ),
        # Diplomatic Relations `{2}{G}` Instant:
        # "Target creature you control gets +1/+0 and gains vigilance
        # until end of turn. It deals damage equal to its power to
        # target creature an opponent controls."
        # Two-target spell — see DiplomaticRelationsEffect for the
        # disjoint-filter target shape.
        make_instant(
            "Diplomatic Relations", "{2}{G}",
            effect=DiplomaticRelationsEffect(),
        ),
        # Scour for Scrap `{3}{U}` Instant — "Choose one or both":
        #   • Search your library for an artifact card, reveal it, put it
        #     into your hand, then shuffle.
        #   • Return target artifact card from your graveyard to your hand.
        # Modeled with ModalChooseOne(or_both=True) so the controller may
        # resolve both modes (in agent-chosen order) or either one alone.
        make_instant(
            "Scour for Scrap", "{3}{U}",
            effect=ModalChooseOne(
                modes=(
                    SearchLibraryForCard(
                        filter_name="artifact", may_fail=True,
                    ),
                    ReturnTargetArtifactCardFromYourGraveyardToHand(),
                ),
                or_both=True,
            ),
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
        # Lost in Space `{3}{U}` — "Target artifact or creature's owner
        # puts it on their choice of the top or bottom of their library.
        # Surveil 1."
        make_instant(
            "Lost in Space", "{3}{U}",
            effect=Sequence(effects=(
                OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(),
                Surveil(amount=1),
            )),
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
        # Destroy target creature or Spacecraft (the Spacecraft branch
        # also covers unstationed Spacecraft, which aren't currently
        # creatures).
        make_sorcery(
            "Embrace Oblivion", "{B}",
            effect=DestroyTargetCreature(or_spacecraft=True),
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
        # Dark Endurance — +2/+0 and indestructible UEOT. Carries the
        # "this spell costs {1} less to cast if it targets a blocking
        # creature" rider via a CostReduction; the
        # ``target_is_blocking_creature`` condition is evaluated against
        # the chosen target inside _cast_spell (and optimistically inside
        # legal_actions for affordability probing).
        make_instant(
            "Dark Endurance", "{1}{B}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=2, toughness_bonus=0,
                granted_keywords=frozenset({"indestructible"}),
            ),
            cost_reductions=(
                CostReduction(
                    amount=1, condition="target_is_blocking_creature",
                ),
            ),
        ),
        # Full Bore — +3/+2 UEOT on target creature you control. If that
        # creature was cast for its warp cost, it also gains trample and
        # haste UEOT.
        make_instant(
            "Full Bore", "{R}",
            effect=PumpTargetCreatureUntilEOT(
                power_bonus=3, toughness_bonus=2,
                you_control_only=True,
                granted_keywords_if_warp_cast=frozenset({"trample", "haste"}),
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
        # Scout for Survivors: return up to three target creature cards
        # with TOTAL mana value 3 or less from your graveyard to the
        # battlefield with a +1/+1 counter on each. The total-MV
        # constraint is enforced at resolution time (the cast pipeline
        # picks targets sequentially without a running budget — see
        # docstring on ReturnUpToNSmallCreaturesFromGraveyardWithCounters).
        make_sorcery(
            "Scout for Survivors", "{2}{W}",
            effect=ReturnUpToNSmallCreaturesFromGraveyardWithCounters(
                max_n=3, max_total_mv=3,
            ),
        ),
        # Drill Too Deep `{1}{R}` Instant — Choose one:
        #   • Put five charge counters on target Spacecraft or Planet
        #     you control.
        #   • Destroy target artifact.
        # Planet is a Land subtype already modeled here (see
        # ``make_planet_land``); the EoE pool ships five Planet lands
        # (Adagia, Evendo, Kavaron, Susur Secundi, Uthros), so the
        # Planet half of mode 0 is genuinely reachable.
        make_instant(
            "Drill Too Deep", "{1}{R}",
            effect=ModalChooseOne(modes=(
                PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(
                    amount=5,
                ),
                DestroyTargetArtifact(),
            )),
        ),
        # Reroute Systems `{W}` Instant — Choose one:
        #   • Target artifact or creature gains indestructible until end
        #     of turn. (Damage and effects that say "destroy" don't
        #     destroy it.)
        #   • Reroute Systems deals 2 damage to target tapped creature.
        # Mode 0 uses the ``("permanent", id)`` target kind via
        # ``PumpTargetArtifactOrCreatureUntilEOT`` so artifacts (not just
        # creatures) can be the target. Mode 1 uses
        # ``DealDamageToTargetTappedCreature`` which gates legal targets
        # on ``obj.tapped`` and re-checks at resolution.
        make_instant(
            "Reroute Systems", "{W}",
            effect=ModalChooseOne(modes=(
                PumpTargetArtifactOrCreatureUntilEOT(
                    granted_keywords=frozenset({"indestructible"}),
                ),
                DealDamageToTargetTappedCreature(amount=2),
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

