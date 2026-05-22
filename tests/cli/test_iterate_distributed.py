"""Tests for the unified distributed-iter launcher CLI.

The launcher's job is to glue config + state + lifecycle + iterate
spawn together; these tests drive the orchestrator with stub
subprocess + monkeypatched heartbeat to exercise the full launch
flow without bringing up real workers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mtg_bot.cli import iterate_distributed as id_mod
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.launcher.config import LaunchConfigError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_toml(tmp_path: Path) -> Path:
    p = tmp_path / "launch.toml"
    p.write_text("""
[iter]
target_iter = 21
bootstrap_version = "v5"
nodes = 200
samples = 8

[cluster]
local_only = true
master_url = "http://desktop-j05412i:5198"
mac_url = "http://greggs-macbook-pro:5198"
""", encoding="utf-8")
    return p


@pytest.fixture
def progress_dir(tmp_path: Path) -> Path:
    p = tmp_path / "tp"
    p.mkdir(parents=True, exist_ok=True)
    # Materialise the runs.db schema so the lifecycle ctx mgr can
    # write the cycle row.
    conn = runs_db.connect(p / "runs.db")
    conn.close()
    return p


@pytest.fixture
def runs_db_env(progress_dir: Path, monkeypatch):
    monkeypatch.setenv(
        "MTG_BOT_RUN_DB_PATH", str(progress_dir / "runs.db"),
    )
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    yield progress_dir / "runs.db"


@pytest.fixture
def stub_heartbeat(monkeypatch):
    """Bypass the live IDLE check -- tests don't have real workers."""
    monkeypatch.setattr(
        id_mod, "verify_worker_idle",
        lambda url: None,
    )


# ---------------------------------------------------------------------------
# Argv parsing: known + overrides + iterate passthrough
# ---------------------------------------------------------------------------


def test_dry_run_prints_resolved_argv(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, capsys,
):
    rc = id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cycle_id=iter_021_cycle" in out
    assert "shards_config=" in out
    assert "queue_url=http://desktop-j05412i:5099" in out  # derived
    assert "--nodes 200" in out
    assert "--bootstrap-version v5" in out
    assert "--n-iterations 1" in out
    assert "--shards-config" in out


def test_cli_overrides_propagate_to_argv(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, capsys,
):
    """--iter.nodes 800 from CLI must override TOML's 200."""
    rc = id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
        "--dry-run",
        "--iter.nodes", "800",
        "--iter.samples=16",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "--nodes 800" in out
    assert "--samples 16" in out


def test_config_error_returns_2(
    progress_dir: Path, runs_db_env: Path, capsys,
):
    """Missing TOML + no overrides -> validation error -> exit 2."""
    rc = id_mod.main([
        "--progress-dir", str(progress_dir),
        "--dry-run",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "config error" in err
    assert "target_iter must be positive" in err


def test_local_only_false_missing_aws_config_blocks_launch(
    tmp_path: Path, progress_dir: Path, runs_db_env: Path, capsys,
):
    """Phase B path: local_only=false without [aws] section fails
    at config-load time with a clear actionable message, not after
    runs.db has been touched."""
    toml = tmp_path / "launch.toml"
    toml.write_text("""
[iter]
target_iter = 5

[cluster]
local_only = false
master_url = "http://h:5198"
""", encoding="utf-8")
    rc = id_mod.main([
        "--config", str(toml),
        "--progress-dir", str(progress_dir),
        "--dry-run",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "aws.count must be >= 1" in err


def test_no_worker_urls_raises(
    tmp_path: Path, progress_dir: Path, runs_db_env: Path,
):
    toml = tmp_path / "launch.toml"
    toml.write_text("""
[iter]
target_iter = 5

[cluster]
local_only = true
""", encoding="utf-8")
    with pytest.raises(LaunchConfigError, match="no worker URLs"):
        id_mod._launch(
            id_mod.load_config(toml),
            progress_dir=progress_dir,
            deck_pool=None,
            queue_url=None,
            force_resume_from_failed=False,
            dry_run=True,
            skip_worker_verify=True,
            iterate_passthrough=[],
        )


# ---------------------------------------------------------------------------
# Cycle row registration + lifecycle
# ---------------------------------------------------------------------------


def _stub_spawn(record: dict[str, Any], *, exit_code: int = 0):
    """Build a spawn stub that records the call + returns exit_code."""
    def _spawn(argv, env=None, cwd=None, popen_factory=None, **kwargs):
        record["argv"] = list(argv)
        record["env"] = dict(env or {})
        return exit_code
    return _spawn


def test_successful_launch_marks_completed(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn(record, exit_code=0),
    )
    rc = id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    assert rc == 0
    # Cycle row was registered + marked completed.
    conn = runs_db.connect(progress_dir / "runs.db")
    try:
        row = runs_db.get_run(conn, "iter_021_cycle")
    finally:
        conn.close()
    assert row is not None
    assert row["run"]["status"] == "completed"
    # Argv carries the iterate-shape flags + the per-cycle shards_config.
    argv = record["argv"]
    assert "iterate" in argv
    assert "--shards-config" in argv
    sc_idx = argv.index("--shards-config")
    sc_path = Path(argv[sc_idx + 1])
    assert sc_path.is_file()
    # And the ephemeral shards_config has the worker URLs from TOML.
    data = json.loads(sc_path.read_text(encoding="utf-8"))
    assert data["worker_urls"] == [
        "http://desktop-j05412i:5198",
        "http://greggs-macbook-pro:5198",
    ]


def test_iterate_nonzero_exit_marks_failed(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn(record, exit_code=7),
    )
    rc = id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    assert rc == 7
    conn = runs_db.connect(progress_dir / "runs.db")
    try:
        row = runs_db.get_run(conn, "iter_021_cycle")
    finally:
        conn.close()
    assert row["run"]["status"] == "failed"


def test_launch_passes_env_with_runs_db_path(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    """The child iterate subprocess must inherit MTG_BOT_RUN_DB_PATH
    so it can write to the same runs.db the launcher pre-registered
    the cycle in."""
    record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn(record, exit_code=0),
    )
    id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    env = record["env"]
    assert "MTG_BOT_RUN_DB_PATH" in env
    assert (progress_dir / "runs.db").resolve() == Path(
        env["MTG_BOT_RUN_DB_PATH"],
    )


def test_launch_prints_clickable_tailnet_url(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch, capsys,
):
    """The launcher's 'Track in UI: <url>' message must use the
    Tailnet base_url, not localhost. Phase C wires this against the
    canonical training-UI port 5103 (hub's mtg_bot_train_ui_windows
    registration) and prints to stderr so it survives stdout
    redirection."""
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn({}, exit_code=0),
    )
    id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    err = capsys.readouterr().err
    assert (
        "Track in UI: http://desktop-j05412i:5103/run/iter_021_cycle"
        in err
    )


# ---------------------------------------------------------------------------
# Worker heartbeat verification
# ---------------------------------------------------------------------------


def test_verify_worker_idle_passes_on_idle(monkeypatch):
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        lambda url, timeout=5.0: (200, {"state": "IDLE"}),
    )
    # No exception.
    id_mod.verify_worker_idle("http://h:5198")


def test_verify_worker_idle_raises_on_non_idle(monkeypatch):
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        lambda url, timeout=5.0: (200, {"state": "BUSY"}),
    )
    with pytest.raises(id_mod.WorkerNotIdleError, match="BUSY"):
        id_mod.verify_worker_idle("http://h:5198")


def test_verify_worker_idle_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        lambda url, timeout=5.0: (503, {}),
    )
    with pytest.raises(id_mod.WorkerNotIdleError, match="HTTP 503"):
        id_mod.verify_worker_idle("http://h:5198")


def test_verify_worker_idle_raises_on_network_error(monkeypatch):
    import urllib.error

    def boom(url, timeout=5.0):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(id_mod, "_http_get_json", boom)
    with pytest.raises(id_mod.WorkerNotIdleError, match="heartbeat GET failed"):
        id_mod.verify_worker_idle("http://h:5198")


def test_skip_worker_verify_does_not_call_heartbeat(
    minimal_toml: Path, progress_dir: Path, runs_db_env: Path, monkeypatch,
):
    """--skip-worker-verify must bypass even the IDLE check."""
    def fail(url):
        raise AssertionError(
            f"verify_worker_idle({url}) called despite --skip-worker-verify",
        )

    monkeypatch.setattr(id_mod, "verify_worker_idle", fail)
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn({}, exit_code=0),
    )
    rc = id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
        "--skip-worker-verify",
    ])
    assert rc == 0


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


def test_dispatcher_registers_iterate_distributed():
    """The top-level mtg_bot.cli dispatcher must know about the
    iterate-distributed subcommand."""
    from mtg_bot.cli import _SUBCOMMANDS, _DESCRIPTIONS
    assert "iterate-distributed" in _SUBCOMMANDS
    assert _SUBCOMMANDS["iterate-distributed"] == (
        "mtg_bot.cli.iterate_distributed"
    )
    assert "iterate-distributed" in _DESCRIPTIONS


# ---------------------------------------------------------------------------
# collect_worker_urls helper
# ---------------------------------------------------------------------------


def test_collect_worker_urls_skips_unset(tmp_path: Path):
    from mtg_bot.launcher.config import load_config
    toml = tmp_path / "launch.toml"
    toml.write_text("""
[iter]
target_iter = 1

[cluster]
local_only = true
master_url = "http://h1:5198"
win10_url = "http://h2:5198"
# mac_url omitted -- only h1 + h2 should appear.
""", encoding="utf-8")
    cfg = load_config(toml)
    urls = id_mod.collect_worker_urls(cfg)
    assert urls == ["http://h1:5198", "http://h2:5198"]
