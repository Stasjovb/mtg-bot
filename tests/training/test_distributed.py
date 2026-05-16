"""Tests for the dataclass schema in ``mtg_bot.training.distributed``.

Post v2-cutover this module is just the per-stage spec dataclasses
(``SelfPlayJobSpec``, ``EvalJobSpec``). The SSH-driven orchestrator
(``run_distributed_self_play`` / ``run_distributed_eval``), the
SSH remote-shard plumbing (``run_shard_remote``,
``_push_weights_to_remote``, ``_pull_remote_replays``,
``_ssh_cmd`` / ``_scp_cmd``, the terminal-status SSH watchdog,
``_local_shard_run_lifecycle``), the pull-mode shard runners
(``run_shard_local`` / ``run_shard_pull`` / ``run_shard_eval_pull``),
the queue HTTP retry layer, the SQLite-backed master queue helpers,
the legacy ``ShardConfig`` / ``ShardsConfig`` dataclasses, and the
SSH-shape ``load_shards_config`` are all gone. See
``docs/DISTRIBUTED_API_v2.md`` for the v2 contract that replaced
them and ``mtg_bot.distributed_rest_orchestrator`` for the new
orchestrator entrypoint.

The tests below pin the dataclass round-trip contract that survives:
``to_dict`` / ``from_dict``, default-field semantics for the
heuristics / architecture / action_encoding_version slots, and the
forward-slash path normalization that lets a serialized spec
round-trip cleanly across Windows / POSIX boundaries.
"""

from __future__ import annotations

import pytest

from mtg_bot.search.heuristics_config import HeuristicsConfig
from mtg_bot.training.distributed import (
    EvalJobSpec,
    SelfPlayJobSpec,
)


# ----------------------------------------------------------------------
# Path normalization
# ----------------------------------------------------------------------


def test_spec_to_dict_normalizes_windows_paths_to_forward_slashes():
    """iterate runs on Windows and produces ``str(Path(...))`` with
    backslashes. A spec serialized on the master must round-trip
    cleanly into a POSIX worker context (and vice versa) — ``to_dict``
    forward-slash-normalizes the path fields so the wire format is
    platform-neutral."""
    spec = SelfPlayJobSpec(
        weights_path="tmp_iter\\registry\\v6\\weights.pt",
        samples=2, inner_nodes=50, hidden_sizes=(64,),
        base_seed=0,
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
    spec = SelfPlayJobSpec(
        weights_path="weights.pt",
        samples=1, inner_nodes=1, hidden_sizes=None,
        base_seed=0,
        per_game_timeout_sec=None,
    )
    d = spec.to_dict()
    assert d["deck_pool_path"] is None
    assert d["replays_root"] is None
    assert d["hang_dump_root"] is None


# ----------------------------------------------------------------------
# Round-trip: to_dict + from_dict is identity
# ----------------------------------------------------------------------


def test_spec_round_trips_through_to_dict_from_dict():
    original = SelfPlayJobSpec(
        weights_path="trained_weights/v6/weights.pt",
        samples=4, inner_nodes=200,
        hidden_sizes=(1024, 1024, 512),
        base_seed=2_000_000,
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


def test_eval_spec_round_trips_through_to_dict_from_dict():
    """``EvalJobSpec.to_dict`` + ``from_dict`` round-trip cleanly with
    backslash-path normalization on Windows-style paths."""
    spec = EvalJobSpec(
        new_weights_path="trained_weights\\v7\\weights.pt",
        old_weights_path="trained_weights\\v6\\weights.pt",
        samples=4, inner_nodes=200, hidden_sizes=(1024, 1024, 512),
        base_seed=2_007_777,
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
    assert rt.new_weights_path == "trained_weights/v7/weights.pt"
    assert rt.old_weights_path == "trained_weights/v6/weights.pt"
    assert rt.deck_pool_path == "data/17lands/eoe_decks.json.gz"
    assert rt.samples == 4 and rt.inner_nodes == 200
    assert rt.hidden_sizes == (1024, 1024, 512)
    assert rt.opponent_label == "v6"


def test_eval_spec_old_weights_can_be_none():
    """``old_weights_path=None`` runs the heuristic-opponent path —
    ``to_dict`` keeps it as null, ``from_dict`` accepts."""
    spec = EvalJobSpec(
        new_weights_path="weights.pt", old_weights_path=None,
        samples=2, inner_nodes=10, hidden_sizes=None,
        base_seed=0,
        per_game_timeout_sec=None,
    )
    d = spec.to_dict()
    assert d["old_weights_path"] is None
    rt = EvalJobSpec.from_dict(d)
    assert rt.old_weights_path is None


# ----------------------------------------------------------------------
# Heuristics-field defaults
# ----------------------------------------------------------------------


def test_self_play_spec_default_heuristics_all_true():
    """Self-play default for the ``heuristics`` field = every flag
    True. Documented as the production default in ``HeuristicsConfig``
    and pinned here against accidental flips."""
    spec = SelfPlayJobSpec(
        weights_path="w.pt", samples=1, inner_nodes=1, hidden_sizes=None,
        base_seed=0, per_game_timeout_sec=None,
    )
    assert spec.heuristics == HeuristicsConfig()


def test_self_play_spec_from_dict_missing_heuristics_defaults_to_all_true():
    """Older payloads written before the heuristics field existed
    must round-trip into the production self-play default."""
    rebuilt = SelfPlayJobSpec.from_dict({
        "weights_path": "w.pt",
        "samples": 1,
        "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.heuristics == HeuristicsConfig()


def test_eval_spec_default_heuristics_all_false():
    """Eval default = ``HeuristicsConfig.disabled()`` (every flag
    OFF). Pin: match outcomes are load-bearing for acceptance gates."""
    spec = EvalJobSpec(
        new_weights_path="new.pt", old_weights_path=None,
        samples=1, inner_nodes=1, hidden_sizes=None,
        base_seed=0, per_game_timeout_sec=None,
    )
    assert spec.heuristics == HeuristicsConfig.disabled()


def test_eval_spec_round_trips_heuristics():
    original = EvalJobSpec(
        new_weights_path="new.pt", old_weights_path="old.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42,
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
    rebuilt = EvalJobSpec.from_dict({
        "new_weights_path": "new.pt",
        "old_weights_path": None,
        "samples": 1,
        "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.heuristics == HeuristicsConfig.disabled()


# ----------------------------------------------------------------------
# Architecture + policy_hidden_sizes
# ----------------------------------------------------------------------


def test_self_play_spec_architecture_round_trips():
    """``architecture`` + ``policy_hidden_sizes`` survive the JSON
    round-trip so any serialized spec can instantiate the matching
    dual-head class."""
    original = SelfPlayJobSpec(
        weights_path="w.pt", samples=4, inner_nodes=200,
        hidden_sizes=(128, 128, 64),
        base_seed=0,
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
    rebuilt = SelfPlayJobSpec.from_dict({
        "weights_path": "w.pt",
        "samples": 1, "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.architecture is None
    assert rebuilt.policy_hidden_sizes is None


def test_eval_spec_architecture_round_trips():
    """``new_architecture`` / ``old_architecture`` / ``policy_hidden_
    sizes`` round-trip cleanly so the eval-stage worker can
    instantiate the right class for each side of the match."""
    original = EvalJobSpec(
        new_weights_path="new.pt", old_weights_path="old.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42,
        per_game_timeout_sec=300.0,
        new_architecture="separate",
        old_architecture="shared",
        policy_hidden_sizes=(48, 24),
    )
    rt = EvalJobSpec.from_dict(original.to_dict())
    assert rt.new_architecture == "separate"
    assert rt.old_architecture == "shared"
    assert rt.policy_hidden_sizes == (48, 24)


# ----------------------------------------------------------------------
# action_encoding_version
# ----------------------------------------------------------------------


def test_self_play_spec_action_encoding_version_round_trips():
    """``action_encoding_version`` round-trips through to_dict /
    from_dict so any consumer encodes policy targets under the same
    slot-mapping convention the bootstrap weights were trained at."""
    original = SelfPlayJobSpec(
        weights_path="w.pt", samples=4, inner_nodes=200,
        hidden_sizes=(1024, 1024, 512),
        base_seed=0,
        per_game_timeout_sec=None,
        action_encoding_version="canonical_v2",
    )
    rt = SelfPlayJobSpec.from_dict(original.to_dict())
    assert rt.action_encoding_version == "canonical_v2"


def test_self_play_spec_action_encoding_version_default_is_none():
    """Older payloads without the field decode cleanly with
    ``action_encoding_version=None`` so v13/v15/v16-era specs already
    in flight don't crash."""
    rebuilt = SelfPlayJobSpec.from_dict({
        "weights_path": "w.pt",
        "samples": 1, "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.action_encoding_version is None


def test_eval_spec_action_encoding_version_round_trips_per_side():
    """Each side carries its own ``action_encoding_version`` so a
    cross-version eval (v17[canonical_v2] vs v13[positional_v1]) can
    encode each NN's PUCT priors against its trained slot mapping."""
    original = EvalJobSpec(
        new_weights_path="new.pt", old_weights_path="old.pt",
        samples=4, inner_nodes=200, hidden_sizes=(64, 64),
        base_seed=42,
        per_game_timeout_sec=300.0,
        new_action_encoding_version="canonical_v2",
        old_action_encoding_version="positional_v1",
    )
    rt = EvalJobSpec.from_dict(original.to_dict())
    assert rt.new_action_encoding_version == "canonical_v2"
    assert rt.old_action_encoding_version == "positional_v1"


def test_eval_spec_action_encoding_version_default_is_none():
    """Older eval payloads without the per-side fields decode with
    None on both sides — back-compat for v13/v15/v16-era evals."""
    rebuilt = EvalJobSpec.from_dict({
        "new_weights_path": "new.pt",
        "old_weights_path": None,
        "samples": 1, "inner_nodes": 1,
        "hidden_sizes": None,
        "base_seed": 0,
        "per_game_timeout_sec": None,
    })
    assert rebuilt.new_action_encoding_version is None
    assert rebuilt.old_action_encoding_version is None
