"""Train the offline deck-belief model on the 17lands EoE corpus.

Trains both the baseline (co-occurrence + Bayesian smoothing) and the
NN MLP, validates on a held-out split, prints calibration + recall@K +
Brier + ECE, and saves the best model to disk. Also writes a JSON
validation report to ``training_progress/deck_belief_report.json`` for
the UI to pick up later.

This is **Step 2** of the NN representation roadmap
(``docs/NN_REPRESENTATION_ROADMAP.md``). No PIMC integration here —
the deck-belief output feeds importance-sampled PIMC determinizations
in a separate follow-up.

Usage::

    PYTHONPATH=src python scripts/train_deck_belief.py \
        --corpus data/17lands/eoe_decks.json.gz \
        --output models/deck_belief \
        --val-fraction 0.1 \
        --nn-epochs 5 \
        --prefixes-per-deck 10

The default arguments produce a ~1.3M training-tuple corpus on the
130K-deck EoE dataset and train in <10 minutes on a CPU baseline +
<5 minutes on an NN with hidden_dim=256 on RTX 5090.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

from mtg_bot.training.deck_belief import (
    BaselineDeckBeliefModel,
    DeckBeliefModel,
    NNDeckBeliefModel,
    brier_score,
    calibration_bins,
    expected_calibration_error,
    load_deck_corpus,
    recall_at_k,
)


def _evaluate(
    model: DeckBeliefModel,
    held_out: list,
    *,
    seed: int = 0,
    revealed_fraction: float = 0.5,
    max_decks_for_calibration: int = 1000,
) -> dict:
    """Compute recall@{5,10,20}, calibration, Brier, ECE for one model."""
    results: dict[str, object] = {}

    for k in (5, 10, 20):
        rng = random.Random(seed)  # same shuffle across k
        r = recall_at_k(
            model,
            held_out,
            k=k,
            rng=rng,
            revealed_fraction=revealed_fraction,
        )
        results[f"recall_at_{k}"] = r

    rng = random.Random(seed + 1)
    bins = calibration_bins(
        model,
        held_out,
        n_bins=10,
        rng=rng,
        revealed_fraction=revealed_fraction,
        max_decks=max_decks_for_calibration,
    )
    results["calibration_bins"] = bins
    results["ece"] = expected_calibration_error(bins)

    rng = random.Random(seed + 2)
    results["brier"] = brier_score(
        model,
        held_out,
        rng=rng,
        revealed_fraction=revealed_fraction,
        max_decks=max_decks_for_calibration,
    )

    return results


def _split_corpus(
    decks: list,
    val_fraction: float,
    seed: int,
) -> tuple[list, list]:
    """Split decks into train / val with a deterministic shuffle."""
    rng = random.Random(seed)
    indices = list(range(len(decks)))
    rng.shuffle(indices)
    n_val = max(1, int(len(decks) * val_fraction))
    val_idx = set(indices[:n_val])
    train = [d for i, d in enumerate(decks) if i not in val_idx]
    val = [decks[i] for i in sorted(val_idx)]
    return train, val


def _print_report(name: str, metrics: dict, wall_seconds: float) -> None:
    """Pretty-print a model's validation metrics to stdout."""
    print(f"\n=== {name} ===")
    print(f"  train wall time: {wall_seconds:.2f}s")
    print(f"  recall@5  = {metrics['recall_at_5']:.4f}")
    print(f"  recall@10 = {metrics['recall_at_10']:.4f}")
    print(f"  recall@20 = {metrics['recall_at_20']:.4f}")
    print(f"  Brier     = {metrics['brier']:.4f}")
    print(f"  ECE       = {metrics['ece']:.4f}")
    print(f"  calibration bins (predicted -> empirical, count):")
    for b in metrics["calibration_bins"]:
        print(
            f"    [{b['bin_low']:.2f}, {b['bin_high']:.2f}) "
            f"pred={b['mean_predicted']:.3f} emp={b['mean_empirical']:.3f} "
            f"n={b['count']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("data/17lands/eoe_decks.json.gz"),
        help="Path to the 17lands EoE deck-pool JSON (gzipped).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/deck_belief"),
        help="Output directory for model artifacts.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("training_progress/deck_belief_report.json"),
        help="Where to write the JSON validation report.",
    )
    parser.add_argument(
        "--val-fraction",
        type=float,
        default=0.1,
        help="Fraction of decks held out for validation.",
    )
    parser.add_argument(
        "--prefixes-per-deck",
        type=int,
        default=10,
        help="Number of (revealed, rest) training tuples sampled per deck.",
    )
    parser.add_argument(
        "--nn-hidden-dim",
        type=int,
        default=256,
        help="Hidden dimension for the NN MLP.",
    )
    parser.add_argument(
        "--nn-n-layers",
        type=int,
        default=2,
        help="Number of hidden layers for the NN MLP.",
    )
    parser.add_argument(
        "--nn-epochs",
        type=int,
        default=5,
        help="Training epochs for the NN MLP.",
    )
    parser.add_argument(
        "--nn-batch-size",
        type=int,
        default=512,
        help="Mini-batch size for NN training.",
    )
    parser.add_argument(
        "--nn-lr",
        type=float,
        default=1e-3,
        help="Adam learning rate for NN training.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="Torch device for the NN ('cpu', 'cuda', etc).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for splits, prefix sampling, and NN init.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of decks loaded (smoke testing).",
    )
    parser.add_argument(
        "--skip-nn",
        action="store_true",
        help="Skip training the NN model — baseline only.",
    )
    args = parser.parse_args(argv)

    print(f"Loading corpus from {args.corpus}")
    decks = load_deck_corpus(args.corpus)
    print(f"  loaded {len(decks)} decks")
    if args.limit is not None:
        decks = decks[: args.limit]
        print(f"  limited to {len(decks)} decks for this run")

    train, val = _split_corpus(decks, args.val_fraction, args.seed)
    print(f"  train: {len(train)} decks, val: {len(val)} decks")

    args.output.mkdir(parents=True, exist_ok=True)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- Baseline ----
    print("\nTraining baseline (co-occurrence + Bayesian smoothing)...")
    t0 = time.time()
    baseline = BaselineDeckBeliefModel()
    baseline.fit(train)
    baseline_wall = time.time() - t0
    baseline_path = args.output / "baseline.npz"
    baseline.save(baseline_path)
    print(f"  saved to {baseline_path}")

    baseline_metrics = _evaluate(baseline, val, seed=args.seed)
    _print_report("Baseline", baseline_metrics, baseline_wall)

    report = {
        "corpus": str(args.corpus),
        "n_train_decks": len(train),
        "n_val_decks": len(val),
        "vocab_size": len(baseline.vocab),
        "seed": args.seed,
        "baseline": {
            "wall_seconds": baseline_wall,
            "model_path": str(baseline_path),
            **baseline_metrics,
        },
    }

    # ---- NN ----
    if not args.skip_nn:
        print("\nTraining NN (MLP)...")
        t0 = time.time()
        nn_model = NNDeckBeliefModel(
            hidden_dim=args.nn_hidden_dim,
            n_layers=args.nn_n_layers,
            epochs=args.nn_epochs,
            batch_size=args.nn_batch_size,
            lr=args.nn_lr,
            prefixes_per_deck=args.prefixes_per_deck,
            device=args.device,
            seed=args.seed,
        )
        nn_model.fit(train)
        nn_wall = time.time() - t0
        nn_path = args.output / "nn.pt"
        nn_model.save(nn_path)
        print(f"  saved to {nn_path}")

        nn_metrics = _evaluate(nn_model, val, seed=args.seed)
        _print_report("NN MLP", nn_metrics, nn_wall)

        report["nn"] = {
            "wall_seconds": nn_wall,
            "model_path": str(nn_path),
            "config": {
                "hidden_dim": args.nn_hidden_dim,
                "n_layers": args.nn_n_layers,
                "epochs": args.nn_epochs,
                "batch_size": args.nn_batch_size,
                "lr": args.nn_lr,
                "device": args.device,
            },
            "epoch_losses": nn_model._losses,
            **nn_metrics,
        }

        # Headline comparison: pick the better recall@10 as the
        # "best" model. Tie-break: lower ECE.
        if (
            nn_metrics["recall_at_10"] > baseline_metrics["recall_at_10"]
            or (
                nn_metrics["recall_at_10"] == baseline_metrics["recall_at_10"]
                and nn_metrics["ece"] < baseline_metrics["ece"]
            )
        ):
            best = "nn"
        else:
            best = "baseline"
        report["best_model"] = best
        print(f"\nBest model by recall@10: {best}")
    else:
        report["best_model"] = "baseline"

    with open(args.report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=_json_default)
    print(f"\nValidation report written to {args.report_path}")

    return 0


def _json_default(o):
    """JSON encoder for numpy scalars and other non-trivial types."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Cannot serialize {type(o).__name__}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
