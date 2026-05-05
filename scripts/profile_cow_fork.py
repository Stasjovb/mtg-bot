"""Micro-benchmark for ``_CowList._fork_if_shared``.

Measures three operating modes:

1. Already-owned fast path: ``_fork_if_shared`` returns immediately
   on the first ``if self._owned: return``. The mutator-prologue
   cost when no fork is needed.
2. Fresh-share fork (the expensive path): two-clone pair, source
   forks once. This is the per-iteration ISMCTS cost.
3. Mutator dispatch overhead: ``append`` + ``pop`` on an owned
   list, to bound how much of a "fast path" call cost is the
   Python attribute lookup + C-level mutator dispatch vs the
   share-check itself.

The goal is to attribute the 0.5ms/call average from the per-game
profile (66s tottime / 127k calls) to one of:

- (A) per-element ``_clone_each`` cost on the fork branch.
- (B) the fast-path overhead when _owned is True (Python stack
  frame + attribute lookups + return).
- (C) the bookkeeping (peer rebinding, share-group filter, attr
  resets) on the fork branch.

If most calls hit the owned branch (which the per-game numbers
suggest — 21,600 ISMCTS iters but 127k _fork_if_shared calls means
~5.9 calls per iter and only 2 of those will fork the first time),
then the per-call cost is dominated by (B) — and the optimization
target is making the owned path absurdly cheap.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.game import _CowList  # noqa: E402


def _make_owned_list(n: int) -> _CowList:
    return _CowList(range(n))


def _make_shared_pair(n: int):
    src = _CowList(range(n))
    clone = _CowList(range(n))
    src._owned = False
    src._clone_each = lambda x: x  # cheap identity clone
    clone._owned = False
    clone._clone_each = lambda x: x
    group = [src, clone]
    src._share_group = group
    clone._share_group = group
    return src, clone


def bench_owned_fast_path(n_calls: int = 1_000_000) -> float:
    """Time the owned-list ``_fork_if_shared`` no-op path."""
    cow = _make_owned_list(40)
    f = cow._fork_if_shared  # bound method lookup pulled out of loop
    t0 = time.perf_counter()
    for _ in range(n_calls):
        f()
    return time.perf_counter() - t0


def bench_owned_append_pop(n_calls: int = 1_000_000) -> float:
    """Time ``append + pop`` on an owned list. Each pair fires
    ``_fork_if_shared`` twice on the owned-fast-path."""
    cow = _make_owned_list(40)
    t0 = time.perf_counter()
    for _ in range(n_calls):
        cow.append(0)
        cow.pop()
    return time.perf_counter() - t0


def bench_fresh_fork(n_calls: int = 10_000, list_size: int = 40) -> float:
    """Time fresh-pair shared fork. Each iteration builds a new
    pair and forks the source once."""
    t0 = time.perf_counter()
    for _ in range(n_calls):
        src, clone = _make_shared_pair(list_size)
        src._fork_if_shared()  # fork direction: src keeps originals.
    return time.perf_counter() - t0


def bench_owned_via_class_method(n_calls: int = 1_000_000) -> float:
    """Same as bench_owned_fast_path but call via class dispatch
    (fresh attr lookup each call) — closer to how mutators see it."""
    cow = _make_owned_list(40)
    t0 = time.perf_counter()
    for _ in range(n_calls):
        cow._fork_if_shared()
    return time.perf_counter() - t0


def bench_realistic_fork(n_calls: int = 5_000) -> tuple[float, int]:
    """Time fresh-pair shared fork using actual GameObjects from a
    real mid-game state (40-card library of slots-dataclass GameObjects).
    The clone_each callback is the production ``_clone_game_object``."""
    import random as _random

    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import _clone_game_object
    from mtg_bot.simulate import simulate_game

    state = simulate_game(
        agents=[RandomAgent(name="a0", rng=_random.Random(101)),
                RandomAgent(name="a1", rng=_random.Random(202))],
        colors=["G", "R"], seed=17, max_turns=5,
    )
    library = list(state.players[0].library)
    print(f"  ... realistic fork benchmark uses {len(library)}-card library")

    elapsed_total = 0.0
    for _ in range(n_calls):
        src = _CowList(library)
        clone = _CowList(library)
        src._owned = False
        src._clone_each = _clone_game_object
        clone._owned = False
        clone._clone_each = _clone_game_object
        group = [src, clone]
        src._share_group = group
        clone._share_group = group
        t0 = time.perf_counter()
        src._fork_if_shared()
        elapsed_total += time.perf_counter() - t0
    return elapsed_total, len(library)


def main() -> None:
    print("# _CowList._fork_if_shared micro-bench\n")

    print("# warm-up...")
    bench_owned_fast_path(50_000)
    bench_fresh_fork(500)

    n_owned = 5_000_000
    elapsed = bench_owned_fast_path(n_owned)
    per_call_us = elapsed / n_owned * 1e6
    print(
        f"  bench_owned_fast_path    : {n_owned:>9d} calls  "
        f"{elapsed*1000:>7.1f}ms  per-call={per_call_us:.3f}us  "
        f"(bound method, hot loop)"
    )

    n_owned = 5_000_000
    elapsed = bench_owned_via_class_method(n_owned)
    per_call_us = elapsed / n_owned * 1e6
    print(
        f"  bench_owned_via_class    : {n_owned:>9d} calls  "
        f"{elapsed*1000:>7.1f}ms  per-call={per_call_us:.3f}us  "
        f"(per-call attr lookup)"
    )

    n_pairs = 1_000_000
    elapsed = bench_owned_append_pop(n_pairs)
    per_pair_us = elapsed / n_pairs * 1e6
    print(
        f"  bench_owned_append_pop   : {n_pairs:>9d} pairs  "
        f"{elapsed*1000:>7.1f}ms  per-pair={per_pair_us:.3f}us  "
        f"(2 forks/pair via mutators)"
    )

    n_forks = 50_000
    elapsed = bench_fresh_fork(n_forks, list_size=40)
    per_call_us = elapsed / n_forks * 1e6
    print(
        f"  bench_fresh_fork (size=40): {n_forks:>9d} calls  "
        f"{elapsed*1000:>7.1f}ms  per-call={per_call_us:.3f}us  "
        f"(actual fork; 40 elements)"
    )

    n_forks = 50_000
    elapsed = bench_fresh_fork(n_forks, list_size=0)
    per_call_us = elapsed / n_forks * 1e6
    print(
        f"  bench_fresh_fork (size=0): {n_forks:>9d} calls  "
        f"{elapsed*1000:>7.1f}ms  per-call={per_call_us:.3f}us  "
        f"(empty list; bookkeeping cost only)"
    )

    elapsed, lib_size = bench_realistic_fork(2000)
    per_call_us = elapsed / 2000 * 1e6
    print(
        f"  bench_realistic_fork     : {2000:>9d} calls  "
        f"{elapsed*1000:>7.1f}ms  per-call={per_call_us:.3f}us  "
        f"(production GameObject clone_each, lib={lib_size})"
    )

    print(
        "\nInterpretation:\n"
        "- bench_owned_fast_path is the 'no fork needed' cost.\n"
        "- bench_fresh_fork - bench_fresh_fork(size=0) ~ per-element\n"
        "  clone cost.\n"
        "- The per-game profile reports avg ~0.5ms per call.\n"
        "  If owned_fast_path is below 0.05us/call, the bulk of the\n"
        "  per-game tottime is in fork bookkeeping or per-element clone,\n"
        "  not the share-check overhead.\n"
    )


if __name__ == "__main__":
    main()
