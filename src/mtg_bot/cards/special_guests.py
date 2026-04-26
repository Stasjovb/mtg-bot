"""EoE Special Guests (set code ``spg``) — 10-card subset.

Special Guests is Magic's cross-set premium-reprint series; Edge of
Eternities shipped with a 10-card Special Guests drop on 2025-08-01
(Scryfall filter ``set:spg date:2025-08-01``). Unlike Stellar Sights
these are not all lands — the subset spans instants, sorceries,
enchantments, an Aura, an Equipment, and creatures.

Each entry ships here as a typed stand-in that satisfies registry
integrity tests; follow-up commits restore full oracle text
per-card (or per-mechanic-family where cards share new plumbing).
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AttachToTargetCreatureYouControl,
    CardPrinting,
    CounterTargetSpell,
    CreateToken,
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    GainControlOfTargetSliverPermanently,
    ModalChooseOne,
    OptionalPutLandFromHandOntoBattlefield,
    PhaseOutEquippedCreature,
    PreventAllCombatDamageThisTurn,
    SearchLibraryForCard,
    SearchLibraryForGreenCreatureWithMVAtMostX,
    TakeExtraTurnAfterThisOne,
    TriggeredAbility,
    make_creature,
    make_enchantment,
    make_equipment,
    make_instant,
    make_sorcery,
    parse_mana_cost,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


# Edge of Eternities Special Guests (10 cards, Scryfall ``set:spg
# date:2025-08-01``). Each entry is a type-correct stand-in; ``# dropped
# X`` comments mirror the EOE_CREATURES / STELLAR_SIGHTS_LANDS tracking
# convention so restoration progress is greppable.
SPECIAL_GUESTS_EOE: dict[str, CardPrinting] = {
    # Warping Wail {1}{C}: Choose one —
    #   • Exile target creature with power or toughness 1 or less.
    #   • Counter target sorcery spell.
    #   • Create a 1/1 colorless Eldrazi Scion creature token with
    #     "Sacrifice this token: Add {C}."
    # Full oracle via ModalChooseOne; the Scion token lives in
    # TOKEN_PRINTINGS and carries the sac-for-{C} mana ability.
    "Warping Wail": make_instant(
        "Warping Wail", "{1}{C}",
        ModalChooseOne(modes=(
            ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1),
            CounterTargetSpell(filter_types=frozenset({"Sorcery"})),
            CreateToken(token_printing=TOKEN_PRINTINGS["Eldrazi Scion"]),
        )),
    ),
    # Deafening Silence {W}: each player can't cast more than one
    # noncreature spell each turn. Enforced via the
    # ``restricts_noncreature_spells_to_one_per_turn`` static flag on
    # CardPrinting — legal.legal_actions post-filters CastSpell so
    # additional noncreature casts aren't proposed once the caster's
    # Player.noncreature_spells_cast_this_turn is already ≥ 1.
    "Deafening Silence": make_enchantment(
        "Deafening Silence", "{W}",
        restricts_noncreature_spells_to_one_per_turn=True,
    ),
    # Robe of Stars {1}{W}: Artifact — Equipment.
    #   Equipped creature gets +0/+3.
    #   Astral Projection — {1}{W}: Equipped creature phases out.
    #   Equip {1}
    # The +0/+3 uses the equipment_bonuses machinery already in play.
    # Phasing uses the new GameObject.phased_out flag — cleared at the
    # controller's next untap step (turn.run_untap_step). Combat
    # damage skips phased creatures; triggers/anthems/targeting
    # don't yet hide them — documented simplification.
    # Equip activation isn't modeled in this engine (the Equip cost is
    # a known limitation shared with other EoE Equipment); Robe enters
    # attached via the same "ETB attach-to-target-creature" pattern
    # used elsewhere.
    "Robe of Stars": make_equipment(
        "Robe of Stars", "{1}{W}",
        power_bonus=0, toughness_bonus=3,
        triggered_abilities=(
            TriggeredAbility(
                trigger="etb",
                effect=AttachToTargetCreatureYouControl(),
            ),
        ),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}{W}"), mana_str="{1}{W}",
                ),
                effect=PhaseOutEquippedCreature(),
            ),
        ),
    ),
    # Nexus of Fate {5}{U}{U}: take an extra turn after this one. If it
    # would be put into a graveyard from anywhere, reveal Nexus and
    # shuffle it into its owner's library instead. The extra-turn
    # clause uses TakeExtraTurnAfterThisOne (pushes the caster onto
    # state.extra_turn_queue, consumed by simulate.simulate_game).
    # The shuffle-instead-of-graveyard clause is the flag-driven
    # replacement in actions._send_to_graveyard_or_library; it covers
    # the spell-resolve, countered, and aura-fizzle paths. Discard-
    # from-hand and mill paths aren't hooked — documented on the flag.
    "Nexus of Fate": make_instant(
        "Nexus of Fate", "{5}{U}{U}", TakeExtraTurnAfterThisOne(),
        shuffles_into_library_instead_of_graveyard=True,
    ),
    # Paradox Haze {2}{U}: Aura — enchant player. Enchanted player gets
    # an additional upkeep step after the first. Per user decision this
    # card ships as a **permanent no-op** stand-in: modeled as a plain
    # Enchantment (not an Aura) because `aura_enchant_type="player"` is
    # not supported and the extra-upkeep mechanic is out of scope.
    "Paradox Haze": make_enchantment(
        "Paradox Haze", "{2}{U}",
    ),
    # Darkness {B}: prevent all combat damage that would be dealt this
    # turn. Sets state.prevent_combat_damage_this_turn which
    # combat._resolve_damage_step checks at the top of each damage
    # step; the flag clears at end-of-turn cleanup. Non-combat damage
    # (direct damage, pings) is not affected.
    "Darkness": make_instant(
        "Darkness", "{B}", PreventAllCombatDamageThisTurn(),
    ),
    # Magus of the Moon {2}{R} 2/2 Human Wizard: nonbasic lands are
    # Mountains. Enforced via the ``nonbasic_lands_are_mountains``
    # static flag — game.effective_land_produces collapses every
    # nonbasic land's mana colors to {R} and
    # game.effective_activated_abilities suppresses nonbasic-land
    # activated abilities while Magus is on the battlefield.
    # Simplifications: subtypes aren't rewritten (the land still
    # reports its printed Type—Cave/etc.), and already-animated
    # manlands keep their temp_is_creature state (no layers system).
    "Magus of the Moon": make_creature(
        "Magus of the Moon", "{2}{R}", 2, 2, subtypes=("Human", "Wizard"),
        nonbasic_lands_are_mountains=True,
    ),
    # Burgeoning {G}: whenever an opponent plays a land, you may put a
    # land card from your hand onto the battlefield. The
    # opponent-plays-land trigger fires only on the land-drop action
    # (actions.play_land), so a Burgeoning-dropped land — which is
    # *put* onto the battlefield, not *played* per CR 305.1 — correctly
    # fires landfall on its controller's permanents but does NOT
    # re-fire the opponent-plays-land chain. See test_burgeoning.py for
    # the regression coverage that pins both halves of this behavior.
    "Burgeoning": make_enchantment(
        "Burgeoning", "{G}",
        triggered_abilities=(
            TriggeredAbility(
                trigger="opponent_plays_land",
                effect=OptionalPutLandFromHandOntoBattlefield(),
            ),
        ),
    ),
    # Green Sun's Zenith {X}{G}: search library for a green creature
    # card with mana value X or less, put it onto the battlefield,
    # shuffle. Shuffle GSZ into its owner's library.
    # The tutor reads X from state.resolving_x_value via
    # SearchLibraryForGreenCreatureWithMVAtMostX; the self-shuffle
    # reuses the same ``shuffles_into_library_instead_of_graveyard``
    # flag as Nexus — after the spell's effect resolves, the card is
    # routed to the library instead of the graveyard.
    "Green Sun's Zenith": make_sorcery(
        "Green Sun's Zenith", "{X}{G}",
        SearchLibraryForGreenCreatureWithMVAtMostX(),
        shuffles_into_library_instead_of_graveyard=True,
    ),
    # Sliver Overlord {W}{U}{B}{R}{G} 7/7 Legendary Sliver Mutant:
    #   • {3}: Search your library for a Sliver card, reveal it, put
    #     it into your hand, then shuffle.
    #   • {3}: Gain control of target Sliver. (Indefinitely.)
    # The tutor uses SearchLibraryForCard with the new "sliver" filter
    # (matches any card with the Sliver subtype). The control-grab is
    # GainControlOfTargetSliverPermanently — reassigns controller_id
    # without scheduling a revert, unlike the existing
    # until-end-of-turn steal effects.
    "Sliver Overlord": make_creature(
        "Sliver Overlord", "{W}{U}{B}{R}{G}", 7, 7,
        subtypes=("Sliver", "Mutant"), legendary=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"), mana_str="{3}",
                ),
                effect=SearchLibraryForCard(filter_name="sliver"),
            ),
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"), mana_str="{3}",
                ),
                effect=GainControlOfTargetSliverPermanently(),
            ),
        ),
    ),
}
