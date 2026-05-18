"""Trace Python's DECLARE_ATTACKERS-entry priority sequence at the
arch5/s0 step-367 boundary, and the Rust-driver adapter's mirror, to
locate the exact priority-advance divergence.
"""

from __future__ import annotations

import random
import sys

from mtg_bot.parity import trajectory
from mtg_bot.search import engine_adapter as ea
from mtg_bot.search.engine_adapter_factory import build_shadow_checked_adapter
from mtg_bot.search.rust_shadow import ShadowDivergenceError


def main(arch: int, seed: int) -> None:
    names = trajectory.load_production_deck(archetype=arch)
    spec = trajectory.production_deck_to_deckspec(names, shared_rng_seed=seed)
    adapter = build_shadow_checked_adapter(spec)
    rng = random.Random(seed)
    rust = adapter.rust_adapter
    py = adapter.py_adapter
    pystate = py.engine_state

    orig_eda = ea.MtgGameStateAdapter._enter_declare_attackers
    orig_epfcs = ea.MtgGameStateAdapter._enter_priority_for_current_step
    orig_rpa = ea.MtgGameStateAdapter._run_priority_action
    orig_ats = ea.MtgGameStateAdapter._advance_to_next_step
    trace = {"on": False}

    def eda(self):
        if trace["on"]:
            ap = self._state.active_player()
            elig = ea.eligible_attackers(self._state, ap.id)
            print(
                f"  PY._enter_declare_attackers: active={ap.id} "
                f"expose_combat={self._expose_combat} "
                f"eligible={[o.id for o in elig]} "
                f"pri_before={self._state.priority_player_idx}"
            )
        orig_eda(self)
        if trace["on"]:
            print(
                f"    -> combat_phase={self._combat_phase} "
                f"pri_after={self._state.priority_player_idx}"
            )

    def epfcs(self):
        orig_epfcs(self)
        if trace["on"]:
            print(
                f"  PY._enter_priority_for_current_step -> "
                f"pri={self._state.priority_player_idx} "
                f"active={self._state.active_player_idx} "
                f"step={self._state.step}"
            )

    def rpa(self, decision):
        if trace["on"]:
            print(
                f"  PY._run_priority_action({decision!r}) "
                f"pre pri={self._state.priority_player_idx} "
                f"act={self._state.active_player_idx} "
                f"step={self._state.step} pass={self._pass_count} "
                f"stack={len(self._state.stack)}"
            )
        orig_rpa(self, decision)
        if trace["on"]:
            print(
                f"    -> post pri={self._state.priority_player_idx} "
                f"step={self._state.step} pass={self._pass_count}"
            )

    def ats(self):
        cur = self._state.step
        orig_ats(self)
        if trace["on"]:
            print(
                f"  PY._advance_to_next_step {cur} -> "
                f"{self._state.step}"
            )

    ea.MtgGameStateAdapter._enter_declare_attackers = eda
    ea.MtgGameStateAdapter._enter_priority_for_current_step = epfcs
    ea.MtgGameStateAdapter._run_priority_action = rpa
    ea.MtgGameStateAdapter._advance_to_next_step = ats

    steps = 0
    while not adapter.is_terminal() and steps < 400:
        if steps >= 364:
            trace["on"] = True
            print(
                f"== step {steps} | PY pri={pystate.priority_player_idx} "
                f"act={pystate.active_player_idx} step={pystate.step} "
                f"pass={py._pass_count} | RUST pri="
                f"{int(rust._rust.get_priority_player())} "
                f"act={int(rust._rust.active_player_idx)} "
                f"phase={int(rust._rust.current_phase())} "
                f"pass={rust._pass_count}"
            )
        try:
            legal = adapter.legal_decisions()
        except ShadowDivergenceError as e:
            print(f"[LEGAL trip @ {steps}] {e}")
            return
        if not legal:
            return
        choice = rng.choice(legal)
        if steps >= 364:
            print(f"  choice={choice!r}")
        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            print(f"\n[TRIP @ step {steps}] {e.tripwire}: {e}")
            return
        steps += 1


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    s = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    main(a, s)
