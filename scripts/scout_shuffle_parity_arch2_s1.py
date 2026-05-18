"""Verify-first scout for b3f7c0a9: reproduce arch2/s1 step 320 STATE_EQ
on library_p1 and inspect the divergence shape (same multiset, different
order? or genuinely different content?).

Drives the rust_shadow bake-in like the closure pin and prints:
- The trip step + tripwire kind
- The full diverged-fields detail
- Multiset comparison of both engines' library_p1 at the trip moment

Throwaway diagnostic; not committed to permanent test pins.
"""
from __future__ import annotations

import random
import sys
import collections

from mtg_bot.parity import trajectory
from mtg_bot.search.engine_adapter_factory import (
    build_shadow_checked_adapter,
)
from mtg_bot.search.rust_shadow import ShadowDivergenceError


def main() -> None:
    arch, seed = 2, 1
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(
        names, shared_rng_seed=seed
    )
    adapter = build_shadow_checked_adapter(spec)
    py_state = adapter._py.engine_state
    rust_state = adapter._rust.rust_state
    print(f"py state.rng = {py_state.rng!r}")
    print(f"py state.rng.getstate hash = {hash(py_state.rng.getstate())}")
    # rust has no python-side rng query method; just note whether one is set
    decision_rng = random.Random(seed)
    steps = 0
    raised: ShadowDivergenceError | None = None
    raw_exc: BaseException | None = None
    last_legal = None
    while not adapter.is_terminal() and steps < 400:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        if not legal:
            break
        last_legal = legal
        choice = decision_rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        except Exception as e:  # noqa: BLE001
            raw_exc = e
            break
        steps += 1

    print(f"steps = {steps}")
    print(f"raised = {raised}")
    print(f"raw_exc = {raw_exc}")

    if raised is not None:
        print(f"tripwire = {raised.tripwire}")
        msg = str(raised)
        print("--- divergence detail ---")
        print(msg[:4000])
        print("--- end ---")

    # Compare library_p1 contents
    p1 = py_state.players[1]
    py_lib = [(obj.id, obj.printing.name) for obj in p1.library]
    print(f"py library_p1 length: {len(py_lib)}")
    py_multiset = collections.Counter(name for _, name in py_lib)
    print(f"py library_p1 multiset (top 8): {py_multiset.most_common(8)}")

    # Rust library_p1 via snapshot
    rust_snap = rust_state.snapshot_objects()
    rust_lib_p1 = [
        (obj_id, obj_dict)
        for obj_id, obj_dict in rust_snap.items()
        if obj_dict.get("zone") == "library"
        and obj_dict.get("owner") == 1
    ]
    print(f"rust library_p1 length: {len(rust_lib_p1)}")


if __name__ == "__main__":
    main()
