"""Pluggable card-source abstraction.

Card printings reach the engine through a ``CardSource``. Today's
production source is ``StaticCardSource``, which delegates to the
hand-coded printings in ``mtg_bot.cards.registry``. The future
oracle-text parser will live as a second ``CardSource`` implementation
(see ``cards.parser_source``) and replace the static source wholesale
once it reaches parity.

The active source is module-global; ``set_active_source`` swaps it.
Production code never calls that — it's the seam parity tests use to
point the engine at an alternative source for the duration of a test
session.

There is intentionally no hybrid / fallback source: the suite-wide
gate against an alternative source must stay strict. Mixing in the
static source to paper over gaps would hide real coverage. Per-card
structural parity (``tests/test_parser_parity.py``) is the
incremental progress signal; the full suite under
``MTG_BOT_CARD_SOURCE=parser`` is the final acceptance gate.
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


def card_source_from_env(value: str | None) -> CardSource:
    """Map an ``MTG_BOT_CARD_SOURCE`` env-var value to a concrete
    ``CardSource``. Used by ``tests/conftest.py`` to swap the active
    source for the duration of a test session.

    Recognized values:

    - ``None`` / ``""`` / ``"static"``: the default ``StaticCardSource``.
    - ``"parser"``: the parser source, strict — cards the parser
      doesn't claim are simply absent, so most simulation tests will
      fail until parser coverage is complete. That's the intended
      acceptance gate.
    """
    normalized = (value or "static").lower()
    if normalized == "static":
        return StaticCardSource()
    if normalized == "parser":
        from mtg_bot.cards.parser_source import OracleParserCardSource

        return OracleParserCardSource()
    raise ValueError(
        f"unknown MTG_BOT_CARD_SOURCE value: {value!r} "
        f"(expected 'static' or 'parser')"
    )
