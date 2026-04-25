"""Round-robin tournament between recent registered NN versions.

Plays each pair of versions head-to-head N games (alternating seats
to remove first-mover advantage), aggregates a win-rate matrix, and
prints both the matrix and an Elo-derived rating per participant.

Usage::

    # Tournament between the last 8 versions, 10 games per pair, also
    # include the heuristic as a fixed reference point.
    python scripts/tournament.py --n-versions 8 --games-per-pair 10 \\
        --include-heuristic

    # Quick smoke (last 4, 4 games per pair, tiny PIMC)
    python scripts/tournament.py --n-versions 4 --games-per-pair 4 \\
        --samples 1 --nodes 8

By default the script caps participants at the last 32 versions
(per project convention — very old / weak versions aren't worth
the games). Adjust via ``--n-versions``.

Each pair plays ``2 * games-per-pair`` actual games — once with
each version as P0 and once as P1 — then results are summed. This
removes any P0/P1 asymmetry.

Pair count grows quadratically, so total game count is
``N * (N - 1) * games_per_pair`` for N participants. At recommend
defaults each game is ~30s, so the matrix gets expensive past ~10
participants × 10 games. Default values are chosen for tractability.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.search import (  # noqa: E402
    Budget, MCTS, NNEvaluator, PIMC,
)
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator  # noqa: E402
from mtg_bot.training import run_match  # noqa: E402
from mtg_bot.training.registry import Registry  # noqa: E402


_HEURISTIC_LABEL = "heuristic"
_INITIAL_ELO = 1500.0
_ELO_K = 24.0  # update strength; 24 is between chess (16) and online games (32)


def _make_pimc_factory(evaluator, samples: int, nodes: int):
    def factory(seed: int) -> PIMC:
        def inner_factory() -> MCTS:
            return MCTS(
                evaluator=evaluator,
                budget_factory=lambda: Budget(max_nodes=nodes),
                rng=random.Random(seed + 100),
            )
        return PIMC(
            inner_factory=inner_factory,
            samples=samples,
            rng=random.Random(seed + 200),
        )
    return factory


def _build_evaluator(label: str, registry: Registry):
    if label == _HEURISTIC_LABEL:
        return MtgHeuristicEvaluator()
    return NNEvaluator(weights_path=registry.weights_path(label))


def _expected_score(rating_a: float, rating_b: float) -> float:
    """Standard Elo expected-score formula. Output in (0, 1)."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _update_elo(
    elo: dict[str, float], a: str, b: str, score_a: float,
) -> None:
    """Update Elo for a single match result. ``score_a`` in [0, 1]
    (1 = win, 0.5 = draw, 0 = loss)."""
    expected = _expected_score(elo[a], elo[b])
    elo[a] += _ELO_K * (score_a - expected)
    elo[b] += _ELO_K * ((1 - score_a) - (1 - expected))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-root", type=Path, default=Path("trained_weights"),
        help="Registry root (default trained_weights/).",
    )
    parser.add_argument(
        "--n-versions", type=int, default=32,
        help=(
            "Cap participants at the last N registered versions. "
            "Default 32 — very old versions aren't worth the games."
        ),
    )
    parser.add_argument(
        "--games-per-pair", type=int, default=10,
        help=(
            "Games per side per pair (so 2x this many actual games "
            "with seat-swapping). Default 10."
        ),
    )
    parser.add_argument(
        "--samples", type=int, default=4,
        help="PIMC samples K (default 4).",
    )
    parser.add_argument(
        "--nodes", type=int, default=200,
        help="MCTS max_nodes per sub-search (default 200).",
    )
    parser.add_argument(
        "--include-heuristic", action="store_true",
        help="Add the heuristic evaluator as a fixed reference point.",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Base seed.",
    )
    args = parser.parse_args()

    registry = Registry(args.registry_root)
    versions = registry.latest_versions(args.n_versions)
    if not versions and not args.include_heuristic:
        sys.exit(
            f"No versions found in {args.registry_root} and "
            f"--include-heuristic not set. Nothing to play."
        )
    versions.reverse()  # oldest → newest for nicer display ordering
    participants = list(versions)
    if args.include_heuristic:
        participants.append(_HEURISTIC_LABEL)
    if len(participants) < 2:
        sys.exit(
            f"Tournament needs >= 2 participants; got {len(participants)}."
        )

    n = len(participants)
    n_pairs = n * (n - 1) // 2
    total_games = n_pairs * 2 * args.games_per_pair
    print(
        f"# tournament: {n} participants, {n_pairs} pairs, "
        f"{2 * args.games_per_pair} games/pair = {total_games} total"
    )
    print(
        f"# samples={args.samples} nodes={args.nodes} "
        f"registry={args.registry_root}"
    )
    print(f"# participants: {participants}")

    # Pre-build evaluators once (NNEvaluator load is the slow part).
    evaluators: dict[str, object] = {
        label: _build_evaluator(label, registry) for label in participants
    }

    # Win matrix: wins[a][b] = games a won against b.
    wins: dict[str, dict[str, int]] = {
        a: {b: 0 for b in participants} for a in participants
    }
    games_played: dict[str, dict[str, int]] = {
        a: {b: 0 for b in participants} for a in participants
    }
    elo: dict[str, float] = {a: _INITIAL_ELO for a in participants}

    started = time.perf_counter()
    pair_idx = 0
    for i in range(n):
        for j in range(i + 1, n):
            pair_idx += 1
            a, b = participants[i], participants[j]
            print(
                f"\n# [{pair_idx}/{n_pairs}] {a} vs {b}",
                flush=True,
            )
            # a as P0
            stats_ab = run_match(
                p0_factory=_make_pimc_factory(
                    evaluators[a], args.samples, args.nodes,
                ),
                p1_factory=_make_pimc_factory(
                    evaluators[b], args.samples, args.nodes,
                ),
                n_games=args.games_per_pair,
                base_seed=args.seed + pair_idx * 1_000,
            )
            # b as P0 (a as P1) — flip seats to remove first-mover effect
            stats_ba = run_match(
                p0_factory=_make_pimc_factory(
                    evaluators[b], args.samples, args.nodes,
                ),
                p1_factory=_make_pimc_factory(
                    evaluators[a], args.samples, args.nodes,
                ),
                n_games=args.games_per_pair,
                base_seed=args.seed + pair_idx * 1_000 + 500,
            )
            a_wins = stats_ab.wins[0] + stats_ba.wins[1]
            b_wins = stats_ab.wins[1] + stats_ba.wins[0]
            draws = stats_ab.draws + stats_ba.draws
            n_games_this_pair = a_wins + b_wins + draws
            wins[a][b] += a_wins
            wins[b][a] += b_wins
            games_played[a][b] += n_games_this_pair
            games_played[b][a] += n_games_this_pair
            print(
                f"  {a} {a_wins}-{b_wins}-{draws} {b}"
            )
            # Update Elo per pair (treat the whole pair as a single
            # observation with score = a_wins / (a_wins + b_wins),
            # ignoring draws). Simple but stable.
            decisive = a_wins + b_wins
            if decisive > 0:
                score_a = a_wins / decisive
                _update_elo(elo, a, b, score_a)

    elapsed = time.perf_counter() - started

    # ---- output ----------------------------------------------------------

    print(
        f"\n# Done in {elapsed:.1f}s ({elapsed / 60:.1f}m)."
    )

    # Win-rate matrix (rows = player, cols = opponent).
    name_w = max(8, max(len(p) for p in participants))
    print(f"\n## Win-rate matrix (row beats column)")
    header = " " * (name_w + 1) + " ".join(
        f"{p:>{name_w}}" for p in participants
    ) + f"  {'total':>9}"
    print(header)
    for a in participants:
        row_wins = sum(wins[a].values())
        row_games = sum(games_played[a].values())
        row_rate = row_wins / row_games if row_games else 0.0
        cells = []
        for b in participants:
            if a == b:
                cells.append(f"{'-':>{name_w}}")
                continue
            g = games_played[a][b]
            if g == 0:
                cells.append(f"{'-':>{name_w}}")
            else:
                rate = wins[a][b] / g
                cells.append(f"{rate:>{name_w}.0%}")
        print(
            f"{a:<{name_w}} " + " ".join(cells)
            + f"  {row_wins}/{row_games} ({row_rate:.0%})"
        )

    print(f"\n## Elo (K={int(_ELO_K)}, initial={int(_INITIAL_ELO)})")
    ranked = sorted(elo.items(), key=lambda kv: kv[1], reverse=True)
    for rank, (name, rating) in enumerate(ranked, start=1):
        print(f"  {rank:>2}. {name:<{name_w}}  {rating:>7.1f}")


if __name__ == "__main__":
    main()
