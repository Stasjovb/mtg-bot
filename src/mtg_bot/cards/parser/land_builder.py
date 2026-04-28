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

Other non-basic shapes (Planet lands, Command Bridge-style sac-self
utility lands) require Station, sac-self triggers, or any-color mana
abilities that the parser doesn't yet wire end-to-end — silent skip,
same pattern as creature/spell.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    AddOneManaFromControlledLandsProductions,
    AddOneManaOfChosenPermanentColor,
    BecomeLandCreatureUEOT,
    CardPrinting,
    DealDamageToControllerAndAddMana,
    DestroyTargetLand,
    Effect,
    ExileTargetAttackingCreatureUntilEndStep,
    GainLife,
    PumpSelfXPowerUEOT,
    PutBasicLandFromHandOntoBattlefieldTapped,
    PutPlusOneCounterOnSelf,
    ReturnTargetLandFromGraveyardToHand,
    SwitchSourcePowerToughnessUEOT,
    TriggeredAbility,
    UntapTargetLand,
    make_basic_land,
    make_colorless_land,
    make_shock_land,
    make_utility_land,
    parse_mana_cost,
)
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.effects.predicates import Event, IsSelf


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
    # Non-basic land shapes follow.
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
    paid_effect = _try_build_paid_effect_utility_land(
        card, text, supertypes, subtypes,
    )
    if paid_effect is not None:
        return paid_effect
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


_LAND_KEYWORD_WHITELIST = frozenset({"indestructible"})


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


# Generic-paid single-effect utility lands.
#
# Plain ``Land`` cards (no supertypes, no subtypes) whose oracle text
# is the strict two-line shape:
#   1. ``{T}: Add {C}.``
#   2. ``<MANA-COST>, {T}: <BODY>.``
# where ``<MANA-COST>`` is a generic-mana cost (e.g. ``{1}``, ``{2}``,
# ``{4}``) and ``<BODY>`` is on a per-card body whitelist that maps to
# a single bespoke ``Effect`` instance. The static side wraps that
# effect in a single ``ActivatedAbility`` whose cost carries the parsed
# mana plus ``tap_self=True``.
#
# Distinct from the tap-and-sac branch (those costs include a sac
# clause) and the paid-fancy-mana branch (those bodies produce mana).
# Currently claims:
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
_PAID_EFFECT_RE = re.compile(
    r"^(?P<cost>(?:\{\d+\})+), \{T\}: (?P<body>.+)\.$"
)


def _paid_effect_untap_target_land() -> Effect:
    return UntapTargetLand()


def _paid_effect_exile_attacking_until_end_step() -> Effect:
    return ExileTargetAttackingCreatureUntilEndStep()


def _paid_effect_put_basic_from_hand_tapped() -> Effect:
    return PutBasicLandFromHandOntoBattlefieldTapped()


_PAID_EFFECT_BODIES: dict[str, "callable"] = {
    "Untap target land": _paid_effect_untap_target_land,
    "Exile target attacking creature an opponent controls. "
    "At the beginning of the next end step, return it to the "
    "battlefield tapped under its owner's control":
        _paid_effect_exile_attacking_until_end_step,
    "You may put a basic land card from your hand onto the "
    "battlefield tapped":
        _paid_effect_put_basic_from_hand_tapped,
}


def _try_build_paid_effect_utility_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Return a generic-paid single-effect utility ``CardPrinting`` if
    ``text`` matches the strict two-line ``{T}: Add {C}.`` +
    ``<MANA>, {T}: <BODY>.`` shape with a body on
    ``_PAID_EFFECT_BODIES``, else ``None``.

    Plain ``Land`` only (no supertypes, no subtypes). The mana-cost
    capture is restricted to all-generic pips (``{1}``, ``{2}``, …) —
    cards with colored or hybrid pips on the activation cost would
    need a different cost shape and don't fit the current set.
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
    paid_match = _PAID_EFFECT_RE.match(lines[1])
    if paid_match is None:
        return None
    body = paid_match.group("body")
    factory = _PAID_EFFECT_BODIES.get(body)
    if factory is None:
        return None
    cost_str = paid_match.group("cost")
    return make_utility_land(
        card["name"],
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost(cost_str),
                    mana_str=cost_str,
                    tap_self=True,
                ),
                effect=factory(),
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
