"""Train the value+policy network from saved self-play data and
register it as a new versioned model in the registry.

Loads every ``*.npz`` in ``--data-dir``, fits the ``_ValuePolicyMLP``
(or value-only ``_ValueMLP`` if no policy supervision in the data),
registers as ``v{N+1}`` under ``--registry-root`` (default
``trained_weights/``) with a metadata sidecar capturing training
hyperparameters, loss history, and the data sources used. Uses CUDA
when available.

Usage::

    python -m mtg_bot.cli train --data-dir training_data/ --epochs 100

    # Custom registry location
    python -m mtg_bot.cli train --data-dir training_data/ \\
        --registry-root experiments/run3/weights --epochs 50

The version ID is auto-assigned (v1, v2, ...). The trained network
loads via ``NNEvaluator(weights_path=registry.weights_path("v3"))``
or via the eval / capture / iterate subcommands by version label.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from mtg_bot.cli.runs import client as _runs_client
from mtg_bot.cli.runs import lifecycle as _lifecycle
from mtg_bot.features import FEATURE_DIM
from mtg_bot.search.nn_evaluator import (
    ARCHITECTURE_SHARED,
    ARCHITECTURE_STRUCTURED,
    HIDDEN_SIZES,
    SUPPORTED_ARCHITECTURES,
)
from mtg_bot.training import (
    auto_device,
    load_all_datasets,
    load_structured_dataset,
    train_structured_model,
    train_value_network,
)
from mtg_bot.training.registry import ModelMetadata, Registry


# Regex matching the iterate cycle run_id format. When ``mtg_bot
# iterate`` invokes train via subprocess it threads the cycle_id
# into ``--notes`` so the resulting training run can be linked back
# to its parent iterate cycle row.
_ITER_CYCLE_RE = re.compile(r"\b(iter_\d+_cycle)\b")


def _now_stamp() -> str:
    """Compact UTC ISO-8601 timestamp suitable for embedding in
    run_ids / filenames (no colons, no fractional seconds, trailing
    ``Z``). Matches the format ``mtg_bot iterate`` uses for its own
    launch IDs (:func:`mtg_bot.cli.iterate._now_stamp`)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_train_run_id(version_label: str, stamp: str) -> str:
    """Compose the standalone-train run_id from a registry version
    label + a UTC stamp.

    The leading ``train_`` namespace plus the trailing timestamp keeps
    each ``mtg_bot train`` invocation unique even when the same
    registry version label is recycled (fresh checkout reusing
    ``vN``, manual recovery train after a failed attempt, ...). See
    ``feature/unique-train-run-id`` for the bug this resolves.
    """
    return f"train_{version_label}_{stamp}"


def _parent_run_id_from_notes(notes: str) -> Optional[str]:
    """Best-effort extract an iterate cycle_id from a ``--notes``
    string. Returns ``None`` when nothing matches — standalone
    ``mtg_bot train`` invocations have no parent."""
    if not notes:
        return None
    match = _ITER_CYCLE_RE.search(notes)
    return match.group(1) if match else None


def _downsample_one_legal_rows(
    features: np.ndarray,
    outcomes: np.ndarray,
    policy_targets: np.ndarray,
    action_masks: np.ndarray,
    *,
    keep_frac: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int]:
    """Drop a fraction of one-legal-action supervised rows.

    Why: when ~84% of supervised rows have exactly one legal action,
    their CE loss is trivially 0 and they dominate the policy-head
    gradient with zero learning signal. Downsampling them lets the
    sparse multi-legal rows (where MCTS visit-count distribution
    actually carries signal) drive the gradient.

    A row is "one-legal-supervised" iff
    ``action_mask.sum(-1) == 1`` AND ``policy_target.sum(-1) > 0.5``.
    Value-only rows (no policy supervision) are kept fully — they
    contribute nothing to the policy gradient anyway.

    Returns the downsampled (features, outcomes, policy_targets,
    action_masks) along with (n_one_legal_total, n_one_legal_kept)
    for logging.
    """
    if not (0.0 < keep_frac <= 1.0):
        raise ValueError(
            f"keep_frac must be in (0.0, 1.0]; got {keep_frac}"
        )

    has_policy = policy_targets.sum(axis=-1) > 0.5
    n_legal = action_masks.sum(axis=-1)
    one_legal_supervised = has_policy & (n_legal == 1)
    n_one_legal_total = int(one_legal_supervised.sum())

    if keep_frac >= 1.0 or n_one_legal_total == 0:
        return (
            features,
            outcomes,
            policy_targets,
            action_masks,
            n_one_legal_total,
            n_one_legal_total,
        )

    rng = np.random.default_rng(seed)
    # Build keep-mask: every non-one-legal-supervised row stays;
    # one-legal-supervised rows pass with probability ``keep_frac``.
    keep_mask = np.ones(features.shape[0], dtype=bool)
    one_legal_idx = np.flatnonzero(one_legal_supervised)
    n_keep = int(round(n_one_legal_total * keep_frac))
    if n_keep < n_one_legal_total:
        # rng.permutation is reproducible given the seed.
        shuffled = rng.permutation(one_legal_idx)
        drop = shuffled[n_keep:]
        keep_mask[drop] = False

    return (
        features[keep_mask],
        outcomes[keep_mask],
        policy_targets[keep_mask],
        action_masks[keep_mask],
        n_one_legal_total,
        n_keep,
    )


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


def main(argv=None) -> None:
    # Argparse + training-driver body; previously script-level code
    # under ``scripts/train_nn.py``. The ``_downsample_one_legal_rows``
    # helper is unit-tested directly; this body is mostly argparse
    # plumbing + a single ``train_value_network(...)`` dispatch. The
    # lifecycle wiring (start_run / push_progress / finish_run) is
    # pinned by ``tests/cli/test_train_runs_db.py``.
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
            "<cwd>/training_progress/train_<version>_<stamp>.json — "
            "<version> is the next registry version (peeked, not "
            "reserved) and <stamp> is a UTC compact-ISO start "
            "timestamp (YYYYMMDDThhmmssZ) so two standalone trains "
            "of the same version land in separate files. Pass an "
            "explicit path to override; pass an empty string to "
            "disable progress emission entirely. (Iterate threads its "
            "own iter-namespaced --progress-path through, so this "
            "default only governs standalone callers.)"
        ),
    )
    parser.add_argument(
        "--compile", dest="compile_model", action="store_true",
        help=(
            "Wrap the model in ``torch.compile`` (PyTorch 2.x) — "
            "fuses kernels and removes per-op interpreter overhead. "
            "Pays a 10-30 s compile cost on the first batch; net "
            "win over 100 epochs is typically 1.5-3x. Off by "
            "default (compile path can be flaky on edge-case ops); "
            "recommended on for any real GPU training run."
        ),
    )
    parser.add_argument(
        "--hidden-sizes", default=None,
        help=(
            "Comma-separated trunk shape (e.g. '1024,1024,512') "
            "overriding the registry-baseline (128, 128, 64). "
            "Saved into the version's metadata.json so loading via "
            "--version (in evaluate_nn.py / iterate_alphazero.py) "
            "rebuilds an evaluator at the matching shape. Useful "
            "for capacity-experiment training runs without making "
            "old versions unloadable."
        ),
    )
    parser.add_argument(
        "--architecture",
        choices=list(SUPPORTED_ARCHITECTURES),
        default=ARCHITECTURE_SHARED,
        help=(
            "Dual-head model class: 'shared' (default, back-compat "
            "with v1-v15) uses a single trunk feeding both value and "
            "policy heads. 'separate' instantiates parallel value_"
            "trunk + policy_trunk MLPs, eliminating the shared-"
            "bottleneck competition between heads (the value head's "
            "louder gradient saturates a shared trunk's representation "
            "and crowds the policy head's branchy-row signal out — see "
            "iter_002 v13 training analysis). Switching from 'shared' "
            "to 'separate' (or vice versa) invalidates the existing "
            "v-chain — the new architecture must train fresh. The "
            "choice is recorded in metadata.json so loaders can "
            "dispatch."
        ),
    )
    parser.add_argument(
        "--policy-hidden-sizes", default=None,
        help=(
            "Optional comma-separated trunk shape for the policy_trunk "
            "when --architecture=separate. Defaults to mirror "
            "--hidden-sizes. Useful for asymmetric capacity allocation "
            "(e.g. trim the policy trunk if VRAM matters)."
        ),
    )
    parser.add_argument(
        "--policy-loss-weight", type=float, default=1.0,
        help=(
            "Coefficient on the policy-head CE in the combined loss "
            "(total = value_loss + policy_loss_weight * policy_loss). "
            "Default 1.0 lets value_loss (~0.5 at epoch 1) dominate "
            "policy_loss (~0.16 at epoch 1) ~3:1 — the policy head "
            "plateaus at the floor set by ~84%% one-legal-action rows "
            "(observed in iter_002 v13 training). Bump to 3.0-10.0 "
            "to give the policy head enough gradient on the ~2%% of "
            "branchy rows where it actually has signal to learn."
        ),
    )
    parser.add_argument(
        "--early-stop-patience", type=int, default=3,
        help=(
            "Stop training after the val loss has failed to improve "
            "for this many consecutive epochs. Default 3 — the D3 "
            "epochs-ablation (docs/SCALING_DIAGNOSTICS.md) showed v5 "
            "was undertrained at 5 epochs / patience=None; re-training "
            "with epochs=20 + patience=3 cleared the eval gate against "
            "v5 (Wilson-LB 0.546). To run every epoch unconditionally, "
            "pass a patience >= --epochs. Must be a positive int."
        ),
    )
    parser.add_argument(
        "--num-workers", type=int, default=0,
        help=(
            "DataLoader worker process count. Default 0 (main thread) "
            "is fine for smoke tests but starves the GPU on real iter "
            "data (~9%% GPU util at 7M+ samples). Production callers "
            "should pass >= 4 so DataLoader prefetches batches in "
            "parallel; persistent_workers=True is enabled automatically "
            "when num_workers > 0 so the dataset is pickled once at "
            "epoch 0 instead of every epoch."
        ),
    )
    parser.add_argument(
        "--window-recent", type=int, default=None,
        help=(
            "If set, load only the N most-recent (by mtime) .npz "
            "files from --data-dir instead of the entire directory. "
            "Default None = load every file. As iterate_data/ "
            "accumulates over many iterations, training on the "
            "entire history slows linearly with size and biases "
            "early data; capping to the latest N files keeps "
            "training fast and weighted toward fresh self-play. "
            "Files greater than the available count loads them "
            "all (no error)."
        ),
    )
    parser.add_argument(
        "--one-legal-keep-frac", type=float, default=1.0,
        help=(
            "Fraction of one-legal-action supervised rows to keep "
            "before training (default 1.0 = no downsample). When "
            "<1.0, only this fraction of rows whose action_mask has "
            "exactly one legal slot AND that carry policy supervision "
            "are retained; multi-legal supervised rows and value-only "
            "rows are kept fully. The companion fix to "
            "--policy-loss-weight: rather than reweighting the loss, "
            "rebalances the dataset so the policy head's gradient is "
            "dominated by branchy rows with real visit-count signal. "
            "At 0.1, the ~84%% one-legal share drops to ~8.4%% so "
            "branchy supervised rows become the majority. Seeded "
            "from --seed for reproducibility. Must be in (0.0, 1.0]."
        ),
    )
    parser.add_argument(
        "--action-encoding-version",
        choices=["positional_v1", "canonical_v2"],
        default="positional_v1",
        help=(
            "Action-encoding slot mapping convention. "
            "'positional_v1' (default, back-compat with v13/v15/v16) "
            "uses raw card.id-positional slots. 'canonical_v2' sorts "
            "hand/graveyard/exile by (printing.name, modifier_tuple, "
            "card.id) before slot assignment so two canonically-"
            "equivalent states share their slot mappings. The choice "
            "is recorded in metadata.json so loaders thread it through "
            "to NNEvaluator at inference. Switching versions is a "
            "v-chain break — old weights cannot be reused."
        ),
    )
    # Structured-architecture (Step 1) hyperparameters. Only consumed
    # when ``--architecture structured``; the flat-feature path
    # ignores them. Defaults mirror
    # :class:`StructuredModelConfig`'s defaults so the structured
    # trunk built here matches the skeleton called out in the
    # roadmap.
    parser.add_argument(
        "--emb-dim", type=int, default=None,
        help=(
            "Structured-trunk: per-token embedding dimension. "
            "Default None defers to StructuredModelConfig (128)."
        ),
    )
    parser.add_argument(
        "--n-heads", type=int, default=None,
        help=(
            "Structured-trunk: transformer attention heads. "
            "Default None defers to StructuredModelConfig (4)."
        ),
    )
    parser.add_argument(
        "--n-layers", type=int, default=None,
        help=(
            "Structured-trunk: encoder layer count. "
            "Default None defers to StructuredModelConfig (2)."
        ),
    )
    parser.add_argument(
        "--hidden-dim", type=int, default=None,
        help=(
            "Structured-trunk: MLP hidden dim inside the encoder. "
            "Default None defers to StructuredModelConfig (256)."
        ),
    )
    parser.add_argument(
        "--action-history-n", type=int, default=None,
        help=(
            "Structured-trunk: last-N action-history window. "
            "Default None defers to StructuredModelConfig (32)."
        ),
    )
    args = parser.parse_args(argv)
    # Structured architecture has a different data pipeline + model
    # + loss shape from the flat-feature MLP trainers; dispatch
    # before any of the flat-feature-specific argument validation.
    if args.architecture == ARCHITECTURE_STRUCTURED:
        _main_structured(args, parser)
        return
    if not (0.0 < args.one_legal_keep_frac <= 1.0):
        parser.error(
            "--one-legal-keep-frac must be in (0.0, 1.0]; got "
            f"{args.one_legal_keep_frac}"
        )
    if args.early_stop_patience is not None and args.early_stop_patience < 1:
        parser.error(
            "--early-stop-patience must be a positive int (>= 1); got "
            f"{args.early_stop_patience}"
        )
    if args.window_recent is not None and args.window_recent <= 0:
        parser.error(
            "--window-recent must be a positive integer; got "
            f"{args.window_recent}"
        )
    if args.hidden_sizes is not None:
        try:
            hidden_sizes = tuple(
                int(x.strip()) for x in args.hidden_sizes.split(",")
            )
        except ValueError as exc:
            sys.exit(f"--hidden-sizes parse error: {exc}")
        if not hidden_sizes:
            sys.exit("--hidden-sizes must list at least one layer")
    else:
        hidden_sizes = HIDDEN_SIZES

    policy_hidden_sizes: tuple[int, ...] | None = None
    if args.policy_hidden_sizes is not None:
        if args.architecture != "separate":
            sys.exit(
                "--policy-hidden-sizes only applies when "
                "--architecture=separate"
            )
        try:
            policy_hidden_sizes = tuple(
                int(x.strip()) for x in args.policy_hidden_sizes.split(",")
            )
        except ValueError as exc:
            sys.exit(f"--policy-hidden-sizes parse error: {exc}")
        if not policy_hidden_sizes:
            sys.exit(
                "--policy-hidden-sizes must list at least one layer"
            )

    if not args.data_dir.is_dir():
        sys.exit(f"--data-dir {args.data_dir} is not a directory")

    print(f"# Loading data from {args.data_dir}")
    if args.window_recent is not None:
        print(
            f"# Window-recent: loading at most {args.window_recent} "
            f"most-recent files by mtime"
        )
    # Always pull policy supervision arrays. ``include_policy=True``
    # zero-pads value-only files so the concatenated arrays align —
    # mixed dirs (some pre-A2.3 .npz, some post-A2.3) load cleanly.
    features, outcomes, policy_targets, action_masks = (
        load_all_datasets(
            args.data_dir,
            include_policy=True,
            max_files=args.window_recent,
        )
    )
    if features.shape[0] == 0:
        sys.exit(
            f"No .npz files found in {args.data_dir}. Generate data "
            f"with scripts/generate_training_data.py first."
        )
    # Reflect the actually-loaded subset in metadata (not every
    # file in the dir) when --window-recent is in play; otherwise
    # this is identical to the all-files glob.
    all_npz = sorted(args.data_dir.glob("*.npz"))
    if args.window_recent is not None and len(all_npz) > args.window_recent:
        loaded_paths = sorted(
            all_npz, key=lambda p: p.stat().st_mtime, reverse=True,
        )[:args.window_recent]
        data_files = sorted(p.name for p in loaded_paths)
    else:
        data_files = [p.name for p in all_npz]

    if args.one_legal_keep_frac < 1.0:
        n_before = features.shape[0]
        (
            features,
            outcomes,
            policy_targets,
            action_masks,
            n_one_legal_total,
            n_one_legal_kept,
        ) = _downsample_one_legal_rows(
            features, outcomes, policy_targets, action_masks,
            keep_frac=args.one_legal_keep_frac,
            seed=args.seed,
        )
        print(
            f"[train_nn] downsampled one-legal rows: kept "
            f"{n_one_legal_kept} of {n_one_legal_total} "
            f"(kept_frac={args.one_legal_keep_frac}); "
            f"final dataset: {features.shape[0]} rows "
            f"(was {n_before})",
            file=sys.stderr,
        )

    n_policy_rows = int(
        (policy_targets.sum(axis=-1) > 0.5).sum()
    )
    has_any_policy = n_policy_rows > 0
    print(
        f"# {features.shape[0]} samples from {len(data_files)} files, "
        f"FEATURE_DIM={features.shape[1]}"
    )
    print(
        f"# Policy supervision: {n_policy_rows} / "
        f"{features.shape[0]} rows "
        f"({n_policy_rows / features.shape[0]:.1%}). Mode: "
        f"{'AlphaZero (dual-head)' if has_any_policy else 'value-only'}"
    )

    device = args.device or auto_device()
    print(f"# Training on {device} for {args.epochs} epochs")

    # Resolve the progress-file path BEFORE training so we can
    # register it as a ``progress_json`` artifact on the run row.
    # We peek at the next version ID rather than reserve it — the
    # registry assigns sequentially at register time, so as long as
    # nobody else trains concurrently the peek value matches the
    # eventual assignment.
    #
    # Phase 3 cutover: the JSON file itself is no longer written
    # (the UI reads runs.db directly). The path string survives as
    # an artifact pointer for historical-compatibility reasons —
    # downstream tooling that walks ``run_artifacts`` keeps seeing
    # a ``progress_json`` entry per training run, even though that
    # file no longer lands on disk for new runs.
    registry = Registry(args.registry_root)
    peeked_version = registry.next_version_id()
    # The run_id salts the registry version label with the start
    # timestamp so re-running ``mtg_bot train`` against the same
    # version label (fresh checkout, manual recovery train, ...) lands
    # a NEW ``runs.run_id`` row rather than colliding with the prior
    # row's UNIQUE constraint. Iterate's subprocess-invoked train
    # supplies its own iter-namespaced run_id via the parent lifecycle
    # CM; this build only governs the standalone-train row.
    train_run_id = _build_train_run_id(peeked_version, _now_stamp())
    if args.progress_path is None:
        progress_dir = Path("training_progress")
        progress_dir.mkdir(parents=True, exist_ok=True)
        # Default progress JSON tracks the run_id (not just the
        # version label) so two concurrent / consecutive standalone
        # trains of the same version land in separate files. Iterate's
        # explicit ``--progress-path`` still wins via the elif/else
        # branches below.
        progress_path: Path | None = progress_dir / f"{train_run_id}.json"
    elif str(args.progress_path) == "":
        progress_path = None
    else:
        progress_path = args.progress_path
        progress_path.parent.mkdir(parents=True, exist_ok=True)

    # Phase 1 dual-write: alongside the existing JSON progress
    # emission, push start_run / per-epoch progress + events /
    # finish_run into the SQLite run DB. Lifecycle helpers are no-ops
    # when neither MTG_BOT_RUN_DB_PATH nor MTG_BOT_RUN_DB_URL is set,
    # so this stays additive on a fresh clone.
    train_config = {
        "kind": "training",
        "data_dir": str(args.data_dir),
        "registry_root": str(args.registry_root),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "val_split": args.val_split,
        "device": device,
        "seed": args.seed,
        "notes": args.notes,
        "compile_model": args.compile_model,
        "hidden_sizes": list(hidden_sizes),
        "policy_hidden_sizes": (
            list(policy_hidden_sizes)
            if policy_hidden_sizes is not None else None
        ),
        "architecture": args.architecture,
        "policy_loss_weight": args.policy_loss_weight,
        "early_stop_patience": args.early_stop_patience,
        "window_recent": args.window_recent,
        "one_legal_keep_frac": args.one_legal_keep_frac,
        "action_encoding_version": args.action_encoding_version,
        "progress_path": (
            str(progress_path) if progress_path is not None else None
        ),
        "has_any_policy": has_any_policy,
        "n_samples": int(features.shape[0]),
        "n_policy_rows": n_policy_rows,
    }
    parent_run_id = _parent_run_id_from_notes(args.notes)

    def _on_epoch(payload: dict) -> None:
        """Per-epoch sink: push a ``run_progress`` upsert keyed by
        the run_id (no shard_label = aggregate row) and append one
        ``epoch_completed`` event carrying the per-epoch loss
        components. ``n_games_done`` reuses the existing field as
        ``current_epoch`` (mirrors how the JSON producer overloads
        the same column for training kind)."""
        _runs_client.push_progress(
            train_run_id,
            n_games_done=int(payload["epoch"]),
            n_games_total=int(payload["total_epochs"]),
            elapsed_seconds=float(payload["elapsed_seconds"]),
            extra={
                "current_epoch": int(payload["epoch"]),
                "total_epochs": int(payload["total_epochs"]),
                "train_loss": payload["train_loss"],
                "val_loss": payload["val_loss"],
                "train_value_loss": payload["train_value_loss"],
                "val_value_loss": payload["val_value_loss"],
                "train_policy_loss": payload["train_policy_loss"],
                "val_policy_loss": payload["val_policy_loss"],
                "status": payload["status"],
            },
        )
        _runs_client.push_event(
            train_run_id,
            event_type="epoch_completed",
            payload={
                "epoch": int(payload["epoch"]),
                "train_loss": payload["train_loss"],
                "val_loss": payload["val_loss"],
                "train_value_loss": payload["train_value_loss"],
                "val_value_loss": payload["val_value_loss"],
                "train_policy_loss": payload["train_policy_loss"],
                "val_policy_loss": payload["val_policy_loss"],
            },
        )

    # Train into a temp file, then hand off to the registry which
    # copies the bytes into the versioned directory. The DB
    # ``runs.label`` column carries the registry version label
    # (e.g. ``v10``) so the UI can still group successive train
    # attempts of the same version together; ``run_id`` is the unique
    # timestamped form so the UNIQUE constraint never collides.
    with tempfile.TemporaryDirectory() as tmp, _lifecycle.run_lifecycle(
        run_id=train_run_id,
        kind="training",
        config=train_config,
        progress_json_path=progress_path,
        parent_run_id=parent_run_id,
        label=peeked_version,
    ):
        tmp_weights = Path(tmp) / "weights.pt"
        started = time.perf_counter()
        # Dispatch on schema: if any row carries policy supervision,
        # forward the policy_targets / action_masks arrays so the
        # trainer trains the dual-head ``_ValuePolicyMLP``. Otherwise
        # train the value-only ``_ValueMLP`` (existing behavior; old
        # v1/v2 weights still load via ``NNEvaluator()`` default).
        train_kwargs: dict = {
            "features": features,
            "outcomes": outcomes,
            "weights_out_path": tmp_weights,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.lr,
            "val_split": args.val_split,
            "device": device,
            "rng_seed": args.seed,
            # Phase 3 cutover: the per-epoch JSON dual-write is dead I/O
            # now that the UI reads runs.db directly. ``_on_epoch``
            # pushes the same per-epoch progress + ``epoch_completed``
            # event into the DB. Pass ``progress_path=None`` so
            # train_value_network skips its ``atomic_write_json`` calls;
            # ``progress_path`` (the path string) is still registered as
            # a ``progress_json`` artifact via run_lifecycle for
            # historical compatibility.
            "progress_path": None,
            "run_id": train_run_id,
            "notes": args.notes,
            "compile_model": args.compile_model,
            "hidden_sizes": hidden_sizes,
            "early_stop_patience": args.early_stop_patience,
            "epoch_callback": _on_epoch,
        }
        if has_any_policy:
            train_kwargs["policy_targets"] = policy_targets
            train_kwargs["action_masks"] = action_masks
            train_kwargs["policy_loss_weight"] = args.policy_loss_weight
            train_kwargs["architecture"] = args.architecture
            if policy_hidden_sizes is not None:
                train_kwargs["policy_hidden_sizes"] = policy_hidden_sizes
        history = train_value_network(**train_kwargs)
        elapsed = time.perf_counter() - started

        metadata = ModelMetadata(
            version="",  # filled in by Registry.register
            created_at="",  # filled in by Registry.register
            feature_dim=FEATURE_DIM,
            hidden_sizes=list(hidden_sizes),
            with_policy=has_any_policy,
            # Architecture is meaningful only for dual-head training
            # (``has_any_policy=True``); for value-only runs we still
            # default to "shared" so the field is present and stable.
            architecture=(
                args.architecture if has_any_policy
                else ARCHITECTURE_SHARED
            ),
            action_encoding_version=args.action_encoding_version,
            training={
                "data_dir": str(args.data_dir),
                "data_files": data_files,
                "n_samples": int(features.shape[0]),
                "n_policy_rows": n_policy_rows,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "learning_rate": args.lr,
                "val_split": args.val_split,
                "device": device,
                "rng_seed": args.seed,
                "duration_seconds": elapsed,
                "one_legal_keep_frac": args.one_legal_keep_frac,
                "window_recent": args.window_recent,
                "policy_hidden_sizes": (
                    list(policy_hidden_sizes)
                    if policy_hidden_sizes is not None else None
                ),
                "early_stop_patience": args.early_stop_patience,
                "epochs_trained": len(history.train_losses),
            },
            training_history={
                "train_losses": history.train_losses,
                "val_losses": history.val_losses,
                "train_value_losses": history.train_value_losses,
                "val_value_losses": history.val_value_losses,
                "train_policy_losses": history.train_policy_losses,
                "val_policy_losses": history.val_policy_losses,
                # ``--epochs 0`` (smoke runs that just want a fresh
                # registered version with no training) produces empty
                # loss lists; guard the ``[-1]`` accesses so the post-
                # train summary doesn't IndexError.
                "final_train_loss": (
                    history.train_losses[-1]
                    if history.train_losses else None
                ),
                "final_val_loss": (
                    history.val_losses[-1]
                    if history.val_losses else None
                ),
                "best_val_loss": history.best_val_loss,
                "best_val_epoch": history.best_val_epoch,
            },
            git_commit=_git_commit(),
            notes=args.notes,
        )
        version = registry.register(tmp_weights, metadata)

        # Final post-train DB writes (still inside the lifecycle
        # context so any failure propagates as status=failed):
        #   1. Aggregate row carries the full training_history blob
        #      as ``extra_json["training_history"]``. A sibling slice
        #      may later add a dedicated ``training_history_json``
        #      column to ``runs``; until then this is the agreed
        #      stash location.
        #   2. Register the registered weights file as an artifact
        #      so the UI / downstream tooling can locate it without
        #      walking the registry tree.
        final_history = {
            "train_losses": list(history.train_losses),
            "val_losses": list(history.val_losses),
            "train_value_losses": list(history.train_value_losses),
            "val_value_losses": list(history.val_value_losses),
            "train_policy_losses": list(history.train_policy_losses),
            "val_policy_losses": list(history.val_policy_losses),
            "best_val_loss": history.best_val_loss,
            "best_val_epoch": history.best_val_epoch,
            "epochs_trained": len(history.train_losses),
        }
        if history.train_losses:
            final_history["final_train_loss"] = history.train_losses[-1]
        if history.val_losses:
            final_history["final_val_loss"] = history.val_losses[-1]
        _runs_client.push_progress(
            train_run_id,
            n_games_done=len(history.train_losses),
            n_games_total=args.epochs,
            elapsed_seconds=elapsed,
            extra={
                "training_history": final_history,
                "registered_version": version,
            },
        )
        weights_path = registry.weights_path(version)
        try:
            weights_bytes = weights_path.stat().st_size
        except OSError:
            weights_bytes = None
        _runs_client.push_artifact(
            train_run_id,
            artifact_type="weights",
            path=str(weights_path),
            bytes_=weights_bytes,
        )

    print(f"\n# Done in {elapsed:.1f}s. Registered as {version}.")
    print(f"# Weights:  {registry.weights_path(version)}")
    # ``--epochs 0`` short-circuits the post-train summary block: the
    # registered version exists, but there were no epochs to report
    # losses for. Don't IndexError on the empty history lists.
    if history.train_losses:
        print(f"# Final train loss: {history.train_losses[-1]:.4f}")
        print(f"# Final val loss:   {history.val_losses[-1]:.4f}")
        if has_any_policy:
            print(
                f"#   value:  train={history.train_value_losses[-1]:.4f} "
                f"val={history.val_value_losses[-1]:.4f}"
            )
            print(
                f"#   policy: train={history.train_policy_losses[-1]:.4f} "
                f"val={history.val_policy_losses[-1]:.4f}"
            )
        print(
            f"# Best val loss: {history.best_val_loss:.4f} "
            f"at epoch {history.best_val_epoch}"
        )
    else:
        print("# epochs_trained=0; no per-epoch losses to report")


def _main_structured(args, parser) -> None:
    """Train + register a :class:`StructuredModel` checkpoint.

    Reached when ``--architecture structured`` is passed. Loads the
    structured-token npz files from ``--data-dir``, runs
    :func:`train_structured_model`, and registers the result with
    ``metadata.architecture='structured'`` so loaders dispatch to the
    transformer trunk at inference time.

    The flat-feature flags (``--one-legal-keep-frac``,
    ``--window-recent``, ``--policy-hidden-sizes``,
    ``--compile``, ``--hidden-sizes``) DO NOT apply to the
    structured trainer — its capacity is set by
    :class:`StructuredModelConfig`'s defaults today, not by the
    flat MLP's trunk shape. We accept them on the namespace but
    ignore (with a stderr note when they were set non-default) rather
    than erroring so iterate's shared CLI shim isn't forced to fork
    its arg-construction path.
    """
    from mtg_bot.training.structured_model import StructuredModelConfig

    if not args.data_dir.is_dir():
        sys.exit(f"--data-dir {args.data_dir} is not a directory")
    if args.early_stop_patience is not None and args.early_stop_patience < 1:
        parser.error(
            "--early-stop-patience must be a positive int (>= 1); got "
            f"{args.early_stop_patience}"
        )
    if args.window_recent is not None and args.window_recent <= 0:
        parser.error(
            "--window-recent must be a positive integer; got "
            f"{args.window_recent}"
        )

    print(
        f"# Structured-trainer: loading data from {args.data_dir}"
    )
    try:
        dataset = load_structured_dataset(
            args.data_dir,
            max_files=args.window_recent,
        )
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    except ValueError as exc:
        # Surface the data-pipeline issue verbatim — most likely "npz
        # missing structured arrays" which means the data_gen run
        # wasn't invoked with structured_tokens=True.
        sys.exit(
            f"--architecture structured requires npz files written "
            f"with structured_tokens=True. {exc}"
        )

    n_samples = len(dataset)
    if n_samples == 0:
        sys.exit(f"No samples found in {args.data_dir}")
    all_npz = sorted(args.data_dir.glob("*.npz"))
    if args.window_recent is not None and len(all_npz) > args.window_recent:
        loaded_paths = sorted(
            all_npz, key=lambda p: p.stat().st_mtime, reverse=True,
        )[:args.window_recent]
        data_files = sorted(p.name for p in loaded_paths)
    else:
        data_files = [p.name for p in all_npz]

    device = args.device or auto_device()
    print(
        f"# Structured-trainer: {n_samples} samples from "
        f"{len(data_files)} files; device={device}; "
        f"epochs={args.epochs} batch={args.batch_size}"
    )

    registry = Registry(args.registry_root)
    peeked_version = registry.next_version_id()
    # Salt the run_id with the start timestamp so the standalone-train
    # row is unique per invocation — see :func:`_build_train_run_id`'s
    # docstring + the flat-feature ``main()`` block above for the
    # ``run_id == label`` UNIQUE-collision bug this resolves.
    train_run_id = _build_train_run_id(peeked_version, _now_stamp())
    if args.progress_path is None:
        progress_dir = Path("training_progress")
        progress_dir.mkdir(parents=True, exist_ok=True)
        progress_path: Path | None = progress_dir / f"{train_run_id}.json"
    elif str(args.progress_path) == "":
        progress_path = None
    else:
        progress_path = args.progress_path
        progress_path.parent.mkdir(parents=True, exist_ok=True)
    if progress_path is not None:
        print(f"# Progress JSON: {progress_path}")

    # Apply any explicit hyperparam overrides from the CLI; defaults
    # of ``None`` defer to StructuredModelConfig's own defaults (the
    # roadmap-pinned 128/4/2/256/32 set).
    structured_overrides: dict = {}
    if args.emb_dim is not None:
        structured_overrides["emb_dim"] = args.emb_dim
    if args.n_heads is not None:
        structured_overrides["n_heads"] = args.n_heads
    if args.n_layers is not None:
        structured_overrides["n_layers"] = args.n_layers
    if args.hidden_dim is not None:
        structured_overrides["hidden_dim"] = args.hidden_dim
    if args.action_history_n is not None:
        structured_overrides["action_history_n"] = args.action_history_n
    structured_config = StructuredModelConfig(**structured_overrides)

    train_config = {
        "kind": "training",
        "architecture": ARCHITECTURE_STRUCTURED,
        "data_dir": str(args.data_dir),
        "registry_root": str(args.registry_root),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "val_split": args.val_split,
        "device": device,
        "seed": args.seed,
        "notes": args.notes,
        "n_samples": n_samples,
        "window_recent": args.window_recent,
        "action_encoding_version": args.action_encoding_version,
        "policy_loss_weight": args.policy_loss_weight,
        "early_stop_patience": args.early_stop_patience,
        "progress_path": (
            str(progress_path) if progress_path is not None else None
        ),
        "structured_config": {
            "emb_dim": structured_config.emb_dim,
            "n_heads": structured_config.n_heads,
            "n_layers": structured_config.n_layers,
            "hidden_dim": structured_config.hidden_dim,
            "action_history_n": structured_config.action_history_n,
            "n_printings": structured_config.n_printings,
        },
    }
    parent_run_id = _parent_run_id_from_notes(args.notes)

    def _on_epoch(payload: dict) -> None:
        _runs_client.push_progress(
            train_run_id,
            n_games_done=int(payload["epoch"]),
            n_games_total=int(payload["total_epochs"]),
            elapsed_seconds=float(payload["elapsed_seconds"]),
            extra={
                "current_epoch": int(payload["epoch"]),
                "total_epochs": int(payload["total_epochs"]),
                "train_loss": payload["train_loss"],
                "val_loss": payload["val_loss"],
                "train_value_loss": payload["train_value_loss"],
                "val_value_loss": payload["val_value_loss"],
                "train_policy_loss": payload["train_policy_loss"],
                "val_policy_loss": payload["val_policy_loss"],
                "status": payload["status"],
                "architecture": ARCHITECTURE_STRUCTURED,
            },
        )
        _runs_client.push_event(
            train_run_id,
            event_type="epoch_completed",
            payload={
                "epoch": int(payload["epoch"]),
                "train_loss": payload["train_loss"],
                "val_loss": payload["val_loss"],
                "train_value_loss": payload["train_value_loss"],
                "val_value_loss": payload["val_value_loss"],
                "train_policy_loss": payload["train_policy_loss"],
                "val_policy_loss": payload["val_policy_loss"],
            },
        )

    with tempfile.TemporaryDirectory() as tmp, _lifecycle.run_lifecycle(
        run_id=train_run_id,
        kind="training",
        config=train_config,
        progress_json_path=progress_path,
        parent_run_id=parent_run_id,
        label=peeked_version,
    ):
        tmp_weights = Path(tmp) / "weights.pt"
        started = time.perf_counter()
        history = train_structured_model(
            dataset,
            weights_out_path=tmp_weights,
            config=structured_config,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.lr,
            val_split=args.val_split,
            device=device,
            rng_seed=args.seed,
            progress_path=progress_path,
            run_id=train_run_id,
            notes=args.notes,
            policy_loss_weight=args.policy_loss_weight,
            epoch_callback=_on_epoch,
            # ``--compile`` is opt-in (action="store_true"). Without
            # this passthrough the structured trainer's internal
            # default fires (``compile_model=None`` → True on CUDA),
            # which crashes on Windows-cu128 (Triton not packaged)
            # because the failure surfaces lazily on the first forward,
            # AFTER the try/except around ``torch.compile()`` itself.
            # The flat-feature train path already passes this through
            # (lines 549, 646 above); structured was the outlier.
            compile_model=args.compile_model,
            early_stop_patience=args.early_stop_patience,
            num_workers=args.num_workers,
        )
        elapsed = time.perf_counter() - started

        metadata = ModelMetadata(
            version="",
            created_at="",
            feature_dim=FEATURE_DIM,  # legacy field; ignored for structured
            hidden_sizes=[],
            with_policy=True,
            architecture=ARCHITECTURE_STRUCTURED,
            action_encoding_version=args.action_encoding_version,
            training={
                "data_dir": str(args.data_dir),
                "data_files": data_files,
                "n_samples": n_samples,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "learning_rate": args.lr,
                "val_split": args.val_split,
                "device": device,
                "rng_seed": args.seed,
                "duration_seconds": elapsed,
                "window_recent": args.window_recent,
                "early_stop_patience": args.early_stop_patience,
                "epochs_trained": len(history.train_losses),
                "structured_config": train_config["structured_config"],
            },
            training_history={
                "train_losses": history.train_losses,
                "val_losses": history.val_losses,
                "train_value_losses": history.train_value_losses,
                "val_value_losses": history.val_value_losses,
                "train_policy_losses": history.train_policy_losses,
                "val_policy_losses": history.val_policy_losses,
                "final_train_loss": (
                    history.train_losses[-1]
                    if history.train_losses else None
                ),
                "final_val_loss": (
                    history.val_losses[-1]
                    if history.val_losses else None
                ),
                "best_val_loss": history.best_val_loss,
                "best_val_epoch": history.best_val_epoch,
            },
            git_commit=_git_commit(),
            notes=args.notes,
        )
        version = registry.register(tmp_weights, metadata)

        final_history = {
            "train_losses": list(history.train_losses),
            "val_losses": list(history.val_losses),
            "train_value_losses": list(history.train_value_losses),
            "val_value_losses": list(history.val_value_losses),
            "train_policy_losses": list(history.train_policy_losses),
            "val_policy_losses": list(history.val_policy_losses),
            "best_val_loss": history.best_val_loss,
            "best_val_epoch": history.best_val_epoch,
            "epochs_trained": len(history.train_losses),
        }
        if history.train_losses:
            final_history["final_train_loss"] = history.train_losses[-1]
        if history.val_losses:
            final_history["final_val_loss"] = history.val_losses[-1]
        _runs_client.push_progress(
            train_run_id,
            n_games_done=len(history.train_losses),
            n_games_total=args.epochs,
            elapsed_seconds=elapsed,
            extra={
                "training_history": final_history,
                "registered_version": version,
                "architecture": ARCHITECTURE_STRUCTURED,
            },
        )
        weights_path = registry.weights_path(version)
        try:
            weights_bytes = weights_path.stat().st_size
        except OSError:
            weights_bytes = None
        _runs_client.push_artifact(
            train_run_id,
            artifact_type="weights",
            path=str(weights_path),
            bytes_=weights_bytes,
        )

    print(f"\n# Done in {elapsed:.1f}s. Registered as {version}.")
    print(f"# Weights: {registry.weights_path(version)}")
    if history.train_losses:
        print(
            f"# Final train loss: {history.train_losses[-1]:.4f}; "
            f"val loss: {history.val_losses[-1]:.4f}"
        )
    else:
        print("# epochs_trained=0; no per-epoch losses to report")


if __name__ == "__main__":
    main()
