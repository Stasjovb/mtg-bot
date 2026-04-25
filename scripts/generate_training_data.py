"""Generate self-play training data for the NN evaluator.

Plays ``--n-games`` of PIMC(heuristic) vs PIMC(heuristic), captures
(features, outcome) pairs at every non-chance decision from both
player perspectives, saves to ``--output`` as a compressed .npz.

Usage::

    # Tiny smoke (10 games, ~30s)
    python scripts/generate_training_data.py --n-games 10 \\
        --output training_data/run01.npz

    # Real session (100 games at recommend defaults, ~30 min)
    python scripts/generate_training_data.py --n-games 100 \\
        --samples 4 --nodes 200 --output training_data/run02.npz

The trainer (``train_nn.py``) loads ALL .npz files in a directory,
so each generation run can be a separate file and they accumulate.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import os  # noqa: E402

from mtg_bot.training import (  # noqa: E402
    PimcConfig,
    Registry,
    ReplayCaptureConfig,
    generate_training_data,
    generate_training_data_parallel,
    save_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-games", type=int, default=10,
        help="Games to play (default 10).",
    )
    parser.add_argument(
        "--samples", type=int, default=2,
        help="PIMC samples K (default 2 — tuning-fast).",
    )
    parser.add_argument(
        "--nodes", type=int, default=50,
        help="MCTS max_nodes per sub-search (default 50).",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Base seed.",
    )
    parser.add_argument(
        "--sample-every", type=int, default=1,
        help="Capture every Nth decision (default 1 = all).",
    )
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Output .npz path. Parent dirs are created.",
    )
    parser.add_argument(
        "--n-workers", type=int, default=None,
        help=(
            "Worker processes for parallel data gen. Default: "
            f"cpu_count - 2 (~{max(1, (os.cpu_count() or 1) - 2)} on "
            "this machine). Pass 1 to use the sequential code path "
            "(no spawn overhead — faster for very small n_games)."
        ),
    )
    parser.add_argument(
        "--save-replays-to", type=Path, default=None,
        help=(
            "Optional directory to write per-game replay files (gzipped "
            "JSON, ~100KB-1MB per game). Each game writes "
            "<prefix>_seed<S>_idx<N>.json.gz. Reviewable in the UI via "
            "/api/load_replay or via scripts/inspect_replay.py."
        ),
    )
    parser.add_argument(
        "--capture-every", type=int, default=1,
        help=(
            "When --save-replays-to is set: capture every Nth game "
            "(default 1 = capture all). Useful for limiting disk on "
            "long runs (e.g. --capture-every 10 -> 1-in-10 sampling)."
        ),
    )
    parser.add_argument(
        "--annotate-with-nn-version", default=None,
        help=(
            "Optional registered NN version (e.g. v3). When set, "
            "each replay snapshot also gets an `nn_eval` annotation "
            "from that network alongside the always-on `heuristic_eval`. "
            "Requires --save-replays-to. Looks up the version in "
            "--registry-root (default trained_weights/)."
        ),
    )
    parser.add_argument(
        "--registry-root", type=Path, default=Path("trained_weights"),
        help=(
            "Registry root for resolving --annotate-with-nn-version. "
            "Default trained_weights/."
        ),
    )
    parser.add_argument(
        "--replay-prefix", default="game",
        help="Prefix on replay filenames (default 'game').",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    config = PimcConfig(samples=args.samples, inner_nodes=args.nodes)
    # PimcConfig.build is a bound method of a frozen dataclass —
    # picklable, so it crosses the multiprocessing spawn boundary
    # cleanly. Lambdas would NOT (no qualified name).
    factory = config.build

    n_workers = args.n_workers
    if n_workers is None:
        n_workers = max(1, (os.cpu_count() or 1) - 2)

    replay_config: ReplayCaptureConfig | None = None
    if args.save_replays_to is not None:
        if args.annotate_with_nn_version is not None:
            registry = Registry(args.registry_root)
            if not registry.has(args.annotate_with_nn_version):
                sys.exit(
                    f"--annotate-with-nn-version {args.annotate_with_nn_version!r} "
                    f"not found in {args.registry_root}. Available: "
                    f"{registry.list_versions()}"
                )
            nn_weights_path = str(registry.weights_path(
                args.annotate_with_nn_version,
            ))
            nn_label = args.annotate_with_nn_version
        else:
            nn_weights_path = None
            nn_label = None
        args.save_replays_to.mkdir(parents=True, exist_ok=True)
        replay_config = ReplayCaptureConfig(
            save_dir=str(args.save_replays_to),
            capture_every=args.capture_every,
            nn_weights_path=nn_weights_path,
            nn_version_label=nn_label,
            filename_prefix=args.replay_prefix,
        )
    elif args.annotate_with_nn_version is not None:
        sys.exit(
            "--annotate-with-nn-version requires --save-replays-to "
            "(annotation only matters when replays are written)"
        )

    print(
        f"# generate_training_data: {args.n_games} games "
        f"(samples={args.samples}, nodes={args.nodes}, "
        f"sample_every={args.sample_every}, seed={args.seed}, "
        f"n_workers={n_workers})"
    )
    if replay_config is not None:
        nn_part = (
            f", annotated_with={args.annotate_with_nn_version}"
            if args.annotate_with_nn_version else ""
        )
        print(
            f"# replay capture: every {args.capture_every} game(s) -> "
            f"{args.save_replays_to}{nn_part}"
        )
    started = time.perf_counter()
    if n_workers == 1:
        features, outcomes = generate_training_data(
            p0_factory=factory, p1_factory=factory,
            n_games=args.n_games, base_seed=args.seed,
            sample_every=args.sample_every,
            replay_config=replay_config,
        )
    else:
        features, outcomes = generate_training_data_parallel(
            p0_factory=factory, p1_factory=factory,
            n_games=args.n_games, base_seed=args.seed,
            n_workers=n_workers,
            sample_every=args.sample_every,
            replay_config=replay_config,
        )
    elapsed = time.perf_counter() - started

    save_dataset(features, outcomes, args.output)
    n = features.shape[0]
    pos = int((outcomes > 0).sum())
    neg = int((outcomes < 0).sum())
    zero = int((outcomes == 0).sum())
    print(
        f"# Done in {elapsed:.1f}s ({elapsed / 60:.1f}m). Saved "
        f"{n} samples to {args.output}.\n"
        f"# Outcome distribution: +1={pos} ({pos / n:.1%}) "
        f"-1={neg} ({neg / n:.1%}) "
        f"0={zero} ({zero / n:.1%})"
    )


if __name__ == "__main__":
    main()
