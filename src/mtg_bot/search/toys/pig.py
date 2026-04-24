"""Pig: a push-your-luck dice game used to exercise chance nodes.

Two players. Scores start at 0. On your turn, you pick "roll" or
"hold":

  - "roll" goes to a chance node. With probability 5/6, ``pending`` is
    incremented by 1 and you decide again. With probability 1/6, you
    "bust" — ``pending`` resets to 0 and the turn passes.
  - "hold" adds ``pending`` to your score, resets ``pending`` to 0,
    and passes the turn.

First player to ``target`` (default 10) wins. Canonical small
stochastic game from the MCTS literature — small state, exercises
chance-node plumbing end-to-end, and has real push-your-luck strategy
so MCTS should beat random non-trivially.

Decisions at real-player nodes: ``"roll"`` | ``"hold"``.
Decisions at chance nodes: ``"advance"`` | ``"bust"``.
"""

from __future__ import annotations

from mtg_bot.search.protocol import CHANCE_PLAYER, Decision, PlayerID


ADVANCE_PROB = 5.0 / 6.0
BUST_PROB = 1.0 - ADVANCE_PROB


class Pig:
    """Mutable Pig game state. Implements the ``GameState`` protocol.

    Intentionally NOT using ``__slots__`` — Python 3.13's specializing
    interpreter had a reproducible crash (``_PyEval_EvalFrameDefault:
    Executing a cache``) against the attribute-access pattern in this
    hot loop when ``__slots__`` was declared. Regular ``__dict__``
    instances avoid the bug. Memory overhead is negligible for a toy.
    """

    def __init__(
        self,
        scores: tuple[int, int] = (0, 0),
        to_move: PlayerID = 0,
        pending: int = 0,
        target: int = 10,
        at_chance: bool = False,
    ) -> None:
        self._scores: tuple[int, int] = scores
        self._to_move: PlayerID = to_move
        self._pending: int = pending
        self._target: int = target
        self._at_chance: bool = at_chance

    def clone(self) -> "Pig":
        return Pig(
            scores=self._scores,
            to_move=self._to_move,
            pending=self._pending,
            target=self._target,
            at_chance=self._at_chance,
        )

    def active_player(self) -> PlayerID:
        if self._at_chance:
            return CHANCE_PLAYER
        return self._to_move

    def legal_decisions(self) -> list[Decision]:
        if self.is_terminal():
            return []
        if self._at_chance:
            return ["advance", "bust"]
        return ["roll", "hold"]

    def chance_outcomes(self) -> list[tuple[Decision, float]]:
        if not self._at_chance or self.is_terminal():
            return []
        return [("advance", ADVANCE_PROB), ("bust", BUST_PROB)]

    def apply(self, decision: Decision) -> None:
        if self._at_chance:
            if decision == "advance":
                self._pending += 1
            elif decision == "bust":
                self._pending = 0
                self._to_move = 1 - self._to_move
            else:
                raise ValueError(
                    f"illegal chance outcome: {decision!r}"
                )
            self._at_chance = False
            return

        if decision == "roll":
            self._at_chance = True
        elif decision == "hold":
            banked = self._scores[self._to_move] + self._pending
            if self._to_move == 0:
                self._scores = (banked, self._scores[1])
            else:
                self._scores = (self._scores[0], banked)
            self._pending = 0
            self._to_move = 1 - self._to_move
        else:
            raise ValueError(f"illegal decision: {decision!r}")

    def is_terminal(self) -> bool:
        return (
            self._scores[0] >= self._target
            or self._scores[1] >= self._target
        )

    def winner(self) -> PlayerID | None:
        if self._scores[0] >= self._target:
            return 0
        if self._scores[1] >= self._target:
            return 1
        return None  # ongoing

    def players(self) -> list[PlayerID]:
        return [0, 1]

    # Diagnostics

    def scores(self) -> tuple[int, int]:
        return self._scores

    def pending(self) -> int:
        return self._pending

    def __repr__(self) -> str:
        s0, s1 = self._scores
        who = f"chance after P{self._to_move}" if self._at_chance else f"P{self._to_move}"
        return (
            f"Pig(scores=({s0},{s1}), pending={self._pending}, "
            f"to_move={who}, target={self._target})"
        )
