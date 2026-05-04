"""Tests for ``mtg_bot.training.distributed`` schema + loader.

The orchestrator's runtime behavior (SSH dispatch, scp result
collection) lives behind a network and is tested manually with the
real remotes. These tests pin the static config layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg_bot.training.distributed import (
    ShardConfig,
    ShardsConfig,
    load_shards_config,
)


# ---- ShardConfig --------------------------------------------------


def test_local_shard_minimal_fields_are_enough():
    shard = ShardConfig(host="local", n_games=100)
    assert shard.is_local
    assert shard.display_label == "local"
    assert shard.seed_offset == 0


def test_label_falls_back_to_host_for_remote():
    """No explicit label → display_label uses the host. Two
    ``host="local"`` shards in one config would collide on this —
    that's caught by ShardsConfig dup-label validation, not here."""
    shard = ShardConfig(
        host="my-mac", n_games=50,
        user="gregg", repo_path="/r",
        venv_python=".venv/bin/python",
    )
    assert shard.display_label == "my-mac"


def test_remote_shard_requires_user_repo_python():
    """Remote shard with missing fields fails at construction time
    (don't wait until self-play has been running for 10 minutes)."""
    with pytest.raises(ValueError, match="missing fields"):
        ShardConfig(host="remote", n_games=100)
    with pytest.raises(ValueError, match="missing fields"):
        ShardConfig(host="remote", n_games=100, user="gregg")
    # Complete remote shard — no exception.
    ShardConfig(
        host="remote", n_games=100,
        user="gregg",
        repo_path="/repo",
        venv_python=".venv/bin/python",
    )


def test_remote_shard_local_fields_are_optional_for_local():
    """Local shards never read user/repo_path/venv_python; missing
    those isn't an error for ``host="local"``."""
    ShardConfig(host="local", n_games=100)


def test_n_games_must_be_positive():
    with pytest.raises(ValueError, match="n_games must be positive"):
        ShardConfig(host="local", n_games=0)
    with pytest.raises(ValueError, match="n_games must be positive"):
        ShardConfig(host="local", n_games=-5)


def test_seed_offset_must_be_non_negative():
    with pytest.raises(ValueError, match="seed_offset"):
        ShardConfig(host="local", n_games=10, seed_offset=-1)


def test_empty_host_rejected():
    with pytest.raises(ValueError, match="host is required"):
        ShardConfig(host="", n_games=10)


# ---- ShardsConfig -------------------------------------------------


def test_shards_config_total_games_sums():
    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_games=200),
        ShardConfig(
            host="m1", n_games=150, user="u",
            repo_path="/r", venv_python=".venv/bin/python",
        ),
    ))
    assert cfg.total_games == 350


def test_shards_config_rejects_empty_list():
    with pytest.raises(ValueError, match="empty"):
        ShardsConfig(shards=())


def test_shards_config_rejects_duplicate_labels():
    """Two shards with the same display_label would collide on npz
    output filenames. Reject up-front."""
    with pytest.raises(ValueError, match="duplicate shard labels"):
        ShardsConfig(shards=(
            ShardConfig(host="local", n_games=100, label="A"),
            ShardConfig(host="local", n_games=100, label="A"),
        ))


def test_shards_config_allows_two_local_with_distinct_labels():
    """Edge case but legal: two local shards with explicit distinct
    labels (the user might want to split a single host's load by
    seed range, though that's silly today; future-proofing)."""
    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_games=100, label="L1"),
        ShardConfig(host="local", n_games=100, label="L2", seed_offset=1_000_000),
    ))
    assert cfg.total_games == 200


# ---- load_shards_config -------------------------------------------


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_assigns_default_seed_offsets_by_position(tmp_path: Path):
    """Idiomatic pattern: seed_offset defaults to position * 1M so
    shards never collide for any sane n_games. Caller can still
    override explicitly."""
    p = tmp_path / "shards.json"
    _write(p, {
        "shards": [
            {"host": "local", "n_games": 100},
            {
                "host": "m1", "n_games": 100,
                "user": "u", "repo_path": "/r",
                "venv_python": ".venv/bin/python",
            },
            {"host": "local", "n_games": 100, "label": "L3"},
        ],
    })
    cfg = load_shards_config(p)
    assert cfg.shards[0].seed_offset == 0
    assert cfg.shards[1].seed_offset == 1_000_000
    assert cfg.shards[2].seed_offset == 2_000_000


def test_load_explicit_seed_offset_overrides_default(tmp_path: Path):
    p = tmp_path / "shards.json"
    _write(p, {
        "shards": [
            {"host": "local", "n_games": 100, "seed_offset": 42},
        ],
    })
    cfg = load_shards_config(p)
    assert cfg.shards[0].seed_offset == 42


def test_load_three_machine_example(tmp_path: Path):
    """The canonical setup from the design doc: master local + Win
    1080Ti box + Apple Silicon Mac, sharing a 500-game iter as
    200/150/150."""
    p = tmp_path / "shards.json"
    _write(p, {
        "shards": [
            {"host": "local", "n_games": 200},
            {
                "host": "win-1080ti", "n_games": 150,
                "user": "gregg",
                "repo_path": "C:\\Users\\gregg\\Projects\\mtg-bot",
                "venv_python": ".venv-py313\\Scripts\\python.exe",
            },
            {
                "host": "macbook", "n_games": 150,
                "user": "gregg",
                "repo_path": "/Users/gregg/projects/mtg-bot",
                "venv_python": ".venv-py313/bin/python",
            },
        ],
    })
    cfg = load_shards_config(p)
    assert cfg.total_games == 500
    assert [s.host for s in cfg.shards] == ["local", "win-1080ti", "macbook"]
    assert cfg.shards[0].is_local
    assert not cfg.shards[1].is_local
    assert not cfg.shards[2].is_local


def test_load_missing_top_level_key_rejected(tmp_path: Path):
    p = tmp_path / "shards.json"
    p.write_text(json.dumps({"not_shards": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing top-level 'shards'"):
        load_shards_config(p)


def test_load_shards_must_be_list(tmp_path: Path):
    p = tmp_path / "shards.json"
    p.write_text(json.dumps({"shards": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        load_shards_config(p)


def test_load_shard_must_be_object(tmp_path: Path):
    p = tmp_path / "shards.json"
    p.write_text(
        json.dumps({"shards": ["not-an-object"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be an object"):
        load_shards_config(p)


# ---- run_shard_local + run_distributed_self_play ----------------


def _tiny_dual_head_weights(tmp_path: Path) -> tuple[Path, tuple[int, int]]:
    """Save a tiny dual-head net to disk; return (path, hidden_sizes).
    Caller passes both into a SelfPlayJobSpec so NNEvaluator loads
    cleanly."""
    import torch
    from mtg_bot.search.nn_evaluator import _ValuePolicyMLP
    hidden_sizes = (16, 16)
    weights_path = tmp_path / "tiny_dual_head.pt"
    torch.save(
        _ValuePolicyMLP(hidden_sizes=hidden_sizes).state_dict(),
        weights_path,
    )
    return weights_path, hidden_sizes


def test_run_shard_local_writes_npz_with_per_shard_filename(
    tmp_path: Path,
):
    """End-to-end smoke for the local-shard runner: builds the
    NNPimcConfig + DataGenProgress, runs ``generate_training_data_
    parallel`` with the shard's slice, saves the npz at the per-
    shard path. Tiny model + 2 games + samples=1 + nodes=10 keeps
    wall under ~10s while still exercising the full pipeline."""
    from mtg_bot.training.distributed import (
        SelfPlayJobSpec,
        run_shard_local,
    )

    weights_path, hidden_sizes = _tiny_dual_head_weights(tmp_path)
    out_dir = tmp_path / "iterate_data"
    progress_dir = tmp_path / "training_progress"
    spec = SelfPlayJobSpec(
        weights_path=str(weights_path),
        samples=1, inner_nodes=10,
        hidden_sizes=hidden_sizes,
        base_seed=0,
        enable_mulligans=False,
        per_game_timeout_sec=None,
        with_policy=True,
    )
    shard = ShardConfig(host="local", n_games=2, label="L0")
    npz_path = run_shard_local(
        shard, spec,
        progress_dir=progress_dir,
        output_dir=out_dir,
        run_id_prefix="iter_001_self_play_v1",
        stamp="20260503T230000Z",
    )
    assert npz_path.is_file()
    assert "shard_L0" in npz_path.name
    assert npz_path.suffix == ".npz"
    # Progress JSON exists and is finalized.
    progress_files = list(progress_dir.glob("*.json"))
    assert len(progress_files) == 1
    progress = json.loads(progress_files[0].read_text(encoding="utf-8"))
    assert progress["status"] == "completed"
    assert progress["n_games_total"] == 2
    assert progress["n_games_done"] == 2


def test_run_distributed_two_local_shards_both_produce_npz(
    tmp_path: Path,
):
    """Smoke for the orchestrator with two local shards. Today the
    orchestrator runs local shards inline (no concurrent local
    shards — they'd contend on the master's CPU). The test pins:
    both shards produce npzs in the configured output dir, in
    shards-config order."""
    from mtg_bot.training.distributed import (
        SelfPlayJobSpec,
        run_distributed_self_play,
    )

    weights_path, hidden_sizes = _tiny_dual_head_weights(tmp_path)
    out_dir = tmp_path / "iterate_data"
    progress_dir = tmp_path / "training_progress"
    spec = SelfPlayJobSpec(
        weights_path=str(weights_path),
        samples=1, inner_nodes=10,
        hidden_sizes=hidden_sizes,
        base_seed=0,
        enable_mulligans=False,
        per_game_timeout_sec=None,
        with_policy=True,
    )
    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_games=2, label="A"),
        ShardConfig(host="local", n_games=2, label="B",
                    seed_offset=1_000_000),
    ))
    paths = run_distributed_self_play(
        cfg, spec,
        progress_dir=progress_dir,
        output_dir=out_dir,
        run_id_prefix="iter_001_self_play_v1",
    )
    assert len(paths) == 2
    # Each shard's npz lives in the configured output_dir, names
    # carry the shard label.
    assert all(p.parent == out_dir.resolve() or p.parent == out_dir
               for p in paths)
    assert "shard_A" in paths[0].name
    assert "shard_B" in paths[1].name
    assert all(p.is_file() for p in paths)


def test_spec_round_trips_through_to_dict_from_dict():
    """SelfPlayJobSpec.to_dict + from_dict is a no-op. Round-trip
    is what enables the remote-shard wrapper to receive the spec via
    base64-encoded JSON over SSH."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    original = SelfPlayJobSpec(
        weights_path="trained_weights/v6/weights.pt",
        samples=4, inner_nodes=200,
        hidden_sizes=(1024, 1024, 512),
        base_seed=2_000_000,
        enable_mulligans=True,
        per_game_timeout_sec=450.0,
        deck_pool_path="data/17lands/eoe_decks.json.gz",
        with_policy=True,
        decision_cap=4000,
        sample_every=1,
        capture_every=25,
        nn_version_label="v6",
        replays_root="replays",
        hang_dump_root="debug_hangs",
    )
    rt = SelfPlayJobSpec.from_dict(original.to_dict())
    assert rt == original


def test_shard_config_round_trips_through_to_dict_from_dict():
    s = ShardConfig(
        host="win-1080ti", n_games=150, label="win",
        seed_offset=1_000_000, n_workers=8,
        user="gregg",
        repo_path="C:\\Users\\gregg\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
        ssh_port=22,
    )
    rt = ShardConfig.from_dict(s.to_dict())
    assert rt == s


def test_remote_command_uses_wrapper_script_with_b64_args():
    """The remote one-liner invokes ``run_self_play_shard.py`` with
    base64-encoded spec + shard JSON. Both encodings must round-trip
    cleanly so the remote can rebuild the dataclasses."""
    import base64

    from mtg_bot.training.distributed import (
        SelfPlayJobSpec,
        _build_remote_self_play_command,
    )

    spec = SelfPlayJobSpec(
        weights_path="trained_weights/v6/weights.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=300.0,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    cmd = _build_remote_self_play_command(
        shard, spec,
        run_id_prefix="iter_001_self_play_v6",
        stamp="20260503T230000Z",
    )
    # POSIX cd + venv invocation.
    assert "cd /Users/g/repo" in cmd
    assert ".venv-py313/bin/python" in cmd
    assert "scripts/run_self_play_shard.py" in cmd
    # Both encoded args present and decode back to the originals.
    for name, expected in (("--spec-b64=", spec), ("--shard-b64=", shard)):
        marker = name
        i = cmd.index(marker) + len(marker)
        # The encoded value runs until the next space.
        end = cmd.index(" ", i)
        encoded = cmd[i:end]
        decoded = json.loads(
            base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        )
        if name.startswith("--spec"):
            assert (
                SelfPlayJobSpec.from_dict(decoded) == expected
            )
        else:
            assert ShardConfig.from_dict(decoded) == expected


def test_remote_command_windows_uses_cmd_syntax():
    """A Windows shard (``.exe`` venv python) must use cmd.exe-style
    ``cd /d "path" && set PYTHONPATH=src && "..\\python.exe" ...``
    instead of POSIX bash form."""
    from mtg_bot.training.distributed import (
        SelfPlayJobSpec,
        _build_remote_self_play_command,
    )

    spec = SelfPlayJobSpec(
        weights_path="trained_weights/v6/weights.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=300.0,
    )
    shard = ShardConfig(
        host="win-box", n_games=10, user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )
    cmd = _build_remote_self_play_command(
        shard, spec,
        run_id_prefix="iter_001", stamp="20260503T000000Z",
    )
    assert 'cd /d "C:\\Users\\g\\Projects\\mtg-bot"' in cmd
    assert "set PYTHONPATH=src" in cmd
    assert '".venv-py313\\Scripts\\python.exe"' in cmd


def test_run_self_play_shard_script_exists_and_imports():
    """Smoke that the script file exists at scripts/run_self_play_
    shard.py and is at least importable / has --help. The deeper
    integration (run a fake shard end-to-end) is covered by
    test_run_shard_local — we don't need a duplicate via
    subprocess."""
    import os
    import subprocess
    import sys as _sys

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_self_play_shard.py"
    assert script.is_file()
    # Use the same interpreter running the test — works regardless
    # of where the worktree lives relative to the venv.
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    res = subprocess.run(
        [_sys.executable, str(script), "--help"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    assert "--spec-b64" in res.stdout
    assert "--shard-b64" in res.stdout
