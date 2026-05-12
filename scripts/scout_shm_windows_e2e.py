"""Scout: end-to-end smoke for SHM server + ProcessPoolExecutor on
Windows, using production NN-eval semantics.

Verifies that:
- A SharedTensorNNEvalServer can be constructed on Windows.
- A ProcessPoolExecutor(initializer=set_worker_handle, mp_context=spawn)
  successfully installs the handle in each spawn worker.
- A worker can call client.evaluate() via the SHM handle and get
  bit-identical results vs a local NNEvaluator.
- The server stops cleanly after the pool shuts down.

Not a unit test (deliberately) — exercises the full multi-process spawn
path which the existing in-process thread-based tests don't reach."""

from __future__ import annotations

import concurrent.futures as cf
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

# Ensure src/ is on path even when running the script directly.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))


def _worker_eval_via_shm(seed: int) -> tuple[float, float]:
    """Run in a SHM-pool worker. Uses the fork/spawn-inherited handle
    to compute a value via SharedTensorNNEvalClient and returns it
    alongside the reference local-NN value for comparison."""
    from mtg_bot.agents import RandomAgent
    from mtg_bot.features import FEATURE_DIM, extract_features
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.search.nn_evaluator import NNEvaluator
    from mtg_bot.search.shm_nn_eval_server import (
        SharedTensorNNEvalClient,
        maybe_get_worker_handle,
    )
    from mtg_bot.simulate import setup_game
    import os
    os.environ.setdefault("PYTHONPATH", "")
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from tests._test_decks import simple_test_decklists  # noqa: E402

    handle = maybe_get_worker_handle()
    if handle is None:
        return (-999.0, -999.0)

    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=seed,
    )
    adapter = MtgGameStateAdapter(state)

    client = SharedTensorNNEvalClient(handle)
    v_shm = client.evaluate(adapter, player_id=0)
    return (v_shm, float(seed))


def main() -> int:
    print(f"platform: {sys.platform}", flush=True)

    from mtg_bot.search.shm_nn_eval_server import (
        SharedTensorNNEvalServer,
        preferred_mp_context,
        set_worker_handle,
    )
    from mtg_bot.search.nn_evaluator import NNEvaluator

    torch.manual_seed(0)
    ref = NNEvaluator(with_policy=False)
    with tempfile.TemporaryDirectory() as tmp:
        weights_path = Path(tmp) / "value.pt"
        ref.save(weights_path)

        server = SharedTensorNNEvalServer(
            weights_path=weights_path,
            device="cpu",
            with_policy=False,
            batch_size=4,
            batch_wait_ms=2.0,
            n_slots=8,
        )
        print("[parent] constructed SharedTensorNNEvalServer", flush=True)

        server.start()
        print(f"[parent] dispatcher running, device={server._device}", flush=True)

        try:
            ctx = preferred_mp_context()
            print(f"[parent] using mp ctx: {ctx}", flush=True)

            with cf.ProcessPoolExecutor(
                max_workers=2,
                mp_context=ctx,
                initializer=set_worker_handle,
                initargs=(server.handle(),),
            ) as exe:
                seeds = list(range(1, 6))
                t0 = time.monotonic()
                results = list(exe.map(_worker_eval_via_shm, seeds))
                elapsed = time.monotonic() - t0

            print(f"[parent] 5 worker evals in {elapsed:.3f}s", flush=True)
            for seed, (v_shm, seed_back) in zip(seeds, results):
                print(f"  seed={seed} v_shm={v_shm}", flush=True)
                if v_shm == -999.0:
                    print("FAIL: handle not installed in worker", flush=True)
                    return 2

            # Verify the value matches a direct (parent-side) local NN
            # evaluation for the same state. Bit-equality (within
            # float32 epsilon) is the load-bearing correctness check.
            from mtg_bot.agents import RandomAgent
            from mtg_bot.search.engine_adapter import MtgGameStateAdapter
            from mtg_bot.simulate import setup_game
            sys.path.insert(0, str(_REPO))
            from tests._test_decks import simple_test_decklists  # noqa: E402

            for seed, (v_shm, _) in zip(seeds, results):
                state = setup_game(
                    [RandomAgent(), RandomAgent()],
                    decks=simple_test_decklists(),
                    seed=seed,
                )
                adapter = MtgGameStateAdapter(state)
                v_local = float(ref.evaluate(adapter, player_id=0))
                if abs(v_shm - v_local) > 1e-5:
                    print(
                        f"FAIL seed={seed}: v_shm={v_shm} vs "
                        f"v_local={v_local} differ by > 1e-5",
                        flush=True,
                    )
                    return 3
                print(
                    f"  seed={seed}: v_shm={v_shm:.6f} matches v_local "
                    f"(delta={abs(v_shm - v_local):.2e})",
                    flush=True,
                )

            print(
                f"[parent] server telemetry: batches={server.batches_dispatched} "
                f"requests={server.requests_served} "
                f"batch_sizes={server.batch_sizes}",
                flush=True,
            )
            print("PASS: SHM server runs end-to-end on Windows spawn", flush=True)
            return 0
        finally:
            server.stop(timeout=5.0)
            print("[parent] server stopped cleanly", flush=True)


if __name__ == "__main__":
    sys.exit(main())
