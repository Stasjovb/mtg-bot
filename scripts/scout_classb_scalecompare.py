"""Throwaway: classify the FIRST rust_shadow divergence (status, step,
tripwire, shape-prefix) per (arch,seed) across a representative sweep.
Run this on the PRISTINE-worktree wheel and the CHANGED-worktree wheel
and diff the JSON to prove whether the option-beta state_ops_legal.rs
change is behavior-neutral at scale (zero boundary shift) or regresses.
"""

from __future__ import annotations

import json
import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.search.engine_adapter_factory import build_shadow_checked_adapter
from mtg_bot.search.rust_shadow import ShadowDivergenceError


def classify(arch: int, seed: int, max_steps: int = 400) -> dict:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        names, shared_rng_seed=seed
    )
    try:
        adapter = build_shadow_checked_adapter(spec)
    except ShadowDivergenceError as e:
        return {"arch": arch, "seed": seed, "status": "FAIL_CONSTRUCT",
                "step": 0, "tripwire": e.tripwire,
                "shape": str(e)[:120]}
    rng = random.Random(seed)
    steps = 0
    while steps < max_steps:
        try:
            if adapter.is_terminal():
                return {"arch": arch, "seed": seed, "status": "PASS",
                        "step": steps, "tripwire": None, "shape": None}
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            return {"arch": arch, "seed": seed,
                    "status": "FAIL_DIVERGENCE", "step": steps,
                    "tripwire": e.tripwire, "shape": str(e)[:120]}
        if not legal:
            return {"arch": arch, "seed": seed, "status": "EMPTY_LEGAL",
                    "step": steps, "tripwire": None, "shape": None}
        choice = rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            return {"arch": arch, "seed": seed,
                    "status": "FAIL_DIVERGENCE", "step": steps,
                    "tripwire": e.tripwire, "shape": str(e)[:120]}
        except Exception as e:  # noqa: BLE001
            return {"arch": arch, "seed": seed, "status": "RAW_EXC",
                    "step": steps, "tripwire": type(e).__name__,
                    "shape": str(e)[:120]}
        steps += 1
    return {"arch": arch, "seed": seed, "status": "TIMEOUT",
            "step": steps, "tripwire": None, "shape": None}


def main(out_path: str, n_arch: int, seeds: list[int]) -> None:
    rows = []
    for a in range(n_arch):
        for s in seeds:
            r = classify(a, s)
            rows.append(r)
            print(f"arch{a}/s{s}: {r['status']} @{r['step']} "
                  f"{r['tripwire']} {r['shape']}")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"[wrote {out_path}] {len(rows)} rows")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/scale.json"
    na = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    sd = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 \
        else [0, 1, 2, 3, 4]
    main(out, na, sd)
