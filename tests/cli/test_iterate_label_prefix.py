"""``mtg_bot iterate --run-label-prefix`` end-to-end wiring.

The prefix has to reach EVERY generated name, not just the cycle id:
runs.db row ids (cycle / self_play / training / eval), the per-stage
progress-JSON filenames, the self-play ``.npz`` basename, and the
replay sub-directories. A single missed site means a second training
lineage still collides with the first one's rows in the shared
coordinator runs.db -- which is the whole reason the flag exists.

The default (``--run-label-prefix`` omitted) must stay byte-identical
to the historical ids; that half is asserted here too so a future
refactor of ``mtg_bot.run_labels`` can't silently rename the original
lineage's rows.

Re-uses the stubbed-downstream harness from
``test_iterate_run_db_wiring`` so the heavy self-play / train / eval
calls stay fakes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg_bot import run_labels
from mtg_bot.cli import iterate as cli_iterate
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs import lifecycle

from tests.cli.test_iterate_run_db_wiring import (
    _baseline_argv,
    _make_version_dir,
    _setup_mocks_for_iterate,
)


def _run_one_iteration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    prefix: str | None,
    eval_games: int = 0,
    acceptance_threshold: float = 0.0,
) -> tuple[Path, list]:
    """Drive ``iterate.main`` for exactly one iteration and return
    ``(tmp_path, runs_rows)``."""
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
        n_iterations=1, eval_games=eval_games,
        acceptance_threshold=acceptance_threshold,
    )
    if prefix is not None:
        argv += ["--run-label-prefix", prefix]

    cli_iterate.main(argv)

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute(
            "SELECT * FROM runs ORDER BY started_at"
        ).fetchall())
    finally:
        conn.close()
    return tmp_path, rows


# ---------------------------------------------------------------------
# runs.db ids
# ---------------------------------------------------------------------


def test_prefix_flows_into_every_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """cycle + self_play + training + eval rows all land under the
    ``s2_`` namespace."""
    _, rows = _run_one_iteration(
        monkeypatch, tmp_path, prefix="s2_",
        eval_games=4, acceptance_threshold=0.5,
    )
    ids = {r["run_id"] for r in rows}
    assert ids == {
        "s2_iter_001_cycle",
        "s2_iter_001_self_play_v1",
        "s2_iter_001_train_v2",
        "s2_iter_001_eval_v2_vs_v1",
    }, ids
    # Parents point at the prefixed cycle, not a bare one.
    parents = {
        r["parent_run_id"] for r in rows if r["parent_run_id"] is not None
    }
    assert parents == {"s2_iter_001_cycle"}
    # The cycle's own display label carries the prefix too.
    cycle = next(r for r in rows if r["run_id"] == "s2_iter_001_cycle")
    assert cycle["label"] == "s2_iter_001"
    assert json.loads(cycle["config_json"])["label_prefix"] == "s2_"


def test_default_run_ids_are_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No flag → the historical un-prefixed ids, byte-for-byte."""
    _, rows = _run_one_iteration(
        monkeypatch, tmp_path, prefix=None,
        eval_games=4, acceptance_threshold=0.5,
    )
    ids = {r["run_id"] for r in rows}
    assert ids == {
        "iter_001_cycle",
        "iter_001_self_play_v1",
        "iter_001_train_v2",
        "iter_001_eval_v2_vs_v1",
    }, ids
    cycle = next(r for r in rows if r["run_id"] == "iter_001_cycle")
    assert json.loads(cycle["config_json"])["label_prefix"] == ""


def test_explicit_empty_prefix_matches_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """``--run-label-prefix ""`` is the documented no-op form."""
    _, rows = _run_one_iteration(monkeypatch, tmp_path, prefix="")
    assert "iter_001_cycle" in {r["run_id"] for r in rows}


def test_unnormalized_prefix_is_normalized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """``s2`` (no trailing underscore) must not produce
    ``s2iter_001_cycle``."""
    _, rows = _run_one_iteration(monkeypatch, tmp_path, prefix="s2")
    assert "s2_iter_001_cycle" in {r["run_id"] for r in rows}


def test_invalid_prefix_exits_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A prefix that would break a glob / LIKE pattern must fail at
    argparse time -- before any runs.db row exists."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")
    _setup_mocks_for_iterate(monkeypatch)
    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
    ) + ["--run-label-prefix", "bad/prefix"]

    with pytest.raises(SystemExit) as exc:
        cli_iterate.main(argv)
    assert exc.value.code == 2
    assert not db_path.exists()


# ---------------------------------------------------------------------
# On-disk names: progress JSON, npz, replay dirs
# ---------------------------------------------------------------------


def test_prefix_flows_into_progress_json_and_npz_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stage progress cards and the self-play npz are named off
    the same ids, so they must carry the prefix too -- otherwise the
    two lineages overwrite each other's files in a shared
    ``--progress-dir`` / ``--data-dir``."""
    _run_one_iteration(
        monkeypatch, tmp_path, prefix="s2_",
        eval_games=4, acceptance_threshold=0.5,
    )
    progress_names = {
        p.name for p in (tmp_path / "training_progress").glob("*.json")
    }
    assert "s2_iter_001_self_play_v1.json" in progress_names
    assert "s2_iter_001_train_v2.json" in progress_names
    assert "s2_iter_001_eval_v2_vs_v1.json" in progress_names
    assert not [n for n in progress_names if n.startswith("iter_")]

    npzs = [p.name for p in (tmp_path / "iterate_data").glob("*.npz")]
    assert npzs and all(n.startswith("s2_iter_001_v1_") for n in npzs), npzs


def test_prefix_flows_into_replay_dir_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Replay sub-directories are named after the stage run_id."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc1234")
    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1")
    deck_pool = tmp_path / "deck_pool.json.gz"
    deck_pool.write_bytes(b"")
    _setup_mocks_for_iterate(monkeypatch)

    argv = _baseline_argv(
        tmp_path=tmp_path, deck_pool=deck_pool, bootstrap="v1",
        n_iterations=1, eval_games=4, acceptance_threshold=0.5,
    )
    # Flip replay capture on for both stages.
    for flag, value in (
        ("--capture-every-self-play", "1"), ("--capture-every-eval", "1"),
    ):
        argv[argv.index(flag) + 1] = value
    argv += ["--run-label-prefix", "s2_"]

    cli_iterate.main(argv)

    replay_dirs = {p.name for p in (tmp_path / "replays").iterdir()}
    assert replay_dirs == {
        "s2_iter_001_self_play_v1", "s2_iter_001_eval_v2_vs_v1",
    }, replay_dirs


# ---------------------------------------------------------------------
# Resume / reconcile path
# ---------------------------------------------------------------------


def test_find_eval_progress_is_prefix_scoped(tmp_path: Path) -> None:
    """``--reconcile-state`` locates the orphan iter's eval card by
    globbing the progress dir. With two lineages present it must pick
    ITS OWN card, not the other lineage's identically-numbered one."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    (progress / "iter_003_eval_v4_vs_v3.json").write_text("{}", "utf-8")
    (progress / "s2_iter_003_eval_v4_vs_v3.json").write_text("{}", "utf-8")

    default_hit = cli_iterate._find_eval_progress(progress, 3, "v4")
    s2_hit = cli_iterate._find_eval_progress(progress, 3, "v4", "s2_")

    assert default_hit is not None
    assert default_hit.name == "iter_003_eval_v4_vs_v3.json"
    assert s2_hit is not None
    assert s2_hit.name == "s2_iter_003_eval_v4_vs_v3.json"


def test_reconcile_state_uses_the_lineages_own_eval_card(
    tmp_path: Path,
) -> None:
    """End-to-end on the reconcile helper: the s2 lineage's orphan
    promotes off the s2 eval card's win-rate, ignoring the
    un-prefixed lineage's card for the same iter+version."""
    registry = tmp_path / "trained_weights_s2"
    for v in ("v1", "v2"):
        (registry / v).mkdir(parents=True)
    progress = tmp_path / "training_progress"
    progress.mkdir()
    # Other lineage: a FAILING eval for the same iter/version.
    (progress / "iter_001_eval_v2_vs_v1.json").write_text(
        json.dumps({"wins_new": 1, "wins_old": 9, "draws": 0,
                    "win_rate": 0.1, "elapsed_seconds": 1.0}),
        encoding="utf-8",
    )
    # Our lineage: a PASSING eval.
    (progress / "s2_iter_001_eval_v2_vs_v1.json").write_text(
        json.dumps({"wins_new": 9, "wins_old": 1, "draws": 0,
                    "win_rate": 0.9, "elapsed_seconds": 1.0}),
        encoding="utf-8",
    )

    state = {"current_best": "v1", "iterations_completed": 0, "history": []}
    out = cli_iterate._reconcile_iterate_state(
        state, registry, progress, "v1", 0.525, "s2_",
    )
    assert out["current_best"] == "v2"
    assert out["history"][-1]["promoted"] is True


def test_reconcile_error_message_names_the_prefixed_glob(
    tmp_path: Path,
) -> None:
    """The "can't find the eval card" error must tell the operator
    the pattern it actually looked for, prefix included."""
    registry = tmp_path / "trained_weights_s2"
    for v in ("v1", "v2"):
        (registry / v).mkdir(parents=True)
    progress = tmp_path / "training_progress"
    progress.mkdir()
    state = {"current_best": "v1", "iterations_completed": 0, "history": []}

    with pytest.raises(cli_iterate.ReconcileError) as exc:
        cli_iterate._reconcile_iterate_state(
            state, registry, progress, "v1", 0.525, "s2_",
        )
    assert "s2_iter_001_eval_v2_vs_*.json" in str(exc.value)


# ---------------------------------------------------------------------
# Foreign-npz guard
# ---------------------------------------------------------------------


def test_foreign_npz_guard_is_lineage_scoped(tmp_path: Path) -> None:
    """With a prefix, the OTHER lineage's npzs count as foreign --
    mixing two lineages' self-play data in one --data-dir is exactly
    the silent-corruption case this guard exists to catch."""
    from mtg_bot.training._iterate_helpers import find_foreign_npzs

    data_dir = tmp_path / "iterate_data"
    data_dir.mkdir()
    (data_dir / "iter_001_v1_x.npz").write_bytes(b"")
    (data_dir / "s2_iter_001_v1_x.npz").write_bytes(b"")
    (data_dir / "gen0_smoke.npz").write_bytes(b"")

    assert find_foreign_npzs(data_dir) == [
        "gen0_smoke.npz", "s2_iter_001_v1_x.npz",
    ]
    assert find_foreign_npzs(data_dir, "s2_") == [
        "gen0_smoke.npz", "iter_001_v1_x.npz",
    ]


# ---------------------------------------------------------------------
# Coherence with the unified launcher
# ---------------------------------------------------------------------


@pytest.mark.parametrize("prefix", ["", "s2_"])
def test_cycle_id_matches_run_labels_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prefix: str,
) -> None:
    """The id iterate actually writes must equal
    ``run_labels.cycle_id(iter_idx, prefix)`` -- the same helper the
    launcher pre-registers its row from. See
    ``tests/test_launcher_label_prefix.py`` for the launcher half."""
    _, rows = _run_one_iteration(monkeypatch, tmp_path, prefix=prefix)
    ids = {r["run_id"] for r in rows}
    assert run_labels.cycle_id(1, prefix) in ids
