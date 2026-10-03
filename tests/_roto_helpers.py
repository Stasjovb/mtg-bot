"""Shared fixtures for Vintage Roto (``roto`` pool) card tests.

``roto_card(name)`` returns the raw Scryfall record from
``data/cube_roto.json``; ``printing(name)`` builds it through the
parser source's own claim path (``build_card_record``) and asserts the
card is claimed. Arena/agent helpers are re-exported from the cube
artifact helpers so roto tests read like the cube bucket tests.

Roto cards are part of the default ``all`` pool since 2026-10-03, so
the default card source holds them too; these helpers build one record
through the claim path without depending on the active source.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.parser.source import build_card_record

from tests._cube_artifact_helpers import (  # noqa: F401  (re-exports)
    ScriptedAgent,
    agent,
    arena,
    put,
    to_graveyard,
    to_hand,
    to_library,
)

_DATA = Path(__file__).resolve().parents[1] / "data" / "cube_roto.json"


@lru_cache(maxsize=1)
def _roto_index() -> dict[str, dict]:
    with _DATA.open(encoding="utf-8") as fh:
        return {c["name"]: c for c in json.load(fh)}


def roto_card(name: str) -> dict:
    return _roto_index()[name]


@lru_cache(maxsize=None)
def printing(name: str) -> CardPrinting:
    built = build_card_record(roto_card(name))
    assert built is not None, f"{name} should be claimed by the parser"
    return built
