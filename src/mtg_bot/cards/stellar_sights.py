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
    "Blast Zone": make_colorless_land(  # dropped enters-with-counters + sac-mass-destroy.
        "Blast Zone",
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
    "Contested War Zone": make_colorless_land(  # dropped attackers-get-+1/+0 + gain-control.
        "Contested War Zone",
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
    "Echoing Deeps": make_colorless_land(  # dropped ETB choose-to-become-copy.
        "Echoing Deeps", subtypes_str="Cave",
    ),
    "Eldrazi Temple": make_colorless_land(  # dropped tap-for-2-when-casting-Eldrazi.
        "Eldrazi Temple",
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
    "Gemstone Caverns": make_colorless_land(  # dropped opening-hand luck-counter + any-color.
        "Gemstone Caverns", legendary=True,
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
    "Lotus Field": make_colorless_land(  # dropped ETB-sac-two-lands + tap-for-3-any.
        "Lotus Field",
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
    "Mystifying Maze": make_colorless_land(  # dropped exile-attacker-return-EoT activated.
        "Mystifying Maze",
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
    "Nesting Grounds": make_colorless_land(  # dropped move-a-counter-from-X-to-Y activated.
        "Nesting Grounds",
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
    "Plaza of Heroes": make_colorless_land(  # dropped legendary-tribal + pay-2-any.
        "Plaza of Heroes",
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
    "Sunken Citadel": make_colorless_land(  # dropped cave-discount-tap-for-2.
        "Sunken Citadel", subtypes_str="Cave",
    ),
    "Swarmyard": make_colorless_land(  # dropped regenerate-Rats/Spiders/etc.
        "Swarmyard",
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
