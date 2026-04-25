"""Train the value-network MLP from saved (features, outcomes) data.

Loads every ``*.npz`` in ``--data-dir``, fits the ``_ValueMLP`` via
MSE regression on the outcome target, saves the final state_dict to
``--weights-out``. Uses CUDA when available.

Usage::

    # Train on whatever's in training_data/
    python scripts/train_nn.py \\
        --data-dir training_data/ \\
        --weights-out trained_weights/v1.pt \\
        --epochs 30

    # CPU explicitly
    python scripts/train_nn.py --data-dir training_data/ \\
        --weights-out trained_weights/cpu_v1.pt --device cpu
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
    auto_device, load_all_datasets, train_value_network,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, required=True,
        help="Directory of *.npz training files (data_gen output).",
    )
    parser.add_argument(
        "--weights-out", type=Path, required=True,
        help="Path to write the trained state_dict (.pt).",
    )
    parser.add_argument(
        "--epochs", type=int, default=30,
        help="Training epochs (default 30).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=256,
        help="Batch size (default 256).",
    )
    parser.add_argument(
        "--lr", type=float, default=1e-3,
        help="Adam learning rate (default 1e-3).",
    )
    parser.add_argument(
        "--val-split", type=float, default=0.1,
        help="Fraction of data held out for validation (default 0.1).",
    )
    parser.add_argument(
        "--device", default=None,
        help="cuda/cpu (default: cuda if available, else cpu).",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="RNG seed for split + init (default 0).",
    )
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        sys.exit(f"--data-dir {args.data_dir} is not a directory")
    args.weights_out.parent.mkdir(parents=True, exist_ok=True)

    print(f"# Loading data from {args.data_dir}")
    features, outcomes = load_all_datasets(args.data_dir)
    if features.shape[0] == 0:
        sys.exit(
            f"No .npz files found in {args.data_dir}. Generate data "
            f"with scripts/generate_training_data.py first."
        )
    print(
        f"# {features.shape[0]} samples, FEATURE_DIM={features.shape[1]}"
    )

    device = args.device or auto_device()
    print(f"# Training on {device} for {args.epochs} epochs")

    started = time.perf_counter()
    history = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=args.weights_out,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        val_split=args.val_split,
        device=device,
        rng_seed=args.seed,
    )
    elapsed = time.perf_counter() - started

    print(f"\n# Done in {elapsed:.1f}s. Wrote {args.weights_out}")
    print(f"# Final train MSE: {history.train_losses[-1]:.4f}")
    print(f"# Final val MSE:   {history.val_losses[-1]:.4f}")
    print(
        f"# Best val MSE: {history.best_val_loss:.4f} "
        f"at epoch {history.best_val_epoch}"
    )


if __name__ == "__main__":
    main()
