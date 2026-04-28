"""Whole-card exact-text dispatch for Special Guests bonus-sheet
single-line statics.

A handful of EoE Special Guests (`spg` set subset) are reprints whose
entire oracle text is a single sentence that the static registry
models via a bespoke printing-level flag rather than a generic
``StaticAbility`` or ``TriggeredAbility``. These cards don't fit the
per-builder grammar cleanly:

- They're across multiple card types (Creature for Magus of the Moon,
  Enchantment for Deafening Silence) — no one builder owns them.
- Their printed effect maps 1:1 to a single ``CardPrinting`` boolean
  flag, so claiming via grammar would route through a ``StaticAbility``
  or ``TriggeredAbility`` shape that doesn't match the static side.

This module sidesteps both by claiming via a name-keyed
exact-oracle-text whitelist that returns the canonical static
``CardPrinting`` directly. Adding a new entry is one factory + one
mapping line; the surface-form check is the entire safety story.

Currently claimed:

- **Magus of the Moon** (Special Guest): 2/2 Human Wizard whose only
  ability is the printing-level ``nonbasic_lands_are_mountains=True``
  flag (the engine wires the layer-7 type-replacement effect off this
  flag).
- **Deafening Silence** (Special Guest): Enchantment whose only
  ability is the printing-level
  ``restricts_noncreature_spells_to_one_per_turn=True`` flag.
"""

from __future__ import annotations

from mtg_bot.cards.base import CardPrinting, parse_mana_cost
from mtg_bot.cards.parser.type_line import _parse_type_line


def _build_magus_of_the_moon() -> CardPrinting:
    type_line = "Creature — Human Wizard"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    mana_str = "{2}{R}"
    return CardPrinting(
        name="Magus of the Moon",
        mana_cost_str=mana_str,
        mana_cost=parse_mana_cost(mana_str),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        power=2,
        toughness=2,
        nonbasic_lands_are_mountains=True,
    )


def _build_deafening_silence() -> CardPrinting:
    type_line = "Enchantment"
    supertypes, card_types, subtypes = _parse_type_line(type_line)
    mana_str = "{W}"
    return CardPrinting(
        name="Deafening Silence",
        mana_cost_str=mana_str,
        mana_cost=parse_mana_cost(mana_str),
        type_line=type_line,
        supertypes=supertypes,
        card_types=card_types,
        subtypes=subtypes,
        restricts_noncreature_spells_to_one_per_turn=True,
    )


# Name → (expected oracle text, factory). The oracle text check is a
# defensive sanity belt: if Scryfall ever changes a printed wording
# the parser falls through to the silent-skip path rather than
# claiming a card whose text no longer matches the modeled flag.
_SPECIAL_GUEST_BUILDERS: dict[str, tuple[str, "callable"]] = {
    "Magus of the Moon": (
        "Nonbasic lands are Mountains.",
        _build_magus_of_the_moon,
    ),
    "Deafening Silence": (
        "Each player can't cast more than one noncreature spell each turn.",
        _build_deafening_silence,
    ),
}


def _build_special_guest_printing(card: dict) -> CardPrinting | None:
    """Claim a Special Guests bonus-sheet card via name-keyed
    exact-oracle-text dispatch. Returns the canonical
    ``CardPrinting`` if the card's name and oracle text match an
    entry in ``_SPECIAL_GUEST_BUILDERS``, else ``None``.

    Only matches cards from the Special Guests bonus sheet (set code
    ``spg``) — Scryfall's main-set printing of the same name (if any
    ever lands in EoE proper) wouldn't claim through this path.
    """
    if card.get("set") != "spg":
        return None
    entry = _SPECIAL_GUEST_BUILDERS.get(card.get("name", ""))
    if entry is None:
        return None
    expected_text, factory = entry
    if card.get("oracle_text", "").strip() != expected_text:
        return None
    return factory()
