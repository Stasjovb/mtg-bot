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


def test_load_v1_replay_injects_decision_none(tmp_path: Path):
    """Files written under v1 (no ``decision`` per snapshot) load
    cleanly: each snapshot gets ``decision=None``, the in-memory
    Replay is stamped at the current format version."""
    path = tmp_path / "legacy_v1.json.gz"
    payload = json.dumps({
        "format_version": 1,
        "metadata": {"game_idx": 0, "winner": 0},
        "snapshots": [
            {"turn_number": 1, "step": "untap", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 20}]},
            {"turn_number": 1, "step": "upkeep", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 19}],
             "heuristic_eval": {"p0": 0.0, "p1": 0.0}},
        ],
    }).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(payload)
    replay = load_replay(path)
    assert replay.format_version == REPLAY_FORMAT_VERSION
    assert all(s["decision"] is None for s in replay.snapshots)
    # Pre-existing fields survive.
    assert replay.snapshots[0]["turn_number"] == 1
    assert replay.snapshots[1]["heuristic_eval"] == {"p0": 0.0, "p1": 0.0}


def test_load_v2_replay_injects_search_none(tmp_path: Path):
    """v2 replays (no per-snapshot ``search`` field) load cleanly:
    each snapshot gets ``search=None``, the in-memory Replay is
    stamped at the current format version. Mirrors the v1→v2
    decision injection but for the v2→v3 search injection."""
    path = tmp_path / "legacy_v2.json.gz"
    payload = json.dumps({
        "format_version": 2,
        "metadata": {"game_idx": 0, "winner": 0},
        "snapshots": [
            {"turn_number": 1, "step": "untap", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 20}],
             "decision": None},
            {"turn_number": 1, "step": "upkeep", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 19}],
             "decision": {"kind": "PassPriority"},
             "heuristic_eval": {"p0": 0.0, "p1": 0.0}},
        ],
    }).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(payload)
    replay = load_replay(path)
    assert replay.format_version == REPLAY_FORMAT_VERSION
    assert REPLAY_FORMAT_VERSION == 3
    assert all(s["search"] is None for s in replay.snapshots)
    # Pre-existing fields survive.
    assert replay.snapshots[1]["decision"] == {"kind": "PassPriority"}
    assert replay.snapshots[1]["heuristic_eval"] == {"p0": 0.0, "p1": 0.0}


def test_load_v1_replay_chains_through_to_v3(tmp_path: Path):
    """v1 → v2 → v3 migration chain: a v1 file gets BOTH
    ``decision=None`` and ``search=None`` injected on every snapshot
    so loaders can dot-access either field without version checks."""
    path = tmp_path / "ancient.json.gz"
    payload = json.dumps({
        "format_version": 1,
        "metadata": {},
        "snapshots": [
            {"turn_number": 1, "step": "untap", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 20}]},
        ],
    }).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(payload)
    replay = load_replay(path)
    assert replay.format_version == REPLAY_FORMAT_VERSION
    assert replay.snapshots[0]["decision"] is None
    assert replay.snapshots[0]["search"] is None


def test_v3_replay_round_trips_search_annotation(tmp_path: Path):
    """A v3 replay with a search annotation on a snapshot saves +
    loads byte-identical (modulo gzip framing). The chosen action,
    candidate list, samples / inner_nodes / elapsed_ms, and the
    floating-point Q / prior / leaf_value all survive."""
    annotation = {
        "chosen": {"kind": "PassPriority"},
        "candidates": [
            {
                "action": {"kind": "PassPriority"},
                "visits": 32,
                "q": 0.421,
                "prior": 0.7,
                "leaf_value": 0.39,
            },
            {
                "action": {"kind": "PlayLand", "card_id": 5},
                "visits": 7,
                "q": -0.1,
                "prior": 0.2,
                "leaf_value": -0.05,
            },
        ],
        "samples": 8,
        "inner_nodes": 200,
        "elapsed_ms": 42,
    }
    replay = Replay(
        format_version=REPLAY_FORMAT_VERSION,
        metadata={"game_idx": 0},
        snapshots=[
            {"turn_number": 1, "step": "upkeep", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 20}],
             "decision": {"kind": "PassPriority"},
             "search": annotation},
            {"turn_number": 1, "step": "draw", "is_over": False,
             "players": [{"id": 0, "life": 20}, {"id": 1, "life": 20}],
             "decision": None,
             "search": None},
        ],
    )
    path = tmp_path / "v3.json.gz"
    save_replay(replay, path)
    restored = load_replay(path)
    assert restored.format_version == REPLAY_FORMAT_VERSION
    assert restored.snapshots[0]["search"] == annotation
    assert restored.snapshots[1]["search"] is None


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
