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

from mtg_bot.training import (  # noqa: E402
    PimcConfig, generate_training_data, save_dataset,
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
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    config = PimcConfig(samples=args.samples, inner_nodes=args.nodes)
    factory = lambda seed, _c=config: _c.build(seed)

    print(
        f"# generate_training_data: {args.n_games} games "
        f"(samples={args.samples}, nodes={args.nodes}, "
        f"sample_every={args.sample_every}, seed={args.seed})"
    )
    started = time.perf_counter()
    features, outcomes = generate_training_data(
        p0_factory=factory,
        p1_factory=factory,
        n_games=args.n_games,
        base_seed=args.seed,
        sample_every=args.sample_every,
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
