"""Pluggable card-source abstraction.

Card printings reach the engine through a ``CardSource``. The
production source is ``OracleParserCardSource``, which walks the
Scryfall JSON dumps under ``data/`` and asks the per-card-type
builders in ``mtg_bot.cards.parser`` to materialize each printing.

The active source is module-global; ``set_active_source`` swaps it.
Production code never calls that — it's the seam tests can use to
point the engine at a fake source for the duration of a session.
"""

from __future__ import annotations

from typing import Protocol

from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.parser_source import OracleParserCardSource


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


_active_source: CardSource = OracleParserCardSource()


def get_active_source() -> CardSource:
    return _active_source


def set_active_source(source: CardSource) -> None:
    global _active_source
    _active_source = source


def card_source_from_env(value: str | None) -> CardSource:
    """Map an ``MTG_BOT_CARD_SOURCE`` env-var value to a concrete
    ``CardSource``. Used by ``tests/conftest.py`` to swap the active
    source for the duration of a test session.

    Recognized values:

    - ``None`` / ``""`` / ``"parser"``: the production
      ``OracleParserCardSource``.

    Any other value raises so typos don't silently become a no-op
    test run.
    """
    normalized = (value or "parser").lower()
    if normalized == "parser":
        return OracleParserCardSource()
    raise ValueError(
        f"unknown MTG_BOT_CARD_SOURCE value: {value!r} "
        f"(expected 'parser')"
    )
