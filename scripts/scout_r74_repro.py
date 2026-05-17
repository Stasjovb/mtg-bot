"""Round-74 minimal-repro tracer for the spell-cast-path FAIL_DIVERGENCE.

Drives one (archetype, seed) game with the bench's OWN per-step
primitives but stops at the FIRST per-step (not combat-phase-aggregate)
divergence and dumps: the action that caused it, the full field-diff
list, and the game log tail on both engines so we can localize which
spell/keyword/counter the engines compute differently.

Read-only diagnostic; modifies no production / bench-script code.
"""

from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))            # repo root (tests pkg)
sys.path.insert(0, str(_HERE.parent / "src"))    # src

import scripts.bench_trajectory_parity as bench  # noqa: E402
from mtg_bot.parity import trajectory  # noqa: E402
from mtg_bot.parity.cross_engine import (  # noqa: E402
    build_python_field_view,
    compare_fields,
    parity_smoke,
)
from mtg_bot.turn import Step  # noqa: E402


def trace(archetype: int, seed: int, max_turns: int = 120) -> None:
    deck = trajectory.load_production_deck(archetype=archetype)
    py_state, rust_state = trajectory.setup_matched_game_from_real_decks(
        deck, shared_rng_seed=seed,
    )
    combat_agent = trajectory.RealGameCombatAgent(strategy="attack_all")

    def snap_compare(tag: str) -> bool:
        ps = parity_smoke()
        divs = compare_fields(
            build_python_field_view(py_state),
            ps._build_field_view(rust_state),
        )
        if divs:
            print(f"\n==== FIRST DIVERGENCE @ {tag} "
                  f"turn={py_state.turn_number} step={py_state.step} ====")
            for d in divs:
                print(f"   {d.field}: py={d.py_value!r} rust={d.rust_value!r} "
                      f"known_gap={getattr(d, 'known_gap', None)!r}")
            print("\n--- Python log tail (last 25) ---")
            for ln in list(getattr(py_state, "log", []))[-25:]:
                print("  PY ", ln)
            try:
                rlog = rust_state.game_log()
            except Exception:
                rlog = []
            print("\n--- Rust log tail (last 25) ---")
            for ln in list(rlog)[-25:]:
                print("  RS ", ln)
            return True
        return False

    n = 0
    while not bench._game_over(py_state):
        if py_state.turn_number > max_turns:
            print("TIMEOUT")
            return
        if py_state.step == Step.PRECOMBAT_MAIN:
            try:
                pl = bench._try_play_one_land(py_state, rust_state)
            except bench._DivergenceError as e:
                print(f"\n==== _DivergenceError on {e.action} ====")
                for d in e.divergences:
                    print(f"   {d.field}: py={d.py_value!r} "
                          f"rust={d.rust_value!r}")
                _dump_logs(py_state, rust_state)
                return
            if pl:
                n += 1
                if snap_compare(f"after play_land #{n}"):
                    return
            while True:
                try:
                    c = bench._try_cast_one_creature(py_state, rust_state)
                except bench._DivergenceError as e:
                    print(f"\n==== _DivergenceError on cast {e.action} ====")
                    for d in e.divergences:
                        print(f"   {d.field}: py={d.py_value!r} "
                              f"rust={d.rust_value!r}")
                    _dump_logs(py_state, rust_state)
                    return
                if c is None:
                    break
                n += 1
                print(f"[t{py_state.turn_number}] CAST/PLAY {c}")
                if snap_compare(f"after cast {c.get('card_id')}"):
                    return
            try:
                bench._advance_phase_with_compare(py_state, rust_state)
            except bench._DivergenceError as e:
                print(f"\n==== phase-advance divergence "
                      f"turn={py_state.turn_number} ====")
                for d in e.divergences:
                    print(f"   {d.field}: py={d.py_value!r} "
                          f"rust={d.rust_value!r}")
                _dump_logs(py_state, rust_state)
                return
            continue
        if py_state.step == Step.DECLARE_ATTACKERS:
            try:
                trajectory.drive_combat_phase(
                    py_state, rust_state, combat_agent,
                )
            except AssertionError as e:
                print(f"\n==== COMBAT-PHASE divergence "
                      f"turn={py_state.turn_number} ====")
                print(str(e)[:1500])
                _dump_logs(py_state, rust_state)
                return
            n += 1
            try:
                bench._advance_phase_with_compare(py_state, rust_state)
            except bench._DivergenceError as e:
                print(f"\n==== phase-advance divergence post-combat "
                      f"turn={py_state.turn_number} ====")
                for d in e.divergences:
                    print(f"   {d.field}: py={d.py_value!r} "
                          f"rust={d.rust_value!r}")
                _dump_logs(py_state, rust_state)
                return
            continue
        try:
            bench._advance_phase_with_compare(py_state, rust_state)
        except bench._DivergenceError as e:
            print(f"\n==== phase-advance divergence "
                  f"turn={py_state.turn_number} step={py_state.step} ====")
            for d in e.divergences:
                print(f"   {d.field}: py={d.py_value!r} "
                      f"rust={d.rust_value!r}")
            _dump_logs(py_state, rust_state)
            return
    print(f"GAME OVER cleanly turn={py_state.turn_number}")


def _dump_logs(py_state, rust_state) -> None:
    print("\n--- Python log tail (last 30) ---")
    for ln in list(getattr(py_state, "log", []))[-30:]:
        print("  PY ", ln)
    try:
        rlog = rust_state.game_log()
    except Exception:
        rlog = []
    print("\n--- Rust log tail (last 30) ---")
    for ln in list(rlog)[-30:]:
        print("  RS ", ln)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--archetype", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--max-turns", type=int, default=120)
    a = p.parse_args()
    trace(a.archetype, a.seed, a.max_turns)
