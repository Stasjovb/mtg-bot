"""Entry point: run a random-vs-random game and print the result."""

from __future__ import annotations

from mtg_bot.agents import RandomAgent
from mtg_bot.simulate import simulate_game


def main() -> None:
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
    main()
