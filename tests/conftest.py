"""Session-scoped card-source swap driven by ``MTG_BOT_CARD_SOURCE``.

Default (env var unset) leaves the production ``StaticCardSource``
in place, so ``pytest`` runs unchanged. Set ``MTG_BOT_CARD_SOURCE``
to ``parser`` or ``parser_with_fallback`` to point the engine at
the parser source for the duration of the session — used to gate
suite-wide parser parity.
"""

from __future__ import annotations

import os

import pytest

from mtg_bot.cards.source import (
    card_source_from_env,
    get_active_source,
    set_active_source,
)


@pytest.fixture(scope="session", autouse=True)
def _swap_card_source_from_env():
    requested = card_source_from_env(os.environ.get("MTG_BOT_CARD_SOURCE"))
    original = get_active_source()
    set_active_source(requested)
    try:
        yield
    finally:
        set_active_source(original)
