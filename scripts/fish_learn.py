"""Forgetful Fish learning loop, step by step, on the user's 80-card list.

    # 1. Play games and SAVE training data (heuristic PIMC on both seats,
    #    or the newest registered net with --nn-version):
    PYTHONPATH=src MTG_BOT_CARD_POOL=fish python scripts/fish_learn.py gen \
        --games 200 --out-dir ../../fish-data/training_data_fish --tag gen0

    # 2. Train the structured net on everything in that folder and register
    #    the next version in the Fish registry (CPU is fine; slow but works):
    PYTHONPATH=src MTG_BOT_CARD_POOL=fish python scripts/fish_learn.py train \
        --data-dir ../../fish-data/training_data_fish \
        --registry-root ../../fish-data/trained_weights_fish --epochs 20

``gen`` writes one ``.npz`` with the structured tokens, policy targets and
game ids (``data_gen.save_dataset``; the shard is stamped with the active
card vocabulary, so run it with ``MTG_BOT_CARD_POOL=fish``). The deck pool
is one ``Deck`` tagged ``game_format="forgetful_fish"``: every game is the
shared-library Fish game (``formats.setup_args_for_decks``). ``train`` runs
Greg's trainer (``scripts/train_nn.py --architecture structured``).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

DEFAULT_DECKLIST = _HERE.parent / "data" / "forgetful_fish" / "decklist.txt"


def fish_deck_pool(decklist: Path):
    """The Fish pool: one ``Deck`` of the list, tagged forgetful_fish."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.decks import Deck
    from mtg_bot.formats.decklist import decklist_names

    names, unknown, unreadable = decklist_names(
        decklist.read_text(encoding="utf-8"), get_active_source().get_printings(),
    )
    if unknown or unreadable:
        raise SystemExit(
            f"decklist problems: unknown={unknown} unreadable={list(unreadable)} "
            "(run with MTG_BOT_CARD_POOL=fish)"
        )
    return [Deck(
        draft_id=f"fish:{decklist.name}", build_index=0, cards=sorted(names),
        game_format="forgetful_fish",
    )]


def _factory(args):
    from mtg_bot.training import PimcConfig

    if args.nn_version:
        import dataclasses
        import json

        from mtg_bot.worker_daemon_production_runner import _build_nn_pimc_config

        vdir = args.registry_root / args.nn_version
        metadata = json.loads((vdir / "metadata.json").read_text(encoding="utf-8"))
        config = _build_nn_pimc_config(vdir / "weights.pt", metadata)
        return dataclasses.replace(
            config, samples=args.samples, inner_nodes=args.nodes,
        ).build
    return PimcConfig(samples=args.samples, inner_nodes=args.nodes).build


def cmd_gen(args) -> Path:
    from mtg_bot.training import generate_training_data_parallel, save_dataset

    pool = fish_deck_pool(args.decklist)
    factory = _factory(args)
    started = time.perf_counter()
    out = generate_training_data_parallel(
        p0_factory=factory, p1_factory=factory,
        n_games=args.games, base_seed=args.seed, n_workers=args.workers,
        deck_pool=pool, with_policy=True, structured_tokens=True,
        with_game_ids=True, per_game_timeout_sec=args.per_game_timeout,
    )
    (features, outcomes, policy, masks, st_type, st_emb, st_scalars,
     st_mask, game_ids) = out
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / (
        f"{args.tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.npz"
    )
    save_dataset(
        features, outcomes, path, policy_targets=policy, action_masks=masks,
        structured_token_type=st_type, structured_token_emb_ids=st_emb,
        structured_token_scalars=st_scalars, structured_attention_mask=st_mask,
        game_ids=game_ids,
    )
    print(
        f"{args.games} games, {len(outcomes)} rows in "
        f"{time.perf_counter() - started:.0f}s -> {path}"
    )
    return path


def cmd_train(args) -> int:
    cmd = [
        sys.executable, "-u", str(_HERE / "train_nn.py"),
        "--data-dir", str(args.data_dir),
        "--registry-root", str(args.registry_root),
        "--architecture", "structured",
        "--epochs", str(args.epochs),
        "--device", "cpu",
        "--progress-dir", str(args.registry_root / "progress"),
        "--notes", args.notes,
    ]
    print(" ".join(cmd))
    return subprocess.call(cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="play Fish games and save training data")
    g.add_argument("--games", type=int, default=20)
    g.add_argument("--out-dir", type=Path, required=True)
    g.add_argument("--tag", default="gen")
    g.add_argument("--decklist", type=Path, default=DEFAULT_DECKLIST)
    g.add_argument("--workers", type=int, default=None)
    g.add_argument("--samples", type=int, default=2)
    g.add_argument("--nodes", type=int, default=50)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--per-game-timeout", type=float, default=600.0)
    g.add_argument("--nn-version", default=None,
                   help="drive both seats with this registered net (NN PIMC)")
    g.add_argument("--registry-root", type=Path, default=Path("trained_weights_fish"))
    t = sub.add_parser("train", help="train the structured net, register a version")
    t.add_argument("--data-dir", type=Path, required=True)
    t.add_argument("--registry-root", type=Path, required=True)
    t.add_argument("--epochs", type=int, default=20)
    t.add_argument("--notes", default="Forgetful Fish (user's 80-card list)")
    args = ap.parse_args(argv)
    if args.cmd == "gen":
        cmd_gen(args)
        return 0
    return cmd_train(args)


if __name__ == "__main__":
    raise SystemExit(main())
