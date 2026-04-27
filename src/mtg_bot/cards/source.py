"""Pluggable card-source abstraction.

Card printings reach the engine through a ``CardSource``. Today's
production source is ``StaticCardSource``, which delegates to the
hand-coded printings in ``mtg_bot.cards.registry``. The future
oracle-text parser will live as a second ``CardSource`` implementation
(see ``cards.parser_source``).

The active source is module-global; ``set_active_source`` swaps it.
Production code never calls that — it's the seam parity tests use to
point the engine at an alternative source for the duration of a test
session.

``FallbackCardSource`` is a development-only decorator: it routes
claimed names to the parser source and falls back to the static
source for everything else, so suite-wide parity can grow
incrementally as parser coverage grows. It is never the production
source.
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


class FallbackCardSource:
    """Routes claimed names to ``primary``; falls back to ``fallback``
    for everything else.

    Deck building is delegated to ``fallback``: the primary source
    typically covers a partial pool during parser build-out, and decks
    need to be built from a complete pool so the engine has cards to
    play with. When the primary's lookups are then exercised, claimed
    cards return the primary's printing and the rest fall through.
    """

    def __init__(
        self, primary: CardSource, fallback: CardSource
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def get_printings(self) -> dict[str, CardPrinting]:
        merged = dict(self.fallback.get_printings())
        merged.update(self.primary.get_printings())
        return merged

    def build_mono_color_deck(
        self, color: str, seed: int | None = None
    ) -> list[str]:
        return self.fallback.build_mono_color_deck(color, seed=seed)


_active_source: CardSource = StaticCardSource()


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

    - ``None`` / ``""`` / ``"static"``: the default ``StaticCardSource``.
    - ``"parser"``: the bare parser source, strict — cards the parser
      doesn't claim are simply absent.
    - ``"parser_with_fallback"``: the parser wrapped by
      ``FallbackCardSource`` over the static source. Use during
      parser build-out to keep the suite green while parser coverage
      is incomplete.
    """
    normalized = (value or "static").lower()
    if normalized == "static":
        return StaticCardSource()
    from mtg_bot.cards.parser_source import StubParserCardSource

    if normalized == "parser":
        return StubParserCardSource()
    if normalized == "parser_with_fallback":
        return FallbackCardSource(StubParserCardSource(), StaticCardSource())
    raise ValueError(
        f"unknown MTG_BOT_CARD_SOURCE value: {value!r} "
        f"(expected 'static', 'parser', or 'parser_with_fallback')"
    )
