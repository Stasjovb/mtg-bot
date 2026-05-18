"""Drive the RAW simulate.py SoT (the true game engine, NOT the search
adapter) on arch5/s0's deck and log priority_player_idx at the
DECLARE_ATTACKERS factored-attacker decision moment + through the step,
to settle which adapter (engine_adapter.py carried-priority vs the Rust
engine active-priority) is SoT-faithful per feedback_parity_new_code_is_right.
"""

from __future__ import annotations

import random
import sys

from mtg_bot import simulate
from mtg_bot.agents import Agent
from mtg_bot.actions import PassPriority
from mtg_bot.parity import cross_engine, trajectory


class RngAgent(Agent):
    def __init__(self, seed):
        self.rng = random.Random(seed)

    def choose_action(self, state, pid, legal):
        return self.rng.choice(legal)

    def declare_attackers(self, state, pid, eligible):
        print(
            f"  >> declare_attackers CALLED: pid={pid} "
            f"eligible={[o.id for o in eligible]} "
            f"priority_player_idx={state.priority_player_idx} "
            f"active_player_idx={state.active_player_idx} "
            f"step={state.step}"
        )
        return []  # never attack — keeps the game going / minimal

    def declare_blockers(self, state, pid, eligible, attackers):
        return {}


def main(arch: int, seed: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)
    state = cross_engine.build_python_state(spec)
    state.players[0].agent = RngAgent(seed)
    state.players[1].agent = RngAgent(seed + 1000)

    orig_loop = simulate.priority_loop

    def loop(st, on_snapshot=None):
        before = st.priority_player_idx
        from mtg_bot.turn import Step
        if st.step in (Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS):
            print(
                f"  priority_loop ENTER step={st.step} "
                f"priority_player_idx(before _next_alive)={before} "
                f"active={st.active_player_idx}"
            )
        orig_loop(st, on_snapshot)

    simulate.priority_loop = loop

    turn = 0
    while not state.is_over() and turn < 30:
        if state.step is None:
            from mtg_bot.turn import Step
            state.step = Step.UNTAP
        from mtg_bot.turn import Step
        if state.turn_number >= 4:
            print(f"=== TURN {state.turn_number} "
                  f"active={state.active_player_idx} ===")
        simulate.run_turn(state)
        turn += 1
    print(f"[done turn={state.turn_number} over={state.is_over()}]")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5,
         int(sys.argv[2]) if len(sys.argv) > 2 else 0)
