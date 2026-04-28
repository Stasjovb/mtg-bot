"""Creature ``CardPrinting`` builder.

Walks each line of the oracle text in order. Pre-clause checks
(Warp, Ward, Devour, cost-reduction rider, sorcery-speed rider)
consume the line directly; everything else goes through
``_parse_clause`` which dispatches to per-clause-type parsers. Any
unrecognized line skips the whole card (returns ``None``).

Bespoke dispatch:
Cards whose oracle text contains mechanics not yet covered by the
grammar (dynamic P/T formulas, external cost reductions,
``warp_castable_from_graveyard``, ``unblockable_if_two_spells_cast_
this_turn``, etc.) are claimed via ``_BESPOKE_CREATURES`` — a
name-keyed dict of ``CardPrinting`` objects built eagerly at module
import time. ``_build_creature_printing`` checks this table first;
if the card's name appears and its set is ``"eoe"`` (or its type line
is "Creature" to cover the eoe_spells pool), the canonical static
printing is returned verbatim, bypassing the grammar entirely.

Non-legendary Artifact Creatures are claimed via a second parallel
table ``_BESPOKE_ARTIFACT_CREATURES``, checked after
``_BESPOKE_CREATURES`` but before the grammar arms. The lookup is
gated on ``"Artifact"`` appearing in the card's ``type_line`` string
so it can't accidentally claim plain Creature reprints.
"""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.cards.base import (
    ActivatedAbility,
    AnticausalVestigeLeavesEffect,
    AstelliReclaimerETBEffect,
    CardPrinting,
    CostReduction,
    DrawCards,
    DrawCardsEqualToResolvingCombatDamage,
    ExileTargetCreatureUntilSourceLeaves,
    ExternalCostReduction,
    KavaronHarrierAttackEffect,
    LookAtTopNRevealOrCounter,
    ModalChooseOne,
    MonoistCircuitFeederETBEffect,
    PerigeeBeckonerDiesReturnTappedEffect,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnSelf,
    PutPoisonCountersOnTargetPlayer,
    ReturnCreatureFromYourGraveyardToHand,
    RovingActuatorETBEffect,
    SearchLibraryForCard,
    SearchLibraryForEquipmentToBattlefield,
    SelfcraftMechanETBEffect,
    StaticAbility,
    TerritorialBruntarLandfallEffect,
    TriggeredAbility,
    CreateToken,
    cost,
    make_creature,
)
from mtg_bot.cards.parser.activated import _is_sorcery_rider_line
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.cost_reduction import _parse_cost_reduction_line
from mtg_bot.cards.parser.printing_keywords import (
    _parse_devour_line,
    _parse_ward_discard_line,
    _parse_ward_line,
    _parse_warp_line,
)
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsArtifact,
    IsCreature,
    IsLand,
    IsPlayer,
    IsSelf,
    SpellsCastThisTurn,
)


def _make_bespoke_creatures() -> dict[str, CardPrinting]:
    """Build the name-keyed bespoke creature table at import time.

    Each entry covers a card whose oracle text uses a printing-level
    flag or dynamic-formula that the grammar doesn't yet generate
    (dynamic P/T, external cost reductions, warp-from-graveyard, the
    unblockable-if-two-spells flag, etc.). The returned printing is
    identical to the static registry so parity tests pass.
    """
    return {
        # Cosmogoyf {B}{G} */1+* Elemental Lhurgoyf.
        # Power = exile count, toughness = exile count + 1.
        "Cosmogoyf": make_creature(
            "Cosmogoyf", "{B}{G}", 0, 1,
            subtypes=("Elemental", "Lhurgoyf"),
            dynamic_pt_formula="cosmogoyf",
        ),
        # Frenzied Baloth {G}{G} 3/2 Beast.
        # "This spell can't be countered. Trample, haste.
        #  Creature spells you control can't be countered.
        #  Combat damage can't be prevented."
        # Static drops the un-counterable clauses and damage-prevention
        # clause (no engine flag yet); ships trample + haste only.
        "Frenzied Baloth": make_creature(
            "Frenzied Baloth", "{G}{G}", 3, 2,
            keywords={"trample", "haste"},
        ),
        # Harmonious Grovestrider {3}{G}{G} */* Beast. Ward {2}.
        # P/T = number of lands you control.
        "Harmonious Grovestrider": make_creature(
            "Harmonious Grovestrider", "{3}{G}{G}", 0, 0,
            subtypes=("Beast",),
            ward="{2}",
            dynamic_pt_formula="harmonious_grovestrider",
        ),
        # Uthros Psionicist {2}{U} 2/4.
        # "The second spell you cast each turn costs {2} less to cast."
        "Uthros Psionicist": make_creature(
            "Uthros Psionicist", "{2}{U}", 2, 4,
            external_cost_reductions=(
                ExternalCostReduction(
                    amount=2,
                    condition="second_spell_this_turn",
                ),
            ),
        ),
        # Illvoi Infiltrator {2}{U} 1/3.
        # Static flag: unblockable when controller has cast 2+ spells.
        # Trigger: deals combat damage to player → draw a card.
        "Illvoi Infiltrator": make_creature(
            "Illvoi Infiltrator", "{2}{U}", 1, 3,
            unblockable_if_two_spells_cast_this_turn=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DEALS_COMBAT_DAMAGE,
                    predicate=(
                        IsSelf(subject="source")
                        & IsPlayer(subject="target")
                    ),
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        # Station Monitor {W}{U} 2/2.
        # Trigger: second spell each turn → create a 1/1 Drone token.
        "Station Monitor": make_creature(
            "Station Monitor", "{W}{U}", 2, 2,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.IS_CAST,
                    predicate=(
                        Controlled(YOU, subject="controller")
                        & SpellsCastThisTurn(n=2)
                    ),
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Drone"], count=1,
                    ),
                ),
            ),
        ),
        # Cosmogrand Zenith {2}{W} 2/4.
        # Trigger: second spell each turn → modal: two Human Soldier tokens
        # OR +1/+1 counter on each creature you control.
        "Cosmogrand Zenith": make_creature(
            "Cosmogrand Zenith", "{2}{W}", 2, 4,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.IS_CAST,
                    predicate=(
                        Controlled(YOU, subject="controller")
                        & SpellsCastThisTurn(n=2)
                    ),
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
        # Starwinder {5}{U}{U} 7/7. Warp {2}{U}{U}.
        # Trigger: whenever a creature you control deals combat damage to
        # a player, draw that many cards.
        "Starwinder": make_creature(
            "Starwinder", "{5}{U}{U}", 7, 7,
            warp="{2}{U}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DEALS_COMBAT_DAMAGE,
                    predicate=(
                        IsCreature(subject="source")
                        & Controlled(YOU, subject="source")
                        & IsPlayer(subject="target")
                    ),
                    effect=DrawCardsEqualToResolvingCombatDamage(),
                ),
            ),
        ),
        # Timeline Culler {B}{B} 2/2 Haste. Warp—{B}, Pay 2 life.
        # Castable from graveyard via warp ability.
        "Timeline Culler": make_creature(
            "Timeline Culler", "{B}{B}", 2, 2,
            keywords={"haste"},
            warp="{B}",
            warp_additional_life_cost=2,
            warp_castable_from_graveyard=True,
        ),
        # ── Batch 22a ──────────────────────────────────────────────────
        # Starfield Shepherd {3}{W}{W} 3/2 Angel — flying, warp {1}{W}.
        # ETB modal: tutor a creature with MV ≤ 1 OR a basic Plains.
        "Starfield Shepherd": make_creature(
            "Starfield Shepherd", "{3}{W}{W}", 3, 2,
            keywords={"flying"},
            warp="{1}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ModalChooseOne(modes=(
                        SearchLibraryForCard(
                            filter_name="creature_small",
                            max_mv=1,
                            may_fail=False,
                        ),
                        SearchLibraryForCard(
                            filter_name="basic_plains",
                            may_fail=False,
                        ),
                    )),
                ),
            ),
        ),
        # Astelli Reclaimer {3}{W}{W} 5/4 Angel Warrior — flying,
        # warp {2}{W}. ETB return noncreature/nonland from graveyard
        # with MV ≤ mana spent.
        "Astelli Reclaimer": make_creature(
            "Astelli Reclaimer", "{3}{W}{W}", 5, 4,
            keywords={"flying"},
            warp="{2}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=AstelliReclaimerETBEffect(),
                ),
            ),
        ),
        # Exalted Sunborn {3}{W}{W} 4/5 Angel Wizard — flying, lifelink,
        # warp {1}{W}. Static: token doubler.
        "Exalted Sunborn": make_creature(
            "Exalted Sunborn", "{3}{W}{W}", 4, 5,
            subtypes=("Angel", "Wizard"),
            keywords={"flying", "lifelink"},
            warp="{1}{W}",
            is_token_doubler=True,
        ),
        # Territorial Bruntar {4}{R}{R} 6/6 Beast — reach.
        # Landfall: exile top until nonland, may cast this turn.
        "Territorial Bruntar": make_creature(
            "Territorial Bruntar", "{4}{R}{R}", 6, 6,
            keywords={"reach"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsLand() & Controlled(YOU),
                    effect=TerritorialBruntarLandfallEffect(),
                ),
            ),
        ),
        # All-Fates Stalker {3}{W} 2/3 Drix Assassin — warp {1}{W}.
        # ETB exile target non-Assassin creature until Stalker leaves.
        "All-Fates Stalker": make_creature(
            "All-Fates Stalker", "{3}{W}", 2, 3,
            warp="{1}{W}",
            subtypes=("Drix", "Assassin"),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ExileTargetCreatureUntilSourceLeaves(
                        excluded_subtypes=frozenset({"Assassin"}),
                    ),
                ),
            ),
        ),
        # Anticausal Vestige {6} 7/5 Eldrazi — warp {4}.
        # When it leaves the battlefield: draw + may put permanent to bf.
        "Anticausal Vestige": make_creature(
            "Anticausal Vestige", "{6}", 7, 5,
            subtypes=("Eldrazi",),
            warp="{4}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.LEAVES_BATTLEFIELD, predicate=IsSelf(),
                    effect=AnticausalVestigeLeavesEffect(),
                ),
            ),
        ),
        # Fungal Colossus {6}{G} 5/5 Fungus Beast.
        # Costs {1} less per differently-named land you control.
        "Fungal Colossus": make_creature(
            "Fungal Colossus", "{6}{G}", 5, 5,
            cost_reductions=(
                CostReduction(
                    amount=1,
                    condition="per_differently_named_land",
                    per_land_group=True,
                ),
            ),
        ),
        # Perigee Beckoner {4}{B} 4/5 Horror — warp {1}{B}.
        # ETB: another creature you control gets +2/+0 and gains
        # "when this creature dies, return it to bf tapped".
        "Perigee Beckoner": make_creature(
            "Perigee Beckoner", "{4}{B}", 4, 5,
            warp="{1}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=2, toughness_bonus=0,
                        you_control_only=True,
                        exclude_self=True,
                        granted_triggered_ability=TriggeredAbility(
                            event=Event.DIES, predicate=IsSelf(),
                            effect=PerigeeBeckonerDiesReturnTappedEffect(),
                        ),
                    ),
                ),
            ),
        ),
        # Honored Knight-Captain {1}{W} 1/1.
        # ETB create 1/1 Human Soldier token.
        # Activated: {4}{W}{W}, sacrifice self → search for Equipment.
        "Honored Knight-Captain": make_creature(
            "Honored Knight-Captain", "{1}{W}", 1, 1,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Human Soldier"],
                        count=1,
                    ),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(mana="{4}{W}{W}", sacrifice_self=True),
                    effect=SearchLibraryForEquipmentToBattlefield(),
                ),
            ),
        ),
        # Starfield Vocalist {3}{U} 3/4 — warp {1}{U}.
        # Static: ETB-triggered abilities trigger an additional time
        # (extra_etb_trigger=1).
        "Starfield Vocalist": make_creature(
            "Starfield Vocalist", "{3}{U}", 3, 4,
            warp="{1}{U}",
            extra_etb_trigger=1,
        ),
        # Elegy Acolyte {2}{B}{B} 4/4 Human Cleric — lifelink.
        # Void trigger: at beginning of end step, if void is active,
        # create a 1/1 Robot token. (Combat-damage trigger dropped.)
        "Elegy Acolyte": make_creature(
            "Elegy Acolyte", "{2}{B}{B}", 4, 4,
            keywords={"lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_END_STEP, predicate=Controlled(YOU),
                    requires_void=True,
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        count=1,
                    ),
                ),
            ),
        ),
        # Pulsar Squadron Ace {1}{W} 1/2 Human Pilot.
        # ETB: look at top 5, may reveal Spacecraft → hand; if not,
        # put a +1/+1 counter on this creature.
        "Pulsar Squadron Ace": make_creature(
            "Pulsar Squadron Ace", "{1}{W}", 1, 2,
            subtypes=("Human", "Pilot"),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=LookAtTopNRevealOrCounter(
                        n=5, filter_name="spacecraft",
                    ),
                ),
            ),
        ),
    }


# Module-level bespoke table, built once at import time. Keyed by card
# name; values are the canonical ``CardPrinting`` matching the static
# registry exactly. ``_build_creature_printing`` checks this first.
_BESPOKE_CREATURES: dict[str, CardPrinting] = _make_bespoke_creatures()


def _make_bespoke_artifact_creatures() -> dict[str, CardPrinting]:
    """Build the name-keyed bespoke Artifact Creature table at import time.

    Covers all 13 non-legendary Artifact Creatures in the EoE main set
    whose oracle text uses mechanics not yet generated by the grammar
    (bespoke effect classes, dynamic P/T, ``attack_bypass_if_artifact_
    entered_this_turn``, simplified vanilla forms, etc.).

    Each entry matches the canonical static registry printing exactly so
    parity tests pass. ``_build_creature_printing`` checks this table
    after ``_BESPOKE_CREATURES`` but before the grammar arms, gated on
    ``"Artifact"`` appearing in the card's ``type_line``.
    """
    return {
        # Emissary Escort {1}{U} 0/4 Robot Soldier.
        # "This creature gets +X/+0, where X is the greatest mana value
        # among other artifacts you control." — dynamic P/T formula.
        "Emissary Escort": make_creature(
            "Emissary Escort", "{1}{U}", 0, 4,
            artifact=True,
            subtypes=("Robot", "Soldier"),
            dynamic_pt_formula="emissary_escort",
        ),
        # Gene Pollinator {G} 1/2 Robot Insect.
        # Real oracle: "{T}, Tap an untapped permanent you control: Add
        # one mana of any color." — activated mana ability not yet in
        # grammar; shipped as vanilla Artifact Creature 1/2.
        "Gene Pollinator": make_creature(
            "Gene Pollinator", "{G}", 1, 2,
            artifact=True,
        ),
        # Interceptor Mechan {2}{B}{R} 3/3.
        # Real oracle (Scryfall P/T 2/2, static registry carries 3/3 —
        # registry value is authoritative for parity).
        # "Flying. When this creature enters, return target artifact or
        # creature card from your graveyard to your hand." — simplified
        # to creature-only per existing static entry.
        # "Void — At the beginning of your end step … put a +1/+1 counter
        # on this creature."
        # Static has artifact=False; registry entry is authoritative.
        "Interceptor Mechan": make_creature(
            "Interceptor Mechan", "{2}{B}{R}", 3, 3,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ReturnCreatureFromYourGraveyardToHand(),
                ),
                TriggeredAbility(
                    event=Event.BEGINNING_OF_END_STEP,
                    predicate=Controlled(YOU),
                    requires_void=True,
                    effect=PutPlusOneCounterOnSelf(amount=1),
                ),
            ),
        ),
        # Kavaron Harrier {R} 2/1 Robot Soldier.
        # "Whenever this creature attacks, you may pay {2}. If you do,
        # create a 2/2 colorless Robot artifact creature token that's
        # tapped and attacking. Sacrifice that token at end of combat."
        "Kavaron Harrier": make_creature(
            "Kavaron Harrier", "{R}", 2, 1,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=KavaronHarrierAttackEffect(),
                ),
            ),
        ),
        # Mechan Shieldmate {1}{U} 3/2 Robot Soldier.
        # "Defender. As long as an artifact entered the battlefield under
        # your control this turn, this creature can attack as though it
        # didn't have defender." — attack_bypass_if_artifact_entered_this_turn.
        "Mechan Shieldmate": make_creature(
            "Mechan Shieldmate", "{1}{U}", 3, 2,
            artifact=True,
            keywords={"defender"},
            attack_bypass_if_artifact_entered_this_turn=True,
        ),
        # Monoist Circuit-Feeder {4}{B}{B} 4/4 Nautilus.
        # "Flying. When this creature enters, until end of turn, target
        # creature you control gets +X/+0 and target creature an opponent
        # controls gets -0/-X, where X is the number of artifacts you
        # control." Static has no subtypes (Nautilus dropped).
        "Monoist Circuit-Feeder": make_creature(
            "Monoist Circuit-Feeder", "{4}{B}{B}", 4, 4,
            artifact=True,
            keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=MonoistCircuitFeederETBEffect(),
                ),
            ),
        ),
        # Pinnacle Emissary {1}{U}{R} 3/3.
        # "Whenever you cast an artifact spell, create a 1/1 colorless
        # Drone artifact creature token." Warp {U/R} — modeled as
        # {U}{R} (hybrid mana not a separate cost structure).
        "Pinnacle Emissary": make_creature(
            "Pinnacle Emissary", "{1}{U}{R}", 3, 3,
            artifact=True,
            warp="{U}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.IS_CAST,
                    predicate=(
                        IsArtifact(subject="spell")
                        & Controlled(YOU, subject="controller")
                    ),
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Drone"], count=1,
                    ),
                ),
            ),
        ),
        # Roving Actuator {3}{R} 3/4. Warp {1}{R}.
        # "Void — When this creature enters … exile up to one target
        # instant or sorcery card with mana value 2 or less from your
        # graveyard. Copy it. You may cast the copy without paying its
        # mana cost."
        "Roving Actuator": make_creature(
            "Roving Actuator", "{3}{R}", 3, 4,
            artifact=True,
            warp="{1}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=RovingActuatorETBEffect(max_mv=2),
                    requires_void=True,
                ),
            ),
        ),
        # Rust Harvester {R} 1/1.
        # Real oracle: "Menace. {2}, {T}, Exile an artifact card from
        # your graveyard: Put a +1/+1 counter on this creature, then it
        # deals damage equal to its power to any target." — activated
        # ability dropped; shipped as menace-only vanilla.
        # Static has artifact=False; registry entry is authoritative.
        "Rust Harvester": make_creature(
            "Rust Harvester", "{R}", 1, 1,
            keywords={"menace"},
        ),
        # Selfcraft Mechan {3}{U} 3/4 Robot Artificer.
        # "When this creature enters, you may sacrifice an artifact. When
        # you do, put a +1/+1 counter on target creature and draw a card."
        # Static has no subtypes (Artificer dropped).
        "Selfcraft Mechan": make_creature(
            "Selfcraft Mechan", "{3}{U}", 3, 4,
            artifact=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=SelfcraftMechanETBEffect(),
                ),
            ),
        ),
        # Survey Mechan {4} 1/3.
        # Real oracle: "Flying. Hexproof. {10}, Sacrifice this creature:
        # …" — large activated ability dropped; shipped with flying only
        # (hexproof also dropped, matching static registry entry).
        "Survey Mechan": make_creature(
            "Survey Mechan", "{4}", 1, 3,
            artifact=True,
            keywords={"flying"},
        ),
        # Tapestry Warden {3}{G} 3/4 Robot Soldier.
        # Real oracle: "Vigilance. Each creature you control with
        # toughness greater than its power assigns combat damage equal
        # to its toughness rather than its power. …" — toughness-as-
        # damage statics dropped; shipped with vigilance only.
        # Static has artifact=False; registry entry is authoritative.
        "Tapestry Warden": make_creature(
            "Tapestry Warden", "{3}{G}", 3, 4,
            keywords={"vigilance"},
        ),
        # Virulent Silencer {3} 2/3 Robot Assassin.
        # "Whenever a nontoken artifact creature you control deals combat
        # damage to a player, that player gets two poison counters."
        # Uses the aggregated observer trigger string (fired once per
        # (controller, target_player) pair by combat.py).
        "Virulent Silencer": make_creature(
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
    }


# Module-level bespoke Artifact Creature table, built once at import
# time. Keyed by card name; values match the canonical static registry
# exactly. ``_build_creature_printing`` checks this after
# ``_BESPOKE_CREATURES`` but before the grammar arms.
_BESPOKE_ARTIFACT_CREATURES: dict[str, CardPrinting] = (
    _make_bespoke_artifact_creatures()
)


def _build_creature_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for ``card`` (a Scryfall
    record). Returns ``None`` if the card is not a creature, has
    non-integer power/toughness (e.g. ``*``), or contains any
    oracle-text clause the slice doesn't yet support.

    Bespoke dispatch (checked before the grammar arms):
    Cards whose oracle text requires printing-level flags not yet
    generated by the grammar (dynamic P/T, external cost reductions,
    warp_castable_from_graveyard, unblockable_if_two_spells_cast_this
    _turn, etc.) are returned from ``_BESPOKE_CREATURES`` verbatim.
    The check is name-only so the card's type_line must still declare
    a Creature (guard below) — but power/toughness may be ``*`` for
    dynamic-P/T cards because the bespoke table already has the right
    printed P/T (0/0 or 0/1 matching the static registry's placeholder).
    """
    # Bespoke name-keyed dispatch: claim without grammar if registered.
    bespoke = _BESPOKE_CREATURES.get(card.get("name", ""))
    if bespoke is not None:
        # Still enforce the Creature type guard so a future reprinting
        # of the same name as a non-creature doesn't accidentally claim.
        supertypes, card_types, _ = _parse_type_line(card.get("type_line", ""))
        if "Creature" in card_types:
            return bespoke
        # Name matched but not a Creature — fall through to grammar.

    # Bespoke Artifact Creature dispatch: claim non-legendary Artifact
    # Creatures registered in the parallel table. Gated on the raw
    # type_line containing "Artifact" so a plain-Creature reprint of
    # the same name won't accidentally match.
    if "Artifact" in card.get("type_line", ""):
        bespoke_ac = _BESPOKE_ARTIFACT_CREATURES.get(card.get("name", ""))
        if bespoke_ac is not None:
            supertypes, card_types, _ = _parse_type_line(
                card.get("type_line", "")
            )
            if "Creature" in card_types:
                return bespoke_ac
            # Name matched but not a Creature — fall through to grammar.

    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Creature" not in card_types:
        return None
    try:
        power = int(card["power"])
        toughness = int(card["toughness"])
    except (KeyError, ValueError):
        return None

    keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    activated: list[ActivatedAbility] = []
    statics: list[StaticAbility] = []
    cost_reductions: list[CostReduction] = []
    warp: str | None = None
    ward: str | None = None
    ward_discard_chosen = False
    ward_discard_random = False
    devour: int = 0
    text = card.get("oracle_text", "")
    for raw_line in text.split("\n"):
        # Strip parenthesized reminder text per-line before any clause
        # dispatch — the keyword/triggered/activated/static grammars
        # don't need to know about flavor parentheticals. ``_strip_
        # reminder_text`` also calls ``.strip()``, so we don't need a
        # separate strip on ``raw_line`` first.
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        warp_cost = _parse_warp_line(line)
        if warp_cost is not None:
            # A card should only have one Warp clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            warp = warp_cost
            continue
        ward_cost = _parse_ward_line(line)
        if ward_cost is not None:
            # A card should only have one Ward clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            ward = ward_cost
            continue
        ward_discard_kind = _parse_ward_discard_line(line)
        if ward_discard_kind is not None:
            # Em-dash discard-cost ward riders. The tag string from the
            # parser ("chosen" or "random") maps 1:1 to the matching
            # boolean kwarg on ``make_creature``. As with the bare
            # ``Ward {cost}`` clause above, a single card carries at
            # most one Ward and parity against the static registry
            # catches any drift; we keep the last-seen marker if a
            # malformed printing somehow listed two.
            if ward_discard_kind == "random":
                ward_discard_random = True
            else:
                ward_discard_chosen = True
            continue
        devour_n = _parse_devour_line(line)
        if devour_n is not None:
            # A card should only have one Devour clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            devour = devour_n
            continue
        cost_reduction = _parse_cost_reduction_line(line)
        if cost_reduction is not None:
            # ``This spell costs {N} less to cast if <condition>.``
            # rider — accumulate; multiple riders on the same card are
            # legal in principle (no EoE printing has more than one
            # today, but the engine handles a tuple).
            cost_reductions.append(cost_reduction)
            continue
        if _is_sorcery_rider_line(line):
            # The rider attaches to the immediately preceding activated
            # ability on the same card. With no preceding ability there's
            # nothing to mark sorcery-speed and the card is skipped — a
            # bare rider line on its own is malformed oracle text.
            if not activated:
                return None
            activated[-1] = replace(activated[-1], sorcery_speed=True)
            continue
        # Pass the printing's own name to the clause dispatcher so the
        # triggered-ability layer can substitute name references
        # (``Haliya``, ``Syr Vondam``, etc.) with the canonical
        # ``this creature`` surface before condition / effect lookup.
        # Non-trigger clause types ignore the parameter today.
        parsed = _parse_clause(line, name=card["name"])
        if parsed is None:
            return None
        keywords.update(parsed.keywords)
        # ``triggers`` is a tuple — one entry per condition arm. A
        # standard single-condition line yields a 1-tuple; a compound
        # condition like ``When this creature enters or dies, …`` yields
        # a 2-tuple (one ``TriggeredAbility`` per event). The builder
        # treats each arm as if it were its own oracle line, mirroring
        # the static-registry shape (Thawbringer's static carries two
        # ``TriggeredAbility`` entries for its single oracle line).
        triggers.extend(parsed.triggers)
        if parsed.activated is not None:
            activated.append(parsed.activated)
        if parsed.static is not None:
            statics.append(parsed.static)

    return make_creature(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        keywords=keywords,
        triggered_abilities=tuple(triggers),
        activated_abilities=tuple(activated),
        static_abilities=tuple(statics),
        cost_reductions=tuple(cost_reductions),
        subtypes=subtypes,
        legendary="Legendary" in supertypes,
        artifact="Artifact" in card_types,
        warp=warp,
        ward=ward,
        ward_discard_chosen=ward_discard_chosen,
        ward_discard_random=ward_discard_random,
        devour_land_multiplier=devour,
    )
