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
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable

import numpy as np

from mtg_bot.agents import RandomAgent
from mtg_bot.features import FEATURE_DIM, extract_features
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.protocol import CHANCE_PLAYER, PlayerID
from mtg_bot.simulate import setup_game
from mtg_bot.training.config import StrategyFactory


_DEFAULT_DECISION_CAP = 4000

_DTYPE_FEATURES = np.float32
_DTYPE_OUTCOMES = np.float32


def generate_training_data(
    p0_factory: StrategyFactory,
    p1_factory: StrategyFactory,
    n_games: int,
    base_seed: int = 0,
    decision_cap: int = _DEFAULT_DECISION_CAP,
    sample_every: int = 1,
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
    feature_buf: list[np.ndarray] = []
    outcome_buf: list[float] = []

    for game_idx in range(n_games):
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

        winner, samples_for_this_game = _play_one_game_recording(
            adapter, strategies, rng, decision_cap, sample_every,
        )
        outcome_label = _outcome_label(winner)
        for features_per_viewer, viewer in samples_for_this_game:
            feature_buf.append(features_per_viewer)
            outcome_buf.append(outcome_label[viewer])

    if not feature_buf:
        return (
            np.zeros((0, FEATURE_DIM), dtype=_DTYPE_FEATURES),
            np.zeros((0,), dtype=_DTYPE_OUTCOMES),
        )
    features = np.stack(feature_buf, axis=0).astype(_DTYPE_FEATURES)
    outcomes = np.asarray(outcome_buf, dtype=_DTYPE_OUTCOMES)
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
) -> tuple[PlayerID | None, list[tuple[np.ndarray, PlayerID]]]:
    """Play one game with the decision cap, recording features at
    every Nth non-chance decision from both player perspectives.

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
