"""Per-game profiler for ISMCTS-uniform self-play at production budget.

Goal: identify where per-game wall time goes in NN-ISMCTS self-play
(samples=4, inner_nodes=200, total_iters=800, with_policy + puct), at
the granularity that explains real-world throughput rather than just
per-choose() cost.

Background (from the perf-analysis-deep handoff):

- Per-choose profile diagnosed and fixed the unbatched policy-prior
  forwards (commit ``de9a92e``: 13.8x speedup on a single mid-game
  state). Per-call wall is now ~5s on the profiled hot state.
- Tree reuse landed (``5f1a202``): inherited visits across choose()
  calls, ~1.2-1.4x effective budget multiplier.
- But end-to-end iter_001 is still ~6-8x slower per worker than the
  prior PIMC self-play loop: ~6-8 games/hour/worker vs ~60.

Hypotheses worth measuring per-game (not per-choose):

1. Per-game NNEvaluator construction (factories build it twice per
   game inside ``_generate_one_game_data`` — once for each seat).
   ``torch.load`` + ``model.load_state_dict`` on a 1024/1024/512 dual-
   head trunk could be seconds per game.
2. Replay capture overhead: ``ReplayRecorder.record`` per priority
   moment (and per chance moment) plus annotators.
3. ``adapter.apply`` / engine work per decision (independent of
   search budget).
4. NN forward time aggregate per game (vs construction).
5. Determinize / clone / info-set-key cost dominated at game scale.

What this script does:

- Pins torch to 1 CPU thread upfront (matches production worker
  pin) so the profile reflects what production workers experience.
- Times the NNEvaluator construction TWICE explicitly (first build
  pays torch import + state_dict load + model construction; second
  build pays only state_dict load + model — that's what a worker's
  *second-and-onward* game costs).
- Phase 1: runs ``--n-games-clean`` self-play games sequentially
  with NO cProfile instrumentation. Reports per-game wall (min /
  median / max / mean) + average samples/game so we can compare
  to production iter shard JSONs.
- Phase 2: runs ONE more game with cProfile enabled. cProfile
  adds ~2-3x slowdown so a single game is enough for the deep
  call-tree breakdown; running it on every game would dominate
  wall clock and not change the breakdown.
- Reports top-N by cumtime, top-N by tottime, and a category
  roll-up (search-side / determinize / engine / NN / replay /
  features) computed from the cProfile data.
- Saves the raw cProfile dump for offline inspection
  (``snakeviz`` / ``pstats``).

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/profile_self_play_game.py --n-games-clean 3

Sequential, single-process. Production-budget settings (``samples=4
inner_nodes=200``, ``with_policy=True``, ``puct=True``, dual-head
1024/1024/512 v12 weights).
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
from typing import Any, Optional

# Make local source tree importable when run from the repo root
# without `pip install -e .`. (Mirrors the pattern in
# scripts/profile_ismcts_choose.py.)
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.decks import decks_from_json  # noqa: E402
from mtg_bot.training import NNPimcConfig, Registry  # noqa: E402
from mtg_bot.training.data_gen import (  # noqa: E402
    _generate_one_game_data,
)


def _format_call_stats(
    stats: pstats.Stats, label: str, name_substring: str,
) -> str:
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
        f"  {label}: calls={total_calls:>10d}  "
        f"tottime={total_tt*1000:>10.1f}ms  "
        f"cumtime={total_ct*1000:>10.1f}ms\n"
    )


def _measure_evaluator_init(weights_path: str, hidden_sizes) -> tuple[float, float]:
    """Build NNEvaluator twice; return (first_build_sec, second_build_sec).

    First build pays ``import torch`` cost AND state_dict load AND
    model construction. Second build pays only the state_dict load
    AND model construction (torch already imported). Reflects the
    real-world cost a worker pays on its second-and-onward game once
    torch is hot in the worker process.
    """
    from mtg_bot.search.nn_evaluator import NNEvaluator

    t0 = time.perf_counter()
    NNEvaluator(
        weights_path=Path(weights_path),
        with_policy=True,
        hidden_sizes=hidden_sizes,
    )
    first = time.perf_counter() - t0

    t0 = time.perf_counter()
    NNEvaluator(
        weights_path=Path(weights_path),
        with_policy=True,
        hidden_sizes=hidden_sizes,
    )
    second = time.perf_counter() - t0
    return first, second


def _pin_torch_threads_now() -> None:
    """Force torch CPU thread count to 1 in this process. data_gen's
    per-game ``pin_worker_torch_threads`` only runs inside
    ``_generate_one_game_data`` after torch has been imported via the
    NN evaluator factory; if we don't pin upfront, the NN
    construction calls earlier in this script run with the platform
    default (host CPU count) which is wrong on a 16+ core box and
    creates a thundering herd of threads during the cProfile-amplified
    forward passes."""
    import torch
    torch.set_num_threads(1)


def _run_one_game(
    *,
    game_idx: int,
    base_seed: int,
    weights_path: str,
    hidden_sizes,
    deck_pool,
    decision_cap: int,
) -> tuple[int, float, int, Optional[int]]:
    """Play a single ISMCTS self-play game with v12 weights. Returns
    ``(game_idx, wall_sec, n_samples, winner)``."""
    cfg = NNPimcConfig(
        weights_path=weights_path,
        samples=4,
        inner_nodes=200,
        batch_size=32,
        with_policy=True,
        puct=True,
        hidden_sizes=hidden_sizes,
        use_ismcts=True,  # ISMCTS, not PIMC — match prod self-play.
    )
    start = time.perf_counter()
    chunk = _generate_one_game_data(
        game_idx=game_idx,
        p0_factory=cfg.build,
        p1_factory=cfg.build,
        base_seed=base_seed,
        decision_cap=decision_cap,
        sample_every=1,
        deck_pool=deck_pool,
        per_game_timeout_sec=None,
    )
    wall = time.perf_counter() - start
    return game_idx, wall, int(chunk[0].shape[0]), chunk[4]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-games-clean", type=int, default=3,
                        help="Profile-free games for per-game wall stats.")
    parser.add_argument("--base-seed", type=int, default=42_000_000)
    # NOTE: production decision_cap is 4000 but most games end well
    # under 500. The cap is tightened here so a long-tail game (the
    # "the game has ended every priority moment for 1500+ decisions
    # but the engine never picks the kill" pathology that landed
    # iter_001 with multi-thousand-decision games at multi-minute
    # cProfile-amplified wall time) won't dominate the wall clock for
    # this diagnostic. The profile then reflects representative-game
    # cost rather than long-tail game cost. The long-tail itself is
    # a separate diagnostic problem.
    parser.add_argument("--decision-cap", type=int, default=800)
    parser.add_argument("--bootstrap-version", default="v12")
    parser.add_argument(
        "--registry-root", type=Path, default=Path("trained_weights"),
    )
    parser.add_argument(
        "--deck-pool", type=Path,
        default=Path("data/17lands/eoe_decks.json.gz"),
    )
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument(
        "--outdir", type=str, default="profile_results",
    )
    args = parser.parse_args()

    registry = Registry(args.registry_root)
    weights_path = str(registry.weights_path(args.bootstrap_version))
    meta = registry.load_metadata(args.bootstrap_version)
    hidden_sizes = (
        tuple(meta.hidden_sizes)
        if getattr(meta, "hidden_sizes", None) else None
    )

    print(
        f"# Per-game self-play profiler  version={args.bootstrap_version} "
        f"hidden_sizes={hidden_sizes}  "
        f"n_games_clean={args.n_games_clean} (+1 cProfile-instrumented)"
    )
    print(f"# weights={weights_path}")

    print("\n# loading deck pool ...")
    t0 = time.perf_counter()
    deck_pool = decks_from_json(Path(args.deck_pool))
    t_decks = time.perf_counter() - t0
    print(f"# loaded {len(deck_pool)} decks in {t_decks*1000:.0f}ms")

    print("\n# pinning torch threads to 1 (matches production worker pin) ...")
    _pin_torch_threads_now()

    print("\n# measuring NNEvaluator construction cost ...")
    t_first, t_second = _measure_evaluator_init(weights_path, hidden_sizes)
    print(
        f"# first build : {t_first*1000:.0f}ms (includes torch import)\n"
        f"# second build: {t_second*1000:.0f}ms (state_dict load + model)\n"
        f"# data_gen builds the evaluator TWICE per game "
        f"(p0_factory + p1_factory), so per-game evaluator init is "
        f"approximately ``2 * second_build`` after torch is hot in "
        f"the worker."
    )

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    prof_path = outdir / f"self_play_game_{stamp}.prof"

    print(f"\n# config: samples=4, inner_nodes=200, with_policy + "
          f"puct, ISMCTS  decision_cap={args.decision_cap}")

    # Phase 1: profile-free per-game wall measurement. cProfile adds
    # ~2-3x overhead to every Python call which dominates wall time
    # at our function-call rate; running the first ``--n-games-clean``
    # games WITHOUT cProfile gives clean wall numbers we can compare
    # to production.
    print(f"\n# Phase 1: {args.n_games_clean} clean (no-profiler) games "
          f"for per-game wall measurement ...")
    per_game: list[tuple[int, float, int, Optional[int]]] = []
    for i in range(args.n_games_clean):
        game_idx, wall, n_samples, winner = _run_one_game(
            game_idx=i, base_seed=args.base_seed,
            weights_path=weights_path, hidden_sizes=hidden_sizes,
            deck_pool=deck_pool, decision_cap=args.decision_cap,
        )
        per_game.append((game_idx, wall, n_samples, winner))
        print(
            f"#   game {game_idx}: {wall:>6.1f}s wall  "
            f"{n_samples:>4d} samples  winner={winner}",
            flush=True,
        )

    # Phase 2: profile a single game with cProfile. Pick a different
    # seed slot to avoid re-playing one we've already timed (results
    # are deterministic per game_idx + base_seed).
    profiler = cProfile.Profile()
    profile_idx = args.n_games_clean  # Next slot in seed space.
    print(
        f"\n# Phase 2: cProfile-instrumented game {profile_idx} "
        f"(expect ~2-4x slowdown from cProfile overhead) ..."
    )
    profiler.enable()
    profile_game_idx, profile_wall, profile_samples, profile_winner = (
        _run_one_game(
            game_idx=profile_idx, base_seed=args.base_seed,
            weights_path=weights_path, hidden_sizes=hidden_sizes,
            deck_pool=deck_pool, decision_cap=args.decision_cap,
        )
    )
    profiler.disable()
    print(
        f"#   game {profile_game_idx}: {profile_wall:>6.1f}s wall "
        f"(cProfile-instrumented)  {profile_samples} samples  "
        f"winner={profile_winner}",
        flush=True,
    )

    profiler.dump_stats(str(prof_path))
    print(f"\n# raw profile saved to {prof_path}")

    # Aggregate per-game wall stats.
    walls = sorted(g[1] for g in per_game)
    n = len(walls)

    def pct(p: float) -> float:
        idx = max(0, min(n - 1, int(round(n * p / 100)) - 1))
        return walls[idx]

    n_samples_total = sum(g[2] for g in per_game)
    print("\n" + "=" * 78)
    print(f"# Per-game wall (n={n})")
    print("=" * 78)
    print(f"#   min  = {walls[0]:.1f}s")
    print(f"#   p25  = {pct(25):.1f}s")
    print(f"#   p50  = {pct(50):.1f}s")
    print(f"#   p75  = {pct(75):.1f}s")
    print(f"#   p90  = {pct(90):.1f}s")
    print(f"#   max  = {walls[-1]:.1f}s")
    print(f"#   mean = {sum(walls)/n:.1f}s")
    print(f"#   total = {sum(walls):.1f}s "
          f"(across all {n} games, sequential)")
    print(f"#   total samples = {n_samples_total}  "
          f"(decisions captured, both viewers)")
    avg_decisions = n_samples_total / max(1, n) / 2  # data-doubled
    print(f"#   avg decisions/game ~ {avg_decisions:.0f}")
    games_per_hour = 3600.0 / max(1e-9, sum(walls) / n)
    print(f"#   games/hour/worker ~ {games_per_hour:.1f} "
          f"(single-process, single-thread, no overhead)")
    print(
        f"#\n# Profile-instrumented game {profile_game_idx} took "
        f"{profile_wall:.1f}s wall ({profile_wall / max(1.0, walls[len(walls)//2]):.1f}x "
        f"vs clean median); cProfile overhead alone."
    )

    # Top-N by cumtime + tottime — same shape as the per-choose script
    # so the writeup can compare apples-to-apples.
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

    print("\n" + "=" * 78)
    print("# Category roll-up (aggregate across all games; ms = milliseconds)")
    print("=" * 78)
    rollup_stats = pstats.Stats(profiler)
    categories = [
        # ---- search-side ----
        ("ISMCTS.choose_with_visits",
         "ismcts.py:choose_with_visits"),
        ("ISMCTS._select_and_expand",
         "ismcts.py:_select_and_expand"),
        ("ISMCTS._evaluate_leaf",
         "ismcts.py:_evaluate_leaf"),
        ("ISMCTS._backprop",
         "ismcts.py:_backprop"),
        ("ISMCTS._fresh_determinization",
         "ismcts.py:_fresh_determinization"),
        ("ISMCTS._stamp_prior",
         "ismcts.py:_stamp_prior"),
        ("ISMCTS._grow_union_mask",
         "ismcts.py:_grow_union_mask"),
        # ---- determinize / clone / info_set ----
        ("determinize (root determinizer)",
         "determinize.py:determinize"),
        ("info_set_key",
         "info_set.py:info_set_key"),
        ("clone (engine GameState)",
         "game.py:clone"),
        ("clone (adapter)",
         "engine_adapter.py:clone"),
        # ---- engine work ----
        ("apply (adapter)",
         "engine_adapter.py:apply"),
        ("legal_decisions (adapter)",
         "engine_adapter.py:legal_decisions"),
        ("legal_actions (engine)",
         "legal.py:legal_actions"),
        # ---- NN ----
        ("NNEvaluator.__init__",
         "nn_evaluator.py:__init__"),
        ("NNEvaluator.evaluate_logits",
         "nn_evaluator.py:evaluate_logits"),
        ("NNEvaluator.batch_evaluate_logits",
         "nn_evaluator.py:batch_evaluate_logits"),
        ("NNEvaluator.batch_evaluate",
         "nn_evaluator.py:batch_evaluate"),
        ("NNEvaluator.batch_evaluate_with_policy",
         "nn_evaluator.py:batch_evaluate_with_policy"),
        ("torch.load",
         "torch/serialization.py:load"),
        ("torch forward (Module __call__)",
         "torch/nn/modules/module.py:_call_impl"),
        ("extract_features",
         "features.py:extract_features"),
        # ---- features / encoding / replay ----
        ("legal_action_mask",
         "action_encoding.py:legal_action_mask"),
        ("encode (action_encoding)",
         "action_encoding.py:encode"),
        ("ReplayRecorder.record",
         "replay_capture.py:record"),
        ("serialize_state",
         "serialize.py:serialize_state"),
        # ---- top-level ----
        ("_play_one_game_recording",
         "data_gen.py:_play_one_game_recording"),
        ("_generate_one_game_data",
         "data_gen.py:_generate_one_game_data"),
        ("setup_game",
         "simulate.py:setup_game"),
    ]
    for label, needle in categories:
        sys.stdout.write(_format_call_stats(rollup_stats, label, needle))

    print(f"\n# raw profile  : {prof_path}")
    print(f"# stamp        : {stamp}")


if __name__ == "__main__":
    main()
