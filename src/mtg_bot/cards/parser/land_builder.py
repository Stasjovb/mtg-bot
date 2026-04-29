"""Land ``CardPrinting`` builder.

Currently supports three land kinds:

- **Basic lands** (``Basic`` supertype + ``Land`` card type), whose
  oracle text is the single reminder line ``"({T}: Add {<color>}.)"``.
  The captured color feeds ``make_basic_land``.
- **Shock lands** (non-basic ``Land`` with a two-color subtype line):
  oracle text is the dual-mana reminder + the fixed
  ``"As this land enters, you may pay 2 life. If you don't, it
  enters tapped."`` rider. Both colors come from the reminder line and
  the subtype string off the type line; both feed ``make_shock_land``.
- **Colorless utility lands** (plain ``Land`` type line, no subtypes,
  no supertypes) whose first oracle line is exactly
  ``"{T}: Add {C}."``. The remaining lines (typically tier-gated
  activated abilities like Secluded Starforge's tap-X-artifacts and
  Robot-token activations) are intentionally dropped — they mirror
  the static-side ``make_colorless_land`` simplification, which also
  ignores those abilities. The land taps for generic via the
  auto-tap-for-cost generic-mana fallback.
- **EoS bespoke lands** — complex multi-ability EoS reprints claimed
  by name in ``_BESPOKE_EOS_LANDS`` before any generic grammar arm.
- **Planet lands** (``Land — Planet`` subtype, EoE) — claimed by the
  parameterized ``_try_build_planet_land`` recognizer that captures
  the produced color and drops Station + tier-gated abilities.
- **EoE bespoke lands** — Command Bridge (EoE Land with
  sac-self-unless-tap ETB) claimed by name in ``_BESPOKE_EOE_LANDS``.
- **Opening-hand luck-counter lands** (Gemstone Caverns) — claimed
  by ``_try_build_opening_hand_luck_counter_land`` for the static
  "always has a luck counter" simplification.
- **Chosen-color Cave lands** (Sunken Citadel) — claimed by
  ``_try_build_chosen_color_cave_land`` for the simplified
  "any-color" static collapse of the printed
  "as it enters, choose a color" clause.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    AddNManaOfChosenColor,
    AddOneManaFromControlledLandsProductions,
    AddOneManaOfChosenPermanentColor,
    BecomeLandCreatureUEOT,
    BecomesCopyOfTargetLand,
    CardPrinting,
    ChangeControllerToCombatDamageSource,
    ConditionalIfYouControlAtLeast,
    CopyTargetInstantOrSorceryYouControl,
    CreateTokenCopyOfTargetCreatureYouControl,
    DealDamageToControllerAndAddMana,
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    DestroyTargetLand,
    DrawCards,
    Effect,
    ExileTargetAttackingCreatureUntilEndStep,
    ExileTargetCreatureUntilSourceLeaves,
    GainLife,
    GrantLifeToEachOpponent,
    ManaCost,
    MovePlusOneCounterBetweenPermanentsYouControl,
    PumpCreaturesYouControlUntilEOT,
    PumpSelfXPowerUEOT,
    PumpTargetCreatureUntilEOT,
    PutBasicLandFromHandOntoBattlefieldTapped,
    PutChargeCountersOnSelf,
    PutPlusOneCounterOnSelf,
    RegenerateTargetCreature,
    ReturnTargetLandFromGraveyardToHand,
    SacrificeNLandsYouControl,
    SacrificeSelfUnlessTapPermanent,
    SearchLibraryForBasicLandTapped,
    SearchLibraryForCard,
    Sequence,
    SwitchSourcePowerToughnessUEOT,
    TriggeredAbility,
    UntapTargetLand,
    make_basic_land,
    make_colorless_land,
    make_planet_land,
    make_shock_land,
    make_utility_land,
    parse_mana_cost,
)
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.effects.predicates import YOU, Controlled, Event, IsCreature, IsSelf


_COLOR_WORD_TO_LETTER: dict[str, str] = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
}


# Manlands ("creature lands") share a fixed three-line oracle shape:
#   1. "This land enters tapped."
#   2. "{T}: Add {<C1>} or {<C2>}."
#   3. "<COST>: Until end of turn, this land becomes a <P>/<T>
#      <c1word> and <c2word> Elemental creature with <KEYWORDS>.
#      It's still a land."
# The "Elemental" type-grant on the animated creature isn't modeled
# (matches the static side, which only passes power/toughness and
# granted_keywords to BecomeLandCreatureUEOT). Variants without the
# trailing ``with <KEYWORDS>`` clause (Creeping Tar Pit's "It can't
# be blocked this turn." rider) are handled separately and don't
# match this pattern.
_MANLAND_TAPPED_LINE = "This land enters tapped."
_MANLAND_TAP_FOR_DUAL_RE = re.compile(
    r"^\{T\}: Add \{([WUBRG])\} or \{([WUBRG])\}\.$"
)
_MANLAND_ANIMATE_RE = re.compile(
    r"^(?P<cost>(?:\{[^}]+\})+): Until end of turn, this land becomes a "
    r"(?P<power>\d+)/(?P<toughness>\d+) "
    r"(?P<c1word>white|blue|black|red|green) and "
    r"(?P<c2word>white|blue|black|red|green) Elemental creature "
    r"with (?P<keywords>[^.]+)\. It's still a land\.$"
)
# Tar-Pit-shape variant: same as the standard manland line but the
# keyword tail is replaced with the literal ``It can't be blocked
# this turn.`` rider after ``It's still a land.``. Maps to
# ``BecomeLandCreatureUEOT(unblockable=True)`` with no
# ``granted_keywords``. Currently the only Stellar Sights manland
# matching this shape is Creeping Tar Pit.
_MANLAND_ANIMATE_UNBLOCKABLE_RE = re.compile(
    r"^(?P<cost>(?:\{[^}]+\})+): Until end of turn, this land becomes a "
    r"(?P<power>\d+)/(?P<toughness>\d+) "
    r"(?P<c1word>white|blue|black|red|green) and "
    r"(?P<c2word>white|blue|black|red|green) Elemental creature\. "
    r"It's still a land\. It can't be blocked this turn\.$"
)
# Granted-ability-shape variant: ``... with "<quoted body>". It's
# still a land.``. The quoted body is dispatched through
# ``_GRANTED_ABILITY_BODIES`` to produce either a granted activated
# ability (Lavaclaw Reaches's X-pump, Wandering Fumarole's P/T swap)
# or a granted triggered ability (Raging Ravine's attacks → +1/+1
# counter). Bodies outside the dispatch table fall through.
_MANLAND_ANIMATE_GRANTED_RE = re.compile(
    r"^(?P<cost>(?:\{[^}]+\})+): Until end of turn, this land becomes a "
    r"(?P<power>\d+)/(?P<toughness>\d+) "
    r"(?P<c1word>white|blue|black|red|green) and "
    r"(?P<c2word>white|blue|black|red|green) Elemental creature "
    r"with \"(?P<body>[^\"]+)\.\" It's still a land\.$"
)


# Whitelist of granted-ability bodies the parser knows how to model.
# Each value is a tuple ``(granted_activated_abilities,
# granted_triggered_abilities)`` to plug straight into
# ``BecomeLandCreatureUEOT``. Lavaclaw Reaches and Wandering Fumarole
# grant activated abilities; Raging Ravine grants a triggered one.
# Adding a new body is a one-line table extension; unrecognized bodies
# leave the manland unclaimed (silent skip).
def _granted_x_pump() -> tuple:
    return (
        (
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{X}"), mana_str="{X}",
                ),
                effect=PumpSelfXPowerUEOT(),
            ),
        ),
        (),
    )


def _granted_pt_swap() -> tuple:
    return (
        (
            ActivatedAbility(
                cost=ActivationCost(),
                effect=SwitchSourcePowerToughnessUEOT(),
            ),
        ),
        (),
    )


def _granted_attacks_plus_one_counter() -> tuple:
    return (
        (),
        (
            TriggeredAbility(
                event=Event.ATTACKS, predicate=IsSelf(),
                effect=PutPlusOneCounterOnSelf(amount=1),
            ),
        ),
    )


_GRANTED_ABILITY_BODIES: dict[str, "callable"] = {
    "{X}: This creature gets +X/+0 until end of turn":
        _granted_x_pump,
    "{0}: Switch this creature's power and toughness until end of turn":
        _granted_pt_swap,
    "Whenever this creature attacks, put a +1/+1 counter on it":
        _granted_attacks_plus_one_counter,
}


def _parse_manland_keywords(text: str) -> frozenset[str] | None:
    """Parse the ``with <X>[, <Y>][, and <Z>]`` keyword tail of a
    manland animation line into a normalized frozenset.

    The Stellar Sights manlands grant simple keywords whose oracle
    surface form matches their printing-keyword name verbatim (flying,
    vigilance, deathtouch, hexproof, double strike, lifelink, reach).
    Returns ``None`` if any token doesn't look like a known keyword
    surface — keeps the parser conservative; unrecognized shapes fall
    through to the silent-skip path.
    """
    parts = re.split(r",\s+|\s+and\s+", text.strip())
    cleaned = [p.strip() for p in parts if p.strip()]
    if not cleaned:
        return None
    allowed = {
        "flying", "vigilance", "deathtouch", "hexproof",
        "double strike", "lifelink", "reach", "trample",
        "first strike", "menace", "haste", "defender",
    }
    for kw in cleaned:
        if kw not in allowed:
            return None
    return frozenset(cleaned)


# Basic-land reminder text. Scryfall always prints the produced color in
# parentheses on the single oracle line: ``"({T}: Add {W}.)"`` etc. The
# capture group identifies which color the land taps for and feeds it
# straight into ``make_basic_land``. Colorless basics aren't a thing in
# EoE today, but ``C`` is included for completeness so a future
# colorless basic doesn't trip the parser.
_BASIC_LAND_REMINDER = re.compile(r"^\(\{T\}: Add \{([WUBRGC])\}\.\)$")


# Shock-land oracle text is exactly two lines, in this order on Scryfall:
#   1. The dual-mana reminder: ``"({T}: Add {<c1>} or {<c2>}.)"``
#   2. The pay-2-life-or-enter-tapped rider:
#      ``"As this land enters, you may pay 2 life. If you don't, it
#      enters tapped."``
# Both colors come from the reminder line and are passed straight to
# ``make_shock_land``. The subtype string (e.g. ``"Forest Island"``)
# comes from the type line. Variants with a different life cost or a
# different tap-condition phrasing intentionally do not match — they
# fall through to the skip-silently behavior.
_SHOCK_LAND_REMINDER = re.compile(
    r"^\(\{T\}: Add \{([WUBRGC])\} or \{([WUBRGC])\}\.\)$"
)
_SHOCK_LAND_LIFE_RIDER = (
    "As this land enters, you may pay 2 life. "
    "If you don't, it enters tapped."
)


# Colorless utility-land "base" line: ``"{T}: Add {C}."``. When this is
# the first line of a plain ``Land`` (no subtypes, no supertypes) we
# build a colorless utility land, dropping any further activated-ability
# lines. Mirrors the static-side ``make_colorless_land`` simplification
# used for Secluded Starforge.
_COLORLESS_TAP_LINE = "{T}: Add {C}."


# ---------------------------------------------------------------------------
# Bespoke EoS (Stellar Sights) land dispatch table.
#
# Lands whose oracle shape doesn't map cleanly onto any of the generic
# grammar arms (multi-step manland, tap-sac, restricted mana, …) are
# pre-built here as complete ``CardPrinting`` objects and looked up by
# name before the grammar arms run. The table is keyed purely by name;
# the dispatcher in ``_build_land_printing`` gates on
# ``card.get("set") in {"eos", "eoe", "spg"}`` so main-set cards with
# the same name can't accidentally be claimed here.
#
# Each entry must exactly match the corresponding ``make_utility_land``
# call in ``src/mtg_bot/cards/stellar_sights.py``.
# ---------------------------------------------------------------------------
def _make_bespoke_eos_lands() -> dict[str, CardPrinting]:
    return {
        # Blinkmoth Nexus: {T}: Add {C}. {1}: → 1/1 Blinkmoth artifact flying UEOT.
        # {1},{T}: Target Blinkmoth gets +1/+1 UEOT.
        # Animation at index 0, explicit mana-tap at index 1, pump at index 2.
        "Blinkmoth Nexus": make_utility_land(
            "Blinkmoth Nexus",
            produces=frozenset({"C"}),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{1}"), mana_str="{1}",
                    ),
                    effect=BecomeLandCreatureUEOT(
                        power=1, toughness=1,
                        granted_keywords=frozenset({"flying"}),
                        granted_subtype="Blinkmoth",
                    ),
                ),
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(produces=(("C", 1),)),
                    is_mana_ability=True,
                ),
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost("{1}"), mana_str="{1}",
                        tap_self=True,
                    ),
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=1, toughness_bonus=1,
                        target_subtype="Blinkmoth",
                    ),
                ),
            ),
        ),
        # Grove of the Burnwillows: {T}: Add {C}. {T}: Add {R} or {G}.
        # Each opponent gains 1 life.
        "Grove of the Burnwillows": make_utility_land(
            "Grove of the Burnwillows",
            produces=frozenset({"C", "R", "G"}),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(produces=(("C", 1),)),
                    is_mana_ability=True,
                ),
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=Sequence(effects=(
                        AddNManaOfChosenColor(
                            amount=1, options=("R", "G"),
                        ),
                        GrantLifeToEachOpponent(amount=1),
                    )),
                    is_mana_ability=True,
                ),
            ),
        ),
        # Swarmyard: {T}: Add {C}. {1},{T}: Regenerate target Insect, Rat,
        # Spider, Squirrel, or Snake.
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
        # Contested War Zone: triggered (combat damage → opponent gains control)
        # + {T}: Add {C}. + {1},{T}: Attacking creatures get +1/+0 UEOT.
        "Contested War Zone": make_utility_land(
            "Contested War Zone",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DEALS_COMBAT_DAMAGE,
                    predicate=(
                        IsCreature(subject="source")
                        & Controlled(YOU, subject="target")
                    ),
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
        # Blast Zone: enters with a charge counter. {T}: Add {C}.
        # {X}{X},{T}: Put X charge counters on this land.
        # {3},{T},Sac self: Destroy each nonland permanent with MV =
        # charge counter count.
        "Blast Zone": make_utility_land(
            "Blast Zone",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
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
        # Endless Sands: {T}: Add {C}. {2},{T}: Exile target creature you
        # control. {4},{T},Sac self: Return each creature card exiled with
        # this land to the battlefield.
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
                    effect=Sequence(effects=()),
                ),
            ),
        ),
        # Inventors' Fair: legendary, enters tapped. Upkeep trigger: if
        # you control 3+ artifacts, gain 1 life. {1},{T},Sac self: Search
        # library for artifact card (if you control 3+ artifacts).
        "Inventors' Fair": make_utility_land(
            "Inventors' Fair", legendary=True,
            enters_tapped=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_UPKEEP, predicate=Controlled(YOU),
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
        # Power Depot: Artifact Land. Enters tapped. {T}: Add one mana of
        # any color (artifact spells only). Modular 1 is not modeled.
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
        # Lotus Field: Hexproof. Enters tapped. ETB sac 2 lands.
        # {T}: Add three mana of any one color.
        "Lotus Field": make_utility_land(
            "Lotus Field",
            keywords=frozenset({"hexproof"}),
            enters_tapped=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=SacrificeNLandsYouControl(count=2),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddNManaOfChosenColor(amount=3),
                    is_mana_ability=True,
                ),
            ),
        ),
        # Mirrorpool: Legendary, enters tapped. {T}: Add {C}.
        # {2}{C},{T},Sac self: copy target instant/sorcery you control.
        # {4}{C},{T},Sac self: create token copy of target creature you control.
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
        # Plaza of Heroes: Legendary. {T}: Add {C}. {T}: any mana
        # (legendary_spell). {T}: any mana among legendary permanents
        # you control (legendary_permanent_ability). {3},{T},Exile self:
        # target legendary creature gains hexproof and indestructible UEOT.
        "Plaza of Heroes": make_utility_land(
            "Plaza of Heroes", legendary=True,
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(produces=(("C", 1),)),
                    is_mana_ability=True,
                ),
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(
                        produces=(("any", 1),),
                        spend_restriction="legendary_spell",
                    ),
                    is_mana_ability=True,
                ),
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(
                        produces=(("any", 1),),
                        spend_restriction="legendary_permanent_ability",
                    ),
                    is_mana_ability=True,
                ),
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
    }


_BESPOKE_EOS_LANDS: dict[str, CardPrinting] = _make_bespoke_eos_lands()

# Set codes that carry full bespoke implementations in the static registry.
# The colorless-utility-land simplifier already skips "eos" and "spg";
# we gate the bespoke table on the same set codes so only true reprints
# are claimed here.
_BESPOKE_EOS_SETS: frozenset[str] = frozenset({"eos", "eoe", "spg"})


# ---------------------------------------------------------------------------
# Bespoke EoE (Edge of Eternities) land dispatch table.
#
# EoE-specific non-basic lands that require sac-self-unless-tap ETB
# triggers or any-color mana abilities that the generic grammar arms
# don't cover.  Keyed by name; dispatcher in ``_build_land_printing``
# gates on ``card.get("set") == "eoe"``.
#
# Planet lands (``Land — Planet`` subtype) are no longer here — they
# are claimed by the parameterized ``_try_build_planet_land`` arm.
#
# Each entry must exactly match the corresponding ``make_utility_land``
# call in ``src/mtg_bot/cards/lands.py``.
# ---------------------------------------------------------------------------
def _make_bespoke_eoe_lands() -> dict[str, CardPrinting]:
    return {
        # Command Bridge: enters tapped, ETB sac-unless-tap-permanent,
        # {T}: Add one mana of any color.
        "Command Bridge": make_utility_land(
            "Command Bridge",
            enters_tapped=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=SacrificeSelfUnlessTapPermanent(),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(tap_self=True),
                    effect=AddManaToPool(produces=(("any", 1),)),
                    is_mana_ability=True,
                ),
            ),
        ),
    }


_BESPOKE_EOE_LANDS: dict[str, CardPrinting] = _make_bespoke_eoe_lands()


# Planet lands (EoE).
#
# ``Land — Planet`` cards (no supertypes, single ``Planet`` subtype)
# whose oracle text is the strict four-line shape:
#   1. ``This land enters tapped.``
#   2. ``{T}: Add {<C>}.``
#   3. ``Station (Tap another creature you control: ...)`` — keyword
#      line with reminder text. Stripped to the bare keyword
#      ``Station``; the Station mechanic itself isn't modeled.
#   4. ``12+ | <ABILITY>``  — tier-gated ability dropped per the
#      static-side ``make_planet_land`` simplification (Planets with
#      Station are functionally non-creature Spacecraft, not modeled
#      for Planets).
#
# The captured color in line 2 feeds ``make_planet_land``; lines 3
# and 4 are intentionally dropped to match the static side. Adding
# more Planets with the same shape is zero code: this recognizer
# already claims any ``Land — Planet`` card with the four-line layout
# and a single basic-color tap line. Variants (e.g. multi-color
# Planets) would need the regex relaxed; today's printed cycle is
# all single-color.
_PLANET_TAPPED_LINE = "This land enters tapped."
_PLANET_TAP_FOR_COLOR_RE = re.compile(r"^\{T\}: Add \{([WUBRG])\}\.$")
_PLANET_STATION_KEYWORD_LINE = "Station"
_PLANET_TIERED_ABILITY_RE = re.compile(r"^\d+\+ \| .+$")


def _try_build_planet_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a Planet ``CardPrinting`` if ``text`` matches the strict
    four-line ``This land enters tapped.`` + ``{T}: Add {<C>}.`` +
    ``Station (...)`` + ``<N>+ | <ABILITY>`` shape and the type line
    is ``Land — Planet``, else ``None``.

    The Station reminder is stripped per-line; the bare ``Station``
    keyword and the tiered ability line are intentionally dropped to
    match the static-side ``make_planet_land`` simplification (Planet
    Station mechanic and tier-gated abilities are not modeled). The
    captured color produces a single-color tapped land via
    ``make_planet_land``.
    """
    if supertypes:
        return None
    if subtypes != ("Planet",):
        return None
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(raw_lines) != 4:
        return None
    lines = [_strip_reminder_text(ln) for ln in raw_lines]
    if lines[0] != _PLANET_TAPPED_LINE:
        return None
    tap_match = _PLANET_TAP_FOR_COLOR_RE.match(lines[1])
    if tap_match is None:
        return None
    if lines[2] != _PLANET_STATION_KEYWORD_LINE:
        return None
    if _PLANET_TIERED_ABILITY_RE.match(lines[3]) is None:
        return None
    return make_planet_land(card["name"], tap_match.group(1))


def _build_land_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for a land ``card`` (a Scryfall
    record). Returns ``None`` if the card is not a land or if its shape
    isn't one the land grammar yet supports."""
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Land" not in card_types:
        return None
    text = card.get("oracle_text", "").strip()
    if "Basic" in supertypes:
        m = _BASIC_LAND_REMINDER.match(text)
        if m is None:
            return None
        color = m.group(1)
        return make_basic_land(name=card["name"], color=color)
    # Bespoke EoS lands: name-keyed exact dispatch before all grammar arms.
    # Checked first so complex multi-ability shapes (Blinkmoth Nexus, Contested
    # War Zone, Grove of the Burnwillows, …) can't accidentally partially-match
    # a generic recognizer. Gated on set code so a main-set card with the same
    # name doesn't get hijacked.
    if card.get("set") in _BESPOKE_EOS_SETS:
        bespoke = _BESPOKE_EOS_LANDS.get(card["name"])
        if bespoke is not None:
            return bespoke
    # Bespoke EoE lands: Command Bridge. Checked after the EoS table so
    # reprints with the same name don't get claimed here. Planet lands
    # used to live in this table; they now claim through the
    # parameterized ``_try_build_planet_land`` arm below.
    if card.get("set") == "eoe":
        bespoke_eoe = _BESPOKE_EOE_LANDS.get(card["name"])
        if bespoke_eoe is not None:
            return bespoke_eoe
    # Non-basic land shapes follow.
    planet = _try_build_planet_land(card, text, supertypes, subtypes)
    if planet is not None:
        return planet
    shock = _try_build_shock_land(card, text, subtypes)
    if shock is not None:
        return shock
    manland = _try_build_manland(card, text, supertypes, subtypes)
    if manland is not None:
        return manland
    tap_sac = _try_build_tap_sac_utility_land(
        card, text, supertypes, subtypes,
    )
    if tap_sac is not None:
        return tap_sac
    fancy_mana = _try_build_fancy_mana_land(
        card, text, supertypes, subtypes,
    )
    if fancy_mana is not None:
        return fancy_mana
    ancient_tomb = _try_build_pain_two_mana_land(
        card, text, supertypes, subtypes,
    )
    if ancient_tomb is not None:
        return ancient_tomb
    paid_fancy = _try_build_paid_fancy_mana_land(
        card, text, supertypes, subtypes,
    )
    if paid_fancy is not None:
        return paid_fancy
    keyword_colorless = _try_build_keyword_colorless_utility_land(
        card, text, supertypes, subtypes,
    )
    if keyword_colorless is not None:
        return keyword_colorless
    paid_effect = _try_build_paid_effect_utility_land(
        card, text, supertypes, subtypes,
    )
    if paid_effect is not None:
        return paid_effect
    restricted_mana = _try_build_restricted_mana_land(
        card, text, supertypes, subtypes,
    )
    if restricted_mana is not None:
        return restricted_mana
    verge = _try_build_verge_dual_land(
        card, text, supertypes, subtypes,
    )
    if verge is not None:
        return verge
    low_life_dual = _try_build_low_life_dual_land(
        card, text, supertypes, subtypes,
    )
    if low_life_dual is not None:
        return low_life_dual
    fetch = _try_build_fetch_land(
        card, text, supertypes, subtypes,
    )
    if fetch is not None:
        return fetch
    optional_copy_cave = _try_build_optional_copy_cave_land(
        card, text, supertypes, subtypes,
    )
    if optional_copy_cave is not None:
        return optional_copy_cave
    gemstone = _try_build_opening_hand_luck_counter_land(
        card, text, supertypes, subtypes,
    )
    if gemstone is not None:
        return gemstone
    chosen_color_cave = _try_build_chosen_color_cave_land(
        card, text, supertypes, subtypes,
    )
    if chosen_color_cave is not None:
        return chosen_color_cave
    colorless = _try_build_colorless_utility_land(
        card, text, supertypes, subtypes,
    )
    if colorless is not None:
        return colorless
    return None


def _try_build_shock_land(
    card: dict, text: str, subtypes: tuple[str, ...]
) -> CardPrinting | None:
    """Return a shock-land ``CardPrinting`` if ``text`` matches the
    two-line shock-land shape, else ``None``.

    The shape is exactly: a dual-mana reminder line followed by the
    fixed pay-2-life-or-enter-tapped rider. Anything else (extra lines,
    different life cost, different rider wording) falls through.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    m = _SHOCK_LAND_REMINDER.match(lines[0])
    if m is None:
        return None
    if lines[1] != _SHOCK_LAND_LIFE_RIDER:
        return None
    if not subtypes:
        return None
    colors = (m.group(1), m.group(2))
    return make_shock_land(
        name=card["name"],
        colors=colors,
        subtypes_str=" ".join(subtypes),
    )


def _try_build_manland(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a manland (creature-land) ``CardPrinting`` if ``text``
    matches the standard 3-line manland shape, else ``None``.

    Shape:
      1. "This land enters tapped."
      2. "{T}: Add {<C1>} or {<C2>}."
      3. "<COST>: Until end of turn, this land becomes a <P>/<T>
          <c1word> and <c2word> Elemental creature with <KEYWORDS>.
          It's still a land."

    The colors named in the type-2 mana ability must match the colors
    named in the type-3 animation line (after color-word translation).
    Variants with extra abilities, X-cost activations, attacks
    triggers, or "It can't be blocked this turn." riders fall through.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 3:
        return None
    if lines[0] != _MANLAND_TAPPED_LINE:
        return None
    tap_match = _MANLAND_TAP_FOR_DUAL_RE.match(lines[1])
    if tap_match is None:
        return None
    animate_match = _MANLAND_ANIMATE_RE.match(lines[2])
    keywords: frozenset[str] = frozenset()
    unblockable = False
    granted_activated: tuple = ()
    granted_triggered: tuple = ()
    if animate_match is not None:
        keywords = _parse_manland_keywords(animate_match.group("keywords"))
        if keywords is None:
            return None
    else:
        animate_match = _MANLAND_ANIMATE_UNBLOCKABLE_RE.match(lines[2])
        if animate_match is not None:
            unblockable = True
        else:
            animate_match = _MANLAND_ANIMATE_GRANTED_RE.match(lines[2])
            if animate_match is None:
                return None
            body = animate_match.group("body")
            builder = _GRANTED_ABILITY_BODIES.get(body)
            if builder is None:
                return None
            granted_activated, granted_triggered = builder()
    c1, c2 = tap_match.group(1), tap_match.group(2)
    c1_animate = _COLOR_WORD_TO_LETTER[animate_match.group("c1word")]
    c2_animate = _COLOR_WORD_TO_LETTER[animate_match.group("c2word")]
    if {c1, c2} != {c1_animate, c2_animate}:
        return None
    cost_str = animate_match.group("cost")
    return make_utility_land(
        card["name"],
        produces=frozenset({c1, c2}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost(cost_str),
                    mana_str=cost_str,
                ),
                effect=BecomeLandCreatureUEOT(
                    power=int(animate_match.group("power")),
                    toughness=int(animate_match.group("toughness")),
                    granted_keywords=keywords,
                    unblockable=unblockable,
                    granted_activated_abilities=granted_activated,
                    granted_triggered_abilities=granted_triggered,
                ),
            ),
        ),
    )


# Tap-and-sac utility land builder.
#
# Recognizes plain colorless utility lands whose oracle text is the
# fixed two-line shape:
#   1. ``{T}: Add {C}.``
#   2. ``<COST>: <BODY>.``
# where ``<COST>`` is one of a small set of recognized cost prefixes
# (``{T}, Sacrifice this land``, ``{N}, {T}, Sacrifice a land``, etc.)
# and ``<BODY>`` is on a per-cost-shape effect whitelist below.
# Bodies / costs outside the table fall through silently.
#
# Built on the same ``make_utility_land`` factory as the manland
# branch — single activated ability, the cost flags carry the sac
# semantics, the effect comes from the dispatch.
_TAP_FOR_C_LINE = "{T}: Add {C}."
_TAP_AND_SAC_SELF_RE = re.compile(
    r"^\{T\}, Sacrifice this land: (?P<body>.+)\.$"
)
_MANA_TAP_AND_SAC_LAND_RE = re.compile(
    r"^(?P<cost>(?:\{[^}]+\})+), \{T\}, Sacrifice a land: (?P<body>.+)\.$"
)
_TAP_AND_SAC_CREATURE_RE = re.compile(
    r"^\{T\}, Sacrifice a creature: (?P<body>.+)\.$"
)
_MANA_TAP_AND_SAC_DESERT_RE = re.compile(
    r"^(?P<cost>(?:\{[^}]+\})+), \{T\}, Sacrifice a Desert: (?P<body>.+)\.$"
)


# Body-text → effect-factory whitelist. Each factory returns a fresh
# ``Effect`` instance; matching bodies outside the table makes the
# recognizer fall through. Adding a new card is one entry per cost
# shape — keep the surface form exact (no trailing period — the
# regexes strip it).
_TAP_SAC_SELF_BODIES: dict[str, "callable"] = {
    "Destroy target land": lambda: DestroyTargetLand(),
    "Return target land card from your graveyard to your hand":
        lambda: ReturnTargetLandFromGraveyardToHand(),
}
_TAP_SAC_LAND_BODIES: dict[str, "callable"] = {
    "Destroy target nonbasic land":
        lambda: DestroyTargetLand(nonbasic_only=True),
}
_TAP_SAC_CREATURE_BODIES: dict[str, "callable"] = {
    "You gain 1 life": lambda: GainLife(amount=1),
}


# Bodies for the Desert-subtyped sac-a-Desert path. Imports are
# resolved lazily inside the factory because some of these effect
# classes are bespoke (e.g. ``ExileAllGraveyards``) and pulling them
# into the top-level imports keeps the import graph predictable.
def _exile_all_graveyards() -> Effect:
    from mtg_bot.cards.base import ExileAllGraveyards
    return ExileAllGraveyards()


_TAP_SAC_DESERT_BODIES: dict[str, "callable"] = {
    "Exile all graveyards": _exile_all_graveyards,
}


def _try_build_tap_sac_utility_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a tap-and-sac utility-land ``CardPrinting`` if ``text``
    matches one of the recognized two-line shapes, else ``None``.

    Supported shapes (each gated by its own body whitelist):

    - **Sac-self, no mana cost**: ``{T}: Add {C}.`` then
      ``{T}, Sacrifice this land: <BODY>.`` — Strip Mine,
      Petrified Field.
    - **Sac-a-land with mana cost**: ``{T}: Add {C}.`` then
      ``<COST>, {T}, Sacrifice a land: <BODY>.`` — Dust Bowl.
    - **Sac-a-creature, no mana cost**: ``{T}: Add {C}.`` then
      ``{T}, Sacrifice a creature: <BODY>.`` — High Market.
      The ``sacrifice_another_creature_or_artifact`` flag is set
      (matches the static side; widens "a creature" to "a creature
      or artifact").
    """
    if supertypes:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    if lines[0] != _TAP_FOR_C_LINE:
        return None
    second = lines[1]

    sac_self = _TAP_AND_SAC_SELF_RE.match(second)
    if sac_self is not None and not subtypes:
        body = sac_self.group("body")
        factory = _TAP_SAC_SELF_BODIES.get(body)
        if factory is None:
            return None
        return make_utility_land(
            card["name"],
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        tap_self=True, sacrifice_self=True,
                    ),
                    effect=factory(),
                ),
            ),
        )

    sac_land = _MANA_TAP_AND_SAC_LAND_RE.match(second)
    if sac_land is not None and not subtypes:
        body = sac_land.group("body")
        factory = _TAP_SAC_LAND_BODIES.get(body)
        if factory is None:
            return None
        cost_str = sac_land.group("cost")
        return make_utility_land(
            card["name"],
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost(cost_str),
                        mana_str=cost_str,
                        tap_self=True,
                        sacrifice_a_land=True,
                    ),
                    effect=factory(),
                ),
            ),
        )

    sac_creature = _TAP_AND_SAC_CREATURE_RE.match(second)
    if sac_creature is not None and not subtypes:
        body = sac_creature.group("body")
        factory = _TAP_SAC_CREATURE_BODIES.get(body)
        if factory is None:
            return None
        return make_utility_land(
            card["name"],
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        tap_self=True,
                        sacrifice_another_creature_or_artifact=True,
                    ),
                    effect=factory(),
                ),
            ),
        )

    sac_desert = _MANA_TAP_AND_SAC_DESERT_RE.match(second)
    if sac_desert is not None and subtypes == ("Desert",):
        body = sac_desert.group("body")
        factory = _TAP_SAC_DESERT_BODIES.get(body)
        if factory is None:
            return None
        cost_str = sac_desert.group("cost")
        return make_utility_land(
            card["name"],
            subtypes_str="Desert",
            activated_abilities=(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost(cost_str),
                        mana_str=cost_str,
                        tap_self=True,
                        sacrifice_a_desert=True,
                    ),
                    effect=factory(),
                ),
            ),
        )

    return None


# Fancy-mana single-ability lands.
#
# Plain ``Land`` cards (no supertypes, no subtypes) whose entire
# oracle text is a single activated mana ability that produces an
# any-color or chosen-color coin (rather than a fixed colorless or
# dual-color coin). Each card pairs an exact oracle line with a
# factory that returns the matching ``(cost, effect)`` pair.
#
# Distinct from the manland branch (lands that animate into
# creatures) and the tap-and-sac branch (lands that pay self-sac
# costs). The ``produces`` set is empty in the static — mana-source
# tracking treats "any" coins as untyped at compile time.
def _fancy_pay_one_life_any_color() -> tuple:
    return (
        ActivationCost(tap_self=True, pay_life=1),
        AddManaToPool(produces=(("any", 1),), spend_restriction=None),
    )


def _fancy_chosen_permanent_color() -> tuple:
    return (
        ActivationCost(tap_self=True),
        AddOneManaOfChosenPermanentColor(),
    )


def _fancy_controlled_lands_productions() -> tuple:
    return (
        ActivationCost(tap_self=True),
        AddOneManaFromControlledLandsProductions(),
    )


_FANCY_MANA_BODIES: dict[str, "callable"] = {
    "{T}, Pay 1 life: Add one mana of any color.":
        _fancy_pay_one_life_any_color,
    "{T}: Choose a color of a permanent you control. "
    "Add one mana of that color.":
        _fancy_chosen_permanent_color,
    "{T}: Add one mana of any type that a land you "
    "control could produce.":
        _fancy_controlled_lands_productions,
}


def _try_build_fancy_mana_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a fancy-mana single-ability ``CardPrinting`` if the
    card's entire oracle text matches an entry in
    ``_FANCY_MANA_BODIES`` and the type line is plain ``Land``,
    else ``None``.

    Currently claims Mana Confluence (``{T}, Pay 1 life``),
    Meteor Crater (chosen-permanent-color), and Reflecting Pool
    (any-from-controlled-lands). Each is a single line whose
    factory returns the canonical static ``(cost, effect)`` pair.
    Future entries are one-liners: add the surface form and a
    factory.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    factory = _FANCY_MANA_BODIES.get(text.strip())
    if factory is None:
        return None
    cost, effect = factory()
    return make_utility_land(
        card["name"],
        activated_abilities=(
            ActivatedAbility(
                cost=cost, effect=effect, is_mana_ability=True,
            ),
        ),
    )


# Ancient-Tomb-shape "pain land" — single-line plain Land whose
# ``{T}`` mana ability fuses an Add-N-mana production with a
# damage-to-controller rider on the same activation. Currently the
# only EoE printing matching this shape is Ancient Tomb itself; the
# regex captures the produced colorless count and damage amount so a
# future printing of similar shape (e.g. ``Add {C}{C}{C}. This land
# deals 3 damage to you.``) can claim by table extension rather than
# code change. The effect class
# (``DealDamageToControllerAndAddMana``) is the bespoke engine
# primitive the static side already uses; the parser only constructs
# it from the parsed values.
_PAIN_TWO_MANA_LINE_RE = re.compile(
    r"^\{T\}: Add (?P<mana>(?:\{[CWUBRG]\})+)\. "
    r"This land deals (?P<damage>\d+) damage to you\.$"
)


def _try_build_pain_two_mana_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a CardPrinting for a single-line pain-shape mana land
    matching the Ancient Tomb pattern, else None.

    Constraint: plain ``Land`` (no supertypes, no subtypes) whose entire
    oracle text is one line whose mana production is an all-colorless
    ``{C}+`` chain (one or more ``{C}`` braces). Other color
    combinations would need a per-color tally; today's only printing
    produces colorless, and adding colored variants is a one-line regex
    relaxation when the day comes.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    line = text.strip()
    m = _PAIN_TWO_MANA_LINE_RE.match(line)
    if m is None:
        return None
    mana_str = m.group("mana")
    pips = re.findall(r"\{([CWUBRG])\}", mana_str)
    if not pips or any(p != "C" for p in pips):
        return None
    return make_utility_land(
        card["name"],
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=DealDamageToControllerAndAddMana(
                    damage=int(m.group("damage")),
                    produces=(("C", len(pips)),),
                ),
                is_mana_ability=True,
            ),
        ),
    )


# "Paid fancy mana" lands: plain ``Land`` whose oracle text is
# (optionally) an evergreen-keyword line, then ``{T}: Add {C}.`` (the
# basic tap-for-colorless ability — *not* modeled on the static side;
# the engine's auto-tap-for-cost generic-mana fallback covers it),
# then a single ``<COST>, {T}: <BODY>.`` paid-mana activation whose
# body is on a per-shape whitelist.
#
# Currently claims:
# - Crystal Quarry: ``{5}, {T}: Add {W}{U}{B}{R}{G}.``
# - Cascading Cataracts: ``{5}, {T}: Add five mana in any combination
#   of colors.`` plus the ``Indestructible`` keyword line.
_KEYWORD_LINE_RE = re.compile(r"^([A-Z][a-z]+)$")
_DROPPED_TAP_FOR_C_LINE = "{T}: Add {C}."
_PAID_FANCY_MANA_RE = re.compile(
    r"^(?P<cost>(?:\{[^}]+\})+), \{T\}: (?P<body>.+)\.$"
)


def _add_wubrg_factory() -> Effect:
    return AddManaToPool(
        produces=(
            ("W", 1), ("U", 1), ("B", 1), ("R", 1), ("G", 1),
        ),
    )


def _add_five_any_factory() -> Effect:
    return AddManaToPool(produces=(("any", 5),))


_PAID_FANCY_MANA_BODIES: dict[str, "callable"] = {
    "Add {W}{U}{B}{R}{G}": _add_wubrg_factory,
    "Add five mana in any combination of colors": _add_five_any_factory,
}


_LAND_KEYWORD_WHITELIST = frozenset({"indestructible", "exalted"})


def _try_build_paid_fancy_mana_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a paid-fancy-mana CardPrinting if ``text`` matches the
    optional-keyword + dropped-{T}:{C} + paid-mana shape, else None.

    The leading optional-keyword line, when present, must be a single
    capitalized word on the keyword whitelist (today: ``Indestructible``
    for Cascading Cataracts). The static side carries this keyword as
    a frozenset on the ``CardPrinting``; the parser threads it through.
    The middle line ``{T}: Add {C}.`` is intentionally dropped — the
    static-side ``make_utility_land`` doesn't add an explicit ability
    for it, relying on the engine's auto-tap-for-cost fallback.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) not in (2, 3):
        return None
    keywords: frozenset[str] = frozenset()
    if len(lines) == 3:
        kw_match = _KEYWORD_LINE_RE.match(lines[0])
        if kw_match is None:
            return None
        kw = kw_match.group(1).lower()
        if kw not in _LAND_KEYWORD_WHITELIST:
            return None
        keywords = frozenset({kw})
        lines = lines[1:]
    if lines[0] != _DROPPED_TAP_FOR_C_LINE:
        return None
    paid_match = _PAID_FANCY_MANA_RE.match(lines[1])
    if paid_match is None:
        return None
    body = paid_match.group("body")
    factory = _PAID_FANCY_MANA_BODIES.get(body)
    if factory is None:
        return None
    cost_str = paid_match.group("cost")
    return make_utility_land(
        card["name"],
        keywords=keywords,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost(cost_str),
                    mana_str=cost_str,
                    tap_self=True,
                ),
                effect=factory(),
                is_mana_ability=True,
            ),
        ),
    )


# Keyword-only utility lands.
#
# Plain ``Land`` cards (no supertypes, no subtypes) whose oracle text
# is the strict three-line shape:
#   1. ``This land enters tapped.``
#   2. <single-keyword-line>      (on ``_LAND_KEYWORD_WHITELIST``)
#   3. ``{T}: Add {C}.``          (intentionally dropped — the
#      static-side ``make_utility_land`` doesn't add an explicit
#      ability for it; the engine's auto-tap-for-cost generic-mana
#      fallback covers tapping for ``{C}``)
#
# Currently claims:
# - Cathedral of War — ``This land enters tapped.`` +
#   ``Exalted (...)`` + ``{T}: Add {C}.``
#
# The keyword-line reminder text is stripped per-line via
# ``_strip_reminder_text`` before the ``_KEYWORD_LINE_RE`` lookup.
# Distinct from the paid-fancy-mana branch (which expects a paid
# mana ability after ``{T}: Add {C}.``) and the colorless-utility
# branch (which doesn't model ``enters_tapped`` and doesn't accept
# a keyword line).
_KEYWORD_TAPPED_TAP_FOR_C_LINE = "This land enters tapped."


def _try_build_keyword_colorless_utility_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a keyword-only colorless utility ``CardPrinting`` if
    ``text`` matches the strict three-line ``This land enters
    tapped.`` + <keyword> + ``{T}: Add {C}.`` shape, else ``None``.

    Plain ``Land`` only (no supertypes, no subtypes). The keyword
    line is restricted to a single capitalized word on
    ``_LAND_KEYWORD_WHITELIST`` (today: ``Exalted`` for Cathedral of
    War). The ``{T}: Add {C}.`` line is intentionally not modeled as
    an explicit activated ability — the engine's auto-tap-for-cost
    generic-mana fallback covers it, matching the static side's
    ``make_utility_land(enters_tapped=True, keywords=...)`` shape.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(raw_lines) != 3:
        return None
    lines = [_strip_reminder_text(ln) for ln in raw_lines]
    if lines[0] != _KEYWORD_TAPPED_TAP_FOR_C_LINE:
        return None
    kw_match = _KEYWORD_LINE_RE.match(lines[1])
    if kw_match is None:
        return None
    kw = kw_match.group(1).lower()
    if kw not in _LAND_KEYWORD_WHITELIST:
        return None
    if lines[2] != _DROPPED_TAP_FOR_C_LINE:
        return None
    return make_utility_land(
        card["name"],
        enters_tapped=True,
        keywords=frozenset({kw}),
    )


# Generic-paid single-effect utility lands.
#
# Plain ``Land`` cards (no supertypes, no subtypes) whose oracle text
# is the strict two-line shape:
#   1. ``{T}: Add {C}.``
#   2. ``<MANA-COST>, {T}: <BODY>.[ <RIDER>.]``
# where ``<MANA-COST>`` is a generic-mana cost (e.g. ``{1}``, ``{2}``,
# ``{4}``) and ``<BODY>`` is on a per-card body whitelist that maps to
# a single bespoke ``Effect`` instance. The static side wraps that
# effect in a single ``ActivatedAbility`` whose cost carries the parsed
# mana plus ``tap_self=True``. The optional trailing ``<RIDER>`` is a
# fixed activation-condition phrase parsed off ``_PAID_EFFECT_RIDERS``
# and surfaced as an extra flag on the ``ActivationCost``.
#
# Distinct from the tap-and-sac branch (those costs include a sac
# clause) and the paid-fancy-mana branch (those bodies produce mana).
# Currently claims:
# - Bonders' Enclave — ``{3}, {T}: Draw a card. Activate only if you
#   control a creature with power 4 or greater.``
# - Deserted Temple — ``{1}, {T}: Untap target land.``
# - Mystifying Maze — ``{4}, {T}: Exile target attacking creature an
#   opponent controls. At the beginning of the next end step, return
#   it to the battlefield tapped under its owner's control.``
# - Terrain Generator — ``{2}, {T}: You may put a basic land card from
#   your hand onto the battlefield tapped.``
#
# Adding a new card with the same shape is a one-line table extension:
# add the exact body surface form (no trailing period — the regex
# strips it) to ``_PAID_EFFECT_BODIES`` paired with a factory that
# returns a fresh ``Effect`` instance. Bodies / cost shapes outside
# the table fall through to the silent-skip path.
#
# The ``{T}`` portion of the activation cost is optional in the regex:
# Mutavault's ``{1}: This land becomes a 2/2 creature ...`` line has
# no tap component, only a generic-mana payment. When the regex
# matches without ``{T}`` (i.e. the ``tap`` named group is empty),
# ``tap_self`` is omitted from the resulting ``ActivationCost``.
_PAID_EFFECT_RE = re.compile(
    r"^(?P<cost>(?:\{\d+\})+)(?P<tap>, \{T\})?: (?P<rest>.+)\.$"
)


def _paid_effect_untap_target_land() -> Effect:
    return UntapTargetLand()


def _paid_effect_exile_attacking_until_end_step() -> Effect:
    return ExileTargetAttackingCreatureUntilEndStep()


def _paid_effect_put_basic_from_hand_tapped() -> Effect:
    return PutBasicLandFromHandOntoBattlefieldTapped()


def _paid_effect_draw_a_card() -> Effect:
    return DrawCards(amount=1)


def _paid_effect_becomes_copy_of_target_land() -> Effect:
    return BecomesCopyOfTargetLand()


def _paid_effect_move_counter_between_permanents() -> Effect:
    return MovePlusOneCounterBetweenPermanentsYouControl()


def _paid_effect_become_2_2_all_creature_types() -> Effect:
    return BecomeLandCreatureUEOT(power=2, toughness=2)


def _paid_effect_become_inkmoth_nexus() -> Effect:
    return BecomeLandCreatureUEOT(
        power=1, toughness=1,
        granted_keywords=frozenset({"flying", "infect"}),
    )


_PAID_EFFECT_BODIES: dict[str, "callable"] = {
    "Untap target land": _paid_effect_untap_target_land,
    "Exile target attacking creature an opponent controls. "
    "At the beginning of the next end step, return it to the "
    "battlefield tapped under its owner's control":
        _paid_effect_exile_attacking_until_end_step,
    "You may put a basic land card from your hand onto the "
    "battlefield tapped":
        _paid_effect_put_basic_from_hand_tapped,
    "Draw a card": _paid_effect_draw_a_card,
    # Thespian's Stage's ``{2}, {T}: This land becomes a copy of
    # target land, except it has this ability.`` This recognizer
    # claims the land via the standard paid-effect arm; the
    # ``except it has this ability`` clause is part of the body
    # surface form (``BecomesCopyOfTargetLand`` already implements
    # the ability-preserving copy).
    "This land becomes a copy of target land, except it has this "
    "ability":
        _paid_effect_becomes_copy_of_target_land,
    # Nesting Grounds' ``{1}, {T}: Move a counter from target permanent
    # you control onto a second target permanent.`` (paired with the
    # ``Activate only as a sorcery`` rider, which lifts to
    # ``sorcery_speed=True`` on the ability).
    "Move a counter from target permanent you control onto a second "
    "target permanent":
        _paid_effect_move_counter_between_permanents,
    # Mutavault's ``{1}: This land becomes a 2/2 creature with all
    # creature types until end of turn. It's still a land.`` (no
    # ``{T}`` in the activation cost — the regex's optional ``tap``
    # group is empty for this body, so ``tap_self`` is dropped from
    # the resulting ``ActivationCost``). The static side simplifies
    # the printed "with all creature types" clause to a plain 2/2
    # animation; the body literal here pins that simplification by
    # mapping the full printed sentence to a fresh
    # ``BecomeLandCreatureUEOT(power=2, toughness=2)`` instance.
    # Currently the only EoS land matching this body literal is
    # Mutavault; deferred generalization would parameterize the
    # P/T capture and the keyword/subtype tail when a sibling
    # printing appears.
    "This land becomes a 2/2 creature with all creature types "
    "until end of turn. It's still a land":
        _paid_effect_become_2_2_all_creature_types,
    # Inkmoth Nexus's ``{1}: This land becomes a 1/1 Phyrexian
    # Blinkmoth artifact creature with flying and infect until end
    # of turn. It's still a land.`` (with the inline infect
    # reminder stripped earlier). The static side simplifies the
    # printed "Phyrexian Blinkmoth artifact" subtype/type tail to a
    # plain creature animation that keeps only the granted keywords
    # (flying + infect); the body literal pins that simplification
    # by mapping the full printed sentence to a fresh
    # ``BecomeLandCreatureUEOT`` with those two keywords. Currently
    # the only EoS land matching this body literal is Inkmoth
    # Nexus; deferred generalization would parameterize the P/T
    # capture, granted-subtype/type capture, and keyword tail when a
    # sibling printing of similar shape (Blinkmoth Nexus, on its
    # own multi-ability shape, doesn't fit this two-line arm)
    # appears.
    "This land becomes a 1/1 Phyrexian Blinkmoth artifact "
    "creature with flying and infect until end of turn. It's "
    "still a land":
        _paid_effect_become_inkmoth_nexus,
}


# Activation-condition rider phrases. Each entry maps an exact phrase
# (no trailing period) to a callable that mutates either the
# ``ActivationCost`` keyword-arg dict or the ``ActivatedAbility``
# keyword-arg dict in place (or both). The mutator's signature is
# ``(cost_kwargs, ability_kwargs)`` — riders that only affect the
# cost ignore ``ability_kwargs`` and vice versa. Riders outside the
# table fall through to the silent-skip path; bodies without a rider
# also pass through — the recognizer treats the rider as optional.
def _rider_creature_power_four_or_greater(
    cost_kwargs: dict, ability_kwargs: dict,
) -> None:
    cost_kwargs["requires_own_creature_power_at_least"] = 4


def _rider_activate_only_as_a_sorcery(
    cost_kwargs: dict, ability_kwargs: dict,
) -> None:
    ability_kwargs["sorcery_speed"] = True


_PAID_EFFECT_RIDERS: dict[str, "callable"] = {
    "Activate only if you control a creature with power 4 or greater":
        _rider_creature_power_four_or_greater,
    # Nesting Grounds — sorcery-speed rider lifts to
    # ``ActivatedAbility(sorcery_speed=True)``.
    "Activate only as a sorcery": _rider_activate_only_as_a_sorcery,
}


def _try_build_paid_effect_utility_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a generic-paid single-effect utility ``CardPrinting`` if
    ``text`` matches the strict two-line ``{T}: Add {C}.`` +
    ``<MANA>[, {T}]: <BODY>.[ <RIDER>.]`` shape with a body on
    ``_PAID_EFFECT_BODIES`` (and rider, if present, on
    ``_PAID_EFFECT_RIDERS``), else ``None``.

    Plain ``Land`` only (no supertypes, no subtypes). The mana-cost
    capture is restricted to all-generic pips (``{1}``, ``{2}``, …) —
    cards with colored or hybrid pips on the activation cost would
    need a different cost shape and don't fit the current set.

    The ``{T}`` part of the activation cost is optional: Mutavault's
    ``{1}: This land becomes a 2/2 creature ...`` line activates
    without tapping, so ``tap_self`` is conditionally set on the
    ``ActivationCost`` only when the regex's ``tap`` group matched.

    Per-line reminder text is stripped via ``_strip_reminder_text``
    before any matching: Inkmoth Nexus's animation line carries an
    inline ``(It deals damage to creatures in the form of -1/-1
    counters and to players in the form of poison counters.)``
    parenthetical that the engine doesn't need to see; stripping it
    here keeps the body literal in ``_PAID_EFFECT_BODIES`` clean.

    The optional rider is a fixed activation-condition phrase (e.g.
    Bonders' Enclave's ``Activate only if you control a creature
    with power 4 or greater``, Nesting Grounds' ``Activate only as a
    sorcery``) that maps to either an ``ActivationCost`` flag or an
    ``ActivatedAbility`` flag (or both, depending on the rider). The
    rider mutator receives both kwargs dicts and writes into whichever
    is appropriate. Bodies / cost shapes / riders outside their tables
    fall through silently.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(raw_lines) != 2:
        return None
    lines = [_strip_reminder_text(ln) for ln in raw_lines]
    if lines[0] != _TAP_FOR_C_LINE:
        return None
    paid_match = _PAID_EFFECT_RE.match(lines[1])
    if paid_match is None:
        return None
    rest = paid_match.group("rest")
    # Try to peel off a recognized rider sentence first; matching is
    # exact on the trailing ``. <RIDER>`` slice. Whichever known rider
    # the body ends with wins (``startswith`` checks pin the body to
    # the front of ``rest`` after trimming the rider).
    body = rest
    cost_extra: dict = {}
    ability_extra: dict = {}
    for rider, mutator in _PAID_EFFECT_RIDERS.items():
        suffix = ". " + rider
        if rest.endswith(suffix):
            body = rest[: -len(suffix)]
            mutator(cost_extra, ability_extra)
            break
    factory = _PAID_EFFECT_BODIES.get(body)
    if factory is None:
        return None
    cost_str = paid_match.group("cost")
    if paid_match.group("tap"):
        cost_extra["tap_self"] = True
    return make_utility_land(
        card["name"],
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost(cost_str),
                    mana_str=cost_str,
                    **cost_extra,
                ),
                effect=factory(),
                **ability_extra,
            ),
        ),
    )


# Restricted-mana lands.
#
# Plain ``Land`` cards (no supertypes, no subtypes) whose oracle text
# is the strict two-line shape:
#   1. ``{T}: Add {C}.``
#   2. ``{T}: Add <MANA>. <RESTRICTION-PHRASE>.``
# The first line is modeled as an explicit ``AddManaToPool`` mana
# ability (NOT dropped to the auto-tap-for-cost fallback) — restricted
# lands carry both abilities on the static side because the
# unrestricted coin from line 1 is independently spendable. The second
# line's restriction phrase is on a small whitelist that maps to
# ``AddManaToPool.spend_restriction`` tag values; the engine's
# ``_coin_satisfies_context`` consults the tag during cost-pay.
#
# Currently claims:
# - Eldrazi Temple — ``{T}: Add {C}{C}.`` + colorless-Eldrazi
#   restriction ("Spend this mana only to cast colorless Eldrazi
#   spells or activate abilities of colorless Eldrazi.").
#
# Adding a new restriction is a one-line table extension keyed on the
# exact phrase (no trailing period). Adding a new produced-mana shape
# (e.g. ``{T}: Add {U}{U}``) needs the second-line regex to
# accommodate the colored pip set; today's only printing produces
# all-colorless.
_RESTRICTED_MANA_LINE_RE = re.compile(
    r"^\{T\}: Add (?P<mana>(?:\{[CWUBRG]\})+)\. (?P<phrase>.+)\.$"
)


_RESTRICTED_MANA_PHRASES: dict[str, str] = {
    "Spend this mana only to cast colorless Eldrazi spells or "
    "activate abilities of colorless Eldrazi": "colorless_eldrazi",
}


def _try_build_restricted_mana_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a restricted-mana ``CardPrinting`` if ``text`` matches
    the strict two-line ``{T}: Add {C}.`` + ``{T}: Add <MANA>.
    <PHRASE>.`` shape with a phrase on ``_RESTRICTED_MANA_PHRASES``,
    else ``None``.

    Plain ``Land`` only (no supertypes, no subtypes). The mana line
    must be all-colorless ``{C}+``. Both abilities are modeled
    explicitly on the printing's ``activated_abilities`` (the first
    is the unrestricted base coin; the second carries the
    restriction tag).
    """
    if supertypes:
        return None
    if subtypes:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    if lines[0] != _TAP_FOR_C_LINE:
        return None
    m = _RESTRICTED_MANA_LINE_RE.match(lines[1])
    if m is None:
        return None
    mana_str = m.group("mana")
    pips = re.findall(r"\{([CWUBRG])\}", mana_str)
    if not pips or any(p != "C" for p in pips):
        return None
    phrase = m.group("phrase")
    tag = _RESTRICTED_MANA_PHRASES.get(phrase)
    if tag is None:
        return None
    return make_utility_land(
        card["name"],
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("C", 1),)),
                is_mana_ability=True,
            ),
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(
                    produces=(("C", len(pips)),),
                    spend_restriction=tag,
                ),
                is_mana_ability=True,
            ),
        ),
    )


# Duskmourn "Verge cycle" dual lands (Blazemire Verge, Floodfarm Verge,
# Gloomlake Verge, Hushwood Verge, Thornspire Verge). Plain ``Land``,
# no supertypes/subtypes, exactly two lines:
#   1. ``{T}: Add {<C1>}.``
#   2. ``{T}: Add {<C2>}. Activate only if you control a <T1> or a
#      <T2>.``
# The first ability is unconditional; the second produces the partner
# color but is gated on the activator controlling at least one
# permanent of either of the two named subtypes (always basic-land
# subtypes on Verges). The gate threads through ``ActivationCost.
# requires_control_of_subtype``; legal_actions consults effective_subtypes.
_VERGE_FIRST_LINE_RE = re.compile(r"^\{T\}: Add \{([WUBRGC])\}\.$")
_VERGE_SECOND_LINE_RE = re.compile(
    r"^\{T\}: Add \{(?P<color>[WUBRGC])\}\. "
    r"Activate only if you control an? (?P<t1>[A-Z][a-z]+) "
    r"or an? (?P<t2>[A-Z][a-z]+)\.$"
)


def _try_build_verge_dual_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a Verge-dual ``CardPrinting`` if ``text`` matches the
    two-line Duskmourn Verge shape, else ``None``.

    Plain ``Land`` only (no supertypes, no subtypes). The two colors
    must differ; the gated second activation requires the activator to
    control a permanent whose effective subtypes include at least one
    of the two named subtypes (capitalized words on the right of the
    "Activate only if you control a X or a Y" clause).
    """
    if supertypes:
        return None
    if subtypes:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    first = _VERGE_FIRST_LINE_RE.match(lines[0])
    if first is None:
        return None
    second = _VERGE_SECOND_LINE_RE.match(lines[1])
    if second is None:
        return None
    c1 = first.group(1)
    c2 = second.group("color")
    if c1 == c2:
        return None
    t1 = second.group("t1")
    t2 = second.group("t2")
    return make_utility_land(
        card["name"],
        produces=frozenset({c1, c2}),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=((c1, 1),)),
                is_mana_ability=True,
            ),
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True,
                    requires_control_of_subtype=(t1, t2),
                ),
                effect=AddManaToPool(produces=((c2, 1),)),
                is_mana_ability=True,
            ),
        ),
    )


# Pure tap-and-sac fetch lands (Terramorphic Expanse). A plain
# ``Land`` (no supertypes, no subtypes) whose ENTIRE oracle text is
# the single line:
#
#     {T}, Sacrifice this land: <BODY>.
#
# Distinct from ``_try_build_tap_sac_utility_land`` which gates on a
# preceding ``{T}: Add {C}.`` line. Bodies are on a per-card whitelist
# pinning the exact surface form to a fresh ``Effect`` instance. The
# produces set is empty — these lands tap only to pay their own
# sacrifice activation, never to mint mana.
_FETCH_LAND_BODIES: dict[str, "callable"] = {
    "Search your library for a basic land card, put it onto the "
    "battlefield tapped, then shuffle":
        lambda: SearchLibraryForBasicLandTapped(count=1),
}


def _try_build_fetch_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a fetch-land ``CardPrinting`` if ``text`` is a single
    ``{T}, Sacrifice this land: <BODY>.`` line whose body is on
    ``_FETCH_LAND_BODIES``, else ``None``.

    Plain ``Land`` only (no supertypes, no subtypes). The cost is
    ``tap_self`` + ``sacrifice_self``; ``produces`` stays empty —
    fetch lands are not a mana source.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    line = text.strip()
    if "\n" in line:
        return None
    m = _TAP_AND_SAC_SELF_RE.match(line)
    if m is None:
        return None
    body = m.group("body")
    factory = _FETCH_LAND_BODIES.get(body)
    if factory is None:
        return None
    return make_utility_land(
        card["name"],
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True, sacrifice_self=True,
                ),
                effect=factory(),
            ),
        ),
    )


# Duskmourn "horror dual" cycle (Abandoned Campground, Bleeding Woods,
# Etched Cornfield, Lakeside Shack, Murky Sewer, Neglected Manor,
# Peculiar Lighthouse, Raucous Carnival, Razortrap Gorge, Strangled
# Cemetery). Plain ``Land``, no supertypes/subtypes, exactly two
# lines:
#   1. ``This land enters tapped unless a player has <N> or less life.``
#   2. ``{T}: Add {<C1>} or {<C2>}.``
# The condition is a deterministic state check at ETB (no agent
# choice). The threshold flows through
# ``CardPrinting.enters_tapped_unless_any_player_life_at_most``;
# ``_play_land`` reads it after applying the default ``enters_tapped``.
_LOW_LIFE_TAPPED_LINE_RE = re.compile(
    r"^This land enters tapped unless a player has "
    r"(?P<threshold>\d+) or less life\.$"
)
_LOW_LIFE_DUAL_TAP_LINE_RE = re.compile(
    r"^\{T\}: Add \{(?P<c1>[WUBRG])\} or \{(?P<c2>[WUBRG])\}\.$"
)


def _try_build_low_life_dual_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a low-life-dual ``CardPrinting`` if ``text`` matches the
    Duskmourn horror-dual two-line shape, else ``None``.

    Plain ``Land`` only (no supertypes, no subtypes). The condition
    line names the threshold (always 13 in the printed cycle, but
    captured generically). The mana line names two distinct colors;
    they're set as the ``produces`` frozenset and the dual-mana
    activation goes on the printing as a single mana ability via the
    ``AddNManaOfChosenColor`` primitive.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    cond = _LOW_LIFE_TAPPED_LINE_RE.match(lines[0])
    if cond is None:
        return None
    tap = _LOW_LIFE_DUAL_TAP_LINE_RE.match(lines[1])
    if tap is None:
        return None
    c1 = tap.group("c1")
    c2 = tap.group("c2")
    if c1 == c2:
        return None
    threshold = int(cond.group("threshold"))
    return make_utility_land(
        card["name"],
        produces=frozenset({c1, c2}),
        enters_tapped_unless_any_player_life_at_most=threshold,
    )


# Optional-copy-from-graveyard Cave land. Plain ``Land — Cave`` (no
# supertypes), exactly two lines:
#   1. ``You may have this land enter tapped as a copy of any land card
#      in a graveyard, except it's a Cave in addition to its other
#      types.``
#   2. ``{T}: Add {C}.``  (intentionally dropped — the engine's
#      auto-tap-for-cost generic-mana fallback covers tapping for
#      ``{C}``; ``make_utility_land`` doesn't add an explicit ability.)
#
# The first line maps to ``optional_copy_land_from_graveyard=True`` on
# the ``CardPrinting``, threading the static-side flag through.
# Currently the only EoS land matching this exact two-line shape is
# Echoing Deeps; recognizer is a literal-line match (deferred
# generalization to a parameterized "<subtype>-in-addition-to-its-
# other-types" recognizer if a sibling printing appears).
_OPTIONAL_COPY_CAVE_FIRST_LINE = (
    "You may have this land enter tapped as a copy of any land card "
    "in a graveyard, except it's a Cave in addition to its other "
    "types."
)


def _try_build_optional_copy_cave_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return an optional-copy-from-graveyard Cave ``CardPrinting`` if
    ``text`` matches the strict two-line Echoing Deeps shape, else
    ``None``.

    ``Land — Cave`` only (no supertypes, single ``Cave`` subtype). The
    first line is a literal match against the printed copy-from-
    graveyard sentence; the second line is the dropped
    ``{T}: Add {C}.``. The static-side
    ``optional_copy_land_from_graveyard=True`` flag carries the
    one-card behavior. Today's only printing matching this shape is
    Echoing Deeps; deferred generalization to a parameterized
    ``<subtype>-in-addition-to-its-other-types`` recognizer would
    happen if a sibling printing appears.
    """
    if supertypes:
        return None
    if subtypes != ("Cave",):
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    if lines[0] != _OPTIONAL_COPY_CAVE_FIRST_LINE:
        return None
    if lines[1] != _DROPPED_TAP_FOR_C_LINE:
        return None
    return make_utility_land(
        card["name"], subtypes_str="Cave",
        optional_copy_land_from_graveyard=True,
    )


# Opening-hand luck-counter land. Plain ``Legendary Land`` (legendary
# supertype, no subtypes), exactly two lines:
#   1. ``If this card is in your opening hand and you're not the
#      starting player, you may begin the game with <NAME> on the
#      battlefield with a luck counter on it. If you do, exile a card
#      from your hand.``
#   2. ``{T}: Add {C}. If <NAME> has a luck counter on it, instead add
#      one mana of any color.``
#
# Both lines reference the card name (matched generically via the
# captured ``<NAME>`` placeholder, so the recognizer doesn't hard-code
# "Gemstone Caverns"). The opening-hand replacement on line 1 isn't
# modeled by the engine; the static side simplifies the card to "always
# has a luck counter on it" which collapses line 2's conditional to its
# "instead" branch — a single tap-for-any-color mana ability. The
# recognizer mirrors that simplification.
#
# Per parser/CLAUDE.md: literal-line recognizers are acceptable when
# "exactly one card in the current data pool fits that printed surface"
# and the docstring "explicitly notes why it isn't generalized today
# (typically: 'only card in the pool with this shape; broader grammar
# deferred until a second example exists')." Gemstone Caverns is the
# only EoS land with this opening-hand-replacement-plus-conditional-
# tap shape; deferred generalization to a parameterized luck-counter
# template would happen if a sibling printing appears.
_OPENING_HAND_LUCK_COUNTER_LINE_RE = re.compile(
    r"^If this card is in your opening hand and you're not the "
    r"starting player, you may begin the game with (?P<name1>.+) on "
    r"the battlefield with a luck counter on it\. If you do, exile a "
    r"card from your hand\.$"
)
_LUCK_COUNTER_TAP_LINE_RE = re.compile(
    r"^\{T\}: Add \{C\}\. If (?P<name2>.+) has a luck counter on it, "
    r"instead add one mana of any color\.$"
)


def _try_build_opening_hand_luck_counter_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return an opening-hand luck-counter ``CardPrinting`` if ``text``
    matches the strict two-line Gemstone Caverns shape, else ``None``.

    ``Legendary Land`` only (legendary supertype, no subtypes). Both
    captured ``<NAME>`` placeholders must equal ``card["name"]`` (the
    card refers to itself by name). The static side simplifies the
    opening-hand replacement to "always has a luck counter", collapsing
    the conditional tap line to a single ``AddManaToPool(produces=(
    ("any", 1),))`` activation.

    Per parser/CLAUDE.md: literal-line recognizers are acceptable only
    when "exactly one card in the current data pool fits that printed
    surface" and the docstring explicitly notes deferred generalization.
    Gemstone Caverns is the only EoS land matching this shape; broader
    grammar deferred until a second example exists.
    """
    if supertypes != ("Legendary",):
        return None
    if subtypes:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    m1 = _OPENING_HAND_LUCK_COUNTER_LINE_RE.match(lines[0])
    if m1 is None:
        return None
    m2 = _LUCK_COUNTER_TAP_LINE_RE.match(lines[1])
    if m2 is None:
        return None
    name = card["name"]
    if m1.group("name1") != name or m2.group("name2") != name:
        return None
    return make_utility_land(
        card["name"], legendary=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
        ),
    )


# Chosen-color Cave land. ``Land — Cave`` (no supertypes, single
# ``Cave`` subtype), exactly three lines:
#   1. ``This land enters tapped. As it enters, choose a color.``
#   2. ``{T}: Add one mana of the chosen color.``
#   3. ``{T}: Add two mana of the chosen color. Spend this mana only to
#      activate abilities of land sources.``
#
# The ``As it enters, choose a color`` clause and the per-activation
# "of the chosen color" specifier are simplified on the static side to
# the ``"any"`` color (the engine's mana primitive doesn't carry a
# per-permanent chosen-color slot for lands today). The two
# activations land as separate mana abilities: the first unrestricted,
# the second tagged with ``spend_restriction="land_activation"``.
#
# Per parser/CLAUDE.md: literal-line recognizers are acceptable when
# "exactly one card in the current data pool fits that printed surface"
# and the docstring notes deferred generalization. Sunken Citadel is
# the only EoS land matching this chosen-color-Cave shape; broader
# grammar (parameterized over the second-line restriction phrase, or
# extended to non-Cave chosen-color lands) deferred until a sibling
# printing exists.
_CHOSEN_COLOR_CAVE_LINE_1 = "This land enters tapped. As it enters, choose a color."
_CHOSEN_COLOR_CAVE_LINE_2 = "{T}: Add one mana of the chosen color."
_CHOSEN_COLOR_CAVE_LINE_3 = (
    "{T}: Add two mana of the chosen color. Spend this mana only to "
    "activate abilities of land sources."
)


def _try_build_chosen_color_cave_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a chosen-color Cave ``CardPrinting`` if ``text`` matches
    the strict three-line Sunken Citadel shape, else ``None``.

    ``Land — Cave`` only (no supertypes, single ``Cave`` subtype). The
    static-side simplification maps "the chosen color" to the
    engine's ``"any"`` color tag for both produced amounts; the second
    activation carries a ``spend_restriction="land_activation"`` tag.

    Per parser/CLAUDE.md: a literal-line recognizer is acceptable
    here because Sunken Citadel is "the only card in the current data
    pool that fits that printed surface" and "broader grammar deferred
    until a second example exists" (e.g. another chosen-color Cave or
    a non-Cave chosen-color land that simplifies the same way).
    """
    if supertypes:
        return None
    if subtypes != ("Cave",):
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 3:
        return None
    if lines[0] != _CHOSEN_COLOR_CAVE_LINE_1:
        return None
    if lines[1] != _CHOSEN_COLOR_CAVE_LINE_2:
        return None
    if lines[2] != _CHOSEN_COLOR_CAVE_LINE_3:
        return None
    return make_utility_land(
        card["name"], subtypes_str="Cave", enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("any", 1),)),
                is_mana_ability=True,
            ),
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(
                    produces=(("any", 2),),
                    spend_restriction="land_activation",
                ),
                is_mana_ability=True,
            ),
        ),
    )


def _try_build_colorless_utility_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a colorless-utility-land ``CardPrinting`` if ``card`` has
    a plain ``Land`` type line (no supertypes, no subtypes) and its
    oracle text starts with ``"{T}: Add {C}."``, else ``None``.

    Matches the simplified Secluded Starforge shape: tap-for-{C} plus
    additional activated abilities the parser doesn't model. The extra
    abilities are intentionally dropped, mirroring the static-side
    ``make_colorless_land`` simplification — the land still works as a
    generic-mana source via the engine's auto-tap-for-cost fallback.

    Defensive: requires ``produced_mana`` (when present on the Scryfall
    record) to contain only colorless. This blocks accidentally
    matching a hypothetical colored-utility land whose first line
    happens to be ``{T}: Add {C}.``.

    Set-gate: skips cards from the Stellar Sights (``eos``) and
    Special Guests (``spg``) bonus sheets. Those reprints have their
    activated abilities fully modeled in the static registry via
    ``make_utility_land`` (and per-card bespoke effects), so the
    simplification would produce a parity mismatch. They are claimed
    via dedicated builders (e.g. ``_try_build_manland``) or skipped
    silently. Synthetic test fixtures and EoE main set cards (no set
    or ``set == "eoe"``) fall through normally.
    """
    if supertypes:
        return None
    if subtypes:
        return None
    if card.get("set") in {"eos", "spg"}:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None
    if lines[0] != _COLORLESS_TAP_LINE:
        return None
    produced = card.get("produced_mana")
    if produced is not None and set(produced) - {"C"}:
        return None
    return make_colorless_land(name=card["name"])
