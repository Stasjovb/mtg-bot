"""Tests for ``mtg_bot.training._iterate_helpers``.

Today this is just ``find_foreign_npzs``, the safety check
``scripts/iterate_alphazero.py`` runs at startup to refuse to feed
non-iterate npzs into the training step. The bug it prevents took
out v7 in the first deck-pool iterate run: ``gen0_smoke.npz`` had
been sitting in ``training_data/`` from a much older debug run,
and its 603 mask-mismatched rows blew up policy CE when it got
co-globbed with the iter_001 npz.
"""

from __future__ import annotations

from pathlib import Path

from mtg_bot.training._iterate_helpers import find_foreign_npzs


def test_finds_foreign_npzs(tmp_path: Path):
    (tmp_path / "iter_001_v6_20260503T213931Z.npz").write_bytes(b"")
    (tmp_path / "iter_002_v7_20260503T230000Z.npz").write_bytes(b"")
    (tmp_path / "gen0_smoke.npz").write_bytes(b"")  # ← foreign
    (tmp_path / "run01.npz").write_bytes(b"")        # ← foreign
    (tmp_path / "notes.txt").write_text("not a foreign npz")
    found = find_foreign_npzs(tmp_path)
    assert found == ["gen0_smoke.npz", "run01.npz"]


def test_clean_dir_returns_empty(tmp_path: Path):
    (tmp_path / "iter_001_v6_20260503T213931Z.npz").write_bytes(b"")
    (tmp_path / "iter_002_v7_20260503T230000Z.npz").write_bytes(b"")
    (tmp_path / "metadata.json").write_text("{}")
    assert find_foreign_npzs(tmp_path) == []


def test_empty_dir_returns_empty(tmp_path: Path):
    """No npzs at all (typical first-iter setup) → no false positives."""
    assert find_foreign_npzs(tmp_path) == []


def test_missing_dir_returns_empty(tmp_path: Path):
    """A dir that doesn't exist (e.g. iterate's first run, before
    mkdir) returns empty rather than raising — caller handles the
    later mkdir."""
    nonexistent = tmp_path / "no_such_dir"
    assert find_foreign_npzs(nonexistent) == []


def test_pattern_match_is_strict_prefix_only(tmp_path: Path):
    """Only ``iter_`` prefix qualifies as iterate-owned. Files that
    contain 'iter' elsewhere in the name are still foreign."""
    (tmp_path / "iter_001_v6.npz").write_bytes(b"")
    (tmp_path / "my_iter_run.npz").write_bytes(b"")  # ← foreign
    (tmp_path / "ITER_005_capitalized.npz").write_bytes(b"")  # ← foreign
    found = find_foreign_npzs(tmp_path)
    assert "my_iter_run.npz" in found
    assert "ITER_005_capitalized.npz" in found
    assert "iter_001_v6.npz" not in found
