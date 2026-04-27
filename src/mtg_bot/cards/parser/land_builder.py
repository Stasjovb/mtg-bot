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
    CardPrinting,
    make_basic_land,
    make_colorless_land,
    make_shock_land,
)
from mtg_bot.cards.parser.type_line import _parse_type_line


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
    """
    if supertypes:
        return None
    if subtypes:
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
