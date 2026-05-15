"""Single-game reproducer for the data-gen hang.

Loads a meta.json from a hang dump (or accepts explicit seed +
game_idx flags), rebuilds the same engine + NN-PIMC config, runs ONE
game in this process with a self-imposed timeout, and reports
elapsed wall + completion status.

If the game hangs, ``faulthandler.dump_traceback_later`` fires after
``--timeout-sec`` and writes a fresh traceback to stderr.

Triage tool, not production code. Mirrors data_gen._generate_one_game_data
just enough to reproduce the engine state at the same (base_seed,
game_idx) pair.
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import random
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.decks import decks_from_json  # noqa: E402
from mtg_bot.search.engine_adapter import MtgGameStateAdapter  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402
from mtg_bot.training import NNPimcConfig, PimcConfig, Registry  # noqa: E402
from mtg_bot.training._worker_threads import (  # noqa: E402
    pin_worker_torch_threads,
)
from mtg_bot.training.data_gen import (  # noqa: E402
    _play_one_game_recording, _sample_decks_for_game,
)


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


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--meta-json", type=Path, default=None,
                   help="Path to a hang dump's .json. Overrides --seed/--game-idx if set.")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--game-idx", type=int, default=None)
    p.add_argument("--samples", type=int, default=4)
    p.add_argument("--nodes", type=int, default=200)
    p.add_argument("--deck-pool", type=Path, required=True)
    p.add_argument("--timeout-sec", type=float, default=180.0)
    p.add_argument("--nn-version", default=None,
                   help="Registered version (e.g. v6). Omit for heuristic-PIMC.")
    p.add_argument("--registry-root", type=Path, default=Path("trained_weights"))
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

    # Mulligans are always on post-feature/always-on-mulligans;
    # setup_game's default fires.
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(engine_seed + 1)),
            RandomAgent(rng=random.Random(engine_seed + 2)),
        ],
        decks=[deck_p0.cards, deck_p1.cards],
        seed=engine_seed,
    )
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    strategies = {
        0: cfg.build(base_seed + 100 * game_idx),
        1: cfg.build(base_seed + 100 * game_idx + 50),
    }
    pin_worker_torch_threads()
    rng = random.Random(base_seed + 100 * game_idx + 99)

    # Arm an automatic faulthandler dump if we hang past timeout.
    faulthandler.dump_traceback_later(args.timeout_sec, exit=False, file=sys.stderr)

    started = time.perf_counter()
    try:
        winner, samples = _play_one_game_recording(
            adapter, strategies, rng,
            decision_cap=4000, sample_every=1, replay_recorder=None,
        )
        elapsed = time.perf_counter() - started
        print(f"# COMPLETED in {elapsed:.1f}s. winner={winner} samples={len(samples)}")
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - started
        print(f"# FAILED after {elapsed:.1f}s: "
              f"{type(exc).__name__}: {exc}")
        raise
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
