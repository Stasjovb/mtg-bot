"""Replayable game-snapshot recordings — file format + load/save.

A ``Replay`` is metadata + a list of serialized snapshot dicts (the
same shape ``serialize_state`` produces). Saved as gzipped JSON
(typical compressed file: ~100 KB to ~1 MB depending on game length).

Snapshots are LOSSY by design — they contain everything visible
about each game moment (life, hand contents, battlefield, stack,
log) but NOT the engine-side bookkeeping (RNG state, priority pass
count, mid-resolution-pause state) needed to resume computation.
You can SCRUB through a replay, you can't run new MCTS searches
from it. Documented limitation; engine-state serialization is
deferred to a future PR if/when we need replay-time recommendations.

Optional snapshot annotations (added by ``ReplayRecorder``):

- ``heuristic_eval``: ``{p0: float, p1: float}`` — the heuristic
  evaluator's score from each player's perspective. Always cheap.
- ``nn_eval``: ``{p0: float, p1: float}`` — same but from a
  trained NN. Present only when capture was annotated with
  ``--annotate-with-nn-version``.
- ``decision``: JSON-encoded ``Decision`` (v2+ only). The action
  taken at this priority moment, encoded by
  ``training.replay_decisions.decision_to_json``. The very first
  snapshot (initial pre-game state) carries ``"decision": None``
  because no action preceded it. Phase 6's likelihood pairs
  ``(snapshots[i-1], snapshots[i].decision)`` to compute
  ``P(decision | pre-state)``.

Format-version field is stamped into the file so future format
changes can detect old replays and either migrate or refuse.

Version history:

- v1: per-snapshot dicts with the ``serialize_state`` shape plus
  optional ``heuristic_eval`` / ``nn_eval`` annotations. No
  per-snapshot ``decision`` field. Loadable by current readers,
  which inject ``decision = None`` on every snapshot for
  compatibility.
- v2 (current): adds the ``decision`` annotation to each snapshot.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Bump if the format changes incompatibly. Old readers that don't
# recognize the version should refuse rather than silently mis-parse.
REPLAY_FORMAT_VERSION: int = 2

# Versions this build can read. Newer-than-current versions are
# refused; older versions are migrated forward at load time.
_SUPPORTED_FORMAT_VERSIONS: frozenset[int] = frozenset({1, 2})


@dataclass
class Replay:
    """One captured game.

    ``metadata`` is freeform — typical keys: ``game_idx``,
    ``base_seed``, ``p0_config``, ``p1_config``, ``winner``,
    ``n_decisions``, ``captured_at``, ``annotated_with_nn_version``.
    """

    format_version: int = REPLAY_FORMAT_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)
    snapshots: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Replay":
        version = d.get("format_version")
        if version not in _SUPPORTED_FORMAT_VERSIONS:
            raise ValueError(
                f"replay format version {version!r} is not supported "
                f"(this build reads {sorted(_SUPPORTED_FORMAT_VERSIONS)}). "
                f"The file was written by a different version of the "
                f"codebase."
            )
        snapshots = list(d.get("snapshots", []))
        if version == 1:
            # v1 snapshots have no ``decision`` field. Inject ``None``
            # on each so callers don't have to special-case version
            # at access time. Also stamp the in-memory ``Replay`` as
            # v2 so re-saving migrates the file forward.
            snapshots = [
                {**snap, "decision": None} for snap in snapshots
            ]
            version = REPLAY_FORMAT_VERSION
        return cls(
            format_version=version,
            metadata=dict(d.get("metadata", {})),
            snapshots=snapshots,
        )


def save_replay(replay: Replay, path: Path) -> None:
    """Write replay as gzipped JSON. Parent directories are created
    if missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(replay.to_dict()).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(payload)


def load_replay(path: Path) -> Replay:
    """Read a gzipped-JSON replay file written by ``save_replay``."""
    path = Path(path)
    with gzip.open(path, "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    return Replay.from_dict(data)
