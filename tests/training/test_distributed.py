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
        )
    finally:
        server.shutdown()
    # 4 games drained, two shards each writing one npz per game
    # (flush_every = n_workers = 1). Total npzs = 4 regardless of
    # how the shards split the work.
    assert len(paths) == 4
    assert all(p.is_file() for p in paths)
    assert all(
        p.parent == out_dir.resolve() or p.parent == out_dir
        for p in paths
    )
    for shard_label in ("A", "B"):
        events_path = (
            progress_dir
            / f"iter_001_self_play_v1_shard_{shard_label}_events.jsonl"
        )
        assert events_path.is_file(), f"missing {events_path.name}"
        lines = events_path.read_text(encoding="utf-8").splitlines()
        assert lines, f"events log {events_path.name} is empty"
        events = [json.loads(line) for line in lines]
        assert events[0]["event"] == "shard_start"
        assert "machine" in events[0]
        assert "host" in events[0]["machine"]
        assert events[-1]["event"] == "shard_end"
        assert events[-1]["status"] == "completed"
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
    for ge in game_ends:
        assert "wall_s" in ge and ge["wall_s"] > 0
        assert "n_samples" in ge
        assert "game_idx" in ge
    # Per-worker take produces game_take events: 4 successful takes
    # + 2 empty takes (one per shard hitting the end of the queue).
    game_takes = [e for e in all_events if e["event"] == "game_take"]
    assert len(game_takes) == 6
    successful = [t for t in game_takes if t["game_idx"] is not None]
    assert len(successful) == 4
    for t in game_takes:
        assert t["in_flight"] == 0  # n_workers=1: refill at empty


def test_run_distributed_eval_two_local_shards_aggregate_counts(
    tmp_path: Path,
):
    """End-to-end smoke for the distributed eval orchestrator: two
    local shards play 4 head-to-head games (NN-vs-NN with the same
    weights for both seats — winner outcome is just whoever the
    engine picks). Returns aggregated counts that sum to 4."""
    from mtg_bot.training.distributed import (
        EvalJobSpec, run_distributed_eval,
    )

    weights_path, hidden_sizes = _tiny_dual_head_weights(tmp_path)
    progress_dir = tmp_path / "training_progress"
    spec = EvalJobSpec(
        new_weights_path=str(weights_path),
        old_weights_path=str(weights_path),
        samples=1, inner_nodes=10,
        hidden_sizes=hidden_sizes,
        base_seed=0,
        enable_mulligans=False,
        per_game_timeout_sec=None,
        opponent_label="self",
    )
    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_games=2, label="A", n_workers=1),
        ShardConfig(host="local", n_games=2, label="B", n_workers=1),
    ))
    queue_url, server = _start_queue_server()
    try:
        counts = run_distributed_eval(
            cfg, spec,
            progress_dir=progress_dir,
            run_id_prefix="iter_001_eval_test",
            total_games=4,
            queue_url=queue_url,
        )
    finally:
        server.shutdown()
    assert counts["n_games"] == 4
    assert (
        counts["wins_new"] + counts["wins_old"]
        + counts["draws"] + counts["crashed"]
    ) == 4
    for label in ("A", "B"):
        ev = (
            progress_dir
            / f"iter_001_eval_test_shard_{label}_events.jsonl"
        )
        assert ev.is_file()
        events = [json.loads(line) for line in ev.read_text().splitlines()]
        assert events[0]["event"] == "shard_start"
        assert events[0]["mode"] == "eval"
        assert events[-1]["event"] == "shard_end"
        assert events[-1]["status"] == "completed"


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
    assert "--batch-size" not in cmd  # worker-driven pulls drop batching
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


def test_eval_spec_round_trips_through_to_dict_from_dict():
    """``EvalJobSpec.to_dict`` + ``from_dict`` round-trip cleanly with
    backslash-path normalization on Windows-style paths."""
    from mtg_bot.training.distributed import EvalJobSpec

    spec = EvalJobSpec(
        new_weights_path="trained_weights\\v7\\weights.pt",
        old_weights_path="trained_weights\\v6\\weights.pt",
        samples=4, inner_nodes=200, hidden_sizes=(1024, 1024, 512),
        base_seed=2_007_777,
        enable_mulligans=True,
        per_game_timeout_sec=300.0,
        deck_pool_path="data\\17lands\\eoe_decks.json.gz",
        capture_every=10,
        nn_new_version_label="v7",
        nn_old_version_label="v6",
        replays_root="replays",
        hang_dump_root="debug_hangs",
        opponent_label="v6",
    )
    d = spec.to_dict()
    assert d["new_weights_path"] == "trained_weights/v7/weights.pt"
    assert d["old_weights_path"] == "trained_weights/v6/weights.pt"
    assert d["deck_pool_path"] == "data/17lands/eoe_decks.json.gz"
    rt = EvalJobSpec.from_dict(d)
    # to_dict normalized paths; from_dict preserves the normalized
    # values, so the round-trip equals a posix-paths version.
    assert rt.new_weights_path == "trained_weights/v7/weights.pt"
    assert rt.old_weights_path == "trained_weights/v6/weights.pt"
    assert rt.deck_pool_path == "data/17lands/eoe_decks.json.gz"
    assert rt.samples == 4 and rt.inner_nodes == 200
    assert rt.hidden_sizes == (1024, 1024, 512)
    assert rt.opponent_label == "v6"


def test_eval_spec_old_weights_can_be_none():
    """``old_weights_path=None`` runs the heuristic-opponent path —
    ``to_dict`` keeps it as null, ``from_dict`` accepts."""
    from mtg_bot.training.distributed import EvalJobSpec

    spec = EvalJobSpec(
        new_weights_path="weights.pt", old_weights_path=None,
        samples=2, inner_nodes=10, hidden_sizes=None,
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    d = spec.to_dict()
    assert d["old_weights_path"] is None
    rt = EvalJobSpec.from_dict(d)
    assert rt.old_weights_path is None


def test_remote_eval_command_posix_round_trips():
    """``_build_remote_eval_command`` produces the SSH one-liner that
    starts an eval shard on a POSIX remote: ``--mode=eval`` and an
    ``EvalJobSpec`` (not ``SelfPlayJobSpec``) base64'd into
    ``--spec-b64``."""
    import base64
    from mtg_bot.training.distributed import (
        EvalJobSpec, _build_remote_eval_command,
    )

    spec = EvalJobSpec(
        new_weights_path="trained_weights/v7/weights.pt",
        old_weights_path="trained_weights/v6/weights.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=300.0,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    cmd = _build_remote_eval_command(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_001_eval_v7_vs_v6",
        iter_total_games=500,
        stamp="20260503T230000Z",
    )
    assert "cd /Users/g/repo" in cmd
    assert "scripts/run_self_play_shard.py" in cmd
    assert "--mode=eval" in cmd
    assert "--queue-url=http://master:5099" in cmd
    assert "--run-id=iter_001_eval_v7_vs_v6" in cmd
    assert "--iter-total-games=500" in cmd
    assert "--batch-size" not in cmd
    assert "--stamp=20260503T230000Z" in cmd
    # spec_b64 decodes back to an EvalJobSpec with both weights paths.
    marker = "--spec-b64="
    i = cmd.index(marker) + len(marker)
    encoded = cmd[i:cmd.index(" ", i)]
    decoded = json.loads(
        base64.b64decode(encoded.encode("ascii")).decode("utf-8"),
    )
    rt = EvalJobSpec.from_dict(decoded)
    assert rt.new_weights_path == "trained_weights/v7/weights.pt"
    assert rt.old_weights_path == "trained_weights/v6/weights.pt"


def test_remote_eval_command_windows_uses_cmd_syntax():
    from mtg_bot.training.distributed import (
        EvalJobSpec, _build_remote_eval_command,
    )

    spec = EvalJobSpec(
        new_weights_path="trained_weights/v7/weights.pt",
        old_weights_path=None,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="win-box", n_games=10, user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )
    cmd = _build_remote_eval_command(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_001_eval", iter_total_games=500,
        stamp="20260503T000000Z",
    )
    assert 'cd /d "C:\\Users\\g\\Projects\\mtg-bot"' in cmd
    assert "set PYTHONPATH=src" in cmd
    assert '".venv-py313\\Scripts\\python.exe"' in cmd
    assert "--mode=eval" in cmd


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


def test_loopback_queue_url_rewrites_host_to_127_0_0_1():
    """Master's own local shard hits the queue endpoint via 127.0.0.1
    instead of the tailnet hostname. Empirically, on Windows the
    tailnet-name path adds ~4s per take (IPv6-first DNS); ``localhost``
    adds ~2s; the IP literal is ~12ms. Pinned because regressing this
    silently caps the master's contribution to ~10% of any iter."""
    from mtg_bot.training.distributed import _loopback_queue_url

    assert _loopback_queue_url(
        "http://desktop-j05412i:5099"
    ) == "http://127.0.0.1:5099"
    assert _loopback_queue_url(
        "http://master.tail123.ts.net:5099"
    ) == "http://127.0.0.1:5099"
    assert _loopback_queue_url(
        "http://h:5099/queue?x=1"
    ) == "http://127.0.0.1:5099/queue?x=1"
    assert _loopback_queue_url("http://h") == "http://127.0.0.1"


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
        stamp="20260503T000000Z",
    )
    assert 'cd /d "C:\\Users\\g\\Projects\\mtg-bot"' in cmd
    assert "set PYTHONPATH=src" in cmd
    assert '".venv-py313\\Scripts\\python.exe"' in cmd
    assert "--mode=pull" in cmd
    assert "--queue-url=http://master:5099" in cmd
    assert "--batch-size" not in cmd


# ---- weight-push step ------------------------------------------


def test_remote_mkdir_command_posix_quotes_path():
    """POSIX uses ``mkdir -p`` with shlex-quoted target."""
    from mtg_bot.training.distributed import _build_remote_mkdir_command

    shard = ShardConfig(
        host="mac", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    cmd = _build_remote_mkdir_command(
        shard, "/Users/g/repo/trained_weights/v6",
    )
    assert cmd == "mkdir -p /Users/g/repo/trained_weights/v6"


def test_remote_mkdir_command_windows_uses_powershell_new_item():
    """cmd.exe ``mkdir`` silently fails on existing dirs over SSH;
    PowerShell ``New-Item -Force`` is genuinely idempotent."""
    from mtg_bot.training.distributed import _build_remote_mkdir_command

    shard = ShardConfig(
        host="winbox", n_games=10, user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )
    cmd = _build_remote_mkdir_command(
        shard, "C:/Users/g/Projects/mtg-bot/trained_weights/v6",
    )
    assert cmd == (
        "powershell -Command \"New-Item -ItemType Directory -Force "
        "-Path 'C:/Users/g/Projects/mtg-bot/trained_weights/v6'\""
    )


class _RecordingSubprocess:
    """Records every (cmd, kwargs) pair instead of exec'ing. Used to
    pin the order + shape of subprocess calls inside
    ``run_shard_remote`` without touching the network."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Result()


def _capture_run_shard_remote_calls(
    monkeypatch, shard, spec, *, bundle_url=None, tmp_path,
):
    """Drive ``run_shard_remote`` end-to-end with all subprocess calls
    redirected to a recorder. Returns the recorded command list."""
    from mtg_bot.training import distributed as dist

    rec = _RecordingSubprocess()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_002_self_play_v7",
        iter_total_games=500,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_002_self_play_v7",
        stamp="20260503T230000Z",
        bundle_url=bundle_url,
    )
    return rec.calls


def test_weight_push_posix_command_shape(monkeypatch, tmp_path):
    """POSIX shard: weight-push step issues ``ssh ... mkdir -p
    <repo>/<parent>`` then ``scp <abs_master>/<weights> remote:<repo>/
    <weights>``."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake-weights")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    calls = _capture_run_shard_remote_calls(
        monkeypatch, shard, spec, tmp_path=tmp_path,
    )
    mkdir_call = next(
        c for c in calls if c[0] == "ssh" and "mkdir -p" in c[-1]
    )
    assert "mkdir -p /Users/g/repo/trained_weights/v7" in mkdir_call[-1]

    scp_pushes = [
        c for c in calls
        if c[0] == "scp"
        and any(p.endswith(":/Users/g/repo/trained_weights/v7/weights.pt")
                for p in c)
    ]
    assert len(scp_pushes) == 1
    push = scp_pushes[0]
    abs_master_src = str((tmp_path / weights_rel).resolve())
    assert abs_master_src in push
    assert "g@macbook:/Users/g/repo/trained_weights/v7/weights.pt" in push


def test_weight_push_windows_command_shape(monkeypatch, tmp_path):
    """Windows shard: mkdir routes through PowerShell New-Item; scp
    dst is forward-slashed (cmd.exe + scp both accept ``C:/...``,
    and scp's quoting layer rejects mixed separators)."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake-weights")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="winbox", n_games=10, user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )
    calls = _capture_run_shard_remote_calls(
        monkeypatch, shard, spec, tmp_path=tmp_path,
    )
    mkdir_call = next(
        c for c in calls if c[0] == "ssh" and "powershell" in c[-1]
    )
    assert (
        "powershell -Command \"New-Item -ItemType Directory -Force "
        "-Path 'C:/Users/g/Projects/mtg-bot/trained_weights/v7'\""
    ) in mkdir_call[-1]

    scp_pushes = [
        c for c in calls
        if c[0] == "scp"
        and any(
            p.endswith(
                ":C:/Users/g/Projects/mtg-bot/"
                "trained_weights/v7/weights.pt"
            )
            for p in c
        )
    ]
    assert len(scp_pushes) == 1
    push = scp_pushes[0]
    dst_target = (
        "g@winbox:C:/Users/g/Projects/mtg-bot/"
        "trained_weights/v7/weights.pt"
    )
    assert dst_target in push
    for arg in push:
        if arg.startswith("g@"):
            assert "\\" not in arg


def test_run_shard_remote_call_sequence(monkeypatch, tmp_path):
    """End-to-end ordering: bundle-sync → mkdir → weight-scp → ssh
    self-play → final progress + events scp-back. Mocks all
    subprocess execution and the progress poller; runs the full
    function and asserts the call order."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake-weights")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    calls = _capture_run_shard_remote_calls(
        monkeypatch, shard, spec,
        bundle_url="http://master:5099/repo.bundle",
        tmp_path=tmp_path,
    )

    def _classify(c: list[str]) -> str:
        if c[0] == "ssh":
            tail = c[-1]
            if "git fetch" in tail and "repo.bundle" in tail:
                return "bundle_sync"
            if "mkdir -p" in tail or "New-Item" in tail:
                return "mkdir"
            if "run_self_play_shard.py" in tail:
                return "self_play"
            if "iterate_data" in tail and (
                "ls " in tail or "dir /b" in tail
            ):
                return "list_npzs"
            return f"ssh_other:{tail[:40]}"
        if c[0] == "scp":
            target_idx = next(
                (i for i, a in enumerate(c) if "@" in a), None
            )
            if target_idx is None:
                return "scp_unknown"
            target = c[target_idx]
            if target.startswith("g@") and ":" in target:
                rhs = target.split(":", 1)[1]
                if rhs.endswith("weights.pt") and target_idx == len(c) - 1:
                    return "weight_push"
                if rhs.endswith(".json"):
                    return "progress_pull"
                if rhs.endswith(".jsonl"):
                    return "events_pull"
            return "scp_other"
        return f"other:{c[0]}"

    seq = [_classify(c) for c in calls]
    bundle_idx = seq.index("bundle_sync")
    mkdir_idx = seq.index("mkdir")
    weight_idx = seq.index("weight_push")
    self_play_idx = seq.index("self_play")
    progress_pull_idx = seq.index("progress_pull")
    events_pull_idx = seq.index("events_pull")

    assert (
        bundle_idx < mkdir_idx < weight_idx
        < self_play_idx < progress_pull_idx < events_pull_idx
    ), f"unexpected order: {seq}"


def test_weight_push_failure_propagates(monkeypatch, tmp_path):
    """If the scp push fails (non-zero exit / OSError), the error
    must propagate. We previously had a silent-failure version that
    burned a debug session — pin this so it doesn't regress."""
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake-weights")

    class _Boom:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            if cmd[0] == "scp":
                raise subprocess.CalledProcessError(
                    1, cmd, output="", stderr="permission denied",
                )

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

    import subprocess
    boom = _Boom()
    monkeypatch.setattr(dist, "_run_subprocess", boom)
    monkeypatch.setattr(dist.subprocess, "run", boom)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    with pytest.raises(subprocess.CalledProcessError):
        dist.run_shard_remote(
            shard, spec,
            queue_url="http://master:5099",
            run_id="iter_002",
            iter_total_games=10,
            progress_dir=tmp_path / "training_progress",
            output_dir=tmp_path / "iterate_data",
            run_id_prefix="iter_002",
            stamp="20260503T230000Z",
        )


# ---- _AggregateProgressPoller ----------------------------------


def test_aggregate_progress_poller_sums_data_gen_shards(tmp_path: Path):
    """Aggregator reads all per-shard self-play JSONs in
    ``progress_dir`` matching ``<run_id>_shard_*.json`` and sums the
    counters into a single ``<run_id>.json``."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_001_self_play_v6"
    # Three shards mid-run, with different progress.
    for label, done, samples, p0, p1, dr, cr, nw in (
        ("local", 30, 4500, 12, 8, 10, 0, 16),
        ("mac", 50, 7200, 25, 20, 5, 0, 14),
        ("win", 5, 600, 2, 2, 1, 0, 4),
    ):
        (pdir / f"{run_id}_shard_{label}.json").write_text(
            json.dumps({
                "run_id": f"{run_id}_shard_{label}",
                "kind": "data_gen",
                "status": "running",
                "n_games_total": 200, "n_games_done": done,
                "n_samples": samples, "n_workers": nw,
                "p0_wins": p0, "p1_wins": p1, "draws": dr,
                "crashed": cr,
            }), encoding="utf-8",
        )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=200, kind="data_gen",
    )
    poller._write("running")  # one snapshot, no thread needed
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    assert agg["run_id"] == run_id
    assert agg["kind"] == "data_gen"
    assert agg["status"] == "running"
    assert agg["n_games_total"] == 200
    assert agg["n_games_done"] == 85
    assert agg["n_samples"] == 4500 + 7200 + 600
    assert agg["n_workers"] == 16 + 14 + 4
    assert agg["p0_wins"] == 39
    assert agg["p1_wins"] == 30
    assert agg["draws"] == 16
    assert agg["crashed"] == 0
    assert {m["label"] for m in agg["machines"]} == {"local", "mac", "win"}


def test_aggregate_progress_poller_sums_eval_shards(tmp_path: Path):
    """Aggregator handles eval-kind shards: sums wins_new, wins_old,
    draws, computes overall win_rate from the totals."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_002_eval_v8_vs_v7"
    for label, n, wn, wo, dr in (
        ("local", 30, 12, 18, 0),
        ("mac", 50, 22, 28, 0),
        ("win", 20, 8, 12, 0),
    ):
        (pdir / f"{run_id}_shard_{label}.json").write_text(
            json.dumps({
                "run_id": f"{run_id}_shard_{label}",
                "kind": "eval",
                "status": "running",
                "n_games_total": 100, "n_games_done": n,
                "n_workers": 4,
                "wins_new": wn, "wins_old": wo, "draws": dr,
                "crashed": 0,
            }), encoding="utf-8",
        )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=100, kind="eval",
        opponent_label="v7",
    )
    poller._write("completed")
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    assert agg["status"] == "completed"
    assert agg["n_games_done"] == 100
    assert agg["wins_new"] == 42
    assert agg["wins_old"] == 58
    assert agg["draws"] == 0
    # win_rate from cluster totals.
    assert abs(agg["win_rate"] - 42 / 100) < 1e-9
    assert agg["opponent_label"] == "v7"


def test_aggregate_progress_poller_skips_eval_result_files(
    tmp_path: Path,
):
    """Eval shards on remotes write a sibling ``_result.json`` with
    the same counts as the per-shard progress JSON. The aggregator
    must skip it; otherwise every remote shard's wins/draws/crashed
    get double-counted in the cluster total. Reproduced from a real
    iter run where ``wins_new + wins_old + crashed`` summed to 871
    on a 500-game eval."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_004_eval_v10_vs_v7"
    # Three shard JSONs (the canonical per-shard EvalProgress output).
    for label, wn, wo in (
        ("local", 80, 50),
        ("mac", 200, 120),
        ("win", 50, 30),
    ):
        (pdir / f"{run_id}_shard_{label}.json").write_text(
            json.dumps({
                "kind": "eval", "status": "completed",
                "n_games_total": 500, "n_games_done": wn + wo,
                "n_workers": 4,
                "wins_new": wn, "wins_old": wo, "draws": 0,
                "crashed": 0,
            }), encoding="utf-8",
        )
    # Two ``_result.json`` files written by the SSH wrapper for the
    # remote shards — same numbers as the corresponding shard file.
    for label, wn, wo in (("mac", 200, 120), ("win", 50, 30)):
        (pdir / f"{run_id}_shard_{label}_result.json").write_text(
            json.dumps({
                "n_games": wn + wo,
                "wins_new": wn, "wins_old": wo, "draws": 0,
                "crashed": 0,
            }), encoding="utf-8",
        )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=500, kind="eval",
    )
    poller._write("completed")
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    assert agg["wins_new"] == 80 + 200 + 50  # NOT double-counted
    assert agg["wins_old"] == 50 + 120 + 30
    assert agg["n_games_done"] == 530  # sum across 3 shards only
    # Machines list also excludes the _result entries.
    labels = sorted(m["label"] for m in agg["machines"])
    assert labels == ["local", "mac", "win"]


def test_aggregate_progress_poller_handles_missing_shard_files(
    tmp_path: Path,
):
    """No per-shard files yet (poller fired before any shard wrote
    its first snapshot) shouldn't crash; aggregate JSON should still
    appear with zeroed counts."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    poller = _AggregateProgressPoller(
        progress_dir=tmp_path, run_id="iter_x",
        n_games_total=100, kind="data_gen",
    )
    poller._write("running")
    agg = json.loads((tmp_path / "iter_x.json").read_text())
    assert agg["n_games_done"] == 0
    assert agg["machines"] == []


def test_aggregate_progress_poller_machines_carry_per_host_perf_stats(
    tmp_path: Path,
):
    """The per-machine sub-card UI surfaces three perf-only stats per
    host: secs/game, crashes, workers. The aggregator is the source of
    truth for that grouping, so each entry in ``agg['machines']`` must
    include ``elapsed_seconds`` (raw) and ``per_game_seconds``
    (precomputed elapsed_seconds / n_games_done; ``None`` when
    n_games_done is 0). The host label is parsed from the shard
    filename suffix (the part after ``_shard_``)."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_007_self_play_v9"
    # Two real-world host suffixes: hyphenated tailnet hostnames; one
    # finished, one mid-run with non-zero crashes.
    (pdir / f"{run_id}_shard_greggs-macbook-pro.json").write_text(
        json.dumps({
            "run_id": f"{run_id}_shard_greggs-macbook-pro",
            "kind": "data_gen", "status": "completed",
            "n_games_total": 200, "n_games_done": 100,
            "n_samples": 12000, "n_workers": 14,
            "p0_wins": 60, "p1_wins": 40, "draws": 0,
            "crashed": 3, "elapsed_seconds": 600.0,
        }), encoding="utf-8",
    )
    (pdir / f"{run_id}_shard_desktop-j05412i.json").write_text(
        json.dumps({
            "run_id": f"{run_id}_shard_desktop-j05412i",
            "kind": "data_gen", "status": "running",
            "n_games_total": 200, "n_games_done": 0,
            "n_samples": 0, "n_workers": 16,
            "p0_wins": 0, "p1_wins": 0, "draws": 0,
            "crashed": 0, "elapsed_seconds": 5.0,
        }), encoding="utf-8",
    )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=400, kind="data_gen",
    )
    poller._write("running")
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    by_label = {m["label"]: m for m in agg["machines"]}
    # Host suffix is parsed from the shard filename, NOT the run_id
    # field — labels with hyphens round-trip verbatim.
    assert set(by_label) == {"greggs-macbook-pro", "desktop-j05412i"}
    mac = by_label["greggs-macbook-pro"]
    assert mac["n_games_done"] == 100
    assert mac["n_workers"] == 14
    assert mac["crashed"] == 3
    assert mac["elapsed_seconds"] == 600.0
    # 600s / 100 games = 6.0 s/game.
    assert mac["per_game_seconds"] == pytest.approx(6.0)
    desk = by_label["desktop-j05412i"]
    assert desk["n_games_done"] == 0
    assert desk["n_workers"] == 16
    assert desk["crashed"] == 0
    assert desk["elapsed_seconds"] == 5.0
    # Zero-divide guard: per_game_seconds must be None, not 0.0 or NaN.
    # The UI distinguishes "no data yet" from "0 secs/game".
    assert desk["per_game_seconds"] is None


def test_aggregate_progress_poller_emits_games_per_hour_data_gen(
    tmp_path: Path,
):
    """``games_per_hour`` and ``samples_per_hour`` must always be
    present on the data_gen aggregate, both running and completed,
    so the UI never sees a missing field. Pin elapsed to a known
    value by overwriting ``_started_perf``."""
    import time as time_mod
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_010_self_play_v3"
    for label, done, samples in (
        ("local", 30, 4500),
        ("mac", 50, 7200),
    ):
        (pdir / f"{run_id}_shard_{label}.json").write_text(
            json.dumps({
                "kind": "data_gen", "status": "running",
                "n_games_total": 200, "n_games_done": done,
                "n_samples": samples, "n_workers": 4,
                "p0_wins": 0, "p1_wins": 0, "draws": 0, "crashed": 0,
            }), encoding="utf-8",
        )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=200, kind="data_gen",
    )
    poller._started_perf = time_mod.monotonic() - 60.0
    poller._write("running")
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    assert "games_per_hour" in agg
    assert "samples_per_hour" in agg
    expected_gph = 80 / 60.0 * 3600.0
    expected_sph = 11700 / 60.0 * 3600.0
    assert abs(agg["games_per_hour"] - expected_gph) / expected_gph < 0.05
    assert abs(agg["samples_per_hour"] - expected_sph) / expected_sph < 0.05

    poller._write("completed")
    agg2 = json.loads((pdir / f"{run_id}.json").read_text())
    assert "games_per_hour" in agg2
    assert "samples_per_hour" in agg2


def test_aggregate_progress_poller_emits_games_per_hour_eval(
    tmp_path: Path,
):
    """``games_per_hour`` must always be present on the eval
    aggregate so the eval card's rate field renders."""
    import time as time_mod
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_011_eval_v3_vs_v2"
    for label, n, wn, wo in (
        ("local", 30, 12, 18),
        ("mac", 50, 22, 28),
    ):
        (pdir / f"{run_id}_shard_{label}.json").write_text(
            json.dumps({
                "kind": "eval", "status": "running",
                "n_games_total": 100, "n_games_done": n,
                "n_workers": 4,
                "wins_new": wn, "wins_old": wo, "draws": 0,
                "crashed": 0, "avg_decisions": 0.0,
            }), encoding="utf-8",
        )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=100, kind="eval",
    )
    poller._started_perf = time_mod.monotonic() - 120.0
    poller._write("running")
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    assert "games_per_hour" in agg
    expected = 80 / 120.0 * 3600.0
    assert abs(agg["games_per_hour"] - expected) / expected < 0.05

    poller._write("completed")
    agg2 = json.loads((pdir / f"{run_id}.json").read_text())
    assert "games_per_hour" in agg2


def test_aggregate_progress_poller_eval_avg_decisions_weighted(
    tmp_path: Path,
):
    """Eval aggregate's ``avg_decisions`` is the per-game-weighted
    mean of each shard's ``avg_decisions``. The shards report a mean
    over their own games, so a shard's decision total is
    ``avg_decisions * n_games_done``; the cluster mean is the sum of
    those totals divided by total games."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_012_eval_v4_vs_v3"
    rows = (
        ("local", 30, 11.5),
        ("mac", 50, 14.25),
        ("win", 20, 9.75),
    )
    for label, n, avg_dec in rows:
        (pdir / f"{run_id}_shard_{label}.json").write_text(
            json.dumps({
                "kind": "eval", "status": "running",
                "n_games_total": 100, "n_games_done": n,
                "n_workers": 4,
                "wins_new": 0, "wins_old": 0, "draws": 0,
                "crashed": 0, "avg_decisions": avg_dec,
            }), encoding="utf-8",
        )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=100, kind="eval",
    )
    poller._write("running")
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    expected = sum(n * d for _, n, d in rows) / sum(n for _, n, _ in rows)
    assert abs(agg["avg_decisions"] - expected) < 1e-9


def test_aggregate_progress_poller_eval_avg_decisions_zero_when_empty(
    tmp_path: Path,
):
    """No per-shard files yet (poller fired before first snapshot)
    must still produce ``avg_decisions == 0.0`` rather than crashing
    or omitting the field."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    poller = _AggregateProgressPoller(
        progress_dir=tmp_path, run_id="iter_y",
        n_games_total=100, kind="eval",
    )
    poller._write("running")
    agg = json.loads((tmp_path / "iter_y.json").read_text())
    assert agg["avg_decisions"] == 0.0
    assert agg["games_per_hour"] == 0.0


# ---- EventLog + helpers ----------------------------------------


def test_event_log_writes_one_line_per_record_and_truncates_on_reopen(
    tmp_path: Path,
):
    """``EventLog.record(event, **kwargs)`` writes one JSON object
    per line, each line carrying its own UTC timestamp + event +
    arbitrary kwargs. Re-instantiating ``EventLog`` on the same path
    truncates — re-running the same iter shouldn't accumulate stale
    events from prior runs."""
    from mtg_bot.training.distributed import EventLog

    log_path = tmp_path / "shard_x_events.jsonl"
    log = EventLog(log_path)
    log.record("shard_start", run_id="r", n_workers=4)
    log.record("game_end", game_idx=0, wall_s=1.23)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["event"] == "shard_start"
    assert parsed[0]["run_id"] == "r"
    assert parsed[1]["event"] == "game_end"
    assert parsed[1]["wall_s"] == 1.23
    for p in parsed:
        assert "T" in p["ts"]

    log2 = EventLog(log_path)
    log2.record("shard_end", status="completed", n_games=1)
    lines2 = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines2) == 1
    parsed2 = json.loads(lines2[0])
    assert parsed2["event"] == "shard_end"
    assert parsed2["status"] == "completed"


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


# ---- Distributed replay collection --------------------------------


class _ScriptedSubprocess:
    """Records calls and lets tests inject scripted stdout for
    specific ssh-listing commands. Anything else returns empty
    stdout. Used to drive the replay-collection ls path."""

    def __init__(
        self,
        listing_responses: Optional[dict[str, str]] = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._listing_responses = listing_responses or {}

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        stdout = ""
        if cmd and cmd[0] == "ssh":
            tail = cmd[-1]
            for marker, payload in self._listing_responses.items():
                if marker in tail:
                    stdout = payload
                    break

        class _Result:
            returncode = 0

            def __init__(self, _stdout):
                self.stdout = _stdout
                self.stderr = ""
        return _Result(stdout)


def _drive_run_shard_remote(
    monkeypatch, shard, spec, *, tmp_path,
    listing_responses=None,
):
    from mtg_bot.training import distributed as dist

    rec = _ScriptedSubprocess(listing_responses=listing_responses)
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_002_self_play_v7",
        iter_total_games=500,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_002_self_play_v7",
        stamp="20260503T230000Z",
    )
    return rec.calls


def _drive_run_shard_eval_remote(
    monkeypatch, shard, spec, *, tmp_path,
    listing_responses=None,
):
    from mtg_bot.training import distributed as dist

    rec = _ScriptedSubprocess(listing_responses=listing_responses)
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    run_id_full = (
        f"iter_002_eval_v7_shard_{shard.display_label}"
    )
    result_path = (
        tmp_path / "training_progress"
        / f"{run_id_full}_result.json"
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps({
            "n_games": 4,
            "wins_new": 2, "wins_old": 1,
            "draws": 1, "crashed": 0,
        }),
        encoding="utf-8",
    )

    dist.run_shard_eval_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_002_eval_v7",
        iter_total_games=4,
        progress_dir=tmp_path / "training_progress",
        stamp="20260503T230000Z",
    )
    return rec.calls


def test_replay_collection_posix_command_shape(monkeypatch, tmp_path):
    """POSIX shard, capture enabled: orchestrator issues an ``ssh ls``
    of the per-shard remote replay dir and an ``scp`` per listed file
    pulling each .json.gz into the master's
    ``<replays_root>/<run_id>_shard_<label>/``."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=10,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    run_id_full = "iter_002_self_play_v7_shard_macbook"
    listing_marker = (
        f"ls replays/{run_id_full}/*.json.gz"
    )
    listing_payload = (
        "self_play_seed0_idx0001.json.gz\n"
        "self_play_seed0_idx0010.json.gz\n"
    )
    calls = _drive_run_shard_remote(
        monkeypatch, shard, spec,
        tmp_path=tmp_path,
        listing_responses={listing_marker: listing_payload},
    )

    ls_calls = [
        c for c in calls
        if c[0] == "ssh" and listing_marker in c[-1]
    ]
    assert len(ls_calls) == 1
    assert "2>/dev/null" in ls_calls[0][-1]
    assert "xargs -n1 basename" in ls_calls[0][-1]
    assert "cd /Users/g/repo" in ls_calls[0][-1]

    replay_pull_targets = [
        c for c in calls
        if c[0] == "scp" and any(
            p.endswith(".json.gz")
            and "self_play_seed0_idx" in p
            for p in c
        )
    ]
    assert len(replay_pull_targets) == 2
    expected_local_dir = tmp_path / "replays" / run_id_full
    for c in replay_pull_targets:
        src = next(
            p for p in c if p.startswith("g@macbook:")
        )
        basename = src.rsplit("/", 1)[-1]
        assert (
            src
            == f"g@macbook:/Users/g/repo/replays/{run_id_full}/"
            f"{basename}"
        )
        local_dst = c[-1]
        assert local_dst == str(expected_local_dir / basename)
    assert expected_local_dir.is_dir()


def test_replay_collection_windows_command_shape(monkeypatch, tmp_path):
    """Windows shard, capture enabled: ``dir /b`` lists basenames
    under ``replays\\<run_id>_shard_<label>\\*.json.gz``; scp pulls
    each file with the forward-slashed remote path."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=10,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="winbox", n_games=10, user="g",
        repo_path="C:\\Users\\g\\Projects\\mtg-bot",
        venv_python=".venv-py313\\Scripts\\python.exe",
    )
    run_id_full = "iter_002_self_play_v7_shard_winbox"
    listing_marker = (
        f"dir /b replays\\{run_id_full}\\*.json.gz"
    )
    listing_payload = (
        "self_play_seed0_idx0001.json.gz\r\n"
        "self_play_seed0_idx0010.json.gz\r\n"
    )
    calls = _drive_run_shard_remote(
        monkeypatch, shard, spec,
        tmp_path=tmp_path,
        listing_responses={listing_marker: listing_payload},
    )

    ls_calls = [
        c for c in calls
        if c[0] == "ssh" and listing_marker in c[-1]
    ]
    assert len(ls_calls) == 1
    assert "2>nul" in ls_calls[0][-1]
    assert 'cd /d "C:\\Users\\g\\Projects\\mtg-bot"' in ls_calls[0][-1]

    replay_pull_targets = [
        c for c in calls
        if c[0] == "scp" and any(
            p.endswith(".json.gz")
            and "self_play_seed0_idx" in p
            for p in c
        )
    ]
    assert len(replay_pull_targets) == 2
    expected_local_dir = tmp_path / "replays" / run_id_full
    for c in replay_pull_targets:
        src = next(
            p for p in c if p.startswith("g@winbox:")
        )
        assert "\\" not in src
        basename = src.rsplit("/", 1)[-1]
        assert (
            src
            == f"g@winbox:C:/Users/g/Projects/mtg-bot/replays/"
            f"{run_id_full}/{basename}"
        )
        local_dst = c[-1]
        assert local_dst == str(expected_local_dir / basename)
    assert expected_local_dir.is_dir()


def test_replay_collection_skipped_when_capture_off(
    monkeypatch, tmp_path,
):
    """``capture_every=0`` (the default): no replay-listing ssh and no
    replay-pull scp commands fire."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=0,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    calls = _drive_run_shard_remote(
        monkeypatch, shard, spec, tmp_path=tmp_path,
    )
    for c in calls:
        if c[0] == "ssh":
            assert ".json.gz" not in c[-1], c
            assert "/replays/" not in c[-1], c
        if c[0] == "scp":
            assert not any(p.endswith(".json.gz") for p in c), c

    assert not (tmp_path / "replays").exists()


def test_replay_collection_skipped_when_replays_root_none(
    monkeypatch, tmp_path,
):
    """``replays_root=None`` with ``capture_every>0`` is also a skip
    — capture is off without a destination root."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=10,
        replays_root=None,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    calls = _drive_run_shard_remote(
        monkeypatch, shard, spec, tmp_path=tmp_path,
    )
    for c in calls:
        if c[0] == "scp":
            assert not any(p.endswith(".json.gz") for p in c), c


def test_replay_collection_eval_path(monkeypatch, tmp_path):
    """Eval counterpart: ``run_shard_eval_remote`` issues the same
    listing + scp shape as the self-play path."""
    from mtg_bot.training.distributed import EvalJobSpec

    monkeypatch.chdir(tmp_path)
    new_weights = "trained_weights/v7/weights.pt"
    old_weights = "trained_weights/v6/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / "trained_weights" / "v6").mkdir(parents=True)
    (tmp_path / new_weights).write_bytes(b"new")
    (tmp_path / old_weights).write_bytes(b"old")

    spec = EvalJobSpec(
        new_weights_path=new_weights,
        old_weights_path=old_weights,
        samples=1, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=5,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="macbook", n_games=4, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    run_id_full = "iter_002_eval_v7_shard_macbook"
    listing_marker = f"ls replays/{run_id_full}/*.json.gz"
    listing_payload = (
        "eval_seed0_idx0001.json.gz\n"
        "eval_seed0_idx0005.json.gz\n"
    )
    calls = _drive_run_shard_eval_remote(
        monkeypatch, shard, spec,
        tmp_path=tmp_path,
        listing_responses={listing_marker: listing_payload},
    )

    ls_calls = [
        c for c in calls
        if c[0] == "ssh" and listing_marker in c[-1]
    ]
    assert len(ls_calls) == 1

    replay_pulls = [
        c for c in calls
        if c[0] == "scp" and any(
            p.endswith(".json.gz") and "eval_seed0_idx" in p
            for p in c
        )
    ]
    assert len(replay_pulls) == 2
    expected_local_dir = tmp_path / "replays" / run_id_full
    for c in replay_pulls:
        src = next(p for p in c if p.startswith("g@macbook:"))
        basename = src.rsplit("/", 1)[-1]
        assert (
            src
            == f"g@macbook:/Users/g/repo/replays/{run_id_full}/"
            f"{basename}"
        )
        assert c[-1] == str(expected_local_dir / basename)
    assert expected_local_dir.is_dir()


def test_replay_collection_eval_skipped_when_capture_off(
    monkeypatch, tmp_path,
):
    """Eval path with capture off: no replay ls or scp."""
    from mtg_bot.training.distributed import EvalJobSpec

    monkeypatch.chdir(tmp_path)
    new_weights = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / new_weights).write_bytes(b"new")

    spec = EvalJobSpec(
        new_weights_path=new_weights,
        old_weights_path=None,
        samples=1, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=0,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="macbook", n_games=4, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    calls = _drive_run_shard_eval_remote(
        monkeypatch, shard, spec, tmp_path=tmp_path,
    )
    for c in calls:
        if c[0] == "scp":
            assert not any(p.endswith(".json.gz") for p in c), c


def test_replay_collection_handles_empty_listing(monkeypatch, tmp_path):
    """If the remote shard captured zero replays (typical for eval
    with low capture-every and few games), the listing returns no
    files. The orchestrator must not raise, must not create the
    local subdir, and must not issue any scp commands for replays.
    """
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=10,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    calls = _drive_run_shard_remote(
        monkeypatch, shard, spec, tmp_path=tmp_path,
    )
    run_id_full = "iter_002_self_play_v7_shard_macbook"
    listing_marker = f"ls replays/{run_id_full}/*.json.gz"
    ls_calls = [
        c for c in calls
        if c[0] == "ssh" and listing_marker in c[-1]
    ]
    assert len(ls_calls) == 1
    for c in calls:
        if c[0] == "scp":
            assert not any(p.endswith(".json.gz") for p in c), c
    assert not (tmp_path / "replays" / run_id_full).exists()
