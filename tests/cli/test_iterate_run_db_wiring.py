"""End-to-end test that ``mtg_bot iterate``'s main() body correctly
issues the cycle-level + per-stage start_run / push_progress /
push_event / push_artifact / finish_run trio against the SQLite run
DB alongside its existing JSON writes.

The iterate body is ``# pragma: no cover`` (lots of orchestration
plumbing); we test it here by stubbing out the heavy downstream
calls (``_self_play``, ``_train_next``, ``_eval_match``,
``sweep_local_orphans``, ...) with fakes that record what they were
asked to do, then asserting the DB rows + events that landed.

This pins the contract between ``mtg_bot.cli.iterate.main`` and the
``mtg_bot.cli.runs`` lifecycle / client surface — a regression on
the iterate side (drop the push_event, swap the kind, forget the
artifact registration, ...) fails this test rather than silently
breaking the UI's runs.db query in production.

Sibling slice notes: the cycle row uses ``kind="iterate"`` because
the schema's CHECK constraint enumerates KINDS as
``(iterate, self_play, eval, bench, capture, training)``; ``cycle``
is not a permitted value. Stage-level rows use the matching schema
kinds: ``self_play`` (not ``data_gen``), ``training``, ``eval``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mtg_bot.cli import iterate as cli_iterate
from mtg_bot.cli.runs import client as runs_client
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs import lifecycle


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _make_version_dir(
    registry_root: Path,
    version: str,
    *,
    hidden_sizes: list[int] | None = None,
) -> None:
    """Synthesize a registry entry the iterate driver can read off
    as the bootstrap version. Mirrors ``test_iterate_v2_wiring._make_version_dir``.
    """
    if hidden_sizes is None:
        hidden_sizes = [4]
    d = registry_root / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "weights.pt").write_bytes(b"\x00")
    payload: dict[str, Any] = {
        "version": version,
        "created_at": "2026-05-06T00:00:00Z",
        "feature_dim": 1,
        "hidden_sizes": hidden_sizes,
        "with_policy": True,
        "architecture": "shared",
        "action_encoding_version": "positional_v1",
    }
    (d / "metadata.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )


class _CallRecorder:
    """Records every positional + keyword call made through it. Used
    to verify the iterate driver issued the right client.* calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def make(self, name: str):
        def _spy(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None
        return _spy

    def of(self, name: str) -> list[tuple[tuple, dict]]:
        """Return positional/keyword tuples for every call matching name."""
        return [(a, k) for (n, a, k) in self.calls if n == name]


# ----------------------------------------------------------------------
# Common test setup helpers
# ----------------------------------------------------------------------


def _baseline_argv(
    *,
    tmp_path: Path,
    deck_pool: Path,
    bootstrap: str = "v1",
    n_iterations: int = 1,
    eval_games: int = 0,
    acceptance_threshold: float = 0.0,
) -> list[str]:
    """Minimal argv for the iterate CLI. Defaults to no eval gate
    (``--eval-games 0 --acceptance-threshold 0``) so the no-gate
    happy-path is the default fixture; tests that exercise the eval
    stage flip both knobs."""
    return [
        "--bootstrap-version", bootstrap,
        "--n-iterations", str(n_iterations),
        "--games-per-iteration", "2",
        "--samples", "1",
        "--nodes", "1",
        "--epochs", "1",
        "--eval-games", str(eval_games),
        "--acceptance-threshold", str(acceptance_threshold),
        "--data-dir", str(tmp_path / "iterate_data"),
        "--registry-root", str(tmp_path / "trained_weights"),
        "--progress-dir", str(tmp_path / "training_progress"),
        "--deck-pool", str(deck_pool),
        "--seed", "0",
        "--capture-every-self-play", "0",
        "--capture-every-eval", "0",
        "--hang-dump-dir", "",
        "--replays-dir", str(tmp_path / "replays"),
        # Opt out of shards_config.json auto-detection — these tests
        # stub local Pool downstream and don't want a real repo-root
        # shards_config.json to flip dispatch into distributed mode.
        "--shards-config", "",
    ]


def _setup_mocks_for_iterate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    self_play_raises: BaseException | None = None,
    train_raises: BaseException | None = None,
    eval_returns: tuple[int, int, int, float] | None = None,
    eval_raises: BaseException | None = None,
) -> None:
    """Stub out the heavy downstream calls inside ``cli_iterate`` so
    main() can run end-to-end on a tmp_path. The defaults make every
    stage succeed with canned-but-deterministic counters."""
    def _fake_self_play(*args, **kwargs):
        if self_play_raises is not None:
            raise self_play_raises
        # Touch the output npz so the artifact-size lookup succeeds.
        output: Path = kwargs["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00" * 17)
        # Also touch the progress JSON so the lifecycle artifact
        # registration sees a real on-disk file.
        progress_path = kwargs.get("progress_path")
        if progress_path is not None:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text("{}", encoding="utf-8")
        return (100, 50, 1.23)  # n_samples, n_policy, elapsed

    def _fake_self_play_dist(*args, **kwargs):
        # Distributed branch — not exercised in the local baseline
        # tests but still pinned to deterministic behavior.
        return (100, 50, 1.23)

    def _fake_train_next(*args, **kwargs):
        if train_raises is not None:
            raise train_raises
        # Add v2 to the registry so registry.weights_path(new_version)
        # works downstream. The actual weights file must exist for the
        # bytes-size lookup in the iterate driver's artifact register.
        registry_root: Path = kwargs["registry_root"]
        v2_dir = registry_root / "v2"
        v2_dir.mkdir(parents=True, exist_ok=True)
        (v2_dir / "weights.pt").write_bytes(b"\x00" * 31)
        (v2_dir / "metadata.json").write_text(
            json.dumps({
                "version": "v2",
                "created_at": "2026-05-06T00:00:00Z",
                "feature_dim": 1,
                "hidden_sizes": [4],
                "with_policy": True,
                "architecture": "shared",
                "action_encoding_version": "positional_v1",
            }),
            encoding="utf-8",
        )
        # Mirror train_nn.py's progress JSON write.
        progress_path = kwargs.get("progress_path")
        if progress_path is not None:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text("{}", encoding="utf-8")
        return "v2"

    def _fake_eval_match(*args, **kwargs):
        if eval_raises is not None:
            raise eval_raises
        # Touch the progress JSON so the lifecycle artifact-register
        # sees a real file.
        progress_path = kwargs.get("progress_path")
        if progress_path is not None:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text("{}", encoding="utf-8")
        return (eval_returns or (60, 30, 10, 4.56))

    monkeypatch.setattr(cli_iterate, "_self_play", _fake_self_play)
    monkeypatch.setattr(
        cli_iterate, "_self_play_distributed", _fake_self_play_dist,
    )
    monkeypatch.setattr(cli_iterate, "_train_next", _fake_train_next)
    monkeypatch.setattr(cli_iterate, "_eval_match", _fake_eval_match)
    # Orphan sweep no-ops — would otherwise scan the live system.
    # sweep_remote_orphans was deleted with the SSH path.
    monkeypatch.setattr(
        cli_iterate, "sweep_local_orphans", lambda *a, **kw: None,
    )
    # Deck pool: pretend a non-empty list of decks loaded.
    monkeypatch.setattr(
        cli_iterate, "decks_from_json",
        lambda p: [_FakeDeck(), _FakeDeck()],
    )
    # find_foreign_npzs: empty (no foreign npzs to abort on).
    monkeypatch.setattr(
        cli_iterate, "find_foreign_npzs", lambda *a, **kw: [],
    )


class _FakeDeck:
    card_count = 60


# ----------------------------------------------------------------------
# Tests — happy path (no eval gate)
# ----------------------------------------------------------------------


def test_iterate_main_writes_cycle_and_self_play_train_run_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """One iteration with no eval gate must write:
    - One cycle row (kind=iterate, status=completed) with the config.
    - One self_play row (kind=self_play, status=completed, parent=cycle).
    - One training row (kind=training, status=completed, parent=cycle).
    - cycle_started + stage_started/stage_completed events.
    - npz + weights + progress_json artifacts.
    """
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc1234")

    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")

    _setup_mocks_for_iterate(monkeypatch)

    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=0, acceptance_threshold=0.0,
    )

    cli_iterate.main(argv)

    conn = runs_db.connect(db_path)
    try:
        runs = list(conn.execute(
            "SELECT * FROM runs ORDER BY started_at"
        ).fetchall())
        progress = list(conn.execute(
            "SELECT * FROM run_progress"
        ).fetchall())
        events = list(conn.execute(
            "SELECT * FROM run_events ORDER BY id"
        ).fetchall())
        artifacts = list(conn.execute(
            "SELECT * FROM run_artifacts"
        ).fetchall())
    finally:
        conn.close()

    # 3 rows: cycle + self_play + training
    by_kind = {r["kind"]: r for r in runs}
    assert set(by_kind) == {"iterate", "self_play", "training"}, runs
    cycle = by_kind["iterate"]
    self_play = by_kind["self_play"]
    train = by_kind["training"]

    assert cycle["run_id"] == "iter_001_cycle"
    assert cycle["status"] == "completed"
    assert cycle["git_commit"] == "abc1234"
    cycle_config = json.loads(cycle["config_json"])
    assert cycle_config["iter_idx"] == 1
    assert cycle_config["bootstrap_version"] == "v1"
    assert cycle_config["best_version_at_start"] == "v1"
    assert cycle_config["kind"] == "cycle"  # the inner config dict's tag

    # Stage runs reference cycle as parent.
    assert self_play["parent_run_id"] == "iter_001_cycle"
    assert self_play["status"] == "completed"
    assert self_play["run_id"] == "iter_001_self_play_v1"
    assert train["parent_run_id"] == "iter_001_cycle"
    assert train["status"] == "completed"
    assert train["run_id"].startswith("iter_001_train_")

    # Self-play stage emitted a progress row with the n_samples /
    # n_policy_rows extras.
    sp_progress = [
        p for p in progress if p["run_id"] == self_play["run_id"]
    ]
    assert len(sp_progress) == 1
    sp_extra = json.loads(sp_progress[0]["extra_json"])
    assert sp_extra["n_samples"] == 100
    assert sp_extra["n_policy_rows"] == 50

    # Events fired: cycle_started, stage_started (self_play),
    # stage_completed (self_play), stage_started (train),
    # stage_completed (train), promoted.
    event_types = [(e["run_id"], e["event_type"]) for e in events]
    assert ("iter_001_cycle", "cycle_started") in event_types
    assert ("iter_001_cycle", "stage_started") in event_types
    assert ("iter_001_cycle", "stage_completed") in event_types
    assert ("iter_001_cycle", "promoted") in event_types

    # Verify the promoted event payload carries from/to/promoted.
    promoted_events = [
        e for e in events
        if e["run_id"] == "iter_001_cycle"
        and e["event_type"] == "promoted"
    ]
    assert len(promoted_events) == 1
    payload = json.loads(promoted_events[0]["payload_json"])
    assert payload["from_version"] == "v1"
    assert payload["to_version"] == "v2"
    assert payload["promoted"] is True

    # Artifacts: npz on self_play, weights on train, progress_json on
    # cycle/self_play/train. The cycle progress_json is registered up
    # front via register_progress_artifact; the file is touched later
    # by _write_cycle_progress so the size lookup may yield None on the
    # first register pass — re-register at finish would refresh, but
    # the upsert key is (run_id, artifact_type, path) so the row is
    # present regardless.
    by_type = {a["artifact_type"]: [] for a in artifacts}
    for a in artifacts:
        by_type[a["artifact_type"]].append(a)
    assert "npz" in by_type, artifacts
    assert "weights" in by_type, artifacts
    assert "progress_json" in by_type, artifacts
    # npz artifact landed under the self_play stage.
    npz_owners = {a["run_id"] for a in by_type["npz"]}
    assert npz_owners == {self_play["run_id"]}
    # weights artifact under the training stage.
    weights_owners = {a["run_id"] for a in by_type["weights"]}
    assert weights_owners == {train["run_id"]}


# ----------------------------------------------------------------------
# Tests — eval gate enabled
# ----------------------------------------------------------------------


def test_iterate_main_writes_eval_stage_when_gate_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """With --acceptance-threshold 0.5 --eval-games 100, the iterate
    body runs the eval stage. The DB must reflect:
    - An eval row (kind=eval, status=completed, parent=cycle).
    - The eval row's aggregate progress carries wins_new/wins_old/draws.
    - An eval_gate_decision event on the cycle with passed=True/False
      matching the win_rate vs threshold check.
    """
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")

    # 60 wins vs 30 -> win_rate = 60/90 = 0.667; threshold 0.55 -> PASS.
    _setup_mocks_for_iterate(
        monkeypatch,
        eval_returns=(60, 30, 10, 7.89),
    )

    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=100, acceptance_threshold=0.55,
    )

    cli_iterate.main(argv)

    conn = runs_db.connect(db_path)
    try:
        runs = {r["kind"]: r for r in conn.execute(
            "SELECT * FROM runs"
        ).fetchall()}
        events = list(conn.execute(
            "SELECT * FROM run_events ORDER BY id"
        ).fetchall())
        progress = list(conn.execute(
            "SELECT * FROM run_progress"
        ).fetchall())
    finally:
        conn.close()

    assert "eval" in runs, list(runs)
    eval_row = runs["eval"]
    assert eval_row["status"] == "completed"
    assert eval_row["parent_run_id"] == "iter_001_cycle"
    # The eval row's run_id matches the JSON stem convention.
    assert "iter_001_eval_v2_vs_v1" in eval_row["run_id"]

    eval_progress = [
        p for p in progress if p["run_id"] == eval_row["run_id"]
    ]
    assert len(eval_progress) == 1
    p = eval_progress[0]
    assert p["wins_new"] == 60
    assert p["wins_old"] == 30
    assert p["draws"] == 10
    # n_games_total is the SUM of wins+draws+crashed (pushed by
    # push_eval_summary, not the eval_games argv).
    assert p["n_games_total"] == 100  # 60 + 30 + 10 + 0

    # eval_gate_decision event on cycle.
    gate_events = [
        e for e in events
        if e["event_type"] == "eval_gate_decision"
    ]
    assert len(gate_events) == 1
    payload = json.loads(gate_events[0]["payload_json"])
    assert payload["passed"] is True  # 0.667 >= 0.55
    assert payload["new"] == "v2"
    assert payload["old"] == "v1"
    assert payload["wins_new"] == 60
    assert payload["wins_old"] == 30


def test_iterate_main_eval_gate_decision_event_marks_failed_promote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """A lopsided eval that loses (wins_new < wins_old) must fire the
    eval_gate_decision event with passed=False and the promoted event
    must report promoted=False."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")

    # 30 wins vs 60 -> win_rate ~ 0.33; threshold 0.55 -> FAIL.
    _setup_mocks_for_iterate(
        monkeypatch,
        eval_returns=(30, 60, 5, 7.89),
    )

    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=100, acceptance_threshold=0.55,
    )

    cli_iterate.main(argv)

    conn = runs_db.connect(db_path)
    try:
        events = list(conn.execute(
            "SELECT run_id, event_type, payload_json "
            "FROM run_events ORDER BY id"
        ).fetchall())
    finally:
        conn.close()

    gate = [
        e for e in events if e["event_type"] == "eval_gate_decision"
    ]
    assert len(gate) == 1
    gate_payload = json.loads(gate[0]["payload_json"])
    assert gate_payload["passed"] is False

    promoted = [e for e in events if e["event_type"] == "promoted"]
    assert len(promoted) == 1
    promoted_payload = json.loads(promoted[0]["payload_json"])
    assert promoted_payload["promoted"] is False
    assert promoted_payload["from_version"] == "v1"
    assert promoted_payload["to_version"] == "v2"


# ----------------------------------------------------------------------
# Tests — error paths
# ----------------------------------------------------------------------


def test_iterate_main_marks_self_play_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """If self-play raises, the self_play stage row should land as
    ``failed`` and the cycle row should land as ``failed`` (the outer
    except handler maps the propagating exception to failed for the
    in-flight cycle)."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")

    _setup_mocks_for_iterate(
        monkeypatch,
        self_play_raises=RuntimeError("self-play crashed"),
    )

    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=0, acceptance_threshold=0.0,
    )

    with pytest.raises(RuntimeError, match="self-play crashed"):
        cli_iterate.main(argv)

    conn = runs_db.connect(db_path)
    try:
        runs = list(conn.execute(
            "SELECT run_id, kind, status, notes FROM runs"
        ).fetchall())
    finally:
        conn.close()

    by_kind = {r["kind"]: r for r in runs}
    assert by_kind["self_play"]["status"] == "failed"
    assert "self-play crashed" in (
        by_kind["self_play"]["notes"] or ""
    )
    assert by_kind["iterate"]["status"] == "failed"


def test_iterate_main_marks_cycle_killed_on_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """KeyboardInterrupt mid-iteration must mark BOTH the in-flight
    stage and the cycle as ``killed`` (not ``failed``)."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")

    _setup_mocks_for_iterate(
        monkeypatch,
        self_play_raises=KeyboardInterrupt(),
    )

    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=0, acceptance_threshold=0.0,
    )

    with pytest.raises(KeyboardInterrupt):
        cli_iterate.main(argv)

    conn = runs_db.connect(db_path)
    try:
        runs = list(conn.execute(
            "SELECT run_id, kind, status FROM runs"
        ).fetchall())
    finally:
        conn.close()

    by_kind = {r["kind"]: r for r in runs}
    assert by_kind["self_play"]["status"] == "killed"
    assert by_kind["iterate"]["status"] == "killed"


def test_iterate_main_no_op_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """Phase 1 invariant: with neither MTG_BOT_RUN_DB_PATH nor
    MTG_BOT_RUN_DB_URL set, all client.* calls are no-ops. The
    iterate body still completes its JSON-side bookkeeping and
    no DB file is created."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")

    _setup_mocks_for_iterate(monkeypatch)

    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=0, acceptance_threshold=0.0,
    )

    cli_iterate.main(argv)
    # No DB file landed.
    assert not (tmp_path / "runs.db").exists()
    # Phase 3 removed the cycle JSON dual-write — iterate is fully
    # DB-only now. Without ``MTG_BOT_RUN_DB_*`` env vars set, the run
    # is invisible (no JSON, no DB). The cycle did execute, though:
    # the trained weights landed.
    assert (
        tmp_path / "trained_weights" / "v2" / "weights.pt"
    ).exists()


# ----------------------------------------------------------------------
# Tests — unit-level config-dict shape (no main() call required)
# ----------------------------------------------------------------------


def test_cycle_config_dict_shape():
    """The cycle-config dict captures the iter identity + hyper-params
    so an offline reader of the DB can reconstruct the run without the
    JSON sidecar. Schema-level test — pin every required key."""
    import argparse

    args = argparse.Namespace(
        bootstrap_version="v3",
        games_per_iteration=500,
        samples=4,
        nodes=200,
        epochs=50,
        eval_games=2000,
        acceptance_threshold=0.51,
        deck_pool=Path("data/decks.json.gz"),
        seed=0,
        n_iterations=5,
        replays_dir=Path("replays"),
        capture_every_self_play=0.05,
        capture_every_eval=0.0,
    )
    out = cli_iterate._cycle_config_dict(
        args=args, iter_idx_one_based=2, best_version="v3",
    )
    assert out["kind"] == "cycle"
    assert out["iter_idx"] == 2
    assert out["bootstrap_version"] == "v3"
    assert out["best_version_at_start"] == "v3"
    assert out["games_per_iteration"] == 500
    assert out["acceptance_threshold"] == 0.51
    # Path.__str__ yields os-native separators (Windows uses
    # backslashes); compare via Path round-trip rather than literal.
    assert Path(out["deck_pool"]) == Path("data/decks.json.gz")
    # Replay-capture fields must be present so the UI can render the
    # capture state without consulting iterate's argparse defaults.
    assert Path(out["replays_dir"]) == Path("replays")
    assert out["capture_every_self_play"] == 0.05
    assert out["capture_every_eval"] == 0.0


def test_self_play_config_dict_shape():
    """Self-play stage config dict pins the wiring (n_games, nodes,
    samples, seed, distributed flag)."""
    import argparse

    args = argparse.Namespace(
        games_per_iteration=500,
        samples=4,
        nodes=200,
        deck_pool=Path("d.json.gz"),
    )
    out = cli_iterate._self_play_config_dict(
        args=args, best_version="v3", cycle_seed=42, distributed=True,
    )
    assert out["kind"] == "self_play"
    assert out["best_version"] == "v3"
    assert out["n_games"] == 500
    assert out["seed"] == 42
    assert out["distributed"] is True


def test_train_config_dict_shape():
    """Train stage config dict pins the training hyper-params."""
    import argparse

    args = argparse.Namespace(
        epochs=50,
        batch_size=256,
        learning_rate=1e-3,
        val_split=0.1,
        data_dir=Path("iterate_data"),
        window_recent=None,
        window_recent_files=None,
        early_stop_patience=5,
        architecture="shared",
    )
    out = cli_iterate._train_config_dict(
        args=args, peeked_train_version="v4", cycle_seed=42,
    )
    assert out["kind"] == "training"
    assert out["peeked_version"] == "v4"
    assert out["epochs"] == 50
    assert out["seed"] == 42


def test_eval_config_dict_shape():
    """Eval stage config dict pins the gate-eval hyper-params."""
    import argparse

    args = argparse.Namespace(
        eval_games=2000,
        samples=4,
        nodes=200,
        acceptance_threshold=0.51,
        deck_pool=Path("d.json.gz"),
    )
    out = cli_iterate._eval_config_dict(
        args=args, new_version="v4", best_version="v3",
        cycle_seed=42, distributed=False,
    )
    assert out["kind"] == "eval"
    assert out["new"] == "v4"
    assert out["old"] == "v3"
    assert out["games"] == 2000
    assert out["seed"] == 42 + 7777
    assert out["distributed"] is False


def test_iterate_threads_progress_dir_into_the_train_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """iterate's ``--progress-dir`` must reach the trainer — both as
    the iter-namespaced ``progress_path`` AND as ``progress_dir`` (so
    the trainer's OWN default lands in the lineage's dir instead of
    the hardcoded ``training_progress/``).
    """
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")

    _setup_mocks_for_iterate(monkeypatch)
    captured: dict = {}
    inner = cli_iterate._train_next

    def _capture_train_next(*args, **kwargs):
        captured.update(kwargs)
        return inner(*args, **kwargs)

    monkeypatch.setattr(cli_iterate, "_train_next", _capture_train_next)

    progress_dir = tmp_path / "training_progress_s2"
    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=0, acceptance_threshold=0.0,
    )
    argv[argv.index("--progress-dir") + 1] = str(progress_dir)
    cli_iterate.main(argv)

    assert captured["progress_dir"] == progress_dir
    assert captured["progress_path"].parent == progress_dir
