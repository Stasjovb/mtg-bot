"""Replay capture during data generation.

``ReplayRecorder`` accumulates serialized snapshots as a game plays,
optionally annotating each snapshot with evaluator scores so the
viewer can spot eval anomalies (sudden swings, persistent disagreement
with intuition, eval saturating long before the game actually ends).

Two annotators ship today:

- ``heuristic_eval_annotator`` — scores each snapshot with the
  hand-crafted ``MtgHeuristicEvaluator`` from each player's
  perspective. Always cheap, always available.
- ``nn_eval_annotator`` — same shape, using ``NNEvaluator`` loaded
  from a registered version's weights. Optional — only attached
  when capture was launched with ``--annotate-with-nn-version``.

Annotations are merged into the snapshot dict under reserved keys
(``heuristic_eval``, ``nn_eval``). The replay file format documents
these as optional; readers that don't know about them ignore them.

Capture interacts with ``generate_training_data`` via the existing
per-game loop: at each ``adapter.apply(decision)`` the recorder is
told to ``record(state)``. Cost: one ``serialize_state`` call per
priority moment plus the annotators' work — for a typical PIMC
game (~270 decisions), captures ~5 ms of work and ~1 MB
compressed disk per game.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from mtg_bot.game import GameState as EngineGameState
from mtg_bot.replay import REPLAY_FORMAT_VERSION, Replay
from mtg_bot.serialize import serialize_state

# An "annotator" is a function that takes the current engine state
# and returns a dict to merge into the snapshot. Returning an empty
# dict (or None) means "don't annotate this snapshot."
SnapshotAnnotator = Callable[[EngineGameState], dict[str, Any]]


@dataclass
class ReplayRecorder:
    """Accumulates snapshots through a game.

    ``annotators`` are applied in order; later annotators can
    overwrite earlier ones' keys (so put the most authoritative
    annotators last if they overlap).

    Not thread-safe (one recorder per game; the parallel data gen
    builds a fresh recorder per worker per game).
    """

    annotators: list[SnapshotAnnotator] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)

    def record(self, state: EngineGameState) -> None:
        """Capture a snapshot of ``state``. Called once per priority
        moment by the data-gen loop (after each applied decision)."""
        snap = serialize_state(state)
        for annotator in self.annotators:
            extra = annotator(state)
            if extra:
                snap.update(extra)
        self.snapshots.append(snap)

    def to_replay(self, metadata: dict[str, Any]) -> Replay:
        return Replay(
            format_version=REPLAY_FORMAT_VERSION,
            metadata=dict(metadata),
            snapshots=list(self.snapshots),
        )


def _terminal_value(state: EngineGameState, player_id: int) -> float:
    """Return ±1/0 from ``player_id``'s perspective for a terminal
    engine state. Mirrors the protocol-side Evaluator's terminal
    short-circuit. Engine state uses ``is_over`` / ``winner_id`` /
    ``is_draw`` (different names than the protocol's
    ``is_terminal`` / ``winner``)."""
    if state.is_draw or state.winner_id is None:
        return 0.0
    return 1.0 if state.winner_id == player_id else -1.0


def heuristic_eval_annotator() -> SnapshotAnnotator:
    """Returns an annotator that adds ``heuristic_eval``: ``{p0,
    p1}`` to each snapshot. Uses the default heuristic weights;
    if you want to compare different weight settings, build the
    annotator with a custom evaluator yourself.

    Engine state is passed directly (not via an adapter), so this
    bypasses ``Evaluator.evaluate``'s protocol-side terminal check
    and uses the engine's ``is_over`` / ``winner_id`` directly."""
    # Lazy import to keep the search/evaluator import out of any code
    # path that doesn't actually capture replays.
    from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
    evaluator = MtgHeuristicEvaluator()

    def annotate(state: EngineGameState) -> dict[str, Any]:
        if state.is_over():
            return {
                "heuristic_eval": {
                    "p0": _terminal_value(state, 0),
                    "p1": _terminal_value(state, 1),
                }
            }
        return {
            "heuristic_eval": {
                "p0": float(evaluator._evaluate_nonterminal(state, 0)),
                "p1": float(evaluator._evaluate_nonterminal(state, 1)),
            }
        }

    return annotate


def nn_eval_annotator(
    weights_path: Path, version_label: Optional[str] = None,
) -> SnapshotAnnotator:
    """Returns an annotator that adds ``nn_eval``: ``{p0, p1,
    version}`` to each snapshot. ``version`` is the registry version
    id (or the raw weights path) so consumers can tell which network
    produced the scores when comparing replays across training
    iterations.

    Same engine-state-direct treatment as the heuristic annotator
    (bypasses the protocol's terminal short-circuit; uses engine
    fields directly)."""
    from mtg_bot.search.nn_evaluator import NNEvaluator
    evaluator = NNEvaluator(weights_path=weights_path)
    label = version_label if version_label is not None else str(weights_path)

    def annotate(state: EngineGameState) -> dict[str, Any]:
        if state.is_over():
            return {
                "nn_eval": {
                    "p0": _terminal_value(state, 0),
                    "p1": _terminal_value(state, 1),
                    "version": label,
                }
            }
        return {
            "nn_eval": {
                "p0": float(evaluator._evaluate_nonterminal(state, 0)),
                "p1": float(evaluator._evaluate_nonterminal(state, 1)),
                "version": label,
            }
        }

    return annotate
