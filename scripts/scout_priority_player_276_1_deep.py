"""Deeper trace: intercept INSIDE the Rust adapter's
``_run_priority_action`` at the divergent step to dump the exact
mid-apply state and rule out / confirm hypothesis on the
priority_player axis at arch=276 seed=1 step 857.

Monkey-patches ``RustGameStateAdapter._run_priority_action`` for one
final step so we can sub-step trace it.
"""
from __future__ import annotations

import argparse
import random
import sys

from mtg_bot.actions import PassPriority
from mtg_bot.parity import trajectory
from mtg_bot.search.rust_shadow import build_shadow_checked_adapter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archetype", type=int, default=276)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--target-step", type=int, default=857)
    args = ap.parse_args()

    deck_names = trajectory.load_production_deck(archetype=args.archetype)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=args.seed,
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(args.seed)
    steps = 0

    # Advance to target_step - 1, then sub-step the final apply by
    # instrumenting the Rust adapter directly (bypass the
    # ShadowCheckedRustAdapter assertions on the last step).
    rust_eng = adapter._rust
    py_eng = adapter._py

    while steps < args.target_step:
        if adapter.is_terminal():
            print(f"terminated at step {steps}")
            return 0
        legal = adapter.legal_decisions()
        choice = rng.choice(legal)
        adapter.apply(choice)
        steps += 1

    # Now we're sitting at the pre-step-857 state. Don't go through
    # ShadowCheckedRustAdapter — sub-step the Rust adapter directly.
    print(f"--- pre-step-{args.target_step} ---")
    print(f"py.active_player_idx = {py_eng.engine_state.active_player_idx}")
    print(f"py.priority_player_idx = {py_eng.engine_state.priority_player_idx}")
    print(f"py.step = {py_eng.engine_state.step}")
    print(f"py.combat_phase = {py_eng.combat_phase}")
    print(f"py.pass_count = {py_eng._pass_count}")
    print(f"rust.active = {rust_eng._rust.active_player_idx}")
    print(f"rust.priority = {rust_eng._rust.get_priority_player()}")
    print(f"rust.current_phase = {rust_eng._rust.current_phase()}")
    print(f"rust.pass_count = {rust_eng._pass_count}")
    print(f"rust._combat_phase = {rust_eng._combat_phase}")
    print(f"rust._finalized_combat_window = {rust_eng._finalized_combat_window}")
    print(f"rust.battlefield-attacking-ids:")
    for obj in rust_eng._rust.battlefield_snapshot():
        d = dict(obj)
        if d.get("attacking"):
            print(f"  attacker id={d['id']} ctrl={d.get('controller_id')} "
                  f"name={d.get('printing_name')!r}")
    print(f"rust.get_attackers() (from state.attackers Vec): "
          f"{list(rust_eng._rust.get_attackers())}")
    print(f"rust battlefield ids (full): "
          f"{[dict(o)['id'] for o in rust_eng._rust.battlefield_snapshot()]}")
    print(f"py battlefield ids (full): "
          f"{[o.id for o in py_eng.engine_state.battlefield]}")
    print(f"py.battlefield attackers:")
    for obj in py_eng.engine_state.battlefield:
        if getattr(obj, "attacking", False):
            print(f"  attacker id={obj.id} ctrl={obj.controller_id} "
                  f"name={obj.printing.name!r}")
    # Now simulate the apply step by step on the Rust side, with
    # print probes interleaved at the adapter's _run_priority_action
    # branch points.
    decision = rng.choice(adapter.legal_decisions())
    print(f"\nchosen at step {args.target_step}: {decision!r}")
    print(f"isinstance PassPriority: {isinstance(decision, PassPriority)}")
    if isinstance(decision, PassPriority):
        rust_eng._pass_count += 1
        alive = rust_eng._alive_count()
        print(f"after pass_count++: rust._pass_count={rust_eng._pass_count} "
              f"alive_count={alive}")
        if rust_eng._pass_count >= alive:
            rust_eng._pass_count = 0
            stack_size = rust_eng._rust.stack_size()
            print(f"round complete. stack_size={stack_size}")
            if stack_size > 0:
                print("would resolve top of stack")
                return 0
            else:
                print("empty stack — calling advance_phase()")
                rust_eng._rust.advance_phase()
                print(f"  rust.current_phase = {rust_eng._rust.current_phase()}")
                print(f"  rust.priority = {rust_eng._rust.get_priority_player()}")
                print(f"  rust.active = {rust_eng._rust.active_player_idx}")
                print("  calling _run_step_enter_sbas()")
                rust_eng._run_step_enter_sbas()
                print(f"  rust.current_phase = {rust_eng._rust.current_phase()}")
                print(f"  rust.priority = {rust_eng._rust.get_priority_player()}")
                print(f"  rust.active = {rust_eng._rust.active_player_idx}")
                print("  invalidating legal cache")
                rust_eng._invalidate_legal_cache()
                is_over = rust_eng._rust.is_over()
                dm = rust_eng._combat_decision_maker()
                print(f"  is_over={is_over} _combat_decision_maker()={dm}")
                if not is_over and dm is None:
                    print("  calling _reset_priority_to_active()")
                    rust_eng._reset_priority_to_active()
                    print(f"  POST rust.priority = {rust_eng._rust.get_priority_player()}")
                else:
                    print("  *** SKIPPING reset (dm is not None or is_over)")
                    print(f"  Rust legal_decisions for dm={dm}:")
                    for d in rust_eng._legal_dicts_cached(dm):
                        print(f"    {d}")
                    # Also dump for the active player and 1 - active
                    for pid in (0, 1):
                        rust_eng._invalidate_legal_cache()
                        print(f"  Rust legal_decisions for pid={pid}:")
                        for d in rust_eng._legal_dicts_cached(pid):
                            print(f"    {d}")
                # Final state
                print(f"\nFINAL rust.priority = {rust_eng._rust.get_priority_player()}")
                print(f"FINAL rust.current_phase = {rust_eng._rust.current_phase()}")

    # And what would Python do?
    print(f"\n--- applying PassPriority to Python for comparison ---")
    py_eng.apply(decision)
    print(f"py.priority_player_idx = {py_eng.engine_state.priority_player_idx}")
    print(f"py.step = {py_eng.engine_state.step}")
    print(f"py.combat_phase = {py_eng.combat_phase}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
