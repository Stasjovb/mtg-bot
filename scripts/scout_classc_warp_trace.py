"""Throwaway diagnostic: trace the Class-C arch1/s1 Starbreach Whale
divergence step-by-step on the rust_shadow bake-in, dumping the FULL
Rust + Python field views (the exact comparator the bake-in uses)
around the cast (step 151) -> divergence (step 169) so the EXACT
split decision + root cause is identified (verify-first root cause
for G7 S6-Class-C / S4b).

Not a production entrypoint (scripts/scout_* convention).
"""
import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.parity import cross_engine as ce
from mtg_bot.parity.cross_engine import build_python_field_view, compare_fields
from mtg_bot.search.rust_shadow import (
    ShadowDivergenceError,
    build_shadow_checked_adapter,
)


def _ps():
    return ce.parity_smoke()


def _views(py_a, rust_a):
    pv = build_python_field_view(py_a.engine_state)
    rv = _ps()._build_field_view(rust_a.rust_state)
    return pv, rv


def _whale(view_val, oid=81):
    """Return a compact note about obj `oid` membership in a field
    value (a tuple of zone-signature tuples whose last element is id)."""
    if not isinstance(view_val, (list, tuple)):
        return repr(view_val)
    hit = [t for t in view_val if isinstance(t, (list, tuple))
           and t and t[-1] == oid]
    return f"obj{oid}={'IN' if hit else 'out'}({len(view_val)} entries)"


def main():
    import os
    archetype = int(os.environ.get("CC_ARCH", "1"))
    seed = int(os.environ.get("CC_SEED", "1"))
    oid = int(os.environ.get("CC_OID", "81"))
    print(f"=== arch{archetype}/s{seed} tracking obj {oid} ===")
    deck_names = trajectory.load_production_deck(archetype=archetype)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=seed
    )
    adapter = build_shadow_checked_adapter(spec)
    py_a = adapter.py_adapter
    rust_a = adapter.rust_adapter

    rng = random.Random(seed)
    steps = 0
    recent = []
    while steps < 4000:
        if adapter.is_terminal():
            print(f"terminal at step {steps}")
            break
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            print(f"\n*** LEGAL_SET divergence step {steps}: {e.tripwire}")
            print(str(e)[:2000])
            return
        if not legal:
            print(f"empty legal set at step {steps}")
            return
        choice = rng.choice(legal)
        recent.append((steps, repr(choice)[:70]))
        if len(recent) > 6:
            recent.pop(0)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            print(f"\n*** {e.tripwire} divergence step {steps}")
            print(f"applied: {choice!r}")
            print("recent decisions:")
            for s, d in recent:
                print(f"  step {s:>4}  {d}")
            pv, rv = _views(py_a, rust_a)
            for f in ("stack", "battlefield", "exile_p0", "exile_p1",
                      "hand_p1", "graveyard_p1"):
                print(f"  POST {f:<12} py:{_whale(pv.get(f), oid)}"
                      f"  rust:{_whale(rv.get(f), oid)}")
            print("\ncompare_fields raw (field, py, rust):")
            for d in compare_fields(pv, rv):
                print(f"  {d.field}: py={d.py_value} rust={d.rust_value}")
            return
        steps += 1
    print("ended", steps, "terminal=", adapter.is_terminal())


if __name__ == "__main__":
    sys.exit(main())
