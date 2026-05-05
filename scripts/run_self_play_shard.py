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
import os
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


def _run(argv=None) -> None:
    """Parse args and dispatch to ``run_shard_pull`` /
    ``run_shard_eval_pull``.

    Separated from ``main`` so ``main`` can wrap it in the
    ``os._exit`` finalizer without ballooning the indented body.
    """
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


def main(argv=None) -> None:
    """Top-level entry. Always exits via ``os._exit`` to bypass
    Python's normal interpreter shutdown.

    Why: ``run_shard_pull`` / ``run_shard_eval_pull`` use
    ``concurrent.futures.ProcessPoolExecutor``, which spawns
    non-daemon management threads
    (``_queue_management_thread`` and friends) that stay alive while
    any worker process is alive. We already replaced
    ``with ... as exe:`` with explicit ``shutdown(wait=False)`` so
    the executor's exit path doesn't block on hung futures, but
    Python's at-exit machinery still joins those non-daemon threads,
    which join the still-alive workers, so the interpreter never
    returns from ``main()``. Concrete repro: 2026-05-05 a Mac shard
    stayed alive 50+ min after self-play completed and all data was
    on disk; master's SSH session never saw EOF, the orchestrator
    never proceeded to rsync-back.

    By the time we reach the ``finally`` block here:
    - ``run_shard_pull`` / ``run_shard_eval_pull`` have flushed every
      ``.npz`` via their internal ``_flush()``,
    - ``progress.finalize(...)`` has written the per-shard progress
      JSON,
    - the ``shard_end`` event has been written to ``events.jsonl``,
    - in eval mode, ``result_path.write_text(...)`` above has
      written the result JSON the orchestrator scps back.

    So everything that needs to be on disk IS on disk. The only
    things ``os._exit`` skips are pure-process cleanup
    (worker-process termination, thread joins, GC) — exactly what's
    hanging us. See ``docs/SEARCH_LIMITATIONS.md`` for the full
    rationale and the proper-fix scope estimate.

    Caveat: any ``atexit`` handler registered by an import is NOT
    going to run. If you need teardown work to happen on shard exit,
    do it explicitly before this function returns, not via
    ``atexit.register``.
    """
    exit_code = 0
    try:
        _run(argv)
    except SystemExit as e:
        # argparse exits via SystemExit on --help or bad args.
        # Preserve whatever exit code it picked.
        code = getattr(e, "code", 0)
        if isinstance(code, int):
            exit_code = code
        elif code is None:
            exit_code = 0
        else:
            # SystemExit with a string message: emit it, exit 1.
            sys.stderr.write(str(code) + "\n")
            exit_code = 1
    except BaseException:
        import traceback
        traceback.print_exc()
        exit_code = 1
    finally:
        # All on-disk artifacts (npzs, progress JSON, events.jsonl,
        # eval result.json) were already written inside ``_run``
        # before we got here; flush stdio so any pending prints
        # (e.g. the final ``{"npz_paths": [...]}`` line the
        # orchestrator parses) reach the parent SSH process before
        # the kernel tears the pipe down.
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        try:
            sys.stderr.flush()
        except Exception:  # noqa: BLE001
            pass
        os._exit(exit_code)


if __name__ == "__main__":
    main()
