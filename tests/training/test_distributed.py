"""Tests for ``mtg_bot.training.distributed`` schema + loader.

The orchestrator's runtime behavior (SSH dispatch, scp result
collection) lives behind a network and is tested manually with the
real remotes. These tests pin the static config layer.
"""

from __future__ import annotations

import json
import time
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
                    state["queues"][run_id] = {
                        "next": 0, "total": total, "closed": False,
                    }
                self._reply(200, {"ok": True})
            elif self.path == "/queue/take":
                run_id = data["run_id"]
                bs = int(data.get("batch_size", 25))
                with state["lock"]:
                    q = state["queues"].get(run_id)
                    if q is None:
                        self._reply(404, {"error": "unknown run_id"})
                        return
                    if q.get("closed"):
                        self._reply(200, {
                            "games": [], "remaining": 0, "closed": True,
                        })
                        return
                    start = q["next"]
                    end = min(start + bs, q["total"])
                    q["next"] = end
                    remaining = q["total"] - end
                self._reply(200, {
                    "games": list(range(start, end)),
                    "remaining": remaining,
                })
            elif self.path.startswith("/queue/close/"):
                run_id = self.path[len("/queue/close/"):]
                with state["lock"]:
                    q = state["queues"].get(run_id)
                    if q is None:
                        self._reply(404, {"error": "unknown run_id"})
                        return
                    q["closed"] = True
                self._reply(200, {"ok": True, "closed": True})
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


def test_run_distributed_self_play_with_slack_initializes_overqueue(
    tmp_path: Path,
):
    """slack_extra=2 with target=4 should size the queue at 6.
    With 4 actual games' worth of work (2 games per shard,
    n_workers=1), the queue server's /queue/take handlers will
    drain only 4 idxes before the early-stop poller closes the
    queue. The slack indices (4, 5) are abandoned."""
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
            run_id_prefix="iter_overq_self_play",
            total_games=4,
            queue_url=queue_url,
            slack_extra=2,
        )
    finally:
        server.shutdown()
    # Run completes without hanging. Number of completed games is
    # at most the queue size; with the early-stop poller closing
    # at 4 successful, we expect ≤ 6 npzs and ≥ 4.
    assert 4 <= len(paths) <= 6
    assert all(p.is_file() for p in paths)


def test_run_distributed_eval_with_slack_initializes_overqueue(
    tmp_path: Path,
):
    """Eval-side counterpart: slack_extra raises the queue cap; the
    early-stop poller closes once target_games successful results
    are in. The aggregate counts should reflect at-least-target
    games (slack may or may not have started before close)."""
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
            run_id_prefix="iter_overq_eval",
            total_games=4,
            queue_url=queue_url,
            slack_extra=2,
        )
    finally:
        server.shutdown()
    # Run completes without hanging; counts are at least the target.
    assert counts["n_games"] >= 4
    assert counts["n_games"] <= 6


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
    from mtg_bot.search.heuristics_config import HeuristicsConfig
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
        heuristics=HeuristicsConfig(
            phase_prune_enabled=True,
            force_landdrop_enabled=False,
            skip_empty_combat_enabled=True,
            skip_opp_postcombat_main_enabled=False,
            skip_dead_main1_enabled=True,
        ),
    )
    rt = SelfPlayJobSpec.from_dict(original.to_dict())
    assert rt == original
    assert rt.heuristics == original.heuristics


def test_self_play_spec_default_heuristics_all_true():
    """Self-play default for the ``heuristics`` field = every flag
    True. Documented as the production default in ``HeuristicsConfig``
    and pinned here against accidental flips."""
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.training.distributed import SelfPlayJobSpec

    spec = SelfPlayJobSpec(
        weights_path="w.pt", samples=1, inner_nodes=1, hidden_sizes=None,
        base_seed=0, enable_mulligans=False, per_game_timeout_sec=None,
    )
    assert spec.heuristics == HeuristicsConfig()


def test_self_play_spec_from_dict_missing_heuristics_defaults_to_all_true():
    """Older payloads written before the heuristics field existed
    must round-trip into the production self-play default."""
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.training.distributed import SelfPlayJobSpec

    rebuilt = SelfPlayJobSpec.from_dict({
        "weights_path": "w.pt",
        "samples": 1,
        "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "enable_mulligans": False,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.heuristics == HeuristicsConfig()


def test_eval_spec_default_heuristics_all_false():
    """Eval default = ``HeuristicsConfig.disabled()`` (every flag
    OFF). Pin: match outcomes are load-bearing for acceptance gates."""
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.training.distributed import EvalJobSpec

    spec = EvalJobSpec(
        new_weights_path="new.pt", old_weights_path=None,
        samples=1, inner_nodes=1, hidden_sizes=None,
        base_seed=0, enable_mulligans=False, per_game_timeout_sec=None,
    )
    assert spec.heuristics == HeuristicsConfig.disabled()


def test_eval_spec_round_trips_heuristics():
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.training.distributed import EvalJobSpec

    original = EvalJobSpec(
        new_weights_path="new.pt", old_weights_path="old.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=300.0,
        heuristics=HeuristicsConfig(
            phase_prune_enabled=True,
            force_landdrop_enabled=True,
            skip_empty_combat_enabled=False,
            skip_opp_postcombat_main_enabled=False,
            skip_dead_main1_enabled=True,
        ),
    )
    rt = EvalJobSpec.from_dict(original.to_dict())
    assert rt == original
    assert rt.heuristics == original.heuristics


def test_eval_spec_from_dict_missing_heuristics_defaults_to_all_false():
    """Older payloads → eval default (every flag OFF)."""
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.training.distributed import EvalJobSpec

    rebuilt = EvalJobSpec.from_dict({
        "new_weights_path": "new.pt",
        "old_weights_path": None,
        "samples": 1,
        "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "enable_mulligans": False,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.heuristics == HeuristicsConfig.disabled()


def test_self_play_spec_architecture_round_trips():
    """The architecture + policy_hidden_sizes fields survive the JSON
    round-trip the SSH wrapper relies on so remote shards instantiate
    the matching dual-head class."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    original = SelfPlayJobSpec(
        weights_path="w.pt", samples=4, inner_nodes=200,
        hidden_sizes=(128, 128, 64),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        architecture="separate",
        policy_hidden_sizes=(64, 32),
    )
    rt = SelfPlayJobSpec.from_dict(original.to_dict())
    assert rt.architecture == "separate"
    assert rt.policy_hidden_sizes == (64, 32)


def test_self_play_spec_architecture_default_is_none():
    """Older payloads without architecture decode cleanly with
    ``architecture=None`` (NNEvaluator's default = "shared")."""
    from mtg_bot.training.distributed import SelfPlayJobSpec

    rebuilt = SelfPlayJobSpec.from_dict({
        "weights_path": "w.pt",
        "samples": 1, "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "enable_mulligans": False,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.architecture is None
    assert rebuilt.policy_hidden_sizes is None


def test_eval_spec_architecture_round_trips():
    """``new_architecture`` / ``old_architecture`` / ``policy_hidden_
    sizes`` round-trip cleanly so the eval-shard worker can instantiate
    the right class for each side of the match."""
    from mtg_bot.training.distributed import EvalJobSpec

    original = EvalJobSpec(
        new_weights_path="new.pt", old_weights_path="old.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42, enable_mulligans=False,
        per_game_timeout_sec=300.0,
        new_architecture="separate",
        old_architecture="shared",
        policy_hidden_sizes=(48, 24),
    )
    rt = EvalJobSpec.from_dict(original.to_dict())
    assert rt.new_architecture == "separate"
    assert rt.old_architecture == "shared"
    assert rt.policy_hidden_sizes == (48, 24)


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


def test_weight_push_failure_returns_failure_report(monkeypatch, tmp_path):
    """If the scp weight-push fails (non-zero exit), the per-shard
    runner must NOT raise — it returns a ``ShardSelfPlayReport`` with
    ``success=False`` and an ``error_stage`` of ``"weight_push"``.
    This is the resilience contract: one shard's SSH/SCP glitch can't
    kill the master; the orchestrator aggregates whatever sibling
    shards produced and continues. The failure is loud (printed to
    stderr) and surfaces in the report's ``error`` field — not
    silent."""
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import (
        ShardSelfPlayReport,
        SelfPlayJobSpec,
    )

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake-weights")

    class _Boom:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            if cmd[0] == "scp" and any(
                p.endswith("weights.pt") for p in cmd
            ):
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
    report = dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_002",
        iter_total_games=10,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_002",
        stamp="20260503T230000Z",
    )
    assert isinstance(report, ShardSelfPlayReport)
    assert report.success is False
    assert report.error_stage == "weight_push"
    assert "permission denied" in (report.error or "") or (
        "CalledProcessError" in (report.error or "")
    )
    assert report.npz_paths == []
    # Per-shard progress JSON marked failed so the UI sees it.
    progress_json = (
        tmp_path / "training_progress"
        / "iter_002_shard_macbook.json"
    )
    assert progress_json.is_file()
    payload = json.loads(progress_json.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "weight_push" in payload.get("error_note", "")


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
    # Shards above didn't set timed_out; aggregator must treat the
    # missing key as zero rather than crashing.
    assert agg["timed_out"] == 0
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


def test_aggregate_progress_poller_sums_timed_out_across_shards(
    tmp_path: Path,
):
    """Per-shard ``timed_out`` counts must roll up into the
    cluster-wide aggregate alongside ``crashed``. Pin both data_gen
    and eval shapes — the field flows through ``_SUM_FIELDS`` so the
    UI can render distinct "crashed" / "timed out" stats on the
    rolled-up card and on each per-machine sub-row."""
    from mtg_bot.training.distributed import _AggregateProgressPoller

    pdir = tmp_path
    run_id = "iter_011_self_play_v11"
    for label, done, samples, p0, p1, dr, cr, to_, nw in (
        ("local", 30, 4500, 12, 8, 10, 0, 1, 16),
        ("mac", 50, 7200, 25, 20, 5, 1, 2, 14),
        ("win", 5, 600, 2, 2, 1, 0, 0, 4),
    ):
        (pdir / f"{run_id}_shard_{label}.json").write_text(
            json.dumps({
                "run_id": f"{run_id}_shard_{label}",
                "kind": "data_gen",
                "status": "running",
                "n_games_total": 200, "n_games_done": done,
                "n_samples": samples, "n_workers": nw,
                "p0_wins": p0, "p1_wins": p1, "draws": dr,
                "crashed": cr, "timed_out": to_,
                "elapsed_seconds": 100.0,
            }), encoding="utf-8",
        )
    poller = _AggregateProgressPoller(
        progress_dir=pdir, run_id=run_id,
        n_games_total=200, kind="data_gen",
    )
    poller._write("running")
    agg = json.loads((pdir / f"{run_id}.json").read_text())
    # Run-level totals: crashed and timed_out flow as separate
    # cluster-wide counters.
    assert agg["crashed"] == 1
    assert agg["timed_out"] == 3
    # Per-machine sub-row entries also carry both — that's what
    # the UI's renderMachines reads.
    by_label = {m["label"]: m for m in agg["machines"]}
    assert by_label["local"]["crashed"] == 0
    assert by_label["local"]["timed_out"] == 1
    assert by_label["mac"]["crashed"] == 1
    assert by_label["mac"]["timed_out"] == 2
    assert by_label["win"]["crashed"] == 0
    assert by_label["win"]["timed_out"] == 0


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


# ---- _EarlyStopPoller ------------------------------------------


def _write_shard_progress(
    progress_dir: Path,
    run_id: str,
    label: str,
    *,
    n_games_done: int,
    crashed: int = 0,
    timed_out: int = 0,
) -> None:
    """Test helper: emit a per-shard progress JSON in the layout the
    aggregate poller and the early-stop poller both consume."""
    payload = {
        "run_id": run_id,
        "n_games_done": n_games_done,
        "crashed": crashed,
        "timed_out": timed_out,
    }
    (progress_dir / f"{run_id}_shard_{label}.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )


def test_early_stop_poller_closes_queue_when_threshold_hit(tmp_path: Path):
    """500 successful completions in the per-shard JSONs → exactly
    one POST to /queue/close/<run_id>. "Successful" =
    n_games_done - crashed - timed_out. Crashed and timed_out games
    DON'T count toward the target — those are abandoned slack."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    # Two shards, total successful = 480 + 20 = 500.
    _write_shard_progress(
        progress_dir, "r", "A", n_games_done=300, crashed=2, timed_out=1,
    )
    _write_shard_progress(
        progress_dir, "r", "B", n_games_done=203,
    )
    # Successful = (300-2-1) + 203 = 500 — should trip immediately.
    posted: list[str] = []

    class FakeResp:
        status = 200

    def fake_urlopen(req):
        posted.append(req.full_url)
        return FakeResp()

    poller = _EarlyStopPoller(
        progress_dir=progress_dir,
        run_id="r",
        target_games=500,
        queue_url="http://master:5099",
        interval_s=0.05,
        urlopen=fake_urlopen,
    )
    poller.start()
    # Let the first tick fire — first iter is no-wait so a brief
    # join is enough.
    if poller._thread is not None:
        poller._thread.join(timeout=2.0)
    poller.stop()
    assert posted == ["http://master:5099/queue/close/r"]
    assert poller.closed is True


def test_early_stop_poller_does_not_close_below_threshold(tmp_path: Path):
    """499 successful (one short) → no POST. Run completes via the
    queue draining naturally."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_shard_progress(progress_dir, "r", "A", n_games_done=499)
    posted: list[str] = []

    poller = _EarlyStopPoller(
        progress_dir=progress_dir,
        run_id="r",
        target_games=500,
        queue_url="http://master:5099",
        interval_s=0.05,
        urlopen=lambda req: posted.append(req.full_url),
    )
    poller.start()
    time.sleep(0.3)  # several ticks
    poller.stop()
    assert posted == []
    assert poller.closed is False


def test_early_stop_poller_subtracts_crashed_and_timed_out(tmp_path: Path):
    """505 raw n_games_done but 6 crashes + 4 timeouts → 495
    successful → no close. The whole point of the design is that
    timed_out / crashed games don't count toward the target."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_shard_progress(
        progress_dir, "r", "A",
        n_games_done=505, crashed=6, timed_out=4,
    )
    posted: list[str] = []

    poller = _EarlyStopPoller(
        progress_dir=progress_dir,
        run_id="r",
        target_games=500,
        queue_url="http://master:5099",
        interval_s=0.05,
        urlopen=lambda req: posted.append(req.full_url),
    )
    poller.start()
    time.sleep(0.3)
    poller.stop()
    assert posted == []


def test_early_stop_poller_closes_only_once(tmp_path: Path):
    """After the threshold trips and the close POST succeeds, the
    poller exits. Subsequent ticks don't re-POST."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_shard_progress(progress_dir, "r", "A", n_games_done=500)

    class FakeResp:
        status = 200

    posted: list[str] = []

    def fake_urlopen(req):
        posted.append(req.full_url)
        return FakeResp()

    poller = _EarlyStopPoller(
        progress_dir=progress_dir, run_id="r",
        target_games=500, queue_url="http://m:5099",
        interval_s=0.02, urlopen=fake_urlopen,
    )
    poller.start()
    # Even after several ticks would have fired, only one POST.
    time.sleep(0.3)
    poller.stop()
    assert len(posted) == 1


def test_early_stop_poller_skips_eval_result_files(tmp_path: Path):
    """Eval shards write a sibling ``..._shard_<label>_result.json``
    with the same wins/draws counts. Including it would double-count.
    Mirrors _AggregateProgressPoller's filter."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_shard_progress(progress_dir, "r", "A", n_games_done=300)
    # Result file mirrors A's count — must be ignored.
    (progress_dir / "r_shard_A_result.json").write_text(
        json.dumps({"n_games_done": 300, "crashed": 0, "timed_out": 0}),
        encoding="utf-8",
    )
    posted: list[str] = []

    poller = _EarlyStopPoller(
        progress_dir=progress_dir, run_id="r",
        target_games=500, queue_url="http://m:5099",
        interval_s=0.02, urlopen=lambda req: posted.append(req.full_url),
    )
    poller.start()
    time.sleep(0.2)
    poller.stop()
    # 300 < 500, so no close (would be 600 if result file
    # double-counted).
    assert posted == []


def test_early_stop_poller_handles_unreadable_shard_files(tmp_path: Path):
    """A partially-written progress JSON (mid-atomic-write) must not
    crash the poller — skip and try again next tick."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    # Half-written JSON — JSONDecodeError on read.
    (progress_dir / "r_shard_BAD.json").write_text(
        "{not json", encoding="utf-8",
    )
    _write_shard_progress(progress_dir, "r", "OK", n_games_done=500)

    class FakeResp:
        status = 200

    posted: list[str] = []

    def fake_urlopen(req):
        posted.append(req.full_url)
        return FakeResp()

    poller = _EarlyStopPoller(
        progress_dir=progress_dir, run_id="r",
        target_games=500, queue_url="http://m:5099",
        interval_s=0.02, urlopen=fake_urlopen,
    )
    poller.start()
    time.sleep(0.2)
    poller.stop()
    assert len(posted) == 1


def test_early_stop_poller_close_post_failure_logs_and_gives_up(
    tmp_path: Path, capsys,
):
    """If the close POST raises, the poller logs to stderr and stops
    trying — the queue will drain on its own once slack indices run
    out, just slower. Don't make the orchestrator hang waiting for a
    well-meaning POST."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_shard_progress(progress_dir, "r", "A", n_games_done=500)

    def boom(req):
        raise ConnectionError("master unreachable")

    poller = _EarlyStopPoller(
        progress_dir=progress_dir, run_id="r",
        target_games=500, queue_url="http://m:5099",
        interval_s=0.02, urlopen=boom,
    )
    poller.start()
    time.sleep(0.2)
    poller.stop()
    # Failure path is logged, not raised. Run keeps going on slack.
    assert poller.closed is False
    err = capsys.readouterr().err
    assert "early-stop" in err


def test_early_stop_poller_close_non_2xx_logs_and_gives_up(
    tmp_path: Path, capsys,
):
    """A 4xx/5xx response from the close endpoint is treated the
    same as a network failure: log + give up. We don't want to spin
    on /queue/close calls that the master is rejecting."""
    from mtg_bot.training.distributed import _EarlyStopPoller

    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_shard_progress(progress_dir, "r", "A", n_games_done=500)

    class FakeResp:
        status = 500

    poller = _EarlyStopPoller(
        progress_dir=progress_dir, run_id="r",
        target_games=500, queue_url="http://m:5099",
        interval_s=0.02, urlopen=lambda req: FakeResp(),
    )
    poller.start()
    time.sleep(0.2)
    poller.stop()
    assert poller.closed is False
    err = capsys.readouterr().err
    assert "HTTP 500" in err or "early-stop" in err


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


# ---- ProcessPoolExecutor cleanup must not block on hung workers ----
#
# Regression: 2026-05-05 a distributed iter_002 self-play hung at
# shard cleanup time when 3 Mac games hit the 300s per-game timeout.
# The shard's `with _cf.ProcessPoolExecutor(...) as exe:` __exit__
# calls shutdown(wait=True), which waits forever on workers stuck in
# C-extension code (the timeout abandons the daemon thread but
# can't kill the underlying process call). The fix is to drop the
# ``with`` and call ``exe.shutdown(wait=False)`` in a finally block.
# This test pins the primitive behavior we depend on AND checks the
# source for the failure-mode-prone pattern.

def test_processpool_shutdown_wait_false_returns_promptly_with_hung_future(
):
    """`ProcessPoolExecutor.shutdown(wait=False)` must return promptly
    even when a submitted future is still running. This is the
    primitive `run_shard_pull` and the eval shard rely on to avoid
    hanging when a per-game timeout abandons the worker thread."""
    import concurrent.futures as _cf
    import time as _time

    def _hang_briefly():
        _time.sleep(10.0)

    exe = _cf.ProcessPoolExecutor(max_workers=2)
    try:
        fut = exe.submit(_hang_briefly)
        # Don't wait for it — it would take 10s.
        t0 = _time.perf_counter()
        exe.shutdown(wait=False)
        elapsed = _time.perf_counter() - t0
        # shutdown(wait=False) returns immediately. With wait=True it
        # would block for the full sleep duration.
        assert elapsed < 2.0, (
            f"shutdown(wait=False) returned in {elapsed:.2f}s; "
            "expected <2s. The 10s sleep should NOT have been waited "
            "for. If this fails the worker mode regressed."
        )
        assert not fut.cancelled()
    finally:
        # If shutdown didn't actually clean up, this would also stall.
        # But asserting elapsed < 2s above is the real check.
        del exe


def test_distributed_does_not_use_with_processpoolexecutor_pattern():
    """``with _cf.ProcessPoolExecutor(...) as exe:`` is a hang trap
    when a worker is stuck in C-extension code — the ``__exit__``
    calls shutdown(wait=True) which never returns. The source of
    distributed.py must NOT contain this pattern; instead it should
    create the executor explicitly and call shutdown(wait=False) in
    a finally block.

    Hard-coded text check rather than a behavior test because the
    behavior test requires standing up a fake shard with a hung
    worker, which is heavy. This is a fast static guard."""
    import inspect
    import mtg_bot.training.distributed as dmod
    src = inspect.getsource(dmod)
    assert "with _cf.ProcessPoolExecutor" not in src, (
        "distributed.py uses `with ProcessPoolExecutor(...) as exe:`. "
        "That pattern hangs forever on workers stuck in C-extension "
        "code past the per-game timeout. Use explicit creation + "
        "`exe.shutdown(wait=False)` in a finally block instead."
    )
    assert "exe.shutdown(wait=False)" in src, (
        "distributed.py should call `exe.shutdown(wait=False)` to "
        "avoid the hang on per-game timeout."
    )


# ---- queue HTTP tight-timeout + bounded retries ------------------
#
# Regression: 2026-05-04 a Mac shard lost the iter_002 self-play run
# at 15:01 UTC with `URLError(TimeoutError(60, 'Operation timed
# out'))` — an OS-level ETIMEDOUT (errno 60 on macOS) on the TCP
# connect to /queue/take. The OS-default 60s connect-timeout fired
# before urllib's `timeout=30` even applied. A momentary Tailscale
# blip should not kill a 30-60-minute shard. The fix: tight per-
# attempt timeout + a small bounded number of retries with
# exponential backoff.

def test_urlopen_with_retry_returns_on_first_success():
    """Happy path: helper returns immediately on the first successful
    urlopen and never sleeps."""
    import io
    from unittest.mock import patch

    from mtg_bot.training.distributed import _urlopen_with_retry

    class _FakeResp:
        status = 200

        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    sleeps: list[float] = []
    calls: list[float] = []

    def _fake_urlopen(req, timeout):
        calls.append(timeout)
        return _FakeResp(b'{"ok": true}')

    with patch(
        "urllib.request.urlopen", side_effect=_fake_urlopen,
    ):
        resp = _urlopen_with_retry(
            "ignored", sleep=lambda s: sleeps.append(s),
        )
    assert resp.status == 200
    assert resp.body == b'{"ok": true}'
    # Exactly one urlopen call, no sleep on the happy path.
    assert len(calls) == 1
    assert sleeps == []


def test_urlopen_with_retry_retries_then_succeeds():
    """The Mac-shard regression scenario: first 1-2 attempts fail
    with URLError(TimeoutError()), the third succeeds. Helper must
    return the success response and have slept exactly twice with
    the expected exponential-backoff pattern."""
    import urllib.error
    from unittest.mock import patch

    from mtg_bot.training.distributed import _urlopen_with_retry

    class _FakeResp:
        status = 200

        def read(self) -> bytes:
            return b"recovered"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    attempts = {"n": 0}
    sleeps: list[float] = []

    def _flaky_urlopen(req, timeout):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise urllib.error.URLError(
                TimeoutError(60, "Operation timed out"),
            )
        return _FakeResp()

    with patch(
        "urllib.request.urlopen", side_effect=_flaky_urlopen,
    ):
        resp = _urlopen_with_retry(
            "ignored",
            backoff_base=0.5,
            sleep=lambda s: sleeps.append(s),
        )
    assert resp.status == 200
    assert resp.body == b"recovered"
    assert attempts["n"] == 3
    # Exponential backoff: 0.5 * 2**0 = 0.5, 0.5 * 2**1 = 1.0.
    assert sleeps == [0.5, 1.0]


def test_urlopen_with_retry_reraises_after_all_attempts_fail():
    """If every attempt fails, the helper re-raises the last
    exception so the caller sees the real failure mode (URLError /
    TimeoutError / ConnectionError) — only transient blips are
    absorbed silently."""
    import urllib.error
    from unittest.mock import patch

    from mtg_bot.training.distributed import _urlopen_with_retry

    sleeps: list[float] = []
    calls = {"n": 0}

    def _always_fail(req, timeout):
        calls["n"] += 1
        raise urllib.error.URLError(TimeoutError(60, "ETIMEDOUT"))

    with patch(
        "urllib.request.urlopen", side_effect=_always_fail,
    ):
        with pytest.raises(urllib.error.URLError):
            _urlopen_with_retry(
                "ignored",
                retries=3,
                backoff_base=0.5,
                sleep=lambda s: sleeps.append(s),
            )
    # All 3 attempts ran; we slept BETWEEN attempts (so 2 sleeps
    # total) but did NOT sleep after the final failing attempt.
    assert calls["n"] == 3
    assert sleeps == [0.5, 1.0]


def test_urlopen_with_retry_retries_on_connection_error():
    """ConnectionError (from the OS-level connect failure path) is
    one of the transient blips we want to retry, alongside URLError
    and bare TimeoutError."""
    from unittest.mock import patch

    from mtg_bot.training.distributed import _urlopen_with_retry

    class _FakeResp:
        status = 200

        def read(self) -> bytes:
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    attempts = {"n": 0}

    def _connect_then_succeed(req, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("boom")
        return _FakeResp()

    with patch(
        "urllib.request.urlopen", side_effect=_connect_then_succeed,
    ):
        resp = _urlopen_with_retry(
            "ignored", sleep=lambda s: None,
        )
    assert resp.status == 200
    assert attempts["n"] == 2


def test_urlopen_with_retry_constants_are_tight_for_tailscale():
    """The whole point of this helper is that the cluster's local
    Tailscale RTT is 6-65ms. A 10s per-attempt timeout is already
    150x typical RTT; anything bigger leaves us re-exposed to the
    OS-default 60s connect-timeout that bit us in iter_002. Pin the
    constants so a future drive-by tweak is loud."""
    from mtg_bot.training import distributed as dmod

    assert dmod._QUEUE_HTTP_ATTEMPT_TIMEOUT_S <= 15.0, (
        "Per-attempt timeout grew above 15s. Tailscale RTT is 6-65ms; "
        "a single attempt should never need that long. If it does, "
        "the network is broken and we should fail fast and retry."
    )
    assert 2 <= dmod._QUEUE_HTTP_RETRIES <= 5, (
        "Retry count outside 2-5: too few and a single blip kills "
        "the shard; too many and a real outage takes minutes to "
        "surface."
    )
    assert dmod._QUEUE_HTTP_BACKOFF_BASE_S <= 1.0, (
        "Backoff base grew above 1s — total worst-case wall would "
        "exceed the 60s OS-default that we're trying to undercut."
    )


def test_urlopen_with_retry_total_wall_bound():
    """The helper's total worst-case wall-clock (sum of per-attempt
    timeouts + sum of inter-attempt backoffs) must stay below the
    60s OS-default TCP-connect ETIMEDOUT that bit us in iter_002.
    This is the headline guarantee of the whole feature."""
    from mtg_bot.training import distributed as dmod

    timeout_budget = (
        dmod._QUEUE_HTTP_ATTEMPT_TIMEOUT_S * dmod._QUEUE_HTTP_RETRIES
    )
    backoff_budget = sum(
        dmod._QUEUE_HTTP_BACKOFF_BASE_S * (2 ** i)
        for i in range(dmod._QUEUE_HTTP_RETRIES - 1)
    )
    total = timeout_budget + backoff_budget
    assert total < 60.0, (
        f"Worst-case retry wall is {total:.1f}s, which is at or "
        "above the 60s OS-default connect-timeout that we're "
        "trying to undercut. Tighten the constants."
    )


# ---- SSH/SCP keepalive guard ---------------------------------------
#
# Regression: 2026-05-05 master's SSH to Mac wedged for 90+ min after
# Mac dropped off Tailscale briefly mid-iteration; the OS-level
# keepalive timeout is hours, so the orchestrator stalled even though
# Mac's python process had finished. Fix: every ssh / scp invocation
# carries -o ServerAliveInterval=30 -o ServerAliveCountMax=5 so ssh
# itself notices a dead socket in ~150s.

def test_ssh_cmd_carries_serveralive_options():
    """Every shard ssh invocation must opt in to TCP keepalive."""
    from mtg_bot.training.distributed import (
        ShardConfig, _ssh_cmd,
    )
    shard = ShardConfig(
        host="my-mac", n_games=10, user="g",
        repo_path="/r", venv_python=".venv/bin/python",
    )
    cmd = _ssh_cmd(shard, "echo ok")
    # Pairs come back-to-back: ('-o', 'ServerAliveInterval=30').
    pairs = [(cmd[i], cmd[i + 1]) for i in range(len(cmd) - 1)]
    assert ("-o", "ServerAliveInterval=30") in pairs, (
        f"missing ServerAliveInterval in {cmd!r}"
    )
    assert ("-o", "ServerAliveCountMax=5") in pairs, (
        f"missing ServerAliveCountMax in {cmd!r}"
    )


def test_scp_cmd_carries_serveralive_options_both_directions():
    """Both pull (from_remote=True) and push (False) carry keepalive."""
    from mtg_bot.training.distributed import (
        ShardConfig, _scp_cmd,
    )
    shard = ShardConfig(
        host="my-mac", n_games=10, user="g",
        repo_path="/r", venv_python=".venv/bin/python",
    )
    pull = _scp_cmd(shard, "/remote/x", "local/x", from_remote=True)
    push = _scp_cmd(shard, "local/x", "/remote/x", from_remote=False)
    for cmd, label in ((pull, "pull"), (push, "push")):
        pairs = [(cmd[i], cmd[i + 1]) for i in range(len(cmd) - 1)]
        assert ("-o", "ServerAliveInterval=30") in pairs, (
            f"{label} missing ServerAliveInterval: {cmd!r}"
        )
        assert ("-o", "ServerAliveCountMax=5") in pairs, (
            f"{label} missing ServerAliveCountMax: {cmd!r}"
        )


# ---- Per-shard SSH resilience -----------------------------------
#
# Today (2026-05-05) we hit a recurring failure where a Tailscale
# blip / lingering ssh.exe / remote python crash made one shard's
# ``_run_subprocess`` raise CalledProcessError. The exception
# propagated up through the master and killed the iter, throwing
# away other shards' completed work. The tests below pin the new
# resilience contract:
#
# 1. Per-shard SSH/SCP failures are caught inside the runner, not
#    raised. The runner returns a ShardSelfPlayReport / ShardEvalReport
#    with success=False.
# 2. Even on failure, the post-shard rsync stages still run — partial
#    data on disk gets recovered.
# 3. The orchestrator continues to other shards and aggregates
#    whatever data it gets.
# 4. Only when ALL shards fail and ZERO npzs are recovered does the
#    orchestrator raise.


def test_run_shard_remote_ssh_run_failure_returns_failure_report(
    monkeypatch, tmp_path,
):
    """The self-play SSH run command raises CalledProcessError (the
    most common failure mode on the cluster: Tailscale glitch, remote
    python crash, manual kill of ssh.exe). The runner catches it,
    logs loudly to stderr, marks the per-shard progress JSON failed,
    and returns a failure report. It does NOT propagate the
    exception."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import (
        ShardSelfPlayReport, SelfPlayJobSpec,
    )

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    class _FailOnSelfPlay:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            if (cmd[0] == "ssh"
                    and "run_self_play_shard.py" in cmd[-1]):
                raise subprocess.CalledProcessError(
                    255, cmd, output="",
                    stderr="ssh: connection closed",
                )

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

    rec = _FailOnSelfPlay()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

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
    report = dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_002",
        iter_total_games=10,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_002",
        stamp="20260503T230000Z",
    )
    assert isinstance(report, ShardSelfPlayReport)
    assert report.success is False
    assert report.error_stage == "self_play"
    assert "ssh" in (report.error or "").lower() or (
        "CalledProcessError" in (report.error or "")
    )
    # Post-failure rsync stages still ran:
    classes = []
    for c in rec.calls:
        if c[0] == "scp":
            # Find the user@host:path arg; for from_remote=True it's
            # the second-to-last positional (followed by local dest).
            remote_arg = next(
                (a for a in c if "@" in a and ":" in a), None,
            )
            if remote_arg is not None:
                rhs = remote_arg.split(":", 1)[1]
                if rhs.endswith(".json"):
                    classes.append("progress_pull")
                elif rhs.endswith(".jsonl"):
                    classes.append("events_pull")
        if c[0] == "ssh" and (
            "iterate_data" in c[-1]
            and ("ls " in c[-1] or "dir /b" in c[-1])
        ):
            classes.append("list_npzs")
    assert "progress_pull" in classes, (
        "expected progress JSON rsync attempt after SSH failure"
    )
    assert "events_pull" in classes, (
        "expected events JSONL rsync attempt after SSH failure"
    )
    assert "list_npzs" in classes, (
        "expected npz listing attempt after SSH failure (the data "
        "may still be on the remote disk after the wrapper died)"
    )

    # Per-shard progress JSON marked failed.
    progress_json = (
        tmp_path / "training_progress" / "iter_002_shard_macbook.json"
    )
    assert progress_json.is_file()
    payload = json.loads(progress_json.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "self_play" in payload.get("error_note", "")


def test_run_shard_remote_recovers_npzs_after_ssh_failure(
    monkeypatch, tmp_path,
):
    """Real-world case from 2026-05-05: Mac shard ran 329 games and
    wrote 24 npzs, then ssh.exe lingered and we manually killed it.
    The data was on disk; the orchestrator should pull it back. This
    test pins that behavior with a scripted listing."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    listing_payload = (
        "iter_002_shard_macbook_chunk_0001_20260503T230000Z.npz\n"
        "iter_002_shard_macbook_chunk_0002_20260503T230000Z.npz\n"
    )

    class _FailMidPlayWithRecoverableNpzs:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            tail = cmd[-1] if cmd else ""
            stdout = ""
            if cmd[0] == "ssh":
                if "run_self_play_shard.py" in tail:
                    raise subprocess.CalledProcessError(
                        255, cmd, output="", stderr="killed",
                    )
                if "iterate_data" in tail and (
                    "ls " in tail or "dir /b" in tail
                ):
                    stdout = listing_payload

            class _Result:
                returncode = 0
                stderr = ""
                def __init__(self_, _stdout):
                    self_.stdout = _stdout
            return _Result(stdout)

    rec = _FailMidPlayWithRecoverableNpzs()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

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
        host="macbook", n_games=329, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_002",
        iter_total_games=329,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_002",
        stamp="20260503T230000Z",
    )
    # Failure report — but with the 2 npzs recovered.
    assert report.success is False
    assert report.error_stage == "self_play"
    assert len(report.npz_paths) == 2, (
        f"expected 2 npzs recovered, got {report.npz_paths}"
    )


def test_run_shard_eval_remote_ssh_failure_returns_failure_report(
    monkeypatch, tmp_path,
):
    """Eval-side mirror: an SSH run failure on the eval shard
    returns a ShardEvalReport with success=False and zero counts
    rather than raising."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import (
        ShardEvalReport, EvalJobSpec,
    )

    monkeypatch.chdir(tmp_path)
    new_weights = "trained_weights/v7/weights.pt"
    old_weights = "trained_weights/v6/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / "trained_weights" / "v6").mkdir(parents=True)
    (tmp_path / new_weights).write_bytes(b"new")
    (tmp_path / old_weights).write_bytes(b"old")

    class _FailOnEval:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            if (cmd[0] == "ssh"
                    and "run_self_play_shard.py" in cmd[-1]
                    and "--mode=eval" in cmd[-1]):
                raise subprocess.CalledProcessError(
                    255, cmd, output="",
                    stderr="ssh: tailscale unreachable",
                )

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

    rec = _FailOnEval()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = EvalJobSpec(
        new_weights_path=new_weights,
        old_weights_path=old_weights,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        opponent_label="v6",
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_eval_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_002_eval_v7",
        iter_total_games=10,
        progress_dir=tmp_path / "training_progress",
        stamp="20260503T230000Z",
    )
    assert isinstance(report, ShardEvalReport)
    assert report.success is False
    assert report.error_stage in ("eval", "no_result_file")
    assert report.counts == {
        "n_games": 0, "wins_new": 0, "wins_old": 0,
        "draws": 0, "crashed": 0,
    }


def test_run_distributed_self_play_one_local_shard_fails(
    monkeypatch, tmp_path,
):
    """Integration smoke: three local shards, one fails. The
    orchestrator must complete with the other two shards' npzs and
    not raise. The failed shard's per-shard progress JSON is marked
    ``status=failed``; the aggregator's status is ``failed`` (any
    failed shard taints the iter for monitoring) but the npz list
    is non-empty."""
    from mtg_bot.training import distributed as dist
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
        ShardConfig(host="local", n_games=2, label="BOOM", n_workers=1,
                    seed_offset=2_000_000),
    ))

    # Patch ``run_shard_pull`` so the BOOM shard raises but the
    # other two delegate to the real implementation.
    real_run_shard_pull = dist.run_shard_pull

    def _selective_pull(*args, **kwargs):
        if kwargs.get("label") == "BOOM":
            raise RuntimeError("simulated local shard crash")
        return real_run_shard_pull(*args, **kwargs)

    monkeypatch.setattr(dist, "run_shard_pull", _selective_pull)

    queue_url, server = _start_queue_server()
    try:
        paths = run_distributed_self_play(
            cfg, spec,
            progress_dir=progress_dir,
            output_dir=out_dir,
            run_id_prefix="iter_resilience",
            total_games=4,
            queue_url=queue_url,
        )
    finally:
        server.shutdown()

    # Two surviving shards drained the 4-game queue between them.
    assert len(paths) == 4, (
        f"expected 4 npzs from the two surviving shards, got "
        f"{[p.name for p in paths]}"
    )
    assert all(p.is_file() for p in paths)
    # No npz file ended up tagged with the BOOM shard.
    assert not any("shard_BOOM" in p.name for p in paths), (
        f"BOOM shard should have produced no npzs, got {paths}"
    )

    # Failed shard's per-shard progress JSON marked failed.
    boom_progress = (
        progress_dir / "iter_resilience_shard_BOOM.json"
    )
    assert boom_progress.is_file()
    payload = json.loads(boom_progress.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "local_shard" in payload.get("error_note", "")

    # Aggregator status reflects the partial failure.
    aggregate = progress_dir / "iter_resilience.json"
    assert aggregate.is_file()
    agg_payload = json.loads(aggregate.read_text(encoding="utf-8"))
    assert agg_payload["status"] == "failed"


def test_run_distributed_self_play_all_shards_fail_raises(
    monkeypatch, tmp_path,
):
    """If every shard fails AND no npzs were recovered, the
    orchestrator raises a descriptive RuntimeError so the iterate
    driver fails the iter cleanly rather than silently producing a
    0-game training step."""
    from mtg_bot.training import distributed as dist
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

    def _always_boom(*args, **kwargs):
        raise RuntimeError("everyone fails")
    monkeypatch.setattr(dist, "run_shard_pull", _always_boom)

    queue_url, server = _start_queue_server()
    try:
        with pytest.raises(RuntimeError, match="all distributed self-play"):
            run_distributed_self_play(
                cfg, spec,
                progress_dir=progress_dir,
                output_dir=out_dir,
                run_id_prefix="iter_all_fail",
                total_games=4,
                queue_url=queue_url,
            )
    finally:
        server.shutdown()


def test_run_distributed_eval_one_shard_fails_aggregates_rest(
    monkeypatch, tmp_path,
):
    """Eval orchestrator with a failing shard: the surviving shard's
    counts come through; the failed shard contributes zeros."""
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import (
        EvalJobSpec, run_distributed_eval,
    )

    weights_path, hidden_sizes = _tiny_dual_head_weights(tmp_path)
    progress_dir = tmp_path / "training_progress"
    spec = EvalJobSpec(
        new_weights_path=str(weights_path),
        old_weights_path=str(weights_path),
        samples=1, inner_nodes=10, hidden_sizes=hidden_sizes,
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        opponent_label="self",
    )
    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_games=2, label="A", n_workers=1),
        ShardConfig(host="local", n_games=2, label="BOOM", n_workers=1),
    ))

    real_eval_pull = dist.run_shard_eval_pull

    def _selective_eval_pull(*args, **kwargs):
        if kwargs.get("label") == "BOOM":
            raise RuntimeError("simulated eval crash")
        return real_eval_pull(*args, **kwargs)
    monkeypatch.setattr(dist, "run_shard_eval_pull", _selective_eval_pull)

    queue_url, server = _start_queue_server()
    try:
        counts = run_distributed_eval(
            cfg, spec,
            progress_dir=progress_dir,
            run_id_prefix="iter_eval_resilience",
            total_games=4,
            queue_url=queue_url,
        )
    finally:
        server.shutdown()

    # Surviving shard A drained at most its share before the queue
    # ran out; total games <= 4. The BOOM shard contributes zeros.
    total = (
        counts["wins_new"] + counts["wins_old"]
        + counts["draws"] + counts["crashed"]
    )
    assert total == counts["n_games"]
    assert counts["n_games"] >= 1, (
        f"expected surviving shard to produce >=1 game, got {counts}"
    )

    # Failed shard's per-shard progress JSON marked failed.
    boom_progress = (
        progress_dir / "iter_eval_resilience_shard_BOOM.json"
    )
    assert boom_progress.is_file()
    payload = json.loads(boom_progress.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"


def test_mark_shard_progress_failed_merges_into_existing(tmp_path):
    """The helper preserves last-known counters when overwriting.
    Useful when the poller already pulled a partial snapshot back
    before the shard's SSH wrapper died."""
    from mtg_bot.training.distributed import _mark_shard_progress_failed

    progress = tmp_path / "iter_x_shard_macbook.json"
    progress.write_text(json.dumps({
        "run_id": "iter_x_shard_macbook",
        "kind": "data_gen",
        "status": "running",
        "n_games_total": 100,
        "n_games_done": 42,
        "n_samples": 600,
    }), encoding="utf-8")

    _mark_shard_progress_failed(
        progress, shard_label="macbook",
        note="self_play: CalledProcessError: ssh died",
    )
    payload = json.loads(progress.read_text(encoding="utf-8"))
    # Counter preservation:
    assert payload["n_games_done"] == 42
    assert payload["n_samples"] == 600
    # Status flipped:
    assert payload["status"] == "failed"
    assert "self_play" in payload["error_note"]
    assert payload["ended_at"]


def test_mark_shard_progress_failed_creates_minimal_when_absent(tmp_path):
    """If the poller never managed to pull a progress snapshot back
    (the shard died immediately), the helper still writes a minimal
    failed-status JSON so the UI knows the shard is dead, not just
    silent."""
    from mtg_bot.training.distributed import _mark_shard_progress_failed

    progress = tmp_path / "iter_x_shard_macbook.json"
    assert not progress.exists()
    _mark_shard_progress_failed(
        progress, shard_label="macbook",
        note="weight_push: scp died",
    )
    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "weight_push" in payload["error_note"]


def test_run_shard_remote_bundle_sync_failure_returns_failure_report(
    monkeypatch, tmp_path,
):
    """Bundle-sync failure (the very first stage on a remote shard,
    before weights have even been pushed): runner returns a failure
    report tagged ``error_stage="bundle_sync"``."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import (
        ShardSelfPlayReport, SelfPlayJobSpec,
    )

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    class _FailOnBundleSync:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            tail = cmd[-1] if cmd else ""
            if cmd[0] == "ssh" and "git fetch" in tail:
                raise subprocess.CalledProcessError(
                    1, cmd, output="", stderr="curl: 404",
                )

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

    rec = _FailOnBundleSync()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="macbook", n_games=10, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_x",
        iter_total_games=10,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_x",
        stamp="20260503T230000Z",
        bundle_url="http://master:5099/repo.bundle",
    )
    assert isinstance(report, ShardSelfPlayReport)
    assert report.success is False
    assert report.error_stage == "bundle_sync"


def test_run_shard_remote_npz_pull_failure_records_partial(
    monkeypatch, tmp_path,
):
    """If listing returns multiple npzs but one of the per-file scps
    fails, the runner records the partial outcome: it returns a
    failure report whose ``error_stage`` is ``"scp_npz"`` but whose
    ``npz_paths`` includes the files that DID transfer. Pulling
    whatever survived is the whole point of the resilience change."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    listing_payload = (
        "iter_y_shard_macbook_chunk_0001_20260503T230000Z.npz\n"
        "iter_y_shard_macbook_chunk_0002_20260503T230000Z.npz\n"
    )

    class _FailOnSecondNpz:
        def __init__(self):
            self.calls = []
            self.npz_seen = 0

        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            tail = cmd[-1] if cmd else ""
            stdout = ""
            if cmd[0] == "ssh" and "iterate_data" in tail and (
                "ls " in tail or "dir /b" in tail
            ):
                stdout = listing_payload
            if cmd[0] == "scp" and any(
                a.endswith(".npz") for a in cmd
            ):
                self.npz_seen += 1
                if self.npz_seen == 2:
                    raise subprocess.CalledProcessError(
                        1, cmd, output="",
                        stderr="scp: connection reset",
                    )

            class _Result:
                returncode = 0
                stderr = ""
                def __init__(self_, _stdout):
                    self_.stdout = _stdout
            return _Result(stdout)

    rec = _FailOnSecondNpz()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="macbook", n_games=2, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_y",
        iter_total_games=2,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_y",
        stamp="20260503T230000Z",
    )
    assert report.success is False
    assert report.error_stage == "scp_npz"
    assert len(report.npz_paths) == 1, (
        f"expected 1 surviving npz, got {report.npz_paths}"
    )


def test_run_shard_remote_npz_listing_failure_records(
    monkeypatch, tmp_path,
):
    """If the npz-listing ssh itself fails (rather than returning
    empty), the runner records that as ``error_stage=list_npzs``
    when no earlier-stage error exists."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    class _FailOnListing:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            tail = cmd[-1] if cmd else ""
            if cmd[0] == "ssh" and "iterate_data" in tail and (
                "ls " in tail or "dir /b" in tail
            ):
                raise subprocess.SubprocessError(
                    "ssh died during listing",
                )

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

    rec = _FailOnListing()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
    )
    shard = ShardConfig(
        host="macbook", n_games=2, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_z",
        iter_total_games=2,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_z",
        stamp="20260503T230000Z",
    )
    assert report.success is False
    assert report.error_stage == "list_npzs"
    assert report.npz_paths == []


def test_run_shard_remote_replay_pull_failure_warned_not_fatal(
    monkeypatch, tmp_path,
):
    """The replay rsync stage runs LAST and is best-effort. If it
    raises, the per-shard data we already collected (npzs) survives;
    the runner returns a SUCCESS report (no earlier failure) and a
    warning is logged."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import SelfPlayJobSpec

    monkeypatch.chdir(tmp_path)
    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")

    listing_payload = (
        "replay_idx0001.json.gz\nreplay_idx0002.json.gz\n"
    )

    class _FailOnReplayPull:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            tail = cmd[-1] if cmd else ""
            stdout = ""
            if cmd[0] == "ssh" and ".json.gz" in tail:
                stdout = listing_payload
            if cmd[0] == "scp" and any(
                a.endswith(".json.gz") for a in cmd
            ):
                raise subprocess.CalledProcessError(
                    1, cmd, output="", stderr="replay copy died",
                )

            class _Result:
                returncode = 0
                stderr = ""
                def __init__(self_, _stdout):
                    self_.stdout = _stdout
            return _Result(stdout)

    rec = _FailOnReplayPull()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        capture_every=1,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="macbook", n_games=2, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_w",
        iter_total_games=2,
        progress_dir=tmp_path / "training_progress",
        output_dir=tmp_path / "iterate_data",
        run_id_prefix="iter_w",
        stamp="20260503T230000Z",
    )
    # Replay-pull failure is a warning, not fatal — npzs went OK so
    # the report is success.
    assert report.success is True
    assert report.error is None


def test_run_shard_eval_remote_bundle_sync_failure(monkeypatch, tmp_path):
    """Eval-side: bundle-sync failure returns a failure report tagged
    ``error_stage="bundle_sync"`` with zero counts."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import (
        ShardEvalReport, EvalJobSpec,
    )

    monkeypatch.chdir(tmp_path)
    new_weights = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / new_weights).write_bytes(b"new")

    class _FailOnBundleSync:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            tail = cmd[-1] if cmd else ""
            if cmd[0] == "ssh" and "git fetch" in tail:
                raise subprocess.CalledProcessError(
                    1, cmd, output="", stderr="bundle 404",
                )

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

    rec = _FailOnBundleSync()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = EvalJobSpec(
        new_weights_path=new_weights,
        old_weights_path=None,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        opponent_label="rand",
    )
    shard = ShardConfig(
        host="macbook", n_games=4, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_eval_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_eval",
        iter_total_games=4,
        progress_dir=tmp_path / "training_progress",
        stamp="20260503T230000Z",
        bundle_url="http://master:5099/repo.bundle",
    )
    assert isinstance(report, ShardEvalReport)
    assert report.success is False
    # The bundle_sync stage records itself as the failure cause; the
    # subsequent "no result file" step doesn't override it.
    assert report.error_stage == "bundle_sync"


def test_run_shard_eval_remote_weight_push_failure(monkeypatch, tmp_path):
    """Eval-side: weight-push failure returns failure report tagged
    ``weight_push``."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import EvalJobSpec

    monkeypatch.chdir(tmp_path)
    new_weights = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / new_weights).write_bytes(b"new")

    class _FailOnWeightPush:
        def __init__(self): self.calls = []
        def __call__(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            if cmd[0] == "scp" and any(
                p.endswith("weights.pt") for p in cmd
            ):
                raise subprocess.CalledProcessError(
                    1, cmd, output="", stderr="permission denied",
                )

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

    rec = _FailOnWeightPush()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    spec = EvalJobSpec(
        new_weights_path=new_weights,
        old_weights_path=None,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        opponent_label="rand",
    )
    shard = ShardConfig(
        host="macbook", n_games=4, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_eval_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_eval",
        iter_total_games=4,
        progress_dir=tmp_path / "training_progress",
        stamp="20260503T230000Z",
    )
    assert report.success is False
    assert report.error_stage == "weight_push"


def test_run_shard_eval_remote_corrupt_result_file(monkeypatch, tmp_path):
    """Eval result file is present but unparseable: returns failure
    report tagged ``result_parse``."""
    import subprocess
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import EvalJobSpec

    monkeypatch.chdir(tmp_path)
    new_weights = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / new_weights).write_bytes(b"new")

    rec = _ScriptedSubprocess()
    monkeypatch.setattr(dist, "_run_subprocess", rec)
    monkeypatch.setattr(dist.subprocess, "run", rec)

    class _NoopPoller:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(dist, "_ProgressPoller", _NoopPoller)

    # Pre-write a CORRUPT result file at the path the eval shard
    # would scp back. _ScriptedSubprocess no-ops the scp so the
    # corrupt file survives.
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    run_id_full = "iter_eval_shard_macbook"
    (progress_dir / f"{run_id_full}_result.json").write_text(
        "{ this is not valid json", encoding="utf-8",
    )

    spec = EvalJobSpec(
        new_weights_path=new_weights,
        old_weights_path=None,
        samples=1, inner_nodes=10, hidden_sizes=(16,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        opponent_label="rand",
    )
    shard = ShardConfig(
        host="macbook", n_games=4, user="g",
        repo_path="/Users/g/repo",
        venv_python=".venv-py313/bin/python",
    )
    report = dist.run_shard_eval_remote(
        shard, spec,
        queue_url="http://master:5099",
        run_id="iter_eval",
        iter_total_games=4,
        progress_dir=progress_dir,
        stamp="20260503T230000Z",
    )
    assert report.success is False
    assert report.error_stage == "result_parse"


def test_run_distributed_eval_all_shards_fail_raises(
    monkeypatch, tmp_path,
):
    """Eval-side mirror: every shard fails -> RuntimeError raised."""
    from mtg_bot.training import distributed as dist
    from mtg_bot.training.distributed import (
        EvalJobSpec, run_distributed_eval,
    )

    weights_path, hidden_sizes = _tiny_dual_head_weights(tmp_path)
    progress_dir = tmp_path / "training_progress"
    spec = EvalJobSpec(
        new_weights_path=str(weights_path),
        old_weights_path=str(weights_path),
        samples=1, inner_nodes=10, hidden_sizes=hidden_sizes,
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None,
        opponent_label="self",
    )
    cfg = ShardsConfig(shards=(
        ShardConfig(host="local", n_games=2, label="A", n_workers=1),
        ShardConfig(host="local", n_games=2, label="B", n_workers=1),
    ))

    def _always_boom(*args, **kwargs):
        raise RuntimeError("eval boom")
    monkeypatch.setattr(dist, "run_shard_eval_pull", _always_boom)

    queue_url, server = _start_queue_server()
    try:
        with pytest.raises(RuntimeError, match="all distributed eval"):
            run_distributed_eval(
                cfg, spec,
                progress_dir=progress_dir,
                run_id_prefix="iter_all_eval_fail",
                total_games=4,
                queue_url=queue_url,
            )
    finally:
        server.shutdown()


def test_mark_shard_progress_failed_swallows_write_errors(
    tmp_path, monkeypatch,
):
    """The helper must never raise — a master that can't write a
    status file is much better than a master that abandons live
    shards mid-iter. Errors are logged to stderr but swallowed."""
    from mtg_bot.training import distributed as dist

    # Path inside a non-existent directory tree where mkdir will work
    # but write_text fails in a contrived way: monkeypatch the helper
    # to raise from inside.
    progress = tmp_path / "iter_x_shard_macbook.json"

    real_write_text = type(progress).write_text

    def _explode(self, *a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(type(progress), "write_text", _explode)
    try:
        # Should not raise.
        dist._mark_shard_progress_failed(
            progress, shard_label="macbook", note="x",
        )
    finally:
        monkeypatch.setattr(type(progress), "write_text", real_write_text)


# ---- shard SSH hard-timeout regression -----------------------------
#
# Pin: every per-shard SSH call goes through ``_run_subprocess`` with a
# bounded ``timeout`` so a Tailscale-keeps-the-TCP-alive hang can't wedge
# the orchestrator forever. The default is _DEFAULT_SHARD_SSH_TIMEOUT_S
# (90 min); the orchestrator threads through the value provided by the
# caller. If the timeout fires, master's per-shard try/except catches
# ``TimeoutExpired`` and the rsync-recovery flow runs in finally.

def test_shard_ssh_timeout_default_is_finite_and_threaded(monkeypatch):
    """``_run_subprocess`` for the shard SSH must be invoked with
    ``timeout=...`` (not None). The default is the module-level
    constant; the orchestrator threads through any explicit value."""
    import subprocess as _subprocess
    from mtg_bot.training import distributed as dmod

    captured: list[dict] = []

    def fake_run_subprocess(cmd, *, timeout=None):
        captured.append({"cmd": cmd, "timeout": timeout})
        return _subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(dmod, "_run_subprocess", fake_run_subprocess)
    # Find a call that includes _ssh_cmd of the run-shard kind. The
    # default constant should be > 0 and finite.
    assert dmod._DEFAULT_SHARD_SSH_TIMEOUT_S > 0
    assert dmod._DEFAULT_SHARD_SSH_TIMEOUT_S < 24 * 60 * 60  # < 1 day
    # 90-min default specifically is the documented value.
    assert dmod._DEFAULT_SHARD_SSH_TIMEOUT_S == 90 * 60


def test_run_shard_remote_uses_supplied_ssh_timeout(monkeypatch, tmp_path):
    """``run_shard_remote(shard_ssh_timeout_s=X)`` propagates X into
    the subprocess call's ``timeout=`` kwarg. Without this pinning,
    the post-shard hang would block forever on the SSH wrapper."""
    import subprocess as _subprocess
    from mtg_bot.training import distributed as dmod
    from mtg_bot.training.distributed import (
        ShardConfig, SelfPlayJobSpec,
    )

    captured: list[dict] = []

    def fake_run_subprocess(cmd, *, timeout=None):
        captured.append({"cmd": list(cmd), "timeout": timeout})
        return _subprocess.CompletedProcess(args=cmd, returncode=0)

    # Stub the rsync stages so we don't try real scp.
    monkeypatch.setattr(dmod, "_run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(
        dmod, "_remote_join", lambda *a, **kw: "/r/x",
    )
    monkeypatch.setattr(dmod, "_is_windows_remote", lambda s: False)
    # Stub list+scp listing (no files to recover).
    monkeypatch.setattr(
        _subprocess, "run",
        lambda *a, **kw: _subprocess.CompletedProcess(
            args=list(a[0]) if a else [], returncode=0, stdout="", stderr="",
        ),
    )

    weights_rel = "trained_weights/v7/weights.pt"
    (tmp_path / "trained_weights" / "v7").mkdir(parents=True)
    (tmp_path / weights_rel).write_bytes(b"fake")
    spec = SelfPlayJobSpec(
        weights_path=weights_rel,
        samples=2, inner_nodes=10, hidden_sizes=(64,),
        base_seed=0, enable_mulligans=False,
        per_game_timeout_sec=None, capture_every=10,
        replays_root="replays",
    )
    shard = ShardConfig(
        host="my-mac", n_games=10, user="g",
        repo_path="/r", venv_python=".venv-py313/bin/python",
    )

    custom_timeout = 600.0
    dmod.run_shard_remote(
        shard, spec,
        queue_url="http://localhost:5099",
        run_id="test_run",
        iter_total_games=10,
        progress_dir=tmp_path / "progress",
        output_dir=tmp_path / "out",
        run_id_prefix="test_run",
        stamp="20260505T000000Z",
        shard_ssh_timeout_s=custom_timeout,
    )

    # Find the run-shard SSH call (the one that runs run_self_play_shard.py).
    shard_run_calls = [
        c for c in captured
        if any(
            "run_self_play_shard.py" in str(arg)
            for arg in c["cmd"]
        )
    ]
    assert shard_run_calls, (
        "expected at least one ssh call invoking run_self_play_shard.py; "
        f"got: {[c['cmd'] for c in captured]}"
    )
    # Pin: the ssh call carries the supplied timeout, not None.
    for c in shard_run_calls:
        assert c["timeout"] == custom_timeout, (
            f"shard ssh timeout was {c['timeout']!r}, "
            f"expected {custom_timeout}"
        )
