"""Verify-first: pinpoint the EXACT site Rust priority_player goes 1->0
on the arch5/s0 step-367 PassPriority (BEGINNING_OF_COMBAT pass-round
end -> DECLARE_ATTACKERS). Wraps the Rust-driver adapter's priority
helpers + the Rust engine advance_phase to log the priority transition.
Throwaway diagnostic.
"""

from __future__ import annotations

import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.search.engine_adapter_factory import build_shadow_checked_adapter
from mtg_bot.search.rust_shadow import ShadowDivergenceError


def main(arch: int, seed: int, trace_from: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    rust = adapter.rust_adapter
    py = adapter.py_adapter

    # Wrap the Rust-driver adapter's priority helpers.
    orig_reset = rust._reset_priority_to_active
    orig_adv = rust._advance_to_next_decision
    orig_rpa = rust._run_priority_action

    def reset(*a, **k):
        before = int(rust._rust.get_priority_player())
        r = orig_reset(*a, **k)
        after = int(rust._rust.get_priority_player())
        if before != after:
            print(f"    [_reset_priority_to_active] pri {before}->{after} "
                  f"phase={int(rust._rust.current_phase())}")
        return r

    def adv(*a, **k):
        before = int(rust._rust.get_priority_player())
        bph = int(rust._rust.current_phase())
        r = orig_adv(*a, **k)
        after = int(rust._rust.get_priority_player())
        aph = int(rust._rust.current_phase())
        if before != after or bph != aph:
            print(f"    [_advance_to_next_decision] pri {before}->{after} "
                  f"phase {bph}->{aph}")
        return r

    def rpa(decision):
        before = int(rust._rust.get_priority_player())
        bph = int(rust._rust.current_phase())
        r = orig_rpa(decision)
        after = int(rust._rust.get_priority_player())
        aph = int(rust._rust.current_phase())
        print(f"    [_run_priority_action {type(decision).__name__}] "
              f"pri {before}->{after} phase {bph}->{aph}")
        return r

    rust._reset_priority_to_active = reset
    rust._advance_to_next_decision = adv
    rust._run_priority_action = rpa

    steps = 0
    while not adapter.is_terminal() and steps < 400:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            print(f"[LEGAL trip @ {steps}] {e}")
            return
        if not legal:
            print(f"[empty legal @ {steps}]")
            return
        choice = rng.choice(legal)
        if steps >= trace_from:
            print(f"step={steps} choice={choice!r} "
                  f"PY[pri={py.engine_state.priority_player_idx} "
                  f"step={py.engine_state.step} cmb={py.combat_phase}] "
                  f"RUST[pri={int(rust._rust.get_priority_player())} "
                  f"ph={int(rust._rust.current_phase())} "
                  f"cmb={rust._combat_phase}]")
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            print(f"\n[TRIP @ {steps}] {e.tripwire}: {e}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"\n[RAW @ {steps}] {type(e).__name__}: {e}")
            return
        steps += 1
    print(f"[end @ {steps}]")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5,
         int(sys.argv[2]) if len(sys.argv) > 2 else 0,
         int(sys.argv[3]) if len(sys.argv) > 3 else 365)
