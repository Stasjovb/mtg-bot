"""Like ``repro_hang.py``, but prints per-decision wall time so we can
spot whether a single MCTS choose_with_visits is unbounded.

Wraps the inner game loop in a custom version that calls strategy
``choose_with_visits`` and records each call's elapsed time. Prints
the slowest 30 decisions and a histogram by elapsed bucket.

Triage tool, not production code.
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import random
import sys
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.decks import decks_from_json  # noqa: E402
from mtg_bot.search.engine_adapter import MtgGameStateAdapter  # noqa: E402
from mtg_bot.search.protocol import CHANCE_PLAYER  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402
from mtg_bot.training import NNPimcConfig, PimcConfig, Registry  # noqa: E402
from mtg_bot.training._worker_threads import (  # noqa: E402
    pin_worker_torch_threads,
)
from mtg_bot.training.data_gen import _sample_decks_for_game  # noqa: E402


def _resolve_meta(args) -> dict:
    if args.meta_json is None:
        return {
            "base_seed": args.seed,
            "game_idx": args.game_idx,
            "engine_seed": args.seed + args.game_idx,
        }
    with open(args.meta_json, "r", encoding="utf-8") as f:
        meta = json.load(f)
    if args.seed is not None:
        meta["base_seed"] = args.seed
    if args.game_idx is not None:
        meta["game_idx"] = args.game_idx
        meta["engine_seed"] = meta["base_seed"] + args.game_idx
    return meta


def _play_instrumented(
    adapter, strategies, rng, decision_cap, deadline,
):
    """Stripped-down loop. Returns
    (winner, n_decisions, slowest_calls, hist).

    slowest_calls is a list of (decision_idx, elapsed_sec, decision_str,
    n_legal) sorted by elapsed desc, capped at 30.
    """
    decision_idx = 0
    slowest: list = []
    hist = [0, 0, 0, 0, 0, 0, 0, 0]  # buckets: <0.1, 0.1-1, 1-5, 5-30,
                                     #          30-60, 60-120, 120-300, 300+
    t_total = time.perf_counter()
    while not adapter.is_terminal() and decision_idx < decision_cap:
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            decision = rng.choices(choices, weights=weights, k=1)[0]
        else:
            n_legal = len(list(adapter.legal_decisions()))
            t0 = time.perf_counter()
            visits = strategies[active].choose_with_visits(adapter, active)
            elapsed = time.perf_counter() - t0
            if visits:
                decision = max(visits.items(), key=lambda kv: kv[1])[0]
            else:
                decision = list(adapter.legal_decisions())[0]
            # Bucket
            bucket = (
                0 if elapsed < 0.1
                else 1 if elapsed < 1.0
                else 2 if elapsed < 5.0
                else 3 if elapsed < 30.0
                else 4 if elapsed < 60.0
                else 5 if elapsed < 120.0
                else 6 if elapsed < 300.0
                else 7
            )
            hist[bucket] += 1
            slowest.append((decision_idx, elapsed, repr(decision)[:80], n_legal))
            slowest.sort(key=lambda r: -r[1])
            slowest = slowest[:30]
            if elapsed > 5.0:
                print(
                    f"  [decision {decision_idx} active=P{active}] "
                    f"{elapsed:.2f}s, {n_legal} legal — {repr(decision)[:90]}",
                    flush=True,
                )
        adapter.apply(decision)
        decision_idx += 1
        if time.perf_counter() > deadline:
            print(
                f"  [DEADLINE] hit at decision {decision_idx} "
                f"({time.perf_counter() - t_total:.1f}s elapsed)",
                flush=True,
            )
            break

    if adapter.is_terminal():
        winner = adapter.winner()
    else:
        winner = None
    return winner, decision_idx, slowest, hist


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--meta-json", type=Path, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--game-idx", type=int, default=None)
    p.add_argument("--samples", type=int, default=4)
    p.add_argument("--nodes", type=int, default=200)
    p.add_argument("--deck-pool", type=Path, required=True)
    p.add_argument("--timeout-sec", type=float, default=600.0)
    p.add_argument("--nn-version", default=None)
    p.add_argument("--registry-root", type=Path, default=Path("trained_weights"))
    p.add_argument("--enable-mulligans", action="store_true")
    args = p.parse_args()

    meta = _resolve_meta(args)
    base_seed = meta["base_seed"]
    game_idx = meta["game_idx"]
    engine_seed = meta["engine_seed"]

    deck_pool = decks_from_json(args.deck_pool)
    deck_p0, deck_p1 = _sample_decks_for_game(deck_pool, game_idx, base_seed)

    if args.nn_version is not None:
        registry = Registry(args.registry_root)
        weights_path = registry.weights_path(args.nn_version)
        m = registry.load_metadata(args.nn_version)
        hidden_sizes = tuple(m.hidden_sizes) if m.hidden_sizes else None
        cfg = NNPimcConfig(
            weights_path=str(weights_path),
            samples=args.samples, inner_nodes=args.nodes,
            batch_size=32, with_policy=True, puct=True,
            hidden_sizes=hidden_sizes,
        )
        print(f"# NN-PUCT: version={args.nn_version} hidden_sizes={hidden_sizes}")
    else:
        cfg = PimcConfig(samples=args.samples, inner_nodes=args.nodes)
        print("# heuristic-PIMC")

    print(f"# base_seed={base_seed} game_idx={game_idx} "
          f"engine_seed={engine_seed} timeout={args.timeout_sec}s")

    enable_mulligans = (
        args.enable_mulligans
        or bool(meta.get("enable_mulligans", False))
    )
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(engine_seed + 1)),
            RandomAgent(rng=random.Random(engine_seed + 2)),
        ],
        decks=[deck_p0.cards, deck_p1.cards],
        seed=engine_seed,
        enable_mulligans=enable_mulligans,
    )
    if game_idx % 2 == 1:
        engine.active_player_idx = 1
        engine.priority_player_idx = 1
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    strategies = {
        0: cfg.build(base_seed + 100 * game_idx),
        1: cfg.build(base_seed + 100 * game_idx + 50),
    }
    pin_worker_torch_threads()
    rng = random.Random(base_seed + 100 * game_idx + 99)

    deadline = time.perf_counter() + args.timeout_sec
    started = time.perf_counter()
    winner, n_dec, slowest, hist = _play_instrumented(
        adapter, strategies, rng, decision_cap=4000, deadline=deadline,
    )
    elapsed = time.perf_counter() - started
    print(f"# DONE elapsed={elapsed:.1f}s winner={winner} decisions={n_dec}")
    bucket_labels = [
        "<0.1s", "0.1-1s", "1-5s", "5-30s",
        "30-60s", "60-120s", "120-300s", ">=300s",
    ]
    print("# decision wall-clock histogram:")
    for L, c in zip(bucket_labels, hist):
        print(f"  {L:>10}: {c:5d}")
    print("# slowest 30 decisions:")
    for idx, t, d, n in slowest:
        print(f"  decision {idx:5d}  {t:7.2f}s  n_legal={n:3d}  {d}")


if __name__ == "__main__":
    faulthandler.enable()
    main()
