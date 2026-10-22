"""Tests for ``mtg_bot.cli.ladder`` — the local fixed-reference
strength ladder.

Pins:

* the Bradley-Terry Elo fit recovers a known ordering from synthetic
  results and anchors ``random`` at 0 (or the first agent when
  ``random`` is absent);
* the bootstrap CI has the right shape and brackets the point
  estimate;
* the two scoring modes (drop timeouts vs 0.5/0.5) and the Wilson
  interval;
* pairing parsing (``all`` / explicit / malformed);
* participant resolution for ``random`` / ``heuristic`` / a
  registered NN version (metadata -> ``NNPimcConfig`` fields);
* ``--resume`` skips pairs already in ``results.json`` and the
  report is rebuilt over everything;
* the dispatcher lists ``ladder``;
* a slow end-to-end smoke that plays real games from the deck pool.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mtg_bot import cli as cli_pkg
from mtg_bot.cli import ladder as L
from mtg_bot.search.strategy import RandomChoice


def _r(a, b, wa, wb, d=0, t=0, c=0, seed=0) -> L.PairResult:
    return L.PairResult(
        a=a, b=b, games_requested=wa + wb + d + t + c,
        wins_a=wa, wins_b=wb, draws=d, timeouts=t, crashed=c,
        mean_decisions=100.0, wall_seconds=1.0, seed=seed,
    )


def _scores(results, timeouts_as_draws=False):
    return {
        (r.a, r.b): L.pair_points(r, timeouts_as_draws=timeouts_as_draws)
        for r in results
    }


# --------------------------------------------------------------------------
# Elo solver
# --------------------------------------------------------------------------


def test_fit_elo_recovers_known_ordering_and_anchors_random():
    agents = ["random", "heuristic", "vA", "vB"]
    results = [
        _r("random", "heuristic", 50, 450),
        _r("heuristic", "vA", 150, 350),
        _r("vA", "vB", 200, 300),
        _r("random", "vA", 5, 495),
        _r("random", "vB", 2, 498),
    ]
    elo = L.fit_elo(agents, _scores(results), anchor="random")
    assert elo["random"] == 0.0
    assert elo["random"] < elo["heuristic"] < elo["vA"] < elo["vB"]
    # 90% for heuristic over random is ~382 Elo on the logistic scale;
    # the joint fit with the other pairs lands near there.
    assert 300 < elo["heuristic"] < 550


def test_fit_elo_two_agents_matches_closed_form():
    """With one pair and no other constraints the MLE is the closed-
    form logit: 75% -> 400*log10(3) = ~190.8 (the virtual draw prior
    pulls it in by a fraction of a point at n=400)."""
    elo = L.fit_elo(
        ["random", "x"], _scores([_r("random", "x", 100, 300)]),
        anchor="random", prior_draws=0.0,
    )
    assert elo["x"] == pytest.approx(400 * 0.47712125, abs=1e-3)


def test_fit_elo_anchor_falls_back_to_first_agent_when_random_absent():
    agents = ["heuristic", "vA"]
    elo = L.fit_elo(
        agents, _scores([_r("heuristic", "vA", 100, 300)]),
        anchor="random",
    )
    assert elo["heuristic"] == 0.0
    assert elo["vA"] > 0


def test_fit_elo_unplayed_agent_is_none_and_zero_win_agent_is_finite():
    agents = ["random", "vA", "ghost"]
    elo = L.fit_elo(
        agents, _scores([_r("random", "vA", 0, 500)]), anchor="random",
    )
    assert elo["ghost"] is None
    assert elo["random"] == 0.0
    assert elo["vA"] > 1000
    assert elo["vA"] < 1e6  # finite thanks to the virtual-draw prior


def test_connected_components_flags_disconnected_graph():
    agents = ["random", "a", "b", "c"]
    scores = _scores([_r("random", "a", 1, 1), _r("b", "c", 1, 1)])
    comps = L.connected_components(agents, scores)
    assert {frozenset(c) for c in comps} == {
        frozenset({"random", "a"}), frozenset({"b", "c"}),
    }


# --------------------------------------------------------------------------
# Scoring modes, Wilson, bootstrap
# --------------------------------------------------------------------------


def test_pair_points_default_drops_timeouts_and_crashes():
    r = _r("a", "b", 10, 5, d=2, t=3, c=1)
    assert L.pair_points(r, timeouts_as_draws=False) == (11.0, 6.0, 17)


def test_pair_points_timeouts_as_draws_scores_half_each_never_crashes():
    r = _r("a", "b", 10, 5, d=2, t=3, c=1)
    assert L.pair_points(r, timeouts_as_draws=True) == (12.5, 7.5, 20)


def test_wilson_interval():
    lo, hi = L.wilson_interval(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3)
    assert hi == pytest.approx(0.5962, abs=1e-3)
    assert L.wilson_interval(0, 0) == (0.0, 1.0)
    lo0, _ = L.wilson_interval(0, 10)
    assert lo0 == 0.0


def test_bootstrap_ci_shape_and_brackets_point_estimate():
    agents = ["random", "heuristic", "vA"]
    results = [
        _r("random", "heuristic", 50, 450),
        _r("heuristic", "vA", 150, 350),
        _r("random", "vA", 5, 495),
    ]
    elo = L.fit_elo(agents, _scores(results), anchor="random")
    ci = L.bootstrap_elo_ci(
        agents, results, anchor="random", timeouts_as_draws=False,
        n_resamples=40, seed=1,
    )
    assert set(ci) == set(agents)
    assert ci["random"] == (0.0, 0.0)
    for a in ("heuristic", "vA"):
        lo, hi = ci[a]
        assert lo < elo[a] < hi
        assert hi - lo < 300  # 500-game pairs: tens of points, not hundreds


def test_bootstrap_ci_none_for_unplayed_agent():
    ci = L.bootstrap_elo_ci(
        ["random", "x", "ghost"], [_r("random", "x", 10, 10)],
        anchor="random", timeouts_as_draws=False, n_resamples=5,
    )
    assert ci["ghost"] is None


# --------------------------------------------------------------------------
# Pairings + persistence
# --------------------------------------------------------------------------


def test_parse_pairs_all_is_round_robin_in_order():
    assert L.parse_pairs("all", ["r", "h", "v"]) == [
        ("r", "h"), ("r", "v"), ("h", "v"),
    ]


def test_parse_pairs_explicit():
    assert L.parse_pairs("r:h, v:r", ["r", "h", "v"]) == [
        ("r", "h"), ("v", "r"),
    ]


@pytest.mark.parametrize("spec", ["r:zz", "r", "r:h:v", "r:r", ",", ":h"])
def test_parse_pairs_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        L.parse_pairs(spec, ["r", "h", "v"])


def test_atomic_write_and_load_roundtrip(tmp_path):
    payload = {"config": {"agents": ["r"]}, "agents": {}, "pairs": {}}
    L.atomic_write_json(tmp_path / L.RESULTS_FILENAME, payload)
    assert not (tmp_path / (L.RESULTS_FILENAME + ".tmp")).exists()
    assert L.load_results(tmp_path) == payload
    assert L.load_results(tmp_path / "nope") == {
        "config": {}, "agents": {}, "pairs": {},
    }


def test_find_completed_matches_either_orientation():
    r = _r("a", "b", 3, 4)
    results = {"pairs": {L.pair_key("a", "b"): r.to_dict()}}
    assert L.find_completed(results, "a", "b") == r
    assert L.find_completed(results, "b", "a") == r
    assert L.find_completed(results, "a", "c") is None


# --------------------------------------------------------------------------
# Participant resolution
# --------------------------------------------------------------------------


def test_resolve_random_and_heuristic_build_strategies(tmp_path):
    from mtg_bot.search import PIMC
    r = L.resolve_agent(
        "random", registry_root=tmp_path, nodes=4, samples=1,
    )
    h = L.resolve_agent(
        "heuristic", registry_root=tmp_path, nodes=4, samples=1,
    )
    assert isinstance(r.factory(0), RandomChoice)
    assert isinstance(h.factory(0), PIMC)
    assert h.description["kind"] == "heuristic_pimc"
    assert h.description["inner_nodes"] == 4
    assert h.description["samples"] == 1
    assert h.description["batch_size"] == 1


def test_resolve_random_config_is_seeded_and_picklable():
    import pickle
    cfg = L.RandomConfig()
    build = pickle.loads(pickle.dumps(cfg.build))
    a = build(7).choose
    assert callable(a)
    # Same seed -> same RNG stream.
    s1, s2 = cfg.build(7), cfg.build(7)
    assert [s1.rng.random() for _ in range(3)] == [s2.rng.random() for _ in range(3)]


def _fake_registry_version(root: Path, label: str, meta: dict) -> None:
    d = root / label
    d.mkdir(parents=True)
    (d / "weights.pt").write_bytes(b"not-real-weights")
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


def test_resolve_nn_version_reads_registry_metadata(tmp_path):
    _fake_registry_version(tmp_path, "v13s", {
        "version": "v13s", "created_at": "2026-05-21T00:21:11Z",
        "feature_dim": 51, "hidden_sizes": [],
        "with_policy": True, "architecture": "structured",
        "action_encoding_version": "canonical_v2",
        "training": {"structured_config": {"emb_dim": 256}},
        "git_commit": "3af7edea",
    })
    _fake_registry_version(tmp_path, "v7", {
        "version": "v7", "created_at": "x", "feature_dim": 51,
        "hidden_sizes": [1024, 1024, 512], "with_policy": True,
        "architecture": "separate",
        "training": {"policy_hidden_sizes": [256, 256]},
    })
    s = L.resolve_agent("v13s", registry_root=tmp_path, nodes=8, samples=1)
    d = s.description
    assert d["kind"] == "nn_pimc"
    assert d["architecture"] == "structured"
    assert d["hidden_sizes"] is None
    assert d["action_encoding_version"] == "canonical_v2"
    assert d["with_policy"] is True and d["puct"] is True
    assert d["inner_nodes"] == 8 and d["samples"] == 1
    from mtg_bot.search.leaf_batch import SEARCH_LEAF_BATCH_SIZE
    assert d["batch_size"] == SEARCH_LEAF_BATCH_SIZE == 1
    assert d["weights_path"].endswith(os.path.join("v13s", "weights.pt"))
    assert d["git_commit"] == "3af7edea"

    s7 = L.resolve_agent("v7", registry_root=tmp_path, nodes=8, samples=1)
    assert s7.description["hidden_sizes"] == [1024, 1024, 512]
    assert s7.description["policy_hidden_sizes"] == [256, 256]
    assert s7.description["architecture"] == "separate"
    assert s7.description["action_encoding_version"] == "positional_v1"


def test_resolve_unknown_label_raises_with_available_versions(tmp_path):
    _fake_registry_version(tmp_path, "v3", {
        "version": "v3", "created_at": "x", "feature_dim": 51,
        "hidden_sizes": [128],
    })
    with pytest.raises(ValueError, match="unknown agent 'v99'.*v3"):
        L.resolve_agent("v99", registry_root=tmp_path, nodes=8, samples=1)


# --------------------------------------------------------------------------
# Argument parsing + main
# --------------------------------------------------------------------------


def test_parser_defaults_and_flags():
    p = L.build_parser()
    args = p.parse_args(["--agents", "random", "heuristic", "v5"])
    assert args.agents == ["random", "heuristic", "v5"]
    assert args.pairs == "all"
    assert args.games == L.DEFAULT_GAMES == 500
    assert args.workers is None
    assert args.seed == 0
    assert args.out is None and args.resume is None
    assert args.timeouts_as_draws is False
    assert args.registry_root == Path("trained_weights")
    # depth + runtime parents are wired in
    assert args.nodes == 200 and args.samples == 4
    assert args.per_game_timeout_sec is None
    args = p.parse_args([
        "--agents", "random", "--pairs", "a:b", "--games", "10",
        "--workers", "3", "--seed", "9", "--timeouts-as-draws",
        "--nodes", "8", "--samples", "1", "--out", "o", "--resume", "r",
    ])
    assert args.pairs == "a:b" and args.games == 10 and args.workers == 3
    assert args.seed == 9 and args.timeouts_as_draws is True
    assert args.nodes == 8 and args.samples == 1
    assert args.out == Path("o") and args.resume == Path("r")


def test_main_requires_agents(tmp_path):
    with pytest.raises(SystemExit):
        L.main(["--out", str(tmp_path)])


def test_main_rejects_missing_resume_dir(tmp_path):
    with pytest.raises(SystemExit):
        L.main(["--resume", str(tmp_path / "nope"), "--agents", "random"])


def _install_fake_play(monkeypatch, tmp_path, calls):
    """Stub the game-playing + deck-loading seams so ``main`` runs
    end-to-end without an engine. Every label resolves to a random
    seat so no registry is needed."""
    def fake_resolve(label, *, registry_root, nodes, samples):
        return L.AgentSpec(
            label=label, factory=L.RandomConfig().build,
            description={"kind": "fake", "nodes": nodes},
        )

    def fake_play(spec_a, spec_b, *, n_games, seed, n_workers,
                  per_game_timeout_sec, deck_pool):
        calls.append((spec_a.label, spec_b.label, n_games, seed))
        return _r(spec_a.label, spec_b.label, n_games - 1, 1, seed=seed)

    monkeypatch.setattr(L, "resolve_agent", fake_resolve)
    monkeypatch.setattr(L, "play_pair", fake_play)
    import mtg_bot.decks as decks_mod
    monkeypatch.setattr(decks_mod, "decks_from_json", lambda p: [object()])
    pool = tmp_path / "pool.json.gz"
    pool.write_bytes(b"")
    return pool


def test_main_plays_all_pairs_and_writes_results_and_report(
    tmp_path, monkeypatch, capsys,
):
    calls: list = []
    pool = _install_fake_play(monkeypatch, tmp_path, calls)
    out = tmp_path / "run"
    L.main([
        "--agents", "random", "heuristic", "vX", "--games", "6",
        "--workers", "1", "--seed", "5", "--out", str(out),
        "--deck-pool", str(pool), "--nodes", "4", "--samples", "1",
    ])
    assert [(a, b) for a, b, _, _ in calls] == [
        ("random", "heuristic"), ("random", "vX"), ("heuristic", "vX"),
    ]
    assert all(n == 6 and s == 5 for _, _, n, s in calls)
    data = json.loads((out / L.RESULTS_FILENAME).read_text(encoding="utf-8"))
    assert set(data["pairs"]) == {"random|heuristic", "random|vX", "heuristic|vX"}
    assert data["config"]["games"] == 6
    assert data["config"]["nodes"] == 4
    assert data["config"]["timeouts_as_draws"] is False
    assert "git_commit" in data["config"]
    assert data["agents"]["vX"]["kind"] == "fake"
    report = (out / L.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "## Elo" in report and "## Pairwise results" in report
    assert "## Config" in report and "`nodes`: `4`" in report
    assert "| random |" in report and "+0 |" in report
    assert report.strip() in capsys.readouterr().out


def test_main_resume_skips_completed_pairs(tmp_path, monkeypatch):
    calls: list = []
    pool = _install_fake_play(monkeypatch, tmp_path, calls)
    out = tmp_path / "run"
    out.mkdir()
    done = _r("heuristic", "random", 2, 4, seed=5)  # reversed orientation
    L.atomic_write_json(out / L.RESULTS_FILENAME, {
        "config": {
            "agents": ["random", "heuristic", "vX"], "games": 6,
            "started_at": "2026-01-01T00:00:00+00:00",
        },
        "agents": {},
        "pairs": {L.pair_key("heuristic", "random"): done.to_dict()},
    })
    # No --agents: they come from the resumed config.
    L.main([
        "--resume", str(out), "--games", "6", "--workers", "1",
        "--seed", "5", "--deck-pool", str(pool),
    ])
    assert [(a, b) for a, b, _, _ in calls] == [
        ("random", "vX"), ("heuristic", "vX"),
    ]
    data = json.loads((out / L.RESULTS_FILENAME).read_text(encoding="utf-8"))
    assert len(data["pairs"]) == 3
    assert data["pairs"]["heuristic|random"] == done.to_dict()
    assert data["config"]["started_at"] == "2026-01-01T00:00:00+00:00"
    report = (out / L.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "heuristic vs random" in report

    # Resuming again with everything done plays nothing but still
    # rebuilds the report (e.g. to switch scoring mode).
    calls.clear()
    L.main([
        "--resume", str(out), "--workers", "1",
        "--deck-pool", str(pool), "--timeouts-as-draws",
    ])
    assert calls == []
    report = (out / L.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "timeouts scored as draws" in report


def test_main_rejects_unknown_agent_loudly(tmp_path, monkeypatch, capsys):
    pool = tmp_path / "pool.json.gz"
    pool.write_bytes(b"")
    with pytest.raises(SystemExit) as ei:
        L.main([
            "--agents", "random", "v999", "--registry-root",
            str(tmp_path / "reg"), "--out", str(tmp_path / "o"),
            "--deck-pool", str(pool),
        ])
    assert "cannot load agent 'v999'" in str(ei.value)


def test_build_report_warns_on_disconnected_graph():
    agents = ["random", "a", "b", "c"]
    results = [_r("random", "a", 1, 3), _r("b", "c", 2, 2)]
    report = L.build_report(
        agents, results, {}, timeouts_as_draws=False,
        bootstrap_resamples=3,
    )
    assert "WARNING" in report and "disconnected" in report


def test_dispatcher_lists_ladder(capsys):
    assert cli_pkg._SUBCOMMANDS["ladder"] == "mtg_bot.cli.ladder"
    cli_pkg.main([])
    assert "ladder" in capsys.readouterr().out


# --------------------------------------------------------------------------
# End-to-end smoke against the real deck pool
# --------------------------------------------------------------------------

_REAL_POOL = Path(__file__).resolve().parents[2] / "data" / "17lands" / "eoe_decks.json.gz"


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("MTG_BOT_FAST_TESTS") == "1",
    reason="ladder e2e smoke skipped under MTG_BOT_FAST_TESTS=1",
)
@pytest.mark.skipif(
    not _REAL_POOL.is_file(),
    reason=f"real deck pool missing at {_REAL_POOL}",
)
def test_end_to_end_smoke_random_vs_heuristic(tmp_path):
    """Actually plays 2 seat-alternated games of random vs heuristic
    PIMC at nodes=4 / samples=1 on one worker and checks the ladder
    accounts for every requested game."""
    out = tmp_path / "ladder"
    L.main([
        "--agents", "random", "heuristic", "--games", "2",
        "--nodes", "4", "--samples", "1", "--workers", "1",
        "--seed", "3", "--out", str(out), "--deck-pool", str(_REAL_POOL),
        "--per-game-timeout-sec", "300", "--bootstrap-resamples", "10",
    ])
    data = json.loads((out / L.RESULTS_FILENAME).read_text(encoding="utf-8"))
    r = L.PairResult.from_dict(data["pairs"]["random|heuristic"])
    assert r.games_requested == 2
    assert r.wins_a + r.wins_b + r.draws + r.timeouts + r.crashed == 2
    assert r.crashed == 0
    assert r.wall_seconds > 0
    assert (out / L.REPORT_FILENAME).is_file()


def test_play_pair_keeps_the_quiet_window_skip_off(monkeypatch):
    """Ladder games play with the production heuristic defaults minus
    the opponent-quiet-window skip (SEARCH_LIMITATIONS #17)."""
    import mtg_bot.training.self_play as sp_mod
    from mtg_bot.search.heuristics_config import HeuristicsConfig
    from mtg_bot.training.self_play import MatchStats

    seen = {}

    def fake_run_match_parallel(**kwargs):
        seen.update(kwargs)
        return MatchStats(wins={0: 1, 1: 0}, draws=0, games=1,
                          avg_decisions=3.0)

    monkeypatch.setattr(sp_mod, "run_match_parallel", fake_run_match_parallel)
    spec = L.AgentSpec(label="random", factory=L.RandomConfig().build,
                       description={"kind": "random"})
    result = L.play_pair(spec, spec, n_games=1, seed=0, n_workers=1,
                         per_game_timeout_sec=None, deck_pool=[])
    assert result.wins_a == 1
    assert seen["heuristics"] == HeuristicsConfig.live_eval()
    assert seen["alternate_seats"] is True


# --------------------------------------------------------------------------
# Head-isolation variants: <version>+valueonly / <version>+heurvalue
# --------------------------------------------------------------------------


def _policy_version(tmp_path, label="v22"):
    _fake_registry_version(tmp_path, label, {
        "version": label, "created_at": "2026-09-28T02:01:22Z",
        "feature_dim": 51, "hidden_sizes": [],
        "with_policy": True, "architecture": "structured",
        "action_encoding_version": "canonical_v2",
        "training": {"structured_config": {"emb_dim": 128}},
        "git_commit": "916b8972",
    })


def test_resolve_valueonly_variant_disables_puct_but_keeps_policy_head(tmp_path):
    _policy_version(tmp_path)
    s = L.resolve_agent("v22+valueonly", registry_root=tmp_path, nodes=8, samples=1)
    d = s.description
    assert s.label == "v22+valueonly"
    assert d["kind"] == "nn_pimc_value_only" and d["version"] == "v22"
    assert d["with_policy"] is True and d["puct"] is False
    assert d["weights_path"].endswith(os.path.join("v22", "weights.pt"))
    # Plain label is untouched.
    assert L.resolve_agent("v22", registry_root=tmp_path, nodes=8, samples=1).description["puct"] is True


def test_resolve_heurvalue_variant_builds_hybrid_config(tmp_path):
    from mtg_bot.search.hybrid_evaluator import HybridPimcConfig
    _policy_version(tmp_path)
    s = L.resolve_agent("v22+heurvalue", registry_root=tmp_path, nodes=8, samples=2)
    d = s.description
    assert d["kind"] == "hybrid_heur_value_nn_policy" and d["version"] == "v22"
    assert d["inner_nodes"] == 8 and d["samples"] == 2
    assert d["nn"]["with_policy"] is True and d["nn"]["puct"] is True
    assert d["heuristic"] is not None
    assert isinstance(s.factory.__self__, HybridPimcConfig)


def test_resolve_heurvalue_needs_policy_head(tmp_path):
    _fake_registry_version(tmp_path, "v1", {
        "version": "v1", "created_at": "x", "feature_dim": 51,
        "hidden_sizes": [], "with_policy": False, "architecture": "structured",
    })
    with pytest.raises(ValueError, match="policy head"):
        L.resolve_agent("v1+heurvalue", registry_root=tmp_path, nodes=4, samples=1)


def test_resolve_unknown_variant_rejected(tmp_path):
    _policy_version(tmp_path)
    with pytest.raises(ValueError, match="unknown agent variant"):
        L.resolve_agent("v22+bogus", registry_root=tmp_path, nodes=4, samples=1)


def test_variant_labels_survive_pair_parsing():
    pairs = L.parse_pairs(
        "heuristic:v22+valueonly,heuristic:v22+heurvalue",
        ["heuristic", "v22+valueonly", "v22+heurvalue"],
    )
    assert pairs == [("heuristic", "v22+valueonly"), ("heuristic", "v22+heurvalue")]


def test_batch_modifier_overrides_leaf_batch_size(tmp_path):
    _policy_version(tmp_path)
    h = L.resolve_agent("heuristic+b32", registry_root=tmp_path, nodes=4, samples=1)
    assert h.description["kind"] == "heuristic_pimc" and h.description["batch_size"] == 32
    v = L.resolve_agent("v22+b1", registry_root=tmp_path, nodes=4, samples=1)
    assert v.description["kind"] == "nn_pimc" and v.description["batch_size"] == 1
    assert v.description["puct"] is True
    both = L.resolve_agent("v22+heurvalue+b1", registry_root=tmp_path, nodes=4, samples=1)
    assert both.description["kind"] == "hybrid_heur_value_nn_policy"
    assert both.description["nn"]["batch_size"] == 1


def test_batch_modifier_rejects_bad_values(tmp_path):
    _policy_version(tmp_path)
    with pytest.raises(ValueError, match="unknown agent variant"):
        L.resolve_agent("v22+b0", registry_root=tmp_path, nodes=4, samples=1)
    with pytest.raises(ValueError, match="head variants need a registered version"):
        L.resolve_agent("heuristic+valueonly", registry_root=tmp_path, nodes=4, samples=1)
    with pytest.raises(ValueError, match="more than one head variant"):
        L.resolve_agent("v22+valueonly+heurvalue", registry_root=tmp_path, nodes=4, samples=1)


def test_default_leaf_batch_is_one_for_every_agent(tmp_path):
    """2026-10-01: batch 32 was an ~8-point search handicap vs the
    batch-1 heuristic; the production default is now 1 everywhere."""
    from mtg_bot.search.leaf_batch import SEARCH_LEAF_BATCH_SIZE
    _policy_version(tmp_path)
    assert SEARCH_LEAF_BATCH_SIZE == 1
    for label in ("heuristic", "v22", "v22+valueonly"):
        d = L.resolve_agent(label, registry_root=tmp_path, nodes=4, samples=1).description
        assert d["batch_size"] == 1, label
    hv = L.resolve_agent("v22+heurvalue", registry_root=tmp_path, nodes=4, samples=1).description
    assert hv["nn"]["batch_size"] == 1
