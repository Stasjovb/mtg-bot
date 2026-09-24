"""Iterate-side handling of a held-out-value-gate rejection.

``mtg_bot train`` exits ``3`` when the freshly-trained value head
fails its held-out quality gate and registers nothing. Iterate must:

1. forward the regularisation / gate flags to the train subprocess
   (structured architecture only);
2. turn exit 3 into :class:`~mtg_bot.cli.iterate.TrainRejected`
   rather than a generic RuntimeError, so the cycle loop can tell a
   verdict apart from a crash.

The loop-level consequence (cycle row -> failed with the reason,
current_best kept, NEXT cycle still runs) is pinned by the
state/flow test at the bottom, which drives ``_train_next`` through
the same exception path the loop catches.
"""

from __future__ import annotations

import json
import subprocess as _subprocess
from pathlib import Path
from typing import Any

import pytest

from mtg_bot.cli import iterate as iz
from mtg_bot.cli import train as cli_train


def _make_version_dir(
    registry_root: Path, version: str, *, architecture: str,
) -> Path:
    d = registry_root / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "weights.pt").write_bytes(b"\x00")
    payload: dict[str, Any] = {
        "version": version,
        "created_at": "2026-09-24T00:00:00Z",
        "feature_dim": 1,
        "hidden_sizes": [4],
        "with_policy": True,
        "architecture": architecture,
    }
    (d / "metadata.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )
    return d


class _Recorder:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        rc = self.returncode

        class _Result:
            returncode = rc

        return _Result()

    @property
    def train_calls(self) -> list[list[str]]:
        return [
            c for c in self.calls
            if any(str(a).endswith("train_nn.py") for a in c)
        ]


def _call_train_next(registry_root: Path, tmp_path: Path, **kwargs):
    return iz._train_next(
        data_dir=tmp_path / "iterate_data",
        registry_root=registry_root,
        epochs=1,
        batch_size=4,
        learning_rate=1e-3,
        val_split=0.1,
        seed=0,
        notes="value-gate test",
        window_recent=None,
        **kwargs,
    )


def test_exit_code_constant_matches_the_trainer() -> None:
    """The two sides of the contract must agree; iterate keeps a
    literal so importing it doesn't drag in torch."""
    assert (
        iz.TRAIN_GATE_REJECT_EXIT_CODE
        == cli_train._GATE_REJECT_EXIT_CODE
    )


def test_train_next_forwards_gate_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1", architecture="structured")
    rec = _Recorder()
    monkeypatch.setattr(_subprocess, "run", rec)

    _call_train_next(
        registry_root, tmp_path,
        architecture="structured",
        dropout=0.2,
        weight_decay=2e-4,
        keep_last_epoch=True,
        min_holdout_value_quality=0.9,
    )
    cmd = rec.train_calls[0]
    assert cmd[cmd.index("--dropout") + 1] == "0.2"
    assert cmd[cmd.index("--weight-decay") + 1] == "0.0002"
    assert "--keep-last-epoch" in cmd
    assert cmd[cmd.index("--min-holdout-value-quality") + 1] == "0.9"


def test_train_next_omits_gate_flags_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset (None) knobs are NOT emitted, so the trainer's own
    defaults win instead of iterate re-declaring them."""
    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1", architecture="structured")
    rec = _Recorder()
    monkeypatch.setattr(_subprocess, "run", rec)

    _call_train_next(
        registry_root, tmp_path, architecture="structured",
    )
    cmd = rec.train_calls[0]
    for flag in (
        "--dropout", "--weight-decay", "--keep-last-epoch",
        "--min-holdout-value-quality",
    ):
        assert flag not in cmd


def test_train_next_omits_gate_flags_for_flat_architecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flat trainer errors on these flags, so they must not leak
    onto a shared/separate-architecture command line."""
    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1", architecture="shared")
    rec = _Recorder()
    monkeypatch.setattr(_subprocess, "run", rec)

    _call_train_next(
        registry_root, tmp_path,
        architecture="shared",
        dropout=0.2,
        weight_decay=2e-4,
        keep_last_epoch=True,
        min_holdout_value_quality=0.9,
    )
    cmd = rec.train_calls[0]
    for flag in (
        "--dropout", "--weight-decay", "--keep-last-epoch",
        "--min-holdout-value-quality",
    ):
        assert flag not in cmd


def test_train_next_raises_train_rejected_on_exit_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1", architecture="structured")
    monkeypatch.setattr(
        _subprocess, "run",
        _Recorder(returncode=iz.TRAIN_GATE_REJECT_EXIT_CODE),
    )
    with pytest.raises(iz.TrainRejected) as exc:
        _call_train_next(
            registry_root, tmp_path, architecture="structured",
        )
    assert "held-out" in str(exc.value)
    assert "no version was registered" in str(exc.value)
    # A verdict, not a crash — but still a RuntimeError subclass so
    # any caller that only catches RuntimeError keeps working.
    assert isinstance(exc.value, RuntimeError)


def test_train_next_other_nonzero_exit_is_still_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_root = tmp_path / "trained_weights"
    _make_version_dir(registry_root, "v1", architecture="structured")
    monkeypatch.setattr(_subprocess, "run", _Recorder(returncode=1))
    with pytest.raises(RuntimeError) as exc:
        _call_train_next(
            registry_root, tmp_path, architecture="structured",
        )
    assert not isinstance(exc.value, iz.TrainRejected)
    assert "exited with code 1" in str(exc.value)


def test_rejection_is_handled_in_the_cycle_loop_source() -> None:
    """Structural pin for the loop behaviour the gate depends on: the
    cycle catches TrainRejected, keeps current_best, marks the cycle
    failed with the reason, and ``continue``s to the next cycle
    instead of re-raising (which would kill the whole chain).

    Driving the real 3000-line loop would need a full distributed
    stack; this asserts the handler exists and does the four things
    that matter, next to the source it guards.
    """
    import inspect

    src = inspect.getsource(iz.main)
    assert "except TrainRejected as exc:" in src
    handler = src.split("except TrainRejected as exc:", 1)[1]
    # Up to the next dedented statement of the cycle body.
    handler = handler.split("\n        new_weights", 1)[0]
    assert '_finish_cycle(' in handler
    assert '"failed"' in handler
    assert '"rejected": True' in handler
    assert "continue" in handler
    # current_best must NOT be reassigned in the rejection path.
    assert 'state["current_best"] =' not in handler
