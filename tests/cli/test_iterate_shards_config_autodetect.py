"""Tests for ``mtg_bot iterate``'s auto-detection of
``shards_config.json``.

Background: pre-fix, ``--shards-config`` was a flag-only knob with
``default=None``. The iterate dispatch gated on ``if args.shards_config
is not None`` — so running ``mtg_bot iterate`` without the flag
silently used local-Pool dispatch even when ``shards_config.json``
existed on disk. This UX trap was how iter_019 BUG #4 (the
subprocess pool leak) surfaced: the user had a distributed
configuration written but iterate didn't see it.

The fix:

* When ``--shards-config`` is omitted, iterate probes
  ``<repo_root>/shards_config.json``. If present → dispatch
  distributed. If absent → fall through to local Pool with a log
  line announcing the chosen mode.
* ``--shards-config ""`` is an explicit opt-out (force local Pool,
  bypass auto-detection). Used by tests that stub the local path.
* ``--shards-config /path/to/file`` validates the file exists; a
  missing explicit path fails loudly rather than silently dropping
  to local — that prevents the "typo'd path silently dispatches
  local" failure mode.

These tests pin all three branches plus the parser-level type
conversion that maps ``""`` to the local-Pool sentinel.
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest


def _spy_parser(invoke):
    """Capture the first ArgumentParser constructed by ``invoke()``.

    Mirrors the helper used by other ``tests/cli/test_iterate_*``
    files; duplicated here so this file stays self-contained.
    """
    captured: dict[str, argparse.ArgumentParser] = {}
    real_init = argparse.ArgumentParser.__init__

    def spy_init(self, *a, **kw):
        real_init(self, *a, **kw)
        captured.setdefault("parser", self)

    argparse.ArgumentParser.__init__ = spy_init
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                invoke()
            except SystemExit:
                pass
    finally:
        argparse.ArgumentParser.__init__ = real_init
    assert "parser" in captured, "expected invoke() to construct a parser"
    return captured["parser"]


def _iterate_parser() -> argparse.ArgumentParser:
    iterate = importlib.import_module("mtg_bot.cli.iterate")
    return _spy_parser(lambda: iterate.main(["--help"]))


_BASE_ARGS = [
    "--bootstrap-version", "v4",
    "--deck-pool", "data/17lands/eoe_decks.json.gz",
]


# ----------------------------------------------------------------------
# A. Parser-level type conversion
# ----------------------------------------------------------------------


def test_default_shards_config_namespace_value_is_none():
    """No flag passed → ``args.shards_config is None`` so main() can
    distinguish "not passed" from "explicit opt-out" and run the
    auto-detection branch.

    A real-Path default here would defeat auto-detection (we'd lose
    the "not passed" signal); the resolution lives in main().
    """
    parser = _iterate_parser()
    ns = parser.parse_args(_BASE_ARGS)
    assert ns.shards_config is None


def test_empty_string_shards_config_maps_to_local_pool_sentinel():
    """``--shards-config ""`` resolves to the
    ``_LOCAL_POOL_SENTINEL`` Path the main() dispatch recognizes as
    "explicit local opt-out". A bare ``Path("")`` would resolve to
    ``WindowsPath(".")`` (on Windows) — which is_file()==False, so a
    naive implementation would crash on the file check instead of
    routing to local; the sentinel pattern avoids that footgun.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")
    parser = _iterate_parser()
    ns = parser.parse_args([*_BASE_ARGS, "--shards-config", ""])
    assert ns.shards_config == iterate._LOCAL_POOL_SENTINEL


def test_explicit_path_shards_config_round_trips_as_path(tmp_path: Path):
    """A real path on the command line shows up as a ``Path``
    instance in the namespace — the existing distributed code path
    consumes ``args.shards_config`` as a ``Path``.
    """
    p = tmp_path / "my_shards.json"
    parser = _iterate_parser()
    ns = parser.parse_args([*_BASE_ARGS, "--shards-config", str(p)])
    assert isinstance(ns.shards_config, Path)
    assert ns.shards_config == p


# ----------------------------------------------------------------------
# B. Dispatch logic — auto-detect / explicit-local / explicit-missing
# ----------------------------------------------------------------------


class _FakeDeck:
    card_count = 60


def _stub_heavy_iterate_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    captured_worker_urls: dict,
) -> None:
    """Stub out everything downstream of the dispatch decision so
    main() returns quickly after the dispatch resolution logs. We
    only need to observe the dispatch choice (worker_urls vs local
    Pool) — not run any actual self-play games.

    Approach: stub ``_self_play`` to capture "local" mode and
    ``_self_play_distributed`` to capture "distributed" mode +
    the worker_urls list iterate passed in.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")

    def _fake_self_play(*args, **kwargs):
        captured_worker_urls["mode"] = "local"
        # Touch the output npz so the artifact-size lookup succeeds.
        output: Path = kwargs["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00" * 17)
        progress_path = kwargs.get("progress_path")
        if progress_path is not None:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text("{}", encoding="utf-8")
        # n_samples, n_policy, elapsed
        return (1, 1, 0.01)

    def _fake_self_play_distributed(*args, **kwargs):
        captured_worker_urls["mode"] = "distributed"
        captured_worker_urls["worker_urls"] = kwargs.get(
            "worker_urls",
        )
        # Same return shape as _self_play
        return (1, 1, 0.01)

    monkeypatch.setattr(iterate, "_self_play", _fake_self_play)
    monkeypatch.setattr(
        iterate, "_self_play_distributed", _fake_self_play_distributed,
    )
    # _train_next would shell out; short-circuit it. Return a fixed
    # version label so the iterate loop's bookkeeping is happy.
    monkeypatch.setattr(
        iterate, "_train_next",
        lambda *a, **kw: "v1",
    )
    # decks_from_json: skip the JSON parse, return a fake list. The
    # main() loop only inspects ``len(...)`` and ``card_count`` from
    # each deck for the log header.
    monkeypatch.setattr(
        iterate, "decks_from_json",
        lambda p: [_FakeDeck(), _FakeDeck()],
    )
    # find_foreign_npzs: empty (no foreign npzs to abort on). Same
    # stub as test_iterate_run_db_wiring.py.
    monkeypatch.setattr(
        iterate, "find_foreign_npzs", lambda d: [],
    )
    # Orphan sweep no-ops — would otherwise touch the live system.
    monkeypatch.setattr(
        iterate, "sweep_local_orphans", lambda *a, **kw: None,
    )


def _make_bootstrap_version(registry_root: Path, version: str) -> None:
    """Create the minimum on-disk shape iterate.main() needs to find
    a bootstrap version: weights.pt + metadata.json.
    """
    d = registry_root / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "weights.pt").write_bytes(b"\x00")
    (d / "metadata.json").write_text(
        json.dumps({
            "version": version,
            "created_at": "2026-05-21T00:00:00Z",
            "feature_dim": 1,
            "hidden_sizes": [1],
        }),
        encoding="utf-8",
    )


def _baseline_argv(
    *,
    tmp_path: Path,
    deck_pool: Path,
    bootstrap: str = "v1",
    shards_config: str | None = None,
) -> list[str]:
    """Smallest argv that reaches the dispatch logic without invoking
    real self-play. ``shards_config=None`` omits the flag entirely
    (exercises auto-detection); a non-None string passes the value
    verbatim (use ``""`` for the explicit-local opt-out test).
    """
    argv = [
        "--bootstrap-version", bootstrap,
        "--n-iterations", "1",
        "--games-per-iteration", "1",
        "--samples", "1",
        "--nodes", "1",
        "--epochs", "1",
        "--eval-games", "0",
        "--acceptance-threshold", "0",
        "--data-dir", str(tmp_path / "iterate_data"),
        "--registry-root", str(tmp_path / "trained_weights"),
        "--progress-dir", str(tmp_path / "training_progress"),
        "--deck-pool", str(deck_pool),
        "--seed", "0",
        "--capture-every-self-play", "0",
        "--capture-every-eval", "0",
        "--hang-dump-dir", "",
        "--replays-dir", str(tmp_path / "replays"),
    ]
    if shards_config is not None:
        argv += ["--shards-config", shards_config]
    return argv


@pytest.fixture
def deck_pool_path(tmp_path: Path) -> Path:
    """Placeholder deck-pool file — iterate.main() checks that the
    path ``is_file()`` before calling ``decks_from_json``, but
    ``decks_from_json`` is monkeypatched to a fake list inside
    ``_stub_heavy_iterate_paths`` so the file contents don't matter.
    """
    pool = tmp_path / "deck_pool.json.gz"
    pool.write_bytes(b"")
    return pool


# ----------------------------------------------------------------------
# Branch 1: auto-detect — file present at default location → distributed
# ----------------------------------------------------------------------


def test_iterate_auto_detects_shards_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    deck_pool_path: Path,
):
    """When the default ``shards_config.json`` exists on disk and
    the user did NOT pass ``--shards-config``, iterate should
    auto-detect the file and dispatch distributed. The log header
    must announce the chosen mode + the path so the operator can
    confirm at a glance.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")

    # Point auto-detection at a tmp_path shards_config.json so the
    # test doesn't depend on whatever the live repo-root file
    # contains.
    fake_default = tmp_path / "shards_config.json"
    fake_default.write_text(
        json.dumps({"worker_urls": [
            "http://127.0.0.1:55198",
            "http://127.0.0.1:55199",
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        iterate, "_DEFAULT_SHARDS_CONFIG_PATH", fake_default,
    )

    _make_bootstrap_version(tmp_path / "trained_weights", "v1")
    captured: dict = {}
    _stub_heavy_iterate_paths(
        monkeypatch, captured_worker_urls=captured,
    )

    argv = _baseline_argv(
        tmp_path=tmp_path,
        deck_pool=deck_pool_path,
        shards_config=None,  # omitted → triggers auto-detection
    )
    # The distributed path needs --queue-url to clear the
    # validation guard; supply one even though _self_play_distributed
    # is stubbed.
    argv += ["--queue-url", "http://127.0.0.1:55099"]

    iterate.main(argv)

    out = capsys.readouterr().out
    assert "dispatch mode: distributed" in out, out
    assert str(fake_default) in out, out
    assert captured.get("mode") == "distributed", captured
    assert captured.get("worker_urls") == [
        "http://127.0.0.1:55198",
        "http://127.0.0.1:55199",
    ], captured


# ----------------------------------------------------------------------
# Branch 1b: auto-detect — no file present → local-Pool fallback
# ----------------------------------------------------------------------


def test_iterate_auto_detect_falls_back_to_local_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    deck_pool_path: Path,
):
    """When the default ``shards_config.json`` does not exist and
    the user did NOT pass ``--shards-config``, iterate should log
    the "no shards_config.json found" message and fall through to
    local-Pool dispatch. The fallback must be loud (logged) so the
    operator sees which mode they ended up in.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")

    # Point auto-detection at a nonexistent path inside tmp_path so
    # the live repo-root file (which DOES exist in this checkout)
    # doesn't confound the test.
    fake_default = tmp_path / "definitely_missing_shards_config.json"
    assert not fake_default.is_file()
    monkeypatch.setattr(
        iterate, "_DEFAULT_SHARDS_CONFIG_PATH", fake_default,
    )

    _make_bootstrap_version(tmp_path / "trained_weights", "v1")
    captured: dict = {}
    _stub_heavy_iterate_paths(
        monkeypatch, captured_worker_urls=captured,
    )

    argv = _baseline_argv(
        tmp_path=tmp_path,
        deck_pool=deck_pool_path,
        shards_config=None,
    )
    iterate.main(argv)

    out = capsys.readouterr().out
    assert "dispatch mode: local Pool" in out, out
    assert "no shards_config.json found" in out, out
    assert captured.get("mode") == "local", captured


# ----------------------------------------------------------------------
# Branch 2: explicit --shards-config "" → local
# ----------------------------------------------------------------------


def test_iterate_explicit_empty_shards_config_uses_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    deck_pool_path: Path,
):
    """``--shards-config ""`` explicitly opts out of auto-detection.
    Even when the default ``shards_config.json`` exists on disk,
    iterate must respect the explicit opt-out and run local-Pool.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")

    # Set the default to an EXISTING file so we can prove the opt-out
    # truly bypasses auto-detection (rather than the missing-file
    # path happening to also produce local mode).
    fake_default = tmp_path / "shards_config.json"
    fake_default.write_text(
        json.dumps({"worker_urls": ["http://127.0.0.1:55198"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        iterate, "_DEFAULT_SHARDS_CONFIG_PATH", fake_default,
    )

    _make_bootstrap_version(tmp_path / "trained_weights", "v1")
    captured: dict = {}
    _stub_heavy_iterate_paths(
        monkeypatch, captured_worker_urls=captured,
    )

    argv = _baseline_argv(
        tmp_path=tmp_path,
        deck_pool=deck_pool_path,
        shards_config="",  # explicit opt-out
    )
    iterate.main(argv)

    out = capsys.readouterr().out
    assert "dispatch mode: local Pool" in out, out
    assert "explicit" in out, out
    assert captured.get("mode") == "local", captured


# ----------------------------------------------------------------------
# Branch 3: explicit --shards-config /missing/path → loud error
# ----------------------------------------------------------------------


def test_iterate_explicit_missing_file_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deck_pool_path: Path,
):
    """``--shards-config /nonexistent/path`` must fail loudly — the
    typo'd-path-silently-falls-through-to-local failure mode is
    exactly what this UX fix exists to prevent.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")
    _make_bootstrap_version(tmp_path / "trained_weights", "v1")

    missing = tmp_path / "definitely_missing.json"
    assert not missing.is_file()

    argv = _baseline_argv(
        tmp_path=tmp_path,
        deck_pool=deck_pool_path,
        shards_config=str(missing),
    )

    with pytest.raises(SystemExit) as ei:
        iterate.main(argv)
    msg = str(ei.value)
    assert "--shards-config" in msg or "not found" in msg, msg


def test_iterate_explicit_missing_file_does_not_dispatch_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    deck_pool_path: Path,
):
    """Reinforces the previous test from the other side: an explicit
    missing path must NOT silently dispatch local. The dispatch
    decision aborts the run before any self-play / Pool work fires.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")
    _make_bootstrap_version(tmp_path / "trained_weights", "v1")

    captured: dict = {}
    _stub_heavy_iterate_paths(
        monkeypatch, captured_worker_urls=captured,
    )

    missing = tmp_path / "no_such_file.json"
    argv = _baseline_argv(
        tmp_path=tmp_path,
        deck_pool=deck_pool_path,
        shards_config=str(missing),
    )

    with pytest.raises(SystemExit):
        iterate.main(argv)

    # The stubbed _self_play / _self_play_distributed must not have
    # been called — the missing-file guard fires before either.
    assert "mode" not in captured, captured


# ----------------------------------------------------------------------
# C. Repo-root anchoring (not cwd) — test isolation invariant
# ----------------------------------------------------------------------


def test_default_shards_config_path_is_repo_root_anchored():
    """The default path must be anchored at the repo root, not cwd.
    A cwd-based default would let an unrelated process working
    directory pull in a stray file and silently flip dispatch.
    """
    iterate = importlib.import_module("mtg_bot.cli.iterate")
    assert iterate._DEFAULT_SHARDS_CONFIG_PATH == (
        iterate._REPO_ROOT / "shards_config.json"
    )
