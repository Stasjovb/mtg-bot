"""Capture per-game decision-count distribution for self-play games.

Diagnostic for the iter_001 long-tail problem: production self-play
under v12 ISMCTS-uniform reports 6.6 games/hour/worker (master, 8
workers). At a clean ~62s median per game (per the perf profile in
``docs/perf_self_play_20260504.md``), workers should be hitting ~58
games/hour, not 6.6. The gap is the long tail — games that hit the
4000-decision cap take 5+ minutes wall and drag the per-worker
average down. Without per-game decision-count visibility we can't
say what fraction of games hit the cap, what their decision-count
distribution looks like, or what a sane lower cap would cover.

What this script does:

- Runs N self-play games in a multiprocessing pool (default: 50
  games, 8 workers, single shard) with v12 weights, samples=4,
  inner_nodes=200, ISMCTS-uniform.
- Uses a HIGH decision cap (default 8000) and HIGH timeout (default
  1200s) so we see the full natural distribution rather than
  truncating at the production cap.
- Captures per-game: wall time, decisions completed, sampled-row
  count, winner, and the LAST K decision reprs for any game that
  exceeds a "long-tail" threshold (default 2000 decisions).
- Writes a JSON report with the distribution histogram and the
  long-tail-game decision tails for offline analysis.

Run from the worktree root::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/capture_game_length_distribution.py \\
            --n-games 50 --n-workers 8 \\
            --decision-cap 8000 --timeout-sec 1200 \\
            --tail-threshold 2000 --tail-keep-last 100 \\
            --out long_tail_distribution.json

Sequential mode (``--n-workers 1`` no pool) is supported for
debugging; production capture uses the pool path.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.decks import decks_from_json  # noqa: E402
from mtg_bot.search.engine_adapter import MtgGameStateAdapter  # noqa: E402
from mtg_bot.search.protocol import CHANCE_PLAYER  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402
from mtg_bot.training import NNPimcConfig, Registry  # noqa: E402
from mtg_bot.training._worker_threads import (  # noqa: E402
    pin_worker_torch_threads,
)
from mtg_bot.training.data_gen import _sample_decks_for_game  # noqa: E402


def _classify_decision(decision: object) -> str:
    """Coarse bucket for a Decision repr — used to summarize the tail
    pattern. Mirrors the names in ``mtg_bot.actions`` plus the search-
    side combat decisions and resolution-pause decisions."""
    name = type(decision).__name__
    return name


# Worker-global state — populated either by ``_pool_initializer``
# (sequential path) or by the first task's ``_worker`` call (parallel
# path; see comment there). Avoids re-shipping the deck pool /
# weights metadata on every task pickle.
#
# Why first-task-bootstrap rather than a Pool ``initializer=``: on
# Windows ``mp.Pool(initializer=..., initargs=(deck_pool, ...))``
# was observed to deadlock with the 5000-deck pool here — workers
# spawn, then sit at idle CPU=0 forever, never running their
# initializer. Passing the bulky state inside the FIRST task's args
# (which the parent then dispatches via the same queue used for
# regular tasks) sidesteps that — and on subsequent tasks the
# worker reads the global it just stashed instead of re-pickling.
_WORKER_DECK_POOL: Optional[list] = None
_WORKER_WEIGHTS_PATH: Optional[str] = None
_WORKER_HIDDEN_SIZES: Optional[tuple[int, ...]] = None


def _pool_initializer(
    deck_pool: list,
    weights_path: str,
    hidden_sizes: Optional[tuple[int, ...]],
) -> None:
    """Sequential-path bootstrap. Stashes the deck pool + weights
    path + hidden sizes as worker-globals so per-task ``_worker``
    calls can read from globals instead of re-pickling. The parallel
    path uses first-task-bootstrap inside ``_worker`` instead.
    """
    global _WORKER_DECK_POOL, _WORKER_WEIGHTS_PATH, _WORKER_HIDDEN_SIZES
    _WORKER_DECK_POOL = deck_pool
    _WORKER_WEIGHTS_PATH = weights_path
    _WORKER_HIDDEN_SIZES = hidden_sizes


def _play_one_game_instrumented(
    *,
    game_idx: int,
    base_seed: int,
    weights_path: str,
    hidden_sizes: Optional[tuple[int, ...]],
    deck_pool: list,
    decision_cap: int,
    enable_mulligans: bool,
    tail_keep_last: int,
) -> dict[str, Any]:
    """Play one self-play game and return a result dict with rich
    per-decision instrumentation. Self-contained — does not call into
    ``data_gen._play_one_game_recording`` because we need to capture
    every decision's class+repr inline. Single-process; the parent
    pool calls this via ``_play_one_parallel_game``.

    The dict contains:

    - ``game_idx``, ``engine_seed``
    - ``wall_sec`` (float)
    - ``decisions_completed`` (int)
    - ``cap_hit`` (bool) — True if the loop bailed at decision_cap
    - ``winner`` (Optional[int])
    - ``is_draw`` (bool) — engine drew (rare; mutual loss)
    - ``decision_class_counts`` (dict[str, int]) — total counts by
      decision class across the WHOLE game.
    - ``last_decision_classes`` (dict[str, int]) — class counts among
      the LAST ``tail_keep_last`` decisions only. Lets us see whether
      the tail is dominated by PassPriority / Combat / etc.
    - ``last_decision_reprs`` (list[str]) — verbatim reprs of the
      last K decisions (truncated to 200 chars each).
    - ``final_p0_life``, ``final_p1_life`` (int) — life totals at
      end-of-game (helps tell whether either player is on the brink).
    - ``final_battlefield_size`` (int) — total non-token+token
      objects on the battlefield at end-of-game.
    - ``final_p0_lib_size``, ``final_p1_lib_size`` (int)
    - ``final_p0_hand_size``, ``final_p1_hand_size`` (int)
    - ``final_step``, ``final_turn`` (str, int)
    - ``error`` (Optional[str]) — set on engine exception.
    """
    cfg = NNPimcConfig(
        weights_path=weights_path,
        samples=4,
        inner_nodes=200,
        batch_size=32,
        with_policy=True,
        puct=True,
        hidden_sizes=hidden_sizes,
        use_ismcts=True,
    )
    pin_worker_torch_threads()
    engine_seed = base_seed + game_idx
    deck_p0, deck_p1 = _sample_decks_for_game(deck_pool, game_idx, base_seed)
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(engine_seed + 1)),
            RandomAgent(rng=random.Random(engine_seed + 2)),
        ],
        decks=[deck_p0.cards, deck_p1.cards],
        seed=engine_seed,
        enable_mulligans=enable_mulligans,
    )
    if game_idx % 2 == 1:
        engine.active_player_idx = 1
        engine.priority_player_idx = 1
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    strategies = {
        0: cfg.build(base_seed + 100 * game_idx),
        1: cfg.build(base_seed + 100 * game_idx + 50),
    }
    rng = random.Random(base_seed + 100 * game_idx + 99)

    decision_class_counts: dict[str, int] = {}
    last_reprs: list[str] = []
    last_classes: list[str] = []
    error: Optional[str] = None
    cap_hit = False

    started = time.perf_counter()
    decision_idx = 0
    try:
        while not adapter.is_terminal() and decision_idx < decision_cap:
            active = adapter.active_player()
            if active == CHANCE_PLAYER:
                outcomes = adapter.chance_outcomes()
                choices = [d for d, _ in outcomes]
                weights = [w for _, w in outcomes]
                decision = rng.choices(choices, weights=weights, k=1)[0]
            else:
                decision = strategies[active].choose(adapter, active)
            cls = _classify_decision(decision)
            decision_class_counts[cls] = (
                decision_class_counts.get(cls, 0) + 1
            )
            try:
                r = repr(decision)[:200]
            except Exception:
                r = f"<unrepr-able {cls}>"
            last_reprs.append(r)
            last_classes.append(cls)
            if len(last_reprs) > tail_keep_last:
                last_reprs.pop(0)
                last_classes.pop(0)
            adapter.apply(decision)
            decision_idx += 1
        else:
            cap_hit = decision_idx >= decision_cap and not adapter.is_terminal()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - started

    # Final-state snapshot. Done via raw engine state to avoid
    # triggering the adapter's lazy combat-phase resolution.
    state = adapter.engine_state
    p0 = state.players[0]
    p1 = state.players[1]
    last_class_counts: dict[str, int] = {}
    for c in last_classes:
        last_class_counts[c] = last_class_counts.get(c, 0) + 1

    return {
        "game_idx": game_idx,
        "engine_seed": engine_seed,
        "wall_sec": round(wall, 3),
        "decisions_completed": decision_idx,
        "cap_hit": cap_hit,
        "winner": (
            adapter.winner() if adapter.is_terminal() else None
        ),
        "is_draw": getattr(state, "is_draw", False),
        "is_terminal": adapter.is_terminal(),
        "error": error,
        "decision_class_counts": decision_class_counts,
        "last_decision_classes": last_class_counts,
        "last_decision_reprs": last_reprs,
        "final_p0_life": int(p0.life),
        "final_p1_life": int(p1.life),
        "final_p0_has_lost": bool(p0.has_lost),
        "final_p1_has_lost": bool(p1.has_lost),
        "final_p0_lost_reason": getattr(p0, "lost_reason", None),
        "final_p1_lost_reason": getattr(p1, "lost_reason", None),
        "final_battlefield_size": len(state.battlefield),
        "final_p0_lib_size": len(p0.library),
        "final_p1_lib_size": len(p1.library),
        "final_p0_hand_size": len(p0.hand),
        "final_p1_hand_size": len(p1.hand),
        "final_step": str(getattr(state, "step", "?")),
        "final_turn": int(getattr(state, "turn_number", 0)),
    }


def _worker(args: dict) -> dict[str, Any]:
    """Top-level pickleable wrapper. Catches engine exceptions so a
    single bad game doesn't take down the pool — same pattern as
    ``data_gen._play_one_parallel_game``.

    ``args`` carries everything needed per task: game_idx, base_seed,
    decision_cap, enable_mulligans, tail_keep_last, deck_pool,
    weights_path, hidden_sizes. The deck pool / weights path are
    re-shipped on every task pickle (3MB-ish per task) to mirror
    the production ``data_gen.generate_training_data_parallel``
    contract — that one is known to work without a Pool initializer
    on Windows, so we copy it here.
    """
    try:
        return _play_one_game_instrumented(**args)
    except Exception as exc:  # noqa: BLE001
        import traceback
        return {
            "game_idx": args.get("game_idx", -1),
            "engine_seed": args.get("base_seed", 0) + args.get("game_idx", 0),
            "wall_sec": -1.0,
            "decisions_completed": 0,
            "cap_hit": False,
            "winner": None,
            "is_draw": False,
            "is_terminal": False,
            "error": (
                f"WORKER_CRASH: {type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()}"
            ),
            "decision_class_counts": {},
            "last_decision_classes": {},
            "last_decision_reprs": [],
            "final_p0_life": -1, "final_p1_life": -1,
            "final_p0_has_lost": False, "final_p1_has_lost": False,
            "final_p0_lost_reason": None, "final_p1_lost_reason": None,
            "final_battlefield_size": -1,
            "final_p0_lib_size": -1, "final_p1_lib_size": -1,
            "final_p0_hand_size": -1, "final_p1_hand_size": -1,
            "final_step": "?", "final_turn": 0,
        }


def _bucket_label(d: int) -> str:
    if d < 200:
        return "0-200"
    if d < 500:
        return "200-500"
    if d < 1000:
        return "500-1000"
    if d < 2000:
        return "1000-2000"
    if d < 4000:
        return "2000-4000"
    if d < 8000:
        return "4000-8000"
    return "8000+"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-games", type=int, default=50)
    p.add_argument("--n-workers", type=int, default=8)
    p.add_argument("--base-seed", type=int, default=80_000_000)
    p.add_argument("--game-indices", type=str, default=None,
                   help="Comma-separated list of explicit game_idx "
                        "values to run (overrides --n-games). Use to "
                        "target known-slow seeds from prior runs.")
    p.add_argument("--decision-cap", type=int, default=8000)
    p.add_argument("--timeout-sec", type=float, default=1200.0,
                   help="Per-game timeout. Currently informational — "
                        "the loop respects decision_cap, not wall.")
    p.add_argument("--tail-threshold", type=int, default=2000,
                   help="Games >= this decision count get their last-K "
                        "decision reprs preserved in the JSON.")
    p.add_argument("--tail-keep-last", type=int, default=100)
    p.add_argument("--enable-mulligans", action="store_true", default=True)
    p.add_argument("--bootstrap-version", default="v12")
    p.add_argument("--registry-root", type=Path,
                   default=Path("../../mtg-bot/trained_weights"))
    p.add_argument("--deck-pool", type=Path,
                   default=Path("../../mtg-bot/data/17lands/eoe_decks.json.gz"))
    p.add_argument("--out", type=Path,
                   default=Path("long_tail_distribution.json"))
    p.add_argument("--jsonl-out", type=Path, default=None,
                   help="Optional path. If set, append each game's "
                        "result dict as a JSONL line as games complete "
                        "— so partial progress is captured if the run "
                        "is interrupted. Independent of --out's final "
                        "summary JSON.")
    args = p.parse_args()

    registry = Registry(args.registry_root)
    weights_path = str(registry.weights_path(args.bootstrap_version))
    meta = registry.load_metadata(args.bootstrap_version)
    hidden_sizes = (
        tuple(meta.hidden_sizes)
        if getattr(meta, "hidden_sizes", None) else None
    )

    print(
        f"# capture_game_length_distribution  "
        f"version={args.bootstrap_version}  "
        f"n_games={args.n_games}  workers={args.n_workers}  "
        f"decision_cap={args.decision_cap}  "
        f"tail_threshold={args.tail_threshold}",
        flush=True,
    )

    print("# loading deck pool ...", flush=True)
    deck_pool = decks_from_json(args.deck_pool)
    print(f"# loaded {len(deck_pool)} decks", flush=True)

    # Per-task args — every task carries the deck_pool, weights_path
    # and hidden_sizes inline. Mirrors the production
    # ``data_gen.generate_training_data_parallel`` pattern, which
    # works reliably with mp.Pool on Windows. The pickled per-task
    # cost is ~3MB but the ``imap_unordered`` queue handles it well.
    if args.game_indices is not None:
        game_indices = [int(s) for s in args.game_indices.split(",")]
    else:
        game_indices = list(range(args.n_games))
    args_list = [
        {
            "game_idx": i,
            "base_seed": args.base_seed,
            "decision_cap": args.decision_cap,
            "enable_mulligans": args.enable_mulligans,
            "tail_keep_last": args.tail_keep_last,
            "deck_pool": deck_pool,
            "weights_path": weights_path,
            "hidden_sizes": hidden_sizes,
        }
        for i in game_indices
    ]

    started = time.perf_counter()
    results: list[dict[str, Any]] = []

    def _record(r: dict) -> None:
        results.append(r)
        print(
            f"#   game {r['game_idx']}: {r['wall_sec']:>6.1f}s "
            f"{r['decisions_completed']:>5d} dec  "
            f"winner={r['winner']}  cap_hit={r['cap_hit']}  "
            f"{'ERR' if r['error'] else ''}",
            flush=True,
        )
        # Per-game JSONL append — partial progress survives an
        # interrupted run. Only the rich payload is written; the
        # summary stats live in --out at the end.
        if args.jsonl_out is not None:
            with open(args.jsonl_out, "a", encoding="utf-8") as f:
                f.write(json.dumps(r, default=str) + "\n")

    if args.n_workers <= 1:
        for a in args_list:
            r = _worker(a)
            _record(r)
    else:
        with mp.Pool(processes=args.n_workers) as pool:
            for r in pool.imap_unordered(_worker, args_list, chunksize=1):
                _record(r)
    total_wall = time.perf_counter() - started
    results.sort(key=lambda x: x["game_idx"])

    # Stats pass.
    walls = sorted(
        r["wall_sec"] for r in results if r["error"] is None
    )
    decisions = sorted(
        r["decisions_completed"] for r in results if r["error"] is None
    )
    n_clean = len(walls)
    n_err = sum(1 for r in results if r["error"] is not None)
    n_cap = sum(1 for r in results if r["cap_hit"])
    n_draw = sum(1 for r in results if r["is_draw"])
    n_winner = sum(1 for r in results if r["winner"] is not None)

    def pct(arr: list, p: float) -> float:
        if not arr:
            return -1.0
        idx = max(0, min(len(arr) - 1, int(round(len(arr) * p / 100)) - 1))
        return arr[idx]

    bucket_counts: dict[str, int] = {}
    bucket_walls: dict[str, list[float]] = {}
    for r in results:
        if r["error"] is not None:
            continue
        b = _bucket_label(r["decisions_completed"])
        bucket_counts[b] = bucket_counts.get(b, 0) + 1
        bucket_walls.setdefault(b, []).append(r["wall_sec"])

    bucket_order = [
        "0-200", "200-500", "500-1000", "1000-2000",
        "2000-4000", "4000-8000", "8000+",
    ]

    print("\n" + "=" * 78)
    print(f"# Run summary")
    print("=" * 78)
    print(f"#   total wall: {total_wall:.0f}s "
          f"({total_wall / 60:.1f}min)")
    print(f"#   clean games: {n_clean}/{len(game_indices)}  "
          f"errored: {n_err}  cap_hit: {n_cap}  "
          f"draws: {n_draw}  winners: {n_winner}")
    if walls:
        print(f"\n# Wall distribution (clean games)")
        print(f"#   min={walls[0]:.1f}s  p25={pct(walls,25):.1f}s  "
              f"p50={pct(walls,50):.1f}s  p75={pct(walls,75):.1f}s  "
              f"p90={pct(walls,90):.1f}s  max={walls[-1]:.1f}s")
    if decisions:
        print(f"\n# Decision distribution (clean games)")
        print(f"#   min={decisions[0]}  p25={pct(decisions,25):.0f}  "
              f"p50={pct(decisions,50):.0f}  p75={pct(decisions,75):.0f}  "
              f"p90={pct(decisions,90):.0f}  max={decisions[-1]}")

    print("\n# Decision-count buckets")
    for b in bucket_order:
        count = bucket_counts.get(b, 0)
        bw = bucket_walls.get(b, [])
        if count == 0:
            continue
        bw_med = sorted(bw)[len(bw)//2] if bw else 0.0
        print(f"#   {b:>10}: {count:>3d} games  "
              f"({100*count/n_clean:>5.1f}%)  "
              f"median_wall={bw_med:.1f}s")

    # Long-tail games — write the rich payload (last K decisions etc.)
    long_tails = [
        r for r in results
        if r["decisions_completed"] >= args.tail_threshold
    ]
    print(f"\n# Long-tail games (>= {args.tail_threshold} decisions): "
          f"{len(long_tails)}/{n_clean}")
    for r in long_tails:
        # Top-3 last-decision classes.
        top = sorted(
            r["last_decision_classes"].items(),
            key=lambda kv: -kv[1],
        )[:3]
        top_s = ", ".join(f"{k}={v}" for k, v in top)
        print(f"#   game {r['game_idx']}: "
              f"{r['decisions_completed']} dec  "
              f"{r['wall_sec']:.1f}s  "
              f"winner={r['winner']}  "
              f"life={r['final_p0_life']}/{r['final_p1_life']}  "
              f"libs={r['final_p0_lib_size']}/{r['final_p1_lib_size']}  "
              f"bf={r['final_battlefield_size']}  "
              f"last100[{top_s}]")

    # Write the JSON payload.
    payload = {
        "config": {
            "n_games": args.n_games,
            "n_workers": args.n_workers,
            "base_seed": args.base_seed,
            "decision_cap": args.decision_cap,
            "tail_threshold": args.tail_threshold,
            "tail_keep_last": args.tail_keep_last,
            "bootstrap_version": args.bootstrap_version,
            "hidden_sizes": (
                list(hidden_sizes) if hidden_sizes else None
            ),
        },
        "summary": {
            "total_wall_sec": round(total_wall, 1),
            "clean_games": n_clean,
            "errored_games": n_err,
            "cap_hit_games": n_cap,
            "draw_games": n_draw,
            "winner_games": n_winner,
            "wall_p25": pct(walls, 25),
            "wall_p50": pct(walls, 50),
            "wall_p75": pct(walls, 75),
            "wall_p90": pct(walls, 90),
            "wall_max": walls[-1] if walls else -1.0,
            "decisions_p25": pct(decisions, 25),
            "decisions_p50": pct(decisions, 50),
            "decisions_p75": pct(decisions, 75),
            "decisions_p90": pct(decisions, 90),
            "decisions_max": decisions[-1] if decisions else -1,
            "bucket_counts": bucket_counts,
        },
        "games": results,
    }
    args.out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n# wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
