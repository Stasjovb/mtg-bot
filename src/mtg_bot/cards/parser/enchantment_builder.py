"""Whole-card name-keyed dispatch for Edge of Eternities + Duskmourn
Enchantments.

Each enchantment whose oracle text maps directly to well-typed
``CardPrinting`` fields is claimed here via a name-keyed exact-dispatch
table — one factory per card, no grammar required.

This module covers:

Non-Aura enchantments (EoE):
- Banishing Light ``{2}{W}``
- Seam Rip ``{W}``
- Loading Zone ``{3}{G}``
- Weftwalking ``{4}{U}{U}``
- Sothera, the Supervoid ``{2}{B}{B}``
- Terrasymbiosis ``{2}{G}``
- Weapons Manufacturing ``{1}{R}``
- Bioengineered Future ``{1}{G}{G}``
- Eusocial Engineering ``{3}{G}{G}``

Aura enchantments (EoE):
- Moonlit Meditation ``{2}{U}``
- Tractor Beam ``{2}{U}{U}``
- Chorale of the Void ``{3}{B}``
- Cryoshatter ``{U}``
- Meltstrider's Resolve ``{G}``
- Hardlight Containment ``{W}``
- Pain for All ``{2}{R}``

Aura enchantments (DSK):
- Duskmourn's Domination ``{4}{U}{U}``
- Frantic Strength ``{1}{R}`` (Flash + +2/+2 + trample)
"""

from __future__ import annotations

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
    DrawCardsEqualToResolvingCounterAmount,
    EnchantedCreatureFightsTargetEffect,
    ExileOpponentsNonlandPermanentUntilLeaves,
    ExileTargetCreatureUntilSourceLeaves,
    PainForAllDamageEchoEffect,
    PainForAllETBEffect,
    SacrificeSelfUnlessVoidActive,
    SotheraEndStepReanimateEffect,
    SotheraExileOpponentCreatureEffect,
    TractorBeamETBEffect,
    WeftwalkingETBEffect,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsArtifact,
    IsCreature,
    IsHost,
    IsLand,
    IsNontoken,
    IsSelf,
)


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


def _build_weftwalking() -> CardPrinting:
    return make_enchantment(
        "Weftwalking", "{4}{U}{U}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS, predicate=IsSelf(),
                effect=WeftwalkingETBEffect(),
            ),
        ),
        grants_first_spell_each_turn_free=True,
    )


def _build_sothera_the_supervoid() -> CardPrinting:
    return make_enchantment(
        "Sothera, the Supervoid", "{2}{B}{B}",
        legendary=True,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.DIES,
                predicate=IsCreature() & Controlled(YOU),
                effect=SotheraExileOpponentCreatureEffect(),
            ),
            TriggeredAbility(
                event=Event.BEGINNING_OF_END_STEP, predicate=Controlled(YOU),
                effect=SotheraEndStepReanimateEffect(),
            ),
        ),
    )


def _build_terrasymbiosis() -> CardPrinting:
    return make_enchantment(
        "Terrasymbiosis", "{2}{G}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.COUNTERS_ADDED,
                predicate=IsCreature() & Controlled(YOU),
                effect=DrawCardsEqualToResolvingCounterAmount(),
                once_per_turn=True,
            ),
        ),
    )


def _build_weapons_manufacturing() -> CardPrinting:
    return make_enchantment(
        "Weapons Manufacturing", "{1}{R}",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsArtifact() & IsNontoken() & Controlled(YOU) & ~IsSelf(),
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
                event=Event.ENTERS, predicate=IsLand() & Controlled(YOU),
                effect=CreateToken(
                    token_printing=TOKEN_PRINTINGS["Robot"],
                    count=1,
                ),
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
    # Non-Aura
    "Banishing Light": _build_banishing_light,
    "Seam Rip": _build_seam_rip,
    "Loading Zone": _build_loading_zone,
    "Weftwalking": _build_weftwalking,
    "Sothera, the Supervoid": _build_sothera_the_supervoid,
    "Terrasymbiosis": _build_terrasymbiosis,
    "Weapons Manufacturing": _build_weapons_manufacturing,
    "Bioengineered Future": _build_bioengineered_future,
    "Eusocial Engineering": _build_eusocial_engineering,
    # Auras
    "Moonlit Meditation": _build_moonlit_meditation,
    "Tractor Beam": _build_tractor_beam,
    "Chorale of the Void": _build_chorale_of_the_void,
    "Cryoshatter": _build_cryoshatter,
    "Meltstrider's Resolve": _build_meltstriders_resolve,
    "Hardlight Containment": _build_hardlight_containment,
    "Pain for All": _build_pain_for_all,
    # Duskmourn (DSK) Auras
    "Duskmourn's Domination": _build_duskmourns_domination,
    "Frantic Strength": _build_frantic_strength,
}


def _build_enchantment_printing(card: dict) -> CardPrinting | None:
    """Claim an EoE main-set Enchantment card via name-keyed dispatch.

    Returns the canonical ``CardPrinting`` if the card's type line
    matches Enchantment (but not Creature, Land, or Artifact) and the
    card's name appears in ``_ENCHANTMENT_BUILDERS``. Returns ``None``
    otherwise so the builder chain continues.
    """
    type_line = card.get("type_line", "")
    if "Enchantment" not in type_line:
        return None
    # Exclude hybrid card types — let their own builders handle them.
    for exclusion in ("Creature", "Land", "Artifact"):
        if exclusion in type_line:
            return None
    factory = _ENCHANTMENT_BUILDERS.get(card.get("name", ""))
    if factory is None:
        return None
    return factory()
