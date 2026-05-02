# GPU (CUDA) setup for training and inference

## Summary

`torch 2.11.0+cu128` is installed in `.venv-py313/` and runs against
an NVIDIA RTX 5090 (Blackwell, sm_120). `torch.cuda.is_available()`
returns `True`; `auto_device()` in `src/mtg_bot/training/trainer.py`
picks `"cuda"` automatically when CUDA is available, falling back to
`"cpu"` otherwise.

## Verified configuration

- **GPU**: NVIDIA GeForce RTX 5090 (32 GB)
- **Driver**: 591.74 (reports `CUDA Version: 13.1` capability)
- **PyTorch**: `2.11.0+cu128` (CUDA-12.8 wheel — Blackwell-native)
- **cuDNN**: 91900
- **Python**: 3.13 (the `.venv-py313/` interpreter)

## Install / reinstall

From the project root:

```
.venv-py313/Scripts/python.exe -m pip install --upgrade torch \
    --index-url https://download.pytorch.org/whl/cu128
```

This pulls a ~2.7 GB wheel that bundles the CUDA 12.8 runtime; no
separate CUDA toolkit install is required.

## Smoke check

```
.venv-py313/Scripts/python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Expect:

```
2.11.0+cu128 True NVIDIA GeForce RTX 5090
```

## Performance: when GPU helps

At today's network sizes the GPU is roughly tied with single-threaded
CPU because per-batch Python↔CUDA dispatch overhead dominates the
actual matmul work. Bench numbers from `scripts/bench_cuda_train.py`
(100k synthetic samples, batch=256, 10 epochs, single torch thread on
CPU):

| Architecture           | Params | CPU avg/epoch | CUDA avg/epoch |
| ---------------------- | ------ | ------------- | -------------- |
| `_ValueMLP` (value-only) | 31 489 | 1 476 ms      | 1 477 ms       |
| `_ValuePolicyMLP`      | 65 094 | 2 313 ms      | 1 968 ms       |

Inference (per forward pass, microseconds):

| Architecture       | Device | b=1     | b=32    |
| ------------------ | ------ | ------- | ------- |
| `_ValueMLP`        | CPU    |  95 µs  | 138 µs  |
| `_ValueMLP`        | CUDA   | 356 µs  | 382 µs  |
| `_ValuePolicyMLP`  | CPU    | 115 µs  | 207 µs  |
| `_ValuePolicyMLP`  | CUDA   | 398 µs  | 464 µs  |

For inference inside MCTS, **CPU is much faster at small batch sizes**
because the per-call CUDA round-trip costs ~250-300 µs. The crossover
will move once batches get large enough or the trunk grows past
several hundred K params.

## What stays CPU-only

- **Self-play data generation.** `src/mtg_bot/training/data_gen.py`
  does not call `auto_device()` — multiprocessing workers play games
  via the engine, no NN involved, so they never grab the GPU.
- **Most tests.** Tests that train or score the network explicitly
  pass `device='cpu'` so test behavior is independent of which host
  has a CUDA device. Adding GPU silently to test code would split
  CI from local in subtle ways; the explicit `cpu` argument is
  intentional.
- **`torch.set_num_threads(1)`** — `train_value_network` only pins
  threads when `device == "cpu"`. On CUDA the pin is skipped (the
  setting only governs CPU OMP/MKL parallelism), so GPU training is
  unaffected.

## When to revisit

The GPU is sitting idle today but earns its keep once any of these
land:

- A trunk much wider/deeper than `(128, 128, 64)` (post-A4-wiring,
  policy supervision driving capacity scaling).
- Batched inference inside MCTS with a fat batch (e.g. PUCT with
  large rollout fan-out per leaf).
- Multi-network training (ensembles, league-style agents).
