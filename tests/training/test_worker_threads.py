"""Tests for the worker-side torch thread pin helper."""

from __future__ import annotations

import sys
import types

import pytest

from mtg_bot.training._worker_threads import pin_worker_torch_threads


def test_noop_when_torch_not_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``torch`` is absent from ``sys.modules`` the helper must
    return without raising and without forcing a torch import — the
    whole point of looking up sys.modules instead of try/except
    ``import torch`` is to keep the training package torch-free at
    load time."""
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    pin_worker_torch_threads()
    # Confirm the call did not implicitly import torch.
    assert "torch" not in sys.modules


def test_pins_to_one_when_torch_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """When torch is loaded, the helper calls
    ``torch.set_num_threads(1)``. We register a stub module so this
    test runs without depending on a real torch install."""
    calls: list[int] = []

    fake_torch = types.SimpleNamespace(
        set_num_threads=lambda n: calls.append(n),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    pin_worker_torch_threads()
    assert calls == [1]


def test_idempotent_on_repeated_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``set_num_threads`` is idempotent — calling pin many times
    just calls through that many times, all with arg=1."""
    calls: list[int] = []
    fake_torch = types.SimpleNamespace(
        set_num_threads=lambda n: calls.append(n),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    for _ in range(5):
        pin_worker_torch_threads()
    assert calls == [1, 1, 1, 1, 1]


def test_swallows_exception_from_set_num_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pin is perf-only; if the underlying call raises (broken
    torch stub, exotic build, etc.) the helper must NOT propagate
    — a worker that fails to pin still produces correct output."""

    def boom(_n: int) -> None:
        raise RuntimeError("simulated torch failure")

    fake_torch = types.SimpleNamespace(set_num_threads=boom)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    # Must not raise.
    pin_worker_torch_threads()
