"""At arch5/s0 step 368 (DECLARE_ATTACKERS), dump Rust's raw
legal_decisions for both players + Python's adapter factored set, to
see whether Rust enters factored-combat emission and how priority
should sit for parity.
"""

from __future__ import annotations

import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.search import rust_shadow as rs
from mtg_bot.search.engine_adapter_factory import build_shadow_checked_adapter


def main(arch: int, seed: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)
    rs.ShadowCheckedRustAdapter._assert_state_eq = lambda self: None

    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    rust = adapter.rust_adapter
    py = adapter.py_adapter
    pystate = py.engine_state
    steps = 0
    while not adapter.is_terminal() and steps < 400:
        if steps == 368:
            rstate = rust._rust
            print(f"=== step {steps} DECLARE_ATTACKERS ===")
            print(
                f"PY pri={pystate.priority_player_idx} "
                f"act={pystate.active_player_idx} step={pystate.step} "
                f"combat={py.combat_phase} "
                f"pending_atk={py._pending_attackers}"
            )
            print(
                f"RUST pri={int(rstate.get_priority_player())} "
                f"act={int(rstate.active_player_idx)} "
                f"phase={int(rstate.current_phase())} "
                f"attackers={list(rstate.get_attackers())}"
            )
            print("RUST legal(0):")
            for d in rstate.legal_decisions(0):
                print(f"   {d}")
            print("RUST legal(1):")
            for d in rstate.legal_decisions(1):
                print(f"   {d}")
            print("PY adapter legal_decisions():")
            for d in py.legal_decisions():
                print(f"   {d!r}")
            # battlefield creatures + can-attack
            print("PY battlefield creatures:")
            for o in pystate.battlefield:
                ct = getattr(o.printing, "card_types", None)
                print(
                    f"   obj {o.id} {o.printing.name} types={ct} "
                    f"controller={o.controller_id} "
                    f"tapped={o.tapped} "
                    f"sick={getattr(o, 'summoning_sick', '?')} "
                    f"attacking={o.attacking}"
                )
            return
        legal = adapter.legal_decisions()
        if not legal:
            return
        adapter.apply(rng.choice(legal))
        steps += 1


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5,
         int(sys.argv[2]) if len(sys.argv) > 2 else 0)
