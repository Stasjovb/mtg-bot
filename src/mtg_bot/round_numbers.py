"""Round numbers for the screen and the log.

The engine's ``turn_number`` counts every player's turn: turn 1 is the
starting player's, turn 2 the other player's, and so on. Per-turn bookkeeping
("entered this turn", "once per turn") relies on that count, so the engine
keeps it. A round is one turn for each player, so the two turns of a round
share one number. Only what the player sees uses the round number.

Extra turns (one player taking two turns in a row) shift the pairing: the
round number then runs one turn behind until the next pair of turns. This
is a display approximation; see docs/SEARCH_LIMITATIONS.md.
"""

from __future__ import annotations


def round_of(turn_number: int) -> int:
    """The round that engine turn ``turn_number`` belongs to: turns 1 and 2
    are round 1, turns 3 and 4 are round 2, and so on."""
    return (turn_number + 1) // 2
