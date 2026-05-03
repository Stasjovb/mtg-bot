# Centralized NN inference server: benchmark notes

## TL;DR

At the **current 25k-param value-only / 58k-param dual-head**
network sizes, the centralized GPU inference server is **slower per
request** than per-worker local inference. The per-leaf forward is
already so cheap (a few microseconds on CPU at this model size) that
the localhost IPC round-trip dominates.

The architecture is correct and lands on the standard AlphaZero-at-
scale shape — the win arrives when **either**:

1. The model scales up (the 420k-param network already starts to make
   CUDA worthwhile; bigger architectures will tip further).
2. Worker batches grow (B1 batched leaf evaluation in MCTS, or moving
   from per-leaf to per-state-block evaluation), so the fixed IPC
   cost amortizes across more evals per request.

This commit is the infrastructure landing — the hooks are in place
so when (1) or (2) lands the centralized server immediately becomes
the hot path. Until then, leave `--use-nn-server` off.

## Microbench

`scripts/bench_nn_eval_server.py` fires N workers x M random feature
vectors. Random init, no engine, no MCTS — clean view of the IPC +
batching cost.

Test box: RTX 5090, Windows 11, Python 3.13, torch 2.11.0+cu128.

### Value-only path (FEATURE_DIM=51 → 1)

24 workers x 200 requests = 4800 evals total

| mode   | wall   | rps    | p50 lat | p95 lat |
|--------|--------|--------|---------|---------|
| local  | 3.84s  | 1249   | 0.110ms | 0.119ms |
| server | 7.22s  | 665    | 15.7ms  | 16.6ms  |

Server runs on CUDA with batch_size=32, batch_wait_ms=5.

### Dual-head path (value + 517-action policy)

24 workers x 1000 requests = 24000 evals total

| mode   | wall   | rps    | p50 lat | p95 lat |
|--------|--------|--------|---------|---------|
| local  | 3.88s  | 6192   | 0.169ms | 0.189ms |
| server | 19.8s  | 1210   | 15.7ms  | 16.7ms  |

Server batch_size=32, batch_wait_ms=5. Dropping batch_wait_ms to 0
moves wall to 17.0s / 1412 rps / 12.2ms p50 — most of the
remaining cost is localhost IPC, not the dispatcher's wait window.

## Why the server loses at this network size

The forward pass for a 25k-param MLP on a single FEATURE_DIM=51
input is on the order of ~10-20us on CPU. The localhost
multiprocessing.connection round-trip on Windows is ~10-15ms (driven
by Nagle, send/recv buffer flushes, and the per-message pickle).
That's **three orders of magnitude** of fixed overhead per request.
Batching across workers helps in theory, but only if multiple
workers happen to be queued at the same moment; in steady state,
each worker fires its next request only after its previous reply
arrives, so 24 workers at 15ms/cycle means at most ~1600 rps in
aggregate — well below the local-mode steady state.

## When the server wins

- **Larger networks**: scale HIDDEN_SIZES up to ~512x4 layers and
  the per-eval CPU forward starts to approach or exceed the IPC
  floor. CUDA becomes a real win once the matmul cost dominates.
- **Batched leaf evaluation in MCTS** (the B1 work): MCTS could
  send a batch of 32 leaves in one IPC round-trip, paying ~15ms
  for 32 evals instead of 32x15ms. Tested in `bench_nn_eval_server`
  via the `value_batch` path (1 worker, batch=32):
  - local:  387k evals/s
  - server: 2k evals/s on CUDA
  Same conclusion at this model size — the IPC overhead per request
  is still much larger than the saved per-eval forward cost.

## Recommendation

- Land the server module + tests now (architecture / contract is
  right, test coverage is high).
- Don't enable `--use-nn-server` for the current 25k/58k networks.
- Re-bench after the next architecture-scaling experiment (HIDDEN_SIZES
  bump) and after the batched-puct branch lands. Either should flip
  the comparison.

## How to reproduce

```bash
# Local mode (today's data-gen behavior)
python scripts/bench_nn_eval_server.py --mode local \
  --workers 24 --requests-per 200

# Server mode
python scripts/bench_nn_eval_server.py --mode server \
  --workers 24 --requests-per 200 \
  --server-batch-size 32 --server-batch-wait-ms 5

# Dual-head versions: add --with-policy
```
