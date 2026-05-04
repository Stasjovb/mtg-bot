"""Run one self-play shard.

Used in two ways:

1. Locally on the master (when run_distributed_self_play wants to
   spawn a separate process — not the default; today it calls
   run_shard_local directly in-process).
2. Remotely via SSH from the master's run_distributed_self_play
   orchestrator. The remote receives base64-encoded JSON for the
   ``SelfPlayJobSpec`` and ``ShardConfig`` so quoting is identical
   on cmd.exe and bash.

CLI surface kept small on purpose: this script's job is to decode
the spec + shard, call ``run_shard_local``, and exit. Everything
else lives in ``mtg_bot.training.distributed``.
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
    run_shard_local,
)


def _decode_b64_json(s: str) -> dict:
    return json.loads(base64.b64decode(s.encode("ascii")).decode("utf-8"))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec-b64", required=True,
        help="base64-encoded JSON of SelfPlayJobSpec.to_dict()",
    )
    parser.add_argument(
        "--shard-b64", required=True,
        help="base64-encoded JSON of ShardConfig.to_dict()",
    )
    parser.add_argument(
        "--run-id-prefix", required=True,
        help=(
            "Run id prefix; the shard's progress JSON + npz "
            "filenames concatenate this with the shard's display "
            "label and a UTC stamp."
        ),
    )
    parser.add_argument(
        "--stamp", required=True,
        help="UTC timestamp string (filename-safe).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("iterate_data"),
        help=(
            "Where the shard writes its npz. Default "
            "``iterate_data/`` (matches iterate's --data-dir "
            "convention)."
        ),
    )
    parser.add_argument(
        "--progress-dir", type=Path, default=Path("training_progress"),
        help=(
            "Where the shard writes its progress JSON (the master "
            "scps this back periodically for the live UI)."
        ),
    )
    args = parser.parse_args(argv)

    spec = SelfPlayJobSpec.from_dict(_decode_b64_json(args.spec_b64))
    shard = ShardConfig.from_dict(_decode_b64_json(args.shard_b64))

    npz_path = run_shard_local(
        shard, spec,
        progress_dir=args.progress_dir,
        output_dir=args.output_dir,
        run_id_prefix=args.run_id_prefix,
        stamp=args.stamp,
    )
    # Print the resulting path so the orchestrator (or a manual
    # invoker) can pick it up via stdout. Keeping this stable is
    # important if a future commit moves to a fire-and-forget /
    # poll-stdout invocation pattern.
    print(json.dumps({"npz_path": str(npz_path)}))


if __name__ == "__main__":
    main()
