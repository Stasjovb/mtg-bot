"""Tests for the unified distributed-iter launcher CLI.

The launcher's job is to glue config + state + lifecycle + iterate
spawn together; these tests drive the orchestrator with stub
subprocess + monkeypatched heartbeat to exercise the full launch
flow without bringing up real workers.
"""
from __future__ import annotations

import json
import os
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
        lambda url, **kwargs: {"state": "IDLE", "git_commit": "deadbee"},
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
    # The launcher's --progress-dir must reach iterate: its stage
    # progress JSONs and .STOP_<run_id> sentinels live there.
    assert f"--progress-dir {progress_dir}" in out


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


def test_launch_defaults_runs_db_url_to_queue_url_when_unset(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    monkeypatch,
):
    """When neither MTG_BOT_RUN_DB_URL nor MTG_BOT_RUN_DB_PATH is set
    in the caller's env, the launcher must default URL transport to
    the coord (queue_url == http://<master>:5099) so the launcher's
    own cycle_lifecycle calls AND the child iterate subprocess both
    write to the coord-owned runs.db. Without this default, a
    worktree-launched run silently writes to a worktree-local runs.db
    that the UI never reads, leaving the cycle row stuck at its prior
    value -- observed live during iter_020 demo."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    record: dict[str, Any] = {}
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn(record, exit_code=0),
    )
    id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    # Subprocess env carries the URL pointing at the coord (port 5099
    # on the master derived from cluster.master_url's host).
    env = record["env"]
    assert env.get("MTG_BOT_RUN_DB_URL") == "http://desktop-j05412i:5099"
    # And the launcher's own os.environ now has it (the runs.client
    # reads fresh from os.environ on each call -- subsequent
    # cycle_lifecycle invocations within the same process will see it).
    assert os.environ.get("MTG_BOT_RUN_DB_URL") == "http://desktop-j05412i:5099"


def test_launch_respects_explicit_runs_db_path_when_set(
    minimal_toml: Path, progress_dir: Path, stub_heartbeat,
    runs_db_env: Path, monkeypatch,
):
    """When the operator sets MTG_BOT_RUN_DB_PATH explicitly, the
    launcher's queue_url default must NOT override it -- operator
    intent (e.g. a per-cycle scratch DB) wins. The fixture
    ``runs_db_env`` already sets PATH; assert URL stays unset."""
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
    # PATH preserved, URL never set.
    assert "MTG_BOT_RUN_DB_PATH" in env
    assert "MTG_BOT_RUN_DB_URL" not in env


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
        "Track in UI: http://desktop-j05412i:5103/#card-iter_021_cycle"
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


# ---------------------------------------------------------------------------
# null:// artifact storage pre-flight
#
# 2026-09-23: both production daemons ran on the ``--artifact-storage-uri
# null://`` default. 500 games completed, the coordinator's stage view
# reported n_games_done=500 / ~1M samples, and zero .npz files existed.
# The launcher now refuses to dispatch to a worker that advertises the
# null:// default.
# ---------------------------------------------------------------------------


def test_verify_worker_idle_rejects_null_artifact_storage(monkeypatch):
    monkeypatch.delenv(id_mod.ALLOW_NULL_ARTIFACTS_ENV, raising=False)
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        lambda url, timeout=5.0: (
            200, {"state": "IDLE", "artifact_storage_uri": "null://"},
        ),
    )
    with pytest.raises(id_mod.WorkerDropsArtifactsError) as exc:
        id_mod.verify_worker_idle("http://h:5198")
    msg = str(exc.value)
    assert "drops artifacts" in msg
    assert "artifact_storage_uri=null://" in msg
    assert "--artifact-storage-uri file://" in msg
    assert "http://<coordinator>:5099" in msg


def test_worker_drops_artifacts_error_is_a_worker_not_idle_error():
    """Callers that already catch the launcher's pre-flight failure
    keep working without a new except clause."""
    assert issubclass(
        id_mod.WorkerDropsArtifactsError, id_mod.WorkerNotIdleError,
    )


def test_verify_worker_idle_allows_null_artifacts_with_env_override(
    monkeypatch, capsys,
):
    monkeypatch.setenv(id_mod.ALLOW_NULL_ARTIFACTS_ENV, "1")
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        lambda url, timeout=5.0: (
            200, {"state": "IDLE", "artifact_storage_uri": "null://"},
        ),
    )
    id_mod.verify_worker_idle("http://h:5198")
    assert "WARNING" in capsys.readouterr().err


@pytest.mark.parametrize(
    "uri",
    [
        "file:///C:/Users/Gregg Keithley/mtg_bot_artifacts_s2",
        "http://100.115.252.110:5099",
        "https://coord.example",
        "s3://prod-bucket/artifacts",
    ],
)
def test_verify_worker_idle_accepts_real_storage_schemes(uri, monkeypatch):
    monkeypatch.delenv(id_mod.ALLOW_NULL_ARTIFACTS_ENV, raising=False)
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        lambda url, timeout=5.0: (
            200, {"state": "IDLE", "artifact_storage_uri": uri},
        ),
    )
    id_mod.verify_worker_idle("http://h:5198")


def test_verify_worker_idle_passes_heartbeat_without_the_key(monkeypatch):
    """Old daemons (and every existing test stub) don't send
    ``artifact_storage_uri``. They must keep passing -- we only fail
    on a positively advertised null://."""
    monkeypatch.delenv(id_mod.ALLOW_NULL_ARTIFACTS_ENV, raising=False)
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        lambda url, timeout=5.0: (200, {"state": "IDLE"}),
    )
    id_mod.verify_worker_idle("http://h:5198")


@pytest.mark.parametrize("value", [None, 123, ""])
def test_verify_artifact_storage_ignores_non_string_values(value):
    """Defensive: a malformed heartbeat field must not crash the
    pre-flight with a TypeError."""
    id_mod._verify_worker_artifact_storage(
        "http://h:5198", {"artifact_storage_uri": value},
    )


def test_skip_worker_verify_does_not_call_heartbeat(
    minimal_toml: Path, progress_dir: Path, runs_db_env: Path, monkeypatch,
):
    """--skip-worker-verify must bypass even the IDLE check."""
    def fail(url, **kwargs):
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


# ---------------------------------------------------------------------------
# Stale-worker pre-flight
#
# A worker daemon caches its checkout SHA at process start and reports
# it as ``git_commit``. A daemon that was never restarted after a merge
# silently generates an entire cycle from old code -- indistinguishable
# from a current one on every other heartbeat field.
# ---------------------------------------------------------------------------


def _hb(**extra):
    """Heartbeat stub: IDLE + real artifact storage unless overridden."""
    body = {
        "state": "IDLE",
        "artifact_storage_uri": "file:///tmp/artifacts",
    }
    body.update(extra)
    return lambda url, timeout=5.0: (200, body)


def test_verify_worker_idle_accepts_matching_commit(monkeypatch):
    monkeypatch.delenv(id_mod.ALLOW_STALE_WORKERS_ENV, raising=False)
    monkeypatch.setattr(id_mod, "_http_get_json", _hb(git_commit="abc1234"))
    body = id_mod.verify_worker_idle(
        "http://h:5198", expected_commit="abc1234",
    )
    # The heartbeat body comes back so the caller can print the banner.
    assert body["git_commit"] == "abc1234"


@pytest.mark.parametrize(
    ("worker", "expected"),
    [
        ("abc1234", "abc12345"),   # launcher's --short is longer
        ("abc12345", "abc1234"),   # worker's is longer
        ("ABC1234", "abc1234"),    # case-insensitive
    ],
)
def test_verify_worker_idle_matches_on_the_shorter_prefix(
    worker, expected, monkeypatch,
):
    """``git rev-parse --short`` picks whatever length is unambiguous;
    the daemon hard-truncates to 7. Same commit, different strings."""
    monkeypatch.delenv(id_mod.ALLOW_STALE_WORKERS_ENV, raising=False)
    monkeypatch.setattr(id_mod, "_http_get_json", _hb(git_commit=worker))
    id_mod.verify_worker_idle("http://h:5198", expected_commit=expected)


def test_verify_worker_idle_rejects_stale_commit(monkeypatch):
    monkeypatch.delenv(id_mod.ALLOW_STALE_WORKERS_ENV, raising=False)
    monkeypatch.setattr(id_mod, "_http_get_json", _hb(git_commit="0ldc0de"))
    with pytest.raises(id_mod.WorkerStaleCommitError) as exc:
        id_mod.verify_worker_idle(
            "http://h:5198", expected_commit="feedbee",
        )
    msg = str(exc.value)
    # Names the worker, its commit, the expected commit, the remedy.
    assert "http://h:5198" in msg
    assert "0ldc0de" in msg
    assert "feedbee" in msg
    assert "/v2/self_update" in msg
    assert "restart the daemon" in msg
    assert "--allow-stale-workers" in msg


def test_worker_stale_commit_error_is_a_worker_not_idle_error():
    assert issubclass(
        id_mod.WorkerStaleCommitError, id_mod.WorkerNotIdleError,
    )


def test_verify_worker_idle_allows_stale_with_flag(monkeypatch, capsys):
    monkeypatch.delenv(id_mod.ALLOW_STALE_WORKERS_ENV, raising=False)
    monkeypatch.setattr(id_mod, "_http_get_json", _hb(git_commit="0ldc0de"))
    id_mod.verify_worker_idle(
        "http://h:5198", expected_commit="feedbee", allow_stale=True,
    )
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "0ldc0de" in err


def test_verify_worker_idle_allows_stale_with_env_override(
    monkeypatch, capsys,
):
    monkeypatch.setenv(id_mod.ALLOW_STALE_WORKERS_ENV, "1")
    monkeypatch.setattr(id_mod, "_http_get_json", _hb(git_commit="0ldc0de"))
    id_mod.verify_worker_idle(
        "http://h:5198", expected_commit="feedbee",
    )
    assert "WARNING" in capsys.readouterr().err


def test_verify_worker_idle_warns_when_heartbeat_has_no_commit(
    monkeypatch, capsys,
):
    """Pre-self-update daemons and test stubs don't report
    ``git_commit`` -- they pass, loudly."""
    monkeypatch.delenv(id_mod.ALLOW_STALE_WORKERS_ENV, raising=False)
    monkeypatch.setattr(id_mod, "_http_get_json", _hb())
    id_mod.verify_worker_idle("http://h:5198", expected_commit="feedbee")
    err = capsys.readouterr().err
    assert "does not report git_commit" in err


@pytest.mark.parametrize("value", [None, 123, "", "   "])
def test_verify_worker_commit_tolerates_malformed_values(
    value, monkeypatch, capsys,
):
    monkeypatch.delenv(id_mod.ALLOW_STALE_WORKERS_ENV, raising=False)
    id_mod._verify_worker_commit(
        "http://h:5198", {"git_commit": value},
        expected_commit="feedbee", allow_stale=False,
    )
    assert "cannot verify" in capsys.readouterr().err


def test_verify_worker_commit_warns_when_launcher_commit_unknown(
    capsys,
):
    """A non-git deploy must not block every launch."""
    id_mod._verify_worker_commit(
        "http://h:5198", {"git_commit": "0ldc0de"},
        expected_commit=None, allow_stale=False,
    )
    assert "cannot resolve the launcher" in capsys.readouterr().err


def test_resolve_expected_commit_prefers_git(monkeypatch):
    monkeypatch.setattr(id_mod, "_launcher_repo_commit", lambda: "gitsha1")
    monkeypatch.setenv(id_mod.EXPECTED_COMMIT_ENV, "envsha1")
    assert id_mod.resolve_expected_commit() == "gitsha1"


def test_resolve_expected_commit_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(id_mod, "_launcher_repo_commit", lambda: None)
    monkeypatch.setenv(id_mod.EXPECTED_COMMIT_ENV, "envsha1")
    assert id_mod.resolve_expected_commit() == "envsha1"


def test_resolve_expected_commit_is_none_without_git_or_env(monkeypatch):
    monkeypatch.setattr(id_mod, "_launcher_repo_commit", lambda: None)
    monkeypatch.delenv(id_mod.EXPECTED_COMMIT_ENV, raising=False)
    assert id_mod.resolve_expected_commit() is None


def test_launcher_repo_commit_returns_none_when_git_is_missing(
    monkeypatch,
):
    def boom(*a, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(id_mod.subprocess, "run", boom)
    assert id_mod._launcher_repo_commit() is None


# ---------------------------------------------------------------------------
# ERROR is its own failure, not "not IDLE"
# ---------------------------------------------------------------------------


def test_verify_worker_idle_reports_parked_error_distinctly(monkeypatch):
    monkeypatch.setattr(
        id_mod, "_http_get_json",
        _hb(state="ERROR", error="claim loop thread 3 crashed: ..."),
    )
    with pytest.raises(id_mod.WorkerParkedInErrorError) as exc:
        id_mod.verify_worker_idle("http://h:5198")
    msg = str(exc.value)
    assert "parked in ERROR" in msg
    assert "restart it" in msg
    # NOT the generic draining advice.
    assert "may still be draining" not in msg


def test_worker_parked_in_error_is_a_worker_not_idle_error():
    assert issubclass(
        id_mod.WorkerParkedInErrorError, id_mod.WorkerNotIdleError,
    )


def test_non_idle_non_error_still_gets_the_draining_message(monkeypatch):
    monkeypatch.setattr(
        id_mod, "_http_get_json", _hb(state="SELF_PLAY_RUNNING"),
    )
    with pytest.raises(id_mod.WorkerNotIdleError) as exc:
        id_mod.verify_worker_idle("http://h:5198")
    assert "may still be draining" in str(exc.value)
    assert not isinstance(exc.value, id_mod.WorkerParkedInErrorError)


# ---------------------------------------------------------------------------
# Launch banner + flag plumbing
# ---------------------------------------------------------------------------


def test_launch_banner_prints_every_worker_commit(
    minimal_toml: Path, progress_dir: Path, runs_db_env: Path,
    monkeypatch, capsys,
):
    seen: list[tuple[str, object, object]] = []

    def stub(url, *, expected_commit=None, allow_stale=False):
        seen.append((url, expected_commit, allow_stale))
        return {"state": "IDLE", "git_commit": "abc1234"}

    monkeypatch.setattr(id_mod, "verify_worker_idle", stub)
    monkeypatch.setattr(id_mod, "resolve_expected_commit", lambda: "abc1234")
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn({}, exit_code=0),
    )
    rc = id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
    ])
    assert rc == 0
    assert seen, "verify_worker_idle was never called"
    # The resolved expectation is threaded through to every worker.
    assert all(entry[1] == "abc1234" for entry in seen)
    assert all(entry[2] is False for entry in seen)
    err = capsys.readouterr().err
    for url, _, _ in seen:
        assert f"worker {url} commit=abc1234" in err
    assert "launcher commit=abc1234" in err


def test_allow_stale_workers_flag_reaches_the_pre_flight(
    minimal_toml: Path, progress_dir: Path, runs_db_env: Path,
    monkeypatch,
):
    seen: list[bool] = []

    def stub(url, *, expected_commit=None, allow_stale=False):
        seen.append(allow_stale)
        return {"state": "IDLE", "git_commit": "abc1234"}

    monkeypatch.setattr(id_mod, "verify_worker_idle", stub)
    monkeypatch.setattr(
        id_mod, "spawn_iterate_subprocess", _stub_spawn({}, exit_code=0),
    )
    rc = id_mod.main([
        "--config", str(minimal_toml),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/decks.json.gz",
        "--allow-stale-workers",
    ])
    assert rc == 0
    assert seen and all(seen)


def test_stale_worker_aborts_the_launch(
    minimal_toml: Path, progress_dir: Path, runs_db_env: Path,
    monkeypatch,
):
    """The whole point: a stale worker stops the cycle before any
    subprocess is spawned."""
    def stub(url, *, expected_commit=None, allow_stale=False):
        raise id_mod.WorkerStaleCommitError(
            f"worker {url} is running commit 0ldc0de",
        )

    monkeypatch.setattr(id_mod, "verify_worker_idle", stub)

    def never(*a, **kw):  # pragma: no cover - must not run
        raise AssertionError("iterate was spawned despite a stale worker")

    monkeypatch.setattr(id_mod, "spawn_iterate_subprocess", never)
    with pytest.raises(id_mod.WorkerStaleCommitError):
        id_mod.main([
            "--config", str(minimal_toml),
            "--progress-dir", str(progress_dir),
            "--deck-pool", "data/decks.json.gz",
        ])
