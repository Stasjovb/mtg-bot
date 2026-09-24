"""``mtg_bot train``'s training-window selection.

``--window-recent N`` means "the last N ITERATIONS" (2026-09-24). It
used to mean "the N most recently modified FILES", which silently
collapsed to a handful of GAMES on the distributed pipeline: that path
rehydrates one ``.npz`` per game
(``s2_iter_003_self_play_v1_<host>_..._000437.npz``) while the local
loop writes one per iteration (``s2_iter_001_v1_<stamp>.npz``). A
cycle launched with ``--window-recent 3`` trained on three games.

``--window-recent-files N`` keeps the old file-count behaviour for
callers that need a hard cap on file count / RAM.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from mtg_bot.cli import train as cli_train
from mtg_bot.features import FEATURE_DIM


# ---------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------

def _touch_npz(path: Path, *, rows: int = 4, seed: int = 0,
               mtime: float | None = None) -> Path:
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((rows, FEATURE_DIM)).astype(np.float32)
    outcomes = np.tanh(features[:, 0]).astype(np.float32)
    np.savez(path, features=features, outcomes=outcomes)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _select(data_dir: Path, *, iters=None, files=None):
    """``select_window_files`` returning basenames (or None)."""
    logged: list[str] = []
    out = cli_train.select_window_files(
        data_dir, window_iters=iters, window_files=files,
        log=logged.append,
    )
    names = None if out is None else sorted(p.name for p in out)
    return names, "\n".join(logged)


# ---------------------------------------------------------------------
# select_window_files — iteration grouping.
# ---------------------------------------------------------------------

def test_no_window_returns_none(tmp_path: Path) -> None:
    """Neither flag set = load the whole directory (the historical
    default), signalled by ``None`` rather than an explicit list."""
    _touch_npz(tmp_path / "iter_001_v1_x.npz")
    names, _ = _select(tmp_path)
    assert names is None


def test_window_iters_keeps_every_file_of_the_last_n_iterations(
    tmp_path: Path,
) -> None:
    """The distributed shape: many per-GAME files per iteration. A
    window of 2 iterations keeps ALL files of iterations 3 and 4, not
    two files."""
    for it in (1, 2, 3, 4):
        for game in range(3):
            _touch_npz(
                tmp_path / (
                    f"s2_iter_{it:03d}_self_play_v1_DESKTOP-J05412I_"
                    f"s2_iter_{it:03d}_self_play_v1_{game:06d}.npz"
                ),
                seed=it * 10 + game,
            )
    names, log = _select(tmp_path, iters=2)
    assert len(names) == 6, names
    assert all(("iter_003" in n) or ("iter_004" in n) for n in names)
    assert "keeping 6 of 12" in log


def test_window_iters_mixes_per_game_and_per_iteration_files(
    tmp_path: Path,
) -> None:
    """A dir holding BOTH pipelines' outputs: the local loop's single
    per-iteration npz and the distributed loop's per-game npzs group
    by the same iteration label."""
    _touch_npz(tmp_path / "s2_iter_001_v1_20260923T152159Z.npz", seed=1)
    _touch_npz(tmp_path / "s2_iter_002_v1_20260923T162159Z.npz", seed=2)
    for game in range(4):
        _touch_npz(
            tmp_path / (
                f"s2_iter_003_self_play_v1_Greggs-MacBook-Pro.local_"
                f"s2_iter_003_self_play_v1_{game:06d}.npz"
            ),
            seed=30 + game,
        )
    names, _ = _select(tmp_path, iters=2)
    assert names == sorted([
        "s2_iter_002_v1_20260923T162159Z.npz",
        *[
            f"s2_iter_003_self_play_v1_Greggs-MacBook-Pro.local_"
            f"s2_iter_003_self_play_v1_{g:06d}.npz"
            for g in range(4)
        ],
    ])


def test_window_iters_keeps_unlabelled_files_with_a_loud_warning(
    tmp_path: Path,
) -> None:
    """Files with no ``iter_NNN`` label cannot be placed in an
    iteration; dropping them silently would be the same class of bug
    this window fixes, so they are kept and NAMED in a warning."""
    _touch_npz(tmp_path / "iter_001_v1_a.npz", seed=1)
    _touch_npz(tmp_path / "iter_009_v1_b.npz", seed=2)
    _touch_npz(tmp_path / "handcopied.npz", seed=3)
    _touch_npz(tmp_path / "generate_training_data_out.npz", seed=4)

    names, log = _select(tmp_path, iters=1)
    assert names == sorted([
        "iter_009_v1_b.npz",
        "handcopied.npz",
        "generate_training_data_out.npz",
    ])
    assert "WARNING" in log
    assert "handcopied.npz" in log
    assert "generate_training_data_out.npz" in log


def test_window_iters_groups_per_lineage_prefix(tmp_path: Path) -> None:
    """Two lineages in one dir: each keeps its OWN last N iterations.
    Ranking indices globally would let the higher-numbered lineage
    evict the other lineage entirely."""
    for it in (1, 2, 3):
        _touch_npz(tmp_path / f"iter_{it + 6:03d}_v1_x.npz", seed=it)
        _touch_npz(tmp_path / f"s2_iter_{it:03d}_v1_x.npz", seed=it + 50)
    names, log = _select(tmp_path, iters=1)
    assert names == sorted(["iter_009_v1_x.npz", "s2_iter_003_v1_x.npz"])
    assert "MULTIPLE lineage" in log


def test_window_iters_larger_than_available_keeps_everything(
    tmp_path: Path,
) -> None:
    for it in (1, 2):
        _touch_npz(tmp_path / f"iter_{it:03d}_v1_x.npz", seed=it)
    names, _ = _select(tmp_path, iters=99)
    assert names == ["iter_001_v1_x.npz", "iter_002_v1_x.npz"]


def test_window_iters_on_empty_dir(tmp_path: Path) -> None:
    names, _ = _select(tmp_path, iters=3)
    assert names == []


def test_window_iters_ignores_mtime(tmp_path: Path) -> None:
    """Iteration index, not mtime, decides. A late-rewritten old shard
    must NOT drag its whole iteration back into the window."""
    old = _touch_npz(tmp_path / "iter_001_v1_x.npz", seed=1)
    _touch_npz(tmp_path / "iter_002_v1_x.npz", seed=2,
               mtime=time.time() - 10_000)
    os.utime(old, None)  # iteration 1 is now the NEWEST file
    names, _ = _select(tmp_path, iters=1)
    assert names == ["iter_002_v1_x.npz"]


# ---------------------------------------------------------------------
# select_window_files — file-count window (legacy behaviour).
# ---------------------------------------------------------------------

def test_window_files_keeps_n_most_recent_by_mtime(tmp_path: Path) -> None:
    now = time.time()
    for i in range(4):
        _touch_npz(tmp_path / f"s2_iter_001_g{i}.npz", seed=i,
                   mtime=now - (10 - i))
    names, log = _select(tmp_path, files=2)
    assert names == ["s2_iter_001_g2.npz", "s2_iter_001_g3.npz"]
    assert "keeping 2 of 4" in log


def test_window_files_larger_than_available_keeps_everything(
    tmp_path: Path,
) -> None:
    _touch_npz(tmp_path / "a.npz", seed=1)
    names, _ = _select(tmp_path, files=99)
    assert names == ["a.npz"]


# ---------------------------------------------------------------------
# WindowedDataDir.
# ---------------------------------------------------------------------

def test_windowed_data_dir_exposes_only_the_selection(
    tmp_path: Path,
) -> None:
    kept = _touch_npz(tmp_path / "iter_002_v1_x.npz", seed=2)
    _touch_npz(tmp_path / "iter_001_v1_x.npz", seed=1)
    view = cli_train.WindowedDataDir(tmp_path, [kept])
    assert [p.name for p in view.glob("*.npz")] == ["iter_002_v1_x.npz"]
    assert [p.name for p in view.iterdir()] == ["iter_002_v1_x.npz"]
    # Non-enumeration attributes delegate to the real Path.
    assert str(view) == str(tmp_path)
    assert os.fspath(view) == str(tmp_path)
    assert view.is_dir()
    assert (view / "sub") == (tmp_path / "sub")
    assert "WindowedDataDir" in repr(view)
    view.check_enumerated()


def test_windowed_data_dir_raises_when_loader_never_enumerates(
    tmp_path: Path,
) -> None:
    """A loader that stops going through ``glob``/``iterdir`` would
    silently train on the WHOLE dir — that must fail loudly."""
    view = cli_train.WindowedDataDir(tmp_path, [])
    with pytest.raises(RuntimeError, match="window was not applied"):
        view.check_enumerated()


# ---------------------------------------------------------------------
# End-to-end through the flat-feature CLI.
# ---------------------------------------------------------------------

def _run_train(tmp_path: Path, data_dir: Path, extra: list[str]):
    import json

    registry_root = tmp_path / "weights"
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--progress-path", str(tmp_path / "p" / "t.json"),
        *extra,
    ])
    return json.loads(
        (registry_root / "v1" / "metadata.json").read_text(encoding="utf-8")
    )


def test_cli_window_recent_counts_iterations_not_files(
    tmp_path: Path, monkeypatch,
) -> None:
    """The regression this change exists for: 3 games in iteration 2
    plus one file in iteration 1. ``--window-recent 1`` must load the
    three iteration-2 files, not one file."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _touch_npz(data_dir / "s2_iter_001_v1_stamp.npz", rows=8, seed=1)
    for game in range(3):
        _touch_npz(
            data_dir / f"s2_iter_002_self_play_v1_host_{game:06d}.npz",
            rows=8, seed=10 + game,
        )
    meta = _run_train(tmp_path, data_dir, ["--window-recent", "1"])
    assert meta["training"]["data_files"] == sorted(
        f"s2_iter_002_self_play_v1_host_{g:06d}.npz" for g in range(3)
    )
    assert meta["training"]["window_recent"] == 1
    assert meta["training"]["window_recent_files"] is None
    # 3 files x 8 rows actually reached the trainer.
    assert meta["training"]["n_samples"] == 24


def test_cli_window_recent_and_files_are_mutually_exclusive(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _touch_npz(data_dir / "iter_001_v1_x.npz")
    with pytest.raises(SystemExit):
        _run_train(
            tmp_path, data_dir,
            ["--window-recent", "1", "--window-recent-files", "1"],
        )


@pytest.mark.parametrize("flag", ["--window-recent", "--window-recent-files"])
def test_cli_window_flags_reject_non_positive(
    tmp_path: Path, monkeypatch, flag: str,
) -> None:
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _touch_npz(data_dir / "iter_001_v1_x.npz")
    with pytest.raises(SystemExit):
        _run_train(tmp_path, data_dir, [flag, "0"])
