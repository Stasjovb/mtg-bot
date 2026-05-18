"""Trace the Rust-driver adapter's priority sequence around step 367
(arch5/s0), with the STATE_EQ priority_player check NEUTERED so we can
see how Rust would proceed past the trip and where Python re-syncs
priority — to scope the byte-mirror fix precisely.
"""

from __future__ import annotations

import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.search import rust_shadow as rs
from mtg_bot.search.engine_adapter_factory import build_shadow_checked_adapter


def main(arch: int, seed: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)

    # Neuter ONLY the priority_player compare so we can see how the run
    # would proceed (characterization only — NOT a shipped change).
    orig = rs.ShadowCheckedRustAdapter._assert_state_eq

    def patched(self):
        from mtg_bot.parity.cross_engine import (
            build_python_field_view, compare_fields, parity_smoke,
        )
        ps = parity_smoke()
        pv = build_python_field_view(self._py.engine_state)
        rv = ps._build_field_view(self._rust.rust_state)
        divs = [d for d in compare_fields(pv, rv)
                if d.field != "priority_player"]
        if divs:
            raise rs.ShadowDivergenceError(
                "STATE_EQ",
                repr([(d.field, d.py_value, d.rust_value) for d in divs]))

    rs.ShadowCheckedRustAdapter._assert_state_eq = patched

    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    rust = adapter.rust_adapter
    py = adapter.py_adapter
    pystate = py.engine_state
    steps = 0
    while not adapter.is_terminal() and steps < 400:
        if 364 <= steps <= 380:
            print(
                f"step {steps}: PY[pri={pystate.priority_player_idx} "
                f"act={pystate.active_player_idx} step={pystate.step} "
                f"pass={py._pass_count} combat={py.combat_phase}] "
                f"RUST[pri={int(rust._rust.get_priority_player())} "
                f"act={int(rust._rust.active_player_idx)} "
                f"phase={int(rust._rust.current_phase())} "
                f"pass={rust._pass_count} combat={rust._combat_phase}]"
            )
        try:
            legal = adapter.legal_decisions()
        except rs.ShadowDivergenceError as e:
            print(f"[LEGAL trip @ {steps}] {e.tripwire}: {e}")
            return
        if not legal:
            print(f"[empty legal @ {steps}]")
            return
        choice = rng.choice(legal)
        if 364 <= steps <= 380:
            print(f"   choice={choice!r}")
        try:
            adapter.apply(choice)
        except rs.ShadowDivergenceError as e:
            print(f"\n[TRIP @ step {steps}] {e.tripwire}: {e}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"\n[RAW @ step {steps}] {type(e).__name__}: {e}")
            return
        steps += 1
    print(f"[end @ {steps} terminal={adapter.is_terminal()}]")


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    s = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    main(a, s)
