"""Scout: drive arch1/s1 through rust_shadow bake-in post-delayed-trigger
port, find where the new trip surfaces and what fields diverge."""
from __future__ import annotations
import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.parity.cross_engine import (
    build_python_field_view, compare_fields, parity_smoke,
)
from mtg_bot.search.rust_shadow import (
    build_shadow_checked_adapter as _bsca,
    ShadowDivergenceError,
)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=4000)
    args = ap.parse_args()
    deck = trajectory.load_production_deck(archetype=args.arch)
    spec = trajectory.production_deck_to_deckspec(deck, shared_rng_seed=args.seed)
    adapter = _bsca(spec)
    py_a, rust_a = adapter.py_adapter, adapter.rust_adapter
    ps = parity_smoke()

    rng = random.Random(args.seed)
    steps = 0
    raised: ShadowDivergenceError | None = None
    while not adapter.is_terminal() and steps < args.max_steps:
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            raised = e
            break
        if not legal:
            break
        choice = rng.choice(legal)
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            raised = e
            break
        steps += 1

    print(f"steps_taken: {steps}")
    print(f"terminal:    {adapter.is_terminal()}")
    print(f"raised:      {raised is not None}")
    if raised is not None:
        print(f"tripwire:    {raised.tripwire}")
        print(f"msg:         {str(raised)[:400]}")
        pv = build_python_field_view(py_a.engine_state)
        rv = ps._build_field_view(rust_a.rust_state)
        divs = compare_fields(pv, rv)
        print(f"divs_count:  {len(divs)}")
        for d in divs[:8]:
            print(f"  field={d.field!r}")
            print(f"    py  ={d.py_value!r}")
            print(f"    rust={d.rust_value!r}")
        print(f"py.stack:  {pv.get('stack')!r}")
        print(f"rust.stack:{rv.get('stack')!r}")
        print(f"py.phase:  {pv.get('phase')!r} step={pv.get('step')!r}")
        print(f"rust.phase:{rv.get('phase')!r} step={rv.get('step')!r}")
        print(f"py.active: {pv.get('active_player')!r}")
        print(f"rust.active:{rv.get('active_player')!r}")
        print(f"py.priority_player:  {pv.get('priority_player')!r}")
        print(f"rust.priority_player:{rv.get('priority_player')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
