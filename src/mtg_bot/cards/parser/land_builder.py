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
    BecomeLandCreatureUEOT,
    CardPrinting,
    make_basic_land,
    make_colorless_land,
    make_shock_land,
    make_utility_land,
    parse_mana_cost,
)
from mtg_bot.cards.parser.type_line import _parse_type_line


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
    if animate_match is not None:
        keywords = _parse_manland_keywords(animate_match.group("keywords"))
        if keywords is None:
            return None
    else:
        animate_match = _MANLAND_ANIMATE_UNBLOCKABLE_RE.match(lines[2])
        if animate_match is None:
            return None
        unblockable = True
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
                ),
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
