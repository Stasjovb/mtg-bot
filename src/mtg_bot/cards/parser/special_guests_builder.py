"""Whole-card exact-text dispatch for Special Guests bonus-sheet
single-line statics.

A handful of EoE Special Guests (`spg` set subset) are reprints whose
entire oracle text is a single sentence that the static registry
models via a bespoke printing-level flag rather than a generic
``StaticAbility`` or ``TriggeredAbility``. These cards don't fit the
per-builder grammar cleanly:

- They span multiple card types (Enchantment for Deafening Silence)
  — no one builder owns them.
- Their printed effect maps 1:1 to a single ``CardPrinting`` boolean
  flag, so claiming via grammar would route through a ``StaticAbility``
  or ``TriggeredAbility`` shape that doesn't match the static side.

This module sidesteps both by claiming via a name-keyed
exact-oracle-text whitelist that returns the canonical static
``CardPrinting`` directly. Adding a new entry is one factory + one
mapping line; the surface-form check is the entire safety story.

Currently claimed:

- **Deafening Silence** (Special Guest): Enchantment whose only
  ability is the printing-level
  ``restricts_noncreature_spells_to_one_per_turn=True`` flag.

Previously claimed here but now migrated to the unified grammar:

- **Sliver Overlord** (Legendary Creature — Sliver Mutant): migrated
  to the creature builder. Both activated abilities now parse via
  ``_parse_activated_ability_line``:
    * ``{3}: Search your library for a Sliver card, reveal that card,
      put it into your hand, then shuffle.``  — claims via the
      ``_SEARCH_LIBRARY_REVEAL_HAND_SHUFFLE`` regex with the new
      ``"Sliver"`` filter entry (and "reveal that card" variant).
    * ``{3}: Gain control of target Sliver.``  — claims via the new
      ``_GAIN_CONTROL_TARGET_SUBTYPE`` regex dispatching to
      ``GainControlOfTargetSliverPermanently()``.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CardPrinting,
    OptionalPutLandFromHandOntoBattlefield,
    TriggeredAbility,
)
from mtg_bot.effects.predicates import Controlled, Event, _Controller


# Name → (expected oracle text, factory). The oracle text check is a
# defensive sanity belt: if Scryfall ever changes a printed wording
# the parser falls through to the silent-skip path rather than
# claiming a card whose text no longer matches the modeled flag.
# Sliver Overlord was previously in this table but has been migrated
# to the unified creature-builder grammar (see module docstring).
_SPECIAL_GUEST_BUILDERS: dict[str, tuple[str, "callable"]] = {}


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
