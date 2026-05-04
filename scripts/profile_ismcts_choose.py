"""Profile a single ISMCTS ``choose_with_visits`` call at production budget.

Goal: identify hot spots in ISMCTS that explain the ~93s/game wall
clock seen on master vs PIMC's ~38s/game at the same budget. We've
already measured ``state.clone()`` at ~26us, but that only accounts
for ~20ms per choose; the remaining ~95ms must live elsewhere.
``cProfile`` answers where, without us guessing.

This is a one-off diagnostic — NOT a perf test, NOT for the suite.
Don't import or extend; rerun directly when something changes.

Setup:

- Loads ``trained_weights/v12/weights.pt`` (dual-head, hidden=1024,1024,512).
- Builds a representative mid-game state by running ~30 random
  decisions from ``setup_game`` with synthetic G/R decks (seed 11).
- Constructs ``ISMCTS`` with production budget
  (``Budget(max_nodes=800)``, ``batch_size=32``, ``puct=True``).
- Profiles ONE ``choose_with_visits(adapter, player_id=0)`` call.
- Prints top-30 by cumtime AND top-30 by tottime.
- Computes call counts + total time for the inner-loop functions
  (``state.clone``, ``info_set_key``, ``_fresh_determinization``,
  ``_select_and_expand``, ``_evaluate_leaf``, ``_backprop``,
  ``batch_evaluate_logits``).
- Saves the raw profile to ``profile_results/ismcts_choose_<stamp>.prof``
  for offline ``snakeviz`` / ``pstats`` inspection.

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/profile_ismcts_choose.py
"""

from __future__ import annotations

import argparse
import cProfile
import datetime as dt
import pstats
import random
import sys
import time
from io import StringIO
from pathlib import Path

# Make local source tree importable when run from the repo root
# without `pip install -e .`.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.search import (  # noqa: E402
    Budget, ISMCTS, MtgGameStateAdapter, NNEvaluator,
)
from mtg_bot.search.protocol import CHANCE_PLAYER  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402


def _build_midgame_adapter(seed: int, n_decisions: int) -> MtgGameStateAdapter:
    """Run ``n_decisions`` random decisions from a fresh setup so the
    profile captures a representative mid-game state (units on the
    battlefield, both libraries drawn down a bit, real combat pressure).
    A pre-game-start adapter has trivial branching and would not stress
    the same code paths.

    After hitting ``n_decisions``, also keep stepping through any
    single-legal-action decisions so the *profiled* call lands at a
    branching point — ISMCTS short-circuits on forced moves and we'd
    profile a no-op otherwise.
    """
    state = setup_game(
        [RandomAgent(rng=random.Random(seed + 1)),
         RandomAgent(rng=random.Random(seed + 2))],
        ["G", "R"], seed=seed,
    )
    adapter = MtgGameStateAdapter(state)
    rng = random.Random(seed + 999)
    decisions = 0
    while decisions < n_decisions and not adapter.is_terminal():
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            d = rng.choices(choices, weights=weights, k=1)[0]
        else:
            legal = list(adapter.legal_decisions())
            if not legal:
                break
            d = rng.choice(legal)
        adapter.apply(d)
        decisions += 1

    # Skip past any forced moves so the profiled call has real
    # branching — ISMCTS returns ``{d: 1}`` immediately when only one
    # action is legal, which would profile nothing.
    extra = 0
    while not adapter.is_terminal():
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            adapter.apply(rng.choices(choices, weights=weights, k=1)[0])
            extra += 1
            continue
        legal = list(adapter.legal_decisions())
        if len(legal) > 1:
            break
        if not legal:
            break
        adapter.apply(legal[0])
        extra += 1
        if extra > 200:  # safety
            break
    return adapter


def _format_call_stats(
    stats: pstats.Stats, label: str, name_substring: str,
) -> str:
    """Pull total cumtime + ncalls for any function whose qualified name
    contains ``name_substring`` from a ``pstats.Stats`` object. Cheap
    way to bucket cost by category without parsing ``print_stats``
    output."""
    rows: list[tuple[str, int, float, float]] = []
    for func, (cc, nc, tt, ct, _) in stats.stats.items():
        filename, _, funcname = func
        full = f"{filename}:{funcname}"
        if name_substring in full or name_substring == funcname:
            rows.append((full, nc, tt, ct))
    if not rows:
        return f"  {label}: <no matches for {name_substring!r}>\n"
    total_calls = sum(r[1] for r in rows)
    total_tt = sum(r[2] for r in rows)
    total_ct = sum(r[3] for r in rows)
    return (
        f"  {label}: calls={total_calls:>8d}  "
        f"tottime={total_tt*1000:>9.1f}ms  "
        f"cumtime={total_ct*1000:>9.1f}ms\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--n-prelude", type=int, default=30,
                        help="Random decisions before profiling (mid-game).")
    parser.add_argument("--max-nodes", type=int, default=800,
                        help="Budget.max_nodes — production is 800.")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--weights", type=str,
        default="trained_weights/v12/weights.pt",
    )
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument(
        "--outdir", type=str, default="profile_results",
    )
    args = parser.parse_args()

    weights_path = Path(args.weights).resolve()
    if not weights_path.is_file():
        print(f"ERROR: weights file not found at {weights_path}",
              file=sys.stderr)
        sys.exit(2)

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    prof_path = outdir / f"ismcts_choose_{stamp}.prof"

    print(f"# ISMCTS profile  stamp={stamp}")
    print(f"# weights={weights_path}")
    print(f"# seed={args.seed}  n_prelude={args.n_prelude}  "
          f"max_nodes={args.max_nodes}  batch_size={args.batch_size}")

    print("\n# building mid-game adapter ...")
    t0 = time.perf_counter()
    adapter = _build_midgame_adapter(args.seed, args.n_prelude)
    t_build = time.perf_counter() - t0
    print(f"# built in {t_build*1000:.0f}ms  "
          f"turn={adapter.engine_state.turn_number}  "
          f"step={adapter.engine_state.step.name}  "
          f"active={adapter.active_player()}  "
          f"legal_actions={len(list(adapter.legal_decisions()))}")

    print("\n# loading NN weights (1024,1024,512 dual-head) ...")
    t0 = time.perf_counter()
    evaluator = NNEvaluator(
        weights_path=weights_path,
        with_policy=True,
        hidden_sizes=(1024, 1024, 512),
    )
    t_load = time.perf_counter() - t0
    print(f"# loaded in {t_load*1000:.0f}ms")

    ismcts = ISMCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=args.max_nodes),
        rng=random.Random(args.seed + 7),
        c_puct=1.0,
        batch_size=args.batch_size,
        puct=True,
    )

    # Warm the network: first forward pass eats Python/torch initialization
    # that we don't want polluting the profile.
    print("\n# warming NN evaluator ...")
    t0 = time.perf_counter()
    evaluator.evaluate_logits(adapter, 0)
    t_warm = time.perf_counter() - t0
    print(f"# warm forward took {t_warm*1000:.0f}ms")

    print(f"\n# profiling ISMCTS.choose_with_visits "
          f"(player_id=0, max_nodes={args.max_nodes}) ...")
    profiler = cProfile.Profile()
    t0 = time.perf_counter()
    profiler.enable()
    visits = ismcts.choose_with_visits(adapter, 0)
    profiler.disable()
    elapsed = time.perf_counter() - t0
    print(f"# choose_with_visits returned in {elapsed:.3f}s "
          f"({len(visits)} root children)")
    print(f"# per-iter wall = {elapsed * 1000 / args.max_nodes:.3f}ms")

    profiler.dump_stats(str(prof_path))
    print(f"# raw profile saved to {prof_path}")

    print("\n" + "=" * 78)
    print(f"# Top {args.top} by cumtime")
    print("=" * 78)
    cum_io = StringIO()
    cum_stats = pstats.Stats(profiler, stream=cum_io)
    cum_stats.sort_stats("cumulative").print_stats(args.top)
    print(cum_io.getvalue())

    print("\n" + "=" * 78)
    print(f"# Top {args.top} by tottime")
    print("=" * 78)
    tot_io = StringIO()
    tot_stats = pstats.Stats(profiler, stream=tot_io)
    tot_stats.sort_stats("tottime").print_stats(args.top)
    print(tot_io.getvalue())

    # Per-function category roll-up. Use a fresh Stats object so we
    # don't disturb the printed ordering.
    print("\n" + "=" * 78)
    print("# Category roll-up (from cProfile stats; ms = milliseconds)")
    print("=" * 78)
    rollup_stats = pstats.Stats(profiler)
    categories = [
        ("state.clone (engine GameState)",
         "mtg_bot/game.py:clone"),
        ("state.clone (adapter)",
         "engine_adapter.py:clone"),
        ("info_set_key",
         "info_set.py:info_set_key"),
        ("_fresh_determinization",
         "ismcts.py:_fresh_determinization"),
        ("_select_and_expand",
         "ismcts.py:_select_and_expand"),
        ("_evaluate_leaf",
         "ismcts.py:_evaluate_leaf"),
        ("_backprop",
         "ismcts.py:_backprop"),
        ("_grow_union_mask",
         "ismcts.py:_grow_union_mask"),
        ("_stamp_prior",
         "ismcts.py:_stamp_prior"),
        ("_apply_virtual_loss",
         "ismcts.py:_apply_virtual_loss"),
        ("_revert_virtual_loss",
         "ismcts.py:_revert_virtual_loss"),
        ("determinize (root determinizer)",
         "determinize.py:determinize"),
        ("legal_action_mask",
         "action_encoding.py:legal_action_mask"),
        ("legal_decisions (adapter)",
         "engine_adapter.py:legal_decisions"),
        ("apply (adapter)",
         "engine_adapter.py:apply"),
        ("evaluate_logits (NN)",
         "nn_evaluator.py:evaluate_logits"),
        ("batch_evaluate_logits (NN)",
         "nn_evaluator.py:batch_evaluate_logits"),
        ("extract_features",
         "features.py:extract_features"),
        ("torch forward (Module __call__)",
         "torch/nn/modules/module.py:_call_impl"),
        ("_puct_score",
         "ismcts.py:_puct_score"),
        ("_apply_policy_mask",
         "ismcts.py:_apply_policy_mask"),
        ("encode (action_encoding)",
         "action_encoding.py:encode"),
    ]
    for label, needle in categories:
        # Format to a buffer, then print so we keep both ordering and
        # alignment.
        sys.stdout.write(_format_call_stats(rollup_stats, label, needle))

    # Bonus: total wall split for the headline.
    print()
    print(f"# total elapsed = {elapsed*1000:.1f}ms")
    print(f"# per iter = {elapsed*1000/args.max_nodes:.3f}ms "
          f"(over {args.max_nodes} budget nodes)")
    print(f"# tree size  = {len(visits)} root children")
    visit_total = sum(visits.values())
    print(f"# total root visits = {visit_total}")
    print(f"# raw profile  : {prof_path}")


if __name__ == "__main__":
    main()
