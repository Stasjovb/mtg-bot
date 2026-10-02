"""Shared fixtures for the Vintage Roto P5 package tests (board-state
prison & layers; not collected).

``printing(name)`` builds a roto card through the parser source's own
claim path (``build_card_record``; asserts it is claimed) -- roto-only
cards are not in the default pool. ``vanilla`` makes plain test
creatures. The state / cast / activate helpers are the cube creatures
bucket's (``_rmc_helpers``), driven by its FIFO ``ScriptedAgent``.
"""

from __future__ import annotations

from functools import lru_cache

from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import CardPrinting, make_creature
from mtg_bot.game import Zone

from tests._rmc_helpers import (  # noqa: F401  (re-exports)
    ScriptedAgent,
    activate,
    can_activate,
    cast,
    make_state,
    resolve_all,
)
from tests._roto_helpers import printing as _roto_printing, roto_card  # noqa: F401


def printing(name: str) -> CardPrinting:
    if name in BASIC_LANDS:
        return BASIC_LANDS[name]
    return _roto_printing(name)


@lru_cache(maxsize=None)
def vanilla(power: int, toughness: int, name: str = "", cost: str = "{2}",
            **kwargs) -> CardPrinting:
    return make_creature(
        name or f"Vanilla {power}/{toughness}", cost, power, toughness,
        **kwargs,
    )


def place(state, pid: int, card: "CardPrinting | str",
          zone: Zone = Zone.BATTLEFIELD, *, sick: bool = False, tapped=False):
    """Put ``card`` (a printing or a roto/basic name) into ``zone``."""
    pr = printing(card) if isinstance(card, str) else card
    obj = state.new_object(pr, owner_id=pid, zone=zone)
    p = state.player_by_id(pid)
    if zone == Zone.BATTLEFIELD:
        obj.controller_id = pid
        obj.summoning_sick = sick
        obj.tapped = tapped
        state.battlefield.append(obj)
    elif zone == Zone.HAND:
        p.hand.append(obj)
    elif zone == Zone.LIBRARY:
        p.library.append(obj)
    elif zone == Zone.GRAVEYARD:
        p.graveyard.append(obj)
    elif zone == Zone.EXILE:
        p.exile.append(obj)
    return obj


def lands(state, pid: int, name: str, n: int) -> list:
    return [place(state, pid, name) for _ in range(n)]


def script(state, pid: int, hook: str, *answers) -> None:
    """Queue ``answers`` for ``pid``'s scripted ``hook``."""
    state.players[pid].agent.scripts.setdefault(hook, []).extend(answers)
