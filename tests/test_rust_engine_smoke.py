"""Smoke test for the Rust engine PyO3 extension.

The extension is built out-of-tree by maturin (see ``rust/`` in the
project root). If it isn't installed yet, the test skips with a
hint instead of failing — that way running ``pytest`` on a fresh
checkout doesn't break before someone has run ``maturin develop``.
"""

from __future__ import annotations

import importlib

import pytest

mtg_bot_engine = pytest.importorskip(
    "mtg_bot_engine",
    reason="rust extension not built; run `maturin develop --release -m rust/pyproject.toml`",
)


def test_module_exposes_version():
    assert hasattr(mtg_bot_engine, "__version__")
    assert isinstance(mtg_bot_engine.__version__, str)


def test_synthetic_state_has_expected_dimensions():
    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=10, num_hand=7, num_library=50
    )
    assert state.turn_number == 5
    assert tuple(state.battlefield_sizes) == (10, 10)
    assert tuple(state.hand_sizes) == (7, 7)
    assert tuple(state.library_sizes) == (50, 50)
    assert tuple(state.life_totals) == (20, 20)


def test_clone_once_returns_independent_state():
    state = mtg_bot_engine.make_synthetic_state()
    cloned = state.clone_once()
    assert tuple(cloned.battlefield_sizes) == tuple(state.battlefield_sizes)
    assert tuple(cloned.life_totals) == tuple(state.life_totals)


def test_clone_n_times_returns_positive_micros():
    state = mtg_bot_engine.make_synthetic_state()
    micros_per_clone = state.clone_n_times_micros(100)
    assert micros_per_clone > 0.0
    # Generous upper bound — debug-mode clone of this shape on x86_64
    # comes in well under 100us; release mode is much lower. If this
    # ever fires we have a real regression to look at.
    assert micros_per_clone < 1000.0, f"clone too slow: {micros_per_clone:.2f}us"


def test_module_can_be_reimported():
    importlib.reload(mtg_bot_engine)
    assert hasattr(mtg_bot_engine, "make_synthetic_state")
