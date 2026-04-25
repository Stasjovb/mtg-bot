"""Performance regression guard for ``GameState.clone()``.

One ratio test. We don't assert absolute wall-clock numbers (those
flap with CPU load / machine / Python version). Instead we measure
``clone()`` against ``copy.deepcopy()`` of the same state — both
scale with machine speed so the ratio is robust.

Current ratio (as of the dataclass-bypass clone optimization) is
~70x faster than deepcopy. We assert the floor at 10x, leaving 7x
headroom — comfortable for normal complexity additions but tight
enough to catch a regression that swaps the __new__ + __dict__.copy
trick back for the dataclass __init__ (which would drop us to ~18x),
or worse, accidentally calls copy.deepcopy somewhere in the clone
path (which would land us at 1x).

If this test ever fails after a legitimate change that genuinely
costs the clone path performance, lower the floor to whatever the
new baseline supports — but think first about whether the cost is
necessary, since clone is in MCTS's hottest path (thousands of
calls per decision).
"""

from __future__ import annotations

import copy
import random
import time

from mtg_bot.agents import RandomAgent
from mtg_bot.simulate import simulate_game


# Lots of iterations to drive variance down. Total runtime ~1-2s
# even on a slow machine.
_N_CALLS = 500

# Skip the first few calls to ignore one-time cache warming.
_WARMUP = 20

# Required minimum speedup vs copy.deepcopy. Current measured ~70x;
# floor at 10x leaves big headroom for legitimate complexity growth.
_MIN_SPEEDUP_VS_DEEPCOPY = 10.0


def _build_mid_game_state():
    """Same shape ``scripts/bench_clone.py`` uses — a turn-5 state
    with non-trivial battlefield and library. Deterministic seed for
    a stable sample."""
    return simulate_game(
        agents=[
            RandomAgent(name="a0", rng=random.Random(1001)),
            RandomAgent(name="a1", rng=random.Random(2002)),
        ],
        colors=["G", "R"],
        seed=17,
        max_turns=5,
    )


def _time_calls(fn, n: int) -> float:
    start = time.perf_counter()
    for _ in range(n):
        fn()
    return time.perf_counter() - start


def test_clone_is_at_least_10x_faster_than_deepcopy():
    """Ratio guard. Catches catastrophic regressions to the clone
    hot path without flapping under CPU-load variance."""
    state = _build_mid_game_state()

    # Warmup both paths so page-in / cache effects don't bias the
    # first measurement.
    for _ in range(_WARMUP):
        state.clone()
    for _ in range(_WARMUP):
        copy.deepcopy(state)

    t_clone = _time_calls(state.clone, _N_CALLS)
    t_deep = _time_calls(lambda: copy.deepcopy(state), _N_CALLS)

    speedup = t_deep / t_clone if t_clone > 0 else float("inf")
    assert speedup >= _MIN_SPEEDUP_VS_DEEPCOPY, (
        f"clone() vs deepcopy speedup is {speedup:.1f}x, below the "
        f"{_MIN_SPEEDUP_VS_DEEPCOPY}x floor. clone={t_clone*1000:.1f}ms "
        f"deepcopy={t_deep*1000:.1f}ms over {_N_CALLS} calls each. "
        f"Likely regression in GameState.clone — investigate before "
        f"lowering this floor."
    )
