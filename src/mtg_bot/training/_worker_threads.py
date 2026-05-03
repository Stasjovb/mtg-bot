"""Per-worker torch thread-count pin.

Multiprocessing pools in the eval (``self_play.run_match_parallel``)
and data-gen (``data_gen.generate_training_data_parallel``) drivers
spawn N workers; each worker imports torch (via the NN-evaluator
strategy factory) and inherits the default ``torch.set_num_threads``
of "host CPU count." With 30 workers x 32 MKL threads on a 32-core
box, we get ~960 OS threads contending for 32 cores — effective
utilization sits at 30-40% and per-NN-forward latency is dominated
by thread-sync overhead, not compute.

The trainer already pins to 1 thread on CPU (commit 3ad808f, 85x
epoch speedup). The worker-side equivalent is this module — call
``pin_worker_torch_threads()`` from each worker entry point. The
call is idempotent (``torch.set_num_threads(1)`` may be invoked any
number of times) and safe on environments without torch (we look
torch up in ``sys.modules`` rather than importing it, so we never
add an unconditional dep on torch to modules that don't already
have one).

Why look up ``sys.modules`` instead of ``import torch`` in a
try/except: ``data_gen`` and ``self_play`` are imported at
``mtg_bot.training`` package load time and are intentionally
torch-free. An unconditional ``import torch`` here would make
every test that imports the training package pay a ~1 second
torch import. By checking ``sys.modules`` we no-op when torch
hasn't been loaded yet (e.g. early in worker startup before the
strategy factory runs) and pin once it's been loaded by something
downstream. ``set_num_threads`` is idempotent so calling per-game
is harmless.
"""

from __future__ import annotations

import sys


def pin_worker_torch_threads() -> None:
    """If torch has been imported in this process, pin its CPU
    thread count to 1.

    Idempotent: safe to call many times. Cheap when torch isn't
    loaded (one ``sys.modules`` lookup). When torch IS loaded but
    the pin call somehow raises (e.g. a stub module), we swallow
    the exception — the pin is a perf optimization, not a
    correctness requirement, and a worker that fails to pin still
    produces correct output (just slower).
    """
    torch = sys.modules.get("torch")
    if torch is None:
        return
    try:
        torch.set_num_threads(1)
    except Exception:  # noqa: BLE001 - perf-only optimization
        pass
