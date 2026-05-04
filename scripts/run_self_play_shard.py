"""Run one self-play shard. Pull-mode only.

Used by the master's local shard AND every remote shard, invoked
via ``ssh ... run_self_play_shard.py --mode=pull ...``. Decodes the
base64-encoded ``SelfPlayJobSpec`` + ``ShardConfig``, then runs
``run_shard_pull`` which feeds a pool of N workers from the master's
``/queue/take`` endpoint one game at a time. Returns the list of
emitted npz paths via stdout JSON when done.

CLI surface kept small: this script decodes args, calls
``run_shard_pull``, and exits. Everything else lives in
``mtg_bot.training.distributed``.
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
    SelfPlayJobSpec,
    ShardConfig,
    run_shard_pull,
)


def _decode_b64_json(s: str) -> dict:
    return json.loads(base64.b64decode(s.encode("ascii")).decode("utf-8"))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", default="pull", choices=["pull"],
        help=(
            "Shard mode. Only ``pull`` today; the static-partition "
            "mode was retired in favor of master-served work-queue."
        ),
    )
    parser.add_argument(
        "--spec-b64", required=True,
        help="base64-encoded JSON of SelfPlayJobSpec.to_dict()",
    )
    parser.add_argument(
        "--shard-b64", required=True,
        help="base64-encoded JSON of ShardConfig.to_dict()",
    )
    parser.add_argument(
        "--queue-url", required=True,
        help=(
            "Master's queue endpoint base URL (e.g. "
            "``http://desktop-master:5099``). The script POSTs "
            "``/queue/take`` here repeatedly."
        ),
    )
    parser.add_argument(
        "--run-id", required=True,
        help=(
            "Per-iter queue + run identifier (typically iterate's "
            "``iter_NNN_self_play_<bootstrap>``). Master groups "
            "concurrent workers' takes by this id."
        ),
    )
    parser.add_argument(
        "--iter-total-games", type=int, required=True,
        help=(
            "Iter's total game count (the queue size). Used only "
            "to set the per-shard progress JSON's ``n_games_total`` "
            "so the UI can show 'this shard did X of Y'."
        ),
    )
    parser.add_argument(
        "--stamp", required=True,
        help="UTC timestamp string (filename-safe).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("iterate_data"),
    )
    parser.add_argument(
        "--progress-dir", type=Path, default=Path("training_progress"),
    )
    args = parser.parse_args(argv)

    spec = SelfPlayJobSpec.from_dict(_decode_b64_json(args.spec_b64))
    shard = ShardConfig.from_dict(_decode_b64_json(args.shard_b64))

    import os
    n_workers = (
        shard.n_workers if shard.n_workers and shard.n_workers > 0
        else max(1, (os.cpu_count() or 1) - 2)
    )

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


if __name__ == "__main__":
    main()
