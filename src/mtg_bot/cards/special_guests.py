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

from dataclasses import dataclass

from mtg_bot.cards.base import (
    CardPrinting,
    CounterTargetSpell,
    CreateToken,
    Effect,
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    ModalChooseOne,
    OptionalPutLandFromHandOntoBattlefield,
    TriggeredAbility,
    make_aura,  # noqa: F401  (used once oracle work lands)
    make_creature,
    make_enchantment,
    make_equipment,
    make_instant,
    make_sorcery,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


@dataclass(frozen=True)
class _SpgNoOp(Effect):
    """Spell-effect placeholder for stand-in Special Guests spells.

    Real oracle text lives in follow-up per-card commits. Keeping the
    placeholder local to this module so it never leaks into the shared
    effects package — once every SPG spell has a real effect this
    class can be deleted.
    """

    name: str

    def describe(self) -> str:
        return f"(stand-in no-op for {self.name})"

    def resolve(self, state, controller_id, targets=()):  # noqa: D401
        state.log.append(f"{self.name} resolves (no-op stand-in)")


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
    # Deafening Silence {W}: each player can cast no more than one
    # noncreature spell each turn. dropped per-player noncreature-spell
    # cast-restriction static effect.
    "Deafening Silence": make_enchantment(
        "Deafening Silence", "{W}",
    ),
    # Robe of Stars {1}{W}: Equipment. Equipped creature has phasing;
    # {2},{T}: phase out equipped creature; Equip {3}. dropped phasing
    # subsystem (phased flag, phase-in-on-untap, skip-untap, attachment
    # handling) and phase-out activated ability.
    "Robe of Stars": make_equipment(
        "Robe of Stars", "{1}{W}",
    ),
    # Nexus of Fate {5}{U}{U}: take an extra turn after this one. If it
    # would be put into a graveyard from anywhere, shuffle it into its
    # owner's library instead. dropped extra-turn queueing + zone-change
    # replacement effect.
    "Nexus of Fate": make_instant(
        "Nexus of Fate", "{5}{U}{U}", _SpgNoOp("Nexus of Fate"),
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
    # turn. dropped combat-damage prevention state flag + gate in
    # combat._resolve_damage_step.
    "Darkness": make_instant(
        "Darkness", "{B}", _SpgNoOp("Darkness"),
    ),
    # Magus of the Moon {2}{R} 2/2 Human Wizard: nonbasic lands are
    # Mountains. dropped static nonbasic→Mountain type-rewriting
    # replacement effect on land mana-ability resolution.
    "Magus of the Moon": make_creature(
        "Magus of the Moon", "{2}{R}", 2, 2, subtypes=("Human", "Wizard"),
    ),
    # Burgeoning {G}: whenever an opponent plays a land, you may put a
    # land card from your hand onto the battlefield. Trigger fires only
    # on the land-drop action (actions.play_land), not on any other
    # "enters the battlefield" event — Burgeoning-put lands fire
    # landfall but don't re-fire the opponent-plays-land chain.
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
    # with mana value ≤ X, put it onto the battlefield, shuffle. Shuffle
    # GSZ into its owner's library. dropped X-cost tutor with color
    # filter + self-shuffle zone-change replacement.
    "Green Sun's Zenith": make_sorcery(
        "Green Sun's Zenith", "{X}{G}", _SpgNoOp("Green Sun's Zenith"),
    ),
    # Sliver Overlord {W}{U}{B}{R}{G} 7/7 Legendary Sliver Mutant:
    # {3}: tutor a Sliver to hand. All Slivers have "{3}: Gain control
    # of target Sliver." dropped Sliver subtype search filter + granted
    # activated ability to all Slivers.
    "Sliver Overlord": make_creature(
        "Sliver Overlord", "{W}{U}{B}{R}{G}", 7, 7,
        subtypes=("Sliver", "Mutant"), legendary=True,
    ),
}
