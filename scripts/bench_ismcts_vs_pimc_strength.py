"""Strategic-strength A/B benchmark: ISMCTS vs PIMC, matched budget.

Phase 4 of the ISMCTS migration plan needs a head-to-head win-rate
comparison before we cut over from PIMC to ISMCTS at the production
call sites. The existing ``bench_ismcts_vs_pimc.py`` measures wall-
clock per ``choose_with_visits`` call but doesn't play games — same
speed could mask either a strength gain or a regression.

This script:

1. Loads NN weights once and constructs two factories from the same
   weights — a PIMC factory at samples=K x inner_nodes=N and an
   ISMCTS factory at total_iterations=K*N (matched total search
   nodes). Identical evaluator, identical NN forward path.
2. Runs ``run_match_parallel(..., alternate_seats=True)`` so seat-
   advantage bias is neutralized — odd-indexed games swap factories
   and the results are remapped server-side.
3. Computes ISMCTS's win rate and a Wilson 95% confidence interval
   (no scipy.stats — closed-form Wilson is exact enough for this).
   Reports stronger / comparable / weaker based on whether the CI
   crosses 50%.
4. Also runs the per-call wall-clock bench at the matched budgets so
   one report shows speed AND strength.

Two budget points by default (production + fast) so we know whether
the verdict holds at scale and at iteration speed.

Operator-facing — DO NOT run from inside an agent or in CI; 200
games at production budget is ~5-15min on the master box.

Usage::

    python scripts/bench_ismcts_vs_pimc_strength.py \\
        --weights-path ../mtg-bot/trained_weights/v6/weights.pt \\
        --n-games 200

JSON report lands at ``--out`` (default
``bench_results/ismcts_vs_pimc_<stamp>.json``).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.search import (  # noqa: E402
    Budget, ISMCTS, MtgGameStateAdapter,
)
from mtg_bot.search.nn_evaluator import NNEvaluator  # noqa: E402
from mtg_bot.search.strategy import SearchStrategy  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402
from mtg_bot.training.config import NNPimcConfig  # noqa: E402
from mtg_bot.training.self_play import run_match_parallel  # noqa: E402


# Default points at the v6 weights in the main checkout. The
# worktree's own ``trained_weights/`` doesn't exist (registry is
# kept in main); this path resolves from ``scripts/`` →
# ``ismcts-ab-bench/`` (parents[1]) → ``mtg-bot-worktrees/``
# (parents[2]) → sibling ``Projects/`` (parents[3]) →
# ``Projects/mtg-bot/``.
_DEFAULT_WEIGHTS = (
    Path(__file__).resolve().parents[3]
    / "mtg-bot" / "trained_weights" / "v6" / "weights.pt"
)


# --------------------------------------------------------------------
# ISMCTS strategy factory
#
# Mirrors NNPimcConfig.build's pattern: a frozen dataclass that pickles
# cleanly across the multiprocessing.Pool spawn boundary, with a bound
# .build method that workers call to construct the live strategy. We
# keep this LOCAL to the bench (not in NNPimcConfig) per the task
# instructions — Phase 4 owns the production-config wiring; this is
# bench-only scaffolding.
# --------------------------------------------------------------------


@dataclass(frozen=True)
class _NNIsmctsConfig:
    """ISMCTS strategy config backed by saved NN weights.

    Total iteration budget = ``total_iterations`` (matched against
    PIMC's ``samples * inner_nodes`` at the call site).
    ``with_policy`` / ``puct`` / ``hidden_sizes`` mirror NNPimcConfig
    so the bench can drive the same NN through both search wrappers
    with identical evaluator settings.

    ``use_belief_weighted=True`` swaps the ISMCTS ``determinize_fn``
    callback from the uniform sampler to ``BeliefWeightedDeterminizer``
    (Phase 6); the determinizer is constructed with an empty
    played_history that the bench's game loop populates per-game via
    ``ISMCTS.observe_action`` (see Phase 6.5 wireup in
    ``self_play._play_capped_game``).
    """

    weights_path: str
    total_iterations: int
    batch_size: int = 32
    with_policy: bool = True
    puct: bool = True
    hidden_sizes: Optional[tuple[int, ...]] = None
    use_belief_weighted: bool = False

    def build(self, seed: int = 0) -> SearchStrategy:
        eval_kwargs: dict[str, Any] = {
            "weights_path": Path(self.weights_path),
            "with_policy": self.with_policy,
        }
        if self.hidden_sizes is not None:
            eval_kwargs["hidden_sizes"] = self.hidden_sizes
        evaluator = NNEvaluator(**eval_kwargs)
        total = self.total_iterations
        ismcts_kwargs: dict[str, Any] = {
            "evaluator": evaluator,
            "budget_factory": lambda: Budget(max_nodes=total),
            "rng": random.Random(seed + 300),
            "batch_size": self.batch_size,
            "puct": self.puct,
        }
        if self.use_belief_weighted:
            from mtg_bot.search.belief import (
                BeliefWeightedDeterminizer,
            )
            ismcts_kwargs["determinize_fn"] = BeliefWeightedDeterminizer(
                opponent_policy_evaluator=evaluator,
            )
        return ISMCTS(**ismcts_kwargs)


# --------------------------------------------------------------------
# Wilson 95% confidence interval for a binomial proportion
# --------------------------------------------------------------------


def wilson_interval(
    successes: int, trials: int, z: float = 1.96,
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Closed-form, no scipy needed. Reference: Newcombe 1998, "Two-
    sided confidence intervals for the single proportion." For a
    fair-coin point estimate of 0.5 with N=100, returns approximately
    (0.404, 0.596) at z=1.96 (95% confidence).

    ``trials==0`` returns ``(0.0, 1.0)`` (no information). ``z``
    defaults to 1.96 (two-sided 95%); pass ``z=2.576`` for 99%.
    """
    if trials <= 0:
        return 0.0, 1.0
    if successes < 0 or successes > trials:
        raise ValueError(
            f"successes ({successes}) must be in [0, trials={trials}]"
        )
    n = float(trials)
    p_hat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    margin = (
        z * math.sqrt((p_hat * (1.0 - p_hat) + z2 / (4.0 * n)) / n)
        / denom
    )
    return center - margin, center + margin


def classify(
    win_rate: float, ci_low: float, ci_high: float,
) -> str:
    """Map (win_rate, CI) to a verdict string against the 50% null.

    'stronger': CI strictly above 0.5.
    'weaker':   CI strictly below 0.5.
    'comparable': CI overlaps 0.5.
    """
    if ci_low > 0.5:
        return "stronger"
    if ci_high < 0.5:
        return "weaker"
    return "comparable"


# --------------------------------------------------------------------
# Wall-clock bench (mirrors bench_ismcts_vs_pimc.py at the matched
# budgets used here, so the JSON report carries both perspectives).
# --------------------------------------------------------------------


def _make_state(seed: int) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    adapter = MtgGameStateAdapter(state)
    while (
        len(adapter.legal_decisions()) == 1
        and not adapter.is_terminal()
    ):
        adapter.apply(adapter.legal_decisions()[0])
    return adapter


def wallclock_bench(
    pimc_cfg: NNPimcConfig,
    ismcts_cfg: _NNIsmctsConfig,
    seeds: list[int],
) -> dict[str, Any]:
    """Time one ``choose_with_visits`` per seed for each strategy.

    Builds fresh strategies per seed (the bench is interested in
    realistic per-call cost, not the amortized warm-cache cost). One
    warmup pass per seed before timing to settle JIT / lazy imports.
    """
    pimc_times: list[float] = []
    ismcts_times: list[float] = []
    for seed in seeds:
        adapter = _make_state(seed)
        if (
            adapter.is_terminal()
            or len(adapter.legal_decisions()) <= 1
        ):
            continue
        pimc = pimc_cfg.build(seed=seed)
        ismcts = ismcts_cfg.build(seed=seed)
        pimc.choose_with_visits(adapter, adapter.active_player())
        ismcts.choose_with_visits(adapter, adapter.active_player())
        t0 = time.perf_counter()
        pimc.choose_with_visits(adapter, adapter.active_player())
        pimc_times.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        ismcts.choose_with_visits(adapter, adapter.active_player())
        ismcts_times.append(time.perf_counter() - t0)
    return {
        "seeds": seeds,
        "pimc_seconds_per_call": pimc_times,
        "ismcts_seconds_per_call": ismcts_times,
        "pimc_median_ms": (
            statistics.median(pimc_times) * 1000.0 if pimc_times else None
        ),
        "ismcts_median_ms": (
            statistics.median(ismcts_times) * 1000.0
            if ismcts_times else None
        ),
    }


# --------------------------------------------------------------------
# Match runner
# --------------------------------------------------------------------


@dataclass
class _PairwiseResult:
    """One pairwise A/B match's stats — ``challenger`` plays seat 0,
    ``defender`` plays seat 1, seats are alternated. Win-rate is from
    the challenger's perspective; verdict classifies the challenger
    against the 50% null."""

    challenger: str
    defender: str
    n_games: int
    decided_games: int
    crashed: int
    draws: int
    challenger_wins: int
    defender_wins: int
    challenger_win_rate: float
    ci_low: float
    ci_high: float
    verdict: str
    avg_decisions: float
    elapsed_seconds: float


@dataclass
class _BudgetResult:
    """One budget-point's results in the JSON report.

    Two-way mode populates ``pairwise`` with one entry: ISMCTS-uniform
    vs PIMC. Three-way mode (``--include-belief``) adds two more:
    ISMCTS-belief vs PIMC, and ISMCTS-belief vs ISMCTS-uniform. All
    pairwise verdicts are reported so the operator can read both the
    "is belief weighting better than uniform?" and "is belief weighting
    better than PIMC?" signals from one report.
    """

    samples: int
    inner_nodes: int
    total_iterations: int
    n_games: int
    pairwise: list[_PairwiseResult] = field(default_factory=list)
    wallclock: dict[str, Any] = field(default_factory=dict)


def _run_pairwise(
    *,
    challenger_label: str,
    challenger_factory,
    defender_label: str,
    defender_factory,
    n_games: int,
    base_seed: int,
    workers: Optional[int],
) -> _PairwiseResult:
    """Play one alternating-seats A/B match and return a
    ``_PairwiseResult`` from the challenger's POV. Challenger plays
    seat 0; ``run_match_parallel`` with ``alternate_seats=True`` swaps
    seats on odd games and remaps the winner so ``wins[0]`` always
    means "challenger won."
    """
    print(
        f"# A/B: {challenger_label} (seat 0) vs {defender_label} "
        f"(seat 1) over {n_games} games (alternating seats)",
        file=sys.stderr, flush=True,
    )
    started = time.perf_counter()
    stats = run_match_parallel(
        p0_factory=challenger_factory,
        p1_factory=defender_factory,
        n_games=n_games,
        base_seed=base_seed,
        n_workers=workers,
        alternate_seats=True,
    )
    elapsed = time.perf_counter() - started

    decided = stats.games
    challenger_wins = stats.wins.get(0, 0)
    defender_wins = stats.wins.get(1, 0)
    win_rate = challenger_wins / decided if decided else 0.0
    ci_low, ci_high = wilson_interval(challenger_wins, decided)
    verdict = classify(win_rate, ci_low, ci_high)

    print(
        f"# Done in {elapsed:.1f}s ({elapsed / 60:.1f}m). "
        f"{challenger_label} won {challenger_wins}, "
        f"{defender_label} won {defender_wins}, "
        f"draws {stats.draws}, crashed {stats.crashed} / decided "
        f"{decided}.",
        file=sys.stderr, flush=True,
    )
    print(
        f"# {challenger_label} win rate: {win_rate:.1%}  Wilson 95% "
        f"CI: [{ci_low:.1%}, {ci_high:.1%}]  → {challenger_label} "
        f"is {verdict.upper()} vs {defender_label}",
        file=sys.stderr, flush=True,
    )

    return _PairwiseResult(
        challenger=challenger_label,
        defender=defender_label,
        n_games=n_games,
        decided_games=decided,
        crashed=stats.crashed,
        draws=stats.draws,
        challenger_wins=challenger_wins,
        defender_wins=defender_wins,
        challenger_win_rate=win_rate,
        ci_low=ci_low,
        ci_high=ci_high,
        verdict=verdict,
        avg_decisions=stats.avg_decisions,
        elapsed_seconds=elapsed,
    )


def run_one_budget(
    *,
    weights_path: Path,
    samples: int,
    inner_nodes: int,
    n_games: int,
    base_seed: int,
    workers: Optional[int],
    nn_batch_size: int,
    metadata_with_policy: bool,
    metadata_hidden_sizes: Optional[tuple[int, ...]],
    wallclock_seeds: list[int],
    include_belief: bool = False,
) -> _BudgetResult:
    """Play matched-budget A/B match(es) and report stats.

    Two-way (default): ISMCTS-uniform vs PIMC.
    Three-way (``include_belief=True``): ISMCTS-uniform vs PIMC,
        ISMCTS-belief vs PIMC, ISMCTS-belief vs ISMCTS-uniform.

    PIMC runs at (K=samples, N=inner_nodes); both ISMCTS variants run
    at total_iterations=K*N. Belief weighting doesn't change the
    iteration count (it changes the per-iteration sampling
    distribution).
    """
    if n_games % 2 != 0:
        raise ValueError(
            f"n_games must be even for clean seat alternation; "
            f"got {n_games}"
        )
    total_iterations = samples * inner_nodes

    pimc_cfg = NNPimcConfig(
        weights_path=str(weights_path),
        samples=samples,
        inner_nodes=inner_nodes,
        batch_size=nn_batch_size,
        with_policy=metadata_with_policy,
        puct=metadata_with_policy,
        hidden_sizes=metadata_hidden_sizes,
    )
    ismcts_uniform_cfg = _NNIsmctsConfig(
        weights_path=str(weights_path),
        total_iterations=total_iterations,
        batch_size=nn_batch_size,
        with_policy=metadata_with_policy,
        puct=metadata_with_policy,
        hidden_sizes=metadata_hidden_sizes,
    )
    ismcts_belief_cfg: Optional[_NNIsmctsConfig] = None
    if include_belief:
        ismcts_belief_cfg = _NNIsmctsConfig(
            weights_path=str(weights_path),
            total_iterations=total_iterations,
            batch_size=nn_batch_size,
            with_policy=metadata_with_policy,
            puct=metadata_with_policy,
            hidden_sizes=metadata_hidden_sizes,
            use_belief_weighted=True,
        )

    pairwise_results: list[_PairwiseResult] = []

    pairwise_results.append(_run_pairwise(
        challenger_label="ISMCTS-uniform",
        challenger_factory=ismcts_uniform_cfg.build,
        defender_label="PIMC",
        defender_factory=pimc_cfg.build,
        n_games=n_games,
        base_seed=base_seed,
        workers=workers,
    ))

    if include_belief:
        # Distinct base_seed offsets per pairwise so the three
        # matches don't share game-seed sequences and end up
        # coupled in their decisions.
        pairwise_results.append(_run_pairwise(
            challenger_label="ISMCTS-belief",
            challenger_factory=ismcts_belief_cfg.build,
            defender_label="PIMC",
            defender_factory=pimc_cfg.build,
            n_games=n_games,
            base_seed=base_seed + 1_000_000,
            workers=workers,
        ))
        pairwise_results.append(_run_pairwise(
            challenger_label="ISMCTS-belief",
            challenger_factory=ismcts_belief_cfg.build,
            defender_label="ISMCTS-uniform",
            defender_factory=ismcts_uniform_cfg.build,
            n_games=n_games,
            base_seed=base_seed + 2_000_000,
            workers=workers,
        ))

    wallclock = wallclock_bench(pimc_cfg, ismcts_uniform_cfg, wallclock_seeds)
    if wallclock["pimc_median_ms"] is not None:
        print(
            f"# wall-clock: PIMC median "
            f"{wallclock['pimc_median_ms']:.1f}ms / call, ISMCTS "
            f"median {wallclock['ismcts_median_ms']:.1f}ms / call "
            f"(over {len(wallclock['seeds'])} seeds)",
            file=sys.stderr, flush=True,
        )

    return _BudgetResult(
        samples=samples,
        inner_nodes=inner_nodes,
        total_iterations=total_iterations,
        n_games=n_games,
        pairwise=pairwise_results,
        wallclock=wallclock,
    )


# --------------------------------------------------------------------
# CLI entry
# --------------------------------------------------------------------


def _parse_budget(s: str) -> tuple[int, int]:
    """Parse ``K:N`` -> (samples=K, inner_nodes=N). Raises on malformed."""
    try:
        k_str, n_str = s.split(":")
        k, n = int(k_str), int(n_str)
    except (ValueError, AttributeError) as exc:
        raise argparse.ArgumentTypeError(
            f"--budget must be 'samples:inner_nodes' (e.g. '4:200'); "
            f"got {s!r}"
        ) from exc
    if k <= 0 or n <= 0:
        raise argparse.ArgumentTypeError(
            f"--budget components must be positive; got {s!r}"
        )
    return k, n


def _load_metadata_from_weights_path(
    weights_path: Path,
) -> tuple[bool, Optional[tuple[int, ...]]]:
    """Best-effort load of with_policy / hidden_sizes from a sibling
    metadata.json. Registry layout: ``trained_weights/<ver>/weights.pt``
    + ``trained_weights/<ver>/metadata.json``.
    """
    meta_path = weights_path.parent / "metadata.json"
    if not meta_path.is_file():
        return False, None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None
    with_policy = bool(meta.get("with_policy", False))
    hidden = meta.get("hidden_sizes")
    hidden_sizes = (
        tuple(int(x) for x in hidden) if hidden is not None else None
    )
    return with_policy, hidden_sizes


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--weights-path", type=Path, default=_DEFAULT_WEIGHTS,
        help=(
            "Path to the NN weights .pt file. Defaults to v6 in the "
            "main checkout's trained_weights/. Both PIMC and ISMCTS "
            "load the same weights — the comparison isolates the "
            "search algorithm."
        ),
    )
    parser.add_argument(
        "--n-games", type=int, default=200,
        help=(
            "Games per budget point (default 200). Must be even — "
            "seat alternation requires it. 200 games gives a Wilson "
            "95%% CI half-width of ~7pp at 50%% true rate."
        ),
    )
    parser.add_argument(
        "--base-seed", type=int, default=0,
        help="Base seed for game-RNG / strategy-RNG derivation.",
    )
    parser.add_argument(
        "--budget", type=_parse_budget, action="append",
        default=None,
        help=(
            "Budget point as 'samples:inner_nodes' (e.g. '4:200'). "
            "Repeatable. PIMC runs at K=samples, N=inner_nodes; "
            "ISMCTS runs at total_iterations=K*N. Default: '4:200' "
            "(production) and '2:50' (fast) — pass --budget once or "
            "more to override."
        ),
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help=(
            "multiprocessing.Pool worker count. Default: "
            "cpu_count() - 2."
        ),
    )
    parser.add_argument(
        "--nn-batch-size", type=int, default=32,
        help=(
            "Batched-leaf-evaluation size used by both PIMC's inner "
            "MCTS and ISMCTS. Default 32 (matches evaluate_nn.py)."
        ),
    )
    parser.add_argument(
        "--with-policy", dest="with_policy", default=None,
        action="store_true",
        help=(
            "Force the dual-head NN load path (with_policy=True). "
            "Auto-detected from sibling metadata.json by default; "
            "pass to override."
        ),
    )
    parser.add_argument(
        "--no-with-policy", dest="with_policy", action="store_false",
        help="Force the value-only NN load path (with_policy=False).",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help=(
            "JSON report path. Default: "
            "bench_results/ismcts_vs_pimc_<UTC stamp>.json"
        ),
    )
    parser.add_argument(
        "--wallclock-seeds", type=int, nargs="*",
        default=[11, 42, 77, 99, 2026],
        help=(
            "Seeds for the per-call wall-clock bench. Default 5 "
            "seeds; pass an empty list to disable."
        ),
    )
    parser.add_argument(
        "--include-belief", action="store_true",
        help=(
            "Run a 3-way comparison instead of the default 2-way: "
            "PIMC vs ISMCTS-uniform vs ISMCTS-belief. Adds two extra "
            "matches per budget point — ISMCTS-belief vs PIMC and "
            "ISMCTS-belief vs ISMCTS-uniform — so the report carries "
            "all three pairwise verdicts. Off by default; the 2-way "
            "PIMC vs ISMCTS-uniform comparison still gates Phase 5 "
            "deletion of PIMC. Use this flag when bench-driving "
            "Phase 6's belief-weighted determinizer."
        ),
    )
    args = parser.parse_args(argv)

    if not args.weights_path.is_file():
        parser.error(
            f"--weights-path {args.weights_path} not found. Pass an "
            f"explicit path to a .pt weights file."
        )
    if args.n_games <= 0 or args.n_games % 2 != 0:
        parser.error(
            f"--n-games must be a positive even integer; got "
            f"{args.n_games}"
        )

    budgets = args.budget or [(4, 200), (2, 50)]
    metadata_with_policy, metadata_hidden_sizes = (
        _load_metadata_from_weights_path(args.weights_path)
    )
    if args.with_policy is not None:
        metadata_with_policy = args.with_policy

    print(
        f"# weights: {args.weights_path}\n"
        f"# with_policy={metadata_with_policy} "
        f"hidden_sizes={metadata_hidden_sizes}\n"
        f"# budgets: {budgets}\n"
        f"# n_games per budget: {args.n_games}",
        file=sys.stderr, flush=True,
    )

    results: list[_BudgetResult] = []
    overall_started = time.perf_counter()
    for samples, inner_nodes in budgets:
        result = run_one_budget(
            weights_path=args.weights_path,
            samples=samples,
            inner_nodes=inner_nodes,
            n_games=args.n_games,
            base_seed=args.base_seed,
            workers=args.workers,
            nn_batch_size=args.nn_batch_size,
            metadata_with_policy=metadata_with_policy,
            metadata_hidden_sizes=metadata_hidden_sizes,
            wallclock_seeds=list(args.wallclock_seeds),
            include_belief=args.include_belief,
        )
        results.append(result)
    overall_elapsed = time.perf_counter() - overall_started

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out or (
        Path("bench_results") / f"ismcts_vs_pimc_{stamp}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "stamp": stamp,
        "weights_path": str(args.weights_path),
        "with_policy": metadata_with_policy,
        "hidden_sizes": (
            list(metadata_hidden_sizes)
            if metadata_hidden_sizes is not None else None
        ),
        "n_games_per_budget": args.n_games,
        "base_seed": args.base_seed,
        "nn_batch_size": args.nn_batch_size,
        "workers": args.workers,
        "include_belief": args.include_belief,
        "matched_budget_formula": (
            "ismcts.total_iterations = pimc.samples * pimc.inner_nodes"
        ),
        "overall_elapsed_seconds": overall_elapsed,
        "budgets": [asdict(r) for r in results],
    }
    out_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"# wrote {out_path}", file=sys.stderr, flush=True)
    print(json.dumps({"report_path": str(out_path)}))


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
