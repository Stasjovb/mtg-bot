"""S6 frontier characterizer (throwaway diagnostic — scripts/scout_*).

Drives the role-swapped rust_shadow bake-in on a specified
(archetype, seed) up to the trip point and prints:
  - the exact trip step
  - the tripwire kind (or raw exception)
  - the divergence detail (verbatim)
  - the decision applied at the trip step
  - the engine step/phase context at the trip

NOT a shipped pin (scripts/scout_* stay under scripts/ per CLAUDE.md);
this is the precise-characterization tool the S6 inventory is built
from. It reuses the EXACT drive_shadow_game_to_terminal idiom (uniform
random over adapter.legal_decisions(), apply until terminal) so the
trip it characterizes is byte-identical to the scale sweep's.
"""
from __future__ import annotations

import argparse
import random
import sys
import traceback

from mtg_bot.parity import trajectory
from mtg_bot.search.engine_adapter_factory import (
    build_shadow_checked_adapter,
)
from mtg_bot.search.rust_shadow import ShadowDivergenceError


def characterize(arch: int, seed: int, max_steps: int = 4000) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        names, shared_rng_seed=seed
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    steps = 0
    last_decision = None
    while not adapter.is_terminal() and steps < max_steps:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            print(f"arch{arch}/s{seed}: TRIP at legal_decisions() "
                  f"step={steps}")
            print(f"  tripwire={e.tripwire}")
            print(f"  detail={str(e)[:900]}")
            return
        if not legal:
            print(f"arch{arch}/s{seed}: EMPTY legal set at step={steps} "
                  f"(non-terminal)")
            return
        choice = rng.choice(legal)
        last_decision = choice
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            print(f"arch{arch}/s{seed}: TRIP (ShadowDivergence) "
                  f"step={steps}")
            print(f"  tripwire={e.tripwire}")
            print(f"  decision_applied={choice!r}")
            print(f"  detail={str(e)[:1200]}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"arch{arch}/s{seed}: TRIP (RAW {type(e).__name__}) "
                  f"step={steps}")
            print(f"  decision_applied={choice!r}")
            print(f"  message={str(e)[:1200]}")
            try:
                rs = adapter.rust_adapter.rust_state
                print(f"  rust step={rs.step!r} "
                      f"active={adapter.rust_adapter.active_player()}")
            except Exception:  # noqa: BLE001
                pass
            return
        steps += 1
    if adapter.is_terminal():
        print(f"arch{arch}/s{seed}: PASS — clean to terminal in "
              f"{steps} steps; winner={adapter.winner()}")
    else:
        print(f"arch{arch}/s{seed}: TIMEOUT at {steps} steps "
              f"(last_decision={last_decision!r})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--max-steps", type=int, default=4000)
    a = ap.parse_args()
    try:
        characterize(a.arch, a.seed, a.max_steps)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
