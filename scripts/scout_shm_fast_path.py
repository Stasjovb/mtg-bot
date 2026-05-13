"""Micro-bench for the SHM eval server's GPU fast path.

Loads a tiny random-init structured model through
``SharedTensorNNEvalServer`` and issues N sequential forward
requests on random inputs at the production batch_size. Reports
wall time + throughput, and compares against a baseline run with
the GPU fast path off (no autocast, no compile, no warmup, no
pinned memory).

Goal: observe SOME measurable speedup. Not the full 3-4x we
projected — production iters surface remaining gains. If the
smoke shows >= ~2x, we ship.

Usage:

    PYTHONPATH=src .venv-py313/Scripts/python.exe \
        scripts/scout_shm_fast_path.py --n 1000 --batch-size 64

Adds no production code; lives under scripts/ alongside the other
scout_*.py investigation scripts per CLAUDE.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

# Repo-relative imports.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mtg_bot.search.nn_evaluator import (  # noqa: E402
    ARCHITECTURE_STRUCTURED, NNEvaluator,
)
from mtg_bot.search.shm_nn_eval_server import (  # noqa: E402
    SharedTensorNNEvalServer, SharedTensorNNEvalClient,
)
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE  # noqa: E402
from mtg_bot.training.structured_model import (  # noqa: E402
    ACTION_KIND_VOCAB_SIZE,
    CONTROLLER_VOCAB_SIZE,
    EMB_FIELD_ACTION_KIND,
    EMB_FIELD_CONTROLLER,
    EMB_FIELD_PRINTING,
    EMB_FIELD_STEP,
    EMB_FIELD_TARGET_KIND,
    EMB_FIELD_TARGET_PRINTING,
    EMB_FIELD_VARIANT,
    N_EMB_FIELDS,
    N_SCALAR_FIELDS,
    N_TOKEN_TYPES,
    STEP_VOCAB_SIZE,
    TARGET_KIND_VOCAB_SIZE,
    VARIANT_VOCAB_SIZE,
)


# Production-shaped tiny structured config — large enough to see GPU
# behavior, small enough to avoid burning compile time.
MODEL_KWARGS: dict[str, Any] = {
    "structured_emb_dim": 128,
    "structured_n_heads": 4,
    "structured_n_layers": 2,
    "structured_hidden_dim": 256,
    "structured_action_history_n": 32,
    "structured_n_printings": 320,
}


class _FakeState:
    """Minimal duck-type so the SHM client's ``evaluate_with_policy``
    fast-paths through ``_engine_state`` without touching a real
    engine. Tokenization is bypassed via a fake tokenizer."""
    def __init__(self):
        self.engine_state = object()

    def is_terminal(self): return False
    def winner(self): return None


def _make_token_dict(*, seq_len: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    token_type = rng.integers(
        0, N_TOKEN_TYPES, size=seq_len, dtype=np.int64,
    )
    token_emb_ids = np.zeros((seq_len, N_EMB_FIELDS), dtype=np.int64)
    token_emb_ids[:, EMB_FIELD_PRINTING] = rng.integers(
        0, 320, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_ACTION_KIND] = rng.integers(
        0, ACTION_KIND_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_CONTROLLER] = rng.integers(
        0, CONTROLLER_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_TARGET_PRINTING] = rng.integers(
        0, 320, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_TARGET_KIND] = rng.integers(
        0, TARGET_KIND_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_VARIANT] = rng.integers(
        0, VARIANT_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_STEP] = rng.integers(
        0, STEP_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_scalars = (
        np.random.default_rng(seed)
        .standard_normal((seq_len, N_SCALAR_FIELDS))
        .astype(np.float32)
    )
    attention_mask = np.ones(seq_len, dtype=bool)
    return {
        "token_type": token_type,
        "token_emb_ids": token_emb_ids,
        "token_scalars": token_scalars,
        "attention_mask": attention_mask,
    }


def _install_fake_tokenizer():
    """Swap ``mtg_bot.training.state_tokenizer.tokenize_state`` with a
    deterministic fake so the bench never touches the real engine.
    Idempotent — repeated calls are safe."""
    import types
    import mtg_bot.training.state_tokenizer as st_mod
    counter = {"n": 0}
    seq_len = 64  # representative production seq_len (median ~53)

    def tokenize_state(state, viewer_id, recent_actions, n=32, *,
                       n_printings_cap=320):
        counter["n"] += 1
        return _make_token_dict(seq_len=seq_len, seed=counter["n"])

    st_mod.tokenize_state = tokenize_state


def _install_fake_legal_mask():
    """All-True legal-action mask. Bench inputs are synthetic, so the
    mask doesn't carry meaning; we just need a consistent shape."""
    from mtg_bot.training import action_encoding as ae

    def _all_true(state, viewer, version="positional_v1"):
        return np.ones(ACTION_VOCAB_SIZE, dtype=bool)
    ae.legal_action_mask = _all_true


def _run_bench(
    weights_path: Path,
    *,
    n_requests: int,
    batch_size: int,
    device: str,
    fast_path: bool,
    enable_compile: bool = True,
    enable_autocast: bool = True,
    enable_pin_memory: bool = True,
    concurrency: int = 1,
    batch_eval: bool = False,
    batch_eval_size: int = 32,
) -> dict[str, float]:
    """Spin up a server with or without the GPU fast-path knobs, run
    ``n_requests`` forward requests on synthetic states (using
    ``concurrency`` worker threads to mimic the cross-worker batching
    pattern), and return wall-time + throughput numbers."""
    # autocast / compile / warmup / pin_memory wire onto ``fast_path``.
    autocast_dtype: Any = (
        "auto" if (fast_path and enable_autocast) else False
    )
    compile_model = (True if fast_path else False) and enable_compile
    warmup = True if fast_path else False
    pin_memory = (True if fast_path else False) and enable_pin_memory

    server = SharedTensorNNEvalServer(
        weights_path=weights_path,
        device=device,
        architecture=ARCHITECTURE_STRUCTURED,
        batch_size=batch_size,
        batch_wait_ms=0.0,
        n_slots=max(64, batch_size),
        autocast_dtype=autocast_dtype,
        compile_model=compile_model,
        warmup=warmup,
        pin_memory=pin_memory,
        **MODEL_KWARGS,
    )
    server.start()
    try:
        client = SharedTensorNNEvalClient(server.handle())
        state = _FakeState()

        # Warmup outside of the timing window: a few free calls to
        # let any first-batch behavior settle. (The server's own
        # warmup runs during start() when fast_path=True; we still
        # do a small extra prelude for the no-fast-path baseline.)
        for _ in range(5):
            client.evaluate_with_policy(state, player_id=0)

        if device == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        if batch_eval:
            states_batch = [state for _ in range(batch_eval_size)]

            def _do(c):
                c.batch_evaluate_with_policy(states_batch, 0)
        else:
            def _do(c):
                c.evaluate_with_policy(state, 0)

        if concurrency <= 1:
            for _ in range(n_requests):
                _do(client)
        else:
            import threading
            per_thread = n_requests // concurrency
            extra = n_requests - per_thread * concurrency

            def _worker(n_each: int):
                local_client = SharedTensorNNEvalClient(server.handle())
                for _ in range(n_each):
                    _do(local_client)

            threads = []
            for i in range(concurrency):
                n_each = per_thread + (1 if i < extra else 0)
                t = threading.Thread(target=_worker, args=(n_each,))
                t.start()
                threads.append(t)
            for t in threads:
                t.join()
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
    finally:
        server.stop(timeout=5.0)

    return {
        "elapsed_s": elapsed,
        "throughput_qps": n_requests / elapsed,
        "wall_per_req_us": elapsed / n_requests * 1e6,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n", type=int, default=1000,
        help="Number of sequential forward requests per condition.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=64,
        help="SHM server batch_size (matches the new default).",
    )
    parser.add_argument(
        "--device", default=None,
        help="Override device ('cuda' / 'cpu'); auto-detects when "
             "omitted.",
    )
    parser.add_argument(
        "--no-compile", action="store_true",
        help="Disable torch.compile in the fast-path run. Useful on "
             "Windows where Triton isn't packaged.",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Number of concurrent client threads. >1 mimics the "
             "multi-worker dispatcher-fusion path that production "
             "self-play uses.",
    )
    parser.add_argument(
        "--no-autocast", action="store_true",
        help="Disable autocast in the fast-path run.",
    )
    parser.add_argument(
        "--no-pin-memory", action="store_true",
        help="Disable pinned host staging buffers in the fast-path run.",
    )
    parser.add_argument(
        "--batch-eval", action="store_true",
        help="Use batch_evaluate_with_policy (production code path) "
             "instead of single-state evaluate. Each thread submits "
             "batches of size = --batch-eval-size.",
    )
    parser.add_argument(
        "--batch-eval-size", type=int, default=32,
        help="Batch size for --batch-eval mode.",
    )
    args = parser.parse_args()

    device = args.device or (
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    print(f"[scout_shm_fast_path] device={device} "
          f"n={args.n} batch_size={args.batch_size}")

    _install_fake_tokenizer()
    _install_fake_legal_mask()

    # Save a fresh structured model state_dict to use for both runs.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        weights_path = Path(td) / "structured.pt"
        torch.manual_seed(0)
        ref = NNEvaluator(
            architecture=ARCHITECTURE_STRUCTURED, **MODEL_KWARGS,
        )
        ref.save(weights_path)

        print("[scout_shm_fast_path] running BASELINE (no fast path)...")
        baseline = _run_bench(
            weights_path,
            n_requests=args.n,
            batch_size=args.batch_size,
            device=device,
            fast_path=False,
            concurrency=args.concurrency,
            batch_eval=args.batch_eval,
            batch_eval_size=args.batch_eval_size,
        )
        print(f"  baseline: {baseline['elapsed_s']:.3f}s, "
              f"{baseline['throughput_qps']:.1f} qps, "
              f"{baseline['wall_per_req_us']:.1f} us/req")

        compile_descr = (
            "no-compile" if args.no_compile else "compile"
        )
        print(f"[scout_shm_fast_path] running FAST PATH "
              f"(autocast + {compile_descr} + warmup + pinned)...")
        fast = _run_bench(
            weights_path,
            n_requests=args.n,
            batch_size=args.batch_size,
            device=device,
            fast_path=True,
            enable_compile=not args.no_compile,
            enable_autocast=not args.no_autocast,
            enable_pin_memory=not args.no_pin_memory,
            concurrency=args.concurrency,
            batch_eval=args.batch_eval,
            batch_eval_size=args.batch_eval_size,
        )
        print(f"  fast:     {fast['elapsed_s']:.3f}s, "
              f"{fast['throughput_qps']:.1f} qps, "
              f"{fast['wall_per_req_us']:.1f} us/req")

    speedup = baseline["elapsed_s"] / fast["elapsed_s"]
    print(f"[scout_shm_fast_path] speedup: {speedup:.2f}x")
    if speedup >= 1.5:
        print("[scout_shm_fast_path] result: >= 1.5x — fast path is "
              "a measurable win.")
        return 0
    print("[scout_shm_fast_path] result: < 1.5x speedup; investigate "
          "before shipping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
