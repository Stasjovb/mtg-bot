"""Run a head-to-head distributed eval between two registered NN
versions (or NN-vs-heuristic with ``--old=heuristic``).

Replaces the per-experiment one-off scripts (``eval_v15_v13_oneoff.py``,
``eval_v16_v13_6000g.py``, ...). The samples / nodes / queue-url /
deck-pool / progress-dir / per-game-timeout-sec defaults all come
from ``mtg_bot.cli._common`` so a fresh-clone invocation of:

    python -m mtg_bot.cli eval --new v16 --old v13 --games 3000

uses the same depth as iter_005 self-play (200 nodes, 4 samples)
and posts to the same master queue, without anyone having to
remember which numbers are current. Override any default with the
matching flag (``--nodes``, ``--queue-url``, ``--per-game-timeout-sec``,
...).
"""

from __future__ import annotations

import argparse
import time
from math import ceil
from pathlib import Path

from mtg_bot.cli._common import (
    cluster_parser,
    depth_parser,
    load_shards_config,
    runtime_parser,
)
from mtg_bot.search.heuristics_config import HeuristicsConfig
from mtg_bot.training.distributed import (
    EvalJobSpec, run_distributed_eval,
)


# Trunk shape baked into v13/v15/v16+. If a future architecture change
# makes this wrong, the registry-loaded ``hidden_sizes`` from the
# version's metadata.json will trump this; keeping it as a default
# avoids one more required CLI flag for the common case.
_DEFAULT_HIDDEN_SIZES = (1024, 1024, 512)


def main(argv=None) -> None:  # pragma: no cover
    # Argparse + run_distributed_eval dispatch; the heavy logic lives
    # in ``mtg_bot.training.distributed.run_distributed_eval`` which
    # has its own coverage. The body here is straight-line plumbing.
    parser = argparse.ArgumentParser(
        description=__doc__,
        parents=[depth_parser(), cluster_parser(), runtime_parser()],
    )
    parser.add_argument(
        "--new", required=True,
        help=(
            "New (challenger) version — registered version label "
            "(e.g. ``v16``). Loaded from "
            "``trained_weights/<label>/weights.pt``."
        ),
    )
    parser.add_argument(
        "--old", required=True,
        help=(
            "Old (champion) version — same shape as ``--new``. Use "
            "``heuristic`` to eval the new NN against the heuristic "
            "agent baseline."
        ),
    )
    parser.add_argument(
        "--games", type=int, required=True,
        help=(
            "Total games to play. Power-analysis discussion 2026-05-07: "
            "~6000 games is the threshold for one-sided 95%%CI / 80%% "
            "power at the 51.5-52%% edge band typical of one-iteration "
            "AlphaZero deltas."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=60007,
        help="Base RNG seed (default 60007).",
    )
    parser.add_argument(
        "--queue-slack-pct", type=float, default=0.1,
        help=(
            "Fraction of ``--games`` to over-queue, so stragglers "
            "don't block the run from completing the requested count "
            "of decided games. Default 0.1 (10%% slack)."
        ),
    )
    parser.add_argument(
        "--label",
        help=(
            "Tag applied to the eval result JSON's ``opponent_label`` "
            "and the run_id_prefix. Defaults to "
            "``<new>_vs_<old>_<games>g``."
        ),
    )
    parser.add_argument(
        "--enable-mulligans", action="store_true",
        help="Allow opening-hand mulligans (default off — eval only).",
    )
    parser.add_argument(
        "--capture-every", type=int, default=0,
        help=(
            "Save annotated replay files every Nth game. Default 0 = "
            "no replay capture."
        ),
    )
    args = parser.parse_args(argv)

    label = args.label or f"{args.new}_vs_{args.old}_{args.games}g"
    weights_path = lambda v: f"trained_weights/{v}/weights.pt"  # noqa: E731

    shards_cfg = load_shards_config(args.shards_config)
    args.progress_dir.mkdir(parents=True, exist_ok=True)

    spec = EvalJobSpec(
        new_weights_path=weights_path(args.new),
        old_weights_path=weights_path(args.old),
        samples=args.samples,
        inner_nodes=args.nodes,
        hidden_sizes=_DEFAULT_HIDDEN_SIZES,
        base_seed=args.seed,
        enable_mulligans=args.enable_mulligans,
        per_game_timeout_sec=args.per_game_timeout_sec,
        deck_pool_path=str(args.deck_pool),
        capture_every=args.capture_every,
        nn_new_version_label=args.new,
        nn_old_version_label=args.old,
        opponent_label=label,
        heuristics=HeuristicsConfig.disabled(),
    )

    slack_extra = ceil(args.games * args.queue_slack_pct)
    print(
        f"[eval] {args.new} vs {args.old}: n_games={args.games}, "
        f"per_game_timeout={args.per_game_timeout_sec}s, "
        f"nodes={args.nodes}, samples={args.samples}, "
        f"queue_slack_extra={slack_extra}"
    )

    t0 = time.perf_counter()
    counts = run_distributed_eval(
        shards_cfg, spec,
        progress_dir=args.progress_dir,
        run_id_prefix=f"eval_{label}",
        total_games=args.games,
        queue_url=args.queue_url,
        bundle_url=args.bundle_url,
        slack_extra=slack_extra,
    )
    elapsed = time.perf_counter() - t0

    wins_new = counts.get("wins_new", 0)
    wins_old = counts.get("wins_old", 0)
    draws = counts.get("draws", 0)
    crashed = counts.get("crashed", 0)
    n_decided = wins_new + wins_old
    wr = wins_new / n_decided if n_decided else 0.0
    print(
        f"[eval] {args.new} vs {args.old} complete in {elapsed/60:.1f}min: "
        f"wins_new={wins_new}, wins_old={wins_old}, draws={draws}, "
        f"crashed={crashed}, win_rate={wr:.1%}"
    )


if __name__ == "__main__":
    main()
