"""Verify-first probe for the arch=9/seed=4 Robot-token MISSING-ON-RUST
divergence (G7 S6 scale-verify v3, follow-up todo f8e3a2b1...).

Step-by-step through drive_shadow_game_to_terminal under Random(seed=4),
recording per-step (turn, phase, action, py_bf, rust_bf, py_gy, rust_gy,
py_stack, rust_stack) on BOTH engines from step 1700 onward so we can
identify exactly when/where Python creates the Robot but Rust doesn't.

Usage:
    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/scout_g7_robot_missing.py
"""
from __future__ import annotations

import pathlib
import random
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


CARDS_OF_INTEREST = {"Gravpack Monoist", "Depressurize", "Robot"}


def _py_view(py_state):
    """Returns per-player ((bf_card_summaries), graveyard names), stack summary."""
    out = []
    bf = list(py_state.battlefield)
    for p in py_state.players:
        bf_cards = [(o.id, o.printing.name, o.controller_id,
                     o.tapped, o.summoning_sick)
                    for o in bf
                    if o.controller_id == p.id
                    and o.printing.name in CARDS_OF_INTEREST]
        gy_cards = [(o.id, o.printing.name) for o in p.graveyard
                    if o.printing.name in CARDS_OF_INTEREST]
        out.append((bf_cards, gy_cards))
    stack = []
    for item in py_state.stack:
        kind = type(item).__name__
        source = getattr(item, "source", None)
        if source is not None:
            stack.append((kind, source.printing.name, source.id,
                          getattr(source, "controller_id", "?")))
        else:
            stack.append((kind, None, None, None))
    return out, stack


def _rust_view(rust_state):
    """Returns per-player ((bf_card_summaries), graveyard names), stack."""
    bf_objs = rust_state.battlefield_snapshot()
    out = [[[], []], [[], []]]  # [pid][0]=bf, [pid][1]=gy
    for o in bf_objs:
        nm = o.get("printing_name", "?")
        if nm in CARDS_OF_INTEREST:
            ctrl = o.get("controller_id", o.get("controller"))
            if ctrl in (0, 1):
                out[ctrl][0].append((o.get("id"), nm, ctrl,
                                     o.get("tapped"),
                                     o.get("summoning_sick")))
    for pid in range(2):
        for o in rust_state.graveyard_snapshot(pid):
            nm = o.get("printing_name", "?")
            if nm in CARDS_OF_INTEREST:
                out[pid][1].append((o.get("id"), nm))
    try:
        stack_snap = rust_state.stack_snapshot()
    except TypeError:
        stack_snap = []
    stack = []
    for item in stack_snap:
        nm = "?"
        try:
            pid = item.get("printing_id")
            if pid is not None:
                nm = rust_state.printing_name_of(pid)
        except Exception:
            pass
        stack.append((item.get("kind", "?"), nm,
                      item.get("object_id"), item.get("controller")))
    return out, stack


def main():
    from mtg_bot.parity import trajectory
    from mtg_bot.search.rust_shadow import (
        build_shadow_checked_adapter,
        ShadowDivergenceError,
    )

    deck_names = trajectory.load_production_deck(archetype=9)
    spec = trajectory.production_deck_to_deckspec(
        deck_names, shared_rng_seed=4,
    )

    adapter = build_shadow_checked_adapter(spec)
    py_state = adapter.py_adapter.engine_state
    rust_state = adapter.rust_adapter.rust_state

    rng = random.Random(4)
    steps = 0

    while steps < 4000:
        if adapter.is_terminal():
            print(f"TERMINAL at step {steps}")
            return
        legal = adapter.legal_decisions()
        if not legal:
            print("EMPTY LEGAL")
            return
        choice = rng.choice(legal)
        kind = type(choice).__name__

        if steps >= 1708 and steps <= 1726:
            print(f"=== step {steps} BEFORE apply: {kind} {str(choice)[:120]}")
            py_v = _py_view(py_state)
            ru_v = _rust_view(rust_state)
            print(f"   py p0_bf={py_v[0][0][0]} p0_gy={py_v[0][0][1]}")
            print(f"   py p1_bf={py_v[0][1][0]} p1_gy={py_v[0][1][1]}")
            print(f"   py stack={py_v[1]}")
            print(f"   ru p0_bf={ru_v[0][0][0]} p0_gy={ru_v[0][0][1]}")
            print(f"   ru p1_bf={ru_v[0][1][0]} p1_gy={ru_v[0][1][1]}")
            print(f"   ru stack={ru_v[1]}")

        try:
            adapter.apply(choice)
        except ShadowDivergenceError as e:
            print(f"\nDIVERGENCE at step {steps}: tripwire={e.tripwire}")
            print(f"  decision: {choice!r}")
            print(f"  After apply, both engines applied. Inspect:")
            py_v = _py_view(py_state)
            ru_v = _rust_view(rust_state)
            print(f"   py p0_bf={py_v[0][0][0]} p0_gy={py_v[0][0][1]}")
            print(f"   py p1_bf={py_v[0][1][0]} p1_gy={py_v[0][1][1]}")
            print(f"   py stack={py_v[1]}")
            print(f"   ru p0_bf={ru_v[0][0][0]} p0_gy={ru_v[0][0][1]}")
            print(f"   ru p1_bf={ru_v[0][1][0]} p1_gy={ru_v[0][1][1]}")
            print(f"   ru stack={ru_v[1]}")
            return

        if steps >= 1708 and steps <= 1726:
            print(f"--- step {steps} AFTER apply:")
            py_v = _py_view(py_state)
            ru_v = _rust_view(rust_state)
            print(f"   py p0_bf={py_v[0][0][0]} p0_gy={py_v[0][0][1]}")
            print(f"   py p1_bf={py_v[0][1][0]} p1_gy={py_v[0][1][1]}")
            print(f"   py stack={py_v[1]}")
            print(f"   ru p0_bf={ru_v[0][0][0]} p0_gy={ru_v[0][0][1]}")
            print(f"   ru p1_bf={ru_v[0][1][0]} p1_gy={ru_v[0][1][1]}")
            print(f"   ru stack={ru_v[1]}")
        steps += 1

    print(f"loop ended step {steps}")


if __name__ == "__main__":
    main()
