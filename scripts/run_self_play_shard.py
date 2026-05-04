"""Run one shard. Pull-mode self-play (--mode=pull) or eval (--mode=eval).

Used by the master's local shard AND every remote shard, invoked
via ``ssh ... run_self_play_shard.py --mode=... ...``. Decodes the
base64-encoded spec + shard config, then runs the appropriate worker
loop which feeds a pool of N workers from the master's
``/queue/take`` endpoint one game at a time.

self-play emits per-batch npzs under ``--output-dir`` and prints
``{"npz_paths": [...]}``. Eval writes a single result JSON under
``--progress-dir/{run_id}_shard_<label>_result.json`` and prints
``{"result_path": "..."}``. The orchestrator scps that file back and
parses it.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.training.distributed import (  # noqa: E402
    EvalJobSpec,
    SelfPlayJobSpec,
    ShardConfig,
    run_shard_eval_pull,
    run_shard_pull,
)


def _decode_b64_json(s: str) -> dict:
    return json.loads(base64.b64decode(s.encode("ascii")).decode("utf-8"))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", default="pull", choices=["pull", "eval"],
        help=(
            "``pull`` runs self-play (single NN, dual seats, emits "
            "training data); ``eval`` runs head-to-head between two "
            "NN versions (or NN-vs-heuristic) and emits a result JSON."
        ),
    )
    parser.add_argument(
        "--spec-b64", required=True,
        help=(
            "base64-encoded JSON of either SelfPlayJobSpec.to_dict() "
            "(--mode=pull) or EvalJobSpec.to_dict() (--mode=eval)."
        ),
    )
    parser.add_argument(
        "--shard-b64", required=True,
        help="base64-encoded JSON of ShardConfig.to_dict()",
    )
    parser.add_argument(
        "--queue-url", required=True,
        help=(
            "Master's queue endpoint base URL (e.g. "
            "``http://desktop-master:5099``)."
        ),
    )
    parser.add_argument(
        "--run-id", required=True,
        help=(
            "Per-iter queue + run identifier. Master groups concurrent "
            "workers' takes by this id."
        ),
    )
    parser.add_argument(
        "--iter-total-games", type=int, required=True,
        help="Iter's total game count (the queue size).",
    )
    parser.add_argument(
        "--stamp", required=True,
        help="UTC timestamp string (filename-safe).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("iterate_data"),
        help="Self-play npz output dir. Ignored in --mode=eval.",
    )
    parser.add_argument(
        "--progress-dir", type=Path, default=Path("training_progress"),
    )
    args = parser.parse_args(argv)

    shard = ShardConfig.from_dict(_decode_b64_json(args.shard_b64))

    import os
    n_workers = (
        shard.n_workers if shard.n_workers and shard.n_workers > 0
        else max(1, (os.cpu_count() or 1) - 2)
    )

    if args.mode == "pull":
        spec = SelfPlayJobSpec.from_dict(_decode_b64_json(args.spec_b64))
        npz_paths = run_shard_pull(
            spec,
            queue_url=args.queue_url,
            run_id=args.run_id,
            n_workers=n_workers,
            output_dir=args.output_dir,
            label=shard.display_label,
            stamp=args.stamp,
            iter_total_games=args.iter_total_games,
            progress_dir=args.progress_dir,
        )
        print(json.dumps({"npz_paths": [str(p) for p in npz_paths]}))
        return

    eval_spec = EvalJobSpec.from_dict(_decode_b64_json(args.spec_b64))
    counts = run_shard_eval_pull(
        eval_spec,
        queue_url=args.queue_url,
        run_id=args.run_id,
        n_workers=n_workers,
        label=shard.display_label,
        iter_total_games=args.iter_total_games,
        progress_dir=args.progress_dir,
    )
    args.progress_dir.mkdir(parents=True, exist_ok=True)
    result_path = (
        args.progress_dir
        / f"{args.run_id}_shard_{shard.display_label}_result.json"
    )
    result_path.write_text(json.dumps(counts), encoding="utf-8")
    print(json.dumps({"result_path": str(result_path), **counts}))


if __name__ == "__main__":
    main()
