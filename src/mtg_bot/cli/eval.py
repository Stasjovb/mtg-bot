"""Run a head-to-head distributed eval between two registered NN
versions via the v2 REST orchestrator.

Post v2-cutover, the standalone eval CLI mirrors what
``mtg_bot iterate`` does for its eval phase: it builds a stage spec
via :func:`mtg_bot.distributed_rest_orchestrator.make_eval_stage_spec`,
POSTs ``/v2/stage/create`` + ``/v2/start_eval`` to the cluster, and
polls ``/v2/stage/<id>`` until ``status == "complete"``.

All SSH-era kwargs (``bundle_url``, per-shard wall caps,
``hang-dump-dir`` plumbing) are gone — worker-owned config now lives
on each worker daemon's CLI flags (see ``deploy/README.md``). The
user-facing flags (``--new``, ``--old``, ``--games``, ``--nodes``,
``--samples``, ``--seed``, ``--label``, ``--capture-every``) stay
unchanged so existing eval invocations keep working.

The eval early-stop watcher continues to call
``/v2/stage/<id>/close`` for Wilson-CI early-stop verdicts — no
change to the watcher's mechanism.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from mtg_bot import distributed_rest_orchestrator as _rest_orch
from mtg_bot.cli._common import (
    cluster_parser,
    depth_parser,
    runtime_parser,
)
from mtg_bot.cli.runs import lifecycle as _lifecycle


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        parents=[depth_parser(), cluster_parser(), runtime_parser()],
    )
    parser.add_argument(
        "--new", required=True,
        help=(
            "New (challenger) version — registered version label "
            "(e.g. ``v16``). Worker daemons fetch the matching "
            "``trained_weights/<label>/`` from the coordinator's "
            "``GET /v2/weights/<label>`` endpoint on first claim."
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
        "--label",
        help=(
            "Tag applied to the eval result JSON's ``opponent_label`` "
            "and the run_id_prefix. Defaults to "
            "``<new>_vs_<old>_<games>g``."
        ),
    )
    parser.add_argument(
        "--capture-every", type=int, default=0,
        help=(
            "Save annotated replay files every Nth game. Default 0 = "
            "no replay capture."
        ),
    )
    parser.add_argument(
        "--poll-interval-s", type=float,
        default=_rest_orch.DEFAULT_POLL_INTERVAL_S,
        help=(
            f"Coordinator stage-poll interval (default "
            f"{_rest_orch.DEFAULT_POLL_INTERVAL_S}s). Tests stub this "
            "to a tiny value so the suite doesn't pace at 5s/poll."
        ),
    )
    args = parser.parse_args(argv)

    label = args.label or f"{args.new}_vs_{args.old}_{args.games}g"

    # Post-cutover: --shards-config is a URL list; --queue-url is the
    # coordinator URL the orchestrator hits for /v2/stage/* and the
    # worker daemons hit for /v2/claim + /v2/report_result.
    if not args.shards_config.is_file():
        sys.exit(f"--shards-config {args.shards_config} not found")
    if not args.queue_url:
        sys.exit(
            "--shards-config requires --queue-url (the master's "
            "coordinator endpoint, e.g. "
            "http://<master-tailnet>:5099)"
        )
    try:
        worker_urls = _rest_orch.load_worker_urls(args.shards_config)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"--shards-config: {e}")
    if not worker_urls:
        sys.exit(
            f"--shards-config {args.shards_config} parsed but "
            "contains no worker_urls entries"
        )

    args.progress_dir.mkdir(parents=True, exist_ok=True)

    # Deck pool size is the only piece of orchestrator-side config we
    # still need at stage-creation time — the per-game deck_indices
    # array lives on the stage spec. We don't load decks here (workers
    # do that locally); we just count entries.
    if not args.deck_pool.is_file():
        sys.exit(f"--deck-pool {args.deck_pool} not found")
    deck_pool_size = _count_decks_in_pool(args.deck_pool)
    if deck_pool_size <= 0:
        sys.exit(f"--deck-pool {args.deck_pool} loaded 0 decks")

    print(
        f"[eval] v2 REST distributed run across {len(worker_urls)} "
        f"workers via coordinator {args.queue_url}; "
        f"workers: {worker_urls}"
    )
    print(
        f"[eval] {args.new} vs {args.old}: n_games={args.games}, "
        f"per_game_timeout={args.per_game_timeout_sec}s, "
        f"nodes={args.nodes}, samples={args.samples}, label={label}"
    )

    run_id = f"eval_{label}"
    progress_json_path = args.progress_dir / f"{run_id}.json"
    eval_config = {
        "kind": "eval",
        "new": args.new,
        "old": args.old,
        "games": args.games,
        "nodes": args.nodes,
        "samples": args.samples,
        "seed": args.seed,
        "label": label,
        "deck_pool": str(args.deck_pool),
        "queue_url": args.queue_url,
        "per_game_timeout_sec": args.per_game_timeout_sec,
        "capture_every": args.capture_every,
    }

    spec = _rest_orch.make_eval_stage_spec(
        stage_id=run_id,
        n_games=args.games,
        base_seed=args.seed,
        deck_pool_size=deck_pool_size,
        new_version=args.new,
        old_version=args.old,
        nodes=args.nodes,
        samples=args.samples,
        per_game_timeout_sec=args.per_game_timeout_sec,
        capture_every=args.capture_every,
    )

    t0 = time.perf_counter()
    with _lifecycle.run_lifecycle(
        run_id=run_id, kind="eval",
        config=eval_config,
        progress_json_path=progress_json_path,
        label=label,
    ):
        # Stream per-poll progress (totals + per-machine breakdown)
        # into runs.db so the training UI's stats cards populate live.
        progress_writer = _rest_orch.make_runs_db_progress_writer(
            run_id, started_perf=t0,
        )
        result = _rest_orch.run_stage(
            coordinator_url=args.queue_url,
            worker_urls=worker_urls,
            spec=spec,
            poll_interval_s=args.poll_interval_s,
            progress_writer=progress_writer,
        )
    elapsed = time.perf_counter() - t0

    wins_new = int(result.wins_new or 0)
    wins_old = int(result.wins_old or 0)
    draws = int(result.draws or 0)
    crashed = int(result.crashed or 0)
    n_decided = wins_new + wins_old
    wr = wins_new / n_decided if n_decided else 0.0
    _lifecycle.push_eval_summary(
        run_id,
        wins_new=wins_new, wins_old=wins_old, draws=draws,
        crashed=crashed, elapsed_seconds=elapsed,
        extra={"win_rate": wr, "label": label},
    )
    print(
        f"[eval] {args.new} vs {args.old} complete in {elapsed/60:.1f}min: "
        f"wins_new={wins_new}, wins_old={wins_old}, draws={draws}, "
        f"crashed={crashed}, win_rate={wr:.1%}"
    )


def _count_decks_in_pool(path: Path) -> int:
    """Cheap row-count of the 17lands deck pool — we only need the
    size to make stage specs (per-game deck_indices). Workers do the
    full ``decks_from_json`` load locally."""
    from mtg_bot.decks import decks_from_json
    return len(decks_from_json(path))


if __name__ == "__main__":
    main()
