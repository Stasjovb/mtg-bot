"""``[iter] label_prefix`` in the unified launcher.

Three things are pinned here:

1. The TOML key + ``--iter.label-prefix`` CLI override parse,
   normalise and validate.
2. ``_build_iterate_argv`` forwards the prefix to ``mtg_bot iterate
   --run-label-prefix`` (and omits the flag entirely at the default
   so the original lineage's argv stays byte-identical).
3. **Coherence.** The ``cycle_id`` the launcher pre-registers in
   runs.db equals the ``cycle_id`` iterate independently generates
   for the same iteration. Historically these were two hand-written
   f-strings in two modules; they now both call
   :mod:`mtg_bot.run_labels`, and this test is the guard that they
   stay equal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot import run_labels
from mtg_bot.cli import iterate_distributed
from mtg_bot.launcher.config import (
    LaunchConfig,
    LaunchConfigError,
    load_config,
    parse_cli_overrides,
)


def _write_toml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "launch.toml"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Config parse / normalise / validate
# ---------------------------------------------------------------------------


def test_label_prefix_defaults_to_empty() -> None:
    cfg = LaunchConfig()
    assert cfg.iter.label_prefix == ""


def test_label_prefix_from_toml(tmp_path: Path) -> None:
    p = _write_toml(tmp_path, """
[iter]
target_iter = 1
label_prefix = "s2_"

[cluster]
local_only = true
""")
    cfg = load_config(p)
    assert cfg.iter.label_prefix == "s2_"
    assert cfg.iter_label == "s2_iter_001"
    assert cfg.cycle_id == "s2_iter_001_cycle"


def test_label_prefix_cli_override_wins(tmp_path: Path) -> None:
    p = _write_toml(tmp_path, """
[iter]
target_iter = 4
label_prefix = "s2_"

[cluster]
local_only = true
""")
    overrides = parse_cli_overrides(["--iter.label-prefix", "s3_"])
    cfg = load_config(p, overrides=overrides)
    assert cfg.iter.label_prefix == "s3_"
    assert cfg.cycle_id == "s3_iter_004_cycle"


def test_label_prefix_is_normalized_at_load(tmp_path: Path) -> None:
    """``s2`` and ``s2_`` must resolve to the same cycle id -- an
    un-normalised value would produce ``s2iter_004_cycle``."""
    p = _write_toml(tmp_path, """
[iter]
target_iter = 4

[cluster]
local_only = true
""")
    cfg = load_config(
        p, overrides=parse_cli_overrides(["--iter.label-prefix", "s2"]),
    )
    assert cfg.iter.label_prefix == "s2_"
    assert cfg.cycle_id == "s2_iter_004_cycle"


def test_invalid_label_prefix_raises_launch_config_error(
    tmp_path: Path,
) -> None:
    """A prefix with a path separator / wildcard would break the
    per-cycle dir names and the UI's LIKE sweep -- reject at load,
    before the launcher takes any side effect."""
    p = _write_toml(tmp_path, """
[iter]
target_iter = 4
label_prefix = "bad/prefix"

[cluster]
local_only = true
""")
    with pytest.raises(LaunchConfigError, match="label_prefix"):
        load_config(p)


def test_default_cycle_id_is_unchanged(tmp_path: Path) -> None:
    """No prefix → the historical ``iter_NNN_cycle`` the live
    runs.db already holds 21 of."""
    p = _write_toml(tmp_path, """
[iter]
target_iter = 21

[cluster]
local_only = true
""")
    cfg = load_config(p)
    assert cfg.iter_label == "iter_021"
    assert cfg.cycle_id == "iter_021_cycle"


# ---------------------------------------------------------------------------
# argv forwarding
# ---------------------------------------------------------------------------


def _argv_for(cfg: LaunchConfig) -> list[str]:
    return iterate_distributed._build_iterate_argv(
        cfg,
        shards_config_path=Path("shards.json"),
        queue_url="http://coord:5099",
        deck_pool=None,
        registry_root=None,
        extra_iterate_args=[],
    )


def test_argv_includes_run_label_prefix_flag(tmp_path: Path) -> None:
    cfg = load_config(_write_toml(tmp_path, """
[iter]
target_iter = 1
label_prefix = "s2_"

[cluster]
local_only = true
"""))
    argv = _argv_for(cfg)
    assert "--run-label-prefix" in argv
    assert argv[argv.index("--run-label-prefix") + 1] == "s2_"


def test_argv_omits_flag_at_default(tmp_path: Path) -> None:
    """The original lineage's spawned command line must not change."""
    cfg = load_config(_write_toml(tmp_path, """
[iter]
target_iter = 21

[cluster]
local_only = true
"""))
    assert "--run-label-prefix" not in _argv_for(cfg)


# ---------------------------------------------------------------------------
# Coherence: launcher's cycle_id == iterate's cycle_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", ["", "s2_", "lineage-b_"])
@pytest.mark.parametrize("target_iter", [1, 7, 21, 100])
def test_launcher_cycle_id_equals_iterate_cycle_id(
    tmp_path: Path, prefix: str, target_iter: int,
) -> None:
    """The launcher derives the cycle row id from
    ``[iter].target_iter``; iterate derives it from
    ``iterate_state.json``'s ``iterations_completed + 1``. When those
    two numbers name the same iteration the ids MUST match, or the
    launcher registers one row while iterate writes a different one
    and the UI card sticks at ``running`` forever.
    """
    body = f"""
[iter]
target_iter = {target_iter}
label_prefix = "{prefix}"

[cluster]
local_only = true
"""
    cfg = load_config(_write_toml(tmp_path, body))
    # iterate's side of the computation, for iterations_completed =
    # target_iter - 1.
    n_done = target_iter - 1
    iterate_side = run_labels.cycle_id(n_done + 1, cfg.iter.label_prefix)
    assert cfg.cycle_id == iterate_side


def test_launcher_forwards_a_prefix_that_reproduces_its_own_cycle_id(
    tmp_path: Path,
) -> None:
    """Closing the loop: take the prefix the launcher puts on the
    argv, feed it back through the label helpers at the launcher's
    own target_iter, and confirm the cycle id comes out identical."""
    cfg = load_config(_write_toml(tmp_path, """
[iter]
target_iter = 3
label_prefix = "s2"

[cluster]
local_only = true
"""))
    argv = _argv_for(cfg)
    forwarded = argv[argv.index("--run-label-prefix") + 1]
    assert run_labels.cycle_id(3, forwarded) == cfg.cycle_id


def test_dry_run_reports_the_prefixed_cycle_id(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """End-to-end through the launcher CLI: the cycle_id it announces
    (and would register) plus the argv it would spawn both carry the
    lineage prefix."""
    from mtg_bot.cli.runs import db as runs_db

    progress_dir = tmp_path / "tp"
    progress_dir.mkdir()
    runs_db.connect(progress_dir / "runs.db").close()
    monkeypatch.setenv(
        "MTG_BOT_RUN_DB_PATH", str(progress_dir / "runs.db"),
    )
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(
        iterate_distributed, "verify_worker_idle", lambda url: None,
    )
    toml_path = _write_toml(tmp_path, """
[iter]
target_iter = 1
label_prefix = "s2_"
bootstrap_version = "v5"

[cluster]
local_only = true
master_url = "http://desktop-j05412i:5198"
""")
    rc = iterate_distributed.main([
        "--config", str(toml_path),
        "--progress-dir", str(progress_dir),
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cycle_id=s2_iter_001_cycle" in out
    assert "--run-label-prefix s2_" in out
