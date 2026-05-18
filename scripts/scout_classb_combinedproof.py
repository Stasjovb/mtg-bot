"""VERIFY-FIRST PROOF (throwaway, NOT committed-behavior): with the
option-beta state_ops_legal.rs:1199 relaxation BUILT IN (this worktree
wheel), monkeypatch ONLY the Rust-driver adapter's eager priority reset
to DEFER it for factored-combat steps (the hypothetical coordinated
rust_engine_adapter.py change Python's _enter_declare_* already does by
returning without _enter_priority_for_current_step). If step 367 then
CLOSES and the run proceeds, that proves: (a) the engine-side line-1199
relaxation is the correct byte-faithful change, and (b) the residual
blocker is the adapter's eager reset (rust_engine_adapter.py:473) which
this lane is forbidden to touch -> the honest-stop boundary is real and
the engine sub-part is sound. This script does NOT alter committed
behavior; it is an experiment to characterize the slice boundary.
"""

from __future__ import annotations

import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.search.engine_adapter_factory import build_shadow_checked_adapter
from mtg_bot.search.rust_shadow import ShadowDivergenceError

_PHASE_DECLARE_ATTACKERS = 5
_PHASE_DECLARE_BLOCKERS = 6


def main(arch: int, seed: int, trace_from: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    rust = adapter.rust_adapter

    orig_reset = rust._reset_priority_to_active

    def deferred_reset(*a, **k):
        # Hypothetical coordinated adapter change: do NOT reset priority
        # when the (just-advanced) step is a factored-combat step with
        # an eligible decision pending — mirror Python's
        # _enter_declare_*'s "return WITHOUT
        # _enter_priority_for_current_step" so priority stays CARRIED
        # through the factored-combat window (the simulate.py SoT).
        ph = int(rust._rust.current_phase())
        if ph in (_PHASE_DECLARE_ATTACKERS, _PHASE_DECLARE_BLOCKERS):
            # Does Rust emit a factored-combat decision for the
            # structural decision-maker? (option-beta engine change
            # keys emission on active/defender, not priority.)
            act = int(rust._rust.active_player_idx)
            dm = act if ph == _PHASE_DECLARE_ATTACKERS else 1 - act
            for d in rust._rust.legal_decisions(dm):
                if d.get("kind") in ("attacker_decision",
                                     "blocker_decision"):
                    return  # defer: keep priority carried
        return orig_reset(*a, **k)

    rust._reset_priority_to_active = deferred_reset

    steps = 0
    while not adapter.is_terminal() and steps < 400:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            print(f"[LEGAL trip @ {steps}] {e.tripwire}: {e}")
            return
        if not legal:
            print(f"[empty legal @ {steps}]")
            return
        choice = rng.choice(legal)
        if steps >= trace_from:
            print(f"step={steps} choice={choice!r} "
                  f"PY[pri={adapter.py_adapter.engine_state.priority_player_idx} "
                  f"step={adapter.py_adapter.engine_state.step} "
                  f"cmb={adapter.py_adapter.combat_phase}] "
                  f"RUST[pri={int(rust._rust.get_priority_player())} "
                  f"ph={int(rust._rust.current_phase())}]")
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            print(f"\n[TRIP @ {steps}] {e.tripwire}: {e}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"\n[RAW @ {steps}] {type(e).__name__}: {e}")
            return
        steps += 1
    print(f"[ran to end @ {steps}, terminal={adapter.is_terminal()}]")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5,
         int(sys.argv[2]) if len(sys.argv) > 2 else 0,
         int(sys.argv[3]) if len(sys.argv) > 3 else 365)
