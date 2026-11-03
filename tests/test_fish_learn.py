"""``scripts/fish_learn.py``: data thinning, chunk joining, the loop's
state and promotion logic, and the trainer's CPU-thread override."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from argparse import Namespace
from datetime import datetime

import numpy as np
import pytest

from mtg_bot.training import trainer
from mtg_bot.training.gate import EVAL_GATE_THRESHOLD

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fish_learn.py"


@pytest.fixture(scope="module")
def fl():
    spec = importlib.util.spec_from_file_location("fish_learn", _PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("fish_learn", module)
    spec.loader.exec_module(module)
    return module


def _chunk(n_rows, legal_counts, width, start_id=0):
    """A generator-shaped 9-tuple: features, outcomes, policy, masks,
    4 token arrays (``width`` tokens), game ids."""
    masks = np.zeros((n_rows, 6), dtype=bool)
    for i, k in enumerate(legal_counts):
        masks[i, :k] = True
    rows = np.arange(n_rows)
    return (
        rows[:, None].astype(np.float32).repeat(3, axis=1),
        np.ones(n_rows, dtype=np.float32),
        masks.astype(np.float32),
        masks,
        np.ones((n_rows, width), dtype=np.int64),
        np.ones((n_rows, width, 7), dtype=np.int64),
        np.ones((n_rows, width, 29), dtype=np.float32),
        np.ones((n_rows, width), dtype=bool),
        (rows // 2 + start_id).astype(np.int32),
    )


def test_thin_rows_keeps_every_real_choice(fl):
    legal = [0, 1, 2, 3, 0, 1, 5, 0]
    out = fl.thin_rows(_chunk(8, legal, 4), 0.0, np.random.default_rng(0))
    # Only the rows with 2+ legal actions survive keep_other=0.
    assert out[3].sum(axis=1).tolist() == [2, 3, 5]
    assert out[0][:, 0].tolist() == [2, 3, 6]
    assert all(len(a) == 3 for a in out)


def test_thin_rows_keep_other_one_keeps_everything(fl):
    out = fl.thin_rows(_chunk(8, [0, 1] * 4, 4), 1.0, np.random.default_rng(0))
    assert all(len(a) == 8 for a in out)


def test_thin_rows_samples_about_keep_other_of_the_rest(fl):
    n = 4000
    out = fl.thin_rows(_chunk(n, [1] * n, 2), 0.1, np.random.default_rng(1))
    assert 300 < len(out[0]) < 500


def test_concat_parts_pads_token_arrays_to_the_widest_chunk(fl):
    a = _chunk(2, [2, 2], 3)
    b = _chunk(3, [2, 2, 2], 5, start_id=10)
    out = fl.concat_parts([a, b])
    assert out[4].shape == (5, 5)
    assert out[5].shape == (5, 5, 7)
    assert out[6].shape == (5, 5, 29)
    assert out[7].shape == (5, 5)
    # The narrow chunk's padding is zeros (attention mask False).
    assert out[7][:2, 3:].sum() == 0 and out[7][:2, :3].all()
    assert out[8].tolist() == [0, 0, 10, 10, 11]
    assert out[0].shape == (5, 3)


@pytest.mark.parametrize("start, until, expected", [
    (datetime(2026, 11, 3, 23, 0), "07:00", datetime(2026, 11, 4, 7, 0)),
    (datetime(2026, 11, 3, 9, 0), "17:30", datetime(2026, 11, 3, 17, 30)),
    (datetime(2026, 11, 3, 7, 0), "07:00", datetime(2026, 11, 4, 7, 0)),
])
def test_deadline_after(fl, start, until, expected):
    assert fl.deadline_after(start, until) == expected


def test_structured_cpu_threads_default_and_override(monkeypatch):
    monkeypatch.delenv(trainer.CPU_THREADS_ENV, raising=False)
    assert trainer.structured_cpu_threads() == 1
    monkeypatch.setenv(trainer.CPU_THREADS_ENV, "8")
    assert trainer.structured_cpu_threads() == 8
    monkeypatch.setenv(trainer.CPU_THREADS_ENV, "0")
    with pytest.raises(ValueError, match="must be >= 1"):
        trainer.structured_cpu_threads()


def _loop_args(tmp_path, rounds=1, until=None):
    return Namespace(
        rounds=rounds, until=until, data_dir=tmp_path / "data",
        registry_root=tmp_path / "reg", decklist=tmp_path / "list.txt",
        games=4, eval_games=2, epochs=1, window_files=4, threads=8,
        workers=1, samples=1, nodes=1, seed=0, per_game_timeout=60.0,
        chunk_games=2, keep_other=0.1,
    )


class _Fakes:
    """Stand-ins for gen / train / eval: train registers ``v{N}`` dirs
    the way the registry lists them; eval returns scripted scores."""

    def __init__(self, scores, train_exits=None):
        self.scores = list(scores)
        self.train_exits = list(train_exits or [])
        self.gen_calls, self.eval_calls = [], []

    def gen(self, a):
        self.gen_calls.append(a)
        return a.out_dir / f"{a.tag}.npz"

    def train(self, a):
        rc = self.train_exits.pop(0) if self.train_exits else 0
        if rc == 0:
            n = len([p for p in a.registry_root.glob("v*")]) + 1
            v = a.registry_root / f"v{n}"
            v.mkdir()
            (v / "weights.pt").write_bytes(b"w")
            (v / "metadata.json").write_text("{}", encoding="utf-8")
        return rc

    def evaluate(self, a):
        self.eval_calls.append((a.new, a.old))
        s = self.scores.pop(0)
        return s, (int(s * 10), 10 - int(s * 10), 0)


def test_loop_promotes_a_version_that_beats_the_best(fl, tmp_path):
    f = _Fakes([0.9, 0.4])
    state = fl.cmd_loop(_loop_args(tmp_path, rounds=2),
                        gen=f.gen, train=f.train, evaluate=f.evaluate)
    # Round 1: heuristic plays, v1 beats it; round 2: v1 plays, v2 loses.
    assert [g.nn_version for g in f.gen_calls] == [None, "v1"]
    assert f.eval_calls == [("v1", "heuristic"), ("v2", "v1")]
    assert state["current_best"] == "v1"
    assert [r["promoted"] for r in state["rounds"]] == [True, False]
    saved = json.loads((tmp_path / "reg" / fl.LOOP_STATE).read_text())
    assert saved == state


def test_loop_gate_is_the_shared_threshold(fl, tmp_path):
    f = _Fakes([EVAL_GATE_THRESHOLD])
    state = fl.cmd_loop(_loop_args(tmp_path), gen=f.gen, train=f.train,
                        evaluate=f.evaluate)
    assert state["current_best"] == "v1"


def test_loop_resumes_from_its_state_file(fl, tmp_path):
    fl.cmd_loop(_loop_args(tmp_path), gen=(f := _Fakes([0.9])).gen,
                train=f.train, evaluate=f.evaluate)
    g = _Fakes([0.1])
    state = fl.cmd_loop(_loop_args(tmp_path), gen=g.gen, train=g.train,
                        evaluate=g.evaluate)
    assert g.gen_calls[0].nn_version == "v1"
    assert g.gen_calls[0].tag == "round002"
    assert [r["round"] for r in state["rounds"]] == [1, 2]


def test_loop_skips_eval_when_training_is_refused(fl, tmp_path):
    f = _Fakes([0.9], train_exits=[3, 0])
    state = fl.cmd_loop(_loop_args(tmp_path, rounds=2), gen=f.gen,
                        train=f.train, evaluate=f.evaluate)
    assert state["rounds"][0]["result"] == "training refused or failed"
    assert state["rounds"][0]["train_exit"] == 3
    assert f.eval_calls == [("v1", "heuristic")]
    assert state["current_best"] == "v1"


def test_loop_starts_no_round_past_the_deadline(fl, tmp_path, monkeypatch):
    f = _Fakes([])
    monkeypatch.setattr(fl, "deadline_after", lambda start, hhmm: start)
    state = fl.cmd_loop(_loop_args(tmp_path, rounds=3, until="07:00"),
                        gen=f.gen, train=f.train, evaluate=f.evaluate)
    assert f.gen_calls == [] and state["rounds"] == []
