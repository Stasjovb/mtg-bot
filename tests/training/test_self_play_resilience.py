"""Tests for ``run_match_parallel``'s worker-crash resilience.

Mirrors the worker-crash handling in
``mtg_bot.training.data_gen._play_one_parallel_game``. The
production motivation: a residual ~1-in-1000 PIMC engine state-
corruption bug surfaces as a ``ValueError`` mid-game; without
catching it inside the worker, ``pool.map`` / ``pool.imap_unordered``
re-raises and aborts the entire eval (losing ~99 games of useful
data). The fix is to catch ``Exception`` in the worker, emit a
traceback to stderr, and return a ``(None, 0)`` "crashed" sentinel
that the driver re-detects, counts toward
``MatchStats.draws``, and surfaces via a loud stderr summary.

The contract the tests pin down:

1. ``_play_one_match_game_packed`` returns ``(None, 0)`` and writes
   a traceback to stderr when the inner game raises.
2. ``_play_one_match_game_indexed`` returns ``(game_idx, (None, 0))``
   on the same error path (preserves the ``game_idx`` so the parallel
   driver can still re-sort ``imap_unordered`` results).
3. ``run_match_parallel`` (no-progress / ``pool.map`` path) survives
   a factory that raises mid-game, counts the crashed game as a
   draw in ``MatchStats``, and emits a ``# WARNING: K/N games
   crashed ...`` summary to stderr.
4. ``run_match_parallel`` (progress-tracked / ``imap_unordered``
   path) survives the same scenario, finalizes the progress tracker
   with status='completed', and emits the same stderr summary.

The tests use a module-level ``RaisesOnceFactory`` so multiprocessing
can pickle it across the spawn boundary on Windows.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from mtg_bot.training import (
    EvalProgress, random_choice_factory,
)
from mtg_bot.training.self_play import (
    _play_one_match_game_indexed,
    _play_one_match_game_packed,
    run_match_parallel,
)


# Module-level so multiprocessing can pickle this across spawn.
class _RaisingStrategy:
    """Strategy that raises ``ValueError`` on its first ``choose``
    call. Stand-in for the residual ~1/1000 PIMC engine state-
    corruption bug ("card N not castable by PX") that the eval pool
    must survive without aborting."""

    def __init__(self, message: str = "simulated engine corruption") -> None:
        self.message = message

    def choose(self, state, player_id):  # noqa: ANN001 - matches search API
        raise ValueError(self.message)

    def choose_with_visits(self, state, player_id):  # noqa: ANN001
        return {}


def _raising_factory(seed: int) -> _RaisingStrategy:
    """Top-level pickleable factory: every game built with this
    factory raises on its first decision. Used to simulate the
    state-corruption bug in tests."""
    return _RaisingStrategy()


# Selectively raises based on the ``MTG_BOT_EVAL_CRASH_SEEDS`` env
# var (comma-separated seed integers). Env vars cross the spawn
# boundary on Windows; module-level globals don't. Lets a parallel
# test simulate "only game K crashes" without needing Manager IPC.
import os as _os
from tests._test_decks import simple_test_deck_pool


def _crash_seeds_from_env() -> set[int]:
    raw = _os.environ.get("MTG_BOT_EVAL_CRASH_SEEDS", "")
    return {int(s) for s in raw.split(",") if s.strip()}


class _SelectiveRaisingStrategy:
    """Raises iff its construction seed is listed in
    ``MTG_BOT_EVAL_CRASH_SEEDS`` — otherwise plays as a
    ``RandomChoice``. Lets us simulate "only game K crashes" in a
    parallel test where the env var crosses the spawn boundary."""

    def __init__(self, seed: int) -> None:
        self._raises = seed in _crash_seeds_from_env()
        self._inner = random.Random(seed)

    def choose(self, state, player_id):  # noqa: ANN001
        if self._raises:
            raise ValueError(
                f"simulated engine corruption (seed={self._inner!r})"
            )
        legal = state.legal_decisions()
        if not legal:
            raise ValueError("no legal decisions")
        return self._inner.choice(legal)

    def choose_with_visits(self, state, player_id):  # noqa: ANN001
        return {}


def _selective_raising_factory(seed: int) -> _SelectiveRaisingStrategy:
    """Top-level pickleable factory paired with
    ``_SelectiveRaisingStrategy``. Set
    ``MTG_BOT_EVAL_CRASH_SEEDS=<seed>,<seed>,...`` BEFORE spawning
    the pool — workers re-import the module and re-read the env var."""
    return _SelectiveRaisingStrategy(seed)


# ---------- worker-level wrappers ------------------------------------------


def test_packed_worker_returns_sentinel_on_crash(capfd):
    """``_play_one_match_game_packed`` catches engine errors and
    returns ``(None, 0)`` rather than re-raising. Traceback is
    routed to stderr so the pool's stderr relay surfaces the cause."""
    args = (
        0,                          # game_idx
        _raising_factory,           # p0_factory — raises mid-game
        random_choice_factory,      # p1_factory
        0,                          # base_seed
        100,                        # decision_cap
        None,                       # per_game_timeout_sec
        simple_test_deck_pool(),    # deck_pool
    )
    result = _play_one_match_game_packed(args)
    assert result == (None, 0, "crashed")
    err = capfd.readouterr().err
    assert "[worker] eval game 0 crashed" in err
    assert "ValueError" in err
    assert "simulated engine corruption" in err


def test_indexed_worker_preserves_game_idx_on_crash(capfd):
    """``_play_one_match_game_indexed`` must still return its
    ``game_idx`` when the inner game crashes, otherwise the
    progress-tracked driver can't re-sort ``imap_unordered``
    results back into deterministic input order."""
    args = (
        7,                          # game_idx — must come back unchanged
        _raising_factory,
        random_choice_factory,
        0,
        100,
        None,                       # per_game_timeout_sec
        simple_test_deck_pool(),    # deck_pool
    )
    game_idx, result = _play_one_match_game_indexed(args)
    assert game_idx == 7
    assert result == (None, 0, "crashed")
    err = capfd.readouterr().err
    assert "[worker] eval game 7 crashed" in err


def test_packed_worker_preserves_partial_decisions_on_timeout(
    monkeypatch, capfd,
):
    """Decisions-zero diagnosis (2026-05-10): when a per-game timeout
    fires, the packed wrapper must return the partial decisions count
    attached to the TimeoutError, not the hardcoded 0 it used to.
    Pre-fix, every timed-out game showed up in the event log as
    ``decisions: 0`` regardless of how far it actually got — making
    it impossible to distinguish "first-decision wedge" from "slow
    but progressing".

    We simulate the inner game completing N decisions by monkey-
    patching the timeout helper to (a) drive a HangProgress for N
    iterations and (b) raise TimeoutError with the decisions count
    attached. The wrapper should surface N in the result tuple.
    """
    from mtg_bot.training import _timeout
    from mtg_bot.training._hang_progress import HangProgress
    from mtg_bot.training import random_choice_factory

    def fake_run_with_timeout(func, args, timeout_sec):
        progress = next(a for a in args if isinstance(a, HangProgress))
        for i in range(173):
            progress.record(active=i % 2, decision=f"D{i}", n_legal=3)
        raise TimeoutError("simulated wedge at decision 173")

    monkeypatch.setattr(
        _timeout, "run_with_timeout", fake_run_with_timeout,
    )

    args = (
        4,                          # game_idx
        random_choice_factory,
        random_choice_factory,
        0,                          # base_seed
        4000,                       # decision_cap
        300.0,                      # per_game_timeout_sec (triggers wrap)
        simple_test_deck_pool(),    # deck_pool
    )
    result = _play_one_match_game_packed(args)
    # Critical assertion: decisions slot carries the partial count,
    # not 0. The diagnosis bench's event log would now show
    # ``decisions: 173`` instead of ``decisions: 0``.
    assert result == (None, 173, "timed_out")

    err = capfd.readouterr().err
    assert "[worker] eval game 4 timed out" in err
    assert "decisions=173" in err


def test_packed_worker_partial_decisions_zero_when_attr_missing(
    monkeypatch,
):
    """Defensive: if a TimeoutError gets raised by a code path that
    didn't have time to attach ``decisions_completed`` (shutdown
    race, OR a TimeoutError raised from somewhere other than
    ``_play_one_match_game``'s catch block), the wrapper must fall
    back to 0 rather than blowing up with AttributeError. This is the
    backward-compat seatbelt that lets the new attribute be optional."""
    from mtg_bot.training import _timeout
    from mtg_bot.training import random_choice_factory

    def fake_run_with_timeout(func, args, timeout_sec):
        # Raise without attaching the attribute — simulates the
        # pre-instrumentation behavior path.
        raise TimeoutError("bare timeout, no attribute attached")

    monkeypatch.setattr(
        _timeout, "run_with_timeout", fake_run_with_timeout,
    )

    args = (
        0, random_choice_factory, random_choice_factory,
        0, 4000, 300.0, simple_test_deck_pool(),
    )
    result = _play_one_match_game_packed(args)
    assert result == (None, 0, "timed_out")


# ---------- run_match_parallel: pool.map (no-progress) path ----------------


def test_run_match_parallel_no_progress_survives_crashes(capfd):
    """A factory that raises every game produces a MatchStats whose
    ``crashed == n_games`` (all dropped) and ``games == 0`` (nothing
    contributed signal). The pool itself completes normally — this
    is the contract the eval CLI relies on so a 1/1000 corruption
    bug can't tank a 100-game match."""
    n_games = 4
    stats = run_match_parallel(
        p0_factory=_raising_factory,
        p1_factory=random_choice_factory,
        n_games=n_games,
        base_seed=0,
        n_workers=2, deck_pool=simple_test_deck_pool(),
    )
    # Every game crashed → all dropped from the dataset; nothing
    # contributed signal. Wins / draws / games are all zero;
    # ``crashed`` carries the loss-of-signal count.
    assert stats.crashed == n_games
    assert stats.games == 0
    assert stats.wins == {0: 0, 1: 0}
    assert stats.draws == 0
    assert stats.avg_decisions == 0.0

    err = capfd.readouterr().err
    assert "# WARNING:" in err
    assert f"{n_games}/{n_games} games crashed" in err


def test_run_match_parallel_no_progress_partial_crash(
    monkeypatch, capfd: Any,
):
    """Mixed scenario — only one game's strategy raises; the rest
    play to completion. The crashed game is DROPPED from
    ``games`` / ``wins`` / ``draws`` and recorded under
    ``crashed``; the remaining 4 games contribute the win-rate
    signal. This is the production scenario: 99/100 games
    complete normally and 1 dies in the engine; the dropped one
    shouldn't pollute the win rate's denominator."""
    n_games = 5
    base_seed = 13
    # ``_play_one_match_game`` builds p0's strategy with seed
    # ``base_seed + 100*game_idx`` — make game 2's p0 strategy raise.
    target_seed = base_seed + 100 * 2
    monkeypatch.setenv("MTG_BOT_EVAL_CRASH_SEEDS", str(target_seed))

    stats = run_match_parallel(
        p0_factory=_selective_raising_factory,
        p1_factory=random_choice_factory,
        n_games=n_games,
        base_seed=base_seed,
        n_workers=2, deck_pool=simple_test_deck_pool(),
    )

    # Exactly 1 game crashed; the remaining 4 contributed signal.
    assert stats.crashed == 1
    assert stats.games == n_games - 1  # 4 completed
    # New invariant: wins + draws == games (excludes crashed).
    assert stats.wins[0] + stats.wins[1] + stats.draws == stats.games
    # No organic decision-cap timeouts at default cap with random
    # play, so all 4 completed games are decisive.
    assert stats.draws == 0
    # The non-crashed games contributed real decisions, so the
    # average must be strictly positive.
    assert stats.avg_decisions > 0

    err = capfd.readouterr().err
    assert "# WARNING:" in err
    assert "1/5 games crashed" in err


# ---------- run_match_parallel: imap_unordered (progress) path -------------


def test_run_match_parallel_with_progress_survives_crashes(
    tmp_path: Path, capfd: Any,
):
    """The progress-tracked path also has to swallow worker crashes.
    Verifies the progress JSON finalizes at status='completed' (not
    'failed') and the crashed games are recorded — same as a no-
    progress run, just with the extra UI-facing snapshot."""
    n_games = 3
    progress = EvalProgress(
        progress_path=tmp_path / "eval.json",
        run_id="eval",
        n_games_total=n_games,
        n_workers=2,
        opponent_label="random",
        flush_interval_s=0.0,
    )
    stats = run_match_parallel(
        p0_factory=_raising_factory,
        p1_factory=random_choice_factory,
        n_games=n_games,
        base_seed=0,
        n_workers=2,
        progress=progress, deck_pool=simple_test_deck_pool(),
    )

    # All games crashed → all dropped from MatchStats; ``crashed``
    # carries the count.
    assert stats.crashed == n_games
    assert stats.games == 0
    assert stats.draws == 0
    assert stats.wins == {0: 0, 1: 0}

    err = capfd.readouterr().err
    assert "# WARNING:" in err
    assert f"{n_games}/{n_games} games crashed" in err

    import json
    payload = json.loads((tmp_path / "eval.json").read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["n_games_done"] == n_games
    assert payload["ended_at"] is not None
    # MatchStats and EvalProgress now align on the same convention:
    # crashed games are excluded from wins / draws / games (they
    # carry no signal) and surface only via the ``crashed`` field.
    assert payload["crashed"] == n_games
    assert payload["draws"] == 0
    assert payload["wins_new"] == 0
    assert payload["wins_old"] == 0
    # win_rate sentinel is 0.0 when there are no decided games.
    assert payload["win_rate"] == 0.0
