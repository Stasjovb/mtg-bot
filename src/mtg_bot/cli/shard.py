"""Run one shard. Pull-mode self-play (--mode=pull) or eval (--mode=eval).

Used by the master's local shard AND every remote shard, invoked
via ``ssh ... run_self_play_shard.py --mode=... ...``. Decodes the
base64-encoded spec + shard config, then runs the appropriate worker
loop which feeds a pool of N workers from the master's
``/queue/take`` endpoint one game at a time.

self-play emits per-batch npzs under ``--output-dir`` and prints
``{"npz_paths": [...]}``. Eval reports its final counts through
``runs.db`` (per-shard ``run_progress`` row, master ``run_id`` +
``shard_label``); the orchestrator's
``_aggregate_eval_counts_from_progress`` reads them back. The stdout
line carries the same dict for diagnostic visibility; pre-cutover
the orchestrator scp'd a sibling ``..._result.json`` and parsed it,
but post-cutover the DB row is authoritative.

Run-DB lifecycle: shards do NOT register their own ``runs`` row.
``run_shard_pull`` / ``run_shard_eval_pull`` push per-shard progress
DIRECTLY to the master's ``run_progress`` table under the master
``run_id`` with ``shard_label`` set — this is the authoritative
record. A separate shard ``runs`` row from a prior design was
redundant (no progress was ever written to it; the FK constraint
on ``run_progress.run_id`` already requires pushes under the master)
and surfaced as visual noise in the UI. The shard wrapper instead
opens a tiny ``run_progress`` open/close pair on the parent so the
shard's start_at / status fields land on the right row.

Transport defaults to the REST path
(``MTG_BOT_RUN_DB_URL=http://master:5099``) on remote shards —
they don't share a filesystem with the master.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import socket
import sys
from pathlib import Path

from mtg_bot.cli.runs import lifecycle as _lifecycle
from mtg_bot.training.distributed import (
    EvalJobSpec,
    SelfPlayJobSpec,
    ShardConfig,
    run_shard_eval_pull,
    run_shard_pull,
)


def _decode_b64_json(s: str) -> dict:
    return json.loads(base64.b64decode(s.encode("ascii")).decode("utf-8"))


def _shard_label() -> str:
    """Hostname-based identifier for the run_progress.shard_label
    column. Best-effort: ``socket.gethostname()`` always returns
    something (falls back to the OS netbios name on Windows / loopback
    on POSIX). Used so the master's runs.db can distinguish
    per-shard progress rows for the same iter."""
    try:
        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"


def _build_shard_config(spec_dict: dict, shard_dict: dict, args) -> dict:
    """Bundle the argparse view + shard/spec dict tags into the JSON
    blob stored in ``runs.config_json``. The full spec dict is too
    large to be useful here (it carries the whole NN architecture
    desc); we keep the small identifying fields and let the master's
    parent run_id row carry the rest."""
    return {
        "mode": args.mode,
        "run_id": args.run_id,
        "shard_label": shard_dict.get("label") or shard_dict.get("host"),
        "shard_host": shard_dict.get("host"),
        "iter_total_games": args.iter_total_games,
        "stamp": args.stamp,
        "queue_url": args.queue_url,
        "progress_dir": str(args.progress_dir),
        "output_dir": str(args.output_dir),
        "weights_path": spec_dict.get("weights_path"),
        "new_weights_path": spec_dict.get("new_weights_path"),
        "old_weights_path": spec_dict.get("old_weights_path"),
        "samples": spec_dict.get("samples"),
        "inner_nodes": spec_dict.get("inner_nodes"),
        "base_seed": spec_dict.get("base_seed"),
        "hostname": _shard_label(),
    }


def _run_pull_shard(args, shard_dict: dict, spec_dict: dict) -> None:
    """Execute a self-play (``--mode=pull``) shard.

    No ``run_lifecycle`` wrapper — the shard does NOT register its
    own ``runs`` row. ``run_shard_pull`` pushes per-shard
    ``run_progress`` rows directly under the master's ``run_id``
    with ``shard_label`` set, which is the authoritative record.
    The redundant shard ``runs`` row was visual noise in the UI
    (5+ cards per iter launch) without any data of its own.
    """
    shard = ShardConfig.from_dict(shard_dict)
    spec = SelfPlayJobSpec.from_dict(spec_dict)
    n_workers = (
        shard.n_workers if shard.n_workers and shard.n_workers > 0
        else max(1, (os.cpu_count() or 1) - 2)
    )
    label = shard.display_label
    npz_paths = run_shard_pull(
        spec,
        queue_url=args.queue_url,
        run_id=args.run_id,
        n_workers=n_workers,
        output_dir=args.output_dir,
        label=label,
        stamp=args.stamp,
        iter_total_games=args.iter_total_games,
        progress_dir=args.progress_dir,
    )
    print(json.dumps({"npz_paths": [str(p) for p in npz_paths]}))


def _run_eval_shard(args, shard_dict: dict, spec_dict: dict) -> None:
    """Execute an eval (``--mode=eval``) shard.

    No ``run_lifecycle`` wrapper — see :func:`_run_pull_shard` for
    the rationale. ``run_shard_eval_pull`` writes the authoritative
    per-shard ``run_progress`` row under the master ``run_id`` with
    ``shard_label`` set.
    """
    shard = ShardConfig.from_dict(shard_dict)
    eval_spec = EvalJobSpec.from_dict(spec_dict)
    n_workers = (
        shard.n_workers if shard.n_workers and shard.n_workers > 0
        else max(1, (os.cpu_count() or 1) - 2)
    )
    label = shard.display_label
    counts = run_shard_eval_pull(
        eval_spec,
        queue_url=args.queue_url,
        run_id=args.run_id,
        n_workers=n_workers,
        label=label,
        iter_total_games=args.iter_total_games,
        progress_dir=args.progress_dir,
    )
    # The per-shard ``run_progress`` row carries the authoritative
    # counts (see ``run_shard_eval_pull``'s post-loop
    # ``_push_eval_shard_progress_to_db(status="completed")``). The
    # stdout line stays so existing diagnostic tooling continues to
    # see the per-shard summary; the legacy sibling
    # ``_shard_<label>_result.json`` write was retired with the
    # runs-db cutover.
    print(json.dumps(counts))


def _parse_args(argv=None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def _run(argv=None) -> None:
    """Parse args and dispatch to ``_run_pull_shard`` /
    ``_run_eval_shard``.

    Separated from ``main`` so ``main`` can wrap it in the
    ``os._exit`` finalizer without ballooning the indented body.
    The heavy lifting (run_lifecycle wrap + the call into
    ``run_shard_pull`` / ``run_shard_eval_pull``) lives in the
    per-mode helpers so the tests can drive each path independently.
    """
    args = _parse_args(argv)
    shard_dict = _decode_b64_json(args.shard_b64)
    spec_dict = _decode_b64_json(args.spec_b64)
    if args.mode == "pull":
        _run_pull_shard(args, shard_dict, spec_dict)
        return
    _run_eval_shard(args, shard_dict, spec_dict)


def _terminate_active_children() -> None:
    """Kill every still-alive multiprocessing child of this process.

    Why: when the master's SSH session is yanked (Tailscale glitch,
    watchdog terminate(), user ctrl-c that doesn't propagate), this
    shard process receives SIGTERM (POSIX) / TerminateProcess
    (Windows) — but its ``ProcessPoolExecutor`` worker children are
    NOT necessarily collected. On Linux/macOS they get reparented to
    init (PID 1) and run forever; on Windows they reparent to
    System and accumulate. The session before this fix accumulated
    141 such orphans on the Mac over a few days of killed runs.

    This handler is registered for SIGTERM and SIGHUP. POSIX raises
    SIGHUP when the controlling SSH session dies; SIGTERM is what
    the orchestrator's watchdog fires. Windows doesn't deliver
    SIGHUP — but ``signal.signal(SIGTERM, ...)`` does fire on
    ``TerminateProcess`` for Windows console apps run under the
    standard signal-bridge, so registering it is still useful.

    Calls ``terminate()`` then ``join(0.5)`` per child; nuked via
    ``kill()`` if still alive. Then ``os._exit(143)`` (128+SIGTERM)
    to bypass the at-exit thread-join hang the rest of this script
    is built around.
    """
    import multiprocessing as _mp
    import time as _t
    children = list(_mp.active_children())
    for c in children:
        try:
            c.terminate()
        except Exception:  # noqa: BLE001
            pass
    deadline = _t.monotonic() + 1.0
    for c in children:
        remaining = max(0.0, deadline - _t.monotonic())
        try:
            c.join(timeout=remaining)
        except Exception:  # noqa: BLE001
            pass
    for c in children:
        if c.is_alive():
            try:
                c.kill()
            except Exception:  # noqa: BLE001
                pass


def _signal_killchildren_and_exit(signum, _frame) -> None:
    """SIGTERM/SIGHUP handler: terminate mp children, then ``os._exit``
    so we don't get stuck in interpreter shutdown's at-exit thread
    joins (the same hang the existing ``os._exit`` finalizer is
    designed to dodge — see ``main`` docstring).
    """
    try:
        _terminate_active_children()
    except Exception:  # noqa: BLE001
        pass
    # 128 + signal number is the convention.
    try:
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    try:
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(128 + int(signum))


def _install_kill_handlers() -> None:
    """Install SIGTERM/SIGHUP handlers. Best-effort: SIGHUP doesn't
    exist on Windows, and any of these may already be inherited from
    the parent. We swallow ValueError ("signal only works in main
    thread") just in case the shard is ever invoked from a non-main
    thread context (today's path runs main() from __main__, so this
    is defense-in-depth)."""
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _signal_killchildren_and_exit)
        except (ValueError, OSError):
            # ValueError: not on main thread; OSError: signal not
            # installable on this platform.
            pass


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
    _install_kill_handlers()
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
        # Terminate any leftover multiprocessing children before
        # ``os._exit`` so they don't reparent to init/System on
        # POSIX/Windows. ``shutdown(wait=False)`` inside
        # ``run_shard_pull`` already returned by here, but in some
        # paths (early-stop, exception) the workers can still be
        # alive when the executor's shutdown thread releases.
        try:
            _terminate_active_children()
        except Exception:  # noqa: BLE001
            pass
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
