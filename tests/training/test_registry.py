"""Tests for ``mtg_bot.training.registry``.

Covers:
- ModelMetadata round-trip (to_dict / from_dict, including unknown
  forward-compat keys).
- Registry CRUD: register, list, latest, has, load.
- Sequential version assignment (v1, v2, ...).
- Incomplete directory handling (missing weights or metadata file
  → not listed).
- add_evaluation_result update path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot.training.registry import ModelMetadata, Registry


def _make_metadata(version: str = "") -> ModelMetadata:
    return ModelMetadata(
        version=version,
        created_at="2026-04-25T17:00:00Z",
        feature_dim=51,
        hidden_sizes=[128, 128, 64],
        training={"epochs": 30, "batch_size": 256},
        training_history={
            "final_train_loss": 0.18,
            "final_val_loss": 0.17,
            "best_val_loss": 0.16,
            "best_val_epoch": 28,
        },
        evaluation={},
        git_commit="abcd1234",
        notes="test",
    )


def _write_dummy_weights(path: Path, payload: bytes = b"weights-bytes") -> None:
    path.write_bytes(payload)


# ---------- ModelMetadata round-trip ----------------------------------------


def test_metadata_round_trips_through_dict():
    m = _make_metadata("v3")
    restored = ModelMetadata.from_dict(m.to_dict())
    assert restored == m


def test_metadata_preserves_unknown_keys_in_extra():
    raw = {
        "version": "v1",
        "created_at": "2026-04-25T17:00:00Z",
        "feature_dim": 51,
        "hidden_sizes": [128],
        "future_field": "from-tomorrow",
        "another_unknown": {"nested": True},
    }
    m = ModelMetadata.from_dict(raw)
    assert m.extra["future_field"] == "from-tomorrow"
    assert m.extra["another_unknown"] == {"nested": True}
    # Round-trip preserves them.
    round_tripped = ModelMetadata.from_dict(m.to_dict())
    assert round_tripped.extra["future_field"] == "from-tomorrow"


def test_metadata_with_policy_defaults_false_for_old_metadata():
    """v1/v2 metadata.json files written before A4 don't have the
    ``with_policy`` key. Loading them must default to False so the
    tournament harness keeps treating them as value-only networks."""
    raw = {
        "version": "v2",
        "created_at": "2026-04-25T17:00:00Z",
        "feature_dim": 51,
        "hidden_sizes": [128, 128, 64],
    }
    m = ModelMetadata.from_dict(raw)
    assert m.with_policy is False
    # Forward-compat: round-trip writes the field, future readers
    # see it explicitly.
    assert m.to_dict()["with_policy"] is False


def test_metadata_with_policy_round_trip_true():
    """v4+ writes ``with_policy=True``; verify round-trip preserves it."""
    m = ModelMetadata(
        version="v4",
        created_at="2026-05-02T17:00:00Z",
        feature_dim=51,
        hidden_sizes=[128, 128, 64],
        with_policy=True,
    )
    restored = ModelMetadata.from_dict(m.to_dict())
    assert restored.with_policy is True
    assert restored == m


# ---------- Registry: registration ------------------------------------------


def test_register_creates_v1_when_empty(tmp_path: Path):
    reg = Registry(tmp_path)
    weights = tmp_path / "src.pt"
    _write_dummy_weights(weights)
    version = reg.register(weights, _make_metadata())
    assert version == "v1"
    assert (tmp_path / "v1" / "weights.pt").is_file()
    assert (tmp_path / "v1" / "metadata.json").is_file()


def test_register_assigns_sequential_versions(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    versions = [reg.register(src, _make_metadata()) for _ in range(5)]
    assert versions == ["v1", "v2", "v3", "v4", "v5"]


def test_register_writes_metadata_with_version_filled_in(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    metadata_in = _make_metadata("")  # caller leaves it blank
    reg.register(src, metadata_in)
    metadata_out = reg.load_metadata("v1")
    assert metadata_out.version == "v1"


def test_register_explicit_version(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    version = reg.register(src, _make_metadata(), version="v42")
    assert version == "v42"
    assert (tmp_path / "v42" / "weights.pt").is_file()


def test_register_explicit_version_validates_format(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    with pytest.raises(ValueError, match=r"v\\d\+"):
        reg.register(src, _make_metadata(), version="not-a-version")


def test_register_copies_weights_bytes(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src, b"specific-payload")
    reg.register(src, _make_metadata())
    assert reg.weights_path("v1").read_bytes() == b"specific-payload"


def test_register_does_not_consume_source_file(tmp_path: Path):
    """Source weights file must remain after register (caller still
    owns it). Important for tests / temp-file workflows."""
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    reg.register(src, _make_metadata())
    assert src.exists()


# ---------- Registry: enumeration -------------------------------------------


def test_list_versions_sorted_numerically(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    for _ in range(12):
        reg.register(src, _make_metadata())
    listed = reg.list_versions()
    # Numeric sort: v1, v2, ..., v10, v11, v12 (NOT v1, v10, v11, v12, v2 ...)
    assert listed == [f"v{i}" for i in range(1, 13)]


def test_list_versions_ignores_non_version_directories(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    reg.register(src, _make_metadata())
    # Drop a scratch directory in the registry root.
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "weights.pt").touch()
    listed = reg.list_versions()
    assert listed == ["v1"]


def test_list_versions_skips_incomplete_directories(tmp_path: Path):
    reg = Registry(tmp_path)
    # Manually create an incomplete v1 (weights only, no metadata).
    incomplete = tmp_path / "v1"
    incomplete.mkdir()
    (incomplete / "weights.pt").touch()
    assert reg.list_versions() == []


def test_latest_versions_returns_newest_first_capped(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    for _ in range(10):
        reg.register(src, _make_metadata())
    assert reg.latest_versions(3) == ["v10", "v9", "v8"]


def test_latest_versions_handles_n_larger_than_count(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    for _ in range(2):
        reg.register(src, _make_metadata())
    assert reg.latest_versions(10) == ["v2", "v1"]


def test_latest_versions_zero_returns_empty(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    reg.register(src, _make_metadata())
    assert reg.latest_versions(0) == []


def test_latest_versions_negative_raises(tmp_path: Path):
    reg = Registry(tmp_path)
    with pytest.raises(ValueError, match="n must be >= 0"):
        reg.latest_versions(-1)


# ---------- Registry: access ------------------------------------------------


def test_has_true_for_complete_false_otherwise(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    reg.register(src, _make_metadata())
    assert reg.has("v1")
    assert not reg.has("v99")


def test_weights_path_raises_for_missing_version(tmp_path: Path):
    reg = Registry(tmp_path)
    with pytest.raises(FileNotFoundError):
        reg.weights_path("v99")


def test_load_metadata_raises_for_missing_version(tmp_path: Path):
    reg = Registry(tmp_path)
    with pytest.raises(FileNotFoundError):
        reg.load_metadata("v99")


# ---------- Registry: evaluation result update ------------------------------


def test_add_evaluation_result_updates_metadata(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    reg.register(src, _make_metadata())
    reg.add_evaluation_result(
        "v1", "vs_heuristic",
        {"win_rate": 0.6, "wins": 12, "losses": 8, "draws": 0},
    )
    reloaded = reg.load_metadata("v1")
    assert reloaded.evaluation["vs_heuristic"]["win_rate"] == 0.6
    assert reloaded.evaluation["vs_heuristic"]["wins"] == 12


def test_add_evaluation_result_overwrites_existing_key(tmp_path: Path):
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    reg.register(src, _make_metadata())
    reg.add_evaluation_result("v1", "vs_heuristic", {"win_rate": 0.3})
    reg.add_evaluation_result("v1", "vs_heuristic", {"win_rate": 0.7})
    reloaded = reg.load_metadata("v1")
    assert reloaded.evaluation["vs_heuristic"]["win_rate"] == 0.7


# ---------- next_version_id edge cases --------------------------------------


def test_next_version_id_skips_past_partial_directories(tmp_path: Path):
    """If there's a partial v3/ (weights only) and a complete v2/,
    next id should be v4, not v3 — avoid colliding with the partial."""
    reg = Registry(tmp_path)
    src = tmp_path / "src.pt"
    _write_dummy_weights(src)
    reg.register(src, _make_metadata())  # v1
    reg.register(src, _make_metadata())  # v2
    # Hand-create a partial v3.
    (tmp_path / "v3").mkdir()
    (tmp_path / "v3" / "weights.pt").touch()
    # No metadata.json — incomplete.
    assert reg.next_version_id() == "v4"
