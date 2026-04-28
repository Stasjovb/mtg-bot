"""Whole-card name-keyed dispatch for Edge of Eternities Planeswalkers.

Planeswalkers have loyalty-activated abilities whose cost type (±N
loyalty counters) the engine doesn't yet model. This module claims
planeswalker cards via a name-keyed exact-dispatch table, mirroring
the ``make_planeswalker`` calls in ``eoe_spells.py`` verbatim. Loyalty
abilities are intentionally dropped; triggered abilities on the walker
still fire normally.

Currently claimed:

- **Tezzeret, Cruel Captain** ``{3}`` — Legendary Planeswalker (Tezzeret,
  loyalty 4). Restored ability: "Whenever an artifact you control enters,
  put a loyalty counter on Tezzeret." The three printed loyalty abilities
  (0/−3/−7) are not modeled.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CardPrinting,
    TriggeredAbility,
    make_planeswalker,
)
from mtg_bot.effects.generic import PutLoyaltyCounterOnSelf
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsArtifact,
    IsSelf,
)


def _build_tezzeret_cruel_captain() -> CardPrinting:
    """Tezzeret, Cruel Captain: Legendary Planeswalker — Tezzeret,
    loyalty 4. Whenever an artifact you control enters (not Tezzeret
    himself), put a loyalty counter on Tezzeret.
    """
    return make_planeswalker(
        "Tezzeret, Cruel Captain", "{3}",
        loyalty=4,
        subtype="Tezzeret",
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsArtifact() & Controlled(YOU) & ~IsSelf(),
                effect=PutLoyaltyCounterOnSelf(amount=1),
            ),
        ),
    )


# Name-keyed dispatch: card name → factory. Each entry mirrors the
# corresponding ``make_planeswalker`` call in ``eoe_spells.py`` exactly.
_PLANESWALKER_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {
    "Tezzeret, Cruel Captain": _build_tezzeret_cruel_captain,
}


def _build_planeswalker_printing(card: dict) -> CardPrinting | None:
    """Claim an EoE planeswalker card via name-keyed dispatch.

    Returns the canonical ``CardPrinting`` if the card's name appears
    in ``_PLANESWALKER_BUILDERS`` and its type line contains
    ``Planeswalker``. Returns ``None`` otherwise so the builder chain
    continues.
    """
    if "Planeswalker" not in card.get("type_line", ""):
        return None
    factory = _PLANESWALKER_BUILDERS.get(card.get("name", ""))
    if factory is None:
        return None
    return factory()
