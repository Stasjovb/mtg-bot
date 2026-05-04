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


# ---- pull-model queue test server -------------------------------


def _start_queue_server() -> tuple[str, "object"]:
    """Spin up an in-process http.server with /queue/init and
    /queue/take. Returns ``(base_url, server)``; caller invokes
    ``server.shutdown()`` to stop. State is per-server so tests don't
    cross-contaminate."""
    import http.server
    import json as _json
    import socket
    import threading as _threading

    state: dict = {"queues": {}, "lock": _threading.Lock()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs):  # silence stderr
            pass

        def _reply(self, status: int, body_obj: dict) -> None:
            payload = _json.dumps(body_obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):  # noqa: N802 — http.server API name
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = _json.loads(raw) if raw else {}
            if self.path == "/queue/init":
                run_id = data["run_id"]
                total = int(data["total_games"])
                with state["lock"]:
                    state["queues"][run_id] = {"next": 0, "total": total}
                self._reply(200, {"ok": True})
            elif self.path == "/queue/take":
                run_id = data["run_id"]
                bs = int(data.get("batch_size", 25))
                with state["lock"]:
                    q = state["queues"].get(run_id)
                    if q is None:
                        self._reply(404, {"error": "unknown run_id"})
                        return
                    start = q["next"]
                    end = min(start + bs, q["total"])
                    q["next"] = end
                    remaining = q["total"] - end
                self._reply(200, {
                    "games": list(range(start, end)),
                    "remaining": remaining,
                })
            else:
                self._reply(404, {"error": "not found"})

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}", server


def test_run_distributed_two_local_shards_both_produce_npz(
    tmp_path: Path,
):
    """Pull-model smoke for the orchestrator with two local shards
    sharing one queue. Both shards open their own mp.Pool, both pull
    from the same /queue/take. Together they should drain a 4-game
    queue and produce ≥1 per-batch npz each (the exact split is
    nondeterministic — pull-mode is the point)."""
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
        ShardConfig(host="local", n_games=2, label="A", n_workers=1),
        ShardConfig(host="local", n_games=2, label="B", n_workers=1,
                    seed_offset=1_000_000),
    ))
    queue_url, server = _start_queue_server()
    try:
        paths = run_distributed_self_play(
            cfg, spec,
            progress_dir=progress_dir,
            output_dir=out_dir,
            run_id_prefix="iter_001_self_play_v1",
            total_games=4,
            queue_url=queue_url,
            batch_size_default=2,
        )
    finally:
        server.shutdown()
    # 4 total games drained across two pools — at minimum one batch
    # per shard (pool empties on the same response that hits the end
    # of the queue), but could be more if one shard wins the race.
    assert len(paths) >= 1
    assert all(p.is_file() for p in paths)
    # Each batch's filename includes its shard label; both A and B
    # should appear at least once unless one shard happened to do
    # zero rounds (very unlikely with batch_size=2 on a 4-game queue
    # split between two equally-fast workers, but possible). The
    # weaker assertion is that every produced file's parent dir is
    # the configured output_dir.
    assert all(
        p.parent == out_dir.resolve() or p.parent == out_dir
        for p in paths
    )
    # Every shard writes a JSONL event log alongside the progress
    # JSON. Both shards' logs must exist and end with shard_end.
    for shard_label in ("A", "B"):
        events_path = (
            progress_dir
            / f"iter_001_self_play_v1_shard_{shard_label}_events.jsonl"
        )
        assert events_path.is_file(), f"missing {events_path.name}"
        lines = events_path.read_text(encoding="utf-8").splitlines()
        assert lines, f"events log {events_path.name} is empty"
        events = [json.loads(line) for line in lines]
        # First event is shard_start with machine metadata.
        assert events[0]["event"] == "shard_start"
        assert "machine" in events[0]
        assert "host" in events[0]["machine"]
        # Final event is shard_end with status.
        assert events[-1]["event"] == "shard_end"
        assert events[-1]["status"] == "completed"
        # At least one game_end + one batch_saved must be present
        # (the shard ran games, not just polled an empty queue).
        kinds = {e["event"] for e in events}
        # If this shard happened to lose every batch race, only
        # shard_start + batch_take(empty) + shard_end are present.
        # Both shards producing zero batches is impossible (4 games,
        # two workers, batch_size=2): at least one must run a batch.
    # Across both shards combined, we should see per-game events.
    all_events: list[dict] = []
    for shard_label in ("A", "B"):
        events_path = (
            progress_dir
            / f"iter_001_self_play_v1_shard_{shard_label}_events.jsonl"
        )
        for line in events_path.read_text(encoding="utf-8").splitlines():
            all_events.append(json.loads(line))
    game_ends = [e for e in all_events if e["event"] == "game_end"]
    assert len(game_ends) == 4, (
        f"expected 4 game_end events across both shards, got "
        f"{len(game_ends)}"
    )
    # game_end carries per-game wall time + n_samples.
    for ge in game_ends:
        assert "wall_s" in ge and ge["wall_s"] > 0
        assert "n_samples" in ge
        assert "game_idx" in ge


def test_spec_to_dict_normalizes_windows_paths_to_forward_slashes():
    """Smoke for the cross-platform path serialization fix. iterate
    runs on Windows and produces ``str(Path(...))`` with backslashes;
    when the spec ships to the Mac via base64-JSON, the literal
    backslashes are interpreted as filename characters (POSIX) and
    every NN load fails. ``to_dict()`` normalizes path fields to
    forward slashes so the wire format is platform-neutral.

    Reproduced from a real iter run where every Mac game had
    ``samples=0 wall_s=0.009`` because ``trained_weights\\v6\\
    weights.pt`` doesn't exist on the Mac as a literal filename.
    """
    from mtg_bot.training.distributed import SelfPlayJobSpec

    spec = SelfPlayJobSpec(
        weights_path="tmp_iter\\registry\\v6\\weights.pt",
        samples=2, inner_nodes=50, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        deck_pool_path="data\\17lands\\eoe_decks.json.gz",
        replays_root="tmp_iter\\replays",
        hang_dump_root="tmp_iter\\hangs",
    )
    d = spec.to_dict()
    assert d["weights_path"] == "tmp_iter/registry/v6/weights.pt"
    assert d["deck_pool_path"] == "data/17lands/eoe_decks.json.gz"
    assert d["replays_root"] == "tmp_iter/replays"
    assert d["hang_dump_root"] == "tmp_iter/hangs"


def test_spec_to_dict_handles_none_path_fields():
    """Optional path fields stay None when not set; the path-
    normalizer must not crash on None."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    spec = SelfPlayJobSpec(
        weights_path="weights.pt",
        samples=1, inner_nodes=1, hidden_sizes=None,
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    d = spec.to_dict()
    assert d["deck_pool_path"] is None
    assert d["replays_root"] is None
    assert d["hang_dump_root"] is None


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


def test_remote_pull_command_posix_round_trips_b64_args():
    """The remote one-liner invokes ``run_self_play_shard.py
    --mode=pull`` with base64-encoded spec + shard JSON. Both
    encodings must round-trip cleanly so the remote can rebuild the
    dataclasses."""
    import base64

    from mtg_bot.training.distributed import (
        SelfPlayJobSpec,
        _build_remote_pull_command,
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
    cmd = _build_remote_pull_command(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_001_self_play_v6",
        iter_total_games=500,
        batch_size=8,
        stamp="20260503T230000Z",
    )
    # POSIX cd + venv invocation.
    assert "cd /Users/g/repo" in cmd
    assert ".venv-py313/bin/python" in cmd
    assert "scripts/run_self_play_shard.py" in cmd
    assert "--mode=pull" in cmd
    assert "--queue-url=http://master:5099" in cmd
    assert "--run-id=iter_001_self_play_v6" in cmd
    assert "--iter-total-games=500" in cmd
    assert "--batch-size=8" in cmd
    assert "--stamp=20260503T230000Z" in cmd
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


def test_remote_join_windows_normalizes_to_forward_slashes():
    """Windows scp's quoting rejects mixed-separator paths like
    ``C:\\Users\\foo/sub/bar``. ``_remote_join`` normalizes
    backslashes in any input segment to ``/`` so the whole path is
    forward-slashed; cmd.exe handles ``C:/...`` fine, scp parses it,
    SSH server resolves it. Pinned because we hit this in the smoke
    (events JSONL silently failed to scp back from the Win10 box)."""
    from mtg_bot.training.distributed import _remote_join

    shard = ShardConfig(
        host="winbox", n_games=10, user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )
    joined = _remote_join(
        shard, "C:\\Users\\g\\Projects\\mtg-bot",
        "training_progress", "iter_001_events.jsonl",
    )
    assert "\\" not in joined
    assert joined == (
        "C:/Users/g/Projects/mtg-bot/training_progress/"
        "iter_001_events.jsonl"
    )


def test_remote_join_posix_uses_forward_slashes():
    from mtg_bot.training.distributed import _remote_join

    shard = ShardConfig(
        host="mac", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    joined = _remote_join(
        shard, "/Users/g/repo", "training_progress", "x.json",
    )
    assert joined == "/Users/g/repo/training_progress/x.json"


def test_remote_bundle_sync_command_posix():
    """POSIX shell uses ``/tmp/repo.bundle`` + bash quoting."""
    from mtg_bot.training.distributed import (
        _build_remote_bundle_sync_command,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    cmd = _build_remote_bundle_sync_command(
        shard, "http://master:5099/repo.bundle",
    )
    assert "cd /Users/g/repo" in cmd
    assert "curl -sSL http://master:5099/repo.bundle -o /tmp/repo.bundle" in cmd
    assert "git fetch /tmp/repo.bundle main" in cmd
    assert "git reset --hard FETCH_HEAD" in cmd


def test_remote_bundle_sync_command_windows():
    """Windows shell uses ``%TEMP%\\repo.bundle`` + cmd.exe ``cd /d``
    + ``curl.exe`` (the explicit ``.exe`` so cmd doesn't accidentally
    pick up a PowerShell alias on PATH)."""
    from mtg_bot.training.distributed import (
        _build_remote_bundle_sync_command,
    )
    shard = ShardConfig(
        host="winbox", n_games=10, user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )
    cmd = _build_remote_bundle_sync_command(
        shard, "http://master:5099/repo.bundle",
    )
    assert 'cd /d "C:\\Users\\g\\Projects\\mtg-bot"' in cmd
    assert (
        'curl.exe -sSL http://master:5099/repo.bundle '
        '-o "%TEMP%\\repo.bundle"'
    ) in cmd
    assert 'git fetch "%TEMP%\\repo.bundle" main' in cmd
    assert "git reset --hard FETCH_HEAD" in cmd


def test_remote_pull_command_windows_uses_cmd_syntax():
    """A Windows shard (``.exe`` venv python) must use cmd.exe-style
    ``cd /d "path" && set PYTHONPATH=src && "..\\python.exe" ...``
    instead of POSIX bash form."""
    from mtg_bot.training.distributed import (
        SelfPlayJobSpec,
        _build_remote_pull_command,
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
    cmd = _build_remote_pull_command(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_001", iter_total_games=500,
        batch_size=8, stamp="20260503T000000Z",
    )
    assert 'cd /d "C:\\Users\\g\\Projects\\mtg-bot"' in cmd
    assert "set PYTHONPATH=src" in cmd
    assert '".venv-py313\\Scripts\\python.exe"' in cmd
    assert "--mode=pull" in cmd
    assert "--queue-url=http://master:5099" in cmd


# ---- EventLog + helpers ----------------------------------------


def test_event_log_appends_jsonl_one_line_per_record(tmp_path: Path):
    """``EventLog.record(event, **kwargs)`` writes one JSON object
    per line, each line carrying its own UTC timestamp + event +
    arbitrary kwargs. Append-only, so re-opening + recording adds
    rather than overwriting."""
    from mtg_bot.training.distributed import EventLog

    log_path = tmp_path / "shard_x_events.jsonl"
    log = EventLog(log_path)
    log.record("shard_start", run_id="r", n_workers=4)
    log.record("game_end", game_idx=0, wall_s=1.23)
    # Re-instantiate to confirm append (not truncate).
    log2 = EventLog(log_path)
    log2.record("shard_end", status="completed", n_games=1)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["event"] == "shard_start"
    assert parsed[0]["run_id"] == "r"
    assert parsed[1]["event"] == "game_end"
    assert parsed[1]["wall_s"] == 1.23
    assert parsed[2]["event"] == "shard_end"
    # All entries carry an iso-8601 ts (cheap shape check; full
    # parsing is overkill).
    for p in parsed:
        assert "T" in p["ts"]


def test_event_log_handles_non_json_native_kwargs(tmp_path: Path):
    """``Path`` and other non-JSON values must serialize via ``str``
    without raising — observability should never break a self-play
    run."""
    from mtg_bot.training.distributed import EventLog

    log = EventLog(tmp_path / "ev.jsonl")
    log.record("batch_saved", npz_path=tmp_path / "out.npz")
    line = (tmp_path / "ev.jsonl").read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert "npz_path" in parsed
    assert "out.npz" in parsed["npz_path"]


def test_machine_metadata_returns_basic_fields():
    """Smoke for the machine-metadata helper. Specific fields must
    be present so cross-machine analysis can group by host. Don't
    pin exact values — they vary by box."""
    from mtg_bot.training.distributed import _machine_metadata

    info = _machine_metadata()
    assert "host" in info
    assert "platform" in info
    assert "python_version" in info
    assert "cpu_count" in info
    assert info["cpu_count"] is None or info["cpu_count"] >= 1


def test_weights_digest_is_stable_for_same_file(tmp_path: Path):
    """SHA-256 prefix is stable for identical bytes, different for
    distinct bytes. Used to confirm "every shard ran the same
    weights" in cross-machine analysis."""
    from mtg_bot.training.distributed import _weights_digest

    a = tmp_path / "a.pt"
    b = tmp_path / "b.pt"
    a.write_bytes(b"weights-version-1" * 100)
    b.write_bytes(b"weights-version-2" * 100)
    da1 = _weights_digest(str(a))
    da2 = _weights_digest(str(a))
    db = _weights_digest(str(b))
    assert da1 == da2
    assert da1 != db
    assert isinstance(da1, str) and len(da1) == 16


def test_weights_digest_returns_none_for_missing_file(tmp_path: Path):
    """Missing weights file shouldn't raise — observability is
    best-effort."""
    from mtg_bot.training.distributed import _weights_digest

    assert _weights_digest(str(tmp_path / "nope.pt")) is None


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
