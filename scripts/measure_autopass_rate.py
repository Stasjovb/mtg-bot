"""Random-walk measurement of capability auto-pass rate.

Counts:
- total priority moments visited
- opp-side auto-passes (priority on non-active player + can't act)
- active-side auto-passes (priority on active player + can't act)
- both-side auto-passes (consecutive auto-pass passes that drive the
  engine through a full opp+active priority round without enumerating)

This is the same methodology referenced in
``docs/perf_opp_autopass_20260504.md`` ("RandomAgent self-play, seed 0,
500 decisions, ~45% of priority moments fire the auto-pass
short-circuit"). Updated to count BOTH the opp and active variants so
we can report on the active-player extension.

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/measure_autopass_rate.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot import legal as legal_mod  # noqa: E402
from mtg_bot.actions import PassPriority  # noqa: E402
from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.search import MtgGameStateAdapter  # noqa: E402
from mtg_bot.simulate import _default_deck_for_color as _default_deck, setup_game  # noqa: E402

# Try to import the new capability function; fall back to opp-only.
try:
    from mtg_bot.search._player_capabilities import (
        has_player_capability_to_act,
    )
    HAS_ACTIVE_API = True
except ImportError:
    from mtg_bot.search._opp_capabilities import opp_can_act
    HAS_ACTIVE_API = False


def main() -> None:
    n_decisions = 500
    seed = 0

    state = setup_game(
        [RandomAgent(), RandomAgent()], decks=[_default_deck("G", seed), _default_deck("R", seed)], seed=seed,
    )
    adapter = MtgGameStateAdapter(state)

    legal_calls = [0]

    real = legal_mod.legal_actions

    def counted(*a, **kw):
        legal_calls[0] += 1
        return real(*a, **kw)

    legal_mod.legal_actions = counted
    from mtg_bot.search import engine_adapter as ea_mod
    ea_mod.legal_actions = counted

    rng = random.Random(seed)
    total_priority_moments = 0
    auto_pass_total = 0
    auto_pass_opp = 0
    auto_pass_active = 0
    cascade_segments = 0  # contiguous-auto-pass runs of length >= 2
    current_run = 0
    decisions = 0

    for _ in range(n_decisions):
        if adapter.is_terminal():
            break
        s = adapter.engine_state
        # Identify priority holder. Skip non-priority "moments"
        # (combat sub-decisions, resolution pauses) — those don't
        # have an auto-pass gate.
        in_combat_or_resolution = (
            getattr(adapter, "_combat_phase", None) is not None
            or getattr(adapter, "_resolution_paused", False)
        )
        is_active_priority = (
            s.priority_player_idx == s.active_player_idx
        )

        decs = adapter.legal_decisions()
        if not in_combat_or_resolution:
            total_priority_moments += 1
            # Auto-pass fires when the only legal decision is
            # PassPriority AND we got there via the short-circuit
            # (no legal_actions enumeration). Easiest signal: the
            # cap cache was populated and ``decs == [PassPriority()]``.
            cap_cache = getattr(adapter, "_opp_cap_cache", None)
            auto_passed = (
                len(decs) == 1
                and isinstance(decs[0], PassPriority)
                and cap_cache is not None
                and cap_cache[-1] is False  # last tuple element is can_act
            )
            if auto_passed:
                auto_pass_total += 1
                if is_active_priority:
                    auto_pass_active += 1
                else:
                    auto_pass_opp += 1
                current_run += 1
                if current_run == 2:
                    cascade_segments += 1
            else:
                current_run = 0

        adapter.apply(rng.choice(decs))
        decisions += 1

    print(f"API: {'active+opp' if HAS_ACTIVE_API else 'opp-only'}")
    print(f"Total decisions: {decisions}")
    print(f"Total priority moments: {total_priority_moments}")
    print(
        f"Auto-passes total: {auto_pass_total}  "
        f"({100*auto_pass_total/max(1,total_priority_moments):.1f}%)"
    )
    print(
        f"  Opp-side: {auto_pass_opp}  "
        f"({100*auto_pass_opp/max(1,total_priority_moments):.1f}%)"
    )
    print(
        f"  Active-side: {auto_pass_active}  "
        f"({100*auto_pass_active/max(1,total_priority_moments):.1f}%)"
    )
    print(
        f"Cascade segments (consecutive >=2 auto-passes): "
        f"{cascade_segments}"
    )
    print(f"Total legal_actions calls: {legal_calls[0]}")


if __name__ == "__main__":
    main()
