"""Enchantment card builders for Edge of Eternities + Duskmourn.

Two claim paths co-exist in this module:

1. **Name-keyed bespoke factories** (``_ENCHANTMENT_BUILDERS`` table) —
   exact-dispatch factories for enchantments whose oracle text cannot yet
   be expressed through the parameterized grammar (bespoke engine effects,
   multi-part statics not in the grammar, etc.).

2. **Oracle-text grammar paths** — parameterized parsers that walk oracle
   text line by line:
   - ``_build_aura_via_oracle_text`` for Enchantment — Aura cards
     (gated by ``_UNIFIED_AURA_NAMES``).
   - ``_build_enchantment_via_oracle_text`` for non-Aura enchantments
     (gated by ``_UNIFIED_ENCHANTMENT_NAMES``).

Cards still on the bespoke path (in ``_ENCHANTMENT_BUILDERS``):

Non-Aura enchantments:
- Loading Zone ``{3}{G}`` — is_counter_doubler + warp
- Weftwalking ``{4}{U}{U}`` — ETB body parses through the unified
  clause grammar via ``ConditionalIfCastFromHand`` wrapping a
  ``Sequence(ShuffleZonesIntoLibrary, DrawCards(7))``;
  ``grants_first_spell_each_turn_free`` rides the literal-static
  recognizer
- Sothera, the Supervoid ``{2}{B}{B}`` — bespoke DIES + end-step effects
- Terrasymbiosis ``{2}{G}`` — COUNTERS_ADDED trigger
- Bioengineered Future ``{1}{G}{G}`` — ETB token + grants_etb_counter_
  per_land_entered_this_turn
- Leyline of Mutation ``{2}{G}{G}`` — honest no-op

Aura enchantments:
- Chorale of the Void ``{3}{B}`` — bespoke attacks-trigger effect
  (ChoraleReanimateDefenderGraveCreatureEffect) and Void end-step rider
  (SacrificeSelfUnlessVoidActive); deferred until those effects land as
  grammar-level phrases.

Cards migrated to the Aura oracle-text path (``_UNIFIED_AURA_NAMES``):

EoE Auras (migrated in bespoke-enchantments wave 1):
- Cryoshatter ``{U}`` — -5/-0 + compound becomes-tapped-or-dealt-damage
- Hardlight Containment ``{W}`` — Enchant artifact + ETB exile + ward {1}
- Meltstrider's Resolve ``{G}`` — Enchant creature you control + ETB
  fights + +0/+2 + menace
- Moonlit Meditation ``{2}{U}`` — Enchant artifact or creature you control
  + token-replace static
- Pain for All ``{2}{R}`` — Enchant creature you control + ETB damage + echo
- Tractor Beam ``{2}{U}{U}`` — Enchant creature or Spacecraft + ETB tap
  + control + doesn't-untap

DSK Auras (migrated in bespoke-enchantments wave 1):
- Cracked Skull ``{2}{B}`` — ETB look-at-hand-may-discard + dealt-damage-
  destroy
- Duskmourn's Domination ``{4}{U}{U}`` — control + -3/-0 + lose-all
- Frantic Strength ``{2}{G}`` — Flash + +2/+2 + trample
- Shardmage's Rescue ``{W}`` — Flash + Enchant creature you control +
  conditional hexproof (honest no-op) + +1/+1
- Sheltered by Ghosts ``{1}{W}`` — Enchant creature you control + ETB
  exile nonland + +1/+0 + lifelink + ward {2}
- Sporogenic Infection ``{1}{B}`` — ETB sac-other-than-enchanted + dealt-
  damage-destroy
- Stay Hidden, Stay Silent ``{1}{U}`` — ETB tap-enchanted + doesn't-
  untap + activated ability (honest no-op)

Non-Aura cards already on the oracle-text path
(``_UNIFIED_ENCHANTMENT_NAMES``):
- Banishing Light, Seam Rip, Trapped in the Screen, Eusocial Engineering,
  Weapons Manufacturing, Deafening Silence, Burgeoning
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    CardPrinting,
    TriggeredAbility,
    make_aura,
    make_enchantment,
    parse_mana_cost,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects import (
    ChoraleReanimateDefenderGraveCreatureEffect,
    CreateToken,
    DestroyEnchantedPermanent,
    EnchantedCreatureFightsTargetEffect,
    ExileOpponentsNonlandPermanentUntilLeaves,
    ExileTargetCreatureUntilSourceLeaves,
    PainForAllDamageEchoEffect,
    PainForAllETBEffect,
    SacrificeSelfUnlessVoidActive,
    SotheraEndStepReanimateEffect,
    SotheraExileOpponentCreatureEffect,
    TapEnchantedPermanent,
    TargetOpponentLookHandMayDiscard,
    TargetOpponentSacrificesCreatureOtherThanEnchanted,
    TractorBeamETBEffect,
)
from mtg_bot.effects.object_predicates import (
    IsArtifact,
    IsCreature,
    IsLand,
    IsNontoken,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsHost,
    IsSelf,
    Subject,
)
from mtg_bot.cards.parser.printing_keywords import (
    _parse_restricts_noncreature_spells_line,
    _parse_ward_line,
    _parse_warp_line,
)
from mtg_bot.cards.parser.keywords import _parse_keyword_line
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line


# ---------------------------------------------------------------------------
# Non-Aura enchantment factories
# ---------------------------------------------------------------------------

def _build_banishing_light() -> CardPrinting:
    return make_enchantment(
        "Banishing Light", "{2}{W}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=ExileOpponentsNonlandPermanentUntilLeaves(),
            ),
        ),
    )


def _build_seam_rip() -> CardPrinting:
    return make_enchantment(
        "Seam Rip", "{W}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=ExileOpponentsNonlandPermanentUntilLeaves(max_mv=2),
            ),
        ),
    )


def _build_loading_zone() -> CardPrinting:
    return make_enchantment(
        "Loading Zone", "{3}{G}",
        warp="{G}",
        is_counter_doubler=True,
    )


def _build_sothera_the_supervoid() -> CardPrinting:
    return make_enchantment(
        "Sothera, the Supervoid", "{2}{B}{B}",
        legendary=True,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.DIES,
                predicate=Subject(None, IsCreature()) & Controlled(YOU),
                effect=SotheraExileOpponentCreatureEffect(),
            ),
            TriggeredAbility(
                event=Event.BEGINNING_OF_END_STEP, predicate=Controlled(YOU),
                effect=SotheraEndStepReanimateEffect(),
            ),
        ),
    )


def _build_weapons_manufacturing() -> CardPrinting:
    return make_enchantment(
        "Weapons Manufacturing", "{1}{R}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=Subject(None, IsArtifact() & IsNontoken()) & Controlled(YOU) & ~IsSelf(),
                effect=CreateToken(
                    token_printing=TOKEN_PRINTINGS["Munitions"],
                    count=1,
                ),
            ),
        ),
    )


def _build_bioengineered_future() -> CardPrinting:
    return make_enchantment(
        "Bioengineered Future", "{1}{G}{G}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=CreateToken(
                    token_printing=TOKEN_PRINTINGS["Lander"],
                    count=1,
                ),
            ),
        ),
        grants_etb_counter_per_land_entered_this_turn=True,
    )


def _build_eusocial_engineering() -> CardPrinting:
    return make_enchantment(
        "Eusocial Engineering", "{3}{G}{G}",
        warp="{1}{G}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=Subject(None, IsLand()) & Controlled(YOU),
                effect=CreateToken(
                    token_printing=TOKEN_PRINTINGS["Robot"],
                    count=1,
                ),
            ),
        ),
    )


def _build_leyline_of_mutation() -> CardPrinting:
    """Leyline of Mutation ``{2}{G}{G}``: Enchantment.

    Oracle text:
        If this card is in your opening hand, you may begin the game
        with it on the battlefield.
        You may pay {W}{U}{B}{R}{G} rather than pay the mana cost for
        spells you cast.

    Honest no-op claim. Both printed lines are inert in this engine
    today:

    - The ``opening hand`` replacement (start-of-game-on-battlefield
      Leyline mechanic) isn't modeled — every Leyline starts the game
      in the controller's library / hand like any other card.
    - The ``You may pay {W}{U}{B}{R}{G} rather than pay the mana
      cost`` alt cost isn't offered by ``legal.py``'s cast pipeline
      today, so the controller is never given the option. Same
      permission-not-offered shape Lecture Hall's ``Other permanents
      you control have hexproof`` ships per dsk-rooms-batch6 — the
      static stays in place as a no-op until the engine wires the
      enabling check.

    The card therefore sits on the battlefield doing nothing, which
    is the rules-correct observable behaviour given that neither of
    its two surface clauses is wired through. Cost-and-name-only
    factory.
    """
    return make_enchantment(
        "Leyline of Mutation", "{2}{G}{G}",
    )


def _build_trapped_in_the_screen() -> CardPrinting:
    """Trapped in the Screen ``{2}{W}``: Enchantment.

    Oracle text:
        Ward {2}
        When this enchantment enters, exile target artifact, creature,
        or enchantment an opponent controls until this enchantment
        leaves the battlefield.

    Routes through the new ``ward`` kwarg on ``make_enchantment`` —
    which threads the printed cost onto the enchantment's own
    ``ward_cost`` / ``ward_cost_str`` fields, the same fields a
    creature with Ward already populates. The ETB rides the existing
    ``ExileOpponentsNonlandPermanentUntilLeaves`` engine class —
    ``artifact, creature, or enchantment`` an opponent controls is
    functionally equivalent to ``nonland permanent`` for the EoE/DSK
    pool (planeswalkers aren't fully modeled and lands are excluded
    either way), the same simplification Banishing Light's ETB
    already uses.
    """
    return make_enchantment(
        "Trapped in the Screen", "{2}{W}",
        ward="{2}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=ExileOpponentsNonlandPermanentUntilLeaves(),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Aura enchantment factories
# ---------------------------------------------------------------------------

def _build_moonlit_meditation() -> CardPrinting:
    return make_aura(
        "Moonlit Meditation", "{2}{U}",
        replaces_first_tokens_with_copies=True,
    )


def _build_tractor_beam() -> CardPrinting:
    return make_aura(
        "Tractor Beam", "{2}{U}{U}",
        attached_prevents_untap=True,
        attached_grants_control=True,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=TractorBeamETBEffect(),
            ),
        ),
    )


def _build_chorale_of_the_void() -> CardPrinting:
    return make_aura(
        "Chorale of the Void", "{3}{B}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ATTACKS, predicate=IsHost(subject="attacker"),
                effect=ChoraleReanimateDefenderGraveCreatureEffect(),
            ),
            TriggeredAbility(
                event=Event.BEGINNING_OF_END_STEP, predicate=Controlled(YOU),
                effect=SacrificeSelfUnlessVoidActive(),
            ),
        ),
    )


def _build_cryoshatter() -> CardPrinting:
    return make_aura(
        "Cryoshatter", "{U}",
        power_bonus=-5, toughness_bonus=0,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.BECOMES_TAPPED, predicate=IsHost(),
                effect=DestroyEnchantedPermanent(),
            ),
            TriggeredAbility(
                event=Event.DEALT_DAMAGE, predicate=IsHost(),
                effect=DestroyEnchantedPermanent(),
            ),
        ),
    )


def _build_meltstriders_resolve() -> CardPrinting:
    return make_aura(
        "Meltstrider's Resolve", "{G}",
        power_bonus=0, toughness_bonus=2,
        granted_keywords=frozenset({"menace"}),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=EnchantedCreatureFightsTargetEffect(),
            ),
        ),
    )


def _build_hardlight_containment() -> CardPrinting:
    return make_aura(
        "Hardlight Containment", "{W}",
        aura_enchant_type="artifact",
        power_bonus=0, toughness_bonus=0,
        granted_keywords=frozenset(),
        attached_grants_ward="{1}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=ExileTargetCreatureUntilSourceLeaves(
                    opponents_only=True,
                ),
            ),
        ),
    )


def _build_pain_for_all() -> CardPrinting:
    """Pain for All: Enchantment — Aura. No P/T bonus. Two triggers:
    - ETB: enchanted creature deals damage equal to its power to any
      other target (``PainForAllETBEffect``).
    - Whenever enchanted creature is dealt damage, it deals that much
      damage to each opponent (``PainForAllDamageEchoEffect``).
    """
    return make_aura(
        "Pain for All", "{2}{R}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=PainForAllETBEffect(),
            ),
            TriggeredAbility(
                event=Event.DEALT_DAMAGE, predicate=IsHost(),
                effect=PainForAllDamageEchoEffect(),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Duskmourn (DSK) Aura factories
# ---------------------------------------------------------------------------

def _build_frantic_strength() -> CardPrinting:
    """Frantic Strength ``{1}{R}``: Enchantment — Aura.

    Oracle text:
        Flash
        Enchant creature
        Enchanted creature gets +2/+2 and has trample.

    Maps onto the existing ``make_aura`` flag set with the new
    ``keywords`` kwarg carrying Flash on the Aura itself:
    - ``keywords=frozenset({"flash"})`` for instant-speed casting (the
      ``CardPrinting.keywords`` field is what ``legal.py`` reads to
      surface a permanent spell at instant speed).
    - ``power_bonus=2, toughness_bonus=2`` and
      ``granted_keywords=frozenset({"trample"})`` for the static
      ``Enchanted creature gets +2/+2 and has trample.`` rider —
      same shared ``equipment_bonuses`` machinery the rest of the
      EoE/DSK Auras already ride.

    No new engine fields are needed: Flash on permanents already
    gates instant-speed casting via the existing
    ``"flash" in printing.keywords`` check, the pump and granted
    keyword ride the existing aura-attached effective-PT layer.
    """
    return make_aura(
        "Frantic Strength", "{1}{R}",
        power_bonus=2, toughness_bonus=2,
        granted_keywords=frozenset({"trample"}),
        keywords=frozenset({"flash"}),
    )


def _build_sheltered_by_ghosts() -> CardPrinting:
    """Sheltered by Ghosts ``{1}{W}``: Enchantment — Aura.

    Oracle text:
        Enchant creature you control
        When this Aura enters, exile target nonland permanent an
        opponent controls until this Aura leaves the battlefield.
        Enchanted creature gets +1/+0 and has lifelink and ward {2}.

    Composes three existing engine pieces against the new
    ``aura_yours_only`` flag (which restricts the cast-time target
    picker to creatures the caster controls — the printed
    "Enchant creature you control" line):

    - ``aura_yours_only=True`` for the controller-restricted enchant
      target. First DSK Aura that ships this restriction; the flag
      defaults to False so existing "Enchant creature" Auras keep
      their previous behavior.
    - ``ExileOpponentsNonlandPermanentUntilLeaves()`` ETB — same
      Banishing-Light-style exile-until-leaves shape. The
      ``max_mv=0`` default disables the optional MV cap (Sheltered
      doesn't have one).
    - ``power_bonus=1, toughness_bonus=0`` and
      ``granted_keywords=frozenset({"lifelink"})`` for the static
      ``Enchanted creature gets +1/+0 and has lifelink`` rider —
      shared ``equipment_bonuses`` machinery.
    - ``attached_grants_ward="{2}"`` for the ``ward {2}`` rider —
      same Hardlight-Containment-style ward grant, just with a
      stronger cost.

    No new engine effect classes are needed: the new
    ``aura_yours_only`` flag is the only engine plumbing this card
    requires.
    """
    return make_aura(
        "Sheltered by Ghosts", "{1}{W}",
        power_bonus=1, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
        aura_yours_only=True,
        attached_grants_ward="{2}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=ExileOpponentsNonlandPermanentUntilLeaves(),
            ),
        ),
    )


def _build_cracked_skull() -> CardPrinting:
    """Cracked Skull ``{2}{B}``: Enchantment — Aura.

    Oracle text:
        Enchant creature
        When this Aura enters, look at target player's hand. You may
        choose a nonland card from it. That player discards that card.
        When enchanted creature is dealt damage, destroy it.

    Composes two existing engine pieces against the new
    ``TargetOpponentLookHandMayDiscard`` ETB:

    - ``TargetOpponentLookHandMayDiscard()`` ETB — the new generic
      effect that honours the printed ``You may`` gate via
      ``Agent.choose_yes_no``. Opponent-only legality is the standard
      EoE / DSK ``target player`` simplification (the same convention
      ``TargetOpponentDiscardsCasterChoice`` already rides). Self-
      targeting is never strategically correct for the controller, so
      narrowing legality doesn't affect rational play.
    - ``DestroyEnchantedPermanent()`` on ``Event.DEALT_DAMAGE & IsHost()``
      — same Cryoshatter-style trigger that fires when the enchanted
      creature is dealt any damage and destroys it via the
      destroys-the-host primitive.
    """
    return make_aura(
        "Cracked Skull", "{2}{B}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=TargetOpponentLookHandMayDiscard(),
            ),
            TriggeredAbility(
                event=Event.DEALT_DAMAGE, predicate=IsHost(),
                effect=DestroyEnchantedPermanent(),
            ),
        ),
    )


def _build_stay_hidden_stay_silent() -> CardPrinting:
    """Stay Hidden, Stay Silent ``{1}{U}``: Enchantment — Aura.

    Oracle text:
        Enchant creature
        When this Aura enters, tap enchanted creature.
        Enchanted creature doesn't untap during its controller's
        untap step.
        {4}{U}{U}: Shuffle enchanted creature into its owner's
        library, then manifest dread. Activate only as a sorcery.

    Composes the new ``TapEnchantedPermanent`` ETB and the existing
    ``attached_prevents_untap`` static rider (Tractor Beam precedent):

    - ETB: ``TapEnchantedPermanent()`` — taps the host via
      ``mtg_bot.turn.tap_permanent``, idempotent if the host is
      already tapped.
    - Static: ``attached_prevents_untap=True`` for the printed
      ``doesn't untap during its controller's untap step`` clause —
      same flag Tractor Beam ships, gated by the engine's untap-step
      walk on every Aura attached to the host.

    Simplification — the activated ability ``{4}{U}{U}: Shuffle
    enchanted creature into its owner's library, then manifest
    dread. Activate only as a sorcery.`` is dropped as an honest
    no-op. The activated ability is OPTIONAL (the controller chooses
    whether to pay {4}{U}{U}), so not offering it through ``legal``
    means the controller misses the option but doesn't violate
    rules. Same permission-not-offered shape Lecture Hall ships per
    dsk-rooms-batch6, applied to an alt-cost activated ability
    rather than a static. The ETB tap and the don't-untap static are
    the load-bearing pieces of the printing — every game with this
    Aura on the battlefield has the host stuck-tapped indefinitely
    regardless of whether the activated ability is ever used.
    """
    return make_aura(
        "Stay Hidden, Stay Silent", "{1}{U}",
        attached_prevents_untap=True,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=TapEnchantedPermanent(),
            ),
        ),
    )


def _build_sporogenic_infection() -> CardPrinting:
    """Sporogenic Infection ``{1}{B}``: Enchantment — Aura.

    Oracle text:
        Enchant creature
        When this Aura enters, target player sacrifices a creature of
        their choice other than enchanted creature.
        When enchanted creature is dealt damage, destroy it.

    Composes the new ``TargetOpponentSacrificesCreatureOtherThan
    Enchanted`` ETB and the existing Cryoshatter-style
    DEALT_DAMAGE-destroys-host trigger:

    - ETB: ``TargetOpponentSacrificesCreatureOtherThanEnchanted()`` —
      identifies the host via ``state.resolving_source.attached_to``
      and excludes it from the target's sac options. The simplified
      ``target player`` -> ``target opponent`` legality narrowing is
      the same convention Cracked Skull's may-discard ETB rides.
    - DEALT_DAMAGE: ``DestroyEnchantedPermanent()`` keyed on
      ``IsHost()`` — same shape Cryoshatter's bottom trigger uses.
    """
    return make_aura(
        "Sporogenic Infection", "{1}{B}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=TargetOpponentSacrificesCreatureOtherThanEnchanted(),
            ),
            TriggeredAbility(
                event=Event.DEALT_DAMAGE, predicate=IsHost(),
                effect=DestroyEnchantedPermanent(),
            ),
        ),
    )


def _build_shardmages_rescue() -> CardPrinting:
    """Shardmage's Rescue ``{W}``: Enchantment — Aura.

    Oracle text:
        Flash
        Enchant creature you control
        As long as this Aura entered this turn, enchanted creature has
        hexproof.
        Enchanted creature gets +1/+1.

    Maps cleanly onto the existing ``make_aura`` flag set:

    - ``keywords=frozenset({"flash"})`` for the printed Flash on the
      Aura itself — same instant-speed gate Frantic Strength rides
      through ``CardPrinting.keywords`` and ``legal.py``.
    - ``aura_yours_only=True`` for the ``Enchant creature you control``
      target restriction — same flag Sheltered by Ghosts ships.
    - ``power_bonus=1, toughness_bonus=1`` for the unconditional
      ``Enchanted creature gets +1/+1`` rider — shared
      ``equipment_bonuses`` machinery.

    The conditional hexproof line (``As long as this Aura entered this
    turn, enchanted creature has hexproof``) is dropped as an honest
    no-op: hexproof is engine-unenforced metadata in this codebase
    today (no targeting site checks for it — same observation Lecture
    Hall's "other permanents you control have hexproof" rests on per
    the dsk-rooms-batch6 precedent). Since the unconditional grant
    would already be a no-op, the conditional ``as long as`` gated
    grant is just as much a no-op — not modelling the optional
    benefit makes the printing miss a defensive shield it never had
    anyway.
    """
    return make_aura(
        "Shardmage's Rescue", "{W}",
        power_bonus=1, toughness_bonus=1,
        keywords=frozenset({"flash"}),
        aura_yours_only=True,
    )


def _build_duskmourns_domination() -> CardPrinting:
    """Duskmourn's Domination ``{4}{U}{U}``: Enchantment — Aura.

    Oracle text:
        Enchant creature
        You control enchanted creature.
        Enchanted creature gets -3/-0 and loses all abilities.

    Maps onto the existing ``make_aura`` flag set:
    - ``attached_grants_control=True`` for the gain-control rider
      (Tractor Beam precedent: the EoE Aura that grants control of
      its enchanted creature).
    - ``attached_grants_lose_all_abilities=True`` for the lose-all-
      abilities rider (already wired on ``make_aura``; no DSK-
      specific engine field needed).
    - ``power_bonus=-3, toughness_bonus=0`` for the ``-3/-0``
      continuous bonus, routed through the shared
      ``equipment_bonuses`` machinery the same way Cryoshatter's
      ``-5/-0`` is.
    """
    return make_aura(
        "Duskmourn's Domination", "{4}{U}{U}",
        power_bonus=-3, toughness_bonus=0,
        attached_grants_control=True,
        attached_grants_lose_all_abilities=True,
    )


# ---------------------------------------------------------------------------
# Dispatch table: card name → factory
# ---------------------------------------------------------------------------

_ENCHANTMENT_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {
    # Non-Aura cards remaining on the bespoke path:
    #
    # (Sothera, the Supervoid migrated to oracle-text path via
    # _NONAURA_LITERAL_TRIGGER_LINES.)
    # (Terrasymbiosis migrated to oracle-text path via _NONAURA_LITERAL_
    # TRIGGER_LINES — see _UNIFIED_ENCHANTMENT_NAMES.)
    # (Chorale of the Void migrated to oracle-text path via _UNIFIED_AURA_NAMES
    # + _AURA_LITERAL_TRIGGER_LINES.)
}


# ---------------------------------------------------------------------------
# Aura oracle-text parser
# ---------------------------------------------------------------------------
#
# Each of the recognizers below handles ONE printed surface shape found on
# Aura oracle lines. They are tried in order by ``_build_aura_via_oracle_
# text``; any unrecognized line causes the card to be rejected (returns
# None) so the silent-skip discipline stays intact.
#
# ``"Enchant X"`` line → (aura_enchant_type, aura_yours_only) --------
#
# Four printed shapes in the EoE/DSK pool:
#
#   "Enchant creature"                       → ("creature", False)
#   "Enchant creature you control"           → ("creature", True)
#   "Enchant artifact you control"           → ("artifact", True)
#   "Enchant creature or Spacecraft"         → ("creature", False)
#      Simplified: Spacecraft are non-creature artifacts; the engine's
#      Aura cast-time target picker only has two branches ("artifact" or
#      "creature"), so we collapse Spacecraft into the creature branch.
#      No card in the pool casts this Aura onto a Spacecraft during play
#      in the current implementation, so the simplification is observable-
#      behavior-equivalent.
#   "Enchant artifact or creature you control" → ("creature", True)
#      Simplified to the creature branch for the same reason as
#      "creature or Spacecraft" above; yours-only=True from the printed
#      "you control" restriction.
#
_ENCHANT_LINE = re.compile(
    r"^Enchant "
    r"(?:(creature you control)"          # group 1: yours-only creature
    r"|(artifact you control)"            # group 2: yours-only artifact
    r"|(creature or Spacecraft)"          # group 3: creature-or-spacecraft
    r"|(artifact or creature you control)"# group 4: artifact-or-creature yours
    r"|(creature)"                        # group 5: plain creature
    r")$"
)


def _parse_enchant_line(
    line: str,
) -> tuple[str, bool] | None:
    """Return ``(aura_enchant_type, aura_yours_only)`` for a recognized
    ``Enchant X`` line, else ``None``.

    The two engine parameters drive the cast-time target picker
    (``actions._select_spell_targets``). Simplifications for compound
    enchant targets ("creature or Spacecraft", "artifact or creature
    you control") are documented on the ``_ENCHANT_LINE`` regex comment.
    """
    m = _ENCHANT_LINE.match(line.strip())
    if m is None:
        return None
    if m.group(1):   # "creature you control"
        return ("creature", True)
    if m.group(2):   # "artifact you control"
        return ("artifact", True)
    if m.group(3):   # "creature or Spacecraft" — simplified to creature
        return ("creature", False)
    if m.group(4):   # "artifact or creature you control" — simplified
        return ("creature", True)
    # m.group(5) — plain "creature"
    return ("creature", False)


# ``"Enchanted (creature|permanent) gets ±N/±M[ and has/loses ...]"``
# line recognizer. Maps to ``power_bonus``, ``toughness_bonus``,
# ``granted_keywords``, ``attached_grants_lose_all_abilities``, and
# ``attached_grants_ward_str`` on ``make_aura``.
#
# The P/T part uses signed integer notation: ``+2/+2``, ``-5/-0``,
# ``+1/+0``, ``-3/-0``. The optional rider is one of:
#
#   and has <keyword>[, keyword]*[ and ward {cost}]
#   and has <keyword> and <keyword>[ and ward {cost}]
#   and can't be blocked by more than one creature
#   and loses all abilities
#
# The ``and loses all abilities`` form also sets
# ``attached_grants_lose_all_abilities=True``; it may appear alone or
# paired with a P/T modifier (Duskmourn's Domination has ``-3/-0 and
# loses all abilities``).
_ENCHANTED_GETS_RE = re.compile(
    r"^Enchanted (?:creature|permanent) gets "
    r"([+-]\d+)/([+-]\d+)"               # groups 1+2: power / toughness
    r"(?: and (.+))?$"                   # group 3: optional rider (no trailing period)
)
# Rider: "loses all abilities" → attached_grants_lose_all_abilities
_RIDER_LOSES_ALL_ABILITIES = "loses all abilities"
# Rider: "can't be blocked by more than one creature" → menace keyword
_RIDER_MENACE = "can't be blocked by more than one creature"
# Ward in "has ... and ward {cost}" rider
_RIDER_WARD_RE = re.compile(r"^(.*?) and (ward \{[^}]+\})$")
# "has <keywords>" rider prefix
_RIDER_HAS_PREFIX = "has "


def _parse_enchanted_gets_line(
    line: str,
) -> (
    "tuple[int, int, frozenset[str], bool, str | None] | None"
):
    """Parse an ``Enchanted (creature|permanent) gets ±N/±M ...`` line.

    Returns ``(power_bonus, toughness_bonus, granted_keywords,
    lose_all_abilities, ward_cost_str_or_None)`` on success, else
    ``None``.

    Handles the following rider shapes (after the P/T modifier):
    - No rider → zero bonuses, empty keywords, no lose-all, no ward.
    - ``and has <keyword>`` → granted keyword.
    - ``and has <kw1> and <kw2>`` → two granted keywords.
    - ``and has <kw> and ward {cost}`` → keyword + ward grant.
    - ``and can't be blocked by more than one creature`` → menace.
    - ``and loses all abilities`` → lose-all flag.
    """
    line = line.rstrip(".")
    m = _ENCHANTED_GETS_RE.match(line)
    if m is None:
        return None
    power_bonus = int(m.group(1))
    toughness_bonus = int(m.group(2))
    rider = m.group(3)  # None if no rider

    granted: set[str] = set()
    lose_all = False
    ward_cost: str | None = None

    if rider is None:
        return (power_bonus, toughness_bonus, frozenset(granted),
                lose_all, ward_cost)

    # "loses all abilities" rider (may stand alone)
    if rider == _RIDER_LOSES_ALL_ABILITIES:
        return (power_bonus, toughness_bonus, frozenset(granted),
                True, ward_cost)

    # "can't be blocked by more than one creature" → menace
    if rider == _RIDER_MENACE:
        granted.add("menace")
        return (power_bonus, toughness_bonus, frozenset(granted),
                lose_all, ward_cost)

    # "has ..." rider — strip the "has " prefix then parse keywords
    if not rider.startswith(_RIDER_HAS_PREFIX):
        return None
    keyword_part = rider[len(_RIDER_HAS_PREFIX):]

    # Check for "... and ward {cost}" suffix
    ward_m = _RIDER_WARD_RE.match(keyword_part)
    if ward_m:
        keyword_part = ward_m.group(1)
        ward_line = ward_m.group(2)  # "ward {cost}"
        # Parse "ward {cost}" via the standard ward-line parser but
        # capitalize for it to match "Ward {cost}" form.
        ward_parsed = _parse_ward_line(ward_line.capitalize())
        if ward_parsed is None:
            return None
        ward_cost = ward_parsed

    # Split remaining keyword_part on " and " to handle multi-keyword
    kw_pieces = [p.strip() for p in keyword_part.split(" and ")]
    for kw in kw_pieces:
        # Normalize first letter to upper case for _parse_keyword_line
        kw_cap = kw[:1].upper() + kw[1:] if kw else kw
        parsed = _parse_keyword_line(kw_cap)
        if parsed is None:
            return None
        granted.update(parsed)

    return (power_bonus, toughness_bonus, frozenset(granted),
            lose_all, ward_cost)


# Aura-level static-flag lines -----------------------------------------

# "Enchanted (creature|permanent) has ward {cost}." (standalone ward grant,
# no P/T modifier) → attached_grants_ward.
# Hardlight Containment prints "Enchanted permanent has ward {1}." as its
# own oracle line. Distinct from the "and ward {cost}" inline rider on a
# "gets +N/+M and has ... and ward {cost}" line; the inline rider is parsed
# by ``_parse_enchanted_gets_line``'s ``_RIDER_WARD_RE`` logic, while this
# standalone form is its own line recognizer. Both feed the same
# ``attached_grants_ward`` kwarg on ``make_aura``.
_ENCHANTED_HAS_WARD_LINE = re.compile(
    r"^Enchanted (?:creature|permanent) has "
    r"(?:ward (\{[^}]+\}))\.$"
)
# "You control enchanted creature/permanent." → attached_grants_control
_YOU_CONTROL_ENCHANTED_LINE = re.compile(
    r"^You control enchanted (?:creature|permanent)\.$"
)
# "Enchanted creature/permanent doesn't untap during its controller's
# untap step." → attached_prevents_untap
_DOESNT_UNTAP_LINE = re.compile(
    r"^Enchanted (?:creature|permanent) doesn't untap during its "
    r"controller's untap step\.$"
)
# "Enchanted creature/permanent loses all abilities." (standalone, no P/T)
_LOSES_ALL_ABILITIES_LINE = re.compile(
    r"^Enchanted (?:creature|permanent) loses all abilities\.$"
)
# "The first time you would create one or more tokens each turn, you may
# instead create that many tokens that are copies of enchanted permanent."
# → replaces_first_tokens_with_copies=True (Moonlit Meditation). Literal
# — only card in the pool with this surface today; deferred until a second
# example with this shape exists.
_REPLACES_FIRST_TOKENS_LINE = (
    "The first time you would create one or more tokens each turn, "
    "you may instead create that many tokens that are copies of "
    "enchanted permanent."
)
# Honest no-op lines that appear on migrated Aura cards but map to
# engine-unenforced metadata or unoffered options. Each is recognized and
# silently dropped so the card can still claim its other lines.
#
# "As long as this Aura entered this turn, enchanted creature has
# hexproof." (Shardmage's Rescue) — hexproof is unenforced metadata per
# rooms-batch6; the conditional grant is likewise a no-op.
#
# Activated-ability lines beginning with "{cost}:" that are dropped as
# honest no-ops (Stay Hidden's shuffle-and-manifest, etc.) — matched
# by the cost-prefix pattern below.
_AURA_HONEST_NOOP_LINES = frozenset({
    # Shardmage's Rescue: conditional hexproof (no-op per rooms-batch6)
    "As long as this Aura entered this turn, enchanted creature "
    "has hexproof.",
})

# Activated abilities on Auras that are dropped as honest no-ops
# (the option isn't offered via ``legal.py``; same permission-not-offered
# shape Lecture Hall ships per dsk-rooms-batch6).
_ACTIVATED_ABILITY_PREFIX = re.compile(r"^\{[^}]+\}.*:.*$")

# "When enchanted creature becomes tapped or is dealt damage, destroy it."
# (Cryoshatter) — compound trigger line: produces TWO TriggeredAbility
# entries (one BECOMES_TAPPED + IsHost(), one DEALT_DAMAGE + IsHost()) both
# with DestroyEnchantedPermanent(). Only Cryoshatter in the pool has this
# exact surface today; deferred generalization until a second card with a
# compound Aura-trigger line (becomes-tapped-or-dealt-damage → destroy)
# appears.
_CRYOSHATTER_COMPOUND_LINE = (
    "When enchanted creature becomes tapped or is dealt damage, "
    "destroy it."
)

# Literal trigger-line recognizers for Aura ETBs whose effect phrase
# uses a bespoke engine class not yet in the general grammar. Each entry
# maps the verbatim stripped oracle trigger line to the ``TriggeredAbility``
# object the bespoke factory would have built. Only one card in the pool
# prints each surface today; each entry's docstring documents why
# generalization is deferred.
#
# The table is consulted BEFORE the standard ``_parse_triggered_ability_line``
# path so the known literal wins over a potential partial parse failure.
# ``_strip_reminder_text`` has already been applied to the line before
# the lookup — keys must be reminder-text-stripped.
_AURA_LITERAL_TRIGGER_LINES: dict[str, TriggeredAbility] = {
    # ---------------------------------------------------------------
    # (audit-litdispatch-auras) Meltstrider's Resolve fight ETB
    # ("When this Aura enters, enchanted creature fights up to one
    # target creature an opponent controls.") migrated to the
    # unified ``_parse_triggered_ability_line`` path: ``this Aura
    # enters`` lives in ``_PREDICATE_TRIGGER_PHRASES`` and the body
    # is now claimed by an Aura-context effect-phrase recognizer in
    # ``mtg_bot.cards.parser.effects._parse_effect`` mapping to
    # ``EnchantedCreatureFightsTargetEffect``.
    # ---------------------------------------------------------------
    # ---------------------------------------------------------------
    # (audit-litdispatch-auras) Pain for All ETB
    # ("When this Aura enters, enchanted creature deals damage equal
    # to its power to any other target.") migrated to the unified
    # ``_parse_triggered_ability_line`` path: ``this Aura enters``
    # already lives in ``_PREDICATE_TRIGGER_PHRASES`` and the body
    # is claimed by an Aura-context effect-phrase recognizer in
    # ``mtg_bot.cards.parser.effects._parse_effect`` mapping to
    # ``PainForAllETBEffect``.
    # ---------------------------------------------------------------
    # ---------------------------------------------------------------
    # (audit-litdispatch-auras) Pain for All damage-echo
    # ("Whenever enchanted creature is dealt damage, it deals that
    # much damage to each opponent.") migrated to the unified
    # ``_parse_triggered_ability_line`` path: ``enchanted creature
    # is dealt damage`` already lives in
    # ``_PREDICATE_TRIGGER_PHRASES`` and the body is now claimed by
    # an Aura-context effect-phrase recognizer in
    # ``mtg_bot.cards.parser.effects._parse_effect`` mapping to
    # ``PainForAllDamageEchoEffect``.
    # ---------------------------------------------------------------
    # ---------------------------------------------------------------
    # Cracked Skull — ETB look-at-hand may-discard trigger.
    # Multi-sentence oracle trigger line; the standard trigger parser
    # anchors on a single trailing period so it can't match this
    # three-sentence form. Literal keeps the entire printed surface.
    # Only Cracked Skull in the pool has this ETB form.
    # ---------------------------------------------------------------
    (
        "When this Aura enters, look at target player's hand. "
        "You may choose a nonland card from it. "
        "That player discards that card."
    ): TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=TargetOpponentLookHandMayDiscard(),
    ),
    # ---------------------------------------------------------------
    # Sporogenic Infection — ETB target-opp-sacs trigger.
    # "When this Aura enters, target player sacrifices a creature of
    # their choice other than enchanted creature." →
    # TargetOpponentSacrificesCreatureOtherThanEnchanted.
    # Only card in the pool with this ETB Aura form.
    # ---------------------------------------------------------------
    (
        "When this Aura enters, target player sacrifices a creature of "
        "their choice other than enchanted creature."
    ): TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=TargetOpponentSacrificesCreatureOtherThanEnchanted(),
    ),
    # ---------------------------------------------------------------
    # Chorale of the Void — attacks trigger (bespoke reanimate effect).
    # "Whenever enchanted creature attacks, put target creature card
    # from defending player's graveyard onto the battlefield under your
    # control tapped and attacking." → ChoraleReanimateDefenderGrave
    # CreatureEffect. Only Chorale in the pool has this "reanimate-from-
    # defending-player's-graveyard-tapped-and-attacking" Aura-attacks
    # trigger; generalization deferred until a second example exists.
    # ---------------------------------------------------------------
    (
        "Whenever enchanted creature attacks, put target creature card "
        "from defending player's graveyard onto the battlefield under "
        "your control tapped and attacking."
    ): TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsHost(subject="attacker"),
        effect=ChoraleReanimateDefenderGraveCreatureEffect(),
    ),
    # ---------------------------------------------------------------
    # Chorale of the Void — Void end-step trigger (bespoke sac-unless-
    # void effect). "Void — At the beginning of your end step, sacrifice
    # this Aura unless a nonland permanent left the battlefield this turn
    # or a spell was warped this turn." → SacrificeSelfUnlessVoidActive.
    # The "Void — " prefix is the oracle ability-word; the rest maps to
    # the existing Void-rider mechanic. Only Chorale in the pool ships
    # this exact "sacrifice this Aura unless" Void end-step form;
    # generalization deferred until a second Aura with a Void rider lands.
    # ---------------------------------------------------------------
    (
        "Void — At the beginning of your end step, sacrifice this Aura "
        "unless a nonland permanent left the battlefield this turn or a "
        "spell was warped this turn."
    ): TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Controlled(YOU),
        effect=SacrificeSelfUnlessVoidActive(),
    ),
    # ---------------------------------------------------------------
    # (audit-litdispatch-auras) Cracked Skull / Sporogenic Infection
    # / Cryoshatter shared DEALT_DAMAGE-destroys-host trigger
    # ("When enchanted creature is dealt damage, destroy it.")
    # migrated to the unified ``_parse_triggered_ability_line`` path:
    # the trigger condition ``enchanted creature is dealt damage``
    # already lives in ``_PREDICATE_TRIGGER_PHRASES``, and the body
    # ``destroy it`` is now claimed by an Aura-context effect-phrase
    # recognizer in ``mtg_bot.cards.parser.effects._parse_effect``
    # mapping to ``DestroyEnchantedPermanent``.
    # ---------------------------------------------------------------
}

# Allowlist of names that may claim through the Aura oracle-text path.
# Mirrors ``_UNIFIED_ENCHANTMENT_NAMES`` — explicit opt-in per name.
# Adding a name here removes it from ``_ENCHANTMENT_BUILDERS`` and routes
# it through ``_build_aura_via_oracle_text`` instead.
_UNIFIED_AURA_NAMES: frozenset[str] = frozenset({
    # EoE Auras — high priority (simple grammar)
    "Cryoshatter",        # -5/-0 + compound becomes-tapped-or-dealt-damage trigger
    "Frantic Strength",   # Flash + Enchant creature + +2/+2 + trample
    "Hardlight Containment",  # Enchant artifact you control + ETB exile + ward {1}
    "Meltstrider's Resolve",  # Enchant creature you control + ETB fights + +0/+2 + menace
    "Pain for All",       # Enchant creature you control + ETB deals damage + echo
    # DSK Auras — high priority
    "Cracked Skull",       # ETB look-at-hand-may-discard + dealt-damage-destroy
    "Duskmourn's Domination",  # Enchant creature + control + -3/-0 + lose-all
    "Shardmage's Rescue",  # Flash + Enchant creature you control + hexproof(noop) + +1/+1
    "Sheltered by Ghosts", # Enchant creature you control + ETB exile + +1/+0 + lifelink + ward {2}
    "Sporogenic Infection",  # ETB sac + dealt-damage-destroy
    "Stay Hidden, Stay Silent",  # ETB tap + doesn't-untap + activated(noop)
    # EoE Auras — medium priority
    "Moonlit Meditation",  # Enchant artifact or creature you control + token-replace
    "Tractor Beam",        # Enchant creature or Spacecraft + ETB tap + control + doesn't-untap
    # Chorale of the Void — attacks trigger (bespoke reanimate effect,
    # literal in _AURA_LITERAL_TRIGGER_LINES) + Void end-step rider
    # (bespoke SacrificeSelfUnlessVoidActive, also literal).
    "Chorale of the Void",
})


def _build_aura_via_oracle_text(card: dict) -> CardPrinting | None:
    """Claim an Enchantment — Aura card whose oracle text parses through
    the recognized Aura line grammar.

    Gated on ``_UNIFIED_AURA_NAMES`` so only explicitly migrated cards
    can reach this path. Returns ``None`` for any card with an
    unrecognized line so the silent-skip discipline stays intact.

    The parser walks the oracle text line by line and accumulates:
    - ``keywords`` — keyword abilities on the Aura itself (Flash).
    - ``aura_enchant_type``, ``aura_yours_only`` — from the "Enchant X"
      line.
    - ``power_bonus``, ``toughness_bonus``, ``granted_keywords`` — from
      "Enchanted creature gets ±N/±M[ and has ...]" static lines.
    - ``attached_grants_control`` — from "You control enchanted
      creature/permanent." lines.
    - ``attached_prevents_untap`` — from the "doesn't untap during its
      controller's untap step." line.
    - ``attached_grants_lose_all_abilities`` — from "Enchanted creature
      loses all abilities." standalone lines or the "and loses all
      abilities" rider on a "gets ±N/±M" line.
    - ``replaces_first_tokens_with_copies`` — from the Moonlit Meditation
      literal line.
    - ``attached_grants_ward_str`` — from the "ward {cost}" inline rider
      on "Enchanted creature gets ... and has ... and ward {cost}." lines.
    - ``triggered_abilities`` — from triggered-ability lines parsed
      through ``_parse_triggered_ability_line`` plus the Cryoshatter
      compound line (two triggers from one surface line).

    Lines that are honest no-ops (conditional hexproof, unoffered
    activated abilities) are recognized and silently dropped; any
    line that doesn't fit a recognized shape causes the card to be
    rejected outright (returns ``None``).
    """
    name = card.get("name", "")
    if name not in _UNIFIED_AURA_NAMES:
        return None

    text = card.get("oracle_text", "")

    # Aura fields accumulated across lines
    aura_keywords: set[str] = set()
    aura_enchant_type: str = "creature"
    aura_yours_only: bool = False
    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: set[str] = set()
    attached_grants_control: bool = False
    attached_prevents_untap: bool = False
    attached_grants_lose_all_abilities: bool = False
    replaces_first_tokens_with_copies: bool = False
    attached_grants_ward_str: str | None = None
    triggers: list[TriggeredAbility] = []

    for raw_line in text.split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue

        # ----------------------------------------------------------------
        # Honest no-op lines — recognized and dropped
        # ----------------------------------------------------------------
        if line in _AURA_HONEST_NOOP_LINES:
            continue
        # Activated-ability lines (cost: effect) dropped as unoffered
        # optional actions (same permission-not-offered shape Lecture Hall
        # ships per dsk-rooms-batch6).
        if _ACTIVATED_ABILITY_PREFIX.match(line):
            continue

        # ----------------------------------------------------------------
        # Keyword lines on the Aura itself (Flash, etc.)
        # ----------------------------------------------------------------
        kw_parsed = _parse_keyword_line(line)
        if kw_parsed is not None:
            aura_keywords.update(kw_parsed)
            continue

        # ----------------------------------------------------------------
        # "Enchant X" line → aura_enchant_type + aura_yours_only
        # ----------------------------------------------------------------
        enchant_parsed = _parse_enchant_line(line)
        if enchant_parsed is not None:
            aura_enchant_type, aura_yours_only = enchant_parsed
            continue

        # ----------------------------------------------------------------
        # Cryoshatter compound trigger: two events, one oracle line.
        # "When enchanted creature becomes tapped or is dealt damage,
        # destroy it." → BECOMES_TAPPED + IsHost() and
        #                 DEALT_DAMAGE + IsHost() both with
        #                 DestroyEnchantedPermanent.
        # Checked BEFORE the standard triggered-ability parser so this
        # specialized compound line wins over the generic single-trigger
        # path (which would fail to parse the compound condition phrase
        # anyway — the standard parser doesn't recognize "becomes tapped
        # or is dealt damage" as a compound event).
        # ----------------------------------------------------------------
        if line == _CRYOSHATTER_COMPOUND_LINE:
            triggers.append(TriggeredAbility(
                event=Event.BECOMES_TAPPED,
                predicate=IsHost(),
                effect=DestroyEnchantedPermanent(),
            ))
            triggers.append(TriggeredAbility(
                event=Event.DEALT_DAMAGE,
                predicate=IsHost(),
                effect=DestroyEnchantedPermanent(),
            ))
            continue

        # ----------------------------------------------------------------
        # Literal bespoke trigger lines: effects that aren't yet in the
        # general grammar. The table maps the verbatim stripped oracle
        # line to its TriggeredAbility. Checked BEFORE the standard
        # trigger parser so the known literal wins.
        # ----------------------------------------------------------------
        literal_trigger = _AURA_LITERAL_TRIGGER_LINES.get(line)
        if literal_trigger is not None:
            triggers.append(literal_trigger)
            continue

        # ----------------------------------------------------------------
        # Standard triggered-ability lines (When/Whenever ...)
        # ----------------------------------------------------------------
        parsed_trigger = _parse_triggered_ability_line(line, name=name)
        if parsed_trigger is not None:
            if isinstance(parsed_trigger, tuple):
                triggers.extend(parsed_trigger)
            else:
                triggers.append(parsed_trigger)
            continue

        # ----------------------------------------------------------------
        # Aura static lines — "Enchanted creature/permanent gets ..."
        # ----------------------------------------------------------------
        gets_parsed = _parse_enchanted_gets_line(line)
        if gets_parsed is not None:
            pb, tb, gkw, lose_all, ward = gets_parsed
            power_bonus += pb
            toughness_bonus += tb
            granted_keywords.update(gkw)
            if lose_all:
                attached_grants_lose_all_abilities = True
            if ward is not None:
                attached_grants_ward_str = ward
            continue

        # ----------------------------------------------------------------
        # "Enchanted (creature|permanent) has ward {cost}." (standalone)
        # ----------------------------------------------------------------
        ward_m = _ENCHANTED_HAS_WARD_LINE.match(line)
        if ward_m is not None:
            attached_grants_ward_str = ward_m.group(1)
            continue

        # ----------------------------------------------------------------
        # "You control enchanted creature/permanent."
        # ----------------------------------------------------------------
        if _YOU_CONTROL_ENCHANTED_LINE.match(line):
            attached_grants_control = True
            continue

        # ----------------------------------------------------------------
        # "Enchanted ... doesn't untap during its controller's untap step."
        # ----------------------------------------------------------------
        if _DOESNT_UNTAP_LINE.match(line):
            attached_prevents_untap = True
            continue

        # ----------------------------------------------------------------
        # "Enchanted ... loses all abilities." (standalone)
        # ----------------------------------------------------------------
        if _LOSES_ALL_ABILITIES_LINE.match(line):
            attached_grants_lose_all_abilities = True
            continue

        # ----------------------------------------------------------------
        # Moonlit Meditation token-replace static (literal)
        # ----------------------------------------------------------------
        if line.rstrip(".") == _REPLACES_FIRST_TOKENS_LINE.rstrip("."):
            replaces_first_tokens_with_copies = True
            continue

        # Unrecognized line — reject the card
        return None

    return make_aura(
        name=card["name"],
        cost=card.get("mana_cost", ""),
        power_bonus=power_bonus,
        toughness_bonus=toughness_bonus,
        granted_keywords=frozenset(granted_keywords),
        keywords=frozenset(aura_keywords),
        triggered_abilities=tuple(triggers),
        aura_enchant_type=aura_enchant_type,
        aura_yours_only=aura_yours_only,
        attached_prevents_untap=attached_prevents_untap,
        attached_grants_control=attached_grants_control,
        attached_grants_lose_all_abilities=attached_grants_lose_all_abilities,
        replaces_first_tokens_with_copies=replaces_first_tokens_with_copies,
        attached_grants_ward=attached_grants_ward_str,
    )


def _build_enchantment_printing(card: dict) -> CardPrinting | None:
    """Claim an Enchantment card via name-keyed dispatch, falling back to
    a printing-flag-only oracle-text path for cards whose entire oracle
    text consists of recognized printing-level static lines (Deafening
    Silence's noncreature-spell restriction etc.).

    Returns the canonical ``CardPrinting`` if either path claims the
    card. Returns ``None`` otherwise so the builder chain continues.
    The exclusion guard rejects hybrid card types (Creature /
    Land / Artifact); their own builders own those.
    """
    type_line = card.get("type_line", "")
    if "Enchantment" not in type_line:
        return None
    # Exclude hybrid card types — let their own builders handle them.
    for exclusion in ("Creature", "Land", "Artifact"):
        if exclusion in type_line:
            return None
    factory = _ENCHANTMENT_BUILDERS.get(card.get("name", ""))
    if factory is not None:
        return factory()
    # Aura oracle-text path tried before the non-Aura oracle-text path
    # so "Aura" in the type line routes to the right grammar.
    if "Aura" in type_line:
        aura = _build_aura_via_oracle_text(card)
        if aura is not None:
            return aura
    return _build_enchantment_via_oracle_text(card)


# Allowlist of names that may claim through the generic oracle-text
# fallback path below. Mirrors the room builder's
# ``_UNIFIED_ROOM_NAMES`` precedent — incremental migration: only
# names listed here can be reached by ``_build_enchantment_via_
# oracle_text``, so adding a new name to the allowlist is the
# explicit opt-in for that card. Other enchantments still take the
# name-dispatched bespoke factory path (or fall through to silent
# skip).
# ---------------------------------------------------------------------------
# Non-Aura enchantment oracle-text static recognizers
# ---------------------------------------------------------------------------
#
# Literal lines whose corresponding engine flag is a boolean or string field
# on ``make_enchantment``. Each is checked in ``_build_enchantment_via_
# oracle_text`` before the trigger parser so the flag accumulates before
# any trigger lines are processed. Adding a new flag-line is a one-entry
# addition here + one kwarg name in the call to ``make_enchantment`` below.

# "If one or more counters would be put on a creature, Spacecraft, or
# Planet you control, twice that many of each of those kinds of counters
# are put on it instead." → is_counter_doubler=True. (Loading Zone.)
# Only card in the pool with this exact counter-doubler surface; deferred
# generalization until a second counter-doubler enchantment lands.
_COUNTER_DOUBLER_LINE = (
    "If one or more counters would be put on a creature, Spacecraft, or "
    "Planet you control, twice that many of each of those kinds of "
    "counters are put on it instead."
)

# "Each creature you control enters with an additional +1/+1 counter on it
# for each land that entered the battlefield under your control this turn."
# → grants_etb_counter_per_land_entered_this_turn=True. (Bioengineered
# Future.) Only card in the pool with this surface today; deferred until
# a second example exists.
_GRANTS_ETB_COUNTER_PER_LAND_LINE = (
    "Each creature you control enters with an additional +1/+1 counter "
    "on it for each land that entered the battlefield under your control "
    "this turn."
)

# "The first spell each player casts during each of their turns may be cast
# without paying its mana cost." → grants_first_spell_each_turn_free=True.
# (Weftwalking.) Only card in the pool with this surface; deferred until a
# second example exists.
_GRANTS_FIRST_SPELL_FREE_LINE = (
    "The first spell each player casts during each of their turns may be "
    "cast without paying its mana cost."
)

# Honest no-op lines for non-Aura enchantments. Lines that appear on
# migrated cards but map to inert / unoffered / engine-unmodeled mechanics.
# The recognizer silently drops them so the remaining lines still parse.
#
# - Leyline of Mutation's two lines are both inert in this engine:
#   opening-hand replacement and the alt-cost offer are not modeled.
#   Both are therefore honest no-ops per the permission-not-offered
#   precedent (same shape as Lecture Hall / Shardmage's Rescue).
_NONAURA_HONEST_NOOP_LINES: frozenset[str] = frozenset({
    # Leyline of Mutation: opening-hand replacement (engine never places
    # it on the battlefield at game start — not modeled).
    "If this card is in your opening hand, you may begin the game "
    "with it on the battlefield.",
    # Leyline of Mutation: alt-cost offer (not wired in legal.py —
    # same permission-not-offered shape Lecture Hall ships).
    "You may pay {W}{U}{B}{R}{G} rather than pay the mana cost for "
    "spells you cast.",
})


# Cards in this set are allowed to produce a cost-and-name-only
# ``CardPrinting`` even when ``_build_enchantment_via_oracle_text``
# recognizes no actionable lines. Every line on these cards is either
# in ``_NONAURA_HONEST_NOOP_LINES`` or is otherwise inert; the printing
# sits on the battlefield doing nothing, which is rules-correct given
# that none of its surface clauses is wired through the engine today.
# (Same honest-no-op discipline the bespoke ``_build_leyline_of_mutation``
# factory uses, documented in the bespoke docstring.)
_UNIFIED_ENCHANTMENT_HONEST_NOOP_NAMES: frozenset[str] = frozenset({
    "Leyline of Mutation",
})


# Literal trigger-line recognizers for non-Aura enchantments whose ETB
# uses a bespoke engine class not yet in the general grammar. Parallel to
# ``_AURA_LITERAL_TRIGGER_LINES`` for non-Aura paths.
_NONAURA_LITERAL_TRIGGER_LINES: dict[str, TriggeredAbility] = {
    # Sothera, the Supervoid — DIES trigger.
    #
    # "Whenever a creature you control dies, each opponent chooses a
    # creature they control and exiles it." → bespoke
    # ``SotheraExileOpponentCreatureEffect``.
    #
    # ARCHITECTURAL BLOCKER: this body needs a per-opponent
    # independent-choice mass-exile primitive that ALSO tags each
    # exiled card with ``exiled_by_source = source.id``. The engine
    # primitives available today are mismatched on two axes:
    #
    #   1. ``EachOpponentSacrificesCreature`` exists but sacrifices,
    #      not exiles, and uses the agent's ``choose_sacrifice`` prompt
    #      with no mechanism to thread a source-id link onto the chosen
    #      object. Switching it to exile would also break sacrifice
    #      semantics for every existing caller.
    #   2. ``ExileTargetCreatureUntilSourceLeaves`` exiles with a
    #      source link but is targeted (single creature, picked by the
    #      ABILITY's controller) — wrong choosing player and wrong
    #      cardinality. The Sothera reading needs N independent
    #      per-opponent picks resolved in turn order, each by that
    #      opponent's agent.
    #
    # Generalization is gated on a new
    # ``EachOpponentChoosesAndExilesCreatureLinkedToSource`` primitive
    # (or a multi-axis parameterization of the existing exile family
    # with: ``per_opponent_choice=True, exile_with_source_link=True``).
    # Until that primitive lands, the literal-line dispatch is the only
    # honest claim — generalizing without it would produce the wrong
    # choosing-player or drop the exile-link bookkeeping that Sothera's
    # end-step trigger then reads.
    (
        "Whenever a creature you control dies, each opponent chooses a "
        "creature they control and exiles it."
    ): TriggeredAbility(
        event=Event.DIES,
        predicate=Subject(None, IsCreature()) & Controlled(YOU),
        effect=SotheraExileOpponentCreatureEffect(),
    ),
    # Sothera, the Supervoid — end-step trigger.
    #
    # "At the beginning of your end step, if a player controls no
    # creatures, sacrifice Sothera, then put a creature card exiled
    # with it onto the battlefield under your control with two
    # additional +1/+1 counters on it." → bespoke
    # ``SotheraEndStepReanimateEffect``.
    #
    # ARCHITECTURAL BLOCKERS (multiple, all on the same ability):
    #
    #   1. The intervening-``if`` gate "if a player controls no
    #      creatures" is a creatureless-player check. The unified
    #      ``_INTERVENING_IF_PHRASES`` table only has ``StateBound``
    #      gates (``OpponentControlsMoreLandsThanYou``, ``VoidActive``,
    #      ``Delirium``); a "any player controls zero creatures"
    #      predicate would need a new ``StateBound`` primitive.
    #      Furthermore, this gate must be re-checked at RESOLVE time
    #      (not just trigger time), per the bespoke's actual behavior
    #      — the ``_INTERVENING_IF_PHRASES`` predicate is checked only
    #      at trigger time today, so even adding the predicate would
    #      drop the resolve-time recheck (a state change between
    #      trigger and resolve would mis-fire).
    #
    #   2. The body composes three sequential operations that share
    #      anaphoric state: (a) sacrifice the source, (b) find a
    #      creature card "exiled with it" (the source-link from the
    #      DIES-trigger sibling above), pull it out of exile BEFORE
    #      the sacrifice triggers the on-leave release path, (c) put
    #      the chosen exiled card onto the battlefield under YOUR
    #      control with +2 +1/+1 counters. The ``Sequence``
    #      combinator can't model the (b)-before-(a) ordering
    #      (sequence runs strictly in order, but the sac-then-recall
    #      reading of the printed text requires recall-then-sac at
    #      the engine level to defeat the auto-return). A
    #      ``SacrificeSelfThenReturnExiledByMeWithCounters`` primitive
    #      would solve it; until that primitive exists, the bespoke
    #      effect is the only correct claim.
    #
    #   3. The "creature card exiled with it" anaphoric reference
    #      depends on the ``exiled_by_source`` bookkeeping populated
    #      by the DIES trigger's bespoke effect — i.e. these two
    #      bespoke classes are coupled, and migrating either one in
    #      isolation would break the other. The migration must land
    #      both new primitives in the same change so the source-link
    #      contract stays consistent.
    (
        "At the beginning of your end step, if a player controls no "
        "creatures, sacrifice Sothera, then put a creature card exiled "
        "with it onto the battlefield under your control with two "
        "additional +1/+1 counters on it."
    ): TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Controlled(YOU),
        effect=SotheraEndStepReanimateEffect(),
    ),
}


_UNIFIED_ENCHANTMENT_NAMES: frozenset[str] = frozenset({
    "Deafening Silence",
    "Burgeoning",
    # Banishing Light / Seam Rip / Trapped in the Screen — ETB exile-until-
    # source-leaves shapes.  The effect phrases are now in the grammar
    # (``_EXILE_OPPONENTS_NONLAND_UNTIL_LEAVES`` in effects.py).
    "Banishing Light",
    "Seam Rip",
    "Trapped in the Screen",
    # Eusocial Engineering — landfall trigger + warp cost. The trigger
    # "a land you control enters" is in PREDICATE_TRIGGER_PHRASES and
    # the Robot token creation is in TOKEN_PRINTINGS; warp support was
    # added to _build_enchantment_via_oracle_text in wave 5.
    "Eusocial Engineering",
    # Weapons Manufacturing — nontoken-artifact-enters trigger + named
    # Munitions token. Trigger phrase and named-token recognizer added
    # in wave 5.
    "Weapons Manufacturing",
    # Wave 1 (bespoke-enchantments) non-Aura additions:
    # Loading Zone — counter-doubler static + warp. The counter-doubler
    # line is recognized as a literal; warp parses via _parse_warp_line.
    "Loading Zone",
    # Bioengineered Future — ETB create-Lander trigger (parseable) +
    # grants_etb_counter_per_land_entered_this_turn static (literal).
    "Bioengineered Future",
    # Leyline of Mutation — both printed lines are honest no-ops.
    # The printing sits inert, same shape as the bespoke factory.
    "Leyline of Mutation",
    # Weftwalking — grants_first_spell_each_turn_free static (literal)
    # + ETB trigger via _NONAURA_LITERAL_TRIGGER_LINES.
    "Weftwalking",
    # Terrasymbiosis — COUNTERS_ADDED trigger now claims through the
    # unified clause grammar via the ``"you put one or more +1/+1
    # counters on a creature you control"`` predicate trigger phrase
    # plus the ``Do this only once each turn.`` rider strip. The
    # context-dependent effect rewrite in ``_parse_triggered_ability_
    # line`` swaps the default ``DrawCardsEqualToResolvingCombatDamage``
    # to ``DrawCardsEqualToResolvingCounterAmount`` when the trigger
    # event is COUNTERS_ADDED.
    "Terrasymbiosis",
    # Sothera, the Supervoid — two literal trigger lines pending
    # architectural blockers documented in
    # ``_NONAURA_LITERAL_TRIGGER_LINES``: the DIES body needs a per-
    # opponent-choice mass-exile-with-source-link primitive, and the
    # end-step body needs both a creatureless-player ``StateBound``
    # gate predicate AND a sequenced sac-then-recall-with-counters
    # primitive. Both are coupled (the end-step recall reads the
    # ``exiled_by_source`` link populated by the DIES trigger).
    "Sothera, the Supervoid",
})


def _build_enchantment_via_oracle_text(
    card: dict,
) -> CardPrinting | None:
    """Fallback path: claim an Enchantment whose entire oracle text
    parses through recognized line shapes — printing-flag statics
    (Deafening Silence) or triggered-ability lines (Burgeoning).

    Gated on ``_UNIFIED_ENCHANTMENT_NAMES`` so the path only attempts
    cards that have been explicitly migrated. Returns ``None`` for
    any card with an unrecognized line so the silent-skip path
    mirrors the rest of the parser.

    Printing-flag statics recognized (in addition to warp, ward, and
    restricts_noncreature_spells):
    - ``_COUNTER_DOUBLER_LINE`` → ``is_counter_doubler=True``
    - ``_GRANTS_ETB_COUNTER_PER_LAND_LINE`` →
      ``grants_etb_counter_per_land_entered_this_turn=True``
    - ``_GRANTS_FIRST_SPELL_FREE_LINE`` →
      ``grants_first_spell_each_turn_free=True``
    - ``_NONAURA_HONEST_NOOP_LINES`` → silently dropped (honest no-ops)
    """
    name = card.get("name", "")
    if name not in _UNIFIED_ENCHANTMENT_NAMES:
        return None

    text = card.get("oracle_text", "")
    legendary = "Legendary" in card.get("type_line", "")
    restricts_noncreature_spells = False
    is_counter_doubler = False
    grants_etb_counter_per_land = False
    grants_first_spell_free = False
    ward: str | None = None
    warp: str | None = None
    triggers: list[TriggeredAbility] = []

    for raw_line in text.split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        # Honest no-op lines — recognized and dropped
        if line in _NONAURA_HONEST_NOOP_LINES:
            continue
        if _parse_restricts_noncreature_spells_line(line):
            restricts_noncreature_spells = True
            continue
        ward_cost = _parse_ward_line(line)
        if ward_cost is not None:
            ward = ward_cost
            continue
        warp_cost = _parse_warp_line(line)
        if warp_cost is not None:
            warp = warp_cost
            continue
        # Counter-doubler static (Loading Zone)
        if line == _COUNTER_DOUBLER_LINE:
            is_counter_doubler = True
            continue
        # ETB-counter-per-land static (Bioengineered Future)
        if line == _GRANTS_ETB_COUNTER_PER_LAND_LINE:
            grants_etb_counter_per_land = True
            continue
        # First-spell-free static (Weftwalking)
        if line == _GRANTS_FIRST_SPELL_FREE_LINE:
            grants_first_spell_free = True
            continue
        # Literal bespoke trigger lines for non-Aura enchantments
        literal_trigger = _NONAURA_LITERAL_TRIGGER_LINES.get(line)
        if literal_trigger is not None:
            triggers.append(literal_trigger)
            continue
        parsed_trigger = _parse_triggered_ability_line(line, name=name)
        if parsed_trigger is not None:
            if isinstance(parsed_trigger, tuple):
                triggers.extend(parsed_trigger)
            else:
                triggers.append(parsed_trigger)
            continue
        # Anything else — Aura grammar, activated abilities, unrecognized
        # statics — falls through to the silent-skip path.
        return None

    has_any_recognized = (
        restricts_noncreature_spells
        or triggers
        or is_counter_doubler
        or grants_etb_counter_per_land
        or grants_first_spell_free
        or ward is not None
        or warp is not None
    )
    if not has_any_recognized and name not in _UNIFIED_ENCHANTMENT_HONEST_NOOP_NAMES:
        # Nothing recognized — leave the card for a future grammar
        # slice rather than emit a blank Enchantment. Exception: cards
        # in _UNIFIED_ENCHANTMENT_HONEST_NOOP_NAMES are explicitly
        # all-no-op and still emit a cost-and-name-only printing.
        return None

    return make_enchantment(
        name=card["name"],
        cost=card.get("mana_cost", ""),
        legendary=legendary,
        restricts_noncreature_spells_to_one_per_turn=(
            restricts_noncreature_spells
        ),
        is_counter_doubler=is_counter_doubler,
        grants_etb_counter_per_land_entered_this_turn=(
            grants_etb_counter_per_land
        ),
        grants_first_spell_each_turn_free=grants_first_spell_free,
        ward=ward,
        warp=warp,
        triggered_abilities=tuple(triggers),
    )
