"""Train the value-network MLP from saved (features, outcomes) data
and register it as a new versioned model in the registry.

Loads every ``*.npz`` in ``--data-dir``, fits the ``_ValueMLP`` via
MSE regression on the outcome target, registers as ``v{N+1}`` under
``--registry-root`` (default ``trained_weights/``) with a metadata
sidecar capturing training hyperparameters, loss history, and the
data sources used. Uses CUDA when available.

Usage::

    python scripts/train_nn.py \\
        --data-dir training_data/ \\
        --epochs 100

    # Custom registry location
    python scripts/train_nn.py --data-dir training_data/ \\
        --registry-root experiments/run3/weights --epochs 50

The version ID is auto-assigned (v1, v2, ...). The trained network
loads via ``NNEvaluator(weights_path=registry.weights_path("v3"))``
or via ``scripts/evaluate_nn.py --version v3``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.features import FEATURE_DIM  # noqa: E402
from mtg_bot.search.nn_evaluator import HIDDEN_SIZES  # noqa: E402
from mtg_bot.training import (  # noqa: E402
    auto_device, load_all_datasets, train_value_network,
)
from mtg_bot.training.registry import ModelMetadata, Registry  # noqa: E402


def _git_commit() -> str | None:
    """Best-effort current git commit short SHA; None if not a git
    repo or git isn't on PATH."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, required=True,
        help="Directory of *.npz training files (data_gen output).",
    )
    parser.add_argument(
        "--registry-root", type=Path,
        default=Path("trained_weights"),
        help=(
            "Registry root directory. Trained weights register as "
            "v{N}/ subdirectories under here. Default trained_weights/."
        ),
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
    parser.add_argument(
        "--notes", default="",
        help="Optional free-form note saved into metadata.json.",
    )
    parser.add_argument(
        "--progress-path", type=Path, default=None,
        help=(
            "Where to write live per-epoch progress JSON for the "
            "training UI. Defaults to "
            "<cwd>/training_progress/<version>.json where <version> "
            "is the next registry version (peeked, not reserved). "
            "Pass an explicit path to override; pass an empty string "
            "to disable progress emission entirely."
        ),
    )
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        sys.exit(f"--data-dir {args.data_dir} is not a directory")

    print(f"# Loading data from {args.data_dir}")
    features, outcomes = load_all_datasets(args.data_dir)
    if features.shape[0] == 0:
        sys.exit(
            f"No .npz files found in {args.data_dir}. Generate data "
            f"with scripts/generate_training_data.py first."
        )
    data_files = sorted(p.name for p in args.data_dir.glob("*.npz"))
    print(
        f"# {features.shape[0]} samples from {len(data_files)} files, "
        f"FEATURE_DIM={features.shape[1]}"
    )

    device = args.device or auto_device()
    print(f"# Training on {device} for {args.epochs} epochs")

    # Resolve the progress-file path BEFORE training so the UI can
    # see the run from epoch 0. We peek at the next version ID
    # rather than reserve it — the registry assigns sequentially at
    # register time, so as long as nobody else trains concurrently
    # the peek value matches the eventual assignment. If a race
    # happens, the progress filename simply won't match the
    # registered version; nothing breaks (the UI just sees an extra
    # file with the original name).
    registry = Registry(args.registry_root)
    peeked_version = registry.next_version_id()
    if args.progress_path is None:
        progress_dir = Path("training_progress")
        progress_dir.mkdir(parents=True, exist_ok=True)
        progress_path: Path | None = progress_dir / f"{peeked_version}.json"
    elif str(args.progress_path) == "":
        progress_path = None
    else:
        progress_path = args.progress_path
        progress_path.parent.mkdir(parents=True, exist_ok=True)
    if progress_path is not None:
        print(f"# Progress JSON: {progress_path}")

    # Train into a temp file, then hand off to the registry which
    # copies the bytes into the versioned directory.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_weights = Path(tmp) / "weights.pt"
        started = time.perf_counter()
        history = train_value_network(
            features=features, outcomes=outcomes,
            weights_out_path=tmp_weights,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.lr,
            val_split=args.val_split,
            device=device,
            rng_seed=args.seed,
            progress_path=progress_path,
            run_id=peeked_version,
            notes=args.notes,
        )
        elapsed = time.perf_counter() - started

        metadata = ModelMetadata(
            version="",  # filled in by Registry.register
            created_at="",  # filled in by Registry.register
            feature_dim=FEATURE_DIM,
            hidden_sizes=list(HIDDEN_SIZES),
            training={
                "data_dir": str(args.data_dir),
                "data_files": data_files,
                "n_samples": int(features.shape[0]),
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "learning_rate": args.lr,
                "val_split": args.val_split,
                "device": device,
                "rng_seed": args.seed,
                "duration_seconds": elapsed,
            },
            training_history={
                "train_losses": history.train_losses,
                "val_losses": history.val_losses,
                "final_train_loss": history.train_losses[-1],
                "final_val_loss": history.val_losses[-1],
                "best_val_loss": history.best_val_loss,
                "best_val_epoch": history.best_val_epoch,
            },
            git_commit=_git_commit(),
            notes=args.notes,
        )
        version = registry.register(tmp_weights, metadata)

    print(f"\n# Done in {elapsed:.1f}s. Registered as {version}.")
    print(f"# Weights:  {registry.weights_path(version)}")
    print(f"# Final train MSE: {history.train_losses[-1]:.4f}")
    print(f"# Final val MSE:   {history.val_losses[-1]:.4f}")
    print(
        f"# Best val MSE: {history.best_val_loss:.4f} "
        f"at epoch {history.best_val_epoch}"
    )


if __name__ == "__main__":
    main()
