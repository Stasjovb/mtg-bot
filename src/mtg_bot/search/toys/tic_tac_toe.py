"""Tic-tac-toe as a ``GameState``.

Two players (0 = X, 1 = O). Perfect information, no chance. Small
branching factor (≤ 9), shallow tree (≤ 9 plies) — MCTS should solve
it to optimal play within a small budget. The canonical sanity check
that the search framework wiring is correct.

State: a length-9 tuple of ``(0, 1, None)``, indexed row-major:

    0 1 2
    3 4 5
    6 7 8

Decisions are ``int`` indices 0..8.
"""

from __future__ import annotations

from mtg_bot.search.protocol import Decision, PlayerID


_LINES: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # cols
    (0, 4, 8), (2, 4, 6),             # diagonals
)


class TicTacToe:
    """Mutable tic-tac-toe game. Implements the ``GameState``
    protocol.

    After initialization, player 0 (X) moves first. ``apply(i)``
    places the active player's mark on cell ``i``.

    Intentionally NOT using ``__slots__`` — see comment on ``Pig``
    for the Python 3.13 specializing-interpreter crash this triggered.
    """

    def __init__(
        self,
        cells: tuple[int | None, ...] | None = None,
        to_move: PlayerID = 0,
    ) -> None:
        self._cells: tuple[int | None, ...] = (
            cells if cells is not None else (None,) * 9
        )
        self._to_move: PlayerID = to_move

    def clone(self) -> "TicTacToe":
        # Immutable cells tuple → cheap share. Just copy the two fields.
        return TicTacToe(cells=self._cells, to_move=self._to_move)

    def active_player(self) -> PlayerID:
        return self._to_move

    def legal_decisions(self) -> list[Decision]:
        if self.is_terminal():
            return []
        return [i for i, cell in enumerate(self._cells) if cell is None]

    def chance_outcomes(self) -> list[tuple[Decision, float]]:
        return []  # no chance nodes in tic-tac-toe

    def apply(self, decision: Decision) -> None:
        i = int(decision)
        if self._cells[i] is not None:
            raise ValueError(f"cell {i} is already occupied")
        new_cells = list(self._cells)
        new_cells[i] = self._to_move
        self._cells = tuple(new_cells)
        self._to_move = 1 - self._to_move

    def is_terminal(self) -> bool:
        return self.winner() is not None or self._board_full()

    def winner(self) -> PlayerID | None:
        for a, b, c in _LINES:
            if (
                self._cells[a] is not None
                and self._cells[a] == self._cells[b] == self._cells[c]
            ):
                return self._cells[a]
        return None  # ongoing OR draw — caller uses is_terminal() to distinguish

    def players(self) -> list[PlayerID]:
        return [0, 1]

    def _board_full(self) -> bool:
        return all(c is not None for c in self._cells)

    # Diagnostic helpers — not part of the protocol, useful for tests
    # and for human-readable logs.

    def cells(self) -> tuple[int | None, ...]:
        return self._cells

    def __repr__(self) -> str:
        sym = {0: "X", 1: "O", None: "."}
        rows = [
            " ".join(sym[self._cells[r * 3 + c]] for c in range(3))
            for r in range(3)
        ]
        return "\n".join(rows)
