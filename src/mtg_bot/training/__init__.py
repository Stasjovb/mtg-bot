"""Training infrastructure for the value-network learning chapter.

Module map:

- ``config``     — ``HeuristicConfig`` + ``PimcConfig`` dataclasses
                   with ``build()`` (→ search strategy) and JSON
                   serialization. Frozen for use as dict keys / set
                   members in tuning loops.
- ``self_play`` — ``run_match(p0_factory, p1_factory, n_games, ...)``:
                   plays N games with a hard decision cap, returns
                   aggregate wins/losses/draws + average decisions.
                   Deterministic from ``base_seed``.
- ``grid``      — ``grid_search`` over a list of configs, each
                   played N games against a fixed opponent factory.
                   Returns results sorted by win rate.
- ``data_gen``  — ``generate_training_data`` (sequential) and
                   ``generate_training_data_parallel`` (multi-process)
                   produce the same arrays for the same ``base_seed``.
                   Both capture ``(features, outcome)`` from both
                   player perspectives at every non-chance decision.
                   Save / load via compressed ``.npz``.
- ``trainer``   — ``train_value_network``: PyTorch MSE training of
                   the ``_ValueMLP`` from nn_evaluator. CUDA when
                   available; saves the final state_dict that
                   ``NNEvaluator(weights_path=...)`` loads.
- ``registry``  — ``Registry`` + ``ModelMetadata``: versioned
                   model checkpoints. Each trained network gets a
                   ``v{N}/`` subdirectory under the registry root
                   with ``weights.pt`` + a JSON metadata sidecar.
                   Used by train_nn.py (auto-register on train),
                   evaluate_nn.py (eval by version, write result
                   back), and tournament.py (round-robin between
                   recent versions).
- ``replay_capture`` — ``ReplayRecorder`` accumulates serialized
                   snapshots through a game, optionally annotated
                   with eval values per snapshot (heuristic_eval
                   always; nn_eval when a registered version is
                   passed). Wired into data gen via
                   ``ReplayCaptureConfig`` for per-game disk-write
                   alongside training-data arrays.

CLI demos in ``scripts/``: ``tune_heuristic.py`` (Phase A weight
sweep), ``generate_training_data.py``, ``train_nn.py``,
``evaluate_nn.py``, ``tournament.py``, ``inspect_replay.py``.
"""

from __future__ import annotations

from mtg_bot.training.config import (
    HeuristicConfig,
    NNPimcConfig,
    PimcConfig,
    random_choice_factory,
)
from mtg_bot.training.data_gen import (
    ReplayCaptureConfig,
    generate_training_data,
    generate_training_data_parallel,
    load_all_datasets,
    load_dataset,
    save_dataset,
)
from mtg_bot.training.grid import grid_search, heuristic_weight_grid
from mtg_bot.training.registry import ModelMetadata, Registry
from mtg_bot.training.replay_capture import (
    ReplayRecorder,
    heuristic_eval_annotator,
    nn_eval_annotator,
)
from mtg_bot.training.self_play import MatchStats, run_match
from mtg_bot.training.trainer import (
    TrainingHistory, auto_device, train_value_network,
)

__all__ = [
    "HeuristicConfig",
    "MatchStats",
    "ModelMetadata",
    "NNPimcConfig",
    "PimcConfig",
    "Registry",
    "ReplayCaptureConfig",
    "ReplayRecorder",
    "TrainingHistory",
    "auto_device",
    "generate_training_data",
    "generate_training_data_parallel",
    "grid_search",
    "heuristic_eval_annotator",
    "heuristic_weight_grid",
    "load_all_datasets",
    "load_dataset",
    "nn_eval_annotator",
    "random_choice_factory",
    "run_match",
    "save_dataset",
    "train_value_network",
]
