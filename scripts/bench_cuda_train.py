"""One-shot bench: CPU vs CUDA training and inference for the value
network architectures. Run with PYTHONPATH=src.

Generates synthetic 100k x FEATURE_DIM data, runs 10 epochs of
training on CPU and CUDA for both _ValueMLP and _ValuePolicyMLP, and
times inference at batch=1 and batch=32 on each device.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from mtg_bot.features import FEATURE_DIM
from mtg_bot.search.nn_evaluator import _ValueMLP, _ValuePolicyMLP


def _count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def _bench_train(
    arch: str,
    device: str,
    n_samples: int = 100_000,
    epochs: int = 10,
    batch_size: int = 256,
    rng_seed: int = 0,
) -> dict[str, float]:
    """Time `epochs` of training on `n_samples` synthetic rows for the
    requested architecture on the requested device. Returns a dict
    with avg/min/max per-epoch seconds.
    """
    torch.manual_seed(rng_seed)
    rng = np.random.default_rng(rng_seed)

    features = rng.standard_normal((n_samples, FEATURE_DIM)).astype(np.float32)
    outcomes = rng.choice([-1.0, 0.0, 1.0], size=n_samples).astype(np.float32)
    x = torch.from_numpy(features)
    y = torch.from_numpy(outcomes).unsqueeze(1)

    if device == "cpu":
        torch.set_num_threads(1)
    device_obj = torch.device(device)

    if arch == "value":
        model: nn.Module = _ValueMLP()
        loss_fn_value = nn.MSELoss()

        def step(batch_x: torch.Tensor, batch_y: torch.Tensor) -> torch.Tensor:
            pred = model(batch_x)
            return loss_fn_value(pred, batch_y)

        # Synthetic policy targets too — but value-only training only
        # uses value loss.
        policy_y: Optional[torch.Tensor] = None

    elif arch == "value_policy":
        model = _ValuePolicyMLP()
        loss_value = nn.MSELoss()
        loss_policy = nn.CrossEntropyLoss()
        # synthetic visit-count distributions: pick a uniform random
        # legal-target index. Use cross-entropy with class indices.
        from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
        policy_targets_np = rng.integers(
            0, ACTION_VOCAB_SIZE, size=n_samples,
        ).astype(np.int64)
        policy_y = torch.from_numpy(policy_targets_np)

        def step(batch_x: torch.Tensor, batch_y: torch.Tensor) -> torch.Tensor:
            value_pred, policy_logits = model(batch_x)
            v_loss = loss_value(value_pred, batch_y)
            # policy_y_batch lives in the closure via ``current_policy``
            # — set per batch below.
            p_loss = loss_policy(policy_logits, current_policy["batch"])
            return v_loss + p_loss

        current_policy: dict[str, torch.Tensor] = {}
    else:
        raise ValueError(arch)

    model = model.to(device_obj)
    optimizer = optim.Adam(model.parameters(), lr=1e-3)

    if arch == "value_policy":
        ds = TensorDataset(x, y, policy_y)
    else:
        ds = TensorDataset(x, y)
    loader = DataLoader(
        ds, batch_size=batch_size, shuffle=True,
        generator=torch.Generator().manual_seed(rng_seed),
    )

    epoch_times: list[float] = []
    model.train()
    for _ in range(epochs):
        if device == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        for batch in loader:
            if arch == "value_policy":
                bx, by, bp = batch
                bx = bx.to(device_obj, non_blocking=True)
                by = by.to(device_obj, non_blocking=True)
                bp = bp.to(device_obj, non_blocking=True)
                current_policy["batch"] = bp
            else:
                bx, by = batch
                bx = bx.to(device_obj, non_blocking=True)
                by = by.to(device_obj, non_blocking=True)
            optimizer.zero_grad()
            loss = step(bx, by)
            loss.backward()
            optimizer.step()
        if device == "cuda":
            torch.cuda.synchronize()
        epoch_times.append(time.perf_counter() - t0)

    return {
        "params": _count_params(model),
        "avg_s": float(np.mean(epoch_times)),
        "min_s": float(np.min(epoch_times)),
        "max_s": float(np.max(epoch_times)),
    }


def _bench_inference(
    arch: str,
    device: str,
    batch_sizes: tuple[int, ...] = (1, 32),
    iters: int = 1000,
    rng_seed: int = 0,
) -> dict[int, float]:
    """Time `iters` inference forward passes at each batch size.
    Returns dict batch_size → microseconds per call."""
    torch.manual_seed(rng_seed)
    if device == "cpu":
        torch.set_num_threads(1)
    device_obj = torch.device(device)

    if arch == "value":
        model: nn.Module = _ValueMLP()
    else:
        model = _ValuePolicyMLP()
    model = model.to(device_obj).eval()

    out: dict[int, float] = {}
    for bs in batch_sizes:
        x = torch.randn(bs, FEATURE_DIM, device=device_obj)
        # warmup
        with torch.no_grad():
            for _ in range(20):
                _ = model(x)
            if device == "cuda":
                torch.cuda.synchronize()
        with torch.no_grad():
            t0 = time.perf_counter()
            for _ in range(iters):
                _ = model(x)
            if device == "cuda":
                torch.cuda.synchronize()
            elapsed = time.perf_counter() - t0
        per_call_us = (elapsed / iters) * 1e6
        out[bs] = per_call_us
    return out


def main() -> None:
    print(f"torch {torch.__version__}")
    print(f"cuda available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"device: {torch.cuda.get_device_name(0)}")
    print(f"FEATURE_DIM: {FEATURE_DIM}")
    print()

    devices = ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")

    for arch in ("value", "value_policy"):
        print(f"=== arch: {arch} ===")
        for device in devices:
            r = _bench_train(arch, device)
            print(
                f"  train {device:4s}: params={r['params']} "
                f"avg={r['avg_s']*1000:.1f}ms/epoch "
                f"min={r['min_s']*1000:.1f}ms "
                f"max={r['max_s']*1000:.1f}ms"
            )
        for device in devices:
            inf = _bench_inference(arch, device)
            parts = " ".join(
                f"b={bs}:{us:.1f}us" for bs, us in inf.items()
            )
            print(f"  infer {device:4s}: {parts}")
        print()


if __name__ == "__main__":
    main()
