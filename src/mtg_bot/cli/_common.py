"""Shared argparse parents + helpers for the ``mtg_bot`` CLI.

Every subcommand consumes these via ``parents=[...]`` so cross-cutting
concerns — depth (samples + nodes), the queue/bundle URLs, the deck
pool, the progress dir, the per-game timeout — are defined exactly
once. Defaults match the most recent iteration's self-play config so
eval-vs-self-play depth never drifts again (see ``CLAUDE.md`` "Eval
depth must match self-play depth").

If you change a default here, every subcommand picks it up; that is
the whole point.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Tailnet hostname of the master that runs the queue + bundle server.
# Hard-coded here (not auto-detected) so a remote shard pulling the
# bundle gets the right master URL out of the box. If the master
# changes, edit this constant.
DEFAULT_MASTER_TAILNET = "desktop-j05412i"

DEFAULT_QUEUE_URL = f"http://{DEFAULT_MASTER_TAILNET}:5099"
DEFAULT_BUNDLE_URL = f"{DEFAULT_QUEUE_URL}/repo.bundle"

# iter_005 self-play depth. Eval/capture defaults track this value by
# convention (CLAUDE.md "Eval depth"). Update both here AND in
# ``iterate_alphazero``'s self-play call when the convention shifts.
DEFAULT_NODES = 200
DEFAULT_SAMPLES = 4

# Deck pools. The TARGET pool is the PowerLSV cube (see
# ``mtg_bot.cards.pools``): ``CUBE_DECK_POOL`` is written by
# ``scripts/build_cube_deck_pool.py`` once the parser claims enough cube
# cards per color pair (it fails loudly until then -- see
# ``docs/CUBE_POOL_COVERAGE.md``). ``DEFAULT_DECK_POOL`` stays on the
# 17lands EoE corpus until that file exists so in-flight EoE runs and
# ad-hoc ``mtg_bot eval/ladder`` invocations keep working; flip it to
# ``CUBE_DECK_POOL`` when the cube pool is generated.
CUBE_DECK_POOL = Path("data/cube/power_lsv_decks.json.gz")
DEFAULT_DECK_POOL = Path("data/17lands/eoe_decks.json.gz")
DEFAULT_PROGRESS_DIR = Path("training_progress")
DEFAULT_SHARDS_CONFIG = Path("shards_config.json")
# 450s was the original budget; 2026-05-08 v16-vs-v13 eval analysis
# showed completed-game p99 wall = 390s and max = 449s. With the
# observed master shard slowdown over long runs (+14% sec/decision
# +30% wall/game by hour 8, separate todo), the right tail of slow
# games regularly clipped the 450 cap. Bumping to 600 leaves margin
# for the right tail without throughput cost (theoretical only — most
# games finish well under 400s). Bias-check from the same investigation:
# v_X win rate is flat across decision-count bins, so longer games are
# not systematically biased toward either side, making this safe.
DEFAULT_PER_GAME_TIMEOUT_SEC = 600.0

# Per-game wall budget scales with the SEARCH WORK PER DECISION, which
# is ``nodes * samples`` -- PIMC runs ``samples`` independent
# sub-searches of ``nodes`` expansions each, every decision. The old
# ``3 * nodes`` default ignored ``samples`` entirely, so halving nodes
# and halving samples (a 4x cost cut) only moved the budget 2x, and at
# the 2026-09-23 production config it landed below the median game.
#
# Measured, this box, 20 workers (in-worker mean = wall * workers /
# games):
#
#   training_progress_s2/iter_001_self_play_v1.json -- nodes=100,
#     samples=2: 3347.7s elapsed / 325 games -> 206s per game mean;
#     6 timeouts (1.8%) against the operator's hand-picked 900s cap.
#   ladder_runs/prod_n100s2/run.log -- nodes=100, samples=2,
#     random vs v13s: 3300s / 200 games -> 330s per game mean;
#     1 timeout (0.5%) at 900s, abandoned at 1070 decisions.
#   ladder_runs/prod_2026-09-23/run.log -- nodes=200, samples=4,
#     random vs heuristic: 1522s / 500 games -> 61s per game mean;
#     4 timeouts (0.8%) at 600s, all on games 1.3-1.75x the mean
#     decision count.
#
# ``3 * nodes`` at nodes=100 is 300s -- BELOW both measured means. The
# 4.5 s/search-unit constant reproduces the 900s the operator
# converged on by hand for nodes=100/samples=2 and tracks depth
# changes correctly thereafter.
#
# Why erring high is the safe direction: timed-out games are dropped
# entirely (``MatchStats.timed_out`` / the data-gen sentinel), and the
# games that time out are systematically the LONG ones, so a tight cap
# silently truncates the training distribution's right tail. A loose
# cap only costs one worker-slot of throughput on a rare game.
PER_GAME_TIMEOUT_SEC_PER_SEARCH_UNIT = 4.5
MIN_DEFAULT_PER_GAME_TIMEOUT_SEC = 60.0
MAX_DEFAULT_PER_GAME_TIMEOUT_SEC = 3600.0

# Iterate-specific split: ``iterate`` runs both self-play (uncontended
# data-gen, one worker per shard) and eval (14-worker contended) off
# the SAME ``--per-game-timeout-...-sec`` knob historically. PR #46
# (commit 591164b9, 2026-05-09) eval against v21 1024-trunk showed the
# one completed game (game_idx=12) used 178.8s / 592 decisions while
# 5 timed-out games had each logged 515-645 decisions when killed
# (real progress, not wedges). So the previous 300s cap clipped right
# at the median, not the p99. Split rationale:
#
# * Self-play is uncontended — one worker, no GPU/CPU sharing. p99
#   completed-game wall measured at <400s consistently; 300s covers
#   the bulk and rare clip is an acceptable throughput-vs-tail tradeoff
#   (mitigates the rare engine-state hang without burning a whole
#   eval-game budget on every slow game).
# * Eval is 14-worker contended — GPU + CPU sharing inflates per-decision
#   wall ~2x for the same network. Field evidence above shows real
#   eval games genuinely need 600s+ to complete. 600s covers the right
#   tail without clipping the median.
DEFAULT_PER_GAME_TIMEOUT_SELF_PLAY_SEC = 300.0
DEFAULT_PER_GAME_TIMEOUT_EVAL_SEC = 600.0


def depth_parser() -> argparse.ArgumentParser:
    """``--samples`` + ``--nodes`` (the search-depth knobs).

    Eval, bench, capture, iterate all consume this. Defaults are pinned
    to the most-recent self-play config so a freshly-templated eval
    doesn't accidentally measure a different network.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--samples", type=int, default=DEFAULT_SAMPLES,
        help=(
            f"PIMC samples K (default {DEFAULT_SAMPLES}). Match "
            "self-play depth for eval (CLAUDE.md 'Eval depth')."
        ),
    )
    p.add_argument(
        "--nodes", type=int, default=DEFAULT_NODES,
        help=(
            f"MCTS max_nodes per sub-search (default {DEFAULT_NODES}; "
            "the iter_005 self-play depth)."
        ),
    )
    return p


def cluster_parser() -> argparse.ArgumentParser:
    """``--shards-config`` + ``--queue-url`` + ``--bundle-url``.

    Distributed self-play, distributed eval, the bundle/queue server
    itself all need these. Defaults bake in the current master's
    tailnet hostname so a fresh-clone invocation works without flags.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--shards-config", type=Path, default=DEFAULT_SHARDS_CONFIG,
        help=f"ShardsConfig JSON path (default {DEFAULT_SHARDS_CONFIG}).",
    )
    p.add_argument(
        "--queue-url", default=DEFAULT_QUEUE_URL,
        help=(
            "Master's queue endpoint base URL (default "
            f"{DEFAULT_QUEUE_URL}). Remotes pull jobs from here."
        ),
    )
    p.add_argument(
        "--bundle-url", default=DEFAULT_BUNDLE_URL,
        help=(
            "Master's git bundle URL (default "
            f"{DEFAULT_BUNDLE_URL}). Remotes refresh their checkout "
            "from this on each shard."
        ),
    )
    return p


def runtime_parser() -> argparse.ArgumentParser:
    """``--deck-pool`` + ``--progress-dir`` + ``--per-game-timeout-sec``.

    Anything that runs games needs these.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--deck-pool", type=Path, default=DEFAULT_DECK_POOL,
        help=f"17lands deck pool path (default {DEFAULT_DECK_POOL}).",
    )
    p.add_argument(
        "--progress-dir", type=Path, default=DEFAULT_PROGRESS_DIR,
        help=(
            "Directory the training UI watches for progress JSON "
            f"(default {DEFAULT_PROGRESS_DIR})."
        ),
    )
    p.add_argument(
        "--per-game-timeout-sec", type=float,
        default=None,
        help=(
            "Wall-clock budget per game before the worker abandons "
            f"it. Default is {PER_GAME_TIMEOUT_SEC_PER_SEARCH_UNIT} * "
            "--nodes * --samples seconds, clamped to "
            f"[{MIN_DEFAULT_PER_GAME_TIMEOUT_SEC:.0f}, "
            f"{MAX_DEFAULT_PER_GAME_TIMEOUT_SEC:.0f}] (resolved by "
            "the caller after parse, see "
            "``resolve_per_game_timeout``). Per-game wall scales with "
            "the search work per decision, which is nodes*samples "
            "under PIMC, so the budget auto-tracks both knobs."
        ),
    )
    return p


def default_per_game_timeout_sec(nodes: int, samples: int) -> float:
    """The per-game wall budget to use when the operator didn't pass
    one: ``PER_GAME_TIMEOUT_SEC_PER_SEARCH_UNIT * nodes * samples``,
    clamped to ``[MIN_.., MAX_DEFAULT_PER_GAME_TIMEOUT_SEC]``.

    See the constant's comment for the calibration and why the old
    ``3 * nodes`` formula was wrong.
    """
    work_units = max(1, int(nodes)) * max(1, int(samples))
    budget = PER_GAME_TIMEOUT_SEC_PER_SEARCH_UNIT * work_units
    return float(
        min(
            MAX_DEFAULT_PER_GAME_TIMEOUT_SEC,
            max(MIN_DEFAULT_PER_GAME_TIMEOUT_SEC, budget),
        )
    )


def resolve_per_game_timeout(args) -> None:
    """Mutate ``args.per_game_timeout_sec`` to
    :func:`default_per_game_timeout_sec` if it wasn't explicitly set.
    Called by subcommands after parse so the formula picks up the
    user's actual ``--nodes`` / ``--samples`` values.

    ``--samples`` comes from :func:`depth_parser`, which every
    game-running subcommand pairs with :func:`runtime_parser`; the
    ``getattr`` fallback keeps a hypothetical samples-less caller
    working at the shipped default.

    Subcommands using :func:`runtime_parser` must call this exactly
    once at the top of their ``main``."""
    if getattr(args, "per_game_timeout_sec", None) is None:
        args.per_game_timeout_sec = default_per_game_timeout_sec(
            args.nodes, getattr(args, "samples", DEFAULT_SAMPLES),
        )


def load_shards_config(path: Path):
    """Re-export of the v2 URL-only shards-config loader.

    Post v2-cutover the loader lives in
    ``mtg_bot.cli.runs.heartbeat_poller`` (same path the coordinator's
    heartbeat thread uses to discover workers). Returns the worker
    list as ``[{worker_url: "..."}, ...]``; the legacy
    ``{shards: [...]}`` SSH shape raises
    :class:`LegacyShardsConfigError` from that module. Most callers
    prefer :func:`mtg_bot.distributed_rest_orchestrator.load_worker_urls`
    which returns just the URL strings; this re-export stays for
    parity with older subcommand imports.
    """
    from mtg_bot.cli.runs.heartbeat_poller import load_shards_config as _impl
    return _impl(path)


__all__ = [
    "DEFAULT_BUNDLE_URL",
    "DEFAULT_DECK_POOL",
    "DEFAULT_MASTER_TAILNET",
    "DEFAULT_NODES",
    "DEFAULT_PER_GAME_TIMEOUT_EVAL_SEC",
    "DEFAULT_PER_GAME_TIMEOUT_SEC",
    "DEFAULT_PER_GAME_TIMEOUT_SELF_PLAY_SEC",
    "DEFAULT_PROGRESS_DIR",
    "DEFAULT_QUEUE_URL",
    "DEFAULT_SAMPLES",
    "DEFAULT_SHARDS_CONFIG",
    "MAX_DEFAULT_PER_GAME_TIMEOUT_SEC",
    "MIN_DEFAULT_PER_GAME_TIMEOUT_SEC",
    "PER_GAME_TIMEOUT_SEC_PER_SEARCH_UNIT",
    "cluster_parser",
    "default_per_game_timeout_sec",
    "depth_parser",
    "load_shards_config",
    "resolve_per_game_timeout",
    "runtime_parser",
]
