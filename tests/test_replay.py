"""Tests for ``mtg_bot.replay`` (file format + save/load)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from mtg_bot.replay import REPLAY_FORMAT_VERSION, Replay, load_replay, save_replay


def _sample_replay() -> Replay:
    return Replay(
        format_version=REPLAY_FORMAT_VERSION,
        metadata={"game_idx": 5, "winner": 0, "annotated_with_nn_version": None},
        snapshots=[
            {"turn_number": 1, "step": "untap", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 20}]},
            {"turn_number": 1, "step": "upkeep", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 19}],
             "heuristic_eval": {"p0": 0.05, "p1": -0.05}},
        ],
    )


def test_save_load_round_trip(tmp_path: Path):
    replay = _sample_replay()
    path = tmp_path / "g.json.gz"
    save_replay(replay, path)
    assert path.is_file()
    restored = load_replay(path)
    assert restored.format_version == replay.format_version
    assert restored.metadata == replay.metadata
    assert restored.snapshots == replay.snapshots


def test_save_creates_parent_directories(tmp_path: Path):
    replay = _sample_replay()
    path = tmp_path / "deeply" / "nested" / "g.json.gz"
    save_replay(replay, path)
    assert path.is_file()


def test_load_rejects_unknown_format_version(tmp_path: Path):
    """If a future writer wrote format_version=99, current readers
    should refuse rather than silently mis-parse the data."""
    path = tmp_path / "future.json.gz"
    payload = json.dumps({
        "format_version": 99,
        "metadata": {},
        "snapshots": [],
    }).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(payload)
    with pytest.raises(ValueError, match="format version"):
        load_replay(path)


def test_load_handles_missing_optional_fields(tmp_path: Path):
    """metadata/snapshots default to empty if absent (forward-compat
    in case a writer trims them)."""
    path = tmp_path / "minimal.json.gz"
    payload = json.dumps({"format_version": REPLAY_FORMAT_VERSION}).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(payload)
    replay = load_replay(path)
    assert replay.metadata == {}
    assert replay.snapshots == []


def test_to_dict_round_trips_via_from_dict():
    replay = _sample_replay()
    assert Replay.from_dict(replay.to_dict()) == replay


def test_compressed_file_is_smaller_than_raw_json(tmp_path: Path):
    """Sanity that gzip is doing its job — saved file should be
    smaller than the equivalent uncompressed JSON. Not a tight
    check, just a smoke."""
    # Make a chunky replay (~50 mostly-similar snapshots) so
    # compression has something to work with.
    snaps = []
    for i in range(50):
        snaps.append({
            "turn_number": i // 5 + 1,
            "step": "precombat_main",
            "is_over": False,
            "players": [
                {"id": 0, "life": 20 - i // 10, "hand": [], "library": []},
                {"id": 1, "life": 20 - i // 10, "hand": [], "library": []},
            ],
        })
    replay = Replay(
        format_version=REPLAY_FORMAT_VERSION,
        metadata={"game_idx": 0},
        snapshots=snaps,
    )
    path = tmp_path / "chunky.json.gz"
    save_replay(replay, path)
    raw_size = len(json.dumps(replay.to_dict()))
    compressed_size = path.stat().st_size
    assert compressed_size < raw_size
