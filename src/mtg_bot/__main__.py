"""Entry point: ``python -m mtg_bot`` runs a random-vs-random game and
prints the result; ``python -m mtg_bot <subcommand> ...`` dispatches to
the ``mtg_bot.cli`` subcommands (e.g. ``python -m mtg_bot cards export-ir
--pool cube --out DIR``)."""

from __future__ import annotations

import sys

from mtg_bot.agents import RandomAgent
from mtg_bot.simulate import simulate_game


def main(argv: "list[str] | None" = None) -> None:
    if argv:
        from mtg_bot.cli import main as cli_main

        cli_main(argv)
        return
    state = simulate_game(
        agents=[RandomAgent(), RandomAgent()],
        colors=["G", "R"],
        seed=42,
        verbose=False,
    )
    print("=" * 60)
    if state.is_draw:
        print("Result: DRAW")
    elif state.winner_id is not None:
        print(f"Result: Player {state.winner_id} wins!")
        loser = next(p for p in state.players if p.has_lost)
        print(f"  ({loser.lost_reason})")
    print(f"Turns played: {state.turn_number}")
    print(
        f"Final life: "
        + ", ".join(f"P{p.id}={p.life}" for p in state.players)
    )
    print(f"Final battlefield: {len(state.battlefield)} permanents")
    print()
    print("Last 20 events:")
    for line in state.log[-20:]:
        print(f"  {line}")


if __name__ == "__main__":
    main(sys.argv[1:])
