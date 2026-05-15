"""Tests that ``_build_remote_pull_command`` /
``_build_remote_eval_command`` inject the ``MTG_BOT_RUN_DB_URL``
env var into the remote command string so SSH-launched shards
can talk to the master's runs.db REST endpoints.

The URL must be sourced from the existing ``--queue-url`` arg (the
master's ``mtg_bot serve`` process serves both ``/queue/...`` and
``/run/...`` on port 5099), NOT hardcoded — the master's tailnet
hostname can shift between ``desktop-j05412i`` and
``desktop-j05412i-wsl`` depending on the cutover state.

Also covers the master-side ``MTG_BOT_RUN_DB_PATH`` default helper
that distributed runners use to make sure the master process has
the env var set before forking workers.
"""

from __future__ import annotations

import os

from mtg_bot.training.distributed import (
    EvalJobSpec,
    SelfPlayJobSpec,
    ShardConfig,
    _build_remote_eval_command,
    _build_remote_pull_command,
    _ensure_master_runs_db_path_default,
    _runs_db_url_env_for_remote,
    _DEFAULT_MASTER_RUNS_DB_PATH,
)


def _self_play_spec() -> SelfPlayJobSpec:
    return SelfPlayJobSpec(
        weights_path="trained_weights/v1/weights.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42,
        per_game_timeout_sec=300.0,
    )


def _eval_spec() -> EvalJobSpec:
    return EvalJobSpec(
        new_weights_path="trained_weights/v2/weights.pt",
        old_weights_path="trained_weights/v1/weights.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42,
        per_game_timeout_sec=300.0,
    )


def _posix_shard() -> ShardConfig:
    return ShardConfig(
        host="macbook", user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )


def _windows_shard() -> ShardConfig:
    return ShardConfig(
        host="win-box", user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )


def test_pull_command_posix_injects_run_db_url_env():
    """POSIX shells accept the ``VAR=val cmd`` single-shot env form.
    The command should prepend ``MTG_BOT_RUN_DB_URL=<queue_url> ``
    before the python invocation so the SSH-launched shard's
    ``runs.client`` resolution sees the master URL."""
    cmd = _build_remote_pull_command(
        _posix_shard(), _self_play_spec(),
        queue_url="http://desktop-j05412i:5099",
        run_id="iter_001", iter_total_games=500,
        stamp="20260511T000000Z",
    )
    # The env var precedes PYTHONPATH on the python invocation.
    # ``shlex.quote`` leaves URLs that contain no shell metachars
    # unquoted, so the literal ``MTG_BOT_RUN_DB_URL=<url>`` is
    # what we expect in the emitted command (not single-quoted).
    assert "MTG_BOT_RUN_DB_URL=http://desktop-j05412i:5099" in cmd
    # The env injection comes after cd but before PYTHONPATH (so the
    # var actually flows to the child python). Verify ordering.
    idx_cd = cmd.index("cd /Users/g/repo")
    idx_db = cmd.index("MTG_BOT_RUN_DB_URL")
    idx_pp = cmd.index("PYTHONPATH=src")
    assert idx_cd < idx_db < idx_pp


def test_pull_command_windows_injects_run_db_url_env():
    """Windows cmd.exe lacks the POSIX ``VAR=val cmd`` form — must use
    ``set VAR=val && cmd``. Verify the ``set`` form lands on the
    Windows path."""
    cmd = _build_remote_pull_command(
        _windows_shard(), _self_play_spec(),
        queue_url="http://desktop-j05412i:5099",
        run_id="iter_001", iter_total_games=500,
        stamp="20260511T000000Z",
    )
    assert "set MTG_BOT_RUN_DB_URL=http://desktop-j05412i:5099 &&" in cmd
    # Order: cd → set PYTHONPATH → set MTG_BOT_RUN_DB_URL → python.
    # That keeps the existing PYTHONPATH wiring untouched.
    idx_cd = cmd.index("cd /d")
    idx_pp = cmd.index("set PYTHONPATH=src")
    idx_db = cmd.index("set MTG_BOT_RUN_DB_URL")
    idx_py = cmd.index(".venv-py313\\Scripts\\python.exe")
    assert idx_cd < idx_pp < idx_db < idx_py


def test_eval_command_posix_injects_run_db_url_env():
    """Eval-mode path: same env injection as the self-play path. The
    eval shard also wants the runs.db URL so its per-shard run row
    lands on the master."""
    cmd = _build_remote_eval_command(
        _posix_shard(), _eval_spec(),
        queue_url="http://desktop-j05412i-wsl:5099",
        run_id="iter_001_eval", iter_total_games=500,
        stamp="20260511T000000Z",
    )
    assert "MTG_BOT_RUN_DB_URL=http://desktop-j05412i-wsl:5099" in cmd
    assert "--mode=eval" in cmd


def test_eval_command_windows_injects_run_db_url_env():
    cmd = _build_remote_eval_command(
        _windows_shard(), _eval_spec(),
        queue_url="http://master:5099",
        run_id="iter_001_eval", iter_total_games=500,
        stamp="20260511T000000Z",
    )
    assert "set MTG_BOT_RUN_DB_URL=http://master:5099 &&" in cmd
    assert "--mode=eval" in cmd


def test_remote_command_strips_trailing_slash_from_queue_url():
    """Tailscale-side URLs sometimes get a trailing slash from
    bookmark URLs / cli copy-paste. The injected env var should be
    normalized (no trailing slash) so the runs.client appending
    ``/run/start`` doesn't double-slash."""
    cmd = _build_remote_pull_command(
        _posix_shard(), _self_play_spec(),
        queue_url="http://desktop-j05412i:5099/",
        run_id="iter_001", iter_total_games=500,
        stamp="20260511T000000Z",
    )
    # ``--queue-url`` itself keeps the user-provided trailing slash
    # (existing behavior). The RUN_DB_URL env var is stripped of it.
    assert "MTG_BOT_RUN_DB_URL=http://desktop-j05412i:5099 " in cmd
    # The original queue_url with trailing slash is still threaded
    # through unchanged.
    assert "--queue-url=http://desktop-j05412i:5099/" in cmd


def test_runs_db_url_env_returns_none_when_no_queue_url():
    """Empty or None ``queue_url`` -> no env-var injection (rather
    than injecting a broken empty string that would set the var to
    empty on the remote and confuse the resolver)."""
    assert _runs_db_url_env_for_remote("") is None
    assert _runs_db_url_env_for_remote(None) is None


def test_runs_db_url_env_strips_trailing_slash():
    """Caller-provided URL gets normalized before injection."""
    assert (
        _runs_db_url_env_for_remote("http://m:5099/")
        == "http://m:5099"
    )
    assert (
        _runs_db_url_env_for_remote("http://m:5099")
        == "http://m:5099"
    )


def test_ensure_master_runs_db_path_default_sets_when_unset(monkeypatch):
    """Defensive default for master-side processes: if no caller has
    set ``MTG_BOT_RUN_DB_PATH``, point it at
    ``training_progress/runs.db`` so the runs.db rows actually land."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    _ensure_master_runs_db_path_default()
    assert (
        os.environ["MTG_BOT_RUN_DB_PATH"]
        == _DEFAULT_MASTER_RUNS_DB_PATH
    )


def test_ensure_master_runs_db_path_default_respects_user_value(
    monkeypatch,
):
    """The helper is setdefault-style — an explicit user value
    survives the call."""
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", "custom/runs.db")
    _ensure_master_runs_db_path_default()
    assert os.environ["MTG_BOT_RUN_DB_PATH"] == "custom/runs.db"


def test_ensure_master_runs_db_path_default_respects_explicit_empty(
    monkeypatch,
):
    """Explicit empty string is the project convention for
    ``--hang-dump-dir ''`` style opt-outs. Empty IS a value the user
    set; the helper must not stomp it. Empty maps to "DB disabled"
    via the resolver in :mod:`mtg_bot.cli.runs.client`."""
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", "")
    _ensure_master_runs_db_path_default()
    assert os.environ["MTG_BOT_RUN_DB_PATH"] == ""
