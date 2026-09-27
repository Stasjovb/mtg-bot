"""Builder dispatch for the non-normal card layouts (cube layouts bucket).

Runs first in ``source._build_printing_unpinned`` and returns ``None``
for every card that isn't one of these layouts, so the per-type builders
see exactly the cards they saw before:

* double-faced cards (``layout`` ``transform`` / ``modal_dfc``) --
  :mod:`mtg_bot.cards.parser.dfc_builder`;
* split cards with two instant / sorcery halves (``layout == "split"``;
  Rooms are left to ``room_builder``) --
  :mod:`mtg_bot.cards.parser.split_builder`.
"""

from __future__ import annotations

from mtg_bot.cards.base import CardPrinting


def _build_layout_printing(card: dict) -> CardPrinting | None:
    from mtg_bot.cards.parser.dfc_builder import _build_dfc_printing
    from mtg_bot.cards.parser.split_builder import _build_split_printing

    for builder in (_build_dfc_printing, _build_split_printing):
        built = builder(card)
        if built is not None:
            return built
    return None
