"""Tests for ``scripts/bench_ismcts_vs_pimc_strength.py``.

Three lightweight smoke checks per the Phase 4 bench task:

1. The wrapped ISMCTS factory builds a working strategy that produces
   a legal decision on a fresh game state (validates the local
   ``_NNIsmctsConfig.build`` shim isn't wired up wrong — same
   contract as ``NNPimcConfig.build``).
2. The Wilson 95% CI helper is mathematically correct on a few hand-
   verifiable cases.
3. ``--help`` runs cleanly and lists the major flags (smoke that the
   argparse surface didn't break — same shape as the
   ``run_self_play_shard.py`` smoke pattern).

The actual 200-game bench is operator-facing and not run here; CI
times out and the noise-level varies game-to-game anyway.
"""

from __future__ import annotations

import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.search import MtgGameStateAdapter
from mtg_bot.search.strategy import SearchStrategy
from mtg_bot.simulate import setup_game


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "bench_ismcts_vs_pimc_strength.py"
)
# _REPO_ROOT is the worktree (ismcts-ab-bench/). Sibling ``mtg-bot/``
# lives one level up at the worktree-parent (mtg-bot-worktrees/), then
# one more level up reaches Projects/, which contains the main checkout.
_DEFAULT_WEIGHTS = (
    _REPO_ROOT.parents[1] / "mtg-bot"
    / "trained_weights" / "v6" / "weights.pt"
)


def _load_module():
    """Load the bench script as a fresh module.

    Registers in ``sys.modules`` BEFORE ``exec_module`` because the
    script defines a frozen dataclass with ``Optional[...]`` type
    hints; ``dataclass`` introspection does ``sys.modules.get(
    cls.__module__).__dict__`` and crashes if the module isn't
    registered. Same trap that bit ``test_iterate_resume.py`` would
    hit if it had typed dataclasses.
    """
    name = "bench_ismcts_vs_pimc_strength"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --- Wilson CI ------------------------------------------------------


def test_wilson_interval_fair_coin_n100():
    """50/100 should give a CI roughly (0.404, 0.596) at z=1.96."""
    bench = _load_module()
    low, high = bench.wilson_interval(50, 100)
    assert 0.40 <= low <= 0.41
    assert 0.59 <= high <= 0.60
    # Center should sit at 0.5.
    assert abs((low + high) / 2 - 0.5) < 1e-9


def test_wilson_interval_zero_trials_is_uninformative():
    bench = _load_module()
    low, high = bench.wilson_interval(0, 0)
    assert (low, high) == (0.0, 1.0)


def test_wilson_interval_extreme_proportions():
    """0/10 and 10/10 should give one-sided non-degenerate bounds."""
    bench = _load_module()
    low, high = bench.wilson_interval(0, 10)
    assert low == pytest.approx(0.0, abs=1e-9)
    assert 0.25 < high < 0.35

    low, high = bench.wilson_interval(10, 10)
    assert 0.65 < low < 0.75
    assert high == pytest.approx(1.0, abs=1e-9)


def test_wilson_interval_validates_inputs():
    bench = _load_module()
    with pytest.raises(ValueError):
        bench.wilson_interval(11, 10)
    with pytest.raises(ValueError):
        bench.wilson_interval(-1, 10)


def test_classify_verdict_thresholds():
    bench = _load_module()
    # CI strictly above 0.5 -> stronger.
    assert bench.classify(0.7, 0.55, 0.85) == "stronger"
    # CI strictly below 0.5 -> weaker.
    assert bench.classify(0.3, 0.15, 0.45) == "weaker"
    # CI overlaps 0.5 -> comparable.
    assert bench.classify(0.52, 0.42, 0.62) == "comparable"
    # Edge: CI touches 0.5 from below -> comparable.
    assert bench.classify(0.5, 0.4, 0.5) == "comparable"


# --- ISMCTS factory smoke -------------------------------------------


@pytest.mark.skipif(
    not _DEFAULT_WEIGHTS.is_file(),
    reason=f"v6 weights not at {_DEFAULT_WEIGHTS}",
)
def test_ismcts_factory_builds_and_chooses_legal_decision():
    """``_NNIsmctsConfig.build`` returns a SearchStrategy whose
    ``choose`` returns a decision in the adapter's legal set.
    Confirms the bench's factory shim isn't sub-classing wrong or
    misconfiguring the NN load path.
    """
    bench = _load_module()
    cfg = bench._NNIsmctsConfig(
        weights_path=str(_DEFAULT_WEIGHTS),
        # Tiny budget — we only need to confirm it runs and returns
        # a legal action.
        total_iterations=4,
        batch_size=1,
        with_policy=True,
        puct=True,
        hidden_sizes=(1024, 1024, 512),
    )
    strategy = cfg.build(seed=0)
    assert isinstance(strategy, SearchStrategy)

    engine = setup_game(
        [RandomAgent(rng=random.Random(1)),
         RandomAgent(rng=random.Random(2))],
        ["G", "R"], seed=0,
    )
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    while (
        len(adapter.legal_decisions()) == 1
        and not adapter.is_terminal()
    ):
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        pytest.skip("setup state went terminal during forced advance")

    legal = list(adapter.legal_decisions())
    decision = strategy.choose(adapter, adapter.active_player())
    assert decision in legal


# --- CLI smoke ------------------------------------------------------


def test_help_runs_cleanly_and_lists_flags():
    """``--help`` exits 0 and lists the major flags."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--help"],
        capture_output=True, text=True,
        env={
            **{k: v for k, v in __import__("os").environ.items()},
            "PYTHONPATH": str(_REPO_ROOT / "src"),
        },
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    for flag in (
        "--weights-path", "--n-games", "--budget",
        "--base-seed", "--out",
    ):
        assert flag in out, f"missing {flag} in --help output"


def test_parse_budget_helper_accepts_and_rejects():
    bench = _load_module()
    assert bench._parse_budget("4:200") == (4, 200)
    assert bench._parse_budget("2:50") == (2, 50)
    import argparse as ap
    for bad in ("foo", "4-200", "0:50", "4:0", "-4:200"):
        with pytest.raises(ap.ArgumentTypeError):
            bench._parse_budget(bad)


def test_load_metadata_handles_missing_metadata(tmp_path: Path):
    """Weights file with no sibling metadata.json returns benign
    defaults rather than raising."""
    bench = _load_module()
    fake_weights = tmp_path / "weights.pt"
    fake_weights.write_bytes(b"\x00")
    with_policy, hidden = bench._load_metadata_from_weights_path(
        fake_weights,
    )
    assert with_policy is False
    assert hidden is None


def test_load_metadata_reads_sibling_json(tmp_path: Path):
    bench = _load_module()
    fake_weights = tmp_path / "weights.pt"
    fake_weights.write_bytes(b"\x00")
    (tmp_path / "metadata.json").write_text(
        json.dumps({
            "with_policy": True,
            "hidden_sizes": [1024, 1024, 512],
        }),
        encoding="utf-8",
    )
    with_policy, hidden = bench._load_metadata_from_weights_path(
        fake_weights,
    )
    assert with_policy is True
    assert hidden == (1024, 1024, 512)


# --- BenchProgress wiring -------------------------------------------


def _fake_match_stats(
    *, challenger_wins: int, defender_wins: int,
    draws: int = 0, crashed: int = 0,
):
    """Build a ``MatchStats``-shaped object the bench's
    ``_run_pairwise`` will consume. The bench reads ``stats.games``
    (decided), ``stats.wins[0]/[1]``, ``stats.draws``,
    ``stats.crashed``, ``stats.avg_decisions``.
    """
    from mtg_bot.training.self_play import MatchStats

    return MatchStats(
        wins={0: challenger_wins, 1: defender_wins},
        draws=draws,
        crashed=crashed,
        games=challenger_wins + defender_wins,
        avg_decisions=42.0,
    )


def test_run_pairwise_with_progress_writes_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """``_run_pairwise(progress=...)`` must open a pairing on the
    BenchProgress tracker, push the totals, and finish the pairing
    cleanly. The on-disk JSON should reflect the completed pairing
    after the call returns.
    """
    from mtg_bot.training import BenchProgress

    bench = _load_module()

    # Replace ``run_match_parallel`` with a stub that returns a known
    # win count, so we can run the wiring without launching real
    # subprocess pools or NN evaluators.
    fake_stats = _fake_match_stats(
        challenger_wins=3, defender_wins=1, draws=0, crashed=0,
    )

    def _fake_run_match_parallel(**kwargs):
        return fake_stats

    monkeypatch.setattr(
        bench, "run_match_parallel", _fake_run_match_parallel,
    )

    progress_path = tmp_path / "bench_run.json"
    progress = BenchProgress(
        progress_path=progress_path,
        run_id="bench_run",
        weights_path="fake/v6/weights.pt",
        n_games_per_pairing=4,
        budgets=[(4, 200)],
    )
    progress.begin()

    result = bench._run_pairwise(
        challenger_label="ISMCTS-uniform",
        challenger_factory=lambda seed=0: None,
        defender_label="PIMC",
        defender_factory=lambda seed=0: None,
        n_games=4,
        base_seed=0,
        workers=1,
        progress=progress,
        samples=4,
        inner_nodes=200,
        total_iterations=800,
    )
    progress.finalize(status="completed")

    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "bench"
    assert payload["status"] == "completed"
    assert len(payload["pairings"]) == 1
    p = payload["pairings"][0]
    assert p["status"] == "completed"
    assert p["challenger"] == "ISMCTS-uniform"
    assert p["defender"] == "PIMC"
    assert p["challenger_wins"] == 3
    assert p["defender_wins"] == 1
    assert p["n_decided"] == 4
    assert p["samples"] == 4
    assert p["inner_nodes"] == 200
    assert p["total_iterations"] == 800
    assert result.challenger_wins == 3
    assert result.defender_wins == 1


def test_run_pairwise_progress_marks_failure_on_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """If ``run_match_parallel`` raises, the BenchProgress pairing
    should be closed with ``status="failed"`` so the UI doesn't
    show it stuck at running, and the original exception should
    propagate so the bench script still exits non-zero.
    """
    from mtg_bot.training import BenchProgress

    bench = _load_module()

    def _exploding_run_match_parallel(**kwargs):
        raise RuntimeError("synthetic worker pool failure")

    monkeypatch.setattr(
        bench, "run_match_parallel",
        _exploding_run_match_parallel,
    )

    progress = BenchProgress(
        progress_path=tmp_path / "boom.json",
        run_id="boom",
        weights_path="fake.pt",
        n_games_per_pairing=2,
        budgets=[(2, 50)],
    )
    progress.begin()

    with pytest.raises(RuntimeError, match="synthetic"):
        bench._run_pairwise(
            challenger_label="A",
            challenger_factory=lambda seed=0: None,
            defender_label="B",
            defender_factory=lambda seed=0: None,
            n_games=2,
            base_seed=0,
            workers=1,
            progress=progress,
        )
    payload = json.loads(
        (tmp_path / "boom.json").read_text(encoding="utf-8"),
    )
    p = payload["pairings"][0]
    assert p["status"] == "failed"


def test_help_advertises_progress_dir_flag():
    """``--help`` should advertise ``--progress-dir`` so operators
    discover the wiring."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--help"],
        capture_output=True, text=True,
        env={
            **{k: v for k, v in __import__("os").environ.items()},
            "PYTHONPATH": str(_REPO_ROOT / "src"),
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "--progress-dir" in proc.stdout
    assert "training_progress" in proc.stdout
