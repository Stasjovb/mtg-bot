"""Shared fixtures for the Forgetful Fish card tests (pool ``fish``; not
collected).

``printing(name)`` builds a card of the user's list through the parser
source's own claim path (``build_card_record``; asserts it is claimed)
from ``data/forgetful_fish/cards.json``; basics come from
``BASIC_LANDS``. The state / place / cast helpers are the Roto P5 ones
(``_roto_p5_helpers``), driven by their FIFO ``ScriptedAgent``.
"""

from __future__ import annotations

from functools import lru_cache

from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.parser.source import build_card_record
from mtg_bot.cards.pools import load_pool_cards
from mtg_bot.game import Zone

from tests._roto_p5_helpers import (  # noqa: F401  (re-exports)
    ScriptedAgent,
    cast,
    make_state,
    resolve_all,
    script,
    vanilla,
)


@lru_cache(maxsize=1)
def _fish_index() -> dict[str, dict]:
    return {c["name"]: c for c in load_pool_cards("fish")}


@lru_cache(maxsize=None)
def printing(name: str) -> CardPrinting:
    if name in BASIC_LANDS:
        return BASIC_LANDS[name]
    built = build_card_record(_fish_index()[name])
    assert built is not None, f"{name} should be claimed by the parser"
    return built


def place(state, pid: int, card: "CardPrinting | str",
          zone: Zone = Zone.BATTLEFIELD, *, sick: bool = False, tapped=False):
    """Put ``card`` (a printing or a Fish/basic name) into ``zone``."""
    pr = printing(card) if isinstance(card, str) else card
    obj = state.new_object(pr, owner_id=pid, zone=zone)
    p = state.player_by_id(pid)
    if zone == Zone.BATTLEFIELD:
        obj.controller_id = pid
        obj.summoning_sick = sick
        obj.tapped = tapped
        state.battlefield.append(obj)
    else:
        {
            Zone.HAND: p.hand, Zone.LIBRARY: p.library,
            Zone.GRAVEYARD: p.graveyard, Zone.EXILE: p.exile,
        }[zone].append(obj)
    return obj


def lands(state, pid: int, name: str, n: int) -> list:
    return [place(state, pid, name) for _ in range(n)]


def text_change(state, obj, old: str, new: str):
    """Apply a text-changing effect (CR 612) to ``obj`` directly."""
    from mtg_bot.effects.generic.fish_cards import TEXT_CHANGE_KIND

    return state.add_continuous_effect(
        source_id=obj.id, layer=3, kind=TEXT_CHANGE_KIND,
        target_id=obj.id, params=(old, new),
    )
