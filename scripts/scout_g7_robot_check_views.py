"""Drill: check if the battlefield field-view diverges at step 1712
(GM cast resolves on Python but apparently not on Rust). The earlier
probe showed STATE_EQ doesn't trip until step 1724; this script
asserts compare_fields(py_view, rust_view) at every step 1708-1724 to
see exactly which field is silently masked or shows up late.
"""
from __future__ import annotations

import pathlib
import random
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main():
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields, parity_smoke,
    )
    from mtg_bot.search.rust_shadow import build_shadow_checked_adapter

    deck_names = trajectory.load_production_deck(archetype=9)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=4,
    )

    adapter = build_shadow_checked_adapter(spec)
    py_state = adapter.py_adapter.engine_state
    rust_state = adapter.rust_adapter.rust_state
    ps = parity_smoke()

    rng = random.Random(4)
    steps = 0

    while steps < 1725:
        if adapter.is_terminal():
            print(f"TERMINAL at step {steps}")
            return
        legal = adapter.legal_decisions()
        if not legal:
            return
        choice = rng.choice(legal)
        kind = type(choice).__name__
        adapter.apply(choice)
        if steps >= 1709 and steps <= 1724:
            py_view = build_python_field_view(py_state)
            rust_view = ps._build_field_view(rust_state)
            divs = compare_fields(py_view, rust_view)
            print(f"step {steps} {kind}: divs={len(divs)}")
            for d in divs:
                py_v = d.py_value
                ru_v = d.rust_value
                print(f"  FIELD {d.field}: py={py_v!r:.180s}")
                print(f"                  ru={ru_v!r:.180s}")
        steps += 1


if __name__ == "__main__":
    main()
