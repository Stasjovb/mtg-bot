"""Regression tests for the local-shard run-DB lifecycle wrap.

Layered tests covering two contracts:

**Layer 1 — direct helper tests.** ``dist._local_shard_run_lifecycle``
still exists as a context manager that opens / closes a per-shard
``runs`` row. These tests exercise the helper in isolation and
remain green; the helper itself is a reusable primitive that the
SSH-launched ``cli/shard.py`` analog uses on the remote side.

**Layer 2 — end-to-end contract via the orchestrator.** Phase 2
removed the call site of ``_local_shard_run_lifecycle`` inside
``run_distributed_self_play`` / ``run_distributed_eval``. The
local shard no longer gets a per-shard ``runs`` row from the
master process — it lands a ``run_progress`` row keyed by
``shard_label='local'`` (under the master ``run_id``) instead.
This matches the remote contract: the orchestrator never writes
per-shard ``runs`` rows; for remotes, ``cli/shard.py`` does that
write SSH-side. Downstream tooling (UI shard rollups, cycle-replay
aggregator) enumerates shards via ``run_progress.shard_label``
rather than ``runs.parent_run_id`` — see
``training_ui/app._cycle_replays_payload`` and
``_per_shard_to_machines``.

The Layer 2 tests below assert the Phase 2 contract:

1. Self-play: a ``run_progress`` row for the local shard lands
   under the master ``run_id``; no per-shard ``runs`` row is
   written.
2. Eval: same shape, eval counters.
3. Self-play with a remote shard alongside local: NEITHER per-
   shard ``runs`` row is created by the master process.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from mtg_bot.cli.runs import client as runs_client
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs import lifecycle as runs_lifecycle
from mtg_bot.training import distributed as dist
from mtg_bot.training.distributed import (
    EvalJobSpec,
    SelfPlayJobSpec,
    ShardConfig,
    ShardsConfig,
)


def _self_play_spec() -> SelfPlayJobSpec:
    return SelfPlayJobSpec(
        weights_path="trained_weights/v1/weights.pt",
        samples=2, inner_nodes=10, hidden_sizes=(8,),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=30.0,
    )


def _eval_spec() -> EvalJobSpec:
    return EvalJobSpec(
        new_weights_path="trained_weights/v2/weights.pt",
        old_weights_path="trained_weights/v1/weights.pt",
        samples=2, inner_nodes=10, hidden_sizes=(8,),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=30.0,
        opponent_label="v1",
    )


# ---- direct helper coverage --------------------------------------


def test_local_shard_run_lifecycle_creates_per_shard_run_row(
    tmp_path: Path, monkeypatch,
):
    """The shared helper :func:`_local_shard_run_lifecycle` should
    register a per-shard ``runs`` row keyed on ``f"{master}_shard_
    {label}"`` with ``parent_run_id=master`` and the supplied
    ``kind`` / ``label``. Mirrors what
    :mod:`mtg_bot.cli.shard._run_pull_shard` does for SSH-launched
    remotes."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(
        runs_lifecycle, "git_commit_short", lambda: "abc1234",
    )
    # Seed the master row so the parent_run_id FK is satisfied
    # exactly the way iterate / run_distributed_self_play does.
    runs_client.start_run(
        "iter_009_self_play_v3",
        kind="self_play", config_json="{}", git_commit="parent",
    )

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    with dist._local_shard_run_lifecycle(
        master_run_id="iter_009_self_play_v3",
        label="local",
        kind="self_play",
        progress_dir=progress_dir,
        iter_total_games=4,
        spec=_self_play_spec(),
        queue_url="http://127.0.0.1:5099",
    ):
        # No work inside — just verifying the lifecycle bookends.
        pass

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_009_self_play_v3_shard_local",),
        ))
    finally:
        conn.close()

    assert len(rows) == 1, (
        "expected the per-shard runs row for local to exist "
        "after the lifecycle wrap"
    )
    row = rows[0]
    assert row["run_id"] == "iter_009_self_play_v3_shard_local"
    assert row["kind"] == "self_play"
    assert row["parent_run_id"] == "iter_009_self_play_v3"
    assert row["label"] == "local"
    # Normal exit -> "completed". The wrapper would map an exception
    # to "failed" / KeyboardInterrupt to "killed"; that mapping
    # lives in cli/runs/lifecycle.py and is covered there.
    assert row["status"] == "completed"
    assert row["git_commit"] == "abc1234"
    cfg = json.loads(row["config_json"])
    assert cfg["run_id"] == "iter_009_self_play_v3"
    assert cfg["shard_label"] == "local"
    assert cfg["shard_host"] == "local"
    assert cfg["iter_total_games"] == 4


def test_local_shard_run_lifecycle_eval_kind(
    tmp_path: Path, monkeypatch,
):
    """Same helper, ``kind="eval"`` path: the per-shard row should
    pick up the eval kind so dashboard roll-ups treat it as eval
    work alongside SSH-launched eval shards."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(
        runs_lifecycle, "git_commit_short", lambda: "evalsha",
    )
    runs_client.start_run(
        "iter_009_eval_v3_vs_v2",
        kind="eval", config_json="{}", git_commit="parent",
    )

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    with dist._local_shard_run_lifecycle(
        master_run_id="iter_009_eval_v3_vs_v2",
        label="local",
        kind="eval",
        progress_dir=progress_dir,
        iter_total_games=6,
        spec=_eval_spec(),
        queue_url="http://127.0.0.1:5099",
    ):
        pass

    conn = runs_db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_009_eval_v3_vs_v2_shard_local",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["kind"] == "eval"
    assert row["parent_run_id"] == "iter_009_eval_v3_vs_v2"
    assert row["label"] == "local"
    cfg = json.loads(row["config_json"])
    # Eval spec uses new/old, not a single weights_path.
    assert cfg["new_weights_path"] == "trained_weights/v2/weights.pt"
    assert cfg["old_weights_path"] == "trained_weights/v1/weights.pt"


def test_local_shard_run_lifecycle_is_noop_without_db(
    tmp_path: Path, monkeypatch,
):
    """When neither ``MTG_BOT_RUN_DB_PATH`` nor
    ``MTG_BOT_RUN_DB_URL`` is set, the helper should be a silent
    no-op — the lifecycle CM still works (so the runner body
    executes), but no DB writes are attempted. Same Phase 1
    invariant the rest of the runs.client layer maintains."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    # Without a configured DB, this must not raise and must not
    # require the master row to exist.
    with dist._local_shard_run_lifecycle(
        master_run_id="iter_unconfigured",
        label="local",
        kind="self_play",
        progress_dir=progress_dir,
        iter_total_games=4,
        spec=_self_play_spec(),
        queue_url="http://127.0.0.1:5099",
    ):
        pass


# ---- end-to-end via run_distributed_self_play --------------------


def _stub_run_shard_pull(spec, **kwargs):
    """Stand-in for the heavy worker-pool body. Echoes a per-shard
    ``run_progress`` push under the master ``run_id`` (matching the
    real runner's post-cutover behavior) and writes a tiny event-log
    so the events.jsonl post-conditions in surrounding tests
    continue to be checkable if needed."""
    run_id = kwargs["run_id"]
    label = kwargs["label"]
    iter_total_games = kwargs["iter_total_games"]
    progress_dir = kwargs.get("progress_dir")
    if progress_dir is not None:
        events_path = (
            progress_dir / f"{run_id}_shard_{label}_events.jsonl"
        )
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(
            json.dumps({"event": "shard_start", "label": label}) + "\n",
            encoding="utf-8",
        )
    # Two upserts under the master row to verify the second one
    # doesn't FK-fail (proves there's no "silent FK failure on
    # subsequent push" mode in play).
    runs_client.push_progress(
        run_id, shard_label=label,
        n_games_done=1, n_games_total=iter_total_games,
        elapsed_seconds=0.5,
    )
    runs_client.push_progress(
        run_id, shard_label=label,
        n_games_done=2, n_games_total=iter_total_games,
        elapsed_seconds=1.5,
    )
    return []


def _stub_run_shard_eval_pull(spec, **kwargs):
    run_id = kwargs["run_id"]
    label = kwargs["label"]
    iter_total_games = kwargs["iter_total_games"]
    runs_client.push_progress(
        run_id, shard_label=label,
        n_games_done=1, n_games_total=iter_total_games,
        wins_new=1, wins_old=0, draws=0, crashed=0,
        elapsed_seconds=0.5,
    )
    runs_client.push_progress(
        run_id, shard_label=label,
        n_games_done=3, n_games_total=iter_total_games,
        wins_new=2, wins_old=1, draws=0, crashed=0,
        elapsed_seconds=1.5,
    )
    return {
        "n_games": 3,
        "wins_new": 2, "wins_old": 1,
        "draws": 0, "crashed": 0, "timed_out": 0,
    }


def _no_op_aggregator_start(self):
    """Disable the background poller so the test doesn't race
    against thread cleanup. The poller would otherwise spin on
    timer-driven DB reads."""


def _no_op_aggregator_stop(self, status):
    """Pair to :func:`_no_op_aggregator_start`."""


def _no_op_queue_init(*args, **kwargs):
    """Skip the queue-server init call — the stubbed runners don't
    use the queue and there's no server listening in this test."""
    return dist._QueueHTTPResponse(status=200, body=b"{}")


def test_run_distributed_self_play_local_shard_progress_only(
    tmp_path: Path, monkeypatch,
):
    """End-to-end: a local self-play shard launched through
    :func:`run_distributed_self_play` lands a ``run_progress`` row
    keyed off the master ``run_id`` + ``shard_label='local'`` but
    does NOT register its own per-shard ``runs`` row.

    Phase 2 reverses the earlier per-shard-row contract: the local-
    shard lifecycle wrap was removed from ``run_distributed_self_play``
    to match the SSH-launched remote contract (which also writes only
    a ``run_progress`` row from the master side; the canonical
    ``runs`` row for remotes is written by ``cli/shard.py`` running
    SSH-side). Downstream tooling enumerates shards via
    ``run_progress.shard_label``, not ``runs.parent_run_id``."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    progress_dir = tmp_path / "training_progress"
    output_dir = tmp_path / "iterate_data"

    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_workers=1),
    ))
    spec = _self_play_spec()

    with patch.object(dist, "run_shard_pull", _stub_run_shard_pull), \
         patch.object(
             dist._AggregateProgressPoller, "start",
             _no_op_aggregator_start,
         ), \
         patch.object(
             dist._AggregateProgressPoller, "stop",
             _no_op_aggregator_stop,
         ), \
         patch.object(dist, "_urlopen_with_retry", _no_op_queue_init):
        dist.run_distributed_self_play(
            cfg, spec,
            progress_dir=progress_dir,
            output_dir=output_dir,
            run_id_prefix="iter_010_self_play_v4",
            total_games=4,
            queue_url="http://127.0.0.1:5099",
        )

    conn = runs_db.connect(db_path)
    try:
        shard_runs = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_010_self_play_v4_shard_local",),
        ))
        progress = list(conn.execute(
            "SELECT * FROM run_progress "
            "WHERE run_id = ? AND shard_label = ?",
            ("iter_010_self_play_v4", "local"),
        ))
        master_runs = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_010_self_play_v4",),
        ))
    finally:
        conn.close()

    # The headline assertion: NO per-shard runs row for local. Phase 2
    # removed the local-shard lifecycle wrap so the master process no
    # longer pre-registers it (matches the remote contract — cli/shard.py
    # is the canonical per-shard runs-row creator, and for local there
    # is no cli/shard.py invocation).
    assert len(shard_runs) == 0, (
        "Phase 2 contract: the orchestrator must not register a "
        "per-shard runs row for the local shard; shard enumeration "
        "uses run_progress.shard_label instead"
    )

    # The run_progress row DOES land (canonical path post-Phase 2).
    assert len(progress) == 1
    assert progress[0]["shard_label"] == "local"
    # Two push_progress calls -> the second overwrites; final state
    # reflects the most recent counters. Proves no silent FK failure
    # on subsequent pushes.
    assert progress[0]["n_games_done"] == 2
    assert progress[0]["n_games_total"] == 4

    # The master run row also exists (defense-in-depth ensure call
    # at the top of run_distributed_self_play creates it).
    assert len(master_runs) == 1


def test_run_distributed_eval_local_shard_progress_only(
    tmp_path: Path, monkeypatch,
):
    """Eval counterpart of the Phase 2 contract: only a
    ``run_progress`` row lands for the local shard; no per-shard
    ``runs`` row is registered by the orchestrator."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    progress_dir = tmp_path / "training_progress"

    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_workers=1),
    ))
    spec = _eval_spec()

    with patch.object(
        dist, "run_shard_eval_pull", _stub_run_shard_eval_pull,
    ), patch.object(
        dist._AggregateProgressPoller, "start",
        _no_op_aggregator_start,
    ), patch.object(
        dist._AggregateProgressPoller, "stop",
        _no_op_aggregator_stop,
    ), patch.object(
        dist, "_urlopen_with_retry", _no_op_queue_init,
    ), patch.object(
        dist, "wait_for_queue_completion",
        lambda *a, **k: {"queues": {}},
    ):
        counts = dist.run_distributed_eval(
            cfg, spec,
            progress_dir=progress_dir,
            run_id_prefix="iter_010_eval_v4_vs_v3",
            total_games=4,
            queue_url="http://127.0.0.1:5099",
            queue_max_wait_s=1.0,
        )

    assert counts["n_games"] == 3  # mirrors stub return

    conn = runs_db.connect(db_path)
    try:
        shard_runs = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_010_eval_v4_vs_v3_shard_local",),
        ))
        progress = list(conn.execute(
            "SELECT * FROM run_progress "
            "WHERE run_id = ? AND shard_label = ?",
            ("iter_010_eval_v4_vs_v3", "local"),
        ))
    finally:
        conn.close()

    # Phase 2: no per-shard runs row for the local shard.
    assert len(shard_runs) == 0

    # The run_progress row carries the latest eval counters and
    # didn't silently drop them on the FK constraint.
    assert len(progress) == 1
    assert progress[0]["wins_new"] == 2
    assert progress[0]["wins_old"] == 1
    assert progress[0]["n_games_done"] == 3


def test_run_distributed_self_play_does_not_register_per_shard_rows(
    tmp_path: Path, monkeypatch,
):
    """Post-Phase 2 the orchestrator does NOT pre-register the
    per-shard ``runs`` row for EITHER local or remote shards. The
    remote's row is written by the SSH-launched ``cli/shard.py``;
    the local shard skips per-shard registration entirely (its
    progress is keyed by ``shard_label='local'`` on the master
    ``run_progress`` row instead). This test guards that symmetry —
    the master process should never write per-shard ``runs`` rows
    from inside ``run_distributed_self_play``.
    """
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    progress_dir = tmp_path / "training_progress"
    output_dir = tmp_path / "iterate_data"

    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_workers=1),
        ShardConfig(
            host="remote-box", label="remote-box",
            user="g", repo_path="/home/g/repo",
            venv_python=".venv-py313/bin/python",
            n_workers=1,
        ),
    ))
    spec = _self_play_spec()

    # Stub the remote runner so it returns a successful report
    # without actually attempting SSH. The point is: when the
    # orchestrator's runner table dispatches to the remote, the
    # MASTER PROCESS does not register the remote's shard row.
    def fake_run_shard_remote(shard, _spec, **kwargs):
        return dist.ShardSelfPlayReport(
            shard_label=shard.display_label,
            success=True, npz_paths=[],
        )

    with patch.object(dist, "run_shard_pull", _stub_run_shard_pull), \
         patch.object(dist, "run_shard_remote", fake_run_shard_remote), \
         patch.object(
             dist._AggregateProgressPoller, "start",
             _no_op_aggregator_start,
         ), \
         patch.object(
             dist._AggregateProgressPoller, "stop",
             _no_op_aggregator_stop,
         ), \
         patch.object(dist, "_urlopen_with_retry", _no_op_queue_init):
        dist.run_distributed_self_play(
            cfg, spec,
            progress_dir=progress_dir,
            output_dir=output_dir,
            run_id_prefix="iter_011_self_play_v5",
            total_games=4,
            queue_url="http://127.0.0.1:5099",
        )

    conn = runs_db.connect(db_path)
    try:
        # Neither per-shard row should exist post-Phase 2.
        local_rows = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_011_self_play_v5_shard_local",),
        ))
        remote_rows = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_011_self_play_v5_shard_remote-box",),
        ))
    finally:
        conn.close()

    assert len(local_rows) == 0, (
        "Phase 2: orchestrator no longer pre-registers the local "
        "shard's runs row"
    )
    assert len(remote_rows) == 0, (
        "the orchestrator must not pre-register the remote shard's "
        "runs row from the master process; cli/shard.py owns that "
        "write under the SSH session"
    )


def test_local_shard_run_lifecycle_marks_failed_on_exception(
    tmp_path: Path, monkeypatch,
):
    """If the wrapped body raises, the per-shard run row should be
    marked ``status='failed'`` (and the exception re-raised so the
    outer ``_local_runner`` catch sees it and emits a
    ``ShardSelfPlayReport(success=False)``). Confirms the
    lifecycle's failure path runs end-to-end for the local shard."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    runs_client.start_run(
        "iter_012_self_play_v6",
        kind="self_play", config_json="{}", git_commit="parent",
    )

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()

    class _Boom(RuntimeError):
        pass

    try:
        with dist._local_shard_run_lifecycle(
            master_run_id="iter_012_self_play_v6",
            label="local",
            kind="self_play",
            progress_dir=progress_dir,
            iter_total_games=4,
            spec=_self_play_spec(),
            queue_url="http://127.0.0.1:5099",
        ):
            raise _Boom("simulated worker crash")
    except _Boom:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected _Boom to propagate")

    conn = runs_db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_012_self_play_v6_shard_local",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["status"] == "failed"
    assert row["notes"] is not None
    assert "_Boom" in row["notes"]
