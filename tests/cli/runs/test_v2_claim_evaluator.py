"""``POST /v2/claim`` must carry the self-play evaluator kind.

A heuristic (warm-start corpus) stage has no weights version, so the
three corpus-format fields the NN path discovers from the version's
``metadata.json`` -- action encoding, structured-token flag, scalar
schema -- have to be copied from the stage spec onto every claim.
Dropping any of them would produce a corpus that silently doesn't
match the net it will train.
"""

from __future__ import annotations

from pathlib import Path

from mtg_bot.cli import serve as serve_mod
from mtg_bot.distributed_rest_orchestrator import make_self_play_stage_spec


def _make_app(tmp_path: Path):
    return serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        queue_db_path=tmp_path / "queue.db",
        weights_root=tmp_path / "trained_weights",
        iterate_data_dir=tmp_path / "iterate_data",
        replays_root=tmp_path / "replays",
        shards_config_path=tmp_path / "shards.json",
        enable_heartbeat_poller=False,
        report_executor=None,
    )


def _claim(client, stage_id: str):
    res = client.post(
        "/v2/claim", json={"worker_id": "wA", "stage_id": stage_id},
    )
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_claim_carries_heuristic_evaluator_and_corpus_format(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    spec = make_self_play_stage_spec(
        stage_id="s2_iter_011_self_play_heuristic",
        n_games=2, base_seed=7, deck_pool_size=50,
        weights_version="ignored",
        nodes=100, samples=2, per_game_timeout_sec=900.0,
        evaluator="heuristic",
        action_encoding_version="canonical_v2",
        structured_tokens=True,
        structured_scalar_schema_version=2,
        move_temperature=1.0, temperature_cutoff=30,
    )
    res = client.post("/v2/stage/create", json=spec.to_dict())
    assert res.status_code == 200, res.get_json()

    body = _claim(client, "s2_iter_011_self_play_heuristic")
    assert body["evaluator"] == "heuristic"
    assert body["action_encoding_version"] == "canonical_v2"
    assert body["structured_tokens"] is True
    assert body["structured_scalar_schema_version"] == 2
    # The interlock: falsy weights so a pre-``evaluator`` worker
    # raises instead of running the NN.
    assert not (body["weights"].get("p0") or body["weights"].get("new"))
    # Exploration knobs still ride along.
    assert body["move_temperature"] == 1.0
    assert body["temperature_cutoff"] == 30


def test_claim_evaluator_is_none_for_a_legacy_spec(tmp_path):
    """A stage created by an older orchestrator has no ``evaluator``
    key; the claim reports ``None`` and the worker's
    ``claim_evaluator`` maps that to "nn" -- unchanged behaviour."""
    app = _make_app(tmp_path)
    client = app.test_client()
    legacy_spec = {
        "stage_id": "iter_009_self_play_v6",
        "kind": "self_play",
        "weights": {"p0": "v5", "p1": "v5"},
        "nodes": 200,
        "samples": 4,
        "per_game_timeout_sec": 600.0,
        "capture_every": 0,
        "claim_ttl_seconds": 1200,
        "games": [
            {"game_idx": 0, "deck_indices": [1, 2], "seed": 5},
        ],
    }
    res = client.post("/v2/stage/create", json=legacy_spec)
    assert res.status_code == 200, res.get_json()

    body = _claim(client, "iter_009_self_play_v6")
    assert body["evaluator"] is None
    assert body["action_encoding_version"] is None
    assert body["structured_tokens"] is None
    assert body["structured_scalar_schema_version"] is None

    from mtg_bot.training.self_play_evaluator import claim_evaluator
    assert claim_evaluator(body) == "nn"
