"""Win meter for game review: each player's estimated chance to win at a
snapshot, shown like a chess evaluation bar.

Only review snapshots carry it -- the Watch tab's games (``/api/play``)
and the review of a finished interactive game
(``/api/interactive/review``); the live interactive snapshot never does,
so the bar can't help during play.

The estimate is the engine's position heuristic
(``MtgHeuristicEvaluator``: life, board power, cards, mana development;
the score the search bots use), a value ``v`` in [-1, 1] for player 0,
shown as a chance ``(v + 1) / 2``. It is a rough guide, not a solved
evaluation: it knows nothing Fish-specific (Dandân's Island needs, the
shared library). A finished game shows the result. Two-player games.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator

if TYPE_CHECKING:
    from mtg_bot.game import GameState

_EVALUATOR = MtgHeuristicEvaluator()


def win_meter(state: "GameState") -> dict[str, Any]:
    """``{"p0": chance player 0 wins, "source": "result" | "heuristic"}``."""
    if state.is_over():
        if state.winner_id is None:
            p0 = 0.5
        else:
            p0 = 1.0 if state.winner_id == 0 else 0.0
        return {"p0": p0, "source": "result"}
    # The evaluator reads a raw engine state (no search adapter: wrapping
    # the live state would replace its players' agents).
    value = _EVALUATOR._evaluate_nonterminal(state, 0)
    return {"p0": round((value + 1.0) / 2.0, 3), "source": "heuristic"}
