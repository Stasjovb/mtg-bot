"""Pluggable card-source abstraction.

Card printings reach the engine through a ``CardSource``. Today's only
implementation, ``StaticCardSource``, delegates to the hand-coded
printings in ``mtg_bot.cards.registry``. A future
``OracleParserCardSource`` will produce equivalent printings by parsing
Scryfall oracle text. Both expose the same protocol so the engine can
be pointed at either one without further code changes.

Production code never calls ``set_active_source`` — it's an escape
hatch for parity-testing alternative sources against the existing
test suite.
"""

from __future__ import annotations

from typing import Protocol

from mtg_bot.cards.base import CardPrinting


class CardSource(Protocol):
    """Provides the set of card printings the engine knows about."""

    def get_printings(self) -> dict[str, CardPrinting]:
        """All card printings keyed by name (lands + nonlands)."""
        ...

    def build_mono_color_deck(
        self, color: str, seed: int | None = None
    ) -> list[str]:
        """Return a 60-card mono-color deck of card names drawn from
        this source's pool."""
        ...


class StaticCardSource:
    """Wraps the hand-coded ``cards/registry.py`` printings."""

    def get_printings(self) -> dict[str, CardPrinting]:
        from mtg_bot.cards.registry import all_printings

        return all_printings()

    def build_mono_color_deck(
        self, color: str, seed: int | None = None
    ) -> list[str]:
        from mtg_bot.cards.registry import build_mono_color_deck

        return build_mono_color_deck(color, seed=seed)


_active_source: CardSource = StaticCardSource()


def get_active_source() -> CardSource:
    return _active_source


def set_active_source(source: CardSource) -> None:
    global _active_source
    _active_source = source
