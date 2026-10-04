"""Shared fixtures for the cube "glue" bucket tests.

``printing(name)`` builds a cube card through the exact builder chain
``OracleParserCardSource`` uses (hand-ability split included), so the
tests exercise the claimed printing without constructing the whole
pool. The arena / agent helpers are the artifact bucket's
(``_cube_artifact_helpers``), re-exported here.
"""

from __future__ import annotations

from functools import lru_cache

from mtg_bot.actions import _activate_ability, resolve_top_of_stack
from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.parser.source import (
    _build_printing,
    _split_hand_abilities,
    _with_hand_abilities,
)
from mtg_bot.turn import state_based_actions

from tests._cube_artifact_helpers import (  # noqa: F401  (re-exports)
    ScriptedAgent,
    agent,
    arena,
    cube_card,
    pool_colors,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


@lru_cache(maxsize=None)
def printing(name: str) -> CardPrinting:
    body, hand_abilities = _split_hand_abilities(cube_card(name))
    built = _build_printing(body)
    assert built is not None, f"{name} should be claimed by the parser"
    return _with_hand_abilities(built, hand_abilities)


def loyalty_index(walker, printed: int) -> int:
    """Index of the loyalty ability printed as ``printed`` (+1 -> 1,
    -3 -> -3)."""
    signed = -printed
    for i, a in enumerate(walker.printing.activated_abilities):
        if a.cost.loyalty == signed:
            return i
    raise AssertionError(f"no {printed} ability on {walker.printing.name}")


def activate_loyalty(state, pid, walker, printed: int, *, resolve=True,
                     index: int | None = None):
    idx = loyalty_index(walker, printed) if index is None else index
    _activate_ability(state, pid, walker.id, idx)
    if resolve:
        resolve_top_of_stack(state)
        state_based_actions(state)


def put_walker(state, name: str, controller: int = 0):
    """A planeswalker on the battlefield with its printed loyalty."""
    obj = put(state, printing(name), controller)
    obj.loyalty_counters = obj.printing.loyalty
    return obj
