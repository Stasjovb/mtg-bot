"""Drive the Python MtgGameStateAdapter ALONE on arch5/s0 (the SoT
reference the bake-in compares Rust against) and log priority_player_idx
+ combat_phase + active_player at every post-apply point through the
combat sequence, so the Rust-driver mirror can be made byte-exact.
"""

from __future__ import annotations

import random
import sys

from mtg_bot.parity import cross_engine, trajectory
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.heuristics_config import HeuristicsConfig


def main(arch: int, seed: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)
    py_state, _rust = cross_engine.build_matched_states(spec)
    adapter = MtgGameStateAdapter(
        py_state, expose_combat_decisions=True,
        heuristics=HeuristicsConfig.disabled(),
    )
    rng = random.Random(seed)
    st = adapter.engine_state
    steps = 0
    while not adapter.is_terminal() and steps < 410:
        if 364 <= steps <= 400:
            print(
                f"step {steps}: pri={st.priority_player_idx} "
                f"act={st.active_player_idx} step={st.step} "
                f"combat={adapter.combat_phase} "
                f"decision_maker={adapter.active_player()} "
                f"pass={adapter._pass_count}"
            )
        legal = adapter.legal_decisions()
        if not legal:
            print(f"[empty @ {steps}]")
            return
        choice = rng.choice(legal)
        if 364 <= steps <= 400:
            print(f"   choice={choice!r}")
        adapter.apply(choice)
        steps += 1
    print(f"[end @ {steps} terminal={adapter.is_terminal()} "
          f"winner={adapter.winner()}]")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5,
         int(sys.argv[2]) if len(sys.argv) > 2 else 0)
