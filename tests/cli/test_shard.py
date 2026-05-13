"""Tests for ``mtg_bot.cli.shard``'s run-DB lifecycle wiring.

Pins the contract between :mod:`mtg_bot.cli.shard` and
:mod:`mtg_bot.cli.runs.lifecycle`: every shard invocation should
land a per-shard ``runs`` row carrying the right ``kind``,
``parent_run_id``, and ``label`` so the master's runs.db roll-up
works.

The runner-side per-game push (the ``client.push_progress`` calls
inside ``run_shard_pull`` / ``run_shard_eval_pull``) is covered
indirectly here — we stub the runner with a fake that calls
``push_progress`` itself, and verify the rows landed with
``shard_label`` set. The "in production the runner threads the
push under each progress.record_game" half is a 4-line addition
near a flush site; testing it with a real worker pool would
require multiprocessing fixtures we don't otherwise need.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mtg_bot.cli import shard as cli_shard
from mtg_bot.cli.runs import client as runs_client
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs import lifecycle as cli_lifecycle
from mtg_bot.training.distributed import (
    EvalJobSpec,
    SelfPlayJobSpec,
    ShardConfig,
)


def _seed_parent_run(db_path: Path, run_id: str, kind: str) -> None:
    """Pre-create the parent run row so the shard's
    ``parent_run_id`` FK is satisfied. In production the master
    (iterate / eval) lays down the parent row first; tests have to
    fake that ordering."""
    runs_client.start_run(
        run_id, kind=kind,
        config_json="{}", git_commit="parent",
    )


def _b64_json(payload: dict) -> str:
    return base64.b64encode(
        json.dumps(payload).encode("utf-8"),
    ).decode("ascii")


def _make_pull_argv(*, run_id: str, label: str, progress_dir: Path,
                    output_dir: Path) -> list[str]:
    spec = SelfPlayJobSpec(
        weights_path="trained_weights/v1/weights.pt",
        samples=2, inner_nodes=10, hidden_sizes=(8,),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=30.0,
    )
    shard = ShardConfig(host="local", label=label, n_workers=1)
    return [
        "--mode=pull",
        f"--spec-b64={_b64_json(spec.to_dict())}",
        f"--shard-b64={_b64_json(shard.to_dict())}",
        "--queue-url=http://master:5099",
        f"--run-id={run_id}",
        "--iter-total-games=4",
        "--stamp=20260511T000000Z",
        f"--output-dir={output_dir}",
        f"--progress-dir={progress_dir}",
    ]


def _make_eval_argv(*, run_id: str, label: str, progress_dir: Path,
                    output_dir: Path) -> list[str]:
    spec = EvalJobSpec(
        new_weights_path="trained_weights/v2/weights.pt",
        old_weights_path="trained_weights/v1/weights.pt",
        samples=2, inner_nodes=10, hidden_sizes=(8,),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=30.0,
    )
    shard = ShardConfig(host="local", label=label, n_workers=1)
    return [
        "--mode=eval",
        f"--spec-b64={_b64_json(spec.to_dict())}",
        f"--shard-b64={_b64_json(shard.to_dict())}",
        "--queue-url=http://master:5099",
        f"--run-id={run_id}",
        "--iter-total-games=4",
        "--stamp=20260511T000000Z",
        f"--output-dir={output_dir}",
        f"--progress-dir={progress_dir}",
    ]


def test_run_pull_shard_writes_per_shard_row_with_parent_run_id(
    monkeypatch, tmp_path, capsys,
):
    """``--mode=pull`` should land a runs.db row with
    ``kind='self_play'`` (the schema-valid canonical name for the
    master's data-gen step), ``parent_run_id=<master_run_id>``, and
    the shard's display label. Mirrors the master's iterate
    self-play kind so roll-ups treat both rows as the same kind
    of work."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(cli_lifecycle, "git_commit_short", lambda: "abcd123")
    _seed_parent_run(db_path, "iter_007_v1", kind="iterate")

    captured = {}

    def fake_run_shard_pull(spec, **kwargs):
        captured["spec"] = spec
        captured["kwargs"] = kwargs
        # Match the real runner's contract: write a placeholder progress
        # JSON so the artifact-registration path sees a real file.
        run_id = kwargs["run_id"]
        label = kwargs["label"]
        json_path = (
            kwargs["progress_dir"] / f"{run_id}_shard_{label}.json"
        )
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text("{}", encoding="utf-8")
        return [tmp_path / "fake.npz"]

    progress_dir = tmp_path / "training_progress"
    output_dir = tmp_path / "iterate_data"
    argv = _make_pull_argv(
        run_id="iter_007_v1", label="local",
        progress_dir=progress_dir, output_dir=output_dir,
    )
    with patch.object(cli_shard, "run_shard_pull", fake_run_shard_pull):
        cli_shard._run(argv)

    # The runner was invoked with the resolved spec / kwargs.
    assert isinstance(captured["spec"], SelfPlayJobSpec)
    assert captured["kwargs"]["run_id"] == "iter_007_v1"
    assert captured["kwargs"]["label"] == "local"

    # The runs.db row reflects the lifecycle wiring. Scope the query
    # to the shard's own row; the test fixture pre-seeds a parent
    # row to satisfy the FK, which would otherwise appear in the
    # unfiltered SELECT.
    conn = runs_db.connect(db_path)
    try:
        run_rows = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_007_v1_shard_local",),
        ))
        artifact_rows = list(conn.execute(
            "SELECT * FROM run_artifacts WHERE run_id = ?",
            ("iter_007_v1_shard_local",),
        ))
    finally:
        conn.close()

    assert len(run_rows) == 1
    row = run_rows[0]
    assert row["run_id"] == "iter_007_v1_shard_local"
    assert row["kind"] == "self_play"
    assert row["parent_run_id"] == "iter_007_v1"
    assert row["label"] == "local"
    assert row["status"] == "completed"
    assert row["git_commit"] == "abcd123"
    cfg = json.loads(row["config_json"])
    assert cfg["mode"] == "pull"
    assert cfg["run_id"] == "iter_007_v1"

    # Progress JSON artifact got registered.
    assert any(
        a["artifact_type"] == "progress_json" for a in artifact_rows
    )

    # Stdout line still emits the npz_paths summary the orchestrator
    # parses.
    out = capsys.readouterr().out
    payload = json.loads(out.strip())
    assert "npz_paths" in payload


def test_run_eval_shard_writes_per_shard_row_with_kind_eval(
    monkeypatch, tmp_path, capsys,
):
    """``--mode=eval`` should land a runs.db row with
    ``kind='eval'`` so eval-shard rolls up with the master's eval
    run, not with self-play."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(cli_lifecycle, "git_commit_short", lambda: "deadbef")
    _seed_parent_run(db_path, "iter_007_eval_v2_vs_v1", kind="eval")

    canned_counts = {
        "n_games": 5, "wins_new": 3, "wins_old": 1,
        "draws": 1, "crashed": 0, "timed_out": 0,
    }

    def fake_run_shard_eval_pull(spec, **kwargs):
        run_id = kwargs["run_id"]
        label = kwargs["label"]
        json_path = (
            kwargs["progress_dir"] / f"{run_id}_shard_{label}.json"
        )
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text("{}", encoding="utf-8")
        # Echo a push_progress under the MASTER run_id (the parent)
        # with shard_label distinguishing per-shard rows. This is the
        # post-Bug-2-fix pattern: per-shard run_progress is keyed by
        # (master_run_id, shard_label), NOT by a synthesized
        # ``{master}_shard_{label}`` id (which would FK-fail because
        # no such ``runs`` row exists for in-process local shards).
        runs_client.push_progress(
            run_id,
            shard_label=label,
            n_games_done=canned_counts["n_games"],
            n_games_total=kwargs["iter_total_games"],
            wins_new=canned_counts["wins_new"],
            wins_old=canned_counts["wins_old"],
            draws=canned_counts["draws"],
        )
        return canned_counts

    progress_dir = tmp_path / "training_progress"
    output_dir = tmp_path / "iterate_data"
    argv = _make_eval_argv(
        run_id="iter_007_eval_v2_vs_v1", label="macbook",
        progress_dir=progress_dir, output_dir=output_dir,
    )
    with patch.object(
        cli_shard, "run_shard_eval_pull", fake_run_shard_eval_pull,
    ):
        cli_shard._run(argv)

    conn = runs_db.connect(db_path)
    try:
        # The shard lifecycle still creates its own runs row for status
        # tracking. The PROGRESS row, however, lives under the master.
        shard_run_rows = list(conn.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            ("iter_007_eval_v2_vs_v1_shard_macbook",),
        ))
        progress_rows = list(conn.execute(
            "SELECT * FROM run_progress WHERE run_id = ?",
            ("iter_007_eval_v2_vs_v1",),
        ))
    finally:
        conn.close()

    assert len(shard_run_rows) == 1
    row = shard_run_rows[0]
    assert row["run_id"] == "iter_007_eval_v2_vs_v1_shard_macbook"
    assert row["kind"] == "eval"
    assert row["parent_run_id"] == "iter_007_eval_v2_vs_v1"
    assert row["label"] == "macbook"
    assert row["status"] == "completed"

    # The push_progress call inside the fake runner created the
    # per-shard row keyed by (master_run_id, shard_label).
    assert progress_rows, "expected at least one run_progress row"
    p = progress_rows[0]
    assert p["shard_label"] == "macbook"
    assert p["wins_new"] == 3 and p["wins_old"] == 1
    assert p["n_games_total"] == 4

    # Post-cutover the sibling ``_shard_<label>_result.json`` write
    # is dropped — the per-shard ``run_progress`` row is the
    # authoritative source. Stdout still carries the counts dict for
    # diagnostic visibility, but no ``result_path`` key.
    out = capsys.readouterr().out
    payload = json.loads(out.strip())
    assert payload["wins_new"] == 3
    assert "result_path" not in payload
    legacy_result = (
        progress_dir
        / "iter_007_eval_v2_vs_v1_shard_macbook_result.json"
    )
    assert not legacy_result.exists(), (
        "legacy _result.json must not be written post-cutover; "
        f"found at {legacy_result}"
    )


def test_run_pull_shard_marks_failed_on_exception(
    monkeypatch, tmp_path,
):
    """A crash inside ``run_shard_pull`` should propagate AND
    mark the runs.db row as ``failed`` via the lifecycle CM."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(cli_lifecycle, "git_commit_short", lambda: "x")
    _seed_parent_run(db_path, "iter_008", kind="iterate")

    def boom(spec, **kwargs):
        raise RuntimeError("shard crashed")

    argv = _make_pull_argv(
        run_id="iter_008", label="local",
        progress_dir=tmp_path / "progress",
        output_dir=tmp_path / "out",
    )
    with patch.object(cli_shard, "run_shard_pull", boom):
        with pytest.raises(RuntimeError, match="shard crashed"):
            cli_shard._run(argv)

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute(
            "SELECT status, notes FROM runs WHERE run_id = ?",
            ("iter_008_shard_local",),
        ))
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "shard crashed" in (rows[0]["notes"] or "")


def test_run_eval_shard_marks_killed_on_keyboard_interrupt(
    monkeypatch, tmp_path,
):
    """KeyboardInterrupt during an eval shard should land as
    ``status='killed'``, not ``'failed'`` — same SIGINT mapping the
    master uses so the dashboard's filter buckets stay consistent."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(cli_lifecycle, "git_commit_short", lambda: "x")
    _seed_parent_run(db_path, "iter_009_eval", kind="eval")

    def interrupted(spec, **kwargs):
        raise KeyboardInterrupt()

    argv = _make_eval_argv(
        run_id="iter_009_eval", label="winbox",
        progress_dir=tmp_path / "progress",
        output_dir=tmp_path / "out",
    )
    with patch.object(cli_shard, "run_shard_eval_pull", interrupted):
        with pytest.raises(KeyboardInterrupt):
            cli_shard._run(argv)

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute(
            "SELECT status FROM runs WHERE run_id = ?",
            ("iter_009_eval_shard_winbox",),
        ))
    finally:
        conn.close()
    assert rows[0]["status"] == "killed"


def test_run_pull_shard_no_op_when_run_db_unset(
    monkeypatch, tmp_path, capsys,
):
    """Phase 1 invariant: with neither env var set, the lifecycle
    is a no-op and the shard runs unchanged. No runs.db file is
    created."""
    db_path = tmp_path / "runs.db"
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    def fake_run_shard_pull(spec, **kwargs):
        return []

    argv = _make_pull_argv(
        run_id="iter_010", label="local",
        progress_dir=tmp_path / "p",
        output_dir=tmp_path / "o",
    )
    with patch.object(cli_shard, "run_shard_pull", fake_run_shard_pull):
        cli_shard._run(argv)

    # Stdout still emits the npz_paths line.
    out = capsys.readouterr().out
    payload = json.loads(out.strip())
    assert "npz_paths" in payload

    # No DB file landed on disk.
    assert not db_path.exists()


def test_shard_label_returns_hostname_when_socket_works(monkeypatch):
    """``_shard_label`` returns ``socket.gethostname()`` happy-path."""
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "my-host")
    assert cli_shard._shard_label() == "my-host"


def test_shard_label_falls_back_when_socket_raises(monkeypatch):
    """``_shard_label`` swallows ``OSError`` from gethostname()
    (CI fixtures sometimes raise this) and returns ``'unknown'``."""
    import socket

    def _raise():
        raise OSError("synthetic")

    monkeypatch.setattr(socket, "gethostname", _raise)
    assert cli_shard._shard_label() == "unknown"


def test_shard_label_falls_back_when_socket_returns_empty(monkeypatch):
    """``_shard_label`` treats an empty hostname (rare, but POSIX
    allows it on misconfigured hosts) as ``'unknown'``."""
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "")
    assert cli_shard._shard_label() == "unknown"


def test_decode_b64_json_round_trips_simple_payload():
    """Sanity: ``_decode_b64_json`` undoes the master-side
    ``base64(json.dumps(...))`` encoding."""
    payload = {"a": 1, "b": [2, 3], "c": "hello"}
    encoded = base64.b64encode(
        json.dumps(payload).encode("utf-8"),
    ).decode("ascii")
    assert cli_shard._decode_b64_json(encoded) == payload


def test_build_shard_config_keeps_identifying_fields(tmp_path):
    """``_build_shard_config`` should keep the small identifying
    fields needed for the runs.db row's config_json column without
    pickling the entire spec dict (which would bloat the column with
    NN-architecture details that already live on the master's parent
    row)."""
    import argparse
    spec_dict = {
        "weights_path": "trained_weights/v1/weights.pt",
        "samples": 4, "inner_nodes": 200, "base_seed": 7,
        "extra_field_we_dont_want": "this string is huge but irrelevant",
    }
    shard_dict = {"host": "macbook", "label": "macbook-m2"}
    args = argparse.Namespace(
        mode="pull",
        run_id="iter_007",
        iter_total_games=500,
        stamp="20260511T000000Z",
        queue_url="http://master:5099",
        progress_dir=tmp_path / "p",
        output_dir=tmp_path / "o",
    )
    cfg = cli_shard._build_shard_config(spec_dict, shard_dict, args)
    assert cfg["mode"] == "pull"
    assert cfg["run_id"] == "iter_007"
    assert cfg["shard_label"] == "macbook-m2"
    assert cfg["shard_host"] == "macbook"
    assert cfg["iter_total_games"] == 500
    assert cfg["weights_path"] == "trained_weights/v1/weights.pt"
    assert cfg["samples"] == 4
    assert cfg["inner_nodes"] == 200
    assert "extra_field_we_dont_want" not in cfg
    # New_weights_path / old_weights_path are None for the self-play
    # spec, but still present (eval specs use them).
    assert cfg["new_weights_path"] is None
    assert cfg["old_weights_path"] is None


def test_build_shard_config_falls_back_to_host_when_label_missing(
    tmp_path,
):
    """``ShardConfig.display_label`` falls back to ``host`` when
    ``label`` is empty. The config dict mirrors that fallback so the
    runs.db row's label always identifies the shard."""
    import argparse
    shard_dict = {"host": "winbox", "label": ""}
    args = argparse.Namespace(
        mode="eval", run_id="r", iter_total_games=1, stamp="s",
        queue_url="u", progress_dir=tmp_path, output_dir=tmp_path,
    )
    cfg = cli_shard._build_shard_config(
        {"new_weights_path": "x"}, shard_dict, args,
    )
    # Empty label → falls back to host.
    assert cfg["shard_label"] == "winbox"
    assert cfg["shard_host"] == "winbox"
