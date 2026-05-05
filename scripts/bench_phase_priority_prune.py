"""Measure the wall-clock savings + prune-fire rate of the phase-
based active-priority prune in ``MtgGameStateAdapter``.

Plays N games of random-vs-random through the adapter, twice:
1. With ``phase_prune_enabled=False`` and the existing opp-capability
   auto-pass active (the "before" baseline).
2. With ``phase_prune_enabled=True`` AND the opp-capability auto-pass
   active (the "after" — both heuristics composed).

Reports:
- Per-game wall delta (mean / median).
- Total priority moments inspected.
- % of those that fired the phase prune.
- % of those that fired the opp-capability auto-pass.
- % that fired EITHER prune (combined).

Random-vs-random is sufficient to characterize the prune rate
because the prune is a structural step+stack-empty check — it does
NOT depend on which agent is choosing. The wall delta will be a
LOWER bound vs production self-play wall delta, because random
games are ``legal_actions``-bound (no NN forward, no MCTS); the
production saving per skipped ``legal_actions`` call is a larger
fraction of total wall.

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/bench_phase_priority_prune.py --n-games 50
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.actions import PassPriority  # noqa: E402
from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.search import (  # noqa: E402
    HeuristicsConfig, MtgGameStateAdapter,
)
from mtg_bot.simulate import (  # noqa: E402
    _default_deck_for_color as _default_deck, setup_game,
)


def _play_one_game(
    seed: int,
    *,
    phase_prune_enabled: bool,
    decision_cap: int,
) -> tuple[float, int, int, int]:
    """Play one random-vs-random game; return
    ``(wall_seconds, priority_moments, phase_prune_fires,
       opp_capability_fires)``.

    Counters are obtained by spying on the adapter's helper methods.
    """
    state = setup_game(
        [RandomAgent(rng=random.Random(seed + 1)),
         RandomAgent(rng=random.Random(seed + 2))],
        decks=[_default_deck("G", seed), _default_deck("R", seed)],
        seed=seed,
    )
    adapter = MtgGameStateAdapter(
        state,
        heuristics=HeuristicsConfig(
            phase_prune_enabled=phase_prune_enabled,
        ),
    )
    rng = random.Random(seed + 99)

    priority_moments = 0
    phase_prune_fires = 0
    opp_capability_fires = 0

    t0 = time.perf_counter()
    n_steps = 0
    while not adapter.is_terminal() and n_steps < decision_cap:
        legal = adapter.legal_decisions()
        if not legal:
            break
        # Detect prune fires: legal == [PassPriority()] AND we skipped
        # the legal_actions enumeration. We can ask the helpers
        # directly — they're cheap idempotent inspections.
        is_pass_only = (
            len(legal) == 1 and isinstance(legal[0], PassPriority)
        )
        if is_pass_only:
            priority_moments += 1
            # Disambiguate phase-prune vs opp-capability vs natural
            # pass-only. The helpers are idempotent.
            if (
                phase_prune_enabled
                and adapter._should_phase_prune_priority()
            ):
                phase_prune_fires += 1
            elif adapter._can_short_circuit_to_pass():
                opp_capability_fires += 1
        else:
            priority_moments += 1
        # Pick a random legal decision and apply.
        adapter.apply(rng.choice(legal))
        n_steps += 1
    return (
        time.perf_counter() - t0,
        priority_moments,
        phase_prune_fires,
        opp_capability_fires,
    )


def _summarize(label: str, times: list[float]) -> None:
    print(
        f"{label}: "
        f"mean={statistics.mean(times)*1000:.1f}ms  "
        f"median={statistics.median(times)*1000:.1f}ms  "
        f"min={min(times)*1000:.1f}ms  "
        f"max={max(times)*1000:.1f}ms"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-games", type=int, default=30)
    p.add_argument("--base-seed", type=int, default=42)
    p.add_argument("--decision-cap", type=int, default=2000)
    p.add_argument(
        "--interleave", action="store_true",
        help=(
            "Interleave on/off runs per game so CPU thermal / "
            "background-load drift cancels out across the two means. "
            "Without this, run-1 and run-2 are sequentially scheduled "
            "and the second pass typically faces hotter cores / "
            "throttled clocks; the wall delta becomes noise-bound."
        ),
    )
    args = p.parse_args()

    print(
        f"# bench_phase_priority_prune: n_games={args.n_games}  "
        f"base_seed={args.base_seed}  decision_cap={args.decision_cap}"
    )
    print()
    off_walls: list[float] = []
    on_walls: list[float] = []
    off_moments = 0
    off_phase = 0
    off_capability = 0
    on_moments = 0
    on_phase = 0
    on_capability = 0

    if args.interleave:
        print(
            "Mode: interleaved (alternating on/off per game)"
        )
        for i in range(args.n_games):
            wall_off, moments_off, phase_off, cap_off = _play_one_game(
                args.base_seed + i,
                phase_prune_enabled=False,
                decision_cap=args.decision_cap,
            )
            wall_on, moments_on, phase_on, cap_on = _play_one_game(
                args.base_seed + i,
                phase_prune_enabled=True,
                decision_cap=args.decision_cap,
            )
            off_walls.append(wall_off)
            on_walls.append(wall_on)
            off_moments += moments_off
            off_phase += phase_off
            off_capability += cap_off
            on_moments += moments_on
            on_phase += phase_on
            on_capability += cap_on
    else:
        # Baseline: phase prune OFF (opp-capability still on).
        print("Pass 1: phase_prune_enabled=False (opp-capability only)")
        for i in range(args.n_games):
            wall, moments, phase, cap = _play_one_game(
                args.base_seed + i,
                phase_prune_enabled=False,
                decision_cap=args.decision_cap,
            )
            off_walls.append(wall)
            off_moments += moments
            off_phase += phase
            off_capability += cap
        # Combined: phase prune ON.
        print("Pass 2: phase_prune_enabled=True (both heuristics)")
        for i in range(args.n_games):
            wall, moments, phase, cap = _play_one_game(
                args.base_seed + i,
                phase_prune_enabled=True,
                decision_cap=args.decision_cap,
            )
            on_walls.append(wall)
            on_moments += moments
            on_phase += phase
            on_capability += cap

    print()
    print("Phase-prune OFF (baseline):")
    _summarize("  per-game wall", off_walls)
    print(
        f"  priority moments: {off_moments}  "
        f"phase-prune fires: {off_phase} "
        f"({100 * off_phase / max(off_moments, 1):.1f}%)  "
        f"capability fires: {off_capability} "
        f"({100 * off_capability / max(off_moments, 1):.1f}%)"
    )
    print()
    print("Phase-prune ON (both heuristics):")
    _summarize("  per-game wall", on_walls)
    print(
        f"  priority moments: {on_moments}  "
        f"phase-prune fires: {on_phase} "
        f"({100 * on_phase / max(on_moments, 1):.1f}%)  "
        f"capability fires: {on_capability} "
        f"({100 * on_capability / max(on_moments, 1):.1f}%)"
    )
    combined_fires = on_phase + on_capability
    print(
        f"  combined fire rate: "
        f"{100 * combined_fires / max(on_moments, 1):.1f}%"
    )
    print()
    # Wall delta.
    mean_off = statistics.mean(off_walls)
    mean_on = statistics.mean(on_walls)
    if mean_off > 0:
        delta_pct = 100 * (mean_off - mean_on) / mean_off
        print(
            f"# wall delta (mean): {mean_off*1000:.1f}ms -> "
            f"{mean_on*1000:.1f}ms = {delta_pct:+.1f}%"
        )
    else:
        print("# wall delta: baseline 0; cannot compute.")


if __name__ == "__main__":
    main()
