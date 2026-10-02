"""Parser recognizers for the Vintage Roto P3 bucket: mana, costs and
cast permissions (``docs/ROTO_COVERAGE_PLAN.md`` section 4).

Every entry point is a last-resort fallback hooked into a shared
dispatcher with a single import-and-call, so no phrase an older
recognizer claims changes meaning. Like the cube buckets, the grammar is
switched off for printings that exist only in the EoE-era dumps (the
shared ``creature_rmc_grammar`` switch), so no EoE printing's parse can
change. Engine effects live in ``effects/generic/roto_mana.py``.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


# ---------------------------------------------------------------------------
# "Activate only if <condition>." riders
# ---------------------------------------------------------------------------

# "you control a[n] <card type>" (Spire of Industry: "Activate only if you
# control an artifact.").
_YOU_CONTROL_A_TYPE_RE = re.compile(
    r"^you control an? (?P<type>artifact|creature|enchantment|land"
    r"|planeswalker)$"
)


def parse_activate_only_if_condition(phrase: str):
    """The ``Condition`` for an ``Activate only if <phrase>.`` rider the
    base activated grammar doesn't know, or ``None``."""
    if _disabled():
        return None
    m = _YOU_CONTROL_A_TYPE_RE.match(phrase)
    if m is not None:
        from mtg_bot.effects.conditions import ControlPermanent
        from mtg_bot.effects.object_predicates import (
            IsArtifact,
            IsCreature,
            IsEnchantment,
            IsLand,
            IsPlaneswalker,
        )

        pred = {
            "artifact": IsArtifact,
            "creature": IsCreature,
            "enchantment": IsEnchantment,
            "land": IsLand,
            "planeswalker": IsPlaneswalker,
        }[m.group("type")]()
        return ControlPermanent(pred)
    return None


# ---------------------------------------------------------------------------
# Effect phrases
# ---------------------------------------------------------------------------

# "add {C} for each card named <name> in each graveyard" (Rite of Flame).
_ADD_PER_CARD_NAMED_IN_GRAVEYARDS_RE = re.compile(
    r"^add \{(?P<c>[WUBRGC])\} for each card named (?P<name>.+) in each "
    r"graveyard$"
)
# "destroy all <permanents> that entered this turn" (Force of Despair).
_DESTROY_ALL_ENTERED_THIS_TURN_RE = re.compile(
    r"^destroy all (?P<np>.+?) that entered this turn$"
)


def parse_roto_mana_effect(phrase: str) -> Effect | None:
    """Effect phrases of this bucket (the last ``_parse_effect``
    fallback)."""
    if _disabled():
        return None
    from mtg_bot.effects.generic import roto_mana as rm

    m = _ADD_PER_CARD_NAMED_IN_GRAVEYARDS_RE.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.mana import AddManaOfColorPerCount

        return AddManaOfColorPerCount(
            color=m.group("c"),
            amount=rm.CardsNamedInAllGraveyards(m.group("name")),
        )
    m = _DESTROY_ALL_ENTERED_THIS_TURN_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect

        base = _parse_effect(f"destroy all {m.group('np')}")
        if base is None or getattr(base, "action", None) != "destroy":
            return None
        from dataclasses import replace

        return replace(
            base,
            permanent_filter=base.permanent_filter & rm.EnteredThisTurn(),
            label=f"{base.label} that entered this turn",
        )
    return None


__all__ = [
    "parse_activate_only_if_condition",
    "parse_roto_mana_effect",
]
