"""Self-play data generation: play games, record (features, outcome).

Produces the training data for Phase D's value-network training. For
every non-chance decision point in every game, captures features from
**both** player perspectives and labels them with the eventual game
outcome from that player's perspective. Same state, two viewers,
two labels — doubles the data with no extra game-play cost.

Storage is ``np.savez_compressed`` (one .npz per generation run).
Multiple .npz files in a directory can be loaded and concatenated
via ``load_all_datasets`` so the trainer can combine sessions.

The strategies used to play the games matter — random play produces
garbage labels (outcome doesn't reflect position quality). Phase D
typically uses PIMC + heuristic on both sides; later phases bootstrap
by using the previously-trained NN to play the next round of games
(the AlphaZero loop).

Two driver functions:

- ``generate_training_data`` runs games sequentially. Used by tests
  (small N, want simple code path) and one-off uses where setup
  overhead matters more than wall-clock parallelism.
- ``generate_training_data_parallel`` distributes games across a
  ``multiprocessing.Pool`` of workers. Both produce identical
  arrays for the same ``base_seed`` because per-game seeds are
  derived from ``game_idx``, not from worker assignment — both
  paths call the same per-game helper. This determinism is locked
  in by a test.

Optional replay capture: pass a ``ReplayCaptureConfig`` to either
driver to write a per-game replay file alongside the training-data
arrays. Useful for debugging engine gaps — see
``mtg_bot.training.replay_capture``.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from mtg_bot.agents import RandomAgent
from mtg_bot.features import FEATURE_DIM, extract_features
from mtg_bot.replay import save_replay
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.protocol import CHANCE_PLAYER, PlayerID
from mtg_bot.simulate import setup_game
from mtg_bot.training.config import StrategyFactory
from mtg_bot.training.replay_capture import (
    ReplayRecorder, heuristic_eval_annotator, nn_eval_annotator,
)


_DEFAULT_DECISION_CAP = 4000

_DTYPE_FEATURES = np.float32
_DTYPE_OUTCOMES = np.float32


@dataclass(frozen=True)
class ReplayCaptureConfig:
    """Picklable config for capturing replays during data gen.

    ``save_dir``: where to write replay files (one .json.gz per
    captured game).
    ``capture_every``: capture every Nth game starting at
    game_idx 0 (so capture_every=10 captures games 0, 10, 20, ...).
    Default 1 = capture all games.
    ``nn_weights_path``: optional path to NN weights — when set,
    each snapshot also gets an ``nn_eval`` annotation alongside the
    always-on ``heuristic_eval``.
    ``nn_version_label``: optional human-readable label (typically
    a registry version like "v3") stored in each ``nn_eval`` so
    consumers know which network produced the scores.
    ``filename_prefix``: prepended to each replay filename. Useful
    for tagging a batch of replays from one experiment.

    Frozen + primitive types so it crosses the multiprocessing spawn
    boundary cleanly.
    """

    save_dir: str
    capture_every: int = 1
    nn_weights_path: Optional[str] = None
    nn_version_label: Optional[str] = None
    filename_prefix: str = "game"

    def should_capture(self, game_idx: int) -> bool:
        return game_idx % self.capture_every == 0

    def replay_path(self, base_seed: int, game_idx: int) -> Path:
        return Path(self.save_dir) / (
            f"{self.filename_prefix}_seed{base_seed}_idx{game_idx:04d}.json.gz"
        )

    def build_recorder(self) -> ReplayRecorder:
        annotators = [heuristic_eval_annotator()]
        if self.nn_weights_path:
            annotators.append(nn_eval_annotator(
                Path(self.nn_weights_path),
                version_label=self.nn_version_label,
            ))
        return ReplayRecorder(annotators=annotators)


def _empty_arrays() -> tuple[np.ndarray, np.ndarray]:
    return (
        np.zeros((0, FEATURE_DIM), dtype=_DTYPE_FEATURES),
        np.zeros((0,), dtype=_DTYPE_OUTCOMES),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_training_data(
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    decision_cap: int = _DEFAULT_DECISION_CAP,
    sample_every: int = 1,
    replay_config: Optional[ReplayCaptureConfig] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Play ``n_games`` and return ``(features, outcomes)`` arrays.

    For each non-chance decision in each game, captures
    ``extract_features(state, viewer)`` for both viewers (0 and 1)
    and labels each with the eventual game outcome from that
    viewer's perspective: +1 / -1 / 0.

    ``sample_every=N`` keeps every Nth decision (1 = all). Useful
    for thinning when games are very long.

    Returns:
        features: ``np.float32`` array of shape ``(samples, FEATURE_DIM)``.
        outcomes: ``np.float32`` array of shape ``(samples,)``, values
            in ``{-1.0, 0.0, +1.0}``.

    Deterministic in ``base_seed`` — same call produces the same
    arrays.
    """
    chunks = [
        _generate_one_game_data(
            game_idx=i,
            p0_factory=p0_factory, p1_factory=p1_factory,
            base_seed=base_seed,
            decision_cap=decision_cap, sample_every=sample_every,
            replay_config=replay_config,
        )
        for i in range(n_games)
    ]
    return _concat_chunks(chunks)


def generate_training_data_parallel(
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    n_workers: Optional[int] = None,
    decision_cap: int = _DEFAULT_DECISION_CAP,
    sample_every: int = 1,
    replay_config: Optional[ReplayCaptureConfig] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Same contract as ``generate_training_data`` but distributes
    games across a ``multiprocessing.Pool``.

    Identical output to the sequential function for the same
    ``base_seed`` — per-game seeds are derived from ``game_idx``, not
    worker assignment, so the same game produces the same samples
    no matter which worker plays it. ``Pool.map`` preserves input
    order so concatenation is deterministic too.

    ``n_workers`` defaults to ``cpu_count() - 2`` (leaves a few cores
    for OS / Python main / the user's other work). Pass an explicit
    int to override.

    Caller note: factories must be picklable. Module-level functions
    (e.g. ``random_choice_factory``) and bound methods of picklable
    dataclasses (e.g. ``PimcConfig().build``) work; lambdas and
    nested closures don't. The CLI builds factories the right way.

    Worker spawn cost on Windows is ~1-2s per worker, paid once per
    pool. Dominates wall clock at very small ``n_games``; amortizes
    away past a few dozen games.
    """
    if n_workers is None:
        n_workers = max(1, (os.cpu_count() or 1) - 2)
    if n_workers < 1:
        raise ValueError(f"n_workers must be >= 1, got {n_workers}")
    if n_games == 0:
        return _empty_arrays()

    args_list = [
        (
            i, p0_factory, p1_factory, base_seed,
            decision_cap, sample_every, replay_config,
        )
        for i in range(n_games)
    ]
    # Pool() with no start method falls back to the platform default —
    # spawn on Windows, fork on Unix. Workers persist for pool
    # lifetime so import cost is paid once per worker.
    with mp.Pool(processes=n_workers) as pool:
        chunks = pool.map(_play_one_parallel_game, args_list)
    return _concat_chunks(chunks)


def _play_one_parallel_game(
    args: tuple,
) -> tuple[np.ndarray, np.ndarray]:
    """Top-level pickleable worker. Plays one game, returns
    ``(features, outcomes)`` arrays for it. Lives at module top
    level (not nested) so multiprocessing can pickle it across the
    spawn boundary."""
    (
        game_idx, p0_factory, p1_factory, base_seed,
        decision_cap, sample_every, replay_config,
    ) = args
    return _generate_one_game_data(
        game_idx=game_idx,
        p0_factory=p0_factory, p1_factory=p1_factory,
        base_seed=base_seed,
        decision_cap=decision_cap, sample_every=sample_every,
        replay_config=replay_config,
    )


def _generate_one_game_data(
    *,
    game_idx: int,
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    base_seed: int,
    decision_cap: int,
    sample_every: int,
    replay_config: Optional[ReplayCaptureConfig] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Play one game and return its ``(features, outcomes)`` arrays.

    The single source of truth for per-game data extraction; both
    sequential and parallel drivers call this so they produce
    bit-identical results for the same ``(game_idx, base_seed,
    factories)``.

    When ``replay_config`` is set and ``should_capture(game_idx)``
    returns True, also writes a per-game replay file to disk before
    returning. The annotators (heuristic + optional NN eval) are
    built fresh per game in the worker — NN model load happens
    once per captured game (a few ms; negligible vs game length).
    """
    engine_seed = base_seed + game_idx
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(engine_seed + 1)),
            RandomAgent(rng=random.Random(engine_seed + 2)),
        ],
        ["G", "R"],
        seed=engine_seed,
    )
    adapter = MtgGameStateAdapter(engine)
    strategies = {
        0: p0_factory(base_seed + 100 * game_idx),
        1: p1_factory(base_seed + 100 * game_idx + 50),
    }
    rng = random.Random(base_seed + 100 * game_idx + 99)

    recorder: Optional[ReplayRecorder] = None
    if replay_config is not None and replay_config.should_capture(game_idx):
        recorder = replay_config.build_recorder()
        # Capture the initial state too so the replay viewer's first
        # snapshot reflects "game 0, before any actions taken."
        recorder.record(adapter.engine_state)

    winner, samples = _play_one_game_recording(
        adapter, strategies, rng, decision_cap, sample_every,
        replay_recorder=recorder,
    )

    if recorder is not None and replay_config is not None:
        replay = recorder.to_replay(metadata={
            "game_idx": game_idx,
            "base_seed": base_seed,
            "engine_seed": engine_seed,
            "winner": winner,
            "n_decisions": len(recorder.snapshots),
            "captured_at": _now_iso(),
            "annotated_with_nn_version": replay_config.nn_version_label,
        })
        save_replay(replay, replay_config.replay_path(base_seed, game_idx))

    if not samples:
        return _empty_arrays()
    outcome_label = _outcome_label(winner)
    features = np.stack(
        [f for f, _ in samples], axis=0,
    ).astype(_DTYPE_FEATURES)
    outcomes = np.asarray(
        [outcome_label[v] for _, v in samples], dtype=_DTYPE_OUTCOMES,
    )
    return features, outcomes


def _concat_chunks(
    chunks: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Concat per-game ``(features, outcomes)`` chunks into the final
    arrays. Skips empty chunks (zero-decision games hit the cap)."""
    nonempty = [c for c in chunks if c[0].size > 0]
    if not nonempty:
        return _empty_arrays()
    features = np.concatenate(
        [c[0] for c in nonempty], axis=0,
    ).astype(_DTYPE_FEATURES)
    outcomes = np.concatenate(
        [c[1] for c in nonempty], axis=0,
    ).astype(_DTYPE_OUTCOMES)
    return features, outcomes


def _outcome_label(
    winner: PlayerID | None,
) -> dict[PlayerID, float]:
    """Per-viewer outcome label. Draw → 0 for both."""
    if winner is None:
        return {0: 0.0, 1: 0.0}
    return {0: 1.0 if winner == 0 else -1.0,
            1: 1.0 if winner == 1 else -1.0}


def _play_one_game_recording(
    adapter: MtgGameStateAdapter,
    strategies: dict[PlayerID, "object"],
    rng: random.Random,
    decision_cap: int,
    sample_every: int,
    replay_recorder: Optional[ReplayRecorder] = None,
) -> tuple[PlayerID | None, list[tuple[np.ndarray, PlayerID]]]:
    """Play one game with the decision cap, recording features at
    every Nth non-chance decision from both player perspectives.

    When ``replay_recorder`` is set, also captures a snapshot of the
    engine state after each ``adapter.apply(decision)`` — both
    chance and player decisions. The recorder's annotators (eval
    values, etc.) run inline.

    Returns ``(winner_or_None, samples)`` where ``samples`` is a list
    of ``(features_array, viewer_id)`` pairs to be paired with the
    eventual outcome label later.
    """
    samples: list[tuple[np.ndarray, PlayerID]] = []
    decision_idx = 0
    while not adapter.is_terminal() and decision_idx < decision_cap:
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            decision = rng.choices(choices, weights=weights, k=1)[0]
        else:
            if decision_idx % sample_every == 0:
                # Capture features from both viewers' perspectives.
                # Same state, opposite outcomes — twice the data
                # with no extra game-play cost.
                engine = adapter.engine_state
                for viewer in (0, 1):
                    feats = extract_features(engine, viewer)
                    samples.append((feats, viewer))
            decision = strategies[active].choose(adapter, active)
        adapter.apply(decision)
        if replay_recorder is not None:
            replay_recorder.record(adapter.engine_state)
        decision_idx += 1
    winner = adapter.winner() if adapter.is_terminal() else None
    return winner, samples


def save_dataset(
    features: np.ndarray, outcomes: np.ndarray, path: Path,
) -> None:
    """Save ``(features, outcomes)`` to a single ``.npz`` file.
    Compressed — datasets are small (~10KB per game) but compression
    is free so why not."""
    if features.shape[0] != outcomes.shape[0]:
        raise ValueError(
            f"features rows {features.shape[0]} != outcomes len "
            f"{outcomes.shape[0]}"
        )
    if features.shape[1] != FEATURE_DIM:
        raise ValueError(
            f"features have dim {features.shape[1]}, expected "
            f"FEATURE_DIM={FEATURE_DIM}"
        )
    np.savez_compressed(path, features=features, outcomes=outcomes)


def load_dataset(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load a single ``.npz`` saved by ``save_dataset``."""
    with np.load(path) as data:
        return data["features"], data["outcomes"]


def load_all_datasets(
    directory: Path,
) -> tuple[np.ndarray, np.ndarray]:
    """Load and concatenate every ``*.npz`` in ``directory``.

    Returns ``(features, outcomes)`` matching ``generate_training_data``'s
    contract. Empty arrays if the directory has no .npz files.
    """
    paths = sorted(directory.glob("*.npz"))
    if not paths:
        return (
            np.zeros((0, FEATURE_DIM), dtype=_DTYPE_FEATURES),
            np.zeros((0,), dtype=_DTYPE_OUTCOMES),
        )
    feature_chunks: list[np.ndarray] = []
    outcome_chunks: list[np.ndarray] = []
    for path in paths:
        feats, outs = load_dataset(path)
        feature_chunks.append(feats)
        outcome_chunks.append(outs)
    return (
        np.concatenate(feature_chunks, axis=0),
        np.concatenate(outcome_chunks, axis=0),
    )
