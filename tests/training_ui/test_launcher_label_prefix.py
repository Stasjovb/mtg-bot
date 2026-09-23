"""Training-UI launcher support for the ``--run-label-prefix`` flag.

Two halves:

1. The schema exposes the flag so the UI's "Launch new iterate" form
   can set it, and ``build_iterate_command`` forwards it (omitting it
   at the blank default so the spawned command line for the original
   lineage is unchanged).
2. ``clear_iter_collision_residue`` is scoped to ONE lineage. This is
   the dangerous one: both lineages number their iterations from 1,
   so an un-scoped ``iter_001_%`` sweep launched for the ``s2_``
   lineage would DELETE the original lineage's completed iter_001
   rows out of the shared runs.db.
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.training_ui.launcher import (
    ITERATE_SCHEMA,
    build_iterate_command,
    clear_iter_collision_residue,
)


def _schema_entry(name: str) -> dict | None:
    for section in ITERATE_SCHEMA:
        for arg in section["args"]:
            if arg["name"] == name:
                return arg
    return None


# ---------------------------------------------------------------------
# Schema + command building
# ---------------------------------------------------------------------


def test_schema_exposes_run_label_prefix() -> None:
    spec = _schema_entry("run-label-prefix")
    assert spec is not None, "run-label-prefix missing from ITERATE_SCHEMA"
    assert spec["type"] == "string"
    assert spec["default"] == ""


def _submitted(**extra) -> dict:
    base = {
        "bootstrap-version": "v5",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
    }
    base.update(extra)
    return base


def test_command_forwards_run_label_prefix() -> None:
    argv = build_iterate_command(
        _submitted(**{"run-label-prefix": "s2_"}),
        python_executable="py",
    )
    assert "--run-label-prefix" in argv
    assert argv[argv.index("--run-label-prefix") + 1] == "s2_"


def test_command_omits_run_label_prefix_at_default() -> None:
    """Blank → leave iterate at its own default; the original
    lineage's command line is unchanged."""
    for value in ("", None):
        argv = build_iterate_command(
            _submitted(**{"run-label-prefix": value}),
            python_executable="py",
        )
        assert "--run-label-prefix" not in argv
    argv = build_iterate_command(_submitted(), python_executable="py")
    assert "--run-label-prefix" not in argv


# ---------------------------------------------------------------------
# Collision-residue sweep scoping
# ---------------------------------------------------------------------


def _seed_iterate_state(registry_root: Path, completed: int) -> None:
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "iterate_state.json").write_text(
        json.dumps({"iterations_completed": completed}), encoding="utf-8",
    )


def _seed_db_row(db_path: Path, run_id: str, status: str) -> None:
    from mtg_bot.cli.runs import db as runs_db
    conn = runs_db.connect(db_path)
    try:
        with runs_db.transaction(conn):
            conn.execute(
                "INSERT INTO runs(run_id, kind, status, started_at, "
                "git_commit, config_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, "iterate", status,
                 "2026-09-23T00:00:00+00:00", "deadbeef", "{}"),
            )
    finally:
        conn.close()


def _remaining_ids(db_path: Path) -> set[str]:
    from mtg_bot.cli.runs import db as runs_db
    conn = runs_db.connect(db_path)
    try:
        return {r["run_id"] for r in conn.execute("SELECT run_id FROM runs")}
    finally:
        conn.close()


def test_residue_sweep_leaves_other_lineage_rows_alone(
    tmp_path: Path,
) -> None:
    """Launching the s2 lineage at its iteration 1 must not touch the
    un-prefixed lineage's iter_001 rows."""
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "trained_weights_s2"
    _seed_iterate_state(registry, completed=0)

    db_path = progress / "runs.db"
    _seed_db_row(db_path, "iter_001_cycle", "completed")
    _seed_db_row(db_path, "iter_001_self_play_v1", "completed")
    _seed_db_row(db_path, "s2_iter_001_cycle", "killed")
    _seed_db_row(db_path, "s2_iter_001_train_v2", "failed")

    out = clear_iter_collision_residue(
        progress, registry_root=registry, n_iterations=1,
        label_prefix="s2_",
    )

    assert sorted(out["cleared_run_ids"]) == [
        "s2_iter_001_cycle", "s2_iter_001_train_v2",
    ]
    assert _remaining_ids(db_path) == {
        "iter_001_cycle", "iter_001_self_play_v1",
    }


def test_residue_sweep_default_prefix_leaves_prefixed_rows_alone(
    tmp_path: Path,
) -> None:
    """The mirror case: the original lineage's sweep must not delete
    the s2 lineage's rows."""
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "trained_weights"
    _seed_iterate_state(registry, completed=0)

    db_path = progress / "runs.db"
    _seed_db_row(db_path, "iter_001_cycle", "killed")
    _seed_db_row(db_path, "s2_iter_001_cycle", "completed")

    out = clear_iter_collision_residue(
        progress, registry_root=registry, n_iterations=1,
    )

    assert out["cleared_run_ids"] == ["iter_001_cycle"]
    assert _remaining_ids(db_path) == {"s2_iter_001_cycle"}


def test_residue_sweep_sentinels_are_lineage_scoped(
    tmp_path: Path,
) -> None:
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "trained_weights_s2"
    _seed_iterate_state(registry, completed=0)

    (progress / ".STOP_iter_001_cycle").write_text("{}", encoding="utf-8")
    (progress / ".STOP_s2_iter_001_cycle").write_text("{}", encoding="utf-8")

    out = clear_iter_collision_residue(
        progress, registry_root=registry, n_iterations=1,
        label_prefix="s2_",
    )

    assert out["cleared_sentinels"] == [".STOP_s2_iter_001_cycle"]
    assert (progress / ".STOP_iter_001_cycle").exists()
    assert not (progress / ".STOP_s2_iter_001_cycle").exists()


def test_spawn_iterate_threads_prefix_into_sweep_and_argv(
    tmp_path: Path, monkeypatch,
) -> None:
    """The prefix submitted on the launch form must reach BOTH the
    spawned argv and the collision sweep. Popen is stubbed so no real
    iterate process starts."""
    import mtg_bot.training_ui.launcher as launcher_mod

    class _FakePopen:
        def __init__(self, *args, **kwargs):
            self.pid = 4242

    monkeypatch.setattr(launcher_mod.subprocess, "Popen", _FakePopen)

    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "trained_weights_s2"
    _seed_iterate_state(registry, completed=0)
    db_path = progress / "runs.db"
    _seed_db_row(db_path, "iter_001_cycle", "completed")
    _seed_db_row(db_path, "s2_iter_001_cycle", "killed")

    result = launcher_mod.spawn_iterate(
        {
            "bootstrap-version": "v_smoke_only",
            "deck-pool": str(tmp_path / "no_such.json"),
            "n-iterations": "1",
            "run-label-prefix": "s2_",
        },
        progress,
        registry_root=registry,
    )

    assert result["ok"] is True
    assert "--run-label-prefix" in result["command"]
    idx = result["command"].index("--run-label-prefix")
    assert result["command"][idx + 1] == "s2_"
    assert result["collision_cleanup"]["cleared_run_ids"] == [
        "s2_iter_001_cycle",
    ]
    # The other lineage's completed cycle survives.
    assert "iter_001_cycle" in _remaining_ids(db_path)
