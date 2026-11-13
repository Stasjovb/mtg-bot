"""``scripts/fish_learn.py train``: the early-stopping and regularisation options
reach the trainer's command line; an option left out keeps the trainer default."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from argparse import Namespace

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fish_learn.py"


@pytest.fixture(scope="module")
def fl():
    spec = importlib.util.spec_from_file_location("fish_learn_args", _PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("fish_learn_args", module)
    spec.loader.exec_module(module)
    return module


def _captured_train_command(fl, monkeypatch, args):
    seen = {}

    def fake_call(cmd, env=None):
        seen["cmd"] = cmd
        return 0

    monkeypatch.setattr(fl.subprocess, "call", fake_call)
    assert fl.cmd_train(args) == 0
    return seen["cmd"]


def test_the_regularisation_options_reach_the_trainer(fl, tmp_path, monkeypatch):
    args = Namespace(
        data_dir=tmp_path, registry_root=tmp_path / "reg", epochs=4, notes="n",
        window_files=None, threads=None, early_stop_patience=1, lr=3e-4,
        dropout=0.1, weight_decay=1e-4, value_target="root",
    )
    cmd = _captured_train_command(fl, monkeypatch, args)
    assert cmd[cmd.index("--early-stop-patience") + 1] == "1"
    assert cmd[cmd.index("--lr") + 1] == "0.0003"
    assert cmd[cmd.index("--dropout") + 1] == "0.1"
    assert cmd[cmd.index("--weight-decay") + 1] == "0.0001"
    assert cmd[cmd.index("--value-target") + 1] == "root"


def test_options_left_out_keep_the_trainer_defaults(fl, tmp_path, monkeypatch):
    args = Namespace(
        data_dir=tmp_path, registry_root=tmp_path / "reg", epochs=4, notes="n",
        window_files=None, threads=None,
    )
    cmd = _captured_train_command(fl, monkeypatch, args)
    # The patience the trainer would use anyway is passed explicitly.
    assert cmd[cmd.index("--early-stop-patience") + 1] == "3"
    for flag in ("--lr", "--dropout", "--weight-decay", "--value-target"):
        assert flag not in cmd


def test_the_window_option_still_comes_first_and_is_unchanged(fl, tmp_path, monkeypatch):
    args = Namespace(
        data_dir=tmp_path, registry_root=tmp_path / "reg", epochs=2, notes="n",
        window_files=4, threads=None,
    )
    cmd = _captured_train_command(fl, monkeypatch, args)
    assert cmd[cmd.index("--window-recent-files") + 1] == "4"
    assert cmd[cmd.index("--epochs") + 1] == "2"
