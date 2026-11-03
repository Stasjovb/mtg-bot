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

    # 3. Or all of it, round after round (play with the current best,
    #    train the next version, keep it only if it beats the best):
    PYTHONPATH=src MTG_BOT_CARD_POOL=fish python scripts/fish_learn.py loop \
        --rounds 3 --until 07:00 --threads 8 \
        --data-dir ../../fish-data/training_data_fish \
        --registry-root ../../fish-data/trained_weights_fish

``gen`` writes one ``.npz`` with the structured tokens, policy targets and
game ids (``data_gen.save_dataset``; the shard is stamped with the active
card vocabulary, so run it with ``MTG_BOT_CARD_POOL=fish``). It keeps every
row with a real choice and ``--keep-other`` of the forced-move and
value-only rows (``thin_rows``). The deck pool
is one ``Deck`` tagged ``game_format="forgetful_fish"``: every game is the
shared-library Fish game (``formats.setup_args_for_decks``). ``train`` runs
Greg's trainer (``scripts/train_nn.py --architecture structured``).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
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


def _version_factory(version, registry_root: Path, samples: int, nodes: int):
    """PIMC factory: ``version`` = a registered net (NN-PIMC with its
    metadata's architecture), ``"heuristic"`` / ``None`` = heuristic PIMC."""
    from mtg_bot.training import PimcConfig

    if version and version != "heuristic":
        import dataclasses
        import json

        from mtg_bot.worker_daemon_production_runner import _build_nn_pimc_config

        vdir = registry_root / version
        metadata = json.loads((vdir / "metadata.json").read_text(encoding="utf-8"))
        config = _build_nn_pimc_config(vdir / "weights.pt", metadata)
        return dataclasses.replace(config, samples=samples, inner_nodes=nodes).build
    return PimcConfig(samples=samples, inner_nodes=nodes).build


def _factory(args):
    return _version_factory(args.nn_version, args.registry_root, args.samples, args.nodes)


def thin_rows(arrays, keep_other: float, rng):
    """Keep every row whose action mask has 2+ legal actions (a real
    choice) and a ``keep_other`` fraction of the rest: forced moves and
    the non-acting viewer's value-only rows. A Fish game records ~1200
    rows, ~90% of them one of those; they repeat the same game outcome
    and make the trainer memorise games instead of learning."""
    import numpy as np

    masks = arrays[3]
    keep = (masks.sum(axis=1) > 1) | (rng.random(masks.shape[0]) < keep_other)
    return tuple(np.asarray(a)[keep] for a in arrays)


# Positions of the structured token arrays (token type, embedding ids,
# scalars, attention mask) in ``generate_training_data_parallel``'s
# output: axis 1 is the token axis, padded with zeros to the chunk's
# longest row.
_TOKEN_ARRAYS = (4, 5, 6, 7)


def concat_parts(parts):
    """Concatenate per-chunk outputs row-wise, zero-padding the token
    arrays to the widest chunk (the generator pads per call)."""
    import numpy as np

    width = max(p[4].shape[1] for p in parts)
    cols = []
    for i, col in enumerate(zip(*parts)):
        if i in _TOKEN_ARRAYS:
            col = [
                np.pad(a, [(0, 0), (0, width - a.shape[1])]
                       + [(0, 0)] * (a.ndim - 2))
                for a in col
            ]
        cols.append(np.concatenate(col))
    return tuple(cols)


def cmd_gen(args) -> Path:
    import numpy as np

    from mtg_bot.training import generate_training_data_parallel, save_dataset

    pool = fish_deck_pool(args.decklist)
    factory = _factory(args)
    rng = np.random.default_rng(args.seed)
    started = time.perf_counter()
    parts = []
    # Chunks bound the memory of the unthinned rows (~30 KB each).
    for start in range(0, args.games, args.chunk_games):
        out = list(generate_training_data_parallel(
            p0_factory=factory, p1_factory=factory,
            n_games=min(args.chunk_games, args.games - start),
            base_seed=args.seed + start, n_workers=args.workers,
            deck_pool=pool, with_policy=True, structured_tokens=True,
            with_game_ids=True, per_game_timeout_sec=args.per_game_timeout,
        ))
        out[-1] = out[-1] + start  # game ids unique across the file
        parts.append(thin_rows(out, args.keep_other, rng))
        print(f"  {min(start + args.chunk_games, args.games)}/{args.games} games",
              flush=True)
    (features, outcomes, policy, masks, st_type, st_emb, st_scalars,
     st_mask, game_ids) = concat_parts(parts)
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


def cmd_eval(args) -> tuple[float, tuple[int, int, int]]:
    """``--new`` vs ``--old`` on the Fish list, seats alternating; prints
    and returns the new side's score (wins + draws / 2) / games and its
    ``(wins, losses, draws)``."""
    from mtg_bot.training.self_play import run_match_parallel

    stats = run_match_parallel(
        _version_factory(args.new, args.registry_root, args.samples, args.nodes),
        _version_factory(args.old, args.registry_root, args.samples, args.nodes),
        n_games=args.games, base_seed=args.seed, n_workers=args.workers,
        deck_pool=fish_deck_pool(args.decklist), alternate_seats=True,
        per_game_timeout_sec=args.per_game_timeout,
    )
    wld = (stats.wins[0], stats.wins[1], stats.draws)
    played = sum(wld)
    score = (wld[0] + 0.5 * wld[2]) / played if played else 0.0
    print(
        f"{args.new} vs {args.old}: {wld[0]}-{wld[1]}-{wld[2]} "
        f"(W-L-D over {played} games) -> score {score:.3f}"
    )
    return score, wld


def cmd_train(args) -> int:
    """Run Greg's structured trainer; exit 0 = a version was registered,
    ``train._GATE_REJECT_EXIT_CODE`` (3) = its held-out value gate
    refused the model."""
    import os

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
    if args.window_files:
        cmd += ["--window-recent-files", str(args.window_files)]
    env = dict(os.environ)
    if args.threads:
        env["MTG_BOT_TRAIN_CPU_THREADS"] = str(args.threads)
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd, env=env)


LOOP_STATE = "fish_loop_state.json"


def deadline_after(start: datetime, hhmm: str) -> datetime:
    """The first ``HH:MM`` after ``start``: the next day when that time
    of day has passed (``--until 07:00`` from a 23:00 start)."""
    hh, mm = (int(x) for x in hhmm.split(":"))
    end = start.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    return end


def cmd_loop(args, gen=None, train=None, evaluate=None) -> dict:
    """Rounds of: play ``--games`` with the current best player (the
    heuristic bot until a net is promoted) and save the data; train the
    next version on the newest ``--window-files`` data files; play it
    ``--eval-games`` against the current best; promote it when its score
    reaches ``gate.EVAL_GATE_THRESHOLD``. The state (current best, one
    record per round) lives in ``<registry-root>/fish_loop_state.json``,
    so a later run continues where the last one stopped. ``--until HH:MM``
    starts no new round after that time."""
    import argparse as _ap
    import json

    from mtg_bot.training.gate import EVAL_GATE_THRESHOLD
    from mtg_bot.training.registry import Registry

    deadline = deadline_after(datetime.now(), args.until) if args.until else None
    gen = gen or cmd_gen
    train = train or cmd_train
    evaluate = evaluate or cmd_eval
    args.registry_root.mkdir(parents=True, exist_ok=True)
    state_path = args.registry_root / LOOP_STATE
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists() else {"current_best": "heuristic", "rounds": []}
    )

    def save():
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    for _ in range(args.rounds):
        if deadline is not None and datetime.now() >= deadline:
            print(f"past {args.until}: no new round", flush=True)
            break
        best = state["current_best"]
        n = len(state["rounds"]) + 1
        record = {"round": n, "started": datetime.now().isoformat(timespec="seconds"),
                  "played_by": best}
        print(f"== round {n}: games by {best}", flush=True)
        data = gen(_ap.Namespace(
            games=args.games, out_dir=args.data_dir, tag=f"round{n:03d}",
            decklist=args.decklist, workers=args.workers, samples=args.samples,
            nodes=args.nodes, seed=args.seed + 100_000 * n,
            per_game_timeout=args.per_game_timeout, chunk_games=args.chunk_games,
            keep_other=args.keep_other,
            nn_version=None if best == "heuristic" else best,
            registry_root=args.registry_root,
        ))
        record["data"] = str(data)
        before = set(Registry(args.registry_root).list_versions())
        rc = train(_ap.Namespace(
            data_dir=args.data_dir, registry_root=args.registry_root,
            epochs=args.epochs, notes=f"Forgetful Fish loop round {n}",
            window_files=args.window_files, threads=args.threads,
        ))
        added = sorted(set(Registry(args.registry_root).list_versions()) - before,
                       key=lambda v: int(v[1:]))
        record["train_exit"] = rc
        if rc != 0 or not added:
            record["result"] = "training refused or failed"
            state["rounds"].append(record)
            save()
            print(f"round {n}: training exit {rc}, no new version", flush=True)
            continue
        new = added[-1]
        score, wld = evaluate(_ap.Namespace(
            new=new, old=best, games=args.eval_games,
            registry_root=args.registry_root, decklist=args.decklist,
            workers=args.workers, samples=args.samples, nodes=args.nodes,
            seed=args.seed + 100_000 * n + 777, per_game_timeout=args.per_game_timeout,
        ))
        promoted = score >= EVAL_GATE_THRESHOLD
        record.update(version=new, vs=best, score=round(score, 3),
                      wins_losses_draws=list(wld), promoted=promoted,
                      finished=datetime.now().isoformat(timespec="seconds"))
        if promoted:
            state["current_best"] = new
        state["rounds"].append(record)
        save()
        print(f"round {n}: {new} vs {best} score {score:.3f} -> "
              f"{'PROMOTED' if promoted else 'kept ' + best}", flush=True)
    return state


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
    g.add_argument("--chunk-games", type=int, default=50,
                   help="games per generation call (bounds memory)")
    g.add_argument("--keep-other", type=float, default=0.1,
                   help="fraction of forced-move / value-only rows kept "
                        "(rows with a real choice are all kept)")
    g.add_argument("--nn-version", default=None,
                   help="drive both seats with this registered net (NN PIMC)")
    g.add_argument("--registry-root", type=Path, default=Path("trained_weights_fish"))
    e = sub.add_parser("eval", help="new version vs old version (or heuristic)")
    e.add_argument("--new", required=True)
    e.add_argument("--old", required=True, help="a version or 'heuristic'")
    e.add_argument("--games", type=int, default=40)
    e.add_argument("--registry-root", type=Path, required=True)
    e.add_argument("--decklist", type=Path, default=DEFAULT_DECKLIST)
    e.add_argument("--workers", type=int, default=None)
    e.add_argument("--samples", type=int, default=2)
    e.add_argument("--nodes", type=int, default=50)
    e.add_argument("--seed", type=int, default=777)
    e.add_argument("--per-game-timeout", type=float, default=600.0)
    t = sub.add_parser("train", help="train the structured net, register a version")
    t.add_argument("--data-dir", type=Path, required=True)
    t.add_argument("--registry-root", type=Path, required=True)
    t.add_argument("--epochs", type=int, default=20)
    t.add_argument("--notes", default="Forgetful Fish (user's 80-card list)")
    t.add_argument("--window-files", type=int, default=None,
                   help="train on the N newest data files only")
    t.add_argument("--threads", type=int, default=None,
                   help="torch CPU threads (MTG_BOT_TRAIN_CPU_THREADS)")
    lp = sub.add_parser("loop", help="rounds of gen -> train -> eval -> promote")
    lp.add_argument("--rounds", type=int, default=1)
    lp.add_argument("--until", default=None, metavar="HH:MM",
                    help="start no new round after this local time")
    lp.add_argument("--data-dir", type=Path, required=True)
    lp.add_argument("--registry-root", type=Path, required=True)
    lp.add_argument("--decklist", type=Path, default=DEFAULT_DECKLIST)
    lp.add_argument("--games", type=int, default=200)
    lp.add_argument("--eval-games", type=int, default=40)
    lp.add_argument("--epochs", type=int, default=10)
    lp.add_argument("--window-files", type=int, default=4)
    lp.add_argument("--threads", type=int, default=None)
    lp.add_argument("--workers", type=int, default=None)
    lp.add_argument("--samples", type=int, default=2)
    lp.add_argument("--nodes", type=int, default=50)
    lp.add_argument("--seed", type=int, default=0)
    lp.add_argument("--per-game-timeout", type=float, default=600.0)
    lp.add_argument("--chunk-games", type=int, default=50)
    lp.add_argument("--keep-other", type=float, default=0.1)
    args = ap.parse_args(argv)
    if args.cmd == "gen":
        cmd_gen(args)
        return 0
    if args.cmd == "eval":
        cmd_eval(args)
        return 0
    if args.cmd == "loop":
        cmd_loop(args)
        return 0
    return cmd_train(args)


if __name__ == "__main__":
    raise SystemExit(main())
