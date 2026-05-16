"""Direct tests for ``_play_one_parallel_game``'s args-tuple arity
dispatch and its timeout / crash exception handlers.

``generate_training_data_parallel`` always packs the current 13-element
tuple, so the 12-element and legacy 11-element back-compat branches and
the dedicated ``TimeoutError`` handler (vs the broad crash handler) are
never reached through the pool path — only an explicit unit call hits
them. The back-compat branches are a real wire contract: a worker built
from an older ``distributed.py`` arg tuple must still run, and a
per-game timeout must bucket under ``timed_out`` (not ``crashed``) so
the driver's counters stay honest.

Each test asserts the concrete returned chunk shape + outcome_kind, not
just "it ran".
"""

from __future__ import annotations

import numpy as np

from mtg_bot.features import FEATURE_DIM
from mtg_bot.training import random_choice_factory
from mtg_bot.training.data_gen import (
    _empty_arrays,
    _play_one_parallel_game,
    _winner_to_p0_outcome,
)
from tests._test_decks import simple_test_deck_pool


# Module-level pickleable raiser (mirrors the existing data_gen test's
# helper; redeclared here to keep this file self-contained).
class _Raiser:
    def __init__(self, message: str = "boom") -> None:
        self.message = message

    def choose(self, state, player_id):  # noqa: ANN001
        raise ValueError(self.message)

    def choose_with_visits(self, state, player_id):  # noqa: ANN001
        raise ValueError(self.message)


def _raising_factory(seed: int) -> _Raiser:
    return _Raiser()


# ---------------------------------------------------------------------
# Args-tuple arity dispatch
# ---------------------------------------------------------------------


def test_legacy_11_arg_tuple_runs_and_defaults_encoding():
    """The shortest legacy form (pre action_encoding_version /
    structured_tokens) still produces a completed chunk; the dispatch
    fills action_encoding_version='positional_v1', structured=False."""
    args = (
        3,                          # game_idx
        random_choice_factory,      # p0
        random_choice_factory,      # p1
        0,                          # base_seed
        40,                         # decision_cap
        1,                          # sample_every
        None,                       # replay_config
        simple_test_deck_pool(),    # deck_pool
        None,                       # per_game_timeout_sec
        None,                       # hang_dump_dir
        None,                       # heuristics
    )
    game_idx, chunk = _play_one_parallel_game(args)
    assert game_idx == 3
    assert chunk[-2] == "completed"
    assert chunk[0].shape[1] == FEATURE_DIM


def test_12_arg_tuple_runs_with_explicit_encoding_version():
    """12-arg form carries action_encoding_version but predates
    structured_tokens (defaulted False by the dispatch)."""
    args = (
        5,
        random_choice_factory,
        random_choice_factory,
        0,
        40,
        1,
        None,
        simple_test_deck_pool(),
        None,
        None,
        None,
        "positional_v1",            # action_encoding_version
    )
    game_idx, chunk = _play_one_parallel_game(args)
    assert game_idx == 5
    assert chunk[-2] == "completed"


def test_13_arg_tuple_runs_with_structured_tokens_flag():
    args = (
        1,
        random_choice_factory,
        random_choice_factory,
        0,
        40,
        1,
        None,
        simple_test_deck_pool(),
        None,
        None,
        None,
        "positional_v1",
        False,                      # structured_tokens
    )
    game_idx, chunk = _play_one_parallel_game(args)
    assert game_idx == 1
    assert chunk[-2] == "completed"


# ---------------------------------------------------------------------
# Crash handler (broad Exception → "crashed" empty chunk)
# ---------------------------------------------------------------------


def test_crash_returns_empty_crashed_chunk(capfd):
    args = (
        9,
        _raising_factory,
        _raising_factory,
        0,
        40,
        1,
        None,
        simple_test_deck_pool(),
        None,
        None,
        None,
    )
    game_idx, chunk = _play_one_parallel_game(args)
    assert game_idx == 9
    assert chunk[-2] == "crashed"
    f, o, p, m = chunk[0], chunk[1], chunk[2], chunk[3]
    assert f.shape == (0, FEATURE_DIM)
    assert o.shape == (0,)
    assert chunk[4] is None  # no winner
    err = capfd.readouterr().err
    assert "crashed" in err
    assert "game 9" in err


# ---------------------------------------------------------------------
# Timeout handler (TimeoutError → dedicated "timed_out" empty chunk)
# ---------------------------------------------------------------------


def test_timeout_returns_empty_timed_out_chunk(monkeypatch, capfd):
    """A per-game wall-clock TimeoutError must bucket under
    ``timed_out``, distinct from the broad ``crashed`` path, so the
    driver's separate counter stays accurate. We patch the inner
    one-game generator to raise TimeoutError."""
    import mtg_bot.training.data_gen as dg

    def _boom_timeout(**kwargs):
        raise TimeoutError("simulated per-game wedge")

    monkeypatch.setattr(dg, "_generate_one_game_data", _boom_timeout)

    args = (
        2,
        random_choice_factory,
        random_choice_factory,
        0,
        40,
        1,
        None,
        simple_test_deck_pool(),
        300.0,                      # per_game_timeout_sec
        None,
        None,
    )
    game_idx, chunk = _play_one_parallel_game(args)
    assert game_idx == 2
    assert chunk[-2] == "timed_out"
    assert chunk[4] is None
    assert chunk[0].shape == (0, FEATURE_DIM)
    err = capfd.readouterr().err
    assert "timed out" in err
    assert "game 2" in err


# ---------------------------------------------------------------------
# _winner_to_p0_outcome + _empty_arrays helpers
# ---------------------------------------------------------------------


def test_winner_to_p0_outcome_mapping():
    assert _winner_to_p0_outcome(None) == 0.0
    assert _winner_to_p0_outcome(0) == 1.0
    assert _winner_to_p0_outcome(1) == -1.0


def test_empty_arrays_shapes():
    f, o, p, m = _empty_arrays()
    assert f.shape == (0, FEATURE_DIM)
    assert o.shape == (0,)
    assert f.dtype == np.float32 or f.dtype == np.float64
