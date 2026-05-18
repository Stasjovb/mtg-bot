"""Map Python's priority_player_idx across the full combat sequence at
arch5/s0 (steps 366..400) with the priority_player STATE_EQ compare
neutered, to confirm exactly how a byte-mirror deferral must behave.
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
    while not adapter.is_terminal() and steps < 410:
        if 366 <= steps <= 400:
            rp = int(rust._rust.get_priority_player())
            pp = pystate.priority_player_idx
            flag = "  <-- PRI DIVERGE" if rp != pp else ""
            print(
                f"step {steps}: PY[pri={pp} step={pystate.step} "
                f"combat={py.combat_phase} pass={py._pass_count}] "
                f"RUST[pri={rp} phase={int(rust._rust.current_phase())} "
                f"combat={rust._combat_phase} pass={rust._pass_count}]"
                f"{flag}"
            )
        try:
            legal = adapter.legal_decisions()
        except rs.ShadowDivergenceError as e:
            print(f"[LEGAL trip @ {steps}] {e.tripwire}: {str(e)[:160]}")
            return
        if not legal:
            print(f"[empty @ {steps}]")
            return
        choice = rng.choice(legal)
        if 366 <= steps <= 400:
            print(f"   choice={choice!r}")
        try:
            adapter.apply(choice)
        except rs.ShadowDivergenceError as e:
            print(f"\n[TRIP @ step {steps}] {e.tripwire}: {str(e)[:160]}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"\n[RAW @ {steps}] {type(e).__name__}: {str(e)[:160]}")
            return
        steps += 1
    print(f"[end @ {steps} terminal={adapter.is_terminal()}]")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5,
         int(sys.argv[2]) if len(sys.argv) > 2 else 0)
