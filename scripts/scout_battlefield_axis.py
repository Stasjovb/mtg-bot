"""Throwaway diagnostic: deep-trace the battlefield STATE_EQ
divergence axis surfaced by the broader-archetype-sweep v9 cycle
(4/300 residuals, todo e5b7c9d8).

This scout repros the 4 v9 battlefield-STATE_EQ residuals (defaults
to arch=253 seed=2 step 1147) through the role-swapped
``rust_shadow`` harness. It drives the run deterministically until
the harness surfaces the STATE_EQ divergence, then:

* Captures the FULL battlefield diff (py vs rust id sets +
  per-id printing-name + zone metadata).
* Walks the last ``--lookback`` steps to find the FIRST step where
  the two sides' battlefield multisets first diverge (the harness
  trips at the comparison step, but the underlying bug may predate).
* For each step, snapshots both engines' battlefield multisets
  (canonical (name, controller, attacking, blocking, tapped,
  attached_to, summoning_sick, id) tuple per object).
* Identifies the divergent permanent + the action that caused the
  divergence.

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
)


def _py_obj_tuple(obj) -> tuple:
    """Canonical tuple for a Python battlefield object (mirrors the
    shape of the STATE_EQ canon from the exception_message)."""
    return (
        obj.printing.name,
        int(getattr(obj, "controller_id", -1)),
        int(bool(getattr(obj, "tapped", False))),
        int(bool(getattr(obj, "attacking", False))),
        int(bool(getattr(obj, "blocking", False))),
        getattr(obj, "attached_to", None),
        int(bool(getattr(obj, "summoning_sick", False))),
        int(obj.id),
    )


def _rust_obj_tuple(obj_dict_like) -> tuple:
    d = dict(obj_dict_like)
    return (
        d.get("printing_name", ""),
        int(d.get("controller_id", -1)),
        int(bool(d.get("tapped", False))),
        int(bool(d.get("attacking", False))),
        int(bool(d.get("blocking", False))),
        d.get("attached_to", None),
        int(bool(d.get("summoning_sick", False))),
        int(d.get("id", -1)),
    )


def _battlefield_snap(adapter) -> dict:
    """Snapshot both engines' battlefield as canonical tuple lists."""
    py = adapter._py
    rust = adapter._rust
    py_bf = [_py_obj_tuple(o) for o in py.engine_state.battlefield]
    rust_bf = [_rust_obj_tuple(o) for o in rust._rust.battlefield_snapshot()]
    py_ids = {t[7] for t in py_bf}
    rust_ids = {t[7] for t in rust_bf}
    py_only = py_ids - rust_ids
    rust_only = rust_ids - py_ids
    # For shared ids, identify per-attribute disagreements
    py_by_id = {t[7]: t for t in py_bf}
    rust_by_id = {t[7]: t for t in rust_bf}
    field_disagreements = []
    for shared_id in py_ids & rust_ids:
        if py_by_id[shared_id] != rust_by_id[shared_id]:
            field_disagreements.append((
                shared_id, py_by_id[shared_id], rust_by_id[shared_id],
            ))
    return {
        "py_n": len(py_bf),
        "rust_n": len(rust_bf),
        "py_only_ids": sorted(py_only),
        "rust_only_ids": sorted(rust_only),
        "py_only_items": [py_by_id[i] for i in sorted(py_only)],
        "rust_only_items": [rust_by_id[i] for i in sorted(rust_only)],
        "field_disagreements": field_disagreements,
        "py_full": py_bf,
        "rust_full": rust_bf,
    }


def _diff_summary(snap) -> str:
    """One-line summary of the bf diff at this step."""
    if (not snap["py_only_ids"]
            and not snap["rust_only_ids"]
            and not snap["field_disagreements"]):
        return "(matching)"
    parts = []
    if snap["py_only_ids"]:
        parts.append(f"py-only={snap['py_only_items']}")
    if snap["rust_only_ids"]:
        parts.append(f"rust-only={snap['rust_only_items']}")
    if snap["field_disagreements"]:
        parts.append(
            f"field-disagreements={snap['field_disagreements']}"
        )
    return " | ".join(parts)


def _ctx_snapshot(adapter) -> dict:
    """Phase/turn/stack context for one step."""
    py = adapter._py
    rust = adapter._rust
    py_state = py.engine_state
    return {
        "py_phase": (
            py_state.step.name if hasattr(py_state.step, "name")
            else str(py_state.step)
        ),
        "py_turn": int(py_state.turn_number),
        "py_priority": int(py_state.priority_player_idx),
        "py_active": int(py_state.active_player_idx),
        "py_stack": len(py_state.stack),
        "py_pass_count": int(py._pass_count),
        "rust_phase": int(rust._rust.current_phase()),
        "rust_turn": int(rust._rust.turn_number),
        "rust_priority": int(rust._rust.get_priority_player()),
        "rust_active": int(rust._rust.active_player_idx),
        "rust_stack": int(rust._rust.stack_size()),
        "rust_pass_count": int(rust._pass_count),
    }


def _decision_repr(d) -> str:
    return f"{type(d).__name__}({canon_decision(d)})"


def trace(
    arch: int, seed: int, target_step: int, lookback: int = 20,
    max_steps: int = 5000,
) -> dict:
    deck_names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=seed,
    )
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    steps = 0
    # Ring buffer of recent (step, decision, ctx, bf_snap) entries
    history: list[dict] = []
    first_divergent_step: int | None = None
    while steps < max_steps:
        if adapter.is_terminal():
            return {
                "arch": arch, "seed": seed,
                "status": "terminal-no-divergence",
                "final_step": steps,
                "first_divergent_step": first_divergent_step,
                "history": history[-lookback:],
            }
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            return {
                "arch": arch, "seed": seed,
                "status": f"legal-divergence:{e.tripwire}",
                "step": steps,
                "detail": str(e)[:600],
                "first_divergent_step": first_divergent_step,
                "history": history[-lookback:],
            }
        if not legal:
            return {
                "arch": arch, "seed": seed,
                "status": "empty-legal",
                "step": steps,
                "first_divergent_step": first_divergent_step,
                "history": history[-lookback:],
            }
        choice = rng.choice(legal)
        pre_ctx = _ctx_snapshot(adapter)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            # We tripped. Snapshot bf POST-trip (the adapter may have
            # partially applied to one side or both). Then report.
            try:
                post_bf = _battlefield_snap(adapter)
            except Exception as ex:  # noqa: BLE001
                post_bf = {"error": f"{type(ex).__name__}: {ex}"}
            try:
                post_ctx = _ctx_snapshot(adapter)
            except Exception as ex:  # noqa: BLE001
                post_ctx = {"error": f"{type(ex).__name__}: {ex}"}
            history.append({
                "step": steps,
                "chosen": _decision_repr(choice),
                "chosen_canon": canon_decision(choice),
                "pre_ctx": pre_ctx,
                "tripwire": e.tripwire,
                "detail": str(e)[:800],
                "post_ctx": post_ctx,
                "post_bf": post_bf,
            })
            return {
                "arch": arch, "seed": seed,
                "status": f"divergence:{e.tripwire}",
                "step": steps,
                "detail": str(e)[:1200],
                "post_bf": post_bf,
                "first_divergent_step": first_divergent_step,
                "history": history[-lookback:],
            }
        # Successful apply — snapshot bf and check for divergence.
        post_bf = _battlefield_snap(adapter)
        post_ctx = _ctx_snapshot(adapter)
        has_diverged = (
            bool(post_bf["py_only_ids"])
            or bool(post_bf["rust_only_ids"])
            or bool(post_bf["field_disagreements"])
        )
        if has_diverged and first_divergent_step is None:
            first_divergent_step = steps
        history.append({
            "step": steps,
            "chosen": _decision_repr(choice),
            "chosen_canon": canon_decision(choice),
            "pre_ctx": pre_ctx,
            "post_ctx": post_ctx,
            "post_bf_summary": _diff_summary(post_bf),
            "post_bf_diverged": has_diverged,
        })
        # Keep ring buffer bounded
        if len(history) > max(lookback * 4, 60):
            history = history[-(lookback * 4):]
        steps += 1
    return {
        "arch": arch, "seed": seed,
        "status": "timeout-no-divergence",
        "step": steps,
        "first_divergent_step": first_divergent_step,
        "history": history[-lookback:],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archetype", type=int, default=253)
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--target-step", type=int, default=1147)
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=5000)
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()
    result = trace(
        args.archetype, args.seed, args.target_step,
        args.lookback, args.max_steps,
    )
    print("=" * 72)
    print(
        f"arch={args.archetype} seed={args.seed} "
        f"target_step={args.target_step}"
    )
    print(f"status: {result.get('status')}")
    print(f"step: {result.get('step')}")
    print(f"first_divergent_step: {result.get('first_divergent_step')}")
    if "detail" in result:
        print(f"detail: {result['detail']}")
    if "post_bf" in result and isinstance(result["post_bf"], dict):
        pb = result["post_bf"]
        print("\n--- post-trip battlefield diff ---")
        print(f"  py_n={pb.get('py_n')} rust_n={pb.get('rust_n')}")
        print(f"  py-only items: {pb.get('py_only_items')}")
        print(f"  rust-only items: {pb.get('rust_only_items')}")
        print(f"  field disagreements: {pb.get('field_disagreements')}")
    print(f"\n--- history (last {args.lookback}, marked * at first-divergent step) ---")
    fds = result.get("first_divergent_step")
    for h in result.get("history", []):
        marker = "*" if h["step"] == fds else " "
        print(
            f" {marker} step={h['step']:>5} "
            f"chosen={h.get('chosen')}"
        )
        pre = h.get("pre_ctx") or {}
        print(
            f"        pre: py_ph={pre.get('py_phase')} "
            f"turn=({pre.get('py_turn')},{pre.get('rust_turn')}) "
            f"pri=({pre.get('py_priority')},{pre.get('rust_priority')}) "
            f"stack=({pre.get('py_stack')},{pre.get('rust_stack')})"
        )
        if "post_bf_summary" in h:
            print(
                f"        bf : "
                f"{'DIVERGED' if h.get('post_bf_diverged') else 'matching'} "
                f"{h['post_bf_summary']}"
            )
        elif "post_bf" in h:
            pb = h["post_bf"]
            if isinstance(pb, dict):
                print(
                    f"        bf : py_n={pb.get('py_n')} "
                    f"rust_n={pb.get('rust_n')}"
                )
                print(f"        py-only: {pb.get('py_only_items')}")
                print(f"        rust-only: {pb.get('rust_only_items')}")
                print(f"        field-disagree: {pb.get('field_disagreements')}")
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
        print(f"\nWrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
