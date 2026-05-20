"""Throwaway diagnostic: deep-trace the priority_player STATE_EQ
divergence axis surfaced by the broader-archetype-sweep v6-v9 cycle
(15/1500 residuals, todo c8d3a5f1).

This scout repros arch=276 seed=1 (a representative py-extra (1,0)
case from the v9 slice, divergence step 857) through the role-swapped
``rust_shadow`` harness. At the divergence step we capture:

* Both engines' ``priority_player`` and ``active_player`` immediately
  BEFORE and AFTER the divergent action's ``apply``.
* The action_dict that triggered the divergence.
* The legal-set canon (rust + python) at the pre-step.
* Phase, turn_number, stack_size, pass_count.
* The N-1 and N-2 prior decisions (so we can see whether this is a
  pass-round-completes branch, a single-pass branch, or a non-pass
  action).
* The Rust ``losers()`` snapshot vs Python's ``has_lost`` per player
  (rules out / confirms a G5-style post-loss-tail bug).

Optional cross-check on arch=290 seed=3 step 968 (another py-extra
case, near-duplicate-deck pair with arch=293).

NOT a production entrypoint — agent-generated investigation tool,
stays under ``scripts/`` per the project's scout-script convention.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import traceback
from typing import Any

from mtg_bot.parity import trajectory
from mtg_bot.search.rust_shadow import (
    ShadowDivergenceError,
    build_shadow_checked_adapter,
    canon_decision,
    canon_set,
)


def _snapshot(adapter) -> dict:
    """Take a single-call snapshot of priority/active/phase/etc on
    both engines. Pure observation — no state mutation."""
    py = adapter._py
    rust = adapter._rust
    py_state = py.engine_state
    info: dict = {}
    # Python side
    info["py_priority_player"] = int(py_state.priority_player_idx)
    info["py_active_player"] = int(py_state.active_player_idx)
    info["py_phase"] = py_state.step.name if hasattr(py_state.step, "name") else int(py_state.step)
    info["py_turn"] = int(py_state.turn_number)
    info["py_has_lost"] = [bool(p.has_lost) for p in py_state.players]
    info["py_lives"] = [int(p.life) for p in py_state.players]
    info["py_lib_sizes"] = [len(p.library) for p in py_state.players]
    info["py_stack_size"] = len(py_state.stack)
    info["py_combat_phase"] = (
        getattr(py.combat_phase, "name", py.combat_phase)
        if py.combat_phase is not None else None
    )
    info["py_pass_count"] = int(py._pass_count)
    # Rust side via the adapter's accessors (avoid touching internals)
    info["rust_priority_player"] = int(rust._rust.get_priority_player())
    info["rust_active_player"] = int(rust._rust.active_player_idx)
    info["rust_phase"] = int(rust._rust.current_phase())
    info["rust_turn"] = int(rust._rust.turn_number)
    info["rust_losers"] = sorted(int(p) for p in rust._rust.losers())
    info["rust_stack_size"] = int(rust._rust.stack_size())
    info["rust_combat_phase"] = (
        str(rust._combat_phase) if rust._combat_phase is not None else None
    )
    info["rust_pass_count"] = int(rust._pass_count)
    info["rust_pending_attackers"] = list(rust._pending_attackers)
    info["rust_pending_blockers"] = list(rust._pending_blockers)
    info["rust_finalized_combat_window"] = rust._finalized_combat_window
    return info


def _decision_repr(d) -> str:
    return f"{type(d).__name__}({canon_decision(d)})"


def trace(arch: int, seed: int, target_step: int, lookback: int = 10) -> dict:
    """Run the rust_shadow harness deterministically until divergence.
    Print pre/post snapshots for the last ``lookback`` decisions plus
    the divergent step itself."""
    deck_names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=seed,
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    history: list[dict] = []
    steps = 0
    result: dict = {"arch": arch, "seed": seed, "target_step": target_step}
    while steps < 4000:
        if adapter.is_terminal():
            result["status"] = "terminal-no-divergence"
            result["final_step"] = steps
            return result
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            result["status"] = f"legal-set-divergence:{e.tripwire}"
            result["detail"] = str(e)[:400]
            result["step"] = steps
            result["history"] = history[-lookback:]
            return result
        if not legal:
            result["status"] = "empty-legal"
            result["step"] = steps
            return result
        choice = rng.choice(legal)
        pre = _snapshot(adapter)
        pre["step"] = steps
        pre["chosen"] = _decision_repr(choice)
        pre["chosen_canon"] = canon_decision(choice)
        pre["n_legal"] = len(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            # Snapshot what we can post-apply (Python side may have
            # raised cleanly; Rust may have applied — we test both).
            post: dict = {"step": steps, "tripwire": e.tripwire,
                          "detail": str(e)[:400]}
            try:
                post.update({"post_" + k: v for k, v in _snapshot(adapter).items()})
            except Exception as snap_e:  # noqa: BLE001
                post["snapshot_error"] = (
                    f"{type(snap_e).__name__}: {snap_e}"
                )
            history.append({**pre, "post": post})
            result["status"] = f"divergence:{e.tripwire}"
            result["step"] = steps
            result["divergent_pre"] = pre
            result["divergent_post"] = post
            result["history"] = history[-lookback:]
            return result
        post = _snapshot(adapter)
        history.append({**pre, "post": post})
        steps += 1
    result["status"] = "timeout"
    result["step"] = steps
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archetype", type=int, default=276)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--target-step", type=int, default=857)
    ap.add_argument("--lookback", type=int, default=12)
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()
    result = trace(args.archetype, args.seed, args.target_step, args.lookback)
    # Print human-readable summary
    print("=" * 72)
    print(f"arch={args.archetype} seed={args.seed} target_step={args.target_step}")
    print(f"status: {result.get('status')}")
    print(f"step: {result.get('step')}")
    if "divergent_pre" in result:
        pre = result["divergent_pre"]
        post = result["divergent_post"]
        print("--- divergent action ---")
        print(f"  chosen: {pre.get('chosen')}")
        print(f"  chosen_canon: {pre.get('chosen_canon')}")
        print(f"  n_legal_pre: {pre.get('n_legal')}")
        print("--- PRE-APPLY snapshot ---")
        for k, v in pre.items():
            if k in ("chosen", "chosen_canon", "n_legal", "step"):
                continue
            print(f"  {k}: {v}")
        print("--- POST-APPLY snapshot / tripwire ---")
        for k, v in post.items():
            print(f"  {k}: {v}")
        print(f"--- history (last {args.lookback}) ---")
        for h in result["history"]:
            print(
                f"  step={h['step']:>4} chosen={h.get('chosen')} "
                f"py_pri={h.get('py_priority_player')} "
                f"rust_pri={h.get('rust_priority_player')} "
                f"py_phase={h.get('py_phase')} "
                f"rust_phase={h.get('rust_phase')} "
                f"py_ap={h.get('py_active_player')} "
                f"rust_ap={h.get('rust_active_player')} "
                f"stack=({h.get('py_stack_size')},{h.get('rust_stack_size')}) "
                f"passes=({h.get('py_pass_count')},{h.get('rust_pass_count')}) "
                f"combat=({h.get('py_combat_phase')},{h.get('rust_combat_phase')})"
            )
            post_h = h.get("post") or {}
            print(
                f"       -> POST py_pri={post_h.get('py_priority_player')} "
                f"rust_pri={post_h.get('rust_priority_player')} "
                f"py_phase={post_h.get('py_phase')} "
                f"rust_phase={post_h.get('rust_phase')} "
                f"passes=({post_h.get('py_pass_count')},{post_h.get('rust_pass_count')})"
            )
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
        print(f"\nWrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
