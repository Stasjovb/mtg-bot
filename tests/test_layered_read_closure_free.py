"""The hot layered-read call tree must stay free of closure cells.

Two production self-play games were dropped by "impossible object in a
slot" crashes raised inside ``mtg_bot.game._static_bonuses`` on CPython
3.13.14:

- ``AttributeError: 'cell' object has no attribute 'attached_to'`` at
  the Equipment walk's ``source.attached_to`` read — the loop variable
  came back holding the frame's closure cell. Nothing in the engine can
  put a ``cell`` into ``state.battlefield``.
- ``TypeError: 'ContinuousModifier' object is not iterable`` from the
  CR 613 dispatcher's read of ``printing.static_abilities``, in a frame
  where the layer-6 walk had just read the same slot off the same list
  successfully.

A generator expression (or comprehension) that reads an enclosing local
turns that local into a CELL variable, and cells live in the same
``localsplus`` array as the frame's fast locals. ``search/mcts.py``
already documents the same class of CPython 3.13 specializing-interpreter
defect in this codebase and works around it by removing the pattern.

These tests pin the mitigation so a future edit does not quietly
reintroduce a cell into one of these frames, and pin the layer-7e
behaviour that the rewrite touched.
"""

from __future__ import annotations

import pytest

import mtg_bot.effects.modifiers as modifiers
import mtg_bot.game as game
from mtg_bot.agents import RandomAgent
from mtg_bot.cards.base import make_token_creature
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_power,
    effective_toughness,
)

# Every frame on the path the two crashes were raised from.
HOT_LAYERED_READS = [
    game._static_bonuses,
    game._source_layer6_wiped,
    game._compute_effective_pt,
    game._layer6_entries_for,
    game.effective_keywords,
    modifiers.active_static_abilities,
    modifiers.walk_continuous_modifiers,
]


@pytest.mark.parametrize(
    "fn", HOT_LAYERED_READS, ids=lambda f: f.__name__,
)
def test_hot_layered_read_has_no_closure_cells(fn):
    assert fn.__code__.co_cellvars == (), (
        f"{fn.__module__}.{fn.__name__} grew a closure cell "
        f"({fn.__code__.co_cellvars}). Cells share the frame's "
        f"localsplus array with the fast locals; keep this call tree "
        f"closure-free (use an explicit loop, not a genexp that reads "
        f"an enclosing local). See the note on game._static_bonuses."
    )


def _state_with_creature():
    state = GameState(
        players=[
            Player(id=0, agent=RandomAgent()),
            Player(id=1, agent=RandomAgent()),
        ],
    )
    obj = state.new_object(
        make_token_creature("Switcher", 3, 1), owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return state, obj


def _add_switch(state, obj):
    state.add_continuous_effect(
        source_id=obj.id,
        layer=7,
        sublayer=4,
        kind="switch_pt",
        target_id=obj.id,
        params=(),
        description="switch P/T",
    )


@pytest.mark.parametrize(
    "n_switches,expected", [(0, (3, 1)), (1, (1, 3)), (2, (3, 1)), (3, (1, 3))],
)
def test_layer7e_switch_count_parity(n_switches, expected):
    """Each layer-7e ``switch_pt`` entry contributes one swap, so only
    the parity of the count matters. The rewrite counts entries instead
    of sorting them by timestamp — the discarded order was never read.
    """
    state, obj = _state_with_creature()
    for _ in range(n_switches):
        _add_switch(state, obj)
    assert (
        effective_power(state, obj), effective_toughness(state, obj),
    ) == expected
