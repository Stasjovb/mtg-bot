"""Phase 2 DB-backed read path for ``mtg_bot.training_ui.app``.

These tests cover the new code paths added in
``feature/ui-from-db``:

- ``/api/runs`` reads the SQLite ``runs.db`` and merges with
  standalone JSON files (the JSON-only fallback for runs that
  haven't been wired to the DB yet — currently iterate / train /
  bench / capture).
- ``/api/runs/<run_id>`` returns the merged DB+JSON record plus the
  per-shard progress rows / events / artifacts pulled from the DB.
- ``/api/runs/recent`` surfaces the last N completed runs across
  all kinds for the cross-run summary panel.
- A DB row's ``kind = 'self_play'`` is translated to the UI's
  ``'data_gen'`` discriminator on the read path so the front-end
  renderer doesn't need to know about the DB enum.
- A JSON file with no DB row gets a synthetic
  ``_synthetic_from_json: true`` marker so backfill tooling and
  tests can tell apart real vs synthesized rows.
- A DB row with no JSON file still surfaces (covers Phase 3
  approach: JSON writes drop, DB becomes sole source).

The existing JSON-fixture tests in ``test_app.py`` exercise the
JSON-only fallback path with no DB present — they still pass under
the new merging logic.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mtg_bot.cli.runs import backfill as runs_backfill, db as runs_db
from mtg_bot.cli.runs.models import (
    Artifact, Event, ProgressUpdate, Run,
)
from mtg_bot.training_ui.app import create_app


class _DBSyncClient:
    """Test-only wrapper that folds ``progress_dir/*.json`` into the DB
    before each request. Phase 3 removed the request-time backfill
    from the UI; this wrapper restores the historical
    "JSON-becomes-DB-on-next-request" convenience SOLELY for tests
    so existing assertions on listings produced from JSON fixtures
    still pass without per-test boilerplate. Production code does NOT
    go through this path — the UI is pure DB.
    """

    def __init__(self, flask_client, progress_dir: Path):
        self._client = flask_client
        self._progress_dir = progress_dir

    def _refresh(self) -> None:
        try:
            runs_backfill.backfill_progress_dir(
                self._progress_dir, self._progress_dir / "runs.db",
                stale_after_hours=24.0 * 365,
            )
        except Exception:  # noqa: BLE001
            # Mirror the request-time backfill's swallow-and-warn
            # contract for test scenarios that intentionally corrupt
            # the DB or progress dir.
            pass

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if name in ("get", "post", "put", "patch", "delete", "head"):
            def _wrapped(*args, **kwargs):
                self._refresh()
                return attr(*args, **kwargs)
            return _wrapped
        return attr


def _open_db(progress_dir: Path) -> sqlite3.Connection:
    """Create + open the colocated runs.db, applying schema. The UI
    queries this same path on every request via
    ``runs_db.connect``."""
    return runs_db.connect(progress_dir / "runs.db")


def _seed_run(
    conn: sqlite3.Connection, run_id: str, *,
    kind: str = "eval",
    status: str = "running",
    started_at: str = "2026-05-04T10:00:00+00:00",
    ended_at: str | None = None,
    git_commit: str = "deadbeef",
    config_json: str = "{}",
    parent_run_id: str | None = None,
    label: str | None = None,
    notes: str | None = None,
) -> None:
    runs_db.insert_run(
        conn,
        Run(
            run_id=run_id, kind=kind, status=status,
            started_at=started_at, ended_at=ended_at,
            git_commit=git_commit, config_json=config_json,
            parent_run_id=parent_run_id, label=label, notes=notes,
        ),
    )


def _seed_progress(
    conn: sqlite3.Connection, run_id: str, *,
    shard_label: str | None = None,
    n_games_done: int | None = None,
    n_games_total: int | None = None,
    elapsed_seconds: float | None = None,
    crashed: int | None = None,
    timed_out: int | None = None,
    wins_new: int | None = None,
    wins_old: int | None = None,
    draws: int | None = None,
    extra: dict | None = None,
) -> None:
    extra_json = json.dumps(extra, sort_keys=True) if extra else None
    runs_db.upsert_progress(
        conn,
        ProgressUpdate(
            run_id=run_id, shard_label=shard_label,
            n_games_done=n_games_done, n_games_total=n_games_total,
            elapsed_seconds=elapsed_seconds,
            crashed=crashed, timed_out=timed_out,
            wins_new=wins_new, wins_old=wins_old, draws=draws,
            extra_json=extra_json,
        ),
    )


def _seed_event(
    conn: sqlite3.Connection, run_id: str, event_type: str,
    *, payload: dict | None = None,
    timestamp: str = "2026-05-04T10:01:00+00:00",
) -> None:
    runs_db.insert_event(
        conn,
        Event(
            run_id=run_id, event_type=event_type,
            payload_json=json.dumps(payload, sort_keys=True) if payload else None,
            timestamp=timestamp,
        ),
    )


def _seed_artifact(
    conn: sqlite3.Connection, run_id: str, *,
    artifact_type: str = "progress_json",
    path: str = "training_progress/eval_v9.json",
    bytes_: int | None = 1024,
) -> None:
    runs_db.upsert_artifact(
        conn,
        Artifact(
            run_id=run_id, artifact_type=artifact_type,
            path=path, bytes=bytes_,
        ),
    )


def _write_json(progress_dir: Path, run_id: str, **fields) -> Path:
    payload = {
        "run_id": run_id,
        "started_at": "2026-05-04T10:00:00+00:00",
        "status": "running",
    }
    payload.update(fields)
    path = progress_dir / f"{run_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture()
def progress_dir(tmp_path: Path) -> Path:
    d = tmp_path / "training_progress"
    d.mkdir()
    return d


@pytest.fixture()
def client(progress_dir: Path):
    app = create_app(progress_dir)
    app.config["TESTING"] = True
    return _DBSyncClient(app.test_client(), progress_dir)


# ---- /api/runs : DB + JSON merging ----------------------------------------


def test_api_runs_reads_run_row_from_db_when_no_json(
    client, progress_dir: Path,
):
    """A run that exists ONLY in the DB (no JSON file) shows up in
    /api/runs. With Phase 2 the DB is the sole source of truth; this
    is the universal case, not just the Phase 3 endgame."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_v9_vs_v8", kind="eval", status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
        _seed_progress(
            conn, "eval_v9_vs_v8",
            n_games_done=42, n_games_total=200,
            elapsed_seconds=600.0,
            wins_new=20, wins_old=18, draws=4, crashed=0, timed_out=0,
            extra={"win_rate": 0.526, "opponent_label": "v8"},
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert len(runs) == 1
    r = runs[0]
    assert r["run_id"] == "eval_v9_vs_v8"
    assert r["kind"] == "eval"
    assert r["status"] == "running"
    assert r["n_games_done"] == 42
    assert r["n_games_total"] == 200
    assert r["wins_new"] == 20
    # extra_json fan-out: opponent_label + win_rate available at the
    # top level so the UI's eval renderer reads them naturally.
    assert r["opponent_label"] == "v8"
    assert r["win_rate"] == pytest.approx(0.526)
    # _db_kind retains the canonical DB enum for downstream tooling.
    assert r["_db_kind"] == "eval"


def test_api_runs_derives_win_rate_from_wins_when_missing(
    client, progress_dir: Path,
):
    """Eval cards on the DB-only read path don't have ``win_rate``
    pushed by producers — the JSON-era producers used to compute it
    pre-backfill but the DB schema doesn't carry it. The UI's eval
    render branch reads ``run.win_rate`` for the headline percentage;
    derive it server-side from wins_new + wins_old when at least one
    decisive game has landed."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_v4_vs_v3", kind="eval", status="running",
            started_at="2026-05-14T03:51:47+00:00",
        )
        # Per-shard rows only — no aggregate, no extra_json with
        # win_rate. Exercises the rollup-path derivation.
        _seed_progress(
            conn, "eval_v4_vs_v3", shard_label="local",
            n_games_done=29, n_games_total=500,
            wins_new=14, wins_old=15,
        )
        _seed_progress(
            conn, "eval_v4_vs_v3", shard_label="macbook",
            n_games_done=61, n_games_total=500,
            wins_new=34, wins_old=26,
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "eval_v4_vs_v3"]
    # Wins SUM across shards.
    assert r["wins_new"] == 48
    assert r["wins_old"] == 41
    # Derived: 48 / (48 + 41) = 0.5393...
    assert r["win_rate"] == pytest.approx(48 / 89)


def test_api_runs_does_not_synthesize_win_rate_before_first_game(
    client, progress_dir: Path,
):
    """Wilson CI / win-rate at 0 games is undefined. Don't synthesize
    a 0.0 (or NaN) value — leave win_rate as None so the JS shows
    the ``—`` placeholder."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_zero_decisive", kind="eval", status="running",
            started_at="2026-05-14T04:00:00+00:00",
        )
        _seed_progress(
            conn, "eval_zero_decisive", shard_label="local",
            n_games_done=0, n_games_total=500,
            wins_new=0, wins_old=0,
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "eval_zero_decisive"]
    assert r.get("win_rate") is None


def test_api_runs_rolls_up_per_shard_when_aggregate_missing(
    client, progress_dir: Path,
):
    """Distributed iterate's self-play writes per-shard
    ``run_progress`` rows (shard_label=local/macbook/win10) but the
    aggregate row (shard_label IS NULL) doesn't always get written.
    The UI must SUM the per-shard counters so the user sees real
    progress instead of ``games=None/None``.
    """
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_003_self_play_v3", kind="self_play",
            status="running",
            started_at="2026-05-14T01:30:00+00:00",
        )
        # Per-shard rows only; NO aggregate (shard_label=NULL) row.
        _seed_progress(
            conn, "iter_003_self_play_v3", shard_label="local",
            n_games_done=18, n_games_total=1000, crashed=0,
            timed_out=2, elapsed_seconds=600.0,
        )
        _seed_progress(
            conn, "iter_003_self_play_v3",
            shard_label="greggs-macbook-pro",
            n_games_done=70, n_games_total=1000, crashed=1,
            timed_out=3, elapsed_seconds=550.0,
        )
        _seed_progress(
            conn, "iter_003_self_play_v3",
            shard_label="desktop-g72aptg",
            n_games_done=8, n_games_total=1000, crashed=0,
            timed_out=1, elapsed_seconds=500.0,
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    [r] = [r for r in runs if r["run_id"] == "iter_003_self_play_v3"]
    # Sum across shards.
    assert r["n_games_done"] == 96  # 18 + 70 + 8
    assert r["crashed"] == 1  # 0 + 1 + 0
    assert r["timed_out"] == 6  # 2 + 3 + 1
    # n_games_total is MAX (replicated across shards).
    assert r["n_games_total"] == 1000
    # elapsed_seconds is MAX (cluster wall = longest shard).
    assert r["elapsed_seconds"] == 600.0


def test_api_runs_rollup_synthesizes_machines_and_extras(
    client, progress_dir: Path,
):
    """Distributed self-play with no aggregate row should still
    surface (a) per-machine sub-cards, (b) summed n_samples /
    n_workers / p0/p1 wins from per-shard extra_json, and (c)
    derived games_per_hour + estimated_remaining_seconds +
    samples_per_hour so the front-end's data_gen card renders
    cleanly instead of with blank fields."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_003_self_play_v3", kind="self_play",
            status="running",
            started_at="2026-05-14T01:30:00+00:00",
        )
        # Per-shard rows with structured counters + extra_json blobs
        # carrying the non-counter fields (n_samples, n_workers,
        # p0/p1 wins).
        _seed_progress(
            conn, "iter_003_self_play_v3", shard_label="local",
            n_games_done=18, n_games_total=1000,
            elapsed_seconds=600.0,
            extra={
                "n_samples": 4500, "n_workers": 9,
                "p0_wins": 11, "p1_wins": 7, "status": "running",
            },
        )
        _seed_progress(
            conn, "iter_003_self_play_v3",
            shard_label="greggs-macbook-pro",
            n_games_done=70, n_games_total=1000,
            elapsed_seconds=550.0,
            extra={
                "n_samples": 17000, "n_workers": 6,
                "p0_wins": 38, "p1_wins": 32,
                "status": "running",
            },
        )
        _seed_progress(
            conn, "iter_003_self_play_v3",
            shard_label="desktop-g72aptg",
            n_games_done=8, n_games_total=1000,
            elapsed_seconds=500.0,
            extra={
                "n_samples": 2000, "n_workers": 4,
                "p0_wins": 5, "p1_wins": 3, "status": "running",
            },
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "iter_003_self_play_v3"]
    # Headline counters (already tested elsewhere — kept for
    # readability).
    assert r["n_games_done"] == 96
    # extra_json-summed fields fan out at the top level.
    assert r["n_samples"] == 23500  # 4500 + 17000 + 2000
    assert r["n_workers"] == 19  # 9 + 6 + 4
    assert r["p0_wins"] == 54  # 11 + 38 + 5
    assert r["p1_wins"] == 42  # 7 + 32 + 3
    # Derived rates + ETA — using MAX(elapsed)=600s, done=96.
    assert r["games_per_hour"] == pytest.approx(
        3600.0 * 96 / 600.0
    )
    # ETA: 904 remaining * 6.25s/game (600s / 96 games) ≈ 5650s.
    assert r["estimated_remaining_seconds"] == pytest.approx(
        904 * (600.0 / 96), abs=1.0,
    )
    # Per-machine breakdown for the UI's sub-card renderer.
    machines = r["machines"]
    assert len(machines) == 3
    labels = {m["label"] for m in machines}
    assert labels == {"local", "greggs-macbook-pro", "desktop-g72aptg"}
    # Each machine carries its n_workers from the extra_json.
    mac = next(m for m in machines if m["label"] == "greggs-macbook-pro")
    assert mac["n_workers"] == 6
    assert mac["n_games_done"] == 70


def test_api_runs_prefers_aggregate_row_over_per_shard_rollup(
    client, progress_dir: Path,
):
    """When an aggregate row exists, it wins — the per-shard rollup
    is only the FALLBACK for distributed runs that didn't write the
    aggregate. A producer that DOES write the aggregate (eval, etc.)
    keeps its existing semantics."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_004_self_play_v4", kind="self_play",
            status="running",
            started_at="2026-05-14T02:00:00+00:00",
        )
        # Aggregate row IS present.
        _seed_progress(
            conn, "iter_004_self_play_v4", shard_label=None,
            n_games_done=500, n_games_total=2000,
        )
        # Per-shard rows would sum to 100 if rollup fired —
        # they should NOT, because aggregate is present.
        _seed_progress(
            conn, "iter_004_self_play_v4", shard_label="local",
            n_games_done=50, n_games_total=2000,
        )
        _seed_progress(
            conn, "iter_004_self_play_v4", shard_label="mac",
            n_games_done=50, n_games_total=2000,
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "iter_004_self_play_v4"]
    # Aggregate value wins; per-shard sum (100) is NOT used.
    assert r["n_games_done"] == 500


def test_api_runs_filters_to_top_level_only(
    client, progress_dir: Path,
):
    """A distributed iterate writes 5+ rows (cycle / stage / 3 shards).
    The list view must surface only the cycle row — stage + shard rows
    are forensics-only and live in the detail endpoint."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_003_cycle", kind="iterate", status="running",
            started_at="2026-05-14T01:30:00+00:00",
        )
        _seed_run(
            conn, "iter_003_self_play_v3", kind="self_play",
            status="running",
            started_at="2026-05-14T01:30:30+00:00",
            parent_run_id="iter_003_cycle",
        )
        for shard in ("local", "macbook", "win10"):
            _seed_run(
                conn,
                f"iter_003_self_play_v3_shard_{shard}",
                kind="self_play", status="running",
                started_at="2026-05-14T01:31:00+00:00",
                parent_run_id="iter_003_self_play_v3",
            )
        _seed_progress(
            conn, "iter_003_self_play_v3", shard_label="local",
            n_games_done=18, n_games_total=1000,
            extra={"n_workers": 9},
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    runs = res.get_json()["runs"]
    iter_runs = [r for r in runs if r["run_id"].startswith("iter_003")]
    assert len(iter_runs) == 1
    assert iter_runs[0]["run_id"] == "iter_003_cycle"


def test_api_runs_cycle_card_renders_with_active_stage_kind(
    client, progress_dir: Path,
):
    """The cycle row's kind is ``iterate``; the front-end has no
    ``cycle`` render branch. The list endpoint translates the cycle's
    kind to its active stage's UI kind (``data_gen`` for self_play)
    and folds the stage's progress onto the cycle row."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_005_cycle", kind="iterate", status="running",
            started_at="2026-05-14T01:00:00+00:00",
        )
        _seed_run(
            conn, "iter_005_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-14T01:00:30+00:00",
            parent_run_id="iter_005_cycle",
        )
        _seed_progress(
            conn, "iter_005_self_play_v5", shard_label="local",
            n_games_done=88, n_games_total=500,
            elapsed_seconds=600.0,
            extra={"n_workers": 9, "n_samples": 22000},
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "iter_005_cycle"]
    assert r["kind"] == "data_gen"
    assert r["n_games_done"] == 88
    assert r["n_games_total"] == 500
    assert r["n_workers"] == 9
    assert r["n_samples"] == 22000
    assert r["_active_stage_run_id"] == "iter_005_self_play_v5"


def test_api_runs_cycle_card_prefers_running_stage_over_finished(
    client, progress_dir: Path,
):
    """If a cycle has multiple stages (self_play finished, training
    running), the active stage is the one with status=running."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_001_cycle", kind="iterate", status="running",
            started_at="2026-05-14T00:00:00+00:00",
        )
        _seed_run(
            conn, "iter_001_self_play_v0", kind="self_play",
            status="completed",
            started_at="2026-05-14T00:00:30+00:00",
            ended_at="2026-05-14T00:30:00+00:00",
            parent_run_id="iter_001_cycle",
        )
        _seed_run(
            conn, "iter_001_train_v1", kind="training",
            status="running",
            started_at="2026-05-14T00:30:10+00:00",
            parent_run_id="iter_001_cycle",
        )
        _seed_progress(
            conn, "iter_001_train_v1",
            extra={"current_epoch": 3, "total_epochs": 50},
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "iter_001_cycle"]
    assert r["kind"] == "training"
    assert r["_active_stage_run_id"] == "iter_001_train_v1"


def test_api_runs_non_cycle_top_level_runs_keep_their_kind(
    client, progress_dir: Path,
):
    """Standalone eval / training runs (parent=NULL but kind != iterate)
    keep their own kind unchanged."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_v5_vs_v4", kind="eval", status="running",
            started_at="2026-05-14T02:00:00+00:00",
        )
        _seed_progress(
            conn, "eval_v5_vs_v4",
            n_games_done=42, n_games_total=2000,
            wins_new=23, wins_old=15, draws=4,
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "eval_v5_vs_v4"]
    assert r["kind"] == "eval"
    assert r["n_games_done"] == 42


def test_api_runs_translates_self_play_kind_to_data_gen(
    client, progress_dir: Path,
):
    """The DB's ``kind = 'self_play'`` is translated to the UI's
    ``'data_gen'`` so the front-end discriminator (which still
    matches on the JSON-era ``data_gen`` literal) lights up the
    blue games-progress card. ``_db_kind`` retains the canonical
    DB value for downstream tooling."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_001_self_play_v6", kind="self_play",
            started_at="2026-05-04T11:00:00+00:00",
        )
    finally:
        conn.close()
    runs = client.get("/api/runs").get_json()["runs"]
    assert len(runs) == 1
    assert runs[0]["kind"] == "data_gen"
    assert runs[0]["_db_kind"] == "self_play"


def test_api_runs_backfills_json_only_run_into_db(
    client, progress_dir: Path,
):
    """Subcommands that don't yet dual-write to the DB (today:
    iterate / train / shard / capture / bench) only have a JSON file.
    The UI's per-request backfill folds them into ``runs.db`` so the
    listing surfaces them as full DB rows. JSON-side rich fields
    (``train_losses``, ``current_epoch``, ...) flow through
    ``run_progress.extra_json`` and get fanned out at read time."""
    _write_json(
        progress_dir, "iter_002_train_v7",
        kind="training", status="running",
        total_epochs=30, current_epoch=10,
        train_losses=[0.5, 0.4, 0.3], val_losses=[0.55, 0.45, 0.35],
        started_at="2026-05-04T12:00:00+00:00",
    )
    runs = client.get("/api/runs").get_json()["runs"]
    assert len(runs) == 1
    r = runs[0]
    assert r["run_id"] == "iter_002_train_v7"
    # JSON-shape fields surfaced via the extra_json fan-out for the
    # front-end renderer.
    assert r["kind"] == "training"
    assert r["current_epoch"] == 10
    assert r["train_losses"] == [0.5, 0.4, 0.3]
    # The backfill landed an actual DB row (no synthesis markers any
    # more).
    assert (progress_dir / "runs.db").is_file()


def test_api_runs_backfill_advances_existing_db_row(
    client, progress_dir: Path,
):
    """When BOTH the DB and a JSON file exist for the same run_id
    (the eval case today; with dual-write the DB row exists from
    start_run + the JSON has progress), the per-request backfill
    advances the DB-side row's progress / status from the JSON.
    Fields like ``machines`` / ``win_rate`` / ``opponent_label`` flow
    into ``extra_json`` and fan out for the renderer."""
    _write_json(
        progress_dir, "eval_v9_vs_v8",
        kind="eval", status="running",
        n_games_done=100, n_games_total=200,
        wins_new=55, wins_old=42, draws=3,
        opponent_label="v8",
        machines=[
            {"label": "macbook", "n_games_done": 60, "n_workers": 14},
            {"label": "desktop", "n_games_done": 40, "n_workers": 16},
        ],
        started_at="2026-05-04T10:00:00+00:00",
    )
    conn = _open_db(progress_dir)
    try:
        # DB lags slightly: progress hasn't been pushed but the run
        # row exists with the run-level metadata the start_run wrote.
        _seed_run(
            conn, "eval_v9_vs_v8", kind="eval", status="running",
            git_commit="dbsha01",
            label="v9_vs_v8",
        )
    finally:
        conn.close()
    runs = client.get("/api/runs").get_json()["runs"]
    assert len(runs) == 1
    r = runs[0]
    assert r["run_id"] == "eval_v9_vs_v8"
    # JSON-side rich fields fanned out from extra_json.
    assert r["machines"][0]["label"] == "macbook"
    assert r["wins_new"] == 55
    assert r["opponent_label"] == "v8"
    # DB-side run-row fields preserved (the backfill leaves them
    # alone via COALESCE).
    assert r["label"] == "v9_vs_v8"
    assert r["git_commit"] == "dbsha01"


def test_api_runs_sorts_by_started_at_desc_across_sources(
    client, progress_dir: Path,
):
    """A mixed pile of DB-only + JSON-only + merged runs sorts as
    one stream by ``started_at`` desc — same invariant the JSON-only
    listing held."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "db_only_old", kind="eval",
            started_at="2026-05-01T08:00:00+00:00",
        )
        _seed_run(
            conn, "merged_mid", kind="eval",
            started_at="2026-05-02T08:00:00+00:00",
        )
    finally:
        conn.close()
    _write_json(
        progress_dir, "merged_mid",
        kind="eval", status="running",
        started_at="2026-05-02T08:00:00+00:00",
    )
    _write_json(
        progress_dir, "json_only_new",
        kind="training", status="running",
        started_at="2026-05-03T08:00:00+00:00",
    )
    runs = client.get("/api/runs").get_json()["runs"]
    assert [r["run_id"] for r in runs] == [
        "json_only_new", "merged_mid", "db_only_old",
    ]


def test_api_runs_skips_per_shard_json_files(
    client, progress_dir: Path,
):
    """Per-shard JSON files (``*_shard_*.json``) are still skipped
    even after the Phase 2 rewrite — the aggregate row in the DB or
    the rolled-up JSON is what surfaces, not N per-shard cards."""
    _write_json(
        progress_dir, "iter_001_self_play_v6",
        kind="data_gen", status="running",
        started_at="2026-05-04T10:00:00+00:00",
    )
    _write_json(
        progress_dir, "iter_001_self_play_v6_shard_local",
        kind="data_gen", status="running",
        started_at="2026-05-04T10:00:00+00:00",
    )
    _write_json(
        progress_dir, "iter_001_self_play_v6_shard_macbook",
        kind="data_gen", status="running",
        started_at="2026-05-04T10:00:00+00:00",
    )
    runs = client.get("/api/runs").get_json()["runs"]
    assert [r["run_id"] for r in runs] == ["iter_001_self_play_v6"]


def test_api_runs_no_db_file_creates_one_via_backfill(
    client, progress_dir: Path,
):
    """If runs.db doesn't exist, the per-request backfill creates it
    on the fly and folds any JSONs in. Phase 2 explicitly runs the
    backfill out of the read path so JSON-only runs surface without
    a manual ``mtg_bot db backfill`` step."""
    _write_json(
        progress_dir, "v1",
        kind="training",
        started_at="2026-05-01T10:00:00+00:00",
        status="completed",
        ended_at="2026-05-01T11:00:00+00:00",
    )
    runs = client.get("/api/runs").get_json()["runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == "v1"
    # Backfill created the DB on demand.
    assert (progress_dir / "runs.db").is_file()


def test_api_runs_corrupt_db_does_not_crash_ui(
    client, progress_dir: Path,
):
    """Defensive: a half-written / unreadable runs.db must not 500
    the UI. The backfill swallows the open error and the listing
    returns empty rather than blowing up."""
    (progress_dir / "runs.db").write_bytes(b"this is not a sqlite database")
    _write_json(
        progress_dir, "v1",
        kind="training",
        started_at="2026-05-01T10:00:00+00:00",
        status="completed",
        ended_at="2026-05-01T11:00:00+00:00",
    )
    res = client.get("/api/runs")
    assert res.status_code == 200
    # The listing returns 200 — exact contents depend on whether the
    # read path could open the corrupt DB at all. The invariant we
    # care about is "no 500".
    runs = res.get_json()["runs"]
    assert isinstance(runs, list)


# ---- /api/runs/<run_id> : per-run detail ----------------------------------


def test_api_run_detail_surfaces_db_events_and_artifacts(
    client, progress_dir: Path,
):
    """Click-through on a run card hits this endpoint. It must
    surface the per-shard progress rows, last 100 events, and
    registered artifacts from the DB so the detail panel can show
    them without an extra round-trip."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_v9", kind="eval", status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
        _seed_progress(
            conn, "eval_v9", n_games_done=50, n_games_total=200,
        )
        _seed_progress(
            conn, "eval_v9", shard_label="macbook",
            n_games_done=30, n_games_total=100,
        )
        _seed_progress(
            conn, "eval_v9", shard_label="desktop",
            n_games_done=20, n_games_total=100,
        )
        _seed_event(
            conn, "eval_v9", "stage_change",
            payload={"stage": "self_play"},
            timestamp="2026-05-04T10:01:00+00:00",
        )
        _seed_event(
            conn, "eval_v9", "promoted",
            payload={"version": "v9"},
            timestamp="2026-05-04T10:02:00+00:00",
        )
        _seed_artifact(
            conn, "eval_v9",
            artifact_type="progress_json",
            path="training_progress/eval_v9.json",
            bytes_=2048,
        )
    finally:
        conn.close()
    res = client.get("/api/runs/eval_v9")
    assert res.status_code == 200
    body = res.get_json()
    assert body["run_id"] == "eval_v9"
    # Aggregate counters surfaced from the (shard_label IS NULL) row.
    assert body["n_games_done"] == 50
    # Per-shard rows in their own bucket.
    per_shard = body["_db_progress_per_shard"]
    labels = sorted(p["shard_label"] for p in per_shard)
    assert labels == ["desktop", "macbook"]
    # Events: latest first by id (insert_event uses autoincrement, so
    # the SECOND event seeded comes back first).
    events = body["_db_events"]
    assert len(events) == 2
    assert events[0]["event_type"] == "promoted"
    assert events[1]["event_type"] == "stage_change"
    # Artifacts.
    arts = body["_db_artifacts"]
    assert len(arts) == 1
    assert arts[0]["artifact_type"] == "progress_json"
    assert arts[0]["bytes"] == 2048


def test_api_run_detail_caps_events_at_100(
    client, progress_dir: Path,
):
    """The DB's get_run() helper already caps events at 100; assert
    the UI passes that cap through unchanged."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(conn, "noisy_run", kind="eval")
        for i in range(150):
            _seed_event(
                conn, "noisy_run", f"event_{i}",
                timestamp=f"2026-05-04T10:{(i // 60) :02d}:{(i % 60) :02d}+00:00",
            )
    finally:
        conn.close()
    body = client.get("/api/runs/noisy_run").get_json()
    assert len(body["_db_events"]) == 100


def test_api_run_detail_for_backfilled_json_only_run(
    client, progress_dir: Path,
):
    """A click-through on a JSON-only run still resolves; the per-
    request backfill folds it into the DB before the detail query
    runs. The rich JSON fields surface via the extra_json fan-out;
    the DB-side arrays start empty (no events / no progress beyond
    the aggregate)."""
    _write_json(
        progress_dir, "iter_002_train_v7",
        kind="training", status="completed",
        started_at="2026-05-04T12:00:00+00:00",
        ended_at="2026-05-04T13:00:00+00:00",
        total_epochs=30, current_epoch=30,
    )
    body = client.get("/api/runs/iter_002_train_v7").get_json()
    assert body["run_id"] == "iter_002_train_v7"
    assert body["current_epoch"] == 30
    assert body["total_epochs"] == 30
    assert body["_db_events"] == []
    # The progress JSON itself gets registered as an artifact.
    artifact_types = {a["artifact_type"] for a in body["_db_artifacts"]}
    assert "progress_json" in artifact_types
    assert body["_db_progress_per_shard"] == []


def test_api_run_detail_404_for_unknown(client):
    res = client.get("/api/runs/no_such_run")
    assert res.status_code == 404


# ---- /api/runs/recent : cross-run aggregations ----------------------------


def test_api_runs_recent_returns_completed_runs_with_summary_stats(
    client, progress_dir: Path,
):
    """The cross-run summary panel asks for "last 20 completed runs
    across all kinds with summary stats". We surface kind / counters
    / wins+draws so the panel can tabulate without per-run details
    fetches."""
    conn = _open_db(progress_dir)
    try:
        # Three runs: 2 completed, 1 running. Recent endpoint returns
        # only the completed pair.
        _seed_run(
            conn, "eval_done_a", kind="eval", status="completed",
            started_at="2026-05-04T10:00:00+00:00",
            ended_at="2026-05-04T11:00:00+00:00",
        )
        _seed_progress(
            conn, "eval_done_a",
            n_games_done=200, n_games_total=200,
            elapsed_seconds=3600.0,
            wins_new=110, wins_old=80, draws=10,
            crashed=0, timed_out=0,
        )
        _seed_run(
            conn, "self_play_done", kind="self_play", status="completed",
            started_at="2026-05-03T10:00:00+00:00",
            ended_at="2026-05-03T13:00:00+00:00",
        )
        _seed_progress(
            conn, "self_play_done",
            n_games_done=500, n_games_total=500,
            elapsed_seconds=10800.0,
            crashed=2, timed_out=4,
        )
        _seed_run(
            conn, "still_running", kind="eval", status="running",
            started_at="2026-05-04T12:00:00+00:00",
        )
    finally:
        conn.close()
    body = client.get("/api/runs/recent").get_json()
    assert body["limit"] == 20
    runs = body["runs"]
    assert len(runs) == 2
    # Newest-first.
    assert [r["run_id"] for r in runs] == [
        "eval_done_a", "self_play_done",
    ]
    # Summary stats from the aggregate progress row.
    a = runs[0]
    assert a["kind"] == "eval"
    assert a["wins_new"] == 110
    assert a["wins_old"] == 80
    assert a["draws"] == 10
    sp = runs[1]
    # self_play translates to data_gen for the UI.
    assert sp["kind"] == "data_gen"
    assert sp["crashed"] == 2


def test_api_runs_recent_respects_limit(client, progress_dir: Path):
    conn = _open_db(progress_dir)
    try:
        for i in range(25):
            _seed_run(
                conn, f"run_{i:02d}", kind="eval", status="completed",
                started_at=f"2026-05-04T10:{i:02d}:00+00:00",
            )
    finally:
        conn.close()
    body = client.get("/api/runs/recent?limit=5").get_json()
    assert len(body["runs"]) == 5
    assert body["limit"] == 5


def test_api_runs_recent_clamps_bad_limit(client, progress_dir: Path):
    """A bogus / out-of-range limit clamps to the default 20 (or
    the [1, 200] range) rather than 500'ing."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "r1", kind="eval", status="completed",
            started_at="2026-05-04T10:00:00+00:00",
        )
    finally:
        conn.close()
    body = client.get("/api/runs/recent?limit=not_a_number").get_json()
    assert body["limit"] == 20
    body = client.get("/api/runs/recent?limit=99999").get_json()
    assert body["limit"] == 200
    body = client.get("/api/runs/recent?limit=-1").get_json()
    # Negative clamps up to 1.
    assert body["limit"] == 1


def test_api_runs_recent_with_no_db_file_returns_empty(client):
    """Recent is explicitly DB-driven; with no DB file it returns an
    empty list rather than walking JSON (the JSON-only fallback is
    a /api/runs concern, not /api/runs/recent)."""
    body = client.get("/api/runs/recent").get_json()
    assert body["runs"] == []


# ---- Stop endpoint over the merged read path ------------------------------


def test_stop_endpoint_finds_db_only_run(client, progress_dir: Path):
    """Even without a JSON file, a DB-known run_id can be stopped.
    The sentinel still lands in progress_dir."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_db_only", kind="eval", status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
    finally:
        conn.close()
    res = client.post("/api/runs/eval_db_only/stop", json={"reason": "test"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["stopped_target"] == "eval_db_only"
    assert (progress_dir / ".STOP_eval_db_only").is_file()


def test_stop_endpoint_uses_db_parent_run_id_as_cycle(
    client, progress_dir: Path,
):
    """When JSON has no ``cycle_id`` but the DB has a
    ``parent_run_id`` set, the stop sentinel targets the parent so
    a stop on a child cancels the whole parent (mirrors the JSON
    cycle_id behavior)."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_001_cycle", kind="iterate", status="running",
            started_at="2026-05-04T09:00:00+00:00",
        )
        _seed_run(
            conn, "iter_001_self_play_v6", kind="self_play",
            status="running", parent_run_id="iter_001_cycle",
            started_at="2026-05-04T10:00:00+00:00",
        )
    finally:
        conn.close()
    res = client.post("/api/runs/iter_001_self_play_v6/stop")
    body = res.get_json()
    assert body["stopped_target"] == "iter_001_cycle"
    assert body["is_cycle_stop"] is True
    assert (progress_dir / ".STOP_iter_001_cycle").is_file()
    assert not (progress_dir / ".STOP_iter_001_self_play_v6").is_file()


def test_stop_status_endpoint_works_for_db_only_run(
    client, progress_dir: Path,
):
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_db_only", kind="eval", status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
    finally:
        conn.close()
    body = client.get("/api/runs/eval_db_only/stop").get_json()
    assert body["stop_requested"] is False
    client.post("/api/runs/eval_db_only/stop")
    body = client.get("/api/runs/eval_db_only/stop").get_json()
    assert body["stop_requested"] is True
    assert body["own_sentinel"] is True


# ---- /api/runs/<id>/replays over the merged read path ---------------------


def test_replays_endpoint_resolves_for_db_only_run(
    client, progress_dir: Path, tmp_path: Path,
):
    """Replays_dir is a JSON-only field today; a DB-only run with no
    JSON correctly returns a "this run did not capture replays"
    response rather than 404. (The endpoint just falls through the
    unset replays_dir branch.)"""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_001_self_play_v6", kind="self_play",
            status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
    finally:
        conn.close()
    res = client.get("/api/runs/iter_001_self_play_v6/replays")
    assert res.status_code == 200
    body = res.get_json()
    assert body["count"] == 0
    assert "did not capture" in body["note"]


# ---- Defensive branches ---------------------------------------------------


def test_ui_kind_from_db_handles_none():
    """Defensive: ``_ui_kind_from_db(None)`` returns None even
    though every real DB row has a NOT-NULL kind. Cheap helper, but
    a future call site (e.g. an aggregation query that selects
    optional columns) shouldn't have to check first."""
    from mtg_bot.training_ui.app import _ui_kind_from_db
    assert _ui_kind_from_db(None) is None
    assert _ui_kind_from_db("eval") == "eval"
    assert _ui_kind_from_db("self_play") == "data_gen"


def test_read_run_file_skips_non_dict_payload(
    client, progress_dir: Path,
):
    """A JSON file that parses to e.g. a list rather than a dict is
    silently skipped — the trainer always writes objects, but a
    typo'd dump shouldn't break the listing."""
    (progress_dir / "list.json").write_text(
        "[1, 2, 3]", encoding="utf-8",
    )
    runs = client.get("/api/runs").get_json()["runs"]
    assert runs == []


def test_extra_json_parse_failure_does_not_crash(
    client, progress_dir: Path,
):
    """If a writer ever stores malformed JSON in run_progress.extra_json
    (e.g. a partially-quoted blob from a buggy serializer), the UI
    must surface the run anyway, just without the fan-out fields."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(conn, "eval_bad_extra", kind="eval", status="running")
        # Bypass upsert_progress so we can write deliberately-broken
        # JSON; ProgressUpdate.extra_json is a TEXT column with no
        # CHECK constraint.
        conn.execute(
            """
            INSERT INTO run_progress(
                run_id, shard_label, n_games_done, extra_json, updated_at
            ) VALUES (?, NULL, ?, ?, ?)
            """,
            ("eval_bad_extra", 5, "{not_json", "2026-05-04T10:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert len(runs) == 1
    assert runs[0]["n_games_done"] == 5
    # No fan-out fields landed because the parse failed; the run still
    # surfaces with its core counter.
    assert "win_rate" not in runs[0]


def test_extra_json_non_dict_parse_does_not_crash(
    client, progress_dir: Path,
):
    """An extra_json that parses to a list rather than a dict (the
    fan-out branch only iterates dict items) likewise doesn't break
    the listing."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(conn, "eval_list_extra", kind="eval", status="running")
        conn.execute(
            """
            INSERT INTO run_progress(
                run_id, shard_label, n_games_done, extra_json, updated_at
            ) VALUES (?, NULL, ?, ?, ?)
            """,
            ("eval_list_extra", 5, "[1, 2, 3]",
             "2026-05-04T10:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert len(runs) == 1


def test_run_detail_for_terminal_db_row_preserves_machines(
    client, progress_dir: Path,
):
    """When the DB has a terminal row + structured progress (the
    dual-write case post-finalize), the backfill leaves the DB-side
    fields alone (idempotency: no clobbering terminal rows) and the
    JSON's rich fields (machines, opponent_label, ...) still surface
    via the run_progress.extra_json fan-out from the live JSON
    backfill into per-shard rows."""
    _write_json(
        progress_dir, "eval_merge",
        kind="eval", status="completed",
        started_at="2026-05-04T10:00:00+00:00",
        ended_at="2026-05-04T11:00:00+00:00",
        wins_new=110, wins_old=80, draws=10,
        opponent_label="v8",
        machines=[{"label": "macbook", "n_games_done": 100}],
    )
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_merge", kind="eval", status="completed",
            started_at="2026-05-04T10:00:00+00:00",
            ended_at="2026-05-04T11:00:00+00:00",
            git_commit="dbsha02",
            label="v9_vs_v8",
        )
        _seed_progress(
            conn, "eval_merge",
            n_games_done=200, n_games_total=200,
            wins_new=110, wins_old=80, draws=10,
            extra={"machines": [{"label": "macbook", "n_games_done": 100}],
                   "opponent_label": "v8"},
        )
        _seed_event(
            conn, "eval_merge", "completed",
            payload={"wins_new": 110},
        )
    finally:
        conn.close()
    body = client.get("/api/runs/eval_merge").get_json()
    # extra_json fan-out preserves the rich fields.
    assert body["machines"][0]["label"] == "macbook"
    assert body["opponent_label"] == "v8"
    # DB row's run-level fields untouched.
    assert body["git_commit"] == "dbsha02"
    assert body["label"] == "v9_vs_v8"
    # Events flow from the DB.
    assert len(body["_db_events"]) == 1
    assert body["_db_events"][0]["event_type"] == "completed"


def test_stop_status_endpoint_404_for_unknown_run(client):
    """GET /api/runs/<unknown>/stop returns 404 — same as the POST
    side and the detail endpoint."""
    res = client.get("/api/runs/no_such_run/stop")
    assert res.status_code == 404


# ---- Phase 2 specific behaviors -------------------------------------------


def test_status_stopped_round_trips_via_extra_json(
    client, progress_dir: Path,
):
    """Producer JSON ``status="stopped"`` maps to DB ``killed`` (the
    DB enum doesn't carry ``stopped``). The original is stashed in
    ``run_progress.extra_json["original_status"]`` and restored at
    UI read time so the user sees ``stopped`` (their nomenclature)."""
    _write_json(
        progress_dir, "iter_005_cycle",
        kind="cycle", status="stopped",
        started_at="2026-05-10T00:36:58+00:00",
        ended_at="2026-05-10T16:03:45+00:00",
        notes="manually marked stopped",
    )
    body = client.get("/api/runs/iter_005_cycle").get_json()
    assert body["status"] == "stopped"
    # _db_kind keeps the canonical DB value.
    assert body["_db_kind"] == "iterate"
    # UI kind translates back to the front-end's "cycle" literal.
    assert body["kind"] == "cycle"


def test_api_runs_attaches_machines_when_aggregate_row_exists(
    client, progress_dir: Path,
):
    # Regression: stages with an aggregate row (the typical iterate
    # self_play / eval case) still want per-machine sub-cards. The
    # rollup-only attachment was an artifact of the
    # missing-aggregate fallback path; per-shard rows should drive
    # the machines array regardless of whether the aggregate fired.
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_009_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-18T17:35:00+00:00",
        )
        # Aggregate row present.
        _seed_progress(
            conn, "iter_009_self_play_v5", shard_label=None,
            n_games_done=4, n_games_total=10,
            elapsed_seconds=600.0,
        )
        # Per-shard rows.
        _seed_progress(
            conn, "iter_009_self_play_v5",
            shard_label="DESKTOP-J05412I",
            n_games_done=3, n_games_total=10,
            elapsed_seconds=600.0,
            extra={"n_workers": 16},
        )
        _seed_progress(
            conn, "iter_009_self_play_v5",
            shard_label="Greggs-MacBook-Pro.local",
            n_games_done=1, n_games_total=10,
            elapsed_seconds=420.0,
            extra={"n_workers": 6},
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "iter_009_self_play_v5"]
    # Aggregate counters preserved (this is the existing-aggregate
    # path, not the rollup fallback).
    assert r["n_games_done"] == 4
    # Machines attached from per-shard rows.
    assert "machines" in r
    labels = sorted(m["label"] for m in r["machines"])
    assert labels == ["DESKTOP-J05412I", "Greggs-MacBook-Pro.local"]
    by_label = {m["label"]: m for m in r["machines"]}
    assert by_label["DESKTOP-J05412I"]["n_workers"] == 16
    assert by_label["Greggs-MacBook-Pro.local"]["n_workers"] == 6


def test_api_runs_cycle_inherits_machines_from_active_stage(
    client, progress_dir: Path,
):
    # When listing cycles, the per-machine sub-cards should reflect
    # the active stage's per-shard rows. Without this the cycle card
    # shows aggregated counters but no machines breakdown, which is
    # the UI defect this fixes.
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_009_cycle", kind="iterate",
            status="running",
            started_at="2026-05-18T17:30:00+00:00",
        )
        # Cycle's own aggregate row (kind=iterate progress).
        _seed_progress(
            conn, "iter_009_cycle", shard_label=None,
            n_games_done=4,
        )
        # Child stage.
        _seed_run(
            conn, "iter_009_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-18T17:31:00+00:00",
            parent_run_id="iter_009_cycle",
        )
        _seed_progress(
            conn, "iter_009_self_play_v5", shard_label=None,
            n_games_done=4, n_games_total=10,
            elapsed_seconds=600.0,
        )
        _seed_progress(
            conn, "iter_009_self_play_v5",
            shard_label="DESKTOP-J05412I",
            n_games_done=3, n_games_total=10,
            elapsed_seconds=600.0,
            extra={"n_workers": 16},
        )
        _seed_progress(
            conn, "iter_009_self_play_v5",
            shard_label="Greggs-MacBook-Pro.local",
            n_games_done=1, n_games_total=10,
            elapsed_seconds=420.0,
            extra={"n_workers": 6},
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "iter_009_cycle"]
    # Cycle's UI kind is folded to the active stage's kind.
    assert r["kind"] == "data_gen"
    assert r["_db_kind"] == "iterate"
    # Cycle inherits machines from the active stage's per-shard rows.
    assert "machines" in r
    labels = sorted(m["label"] for m in r["machines"])
    assert labels == ["DESKTOP-J05412I", "Greggs-MacBook-Pro.local"]


def test_api_runs_exposes_nodes_from_config_json(
    client, progress_dir: Path,
):
    # The MCTS node-budget surfaces as ``run.nodes`` for the UI's
    # "Depth (nodes)" stat. v5 was iter_005's 200-node baseline; iter
    # cycles at the bumped --nodes 400 want this visible at a glance.
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_009_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-18T17:35:00+00:00",
            config_json=json.dumps({"nodes": 400, "samples": 4}),
        )
    finally:
        conn.close()
    res = client.get("/api/runs")
    [r] = [r for r in res.get_json()["runs"]
           if r["run_id"] == "iter_009_self_play_v5"]
    assert r["nodes"] == 400


def test_per_shard_progress_rows_synthesize_machines_array(
    client, progress_dir: Path,
):
    """The front-end's per-machine sub-card renderer reads ``machines
    = [{label, n_games_done, n_workers, status}, ...]``. When the JSON
    is gone (Phase 3 endgame) the UI derives this array from the
    structured per-shard ``run_progress`` rows + their ``extra_json``."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_v9", kind="eval", status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
        _seed_progress(
            conn, "eval_v9", shard_label="macbook",
            n_games_done=60, n_games_total=100, crashed=2,
            elapsed_seconds=1200.5, timed_out=3,
            wins_new=40, wins_old=18, draws=2,
            extra={"n_workers": 14, "status": "running"},
        )
        _seed_progress(
            conn, "eval_v9", shard_label="desktop",
            n_games_done=40, n_games_total=100, crashed=0,
            elapsed_seconds=900.0, timed_out=0,
            wins_new=30, wins_old=10, draws=0,
            extra={"n_workers": 16, "status": "completed"},
        )
    finally:
        conn.close()
    body = client.get("/api/runs/eval_v9").get_json()
    machines = body["machines"]
    # Order matches the DB ORDER BY shard_label.
    labels = [m["label"] for m in machines]
    assert sorted(labels) == ["desktop", "macbook"]
    by_label = {m["label"]: m for m in machines}
    assert by_label["macbook"]["n_workers"] == 14
    assert by_label["macbook"]["n_games_done"] == 60
    assert by_label["macbook"]["status"] == "running"
    assert by_label["desktop"]["status"] == "completed"
    # Structured counter columns must surface onto each machine dict so
    # the front-end can compute secs/game (elapsed_seconds /
    # n_games_done), render the timeout count, and show wins/losses
    # per shard. Without this fan-out the UI's secs/game fallback
    # would always return a dash because the column-level fields
    # never reach the JSON.
    assert by_label["macbook"]["elapsed_seconds"] == 1200.5
    assert by_label["macbook"]["n_games_total"] == 100
    assert by_label["macbook"]["timed_out"] == 3
    assert by_label["macbook"]["wins_new"] == 40
    assert by_label["macbook"]["wins_old"] == 18
    assert by_label["macbook"]["draws"] == 2
    assert by_label["desktop"]["elapsed_seconds"] == 900.0


def test_extra_json_preserves_train_loss_arrays(
    client, progress_dir: Path,
):
    """The training chart needs ``train_losses`` / ``val_losses`` /
    the four sub-arrays. These flow through extra_json after the
    backfill runs against the producer's training JSON."""
    _write_json(
        progress_dir, "iter_002_train_v7",
        kind="training", status="completed",
        started_at="2026-05-04T12:00:00+00:00",
        ended_at="2026-05-04T13:00:00+00:00",
        total_epochs=3, current_epoch=3,
        train_losses=[0.5, 0.4, 0.3],
        val_losses=[0.55, 0.45, 0.35],
        train_value_losses=[0.3, 0.25, 0.2],
        val_value_losses=[0.32, 0.28, 0.22],
        train_policy_losses=[0.18, 0.18, 0.18],
        val_policy_losses=[0.19, 0.19, 0.19],
        policy_loss_weight=1.0,
    )
    body = client.get("/api/runs/iter_002_train_v7").get_json()
    assert body["train_losses"] == [0.5, 0.4, 0.3]
    assert body["val_losses"] == [0.55, 0.45, 0.35]
    assert body["train_value_losses"] == [0.3, 0.25, 0.2]
    assert body["val_policy_losses"] == [0.19, 0.19, 0.19]
    assert body["policy_loss_weight"] == 1.0


def test_iterate_cycle_kind_renders_as_cycle_to_ui(
    client, progress_dir: Path,
):
    """The DB enum ``iterate`` corresponds to the front-end's ``cycle``
    discriminator (legacy JSON nomenclature). The renderer keys off
    ``kind=cycle`` so we map at read time."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_001_cycle", kind="iterate", status="running",
            started_at="2026-05-04T05:00:00+00:00",
        )
    finally:
        conn.close()
    runs = client.get("/api/runs").get_json()["runs"]
    assert len(runs) == 1
    r = runs[0]
    assert r["kind"] == "cycle"
    assert r["_db_kind"] == "iterate"


def test_replays_endpoint_pulls_replays_dir_from_extra_json(
    client, progress_dir: Path, tmp_path: Path,
):
    """``replays_dir`` is a JSON-only field; after the backfill it
    lives in run_progress.extra_json and fans out at read time. The
    /replays endpoint reads it from the surfaced field."""
    rep_dir = tmp_path / "replays" / "iter_001_self_play_v6"
    rep_dir.mkdir(parents=True)
    (rep_dir / "g1.json.gz").write_bytes(b"")
    _write_json(
        progress_dir, "iter_001_self_play_v6",
        kind="data_gen", status="completed",
        started_at="2026-05-04T10:00:00+00:00",
        ended_at="2026-05-04T11:00:00+00:00",
        replays_dir=str(rep_dir),
    )
    body = client.get(
        "/api/runs/iter_001_self_play_v6/replays",
    ).get_json()
    assert body["count"] == 1
    assert body["replays"][0]["filename"] == "g1.json.gz"


def test_api_runs_recent_does_not_crash_on_corrupt_db(
    progress_dir: Path,
):
    """Defensive: the recent endpoint must tolerate a corrupt DB —
    return 200 with an empty list rather than 500."""
    from mtg_bot.training_ui.app import create_app
    (progress_dir / "runs.db").write_bytes(b"not a sqlite db")
    app = create_app(progress_dir)
    client = app.test_client()
    res = client.get("/api/runs/recent")
    assert res.status_code == 200
    assert isinstance(res.get_json()["runs"], list)


def test_extra_json_with_original_status_overrides_status(
    client, progress_dir: Path,
):
    """If the structured DB status conflicts with extra_json's
    ``original_status`` (the backfill stash), the UI surfaces the
    JSON-side label so the user sees their producer's actual
    terminology."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "killed_with_history", kind="iterate",
            status="killed",
            started_at="2026-05-04T05:00:00+00:00",
            ended_at="2026-05-04T06:00:00+00:00",
        )
        _seed_progress(
            conn, "killed_with_history",
            extra={"original_status": "stopped"},
        )
    finally:
        conn.close()
    runs = client.get("/api/runs").get_json()["runs"]
    assert runs[0]["status"] == "stopped"


def test_read_json_cycle_id_handles_corrupt_json(progress_dir: Path):
    """``_read_json_cycle_id`` is the freshness-aware lookup the stop
    endpoint uses. Corrupt / non-dict / no-such-file inputs all return
    None gracefully."""
    from mtg_bot.training_ui.app import _read_json_cycle_id
    # No file: None.
    assert _read_json_cycle_id(progress_dir, "nope") is None
    # Corrupt JSON: None.
    (progress_dir / "broken.json").write_text("{not json", encoding="utf-8")
    assert _read_json_cycle_id(progress_dir, "broken") is None
    # JSON parses but isn't a dict: None.
    (progress_dir / "list.json").write_text("[1, 2]", encoding="utf-8")
    assert _read_json_cycle_id(progress_dir, "list") is None
    # JSON has a non-string cycle_id: None.
    (progress_dir / "weird.json").write_text(
        '{"cycle_id": 42}', encoding="utf-8",
    )
    assert _read_json_cycle_id(progress_dir, "weird") is None
    # JSON has a real cycle_id: returns it.
    (progress_dir / "good.json").write_text(
        '{"cycle_id": "iter_001_cycle"}', encoding="utf-8",
    )
    assert _read_json_cycle_id(progress_dir, "good") == "iter_001_cycle"


def test_per_shard_machines_tolerates_malformed_extra_json(
    client, progress_dir: Path,
):
    """A per-shard ``run_progress`` row whose ``extra_json`` is
    malformed shouldn't break the synthesized ``machines`` array —
    we silently fall back to the structured columns."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_v9", kind="eval", status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
        # Bypass upsert so we can write deliberately-broken JSON.
        conn.execute(
            """
            INSERT INTO run_progress(
                run_id, shard_label, n_games_done, extra_json, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("eval_v9", "macbook", 60, "{not_json", "2026-05-04T10:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    body = client.get("/api/runs/eval_v9").get_json()
    machines = body["machines"]
    assert len(machines) == 1
    assert machines[0]["label"] == "macbook"
    assert machines[0]["n_games_done"] == 60


def test_aggregate_row_derives_rates_and_eta_for_self_play(
    client, progress_dir: Path,
):
    """When the writer populates an aggregate run_progress row with
    n_games_done + elapsed_seconds + extra_json[n_samples], the UI
    derives ``games_per_hour``, ``samples_per_hour``, and
    ``estimated_remaining_seconds`` at read time. The headline UI
    stats card (SAMPLES, GAMES/HR, SAMPLES/HR, ETA) reads these fields
    so all four must surface for any aggregate-row run, not just the
    per-shard-rollup fallback path."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "smoke_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-16T06:00:00+00:00",
        )
        _seed_progress(
            conn, "smoke_self_play_v5",
            n_games_done=10, n_games_total=100,
            elapsed_seconds=200.0,  # 200s for 10 games -> 180/hr
            extra={"n_samples": 5000, "n_workers": 3},
        )
    finally:
        conn.close()
    body = client.get("/api/runs/smoke_self_play_v5").get_json()
    # Counters fanned out as before.
    assert body["n_games_done"] == 10
    assert body["n_games_total"] == 100
    assert body["n_samples"] == 5000
    assert body["n_workers"] == 3
    # Derived: 10 games / 200s × 3600 = 180 games/hr.
    assert body["games_per_hour"] == pytest.approx(180.0)
    # Derived: 5000 samples / 200s × 3600 = 90000 samples/hr.
    assert body["samples_per_hour"] == pytest.approx(90000.0)
    # 90 games remaining × 20s/game = 1800s ETA.
    assert body["estimated_remaining_seconds"] == pytest.approx(1800.0)


def test_aggregate_row_skips_derivation_when_no_games_done_yet(
    client, progress_dir: Path,
):
    """Fresh stage with 0 games done shouldn't divide-by-zero or
    surface nonsense rates. games_per_hour / samples_per_hour /
    estimated_remaining_seconds stay absent (UI renders ``—``).
    """
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "fresh_run", kind="self_play", status="running",
            started_at="2026-05-16T06:00:00+00:00",
        )
        _seed_progress(
            conn, "fresh_run",
            n_games_done=0, n_games_total=100,
            elapsed_seconds=5.0,
            extra={"n_samples": 0, "n_workers": 3},
        )
    finally:
        conn.close()
    body = client.get("/api/runs/fresh_run").get_json()
    assert body["n_games_done"] == 0
    # Derived rates absent until first game lands.
    assert body.get("games_per_hour") is None
    assert body.get("samples_per_hour") is None
    assert body.get("estimated_remaining_seconds") is None


def test_extra_json_preserves_underscore_keys_in_top_level(
    client, progress_dir: Path,
):
    """Internal markers like ``backfill_note`` start with an underscore
    only when the backfill chooses to (most don't). Today the backfill
    writes ``backfill_note`` / ``original_status`` / ``orphan_cycle_id``
    without leading underscores; the `_`-prefix-passthrough branch in
    `_row_to_ui_dict` covers any future additions that DO use a
    leading underscore."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "with_marker", kind="eval", status="running",
            started_at="2026-05-04T10:00:00+00:00",
        )
        _seed_progress(
            conn, "with_marker",
            extra={"_some_internal_marker": "abc", "win_rate": 0.5},
        )
    finally:
        conn.close()
    body = client.get("/api/runs/with_marker").get_json()
    assert body["_some_internal_marker"] == "abc"
    assert body["win_rate"] == 0.5


def test_config_json_replay_fields_fan_out_to_top_level(
    client, progress_dir: Path,
):
    """``replays_dir`` + the two ``capture_every_*`` rates live in
    iterate's ``config_json`` (cycle rows don't carry them in
    ``run_progress.extra_json``). The UI's
    ``if (!run.replays_dir) → 'replay capture: off'`` branch needs
    them surfaced at the top level so iter cards label correctly when
    capture is configured."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_004_cycle", kind="iterate", status="running",
            started_at="2026-05-13T05:00:00+00:00",
            config_json=json.dumps({
                "kind": "cycle",
                "iter_idx": 4,
                "replays_dir": "replays",
                "capture_every_self_play": 20,
                "capture_every_eval": 0,
            }),
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_004_cycle").get_json()
    assert body["replays_dir"] == "replays"
    assert body["capture_every_self_play"] == 20
    assert body["capture_every_eval"] == 0


def test_config_json_replay_fields_absent_when_not_in_config(
    client, progress_dir: Path,
):
    """When ``config_json`` doesn't carry the replay fields (older
    iterate rows that predate the fan-out, or non-iterate runs), the
    UI dict must NOT invent values — the JS branch correctly falls
    back to "off"."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "eval_v4_vs_v3", kind="eval", status="running",
            started_at="2026-05-14T01:00:00+00:00",
            config_json=json.dumps({"new_version": "v4", "old_version": "v3"}),
        )
    finally:
        conn.close()
    body = client.get("/api/runs/eval_v4_vs_v3").get_json()
    assert "replays_dir" not in body
    assert "capture_every_self_play" not in body
    assert "capture_every_eval" not in body


def test_config_json_malformed_blob_does_not_break_endpoint(
    client, progress_dir: Path,
):
    """A non-JSON ``config_json`` blob (legacy / corrupted row)
    must not 500 the endpoint. The except branch swallows the parse
    error; the rest of the UI dict still surfaces."""
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_bogus_cycle", kind="iterate", status="running",
            started_at="2026-05-13T05:00:00+00:00",
            config_json="{not-json",
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_bogus_cycle").get_json()
    assert body["run_id"] == "iter_bogus_cycle"
    assert "replays_dir" not in body


def test_cycle_replays_aggregate_via_parent_run_id(
    client, progress_dir: Path, tmp_path: Path,
):
    """Cycle ``/replays`` walks ``runs.parent_run_id`` to find stage
    + shard descendants and globs each descendant's subdir. The cycle's
    own ``replays_dir`` (``config_json``-side) is the BARE ROOT; we
    must not enumerate flat files at that root, only the per-descendant
    subdirs. Subdir names match the descendant ``run_id`` (iterate's
    fs convention)."""
    replays_root = tmp_path / "replays"
    # Two stage descendants, one shard descendant under a stage. All
    # three have their own capture subdirs under the cycle root.
    sp_dir = replays_root / "iter_009_self_play_v5"
    ev_dir = replays_root / "iter_009_eval_v5_vs_v4"
    sp_shard_dir = replays_root / "iter_009_self_play_v5_shard_local"
    for d in (sp_dir, ev_dir, sp_shard_dir):
        d.mkdir(parents=True)
    (sp_dir / "game_seed0_idx0020.json.gz").write_bytes(b"")
    (sp_dir / "game_seed0_idx0040.json.gz").write_bytes(b"")
    (ev_dir / "game_seed1_idx0000.json.gz").write_bytes(b"")
    (sp_shard_dir / "game_seed2_idx0000.json.gz").write_bytes(b"")
    # Bare-root flat file that must NOT surface (legacy leftover):
    (replays_root / "legacy_probe.json.gz").write_bytes(b"")
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_009_cycle", kind="iterate", status="running",
            started_at="2026-05-13T05:00:00+00:00",
            config_json=json.dumps({
                "kind": "cycle", "iter_idx": 9,
                "replays_dir": str(replays_root),
                "capture_every_self_play": 20,
                "capture_every_eval": 50,
            }),
        )
        _seed_run(
            conn, "iter_009_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-13T05:01:00+00:00",
            parent_run_id="iter_009_cycle",
        )
        _seed_run(
            conn, "iter_009_eval_v5_vs_v4", kind="eval", status="running",
            started_at="2026-05-13T05:02:00+00:00",
            parent_run_id="iter_009_cycle",
        )
        _seed_run(
            conn, "iter_009_self_play_v5_shard_local", kind="self_play",
            status="running",
            started_at="2026-05-13T05:01:30+00:00",
            parent_run_id="iter_009_self_play_v5",  # transitive
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_009_cycle/replays").get_json()
    assert body["count"] == 4
    subpaths = sorted(r["subpath"] for r in body["replays"])
    assert subpaths == [
        "iter_009_eval_v5_vs_v4/game_seed1_idx0000.json.gz",
        "iter_009_self_play_v5/game_seed0_idx0020.json.gz",
        "iter_009_self_play_v5/game_seed0_idx0040.json.gz",
        "iter_009_self_play_v5_shard_local/game_seed2_idx0000.json.gz",
    ]
    # The legacy flat file at the bare root must NOT be in the list.
    assert all("legacy_probe" not in s for s in subpaths)


def test_cycle_replays_empty_when_no_descendants(
    client, progress_dir: Path, tmp_path: Path,
):
    """A cycle that hasn't started any stage runs yet (or whose
    descendants have no replays_dir on disk) returns count=0 — not
    a 500, and not the bare-root flat files."""
    replays_root = tmp_path / "replays"
    replays_root.mkdir()
    (replays_root / "stray.json.gz").write_bytes(b"")
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_010_cycle", kind="iterate", status="running",
            started_at="2026-05-13T05:00:00+00:00",
            config_json=json.dumps({
                "kind": "cycle", "iter_idx": 10,
                "replays_dir": str(replays_root),
                "capture_every_self_play": 20,
                "capture_every_eval": 0,
            }),
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_010_cycle/replays").get_json()
    assert body["count"] == 0
    assert body["replays"] == []
    assert str(replays_root) == body["replays_dir"]


def test_cycle_replays_skips_missing_descendant_subdirs(
    client, progress_dir: Path, tmp_path: Path,
):
    """A descendant whose subdir doesn't exist yet on disk (capture
    rate set but no game has hit a capture point) doesn't crash —
    that descendant just contributes 0 files."""
    replays_root = tmp_path / "replays"
    sp_dir = replays_root / "iter_011_self_play_v5"
    sp_dir.mkdir(parents=True)
    (sp_dir / "g.json.gz").write_bytes(b"")
    # ev_dir intentionally NOT created — descendant exists in DB but
    # no on-disk subdir yet.
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_011_cycle", kind="iterate", status="running",
            started_at="2026-05-13T05:00:00+00:00",
            config_json=json.dumps({
                "kind": "cycle",
                "replays_dir": str(replays_root),
                "capture_every_self_play": 20,
                "capture_every_eval": 50,
            }),
        )
        _seed_run(
            conn, "iter_011_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-13T05:01:00+00:00",
            parent_run_id="iter_011_cycle",
        )
        _seed_run(
            conn, "iter_011_eval_v5_vs_v4", kind="eval", status="running",
            started_at="2026-05-13T05:02:00+00:00",
            parent_run_id="iter_011_cycle",
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_011_cycle/replays").get_json()
    assert body["count"] == 1
    assert body["replays"][0]["subpath"] == (
        "iter_011_self_play_v5/g.json.gz"
    )


def test_cycle_replays_falls_back_to_default_root(
    client, progress_dir: Path, tmp_path: Path, monkeypatch,
):
    """Older cycle rows that predate the ``replays_dir`` fan-out have
    no ``replays_dir`` in config_json. The endpoint falls back to
    iterate's argparse default ``Path("replays")`` so those cycles
    still surface their captures."""
    workdir = tmp_path / "work"
    sp_dir = workdir / "replays" / "iter_012_self_play_v5"
    sp_dir.mkdir(parents=True)
    (sp_dir / "g.json.gz").write_bytes(b"")
    monkeypatch.chdir(workdir)
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_012_cycle", kind="iterate", status="running",
            started_at="2026-05-13T05:00:00+00:00",
            config_json=json.dumps({"kind": "cycle", "iter_idx": 12}),
        )
        _seed_run(
            conn, "iter_012_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-13T05:01:00+00:00",
            parent_run_id="iter_012_cycle",
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_012_cycle/replays").get_json()
    assert body["count"] == 1
    assert body["replays_dir"] == "replays"
    assert body["replays"][0]["subpath"] == (
        "iter_012_self_play_v5/g.json.gz"
    )


def test_cycle_replays_aggregates_shard_subdirs_via_run_progress(
    client, progress_dir: Path, tmp_path: Path,
):
    """Shards are not separate ``runs`` rows — they live as
    ``run_progress`` rows keyed on ``(stage_run_id, shard_label)``.
    iterate's filesystem convention writes shard captures to
    ``<root>/<stage_run_id>_shard_<shard_label>/`` (``distributed.py``
    line 4977's ``run_id_full``). The aggregator must walk those
    subdirs in addition to the bare stage subdir."""
    replays_root = tmp_path / "replays"
    stage_dir = replays_root / "iter_014_self_play_v5"
    shard_local = replays_root / "iter_014_self_play_v5_shard_local"
    shard_mac = (
        replays_root
        / "iter_014_self_play_v5_shard_greggs-macbook-pro"
    )
    for d in (stage_dir, shard_local, shard_mac):
        d.mkdir(parents=True)
    (stage_dir / "stage.json.gz").write_bytes(b"")
    (shard_local / "local_a.json.gz").write_bytes(b"")
    (shard_local / "local_b.json.gz").write_bytes(b"")
    (shard_mac / "mac.json.gz").write_bytes(b"")
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_014_cycle", kind="iterate", status="running",
            started_at="2026-05-13T05:00:00+00:00",
            config_json=json.dumps({
                "kind": "cycle",
                "replays_dir": str(replays_root),
                "capture_every_self_play": 20,
                "capture_every_eval": 0,
            }),
        )
        _seed_run(
            conn, "iter_014_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-13T05:01:00+00:00",
            parent_run_id="iter_014_cycle",
        )
        # Per-shard rows: presence of shard_label is what flags them
        # as shards rather than aggregate. The aggregator should
        # synthesize <stage>_shard_<label> for each.
        _seed_progress(
            conn, "iter_014_self_play_v5", shard_label="local",
            n_games_done=80,
        )
        _seed_progress(
            conn, "iter_014_self_play_v5",
            shard_label="greggs-macbook-pro", n_games_done=200,
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_014_cycle/replays").get_json()
    assert body["count"] == 4
    subpaths = sorted(r["subpath"] for r in body["replays"])
    assert subpaths == [
        "iter_014_self_play_v5/stage.json.gz",
        "iter_014_self_play_v5_shard_greggs-macbook-pro/mac.json.gz",
        "iter_014_self_play_v5_shard_local/local_a.json.gz",
        "iter_014_self_play_v5_shard_local/local_b.json.gz",
    ]


def test_stage_replays_unchanged_by_cycle_branch(
    client, progress_dir: Path, tmp_path: Path,
):
    """The cycle branch is gated on ``_db_kind == 'iterate'``; a
    stage row (kind=self_play) still uses the legacy single-subdir
    glob without parent-tree aggregation."""
    rep_dir = tmp_path / "replays" / "iter_013_self_play_v5"
    rep_dir.mkdir(parents=True)
    (rep_dir / "a.json.gz").write_bytes(b"")
    (rep_dir / "b.json.gz").write_bytes(b"")
    conn = _open_db(progress_dir)
    try:
        _seed_run(
            conn, "iter_013_self_play_v5", kind="self_play",
            status="running",
            started_at="2026-05-13T05:01:00+00:00",
        )
        _seed_progress(
            conn, "iter_013_self_play_v5",
            extra={"replays_dir": str(rep_dir)},
        )
    finally:
        conn.close()
    body = client.get("/api/runs/iter_013_self_play_v5/replays").get_json()
    assert body["count"] == 2
    assert body["replays_dir"] == str(rep_dir)
    # Stage subpath is just `<this_run_id>/<filename>` (replays_dir.name
    # / filename); no parent-tree walk.
    subpaths = sorted(r["subpath"] for r in body["replays"])
    assert subpaths == [
        "iter_013_self_play_v5/a.json.gz",
        "iter_013_self_play_v5/b.json.gz",
    ]
