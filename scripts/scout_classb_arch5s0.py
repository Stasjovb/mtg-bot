"""Verify-first repro for G7 S6 Class B (arch5/s0 step 367 priority-port).

Drives the role-swapped rust_shadow bake-in for arch5/seed0 to the
documented STATE_EQ ('priority_player', 1, 0) trip and dumps the exact
decision + priority/active-player divergence on BOTH engines around the
boundary. Throwaway diagnostic (scripts/scout_*.py stays under scripts/).
"""

from __future__ import annotations

import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.search.engine_adapter_factory import build_shadow_checked_adapter
from mtg_bot.search.rust_shadow import ShadowDivergenceError


def _rust_pri(rust_adapter):
    return int(rust_adapter._rust.get_priority_player())


def _rust_active(rust_adapter):
    return int(rust_adapter._rust.active_player_idx)


def _rust_phase(rust_adapter):
    return int(rust_adapter._rust.current_phase())


def _py_pri(py_adapter):
    return int(py_adapter.engine_state.priority_player_idx)


def _py_active(py_adapter):
    return int(py_adapter.engine_state.active_player_idx)


def _py_step(py_adapter):
    return py_adapter.engine_state.step


def main(arch: int, seed: int, trace_from: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    rust = adapter.rust_adapter
    py = adapter.py_adapter
    steps = 0
    while not adapter.is_terminal() and steps < 400:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            print(f"[LEGAL_SET trip @ step {steps}] {e.tripwire}: {e}")
            return
        if not legal:
            print(f"[empty legal @ step {steps}]")
            return
        choice = rng.choice(legal)
        pre = (
            f"step={steps} choice={choice!r} "
            f"PY[pri={_py_pri(py)} act={_py_active(py)} "
            f"step={_py_step(py)} pass={py._pass_count} "
            f"combat={py.combat_phase}] "
            f"RUST[pri={_rust_pri(rust)} act={_rust_active(rust)} "
            f"phase={_rust_phase(rust)} pass={rust._pass_count} "
            f"combat={rust._combat_phase} "
            f"losers={list(rust._rust.losers())} "
            f"stack={rust._rust.stack_size()}]"
        )
        if steps >= trace_from:
            print(pre)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            print(f"\n[TRIP @ step {steps}] tripwire={e.tripwire}")
            print(f"  detail: {e}")
            print(f"  pre-apply: {pre}")
            print(
                f"  post-apply PY[pri={_py_pri(py)} act={_py_active(py)} "
                f"step={_py_step(py)} pass={py._pass_count} "
                f"is_over={py.engine_state.is_over()}] "
                f"RUST[pri={_rust_pri(rust)} act={_rust_active(rust)} "
                f"phase={_rust_phase(rust)} pass={rust._pass_count} "
                f"is_over={rust._rust.is_over()} "
                f"losers={list(rust._rust.losers())}]"
            )
            return
        except Exception as e:  # noqa: BLE001
            print(f"\n[RAW EXC @ step {steps}] {type(e).__name__}: {e}")
            print(f"  pre-apply: {pre}")
            return
        steps += 1
    print(f"[ran to end @ step {steps}, terminal={adapter.is_terminal()}]")


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    s = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    tf = int(sys.argv[3]) if len(sys.argv) > 3 else 355
    main(a, s, tf)
