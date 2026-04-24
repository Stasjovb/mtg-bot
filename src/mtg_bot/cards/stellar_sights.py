"""EoE Stellar Sights (set code ``eos``) bonus-sheet lands.

45 land reprints included in Edge of Eternities boosters — the big utility
/ shock / manland cycle. Each entry's comment records any simplifications
relative to oracle text.
"""

from __future__ import annotations

from mtg_bot.cards.base import *  # noqa: F401,F403


# Edge of Eternities: Stellar Sights (Scryfall set `eos`). Bonus-sheet
# reprints of 45 famous Magic lands included in EoE boosters. Each
# entry below starts as a colorless-only stand-in (`# dropped X` per
# the same pattern used to track EOE_CREATURES restoration progress);
# incremental branches restore the real oracle ability.
STELLAR_SIGHTS_LANDS: dict[str, CardPrinting] = {
    # Ancient Tomb: `{T}: Add {C}{C}. This land deals 2 damage to you.`
    "Ancient Tomb": make_utility_land(
        "Ancient Tomb",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=DealDamageToControllerAndAddMana(
                    damage=2, produces=(("C", 2),),
                ),
                is_mana_ability=True,
            ),
        ),
    ),
    # Blast Zone: enters with a charge counter. {T}: Add {C}. {X}{X},
    # {T}: Put X charge counters on this land. {3},{T},Sacrifice this
    # land: Destroy each nonland permanent with mana value equal to
    # the number of charge counters on this land.
    "Blast Zone": make_utility_land(
        "Blast Zone",
        triggered_abilities=(
            TriggeredAbility(
                trigger="etb",
                effect=PutChargeCountersOnSelf(amount=1),
            ),
        ),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{X}{X}"),
                    mana_str="{X}{X}",
                    tap_self=True,
                ),
                effect=PutChargeCountersOnSelf(amount_from_x=True),
            ),
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"),
                    mana_str="{3}",
                    tap_self=True,
                    sacrifice_self=True,
                ),
                effect=(
                    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters()
                ),
            ),
        ),
    ),
    # Blinkmoth Nexus: {T}: Add {C}. {1}: → 1/1 Blinkmoth artifact
    # creature with flying UEOT. Also: {1}, {T}: +1/+1 UEOT to target
    # Blinkmoth — dropped (simplification: other Blinkmoths rare).
    "Blinkmoth Nexus": make_utility_land(
        "Blinkmoth Nexus",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"), mana_str="{1}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=1, toughness=1,
                    granted_keywords=frozenset({"flying"}),
                ),
            ),
        ),
    ),
    # Bonders' Enclave: `{T}: Add {C}. {3}, {T}: Draw a card.
    # Activate only if you control a creature with power 4 or
    # greater.`
    "Bonders' Enclave": make_utility_land(
        "Bonders' Enclave",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"),
                    mana_str="{3}",
                    tap_self=True,
                    requires_own_creature_power_at_least=4,
                ),
                effect=DrawCards(amount=1),
            ),
        ),
    ),
    # Cascading Cataracts: Indestructible. {T}: Add {C}. {5}, {T}:
    # Add five mana in any combination of colors.
    "Cascading Cataracts": make_utility_land(
        "Cascading Cataracts",
        keywords=frozenset({"indestructible"}),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{5}"),
                    mana_str="{5}",
                    tap_self=True,
                ),
                effect=AddManaToPool(produces=(("any", 5),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Cathedral of War: enters tapped, {T}: Add {C}. Exalted (whenever
    # a creature you control attacks alone, it gets +1/+1 UEOT).
    # Simplification: Exalted dropped — the engine has no "attacks alone"
    # trigger machinery. Taps-for-C + enters-tapped still matter for
    # mana sequencing, so restoring the timing half is still worthwhile.
    "Cathedral of War": make_utility_land(
        "Cathedral of War",
        enters_tapped=True,
    ),
    # Celestial Colonnade: enters tapped, {T}: W or U, {3}{W}{U}:
    # → 4/4 W/U Elemental flying vigilance UEOT.
    "Celestial Colonnade": make_utility_land(
        "Celestial Colonnade",
        produces=frozenset({"W", "U"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}{W}{U}"),
                    mana_str="{3}{W}{U}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=4, toughness=4,
                    granted_keywords=frozenset({"flying", "vigilance"}),
                ),
            ),
        ),
    ),
    # Contested War Zone: {T}: Add {C}. {1},{T}: Attacking creatures
    # get +1/+0 until end of turn. Whenever a creature deals combat
    # damage to you, that creature's controller gains control of this
    # land.
    "Contested War Zone": make_utility_land(
        "Contested War Zone",
        triggered_abilities=(
            TriggeredAbility(
                trigger="creature_deals_combat_damage_to_you",
                effect=ChangeControllerToCombatDamageSource(),
            ),
        ),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"),
                    mana_str="{1}",
                    tap_self=True,
                ),
                effect=PumpCreaturesYouControlUntilEOT(
                    power_bonus=1, toughness_bonus=0,
                    attacking_only=True,
                ),
            ),
        ),
    ),
    # Creeping Tar Pit: enters tapped, {T}: U or B, {1}{U}{B}: → 3/2
    # U/B Elemental UEOT. "It can't be blocked this turn."
    "Creeping Tar Pit": make_utility_land(
        "Creeping Tar Pit",
        produces=frozenset({"U", "B"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}{U}{B}"),
                    mana_str="{1}{U}{B}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=3, toughness=2, unblockable=True,
                ),
            ),
        ),
    ),
    # Crystal Quarry: {T}: Add {C}. {5}, {T}: Add {W}{U}{B}{R}{G}.
    "Crystal Quarry": make_utility_land(
        "Crystal Quarry",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{5}"),
                    mana_str="{5}",
                    tap_self=True,
                ),
                effect=AddManaToPool(
                    produces=(
                        ("W", 1), ("U", 1), ("B", 1), ("R", 1), ("G", 1),
                    ),
                ),
                is_mana_ability=True,
            ),
        ),
    ),
    # Deserted Temple: {T}: Add {C}. {1}, {T}: Untap target land.
    "Deserted Temple": make_utility_land(
        "Deserted Temple",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"),
                    mana_str="{1}",
                    tap_self=True,
                ),
                effect=UntapTargetLand(),
            ),
        ),
    ),
    # Dust Bowl: {T}: Add {C}. {3}, {T}, Sacrifice a land: Destroy
    # target nonbasic land.
    "Dust Bowl": make_utility_land(
        "Dust Bowl",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"),
                    mana_str="{3}",
                    tap_self=True,
                    sacrifice_a_land=True,
                ),
                effect=DestroyTargetLand(nonbasic_only=True),
            ),
        ),
    ),
    # Echoing Deeps: {T}: Add {C}. "You may have this land enter
    # tapped as a copy of any land card in a graveyard, except it's a
    # Cave in addition to its other types."
    #
    # Implementation: the optional_copy_land_from_graveyard flag
    # triggers a controller-agent prompt in _play_land. If they pick
    # a target graveyard land, the card's printing is replaced with a
    # Cave-injected copy of that printing and it enters tapped.
    # Decline (or no graveyard lands exist) → enters normally as a
    # Cave colorless land.
    "Echoing Deeps": make_utility_land(
        "Echoing Deeps", subtypes_str="Cave",
        optional_copy_land_from_graveyard=True,
    ),
    # Eldrazi Temple: {T}: Add {C}. {T}: Add {2}. Spend this mana
    # only to cast colorless Eldrazi spells or activate abilities of
    # colorless Eldrazi.
    #
    # Gameplay-moot in our EoE pool — no Eldrazi cards exist — but
    # the machinery is modeled faithfully: the second mana ability
    # produces two coins tagged "colorless_eldrazi", which
    # _coin_satisfies_context accepts for "colorless_eldrazi_spell"
    # (set in _cast_spell when the spell is an Eldrazi with no
    # colored pips) and "colorless_eldrazi_ability" (set in
    # _activate_ability when the source is a colorless-Eldrazi
    # permanent). With no Eldrazi in-pool the coins effectively sit
    # in the mana pool until cleanup.
    "Eldrazi Temple": make_utility_land(
        "Eldrazi Temple",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(
                    produces=(("C", 2),),
                    spend_restriction="colorless_eldrazi",
                ),
                is_mana_ability=True,
            ),
        ),
    ),
    # Endless Sands: {T}: Add {C}. {3},{T}: Exile target creature you
    # control. {3},{T}, Sacrifice this land: Return each card exiled
    # with this to the battlefield under its owner's control.
    #
    # Simplification: the engine's _release_exiled_until_leaves auto-
    # returns exiled creatures when ANY source leaves the battlefield,
    # including a non-sac destruction. Oracle would keep them exiled
    # permanently if the land died to e.g. Strip Mine. Close enough
    # for this scope — flavor preserved; rare edge case drops.
    "Endless Sands": make_utility_land(
        "Endless Sands", subtypes_str="Desert",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"),
                    mana_str="{3}",
                    tap_self=True,
                ),
                effect=ExileTargetCreatureUntilSourceLeaves(yours_only=True),
            ),
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"),
                    mana_str="{3}",
                    tap_self=True,
                    sacrifice_self=True,
                ),
                # The sac cost itself triggers
                # _release_exiled_until_leaves via move_off_battlefield,
                # so the effect body is empty.
                effect=Sequence(effects=()),
            ),
        ),
    ),
    # Gemstone Caverns: legendary. If in opening hand and you're not
    # the starting player, may begin the game with this on the
    # battlefield with a luck counter (+exile a card from hand). {T}:
    # Add {C}; if it has a luck counter, instead add one mana of any
    # color.
    #
    # Simplification: the opening-hand alt-ETB requires per-game
    # opening-hand reveal infrastructure we don't model. Caverns is
    # treated as if it ALWAYS has a luck counter — taps for one
    # "any"-color coin, like Reflecting Pool. Strictly an upside for
    # the player (oracle's untriggered case is colorless-only).
    "Gemstone Caverns": make_utility_land(
        "Gemstone Caverns", legendary=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Grove of the Burnwillows: `{T}: Add {C}. {T}: Add {R} or {G}.
    # Each opponent gains 1 life.` Modeled as produces={R,G} + a
    # becomes-tapped trigger granting 1 to each opp. Simplification:
    # the lifegain fires on every tap (including generic-only use),
    # which is slightly over-broad compared to the printed two-mode
    # mana ability.
    "Grove of the Burnwillows": make_utility_land(
        "Grove of the Burnwillows",
        produces=frozenset({"R", "G"}),
        triggered_abilities=(
            TriggeredAbility(
                trigger="becomes_tapped",
                effect=GrantLifeToEachOpponent(amount=1),
            ),
        ),
    ),
    # High Market: {T}: Add {C}. {T}, Sacrifice a creature: You gain
    # 1 life. Uses sacrifice_another_creature_or_artifact (wider than
    # oracle's "a creature"; creatures are always eligible, artifacts
    # incidentally too — acceptable widening).
    "High Market": make_utility_land(
        "High Market",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True,
                    sacrifice_another_creature_or_artifact=True,
                ),
                effect=GainLife(amount=1),
            ),
        ),
    ),
    # Hissing Quagmire: enters tapped, {T}: B or G, {1}{B}{G}: → 2/2
    # B/G Elemental deathtouch UEOT.
    "Hissing Quagmire": make_utility_land(
        "Hissing Quagmire",
        produces=frozenset({"B", "G"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}{B}{G}"),
                    mana_str="{1}{B}{G}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=2, toughness=2,
                    granted_keywords=frozenset({"deathtouch"}),
                ),
            ),
        ),
    ),
    # Inkmoth Nexus: {T}: C. {1}: → 1/1 Phyrexian Blinkmoth artifact
    # creature with flying and infect UEOT.
    "Inkmoth Nexus": make_utility_land(
        "Inkmoth Nexus",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"), mana_str="{1}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=1, toughness=1,
                    granted_keywords=frozenset({"flying", "infect"}),
                ),
            ),
        ),
    ),
    # Inventors' Fair: enters tapped, {T}: Add {C}. At the beginning of
    # your upkeep, if you control three or more artifacts, you gain 1
    # life. {1},{T}, Sacrifice this land: Search your library for an
    # artifact card, put it into your hand, then shuffle.
    "Inventors' Fair": make_utility_land(
        "Inventors' Fair", legendary=True,
        enters_tapped=True,
        triggered_abilities=(
            TriggeredAbility(
                trigger="beginning_of_upkeep",
                effect=ConditionalIfYouControlAtLeast(
                    threshold=3,
                    predicate="artifact",
                    inner=GainLife(amount=1),
                ),
            ),
        ),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"),
                    mana_str="{1}",
                    tap_self=True,
                    sacrifice_self=True,
                ),
                effect=SearchLibraryForCard(
                    filter_name="artifact", may_fail=False,
                ),
            ),
        ),
    ),
    # Lavaclaw Reaches: enters tapped, {T}: B or R, {1}{B}{R}: → 2/2
    # B/R Elemental UEOT. Real oracle also grants "{X}: +X/+0 UEOT"
    # while animated — not modeled (the granted-activated-while-
    # animated-UEOT pattern isn't supported yet).
    "Lavaclaw Reaches": make_utility_land(
        "Lavaclaw Reaches",
        produces=frozenset({"B", "R"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}{B}{R}"),
                    mana_str="{1}{B}{R}",
                ),
                effect=BecomeLandCreatureUEOT(power=2, toughness=2),
            ),
        ),
    ),
    # Lotus Field: Hexproof. Enters tapped. When it enters, sacrifice
    # two lands. {T}: Add three mana of any one color.
    #
    # Simplification: oracle's "three of any ONE color" becomes three
    # coins tagged "any" (each is a wildcard satisfying any colored
    # requirement). Strictly more flexible than oracle — a small
    # upside for the player — but correct for non-hybrid costs.
    "Lotus Field": make_utility_land(
        "Lotus Field",
        keywords=frozenset({"hexproof"}),
        enters_tapped=True,
        triggered_abilities=(
            TriggeredAbility(
                trigger="etb",
                effect=SacrificeNLandsYouControl(count=2),
            ),
        ),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 3),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Lumbering Falls: enters tapped, {T}: G or U, {2}{G}{U}: → 3/3
    # G/U Elemental hexproof UEOT.
    "Lumbering Falls": make_utility_land(
        "Lumbering Falls",
        produces=frozenset({"G", "U"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}{G}{U}"),
                    mana_str="{2}{G}{U}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=3, toughness=3,
                    granted_keywords=frozenset({"hexproof"}),
                ),
            ),
        ),
    ),
    # Mana Confluence: `{T}, Pay 1 life: Add one mana of any color.`
    "Mana Confluence": make_utility_land(
        "Mana Confluence",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True, pay_life=1),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Meteor Crater: {T}: Choose a color of a permanent you control.
    # Add one mana of that color. Simplified to "any" coin.
    "Meteor Crater": make_utility_land(
        "Meteor Crater",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Mirrorpool: Legendary Land. Enters tapped. {T}: Add {C}.
    # {2}{C}, {T}, Sacrifice: Copy target instant or sorcery spell you
    # control; you may choose new targets.
    # {4}{C}, {T}, Sacrifice: Create a token that's a copy of target
    # creature you control.
    #
    # Simplification: copy-spell short-circuits to re-resolving the
    # target spell's effect rather than pushing a fresh StackItem.
    # Counterspell-proofing and split-moment responses aren't modeled.
    "Mirrorpool": make_utility_land(
        "Mirrorpool", legendary=True, enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}{C}"),
                    mana_str="{2}{C}",
                    tap_self=True,
                    sacrifice_self=True,
                ),
                effect=CopyTargetInstantOrSorceryYouControl(),
            ),
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{4}{C}"),
                    mana_str="{4}{C}",
                    tap_self=True,
                    sacrifice_self=True,
                ),
                effect=CreateTokenCopyOfTargetCreatureYouControl(),
            ),
        ),
    ),
    # Mutavault: {T}: C. {1}: → 2/2 creature with all creature types
    # UEOT. "All creature types" isn't modeled; the 2/2 body lands
    # cleanly.
    "Mutavault": make_utility_land(
        "Mutavault",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"), mana_str="{1}",
                ),
                effect=BecomeLandCreatureUEOT(power=2, toughness=2),
            ),
        ),
    ),
    # Mystifying Maze: {T}: Add {C}. {4},{T}: Exile target attacking
    # creature an opponent controls. At the beginning of the next end
    # step, that player returns it to the battlefield under its
    # owner's control tapped.
    "Mystifying Maze": make_utility_land(
        "Mystifying Maze",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{4}"),
                    mana_str="{4}",
                    tap_self=True,
                ),
                effect=ExileTargetAttackingCreatureUntilEndStep(),
            ),
        ),
    ),
    # Needle Spires: enters tapped, {T}: R or W, {2}{R}{W}: → 2/1
    # R/W Elemental double strike UEOT.
    "Needle Spires": make_utility_land(
        "Needle Spires",
        produces=frozenset({"R", "W"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}{R}{W}"),
                    mana_str="{2}{R}{W}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=2, toughness=1,
                    granted_keywords=frozenset({"double strike"}),
                ),
            ),
        ),
    ),
    # Nesting Grounds: {T}: Add {C}. {1},{T}: Move a counter from
    # target permanent you control onto a second target permanent.
    # Activate only as a sorcery.
    #
    # Simplification: oracle allows "a counter" of any type; this
    # implementation moves exactly one +1/+1 counter. Other counter
    # types (charge, loyalty, stun) stay on their original permanent
    # — their recipient constraints (Spacecraft for charge, PW for
    # loyalty, tapped creature for stun) would need per-type
    # filtering. +1/+1 counters are by far the common case in the
    # EoE pool.
    "Nesting Grounds": make_utility_land(
        "Nesting Grounds",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"),
                    mana_str="{1}",
                    tap_self=True,
                ),
                effect=MovePlusOneCounterBetweenPermanentsYouControl(),
                sorcery_speed=True,
            ),
        ),
    ),
    # Petrified Field: `{T}: Add {C}. {T}, Sacrifice this land:
    # Return target land card from your graveyard to your hand.`
    "Petrified Field": make_utility_land(
        "Petrified Field",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True, sacrifice_self=True,
                ),
                effect=ReturnTargetLandFromGraveyardToHand(),
            ),
        ),
    ),
    # Plaza of Heroes: {T}: Add {C}. {T}: Add one mana of any color
    # (spend only for a legendary spell). {T}: Add one mana of any
    # color among legendary permanents you control. {3},{T}, Exile
    # this land: Target legendary creature gains hexproof and
    # indestructible UEOT.
    #
    # Simplification: the two mana abilities with spend restrictions
    # ("only for legendary spells" + "among legendary permanents you
    # control") are dropped — both would need spend_restriction
    # plumbing tied to card characteristics and legendary-permanent
    # tracking. The flagship activated ability (grant hexproof +
    # indestructible UEOT) is restored, but without the "target
    # LEGENDARY creature" filter — targets any creature. Exile-self
    # is modeled as sacrifice-self (close enough; only matters if an
    # effect cares about Plaza being in the graveyard vs. exile).
    "Plaza of Heroes": make_utility_land(
        "Plaza of Heroes", legendary=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"),
                    mana_str="{3}",
                    tap_self=True,
                    sacrifice_self=True,
                ),
                effect=PumpTargetCreatureUntilEOT(
                    granted_keywords=frozenset(
                        {"hexproof", "indestructible"}
                    ),
                ),
            ),
        ),
    ),
    # Power Depot `Artifact Land`. Oracle: "This land enters tapped.
    # {T}: Add {C}. {T}: Add one mana of any color. Spend this mana
    # only to cast artifact spells or activate abilities of artifacts.
    # Modular 1."
    # Simplifications: the second ability adds an "any" coin tagged
    # artifact_spell (our engine doesn't model the artifact-activation
    # branch of the restriction). Modular 1 (enters-with-+1/+1 counter
    # plus dies-move-to-creature) is NOT modeled — Modular is an
    # artifact-equipment archetype, and Power Depot dying rarely
    # happens in our sim.
    "Power Depot": CardPrinting(
        name="Power Depot",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Artifact Land",
        supertypes=(),
        card_types=("Artifact", "Land"),
        subtypes=(),
        produces=frozenset(),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(
                    produces=(("any", 1),),
                    spend_restriction="artifact_spell",
                ),
                is_mana_ability=True,
            ),
        ),
    ),
    # Raging Ravine: enters tapped, {T}: R or G, {2}{R}{G}: → 3/3
    # R/G Elemental UEOT. Real oracle also grants "when this attacks,
    # put a +1/+1 counter on it" while animated — not modeled (see
    # Lavaclaw note).
    "Raging Ravine": make_utility_land(
        "Raging Ravine",
        produces=frozenset({"R", "G"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}{R}{G}"),
                    mana_str="{2}{R}{G}",
                ),
                effect=BecomeLandCreatureUEOT(power=3, toughness=3),
            ),
        ),
    ),
    # Reflecting Pool: {T}: Add one mana of any type that a land you
    # control could produce. Simplified to "any" coin — the dynamic
    # "type your lands could produce" is a wildcard in practice
    # (our agents don't reason about conditional mana availability).
    "Reflecting Pool": make_utility_land(
        "Reflecting Pool",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Scavenger Grounds: {T}: Add {C}. {2}, {T}, Sacrifice a Desert:
    # Exile all graveyards.
    "Scavenger Grounds": make_utility_land(
        "Scavenger Grounds",
        subtypes_str="Desert",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}"),
                    mana_str="{2}",
                    tap_self=True,
                    sacrifice_a_desert=True,
                ),
                effect=ExileAllGraveyards(),
            ),
        ),
    ),
    # Shambling Vent: enters tapped, {T}: W or B, {1}{W}{B}: → 2/3
    # W/B Elemental lifelink UEOT.
    "Shambling Vent": make_utility_land(
        "Shambling Vent",
        produces=frozenset({"W", "B"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}{W}{B}"),
                    mana_str="{1}{W}{B}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=2, toughness=3,
                    granted_keywords=frozenset({"lifelink"}),
                ),
            ),
        ),
    ),
    # Stirring Wildwood: enters tapped, {T}: G or W, {1}{G}{W}: → 3/4
    # G/W Elemental reach UEOT.
    "Stirring Wildwood": make_utility_land(
        "Stirring Wildwood",
        produces=frozenset({"G", "W"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}{G}{W}"),
                    mana_str="{1}{G}{W}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=3, toughness=4,
                    granted_keywords=frozenset({"reach"}),
                ),
            ),
        ),
    ),
    # Strip Mine: `{T}: Add {C}. {T}, Sacrifice this land: Destroy
    # target land.`
    "Strip Mine": make_utility_land(
        "Strip Mine",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True, sacrifice_self=True,
                ),
                effect=DestroyTargetLand(),
            ),
        ),
    ),
    # Sunken Citadel: Enters tapped. As it enters, choose a color.
    # {T}: Add one mana of the chosen color. {T}: Add two mana of the
    # chosen color — spend only to activate land abilities.
    #
    # Simplifications: the "choose a color on ETB" and per-object
    # color storage aren't modeled — Citadel taps for one "any"-color
    # coin (strictly more flexible than oracle's locked-in color).
    # The second "add two mana, spend only for land abilities" ability
    # is dropped — its spend restriction would need new cost-payment
    # plumbing tagged for land-activations.
    "Sunken Citadel": make_utility_land(
        "Sunken Citadel", subtypes_str="Cave", enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    ),
    # Swarmyard: {T}: Add {C}. {1},{T}: Regenerate target Rat, Spider,
    # Squirrel, Insect, or Snake.
    #
    # Gameplay-moot in our EoE pool — no printed creatures have any of
    # the five allowed subtypes — but the regenerate machinery is now
    # fully wired (GameObject.regeneration_shield + SBA check in
    # state_based_actions + UEOT cleanup). The ability's target
    # filter lists the subtype constraint so legal_moves honors it.
    "Swarmyard": make_utility_land(
        "Swarmyard",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"),
                    mana_str="{1}",
                    tap_self=True,
                ),
                effect=RegenerateTargetCreature(
                    allowed_subtypes=frozenset({
                        "Rat", "Spider", "Squirrel", "Insect", "Snake",
                    }),
                ),
            ),
        ),
    ),
    # Terrain Generator: `{T}: Add {C}. {2}, {T}: You may put a basic
    # land card from your hand onto the battlefield tapped.`
    "Terrain Generator": make_utility_land(
        "Terrain Generator",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}"),
                    mana_str="{2}",
                    tap_self=True,
                ),
                effect=PutBasicLandFromHandOntoBattlefieldTapped(),
            ),
        ),
    ),
    # Thespian's Stage: {T}: Add {C}. {2},{T}: This land becomes a copy
    # of target land, except it has this ability.
    #
    # Implementation: BecomesCopyOfTargetLand mutates source.printing
    # to match the target's printing, re-attaching Thespian's own
    # activated abilities so "it has this ability" survives.
    "Thespian's Stage": make_utility_land(
        "Thespian's Stage",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}"),
                    mana_str="{2}",
                    tap_self=True,
                ),
                effect=BecomesCopyOfTargetLand(),
            ),
        ),
    ),
    # Wandering Fumarole: enters tapped, {T}: U or R, {2}{U}{R}: → 1/4
    # U/R Elemental UEOT. Real oracle also grants "{0}: Switch P/T
    # UEOT" while animated — not modeled (see Lavaclaw note).
    "Wandering Fumarole": make_utility_land(
        "Wandering Fumarole",
        produces=frozenset({"U", "R"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}{U}{R}"),
                    mana_str="{2}{U}{R}",
                ),
                effect=BecomeLandCreatureUEOT(power=1, toughness=4),
            ),
        ),
    ),
}
