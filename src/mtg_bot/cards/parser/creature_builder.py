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

Legendary Creatures (including legendary Artifact Creatures like
Dyadrine) are claimed via a third parallel table
``_BESPOKE_LEGENDARY_CREATURES``, checked after
``_BESPOKE_ARTIFACT_CREATURES`` but before the grammar arms. The lookup
is gated on both ``"Legendary"`` in supertypes and ``"Creature"`` in
card_types to avoid accidentally claiming non-creature legendary
permanents.
"""

from __future__ import annotations

import re
from dataclasses import replace

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    AlpharaelDreamingAcolyteDiscardEffect,
    AnticausalVestigeLeavesEffect,
    ArabellaAttackEffect,
    AstelliReclaimerETBEffect,
    AttackInTheBoxAttackEffect,
    BoilerbilgesRipperETBEffect,
    CardPrinting,
    ConditionalIfSourcePowerAtLeast,
    CostReduction,
    DealDamageEachOpponent,
    DealDamageEqualToSourcePowerAnyTarget,
    DiscardSelf,
    DestroyTargetNonlandPermanent,
    DrawCards,
    DyadrineAttackEffect,
    ExileTargetCreatureUntilSourceLeaves,
    ExternalCostReduction,
    FamishedWorldsireETBEffect,
    FanaticOfTheHarrowingETBEffect,
    GainLife,
    HouseCartographerSurvivalEffect,
    IfGainedLifeThisTurnUntapSelf,
    KavaronHarrierAttackEffect,
    ModalChooseOne,
    MonoistCircuitFeederETBEffect,
    MoveSelfCountersToTargetCreatureYouControl,
    OsseousSticktwisterEndStepEffect,
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
    PerigeeBeckonerDiesReturnTappedEffect,
    PossibilityTechnicianETBEffect,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnSelf,
    PutPoisonCountersOnTargetPlayer,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    RovingActuatorETBEffect,
    SearchLibraryForCard,
    SelfcraftMechanETBEffect,
    SelfMill,
    Sequence,
    SplitskinDollETBEffect,
    WickerfolkThresherAttackEffect,
    StaticAbility,
    StaticScope,
    TannukEnsignLandfallEffect,
    TerrapactIntimidatorETBEffect,
    TerritorialBruntarLandfallEffect,
    TriggeredAbility,
    cost,
    make_creature,
    parse_mana_cost,
)
from mtg_bot.cards.parser.activated import _is_sorcery_rider_line
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.cost_reduction import (
    _parse_cost_reduction_line,
    _parse_external_cost_reduction_line,
)
from mtg_bot.cards.parser.printing_keywords import (
    _parse_additional_land_per_turn_line,
    _parse_attack_bypass_if_artifact_entered_line,
    _parse_combat_damage_cant_be_prevented_line,
    _parse_creature_spells_uncounterable_line,
    _parse_devour_line,
    _parse_dynamic_pt_formula_line,
    _parse_enters_tapped_line,
    _parse_enters_with_minus_one_counters_from_hand_cast_line,
    _parse_enters_with_plus_one_counter_if_creature_died_line,
    _parse_enters_with_x_counters_line,
    _parse_extra_etb_trigger_line,
    _parse_impending_line,
    _parse_landcycling_line,
    _parse_must_be_blocked_line,
    _parse_nonbasic_lands_are_mountains_line,
    _parse_play_lands_from_graveyard_line,
    _parse_replaces_draw_when_hand_at_most_one_line,
    _parse_spell_cant_be_countered_line,
    _parse_token_doubler_line,
    _parse_toughness_as_damage_line,
    _parse_toughness_as_station_power_line,
    _parse_unblockable_if_two_spells_cast_this_turn_line,
    _parse_ward_discard_line,
    _parse_ward_line,
    _parse_warp_castable_from_graveyard_line,
    _parse_warp_line,
    _parse_warp_with_life_cost_line,
)
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.triggers import (
    _parse_predicate_trigger_phrase,
    _substitute_self_name,
    _strip_ability_word_prefix,
)
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.effects.object_predicates import (
    HasSubtype,
    IsArtifact,
    IsCreature,
    IsLand,
    IsTapped,
)
from mtg_bot.effects.conditions import (
    AtLeastNSpellsCastThisTurn,
    ControlledArtifactEnteredThisTurn,
)
from mtg_bot.effects.modifiers import (
    ContinuousModifier,
    GrantKeyword,
    RemoveKeyword,
)
from mtg_bot.effects.state_predicates import (
    Delirium,
    SpellsCastThisTurn,
)
from mtg_bot.effects.predicates import (
    YOU,
    Always,
    Controlled,
    Event,
    IsSelf,
    Source,
    StateBound,
    Subject,
)


# ── Modal creature trigger support ────────────────────────────────────────
#
# A modal triggered ability on a creature prints as:
#   ``When/Whenever <condition>, choose one —``       ← trigger header
#   ``• <mode 1 sentence>.``                           ← mode line(s)
#   ``• <mode 2 sentence>.``
#
# The header line ends with ``, choose one —`` (em-dash U+2014);
# each mode line begins with ``• `` (bullet U+2022 + space).
# The creature-builder loop processes lines one at a time, so modal
# blocks are pre-grouped before the main dispatch runs.
#
# Modal mode bodies use spell-style normalization (strip trailing period,
# lowercase first letter) because each mode is a full printed sentence
# rather than the ``it deals …`` creature-trigger form.
_MODAL_CHOOSE_ONE_SUFFIX = ", choose one —"
_MODAL_MODE_PREFIX = "• "

# Trigger-header shape for a modal triggered ability. The leading
# ``When``/``Whenever`` and the trailing ``, choose one —`` are fixed;
# the condition body (group 1) is captured non-greedily.
_MODAL_TRIGGER_HEADER_RE = re.compile(
    r"^(?:When|Whenever) (.+?), choose one —$"
)


def _parse_modal_mode_phrase(raw_mode: str) -> "Effect | None":
    """Parse a modal mode line body into an ``Effect``.

    ``raw_mode`` is the stripped line after the ``• `` prefix — a full
    sentence with trailing period and uppercase initial letter (e.g.
    ``"Create two 1/1 white Human Soldier creature tokens."``). Applies
    spell-style normalization (strip period, lowercase first letter)
    before dispatching through the unified effect grammar.
    """
    phrase = raw_mode.strip()
    if phrase.endswith("."):
        phrase = phrase[:-1]
    if phrase and phrase[0].isupper():
        phrase = phrase[0].lower() + phrase[1:]
    return _parse_effect(phrase)


def _parse_modal_trigger_block(
    header: str,
    mode_lines: list[str],
    *,
    name: str | None = None,
) -> "TriggeredAbility | None":
    """Parse a modal trigger block (header + mode lines) into a single
    ``TriggeredAbility`` with a ``ModalChooseOne`` effect.

    ``header`` is the trigger-header line after stripping reminder text
    (e.g. ``"Whenever you cast your second spell each turn, choose one —"``).
    ``mode_lines`` are the subsequent ``• <mode>`` lines, also stripped.
    ``name`` is the card's own printed name (forwarded to trigger-phrase
    normalization, same as the regular trigger parser).

    Returns ``None`` if any piece fails to parse — the whole modal block
    is rejected rather than silently losing modes. Rejection propagates
    as a parse failure for the oracle clause, keeping the card unclaimed.
    """
    # Substitute self-name references and strip ability-word prefixes
    # on the header before matching the trigger condition — mirrors the
    # flow in ``_parse_triggered_ability_line`` for regular triggers.
    h = header
    if name is not None:
        h = _substitute_self_name(h, name)
    h = _strip_ability_word_prefix(h)
    m = _MODAL_TRIGGER_HEADER_RE.match(h)
    if m is None:
        return None
    condition = m.group(1)
    pred_match = _parse_predicate_trigger_phrase(condition)
    if pred_match is None:
        return None
    event, predicate = pred_match
    # Parse each mode body. At least two modes are required.
    if len(mode_lines) < 2:
        return None
    parsed_modes: list["Effect"] = []
    for raw in mode_lines:
        if not raw.startswith(_MODAL_MODE_PREFIX):
            return None
        body = raw[len(_MODAL_MODE_PREFIX):]
        eff = _parse_modal_mode_phrase(body)
        if eff is None:
            return None
        parsed_modes.append(eff)
    return TriggeredAbility(
        event=event,
        predicate=predicate,
        effect=ModalChooseOne(modes=tuple(parsed_modes)),
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
        # ── bespoke-creature-wave7 ─────────────────────────────────────
        # Lightstall Inquisitor {W} 2/1 Angel Wizard — vigilance.
        # SKIP (wave7): ETB clause "each opponent exiles a card from
        # their hand and may play that card for as long as it remains
        # exiled" requires engine support for "may play card exiled this
        # way" — an opponent-exiles-from-hand-and-grants-cast-from-exile
        # rider that has no grammar primitive and no engine model.
        # Only Vigilance is retained faithfully; the ETB body is dropped.
        "Lightstall Inquisitor": make_creature(
            "Lightstall Inquisitor", "{W}", 2, 1,
            keywords={"vigilance"},
        ),
        # Genemorph Imago {G}{U} 1/3 Insect Druid — flying.
        # SKIP (wave7): Landfall trigger sets base P/T to 3/3 UEOT
        # (or 6/6 if ≥6 lands) using a "has base power and toughness
        # N/N until end of turn" shape.  Neither ``ContinuousModifier``
        # nor any grammar effect primitive implements a base-PT-setter
        # UEOT; ``PowerToughnessBonus`` only adds a delta, not a floor.
        # Only Flying is retained; the Landfall ability is dropped.
        "Genemorph Imago": make_creature(
            "Genemorph Imago", "{G}{U}", 1, 3,
            keywords={"flying"},
        ),
        # Famished Worldsire {5}{G}{G}{G} 6/6 Leviathan. Ward {3}.
        # Devour land 3 (enters with 3× sacrificed lands as +1/+1
        # counters). ETB: look at top X cards (X = power), put land
        # cards onto battlefield tapped.
        "Famished Worldsire": make_creature(
            "Famished Worldsire", "{5}{G}{G}{G}", 6, 6,
            subtypes=("Leviathan",),
            ward="{3}",
            devour_land_multiplier=3,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=FamishedWorldsireETBEffect(),
                ),
            ),
        ),
        # Duskmourn Overlord cycle (Mistmoors, Floodpits, Boilerbilges)
        # migrated to the parameterized grammar (engine-impending):
        # - ``Impending N—{cost}`` parses via ``_parse_impending_line``
        #   and wires ``impending=`` / ``impending_count=`` on
        #   ``make_creature``.
        # - ``Enchantment`` in the type_line sets ``enchantment=True``
        #   via the ``"Enchantment" in card_types`` check in the builder.
        # - ``"Whenever this permanent enters or attacks, …"`` maps to
        #   the ``"this permanent enters or attacks"`` entry in
        #   ``_COMPOUND_PREDICATE_TRIGGER_PHRASES`` (triggers.py),
        #   producing one ENTERS+IsSelf and one ATTACKS+IsSelf
        #   ``TriggeredAbility``.
        # All three Overlords removed — the grammar claims them.
        # ── DSK creatures batch 7 ─────────────────────────────────────
    }


# Module-level bespoke table, built once at import time. Keyed by card
# name; values are the canonical ``CardPrinting`` matching the static
# registry exactly. ``_build_creature_printing`` checks this first.
_BESPOKE_CREATURES: dict[str, CardPrinting] = _make_bespoke_creatures()


def _make_bespoke_artifact_creatures() -> dict[str, CardPrinting]:
    """Build the name-keyed bespoke Artifact Creature table at import time.

    Migrated to the oracle-text grammar (removed from this table):
    - Pinnacle Emissary — hybrid-mana support landed in ``parse_mana_cost``;
      ``{U/R}`` warp cost now parses correctly.
    - Tapestry Warden — toughness-as-damage + toughness-as-station flags.
    - Virulent Silencer — predicate-dispatch poison trigger.
    - Gene Pollinator — ``{T}, Tap an untapped permanent you control``
      cost atoms both classified; mana-ability grammar claims the effect.
      Migrated in bespoke-creature-wave7.
    - Rust Harvester — ``{2}, {T}, Exile an artifact card from your
      graveyard`` cost classifies; compound ``, then `` effect
      ``PutPlusOneCounterOnSelf + DealDamageEqualToSourcePowerAnyTarget``
      now parses after adding ``(?:it )?`` prefix to the power-damage
      regex.  Migrated in bespoke-creature-wave7.

    Remaining entries (with ``# SKIP`` comments) have oracle-text
    mechanics not yet generated by the grammar (bespoke effect classes,
    unsupported token shapes, delayed-trigger primitives, or dynamic-X
    effects). Each entry has an inline comment explaining the specific
    blocker.

    ``_build_creature_printing`` checks this table after
    ``_BESPOKE_CREATURES`` but before the grammar arms, gated on
    ``"Artifact"`` appearing in the card's ``type_line``.
    """
    return {
        # Gene Pollinator {G} 1/2 Robot Insect.
        # Migrated to the oracle-text grammar (bespoke-creature-wave7).
        # The two-atom cost ``{T}, Tap an untapped permanent you control``
        # classifies correctly via ``_classify_cost_piece`` (both atoms
        # have dedicated entries) and the effect ``Add one mana of any
        # color`` parses via the existing mana-ability grammar.
        # The grammar round-trips the card end-to-end; removed from this
        # table so the oracle parser claims it directly.
        #
        # Kavaron Harrier {R} 2/1 Robot Soldier.
        # "Whenever this creature attacks, you may pay {2}. If you do,
        # create a 2/2 colorless Robot artifact creature token that's
        # tapped and attacking. Sacrifice that token at end of combat."
        # SKIP (wave7): ``_YOU_MAY_PAY_THEN_EFFECT`` exists and the token-
        # create shape ``create a tapped N/N <color> <type> token`` parses,
        # but the oracle phrase ``that's tapped and attacking`` (not just
        # ``tapped``) fails the ``_CREATE_CREATURE_TOKEN`` regex.  The
        # "Sacrifice that token at end of combat" sentence is a
        # delayed-trigger sac encoded in ``state.pending_end_of_combat_
        # sacrifices`` — no grammar primitive covers the delayed-sac shape.
        # Both gaps require grammar/engine additions before the grammar can
        # claim this card.
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
        # Monoist Circuit-Feeder {4}{B}{B} 4/4 Nautilus.
        # "Flying. When this creature enters, until end of turn, target
        # creature you control gets +X/+0 and target creature an opponent
        # controls gets -0/-X, where X is the number of artifacts you
        # control."
        # SKIP (wave7): The ETB body names two simultaneous targets with
        # opposite polarity (+X/-X) where X is the controller's artifact
        # count at resolve time.  The grammar's compound-effect splitter
        # rejects multi-target Sequences (``Sequence`` supports only one
        # targeting sub-effect) and there is no paired-target primitive.
        # Both gaps require new grammar/engine primitives; skip+document
        # until a second example with the same shape exists.
        # Subtypes: Nautilus is dropped (matching static registry).
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
        # Pinnacle Emissary {1}{U}{R} 3/3 Artifact Creature — migrated to
        # the oracle-text grammar. The warp cost "{U/R}" is now handled by
        # parse_mana_cost (hybrid mana support added in engine-hybrid-mana).
        # Roving Actuator {3}{R} 3/4. Warp {1}{R}.
        # "Void — When this creature enters, if a nonland permanent left
        # the battlefield this turn or a spell was warped this turn, exile
        # up to one target instant or sorcery card with mana value 2 or
        # less from your graveyard. Copy it. You may cast the copy without
        # paying its mana cost."
        # SKIP (wave7): The ETB body is exile-from-graveyard + copy +
        # free-cast — a three-part chain encoded in ``RovingActuatorETBEffect``.
        # This is NOT the exile-until-source-leaves shape (Oblivion Ring
        # pattern) supported by ``_EXILE_OPPONENTS_NONLAND_UNTIL_LEAVES``
        # and ``_EXILE_CREATURE_UNTIL_LEAVES``; the Void gate is correctly
        # recognized (``requires_void=True``) but the effect body has no
        # grammar primitive.  Requires a copy-from-graveyard-and-cast-free
        # effect primitive before the grammar can claim this card.
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
        # Rust Harvester {R} 1/1 Robot.
        # Migrated to the oracle-text grammar (bespoke-creature-wave7).
        # The three-atom cost ``{2}, {T}, Exile an artifact card from
        # your graveyard`` classifies correctly via ``_classify_cost_piece``
        # (all three atoms now have dedicated entries in ActivationCost).
        # The effect body ``put a +1/+1 counter on this creature, then it
        # deals damage equal to its power to any target`` splits at
        # ``, then `` into two primitives: ``PutPlusOneCounterOnSelf`` and
        # ``DealDamageEqualToSourcePowerAnyTarget``.  The
        # ``_DEAL_DAMAGE_EQUAL_TO_SOURCE_POWER_ANY_TARGET`` regex was
        # extended with a ``(?:it )?`` prefix so the pronoun-bearing
        # compound piece ``it deals damage equal to its power to any
        # target`` matches without the creature-trigger normalizer's
        # ``it ``-strip.  The ``Menace`` keyword line and the
        # activated-ability line both route through ``_parse_clause``
        # in the normal creature-builder loop.
        # Removed from this table so the grammar claims it directly.
        #
        # Selfcraft Mechan {3}{U} 3/4 Robot Artificer.
        # "When this creature enters, you may sacrifice an artifact. When
        # you do, put a +1/+1 counter on target creature and draw a card."
        # SKIP (wave7): The oracle shape is "you may sacrifice an artifact.
        # When you do, <effect>." — "sacrifice an artifact" (not "sacrifice
        # another creature or artifact") with a reflexive "When you do"
        # continuation.  The grammar has ``OptionalSacAnotherForEffect``
        # (shape: "you may sacrifice another creature or artifact. If you
        # do, <effect>") but Selfcraft Mechan uses a different sacrifice
        # object ("an artifact" = possibly self) and the continuation uses
        # "When you do" not "If you do".  Neither the sacrifice-object
        # shape nor the "When you do" reflexive trigger form has a grammar
        # recognizer today.  Requires a parameterized recognizer for the
        # "you may sacrifice <object>. When you do, <effect>" shape.
        # Subtypes: Artificer is dropped (matching static registry).
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
        # Skip — the activated-ability body is a three-part sequence
        # (deal 3 damage to any target, target player draws three cards,
        # gains 3 life) with an X-based cost-reduction rider; no grammar
        # primitive covers the compound activation body or its inline
        # X cost-reduction, and the static registry entry also drops
        # hexproof + the activation (registry is authoritative here).
        "Survey Mechan": make_creature(
            "Survey Mechan", "{4}", 1, 3,
            artifact=True,
            keywords={"flying"},
        ),
        # ── DSK artifacts batch 3 ─────────────────────────────────────
        # Splitskin Doll {1}{W} 2/1 Toy.
        # "When this creature enters, draw a card. Then discard a card
        # unless you control another creature with power 2 or less."
        # Bespoke single-effect ETB encoding the draw + conditional
        # discard. The "another creature with power 2 or less" gate is
        # source-relative (excludes the doll itself); since the doll is
        # printed 2/1 it would otherwise trivially satisfy its own
        # condition.
        # Skip — "discard a card unless you control another creature with
        # power 2 or less" is a source-relative conditional discard (the
        # gate excludes the source itself) not expressible by any grammar
        # effect primitive today; ``SplitskinDollETBEffect`` encodes both
        # halves with the correct exclusion logic.
        "Splitskin Doll": make_creature(
            "Splitskin Doll", "{1}{W}", 2, 1,
            artifact=True,
            subtypes=("Toy",),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=SplitskinDollETBEffect(),
                ),
            ),
        ),
        # Attack-in-the-Box {3} 2/4 Toy.
        # "Whenever this creature attacks, you may have it get +4/+0
        # until end of turn. If you do, sacrifice it at the beginning
        # of the next end step."
        # Bespoke attack trigger: agent.choose_yes_no gates the optional
        # +4/+0 UEOT pump and the schedule-self-sac delayed trigger.
        # Decline = silent no-op; accept = pump + delayed-trigger entry
        # keyed at the current turn (same shape Devastating Onslaught
        # uses for its haste-token end-step sacrifice).
        # Skip — "sacrifice it at the beginning of the next end step"
        # is a delayed triggered ability whose grammar-side expression
        # requires an ``OptionalPumpSelfThenScheduleSacUEOT``-style
        # compound primitive that doesn't exist; ``AttackInTheBoxAttack
        # Effect`` handles the yes/no gate + pump + ``SacrificeSource
        # Delayed`` scheduling in one bespoke step.
        "Attack-in-the-Box": make_creature(
            "Attack-in-the-Box", "{3}", 2, 4,
            artifact=True,
            subtypes=("Toy",),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=AttackInTheBoxAttackEffect(),
                ),
            ),
        ),
        # Osseous Sticktwister {1}{B} 2/2 Scarecrow. Lifelink.
        # "Delirium — At the beginning of your end step, if there are
        # four or more card types among cards in your graveyard, each
        # opponent may sacrifice a nonland permanent of their choice
        # or discard a card. Then this creature deals damage equal to
        # its power to each opponent who didn't sacrifice a permanent
        # or discard a card this way."
        # Lifelink rides the standard ``keywords`` kwarg; the Delirium
        # gate composes ``Controlled(YOU) & Delirium()`` onto the
        # end-step trigger, and the bespoke
        # ``OsseousSticktwisterEndStepEffect`` engine class encodes the
        # per-opponent three-mode choice (sac / discard / take damage).
        # Skip — the per-opponent "sac or discard, else take damage"
        # branching effect is encoded in ``OsseousSticktwisterEndStep
        # Effect``; no grammar primitive covers the per-player
        # mode-selection + conditional-damage-to-non-compliers shape.
        "Osseous Sticktwister": make_creature(
            "Osseous Sticktwister", "{1}{B}", 2, 2,
            artifact=True,
            subtypes=("Scarecrow",),
            keywords={"lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_END_STEP,
                    predicate=Controlled(YOU) & StateBound(Delirium()),
                    effect=OsseousSticktwisterEndStepEffect(),
                ),
            ),
        ),
        # Wickerfolk Thresher {3}{G} 5/4 Scarecrow.
        # "Delirium — Whenever this creature attacks, if there are four
        # or more card types among cards in your graveyard, look at the
        # top card of your library. If it's a land card, you may put it
        # onto the battlefield. If you don't put the card onto the
        # battlefield, put it into your hand."
        # The Delirium ability-word prefix carries no rules consequence
        # (CR 207.2c); the gate is enforced via a ``Delirium()`` predicate
        # AND-ed onto the base ``IsSelf()`` ATTACKS predicate, matching
        # the parser's intervening-if discipline (see
        # ``_INTERVENING_IF_PHRASES`` in triggers.py). The bespoke
        # ``WickerfolkThresherAttackEffect`` engine class encodes the
        # peek-and-may-put-on-battlefield-otherwise-hand body.
        # Skip — the "look at top card; if land, may put onto battlefield;
        # else put into hand" peek-and-branch body is encoded in
        # ``WickerfolkThresherAttackEffect``; no grammar effect primitive
        # covers the peek-top-card conditional-land-ramp shape today.
        "Wickerfolk Thresher": make_creature(
            "Wickerfolk Thresher", "{3}{G}", 5, 4,
            artifact=True,
            subtypes=("Scarecrow",),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ATTACKS,
                    predicate=IsSelf() & StateBound(Delirium()),
                    effect=WickerfolkThresherAttackEffect(),
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


def _make_bespoke_legendary_creatures() -> dict[str, CardPrinting]:
    """Build the name-keyed bespoke Legendary Creature table at import time.

    Originally covered all 10 legendary Creatures and 1 legendary
    Artifact Creature (Dyadrine) from the EoE main set.

    Migrated to the parameterized grammar (removed from this table):
    - Alpharael, Stonechosen — ward-discard-random + Void/intervening-if
      attack trigger with DefendingPlayerLosesHalfLifeRoundedUp effect.
    - Haliya, Guided by Light — "this creature or another creature or
      artifact you control enters" collapsed trigger + trailing-if-gained-
      life end-step body + Warp.

    Remaining entries have ``# SKIP`` comments explaining which oracle-
    text mechanic(s) block migration (bespoke engine classes, printing-
    level flags, legacy string-key triggers, or missing effect primitives).

    Each entry matches the canonical static registry printing exactly so
    parity tests pass. ``_build_creature_printing`` checks this table
    after ``_BESPOKE_CREATURES`` and ``_BESPOKE_ARTIFACT_CREATURES`` but
    before the grammar arms, gated on both ``"Legendary"`` in supertypes
    and ``"Creature"`` in card_types.
    """
    return {
        # Dyadrine, Synthesis Amalgam `{X}{G}{W}` 0/1 Legendary Artifact
        # Creature — Construct.
        # Trample. Enters with +1/+1 counters equal to mana spent (X +
        # generic + colored pips). Whenever you attack, may remove a
        # counter from each of two creatures → draw a card and create a
        # 2/2 Robot token.
        # SKIP: enters_with_counters_from_x="mana_spent" has no grammar
        # recognizer; DyadrineAttackEffect is a bespoke engine class with
        # no grammar primitive. Both require grammar/engine additions.
        "Dyadrine, Synthesis Amalgam": make_creature(
            "Dyadrine, Synthesis Amalgam", "{X}{G}{W}", 0, 1,
            artifact=True,
            legendary=True,
            subtypes=("Construct",),
            keywords={"trample"},
            enters_with_counters_from_x="mana_spent",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=DyadrineAttackEffect(),
                ),
            ),
        ),
        # Alpharael, Dreaming Acolyte `{1}{U}{B}` 2/3 Legendary Creature
        # — Human Cleric.
        # ETB: draw two cards, then discard two unless you discard an
        # artifact card. During your turn, has deathtouch.
        # SKIP: AlpharaelDreamingAcolyteDiscardEffect is a bespoke engine
        # class (draw 2 then conditional discard with artifact-exception).
        # The "During your turn, <source> has <keyword>." static shape
        # also has no recognizer. Both require grammar additions.
        "Alpharael, Dreaming Acolyte": make_creature(
            "Alpharael, Dreaming Acolyte", "{1}{U}{B}", 2, 3,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=Sequence(effects=(
                        DrawCards(amount=2),
                        AlpharaelDreamingAcolyteDiscardEffect(),
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
        # Alpharael, Stonechosen migrated to parameterized grammar:
        # Ward—discard-random parses via _parse_ward_discard_line;
        # Void — Whenever Alpharael attacks, if <void-gate>,
        # defending player loses half their life, rounded up.
        # parses via intervening-if + _DEFENDING_PLAYER_LOSES_HALF_LIFE
        # regex in effects.py.  Removed from this table so the grammar
        # path claims it.
        # Syr Vondam, Sunstar Exemplar `{W}{B}` 2/2 Legendary Creature —
        # Human Knight. Vigilance, menace.
        # Whenever another creature you control dies or is put into exile,
        # put a +1/+1 counter on Syr Vondam and you gain 1 life.
        # When Syr Vondam dies or is put into exile while its power is 4+,
        # destroy up to one target nonland permanent.
        # SKIP: Line 2 needs trigger phrase "another creature you control
        # dies or is put into exile" (LEAVES_BATTLEFIELD). Line 3 needs
        # intervening-while gate "its power is 4 or greater" (encoded as
        # ConditionalIfSourcePowerAtLeast effect wrapper, not a predicate)
        # and "destroy up to one target nonland permanent" (optional-target
        # effect). All three require grammar additions.
        "Syr Vondam, Sunstar Exemplar": make_creature(
            "Syr Vondam, Sunstar Exemplar", "{W}{B}", 2, 2,
            legendary=True,
            keywords={"vigilance", "menace"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.LEAVES_BATTLEFIELD,
                    predicate=Subject(None, IsCreature()) & Controlled(YOU) & ~IsSelf(),
                    effect=Sequence(effects=(
                        PutPlusOneCounterOnSelf(amount=1),
                        GainLife(amount=1),
                    )),
                ),
                TriggeredAbility(
                    event=Event.LEAVES_BATTLEFIELD, predicate=IsSelf(),
                    effect=ConditionalIfSourcePowerAtLeast(
                        effect=DestroyTargetNonlandPermanent(),
                        threshold=4,
                    ),
                ),
            ),
        ),
        # Haliya, Ascendant Cadet `{2}{G}{W}{W}` 3/3 Legendary Creature
        # — Human Soldier.
        # Whenever Haliya enters or attacks, put a +1/+1 counter on target
        # creature you control. Whenever one or more creatures you control
        # with +1/+1 counters deal combat damage to a player, draw a card.
        # SKIP: Line 2 uses the legacy string-key trigger
        # "your_counter_creature_combat_damage_to_player_aggregated" which
        # has a specialized aggregated fire path in combat.py and no
        # predicate-trigger grammar entry. Migrating requires promoting the
        # aggregated trigger to the predicate path.
        "Haliya, Ascendant Cadet": make_creature(
            "Haliya, Ascendant Cadet", "{2}{G}{W}{W}", 3, 3,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
                ),
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=PutPlusOneCounterOnCreatureYouControl(amount=1),
                ),
                TriggeredAbility(
                    trigger=(
                        "your_counter_creature_combat_damage_"
                        "to_player_aggregated"
                    ),
                    effect=DrawCards(amount=1),
                ),
            ),
        ),
        # Haliya, Guided by Light migrated to parameterized grammar:
        # Line 1 — "this creature or another creature or artifact you
        # control enters" maps to a new _COLLAPSED_PREDICATE_TRIGGER_PHRASES
        # entry; the predicate faithfully includes self (no ~IsSelf()),
        # which is correct per oracle text.
        # Line 2 — "At the beginning of your end step, draw a card if
        # you've gained 3 or more life this turn." parses via the new
        # trailing-if body handler in _parse_at_the_beginning_of_line.
        # Warp {W} parses via _parse_warp_line.
        # Removed from this table so the grammar path claims it.
        # Mm'menon, the Right Hand `{3}{U}{U}` 3/4 Legendary Creature —
        # Jellyfish Advisor. Flying.
        # You may cast artifact spells from the top of your library.
        # Artifacts you control have {T}: Add {U} (spend only to cast
        # spells from outside your hand).
        # SKIP: grants_cast_artifact_from_top_of_library and
        # grants_blue_mana_ability_to_your_artifacts are printing-level
        # flags with no grammar recognizer. "You may look at the top card
        # of your library any time." also has no static-line recognizer.
        # Requires new grammar for all three oracle lines.
        "Mm'menon, the Right Hand": make_creature(
            "Mm'menon, the Right Hand", "{3}{U}{U}", 3, 4,
            keywords={"flying"},
            legendary=True,
            grants_cast_artifact_from_top_of_library=True,
            grants_blue_mana_ability_to_your_artifacts=True,
        ),
        # Tannuk, Memorial Ensign `{1}{R}{G}` 2/4 Legendary Creature —
        # Kavu Pilot. Landfall — whenever a land you control enters,
        # Tannuk deals 1 damage to each opponent. If this is the second
        # time this ability has resolved this turn, draw a card.
        # SKIP: TannukEnsignLandfallEffect is a bespoke engine class that
        # tracks per-turn resolution count and draws on the second fire.
        # There is no grammar primitive for "if this is the second time
        # this ability has resolved this turn." Requires engine/grammar
        # additions for per-card resolution tracking.
        "Tannuk, Memorial Ensign": make_creature(
            "Tannuk, Memorial Ensign", "{1}{R}{G}", 2, 4,
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=Subject(None, IsLand()) & Controlled(YOU),
                    effect=TannukEnsignLandfallEffect(),
                ),
            ),
        ),
        # Tannuk, Steadfast Second `{2}{R}{R}` 3/5 Legendary Creature —
        # Kavu Pilot. Static: other creatures you control have haste.
        # Second oracle line: "Artifact cards and red creature cards in
        # your hand have warp {2}{R}."
        # SKIP: The second oracle line grants warp to cards in hand by
        # type — a printing-level effect with no grammar recognizer.
        # The grammar would fail on this line and reject the card.
        # Requires a new grammar recognizer for the hand-warp grant.
        "Tannuk, Steadfast Second": make_creature(
            "Tannuk, Steadfast Second", "{2}{R}{R}", 3, 5,
            legendary=True,
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                    granted_keywords=frozenset({"haste"}),
                ),
            ),
        ),
        # Ragost, Deft Gastronaut `{R}{W}` 2/2 Legendary Creature —
        # Lobster Citizen. Artifacts you control are also Foods and have
        # the Food sac ability. {1}, {T}, Sacrifice a Food: Ragost deals
        # 3 damage to each opponent. At beginning of each end step, if
        # you gained life this turn, untap Ragost.
        # SKIP: grants_food_to_your_artifacts and
        # grants_food_ability_to_your_artifacts are printing-level flags
        # with no grammar recognizer. The activated ability with
        # sacrifice_food cost and IfGainedLifeThisTurnUntapSelf also have
        # no grammar support. Requires new grammar for all oracle lines.
        "Ragost, Deft Gastronaut": make_creature(
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
                    event=Event.BEGINNING_OF_END_STEP, predicate=Always(),
                    effect=IfGainedLifeThisTurnUntapSelf(),
                ),
            ),
        ),
        # ── DSK artifacts batch 3 ─────────────────────────────────────
        # Arabella, Abandoned Doll {R}{W} 1/3 Legendary Artifact Creature
        # — Toy. "Whenever Arabella attacks, it deals X damage to each
        # opponent and you gain X life, where X is the number of
        # creatures you control with power 2 or less." Bespoke effect
        # computes X at resolve time via ``effective_power`` so pump and
        # counter-modifications are reflected.
        # SKIP: ArabellaAttackEffect is a bespoke engine class for X-scaled
        # damage+life-gain gated on a creature-count with power filter.
        # There is no grammar primitive for this shape. Requires a new
        # parameterized effect primitive.
        "Arabella, Abandoned Doll": make_creature(
            "Arabella, Abandoned Doll", "{R}{W}", 1, 3,
            artifact=True,
            legendary=True,
            subtypes=("Toy",),
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=ArabellaAttackEffect(),
                ),
            ),
        ),
    }


# Module-level bespoke Legendary Creature table, built once at import
# time. Keyed by card name; values match the canonical static registry
# exactly. ``_build_creature_printing`` checks this after
# ``_BESPOKE_CREATURES`` and ``_BESPOKE_ARTIFACT_CREATURES`` but before
# the grammar arms, gated on "Legendary" in supertypes AND "Creature" in
# card_types.
_BESPOKE_LEGENDARY_CREATURES: dict[str, CardPrinting] = (
    _make_bespoke_legendary_creatures()
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

    # Bespoke Legendary Creature dispatch: claim legendary creatures
    # (including legendary Artifact Creatures like Dyadrine) registered
    # in the parallel table. Gated on both "Legendary" appearing in the
    # raw type_line and "Creature" in the parsed card_types to avoid
    # accidentally claiming non-creature legendary permanents.
    if "Legendary" in card.get("type_line", ""):
        bespoke_lc = _BESPOKE_LEGENDARY_CREATURES.get(card.get("name", ""))
        if bespoke_lc is not None:
            supertypes, card_types, _ = _parse_type_line(
                card.get("type_line", "")
            )
            if "Legendary" in supertypes and "Creature" in card_types:
                return bespoke_lc
            # Name matched but guard failed — fall through to grammar.

    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Creature" not in card_types:
        return None

    # Pre-scan oracle text to detect dynamic P/T formulas before the
    # main line loop. A ``*``-based Scryfall power/toughness value is
    # only valid when the oracle text contains a known dynamic-PT line;
    # cards with ``*`` P/T but no such line (e.g. a vanilla ``*``-power
    # card whose formula isn't implemented yet) still return None.
    _raw_text = card.get("oracle_text", "")
    _has_dynamic_pt = any(
        _parse_dynamic_pt_formula_line(_strip_reminder_text(l))
        for l in _raw_text.split("\n")
        if _strip_reminder_text(l)
    )

    def _star_pt(val: str) -> int | None:
        """Return numeric base for a ``*``-based P/T string, else None.
        ``"*"`` → 0; ``"1+*"`` / ``"*+1"`` → 1; other offsets likewise.
        """
        import re as _re
        v = val.strip()
        if v == "*":
            return 0
        m = _re.match(r"^(\d+)\+\*$", v) or _re.match(r"^\*\+(\d+)$", v)
        return int(m.group(1)) if m else None

    try:
        power = int(card["power"])
    except (KeyError, ValueError):
        power = _star_pt(card.get("power", "")) if _has_dynamic_pt else None
        if power is None:
            return None
    try:
        toughness = int(card["toughness"])
    except (KeyError, ValueError):
        toughness = _star_pt(card.get("toughness", "")) if _has_dynamic_pt else None
        if toughness is None:
            return None

    keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    activated: list[ActivatedAbility] = []
    statics: list[StaticAbility] = []
    cost_reductions: list[CostReduction] = []
    external_cost_reductions: list[ExternalCostReduction] = []
    warp: str | None = None
    warp_additional_life_cost: int = 0
    warp_castable_from_graveyard: bool = False
    ward: str | None = None
    ward_discard_chosen = False
    ward_discard_random = False
    devour: int = 0
    impending: str | None = None
    impending_count: int = 0
    enchantment: bool = "Enchantment" in card_types
    enters_tapped = False
    must_be_blocked_if_able = False
    nonbasic_lands_are_mountains = False
    landcycling: tuple[str, str] | None = None
    enters_with_plus_one_counter_if_creature_died_this_turn = False
    enters_with_minus_one_counters_from_hand_cast = 0
    is_token_doubler = False
    extra_etb_trigger = 0
    replaces_draw_with_extra_when_hand_at_most_one = False
    dynamic_pt_formula: str | None = None
    enters_with_counters_from_x: str | None = None
    grants_additional_land_per_turn = 0
    grants_play_lands_from_graveyard = False
    spell_is_uncounterable = False
    combat_damage_cant_be_prevented = False
    grants_toughness_as_damage_for_creatures_you_control = False
    grants_toughness_as_station_power_for_creatures_you_control = False
    text = card.get("oracle_text", "")
    # Pre-process oracle lines into groups. Most lines become a 1-element
    # group ``(stripped_line,)``. A modal trigger block (header ending
    # with ``, choose one —`` followed by ``• <mode>`` lines) becomes a
    # 2-element group ``(header_line, [mode_line, ...])``. Pre-grouping
    # lets the main loop stay a simple ``for group in groups`` dispatch
    # without look-ahead, and modal groups are rejected as a unit if any
    # piece fails to parse (no partial progress).
    _raw_lines = [
        _strip_reminder_text(l)
        for l in text.split("\n")
        if _strip_reminder_text(l)
    ]
    _groups: list[tuple] = []
    _i = 0
    while _i < len(_raw_lines):
        _ln = _raw_lines[_i]
        if _ln.endswith(_MODAL_CHOOSE_ONE_SUFFIX):
            # Modal trigger header — collect subsequent bullet mode lines.
            _modes: list[str] = []
            _j = _i + 1
            while _j < len(_raw_lines) and _raw_lines[_j].startswith(_MODAL_MODE_PREFIX):
                _modes.append(_raw_lines[_j])
                _j += 1
            if _modes:
                _groups.append((_ln, _modes))
                _i = _j
                continue
        _groups.append((_ln,))
        _i += 1
    for _group in _groups:
        # Unpack the group: single-element groups are normal lines;
        # two-element groups are modal trigger blocks.
        if len(_group) == 2:
            # Modal trigger block: ``(header, [mode_line, ...])``.
            # Delegate to ``_parse_modal_trigger_block``; append the
            # resulting ``TriggeredAbility`` to ``triggers``, or
            # return None if the block fails to parse.
            _header, _mode_lines = _group
            _modal_ta = _parse_modal_trigger_block(
                _header, _mode_lines, name=card["name"],
            )
            if _modal_ta is None:
                return None
            triggers.append(_modal_ta)
            continue
        line = _group[0]
        if not line:
            continue
        warp_life_result = _parse_warp_with_life_cost_line(line)
        if warp_life_result is not None:
            # ``Warp—{cost}, Pay N life.`` — em-dash warp with an
            # additional life cost (Timeline Culler). Sets both the
            # ``warp`` cost and ``warp_additional_life_cost``.
            warp, warp_additional_life_cost = warp_life_result
            continue
        warp_cost = _parse_warp_line(line)
        if warp_cost is not None:
            # A card should only have one Warp clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            warp = warp_cost
            continue
        if _parse_warp_castable_from_graveyard_line(line):
            # ``You may cast this card from your graveyard using its warp
            # ability.`` — Timeline Culler's graveyard-castability rider.
            # Flips the ``warp_castable_from_graveyard`` kwarg below.
            warp_castable_from_graveyard = True
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
        impending_result = _parse_impending_line(line)
        if impending_result is not None:
            # ``Impending N—{cost}`` — Duskmourn Overlord cycle alt-cost.
            # When cast for the impending cost the permanent enters with N
            # time counters and ``impending_active=True``, suppressing its
            # printed creature type (``is_creature_now`` returns False)
            # until the last counter is removed at the active player's end
            # step (``run_impending_decrement_turn_based_action``). A card
            # carries at most one Impending clause; if a malformed printing
            # somehow had two we keep the last — parity against the static
            # registry will catch drift.
            impending_count, impending = impending_result
            continue
        if _parse_enters_tapped_line(line):
            # ``This creature enters tapped.`` — printing-level static
            # replacement. Flips the ``enters_tapped`` kwarg below; the
            # engine already consults the printing's ``enters_tapped``
            # field at ETB. Idempotent: a hypothetical malformed
            # printing with the line twice still ends up with the
            # field set once.
            enters_tapped = True
            continue
        if _parse_enters_with_plus_one_counter_if_creature_died_line(line):
            # ``This creature enters with a +1/+1 counter on it if a
            # creature died this turn.`` — printing-level ETB
            # replacement. Flips the matching kwarg below; the engine
            # reads ``state.creatures_died_this_turn`` at ETB and adds
            # one +1/+1 counter when positive (Cackling Slasher).
            enters_with_plus_one_counter_if_creature_died_this_turn = True
            continue
        n_minus = _parse_enters_with_minus_one_counters_from_hand_cast_line(
            line,
        )
        if n_minus is not None:
            # ``This creature enters with N -1/-1 counters on it if you
            # cast it from your hand.`` — printing-level ETB
            # replacement. The cast-from-hand origin is tracked on the
            # GameObject via ``cast_via_hand`` set in
            # ``actions._cast_spell``'s cast-from-hand branch and
            # cleared on every other cast path; the engine adds N
            # -1/-1 counters at ETB only when the flag is set
            # (Patched Plaything).
            enters_with_minus_one_counters_from_hand_cast = n_minus
            continue
        if _parse_must_be_blocked_line(line):
            # ``This creature must be blocked if able.`` — printing-
            # level block requirement (CR 509.1c). Flips the
            # ``must_be_blocked_if_able`` kwarg below; the engine's
            # ``_declare_blockers`` enforces the requirement by
            # forcing a block when the defending player skipped it
            # but has an eligible blocker.
            must_be_blocked_if_able = True
            continue
        if _parse_nonbasic_lands_are_mountains_line(line):
            # ``Nonbasic lands are Mountains.`` — Magus of the Moon's
            # printing-level type-replacement static. Flips the
            # ``nonbasic_lands_are_mountains`` kwarg below; the engine
            # consumes the flag at land ETB and layer-4 type-
            # replacement application time. Idempotent: a malformed
            # printing with the line twice ends up with the field
            # set once.
            nonbasic_lands_are_mountains = True
            continue
        if _parse_token_doubler_line(line):
            # ``If one or more tokens would be created under your
            # control, twice that many of those tokens are created
            # instead.`` — Exalted Sunborn's printed token-doubler
            # replacement effect. Flips the ``is_token_doubler`` kwarg
            # below; the engine consumes the flag at create-token
            # resolution time and doubles the count. Idempotent: a
            # malformed printing with the line twice ends up with the
            # field set once.
            is_token_doubler = True
            continue
        if _parse_extra_etb_trigger_line(line):
            # ``If a permanent entering the battlefield causes a
            # triggered ability of a permanent you control to trigger,
            # that ability triggers an additional time.`` — Starfield
            # Vocalist's Panharmonicon-style ETB-trigger doubler.
            # Increments the ``extra_etb_trigger`` kwarg below; the
            # engine reads the controller's battlefield total at
            # trigger enqueue time and adds that many extra firings.
            # Accumulating rather than overwriting matches the
            # static-registry semantics — multiple copies on the same
            # printing would each contribute one extra firing (no card
            # in the pool today carries the line twice, but the int
            # field handles it).
            extra_etb_trigger += 1
            continue
        if _parse_replaces_draw_when_hand_at_most_one_line(line):
            # ``As long as you have one or fewer cards in hand, if you
            # would draw one or more cards, you draw that many cards
            # plus one instead.`` — Quantum Riddler's printed
            # draw-replacement static. Flips the
            # ``replaces_draw_with_extra_when_hand_at_most_one`` kwarg
            # below; the engine consumes the flag at draw resolution
            # time and adds one extra card when the controller's hand
            # is at most one card. Idempotent: a malformed printing
            # with the line twice ends up with the field set once.
            replaces_draw_with_extra_when_hand_at_most_one = True
            continue
        if _parse_attack_bypass_if_artifact_entered_line(line):
            # ``As long as an artifact entered the battlefield under
            # your control this turn, this creature can attack as
            # though it didn't have defender.`` — Mechan Shieldmate's
            # printed defender-bypass. Expressed as a SELF-scope
            # StaticAbility carrying a ContinuousModifier that removes
            # "defender" from this creature while
            # ControlledArtifactEnteredThisTurn() holds.
            # effective_keywords then returns a set without "defender"
            # and eligible_attackers' defender check passes naturally.
            statics.append(StaticAbility(
                scope=StaticScope.SELF,
                condition=ControlledArtifactEnteredThisTurn(),
                continuous_effect=ContinuousModifier(
                    layer=6,
                    payload=RemoveKeyword("defender"),
                ),
            ))
            continue
        if _parse_unblockable_if_two_spells_cast_this_turn_line(line):
            # ``This creature can't be blocked if you've cast two or
            # more spells this turn.`` — Illvoi Infiltrator's printed
            # conditional-unblockable. Expressed as a SELF-scope
            # StaticAbility carrying a ContinuousModifier that grants
            # "unblockable" while AtLeastNSpellsCastThisTurn(2) holds.
            # combat.can_block checks "unblockable" in
            # effective_keywords(state, attacker) and rejects all
            # blocks; declare_blockers does the same safety check.
            statics.append(StaticAbility(
                scope=StaticScope.SELF,
                condition=AtLeastNSpellsCastThisTurn(2),
                continuous_effect=ContinuousModifier(
                    layer=6,
                    payload=GrantKeyword("unblockable"),
                ),
            ))
            continue
        dpt_key = _parse_dynamic_pt_formula_line(line)
        if dpt_key is not None:
            # Dynamic P/T formula line (e.g. Emissary Escort, Cosmogoyf,
            # Harmonious Grovestrider). The formula key is forwarded as
            # ``dynamic_pt_formula`` to ``make_creature``; ``game._dynamic_pt``
            # computes the actual P/T at query time. A card carries at most
            # one such clause; idempotent on the same key.
            dynamic_pt_formula = dpt_key
            continue
        if _parse_enters_with_x_counters_line(line):
            # ``This creature enters with X +1/+1 counters on it.``
            # Sets ``enters_with_counters_from_x="x"``; the engine reads
            # ``state.resolving_x_value`` at ETB and adds that many
            # +1/+1 counters (Broodguard Elite). Idempotent.
            enters_with_counters_from_x = "x"
            continue
        if _parse_additional_land_per_turn_line(line):
            # ``You may play an additional land on each of your turns.``
            # Increments the grant counter; a card with the line twice
            # (no current EoE printing) would grant two additional land
            # plays, matching the engine field's int semantics.
            grants_additional_land_per_turn += 1
            continue
        if _parse_play_lands_from_graveyard_line(line):
            # ``You may play lands from your graveyard.`` — Icetill
            # Explorer's graveyard land-play static. Idempotent.
            grants_play_lands_from_graveyard = True
            continue
        if _parse_spell_cant_be_countered_line(line):
            # ``This spell can't be countered.`` — printing-level immunity
            # to counter effects. Flips ``spell_is_uncounterable`` kwarg
            # below; ``CounterTargetSpell`` excludes spells with this flag
            # from its legal-target list and fizzles at resolve time.
            spell_is_uncounterable = True
            continue
        if _parse_creature_spells_uncounterable_line(line):
            # ``Creature spells you control can't be countered.`` —
            # static ability granting uncounterability to all creature
            # spells the controller casts while this permanent is on the
            # battlefield. Wired as a SELF-scope ``StaticAbility`` with
            # ``grants_creature_spells_uncounterable=True``; the flag is
            # checked in ``CounterTargetSpell`` against the spell
            # controller's battlefield.
            statics.append(StaticAbility(
                scope=StaticScope.SELF,
                grants_creature_spells_uncounterable=True,
            ))
            continue
        if _parse_combat_damage_cant_be_prevented_line(line):
            # ``Combat damage can't be prevented.`` — printing-level
            # static causing this creature's damage events to bypass
            # global prevention (Darkness-style). Flips the
            # ``combat_damage_cant_be_prevented`` kwarg below; the engine
            # checks the flag per-source in
            # ``combat._source_bypasses_prevention``.
            combat_damage_cant_be_prevented = True
            continue
        if _parse_toughness_as_damage_line(line):
            # ``Each creature you control with toughness greater than its
            # power assigns combat damage equal to its toughness rather
            # than its power.`` — CR 510.1b replacement effect. Flips the
            # ``grants_toughness_as_damage_for_creatures_you_control``
            # kwarg below; the engine checks the flag per-controller in
            # ``combat._effective_combat_damage_amount``.
            grants_toughness_as_damage_for_creatures_you_control = True
            continue
        if _parse_toughness_as_station_power_line(line):
            # ``Each creature you control with toughness greater than its
            # power stations permanents using its toughness rather than
            # its power.`` — station-power replacement effect. Flips the
            # ``grants_toughness_as_station_power_for_creatures_you_control``
            # kwarg below; the engine checks the flag per-controller in
            # ``actions._station_spacecraft``.
            grants_toughness_as_station_power_for_creatures_you_control = True
            continue
        landcycling_match = _parse_landcycling_line(line)
        if landcycling_match is not None:
            # ``Plainscycling/Islandcycling/Swampcycling/Mountaincycling/
            # Forestcycling {cost}`` — basic-landcycling. Stored as
            # declarative metadata on the printing
            # (``CardPrinting.landcycling = (subtype, cost_str)``); the
            # activation pipeline isn't wired today, so the cycling
            # ability cannot be paid in simulation. The field is
            # populated honestly so the printing reflects oracle text;
            # claiming the card on the basis of this recognition keeps
            # parser parity with the printed oracle line. A card
            # carries at most one landcycling clause; if a malformed
            # printing somehow listed two we keep the last (matching
            # the Warp/Ward/Devour precedent above).
            landcycling = landcycling_match
            continue
        cost_reduction = _parse_cost_reduction_line(line)
        if cost_reduction is not None:
            # ``This spell costs {N} less to cast if <condition>.``
            # rider — accumulate; multiple riders on the same card are
            # legal in principle (no EoE printing has more than one
            # today, but the engine handles a tuple).
            cost_reductions.append(cost_reduction)
            continue
        external_cost_reduction = _parse_external_cost_reduction_line(line)
        if external_cost_reduction is not None:
            # Permanent-on-battlefield static that grants a flat cost
            # reduction to OTHER spells the controller casts (e.g.
            # Uthros Psionicist's ``The second spell you cast each turn
            # costs {2} less to cast.``). Accumulated; the engine's
            # ``apply_cost_reductions`` scans every ETB permanent for
            # these at cast time.
            external_cost_reductions.append(external_cost_reduction)
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
        external_cost_reductions=tuple(external_cost_reductions),
        subtypes=subtypes,
        legendary="Legendary" in supertypes,
        artifact="Artifact" in card_types,
        enchantment=enchantment,
        warp=warp,
        warp_additional_life_cost=warp_additional_life_cost,
        warp_castable_from_graveyard=warp_castable_from_graveyard,
        ward=ward,
        ward_discard_chosen=ward_discard_chosen,
        ward_discard_random=ward_discard_random,
        devour_land_multiplier=devour,
        impending=impending,
        impending_count=impending_count,
        enters_tapped=enters_tapped,
        must_be_blocked_if_able=must_be_blocked_if_able,
        landcycling=landcycling,
        enters_with_plus_one_counter_if_creature_died_this_turn=(
            enters_with_plus_one_counter_if_creature_died_this_turn
        ),
        enters_with_minus_one_counters_from_hand_cast=(
            enters_with_minus_one_counters_from_hand_cast
        ),
        nonbasic_lands_are_mountains=nonbasic_lands_are_mountains,
        is_token_doubler=is_token_doubler,
        extra_etb_trigger=extra_etb_trigger,
        replaces_draw_with_extra_when_hand_at_most_one=(
            replaces_draw_with_extra_when_hand_at_most_one
        ),
        dynamic_pt_formula=dynamic_pt_formula,
        enters_with_counters_from_x=enters_with_counters_from_x,
        grants_additional_land_per_turn=grants_additional_land_per_turn,
        grants_play_lands_from_graveyard=grants_play_lands_from_graveyard,
        spell_is_uncounterable=spell_is_uncounterable,
        combat_damage_cant_be_prevented=combat_damage_cant_be_prevented,
        grants_toughness_as_damage_for_creatures_you_control=(
            grants_toughness_as_damage_for_creatures_you_control
        ),
        grants_toughness_as_station_power_for_creatures_you_control=(
            grants_toughness_as_station_power_for_creatures_you_control
        ),
    )
