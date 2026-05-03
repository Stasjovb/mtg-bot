"""Tests for ``mtg_bot.training._hang_dump.dump_hang_diagnostics``.

The helper is invoked from inside data-gen / eval workers when a
per-game timeout fires, so it must:

- Write a structured meta.json + a faulthandler-style traceback.txt.
- Never raise — a failed dump must not crash the worker, since the
  existing sentinel-return path still needs to run.
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.training._hang_dump import dump_hang_diagnostics


def test_dump_writes_meta_and_traceback_files(tmp_path: Path):
    out = dump_hang_diagnostics(
        str(tmp_path / "hangs"),
        base_seed=12345,
        game_idx=7,
        engine_seed=12352,
        error_type="TimeoutError",
        error_message="game exceeded 300s",
        extra={"phase": "data_gen", "n_workers": 24},
    )
    assert out is not None and out.is_file()
    # Two files per dump event with matching stem.
    stem = out.stem
    siblings = list((tmp_path / "hangs").iterdir())
    assert len(siblings) == 2
    assert any(p.suffix == ".json" for p in siblings)
    assert any(p.suffix == ".txt" for p in siblings)
    meta = json.loads(out.read_text(encoding="utf-8"))
    assert meta["base_seed"] == 12345
    assert meta["game_idx"] == 7
    assert meta["engine_seed"] == 12352
    assert meta["error_type"] == "TimeoutError"
    assert meta["error_message"] == "game exceeded 300s"
    assert meta["phase"] == "data_gen"
    assert meta["n_workers"] == 24
    assert "captured_at" in meta and "pid" in meta
    # Traceback file should contain at least one frame from the
    # current test thread — confirms faulthandler ran.
    txt = (tmp_path / "hangs" / f"{stem}.txt").read_text(
        encoding="utf-8",
    )
    assert "Thread" in txt or "Stack" in txt or "  File" in txt


def test_dump_creates_parent_directory(tmp_path: Path):
    """``dump_dir`` may not exist yet — iterate creates per-run
    subdirs lazily and the worker has no startup chance to mkdir."""
    nested = tmp_path / "deeply" / "nested" / "hangs"
    out = dump_hang_diagnostics(
        str(nested),
        base_seed=0, game_idx=0, engine_seed=0,
        error_type="TimeoutError", error_message="",
    )
    assert out is not None
    assert nested.is_dir()


def test_dump_swallows_filesystem_errors(tmp_path: Path):
    """A bad path (e.g. a file masquerading as a dir) must NOT
    propagate — diagnostic capture must never crash the worker."""
    # Create a file at the path we'll try to use as the dump dir.
    blocker = tmp_path / "blocker"
    blocker.write_text("im a file not a dir", encoding="utf-8")
    out = dump_hang_diagnostics(
        str(blocker),
        base_seed=0, game_idx=0, engine_seed=0,
        error_type="TimeoutError", error_message="",
    )
    assert out is None  # failed silently


def test_dump_filename_encodes_seed_and_game_idx(tmp_path: Path):
    """Filename pattern is grep-friendly — a user investigating a
    flaky run can find their seed via ``ls debug_hangs/`` alone."""
    out = dump_hang_diagnostics(
        str(tmp_path),
        base_seed=999, game_idx=42, engine_seed=1041,
        error_type="TimeoutError", error_message="",
    )
    assert out is not None
    assert "seed999" in out.name
    assert "idx0042" in out.name


# -----------------------------------------------------------------
# Integration: TimeoutError raised inside the game loop triggers a
# dump for both data-gen (_generate_one_game_data) and self-play
# (_play_one_match_game). Both paths catch TimeoutError specifically
# vs the broad sentinel handler so the seed + traceback land before
# the empty-chunk / (None, 0) sentinel propagates back to the pool.
# -----------------------------------------------------------------


def test_self_play_dumps_on_timeout(tmp_path: Path, monkeypatch):
    from mtg_bot.training import _timeout
    from mtg_bot.training import random_choice_factory
    from mtg_bot.training.self_play import _play_one_match_game

    def fake_run_with_timeout(*args, **kwargs):
        raise TimeoutError("simulated worker hang")

    monkeypatch.setattr(_timeout, "run_with_timeout", fake_run_with_timeout)
    dump_dir = tmp_path / "hangs"
    import pytest
    with pytest.raises(TimeoutError):
        _play_one_match_game(
            game_idx=3,
            p0_factory=random_choice_factory,
            p1_factory=random_choice_factory,
            base_seed=42,
            decision_cap=4000,
            per_game_timeout_sec=300.0,
            hang_dump_dir=str(dump_dir),
        )
    files = sorted(dump_dir.iterdir())
    assert len(files) == 2  # meta.json + traceback.txt
    meta = next(f for f in files if f.suffix == ".json")
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["base_seed"] == 42
    assert payload["game_idx"] == 3
    assert payload["phase"] == "eval"
    assert payload["error_type"] == "TimeoutError"


def test_self_play_no_dump_when_dir_omitted(
    tmp_path: Path, monkeypatch,
):
    """If iterate doesn't pass hang_dump_dir, the timeout still
    propagates but no files are written — backward compat for
    callers that don't opt in."""
    from mtg_bot.training import _timeout
    from mtg_bot.training import random_choice_factory
    from mtg_bot.training.self_play import _play_one_match_game

    monkeypatch.setattr(
        _timeout, "run_with_timeout",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("x")),
    )
    import pytest
    with pytest.raises(TimeoutError):
        _play_one_match_game(
            game_idx=0,
            p0_factory=random_choice_factory,
            p1_factory=random_choice_factory,
            base_seed=0,
            decision_cap=4000,
            per_game_timeout_sec=300.0,
            hang_dump_dir=None,
        )
    # No dump dir was created (or written into) — there's nothing
    # to assert besides "no files leaked into tmp_path".
    assert list(tmp_path.iterdir()) == []


def test_data_gen_dumps_on_timeout(tmp_path: Path, monkeypatch):
    from mtg_bot.training import _timeout
    from mtg_bot.training import random_choice_factory
    from mtg_bot.training.data_gen import _generate_one_game_data

    monkeypatch.setattr(
        _timeout, "run_with_timeout",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("hang")),
    )
    dump_dir = tmp_path / "hangs"
    import pytest
    with pytest.raises(TimeoutError):
        _generate_one_game_data(
            game_idx=11,
            p0_factory=random_choice_factory,
            p1_factory=random_choice_factory,
            base_seed=99,
            decision_cap=4000,
            sample_every=1,
            per_game_timeout_sec=300.0,
            hang_dump_dir=str(dump_dir),
        )
    files = sorted(dump_dir.iterdir())
    assert len(files) == 2
    meta = next(f for f in files if f.suffix == ".json")
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["base_seed"] == 99
    assert payload["game_idx"] == 11
    assert payload["phase"] == "data_gen"
