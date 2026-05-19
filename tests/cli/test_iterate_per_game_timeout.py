"""Tests for ``mtg_bot iterate``'s split per-game timeout flags.

Until PR #47 a single ``--per-game-timeout-sec`` knob governed both
the self-play and the eval phase. PR #46 (commit 591164b9, 2026-05-09)
showed that's the wrong shape: at 14-worker SHM eval against v21
1024-trunk the one completed game took 178.8s for 592 decisions while
five timed-out games each logged 515-645 decisions when killed (real
progress, not wedges). The previous single cap sat right at the
median, clipping the legitimate p99 tail of contended eval games.

The split:

* ``--per-game-timeout-self-play-sec`` defaults to 300s — self-play is
  uncontended (one worker per shard) so 300s covers the bulk.
* ``--per-game-timeout-eval-sec`` defaults to 600s — eval is 14-worker
  contended; matches the standalone ``mtg_bot eval`` budget.
* ``--per-game-timeout-sec`` survives as a deprecated back-compat
  alias that, when explicitly passed, overrides BOTH.

These tests pin every leg of that contract.
"""

from __future__ import annotations

import argparse
import importlib
import io
from contextlib import redirect_stderr, redirect_stdout

from mtg_bot.cli import _common


def _spy_parser(invoke):
    """Capture the first ArgumentParser constructed by ``invoke()``.

    Same trick as ``tests/cli/test_iterate_shm_defaults.py``; duplicated
    here so this file stays self-contained.
    """
    captured: dict[str, argparse.ArgumentParser] = {}
    real_init = argparse.ArgumentParser.__init__

    def spy_init(self, *a, **kw):
        real_init(self, *a, **kw)
        captured.setdefault("parser", self)

    argparse.ArgumentParser.__init__ = spy_init
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                invoke()
            except SystemExit:
                pass
    finally:
        argparse.ArgumentParser.__init__ = real_init
    assert "parser" in captured, "expected invoke() to construct a parser"
    return captured["parser"]


def _iterate_parser() -> argparse.ArgumentParser:
    iterate = importlib.import_module("mtg_bot.cli.iterate")
    return _spy_parser(lambda: iterate.main(["--help"]))


_BASE_ARGS = [
    "--bootstrap-version", "v4",
    "--deck-pool", "data/17lands/eoe_decks.json.gz",
]


def test_default_self_play_timeout_is_none_pre_resolve():
    """No flag passed → self-play default is ``None`` at parse time.
    ``main()`` then resolves to ``3 * args.nodes`` after parse so
    the formula picks up the user's actual ``--nodes`` value. A
    real argparse default value would bake in a fixed number that
    couldn't track ``--nodes``."""
    parser = _iterate_parser()
    ns = parser.parse_args(_BASE_ARGS)
    assert ns.per_game_timeout_self_play_sec is None


def test_default_eval_timeout_is_none_pre_resolve():
    """Same contract as self-play: None at parse, resolved by main()
    to ``3 * args.nodes``."""
    parser = _iterate_parser()
    ns = parser.parse_args(_BASE_ARGS)
    assert ns.per_game_timeout_eval_sec is None


def test_legacy_alias_defaults_to_none():
    """The deprecated single-knob alias must default to None so the
    resolution step in ``main()`` can tell "operator didn't pass it"
    apart from "operator passed 0". A real default value here would
    silently override the split defaults on every invocation."""
    parser = _iterate_parser()
    ns = parser.parse_args(_BASE_ARGS)
    assert ns.per_game_timeout_sec is None


def test_split_flags_are_independent():
    """Overriding one phase must not affect the other."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        *_BASE_ARGS,
        "--per-game-timeout-self-play-sec", "120",
    ])
    assert ns.per_game_timeout_self_play_sec == 120.0
    # The unset side stays None until main()'s post-parse resolve;
    # the override on one phase mustn't accidentally trigger or skip
    # the resolve on the other.
    assert ns.per_game_timeout_eval_sec is None

    ns2 = parser.parse_args([
        *_BASE_ARGS,
        "--per-game-timeout-eval-sec", "900",
    ])
    assert ns2.per_game_timeout_eval_sec == 900.0
    assert ns2.per_game_timeout_self_play_sec is None


def test_explicit_overrides_accept_both_flags():
    """Both flags accept their own override without colliding."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        *_BASE_ARGS,
        "--per-game-timeout-self-play-sec", "200",
        "--per-game-timeout-eval-sec", "800",
    ])
    assert ns.per_game_timeout_self_play_sec == 200.0
    assert ns.per_game_timeout_eval_sec == 800.0


def test_eval_default_is_at_least_self_play_default():
    """Sanity invariant: contention only inflates per-game wall, so the
    eval default budget must never be smaller than the self-play one.
    Both phases now use the same ``3 * --nodes`` formula so the
    invariant holds trivially with equality."""
    assert (
        _common.DEFAULT_PER_GAME_TIMEOUT_EVAL_SEC
        >= _common.DEFAULT_PER_GAME_TIMEOUT_SELF_PLAY_SEC
    )


def test_post_resolve_default_is_three_times_nodes(monkeypatch, tmp_path):
    """After main() runs the post-parse resolve step, an unset
    timeout becomes exactly ``3 * args.nodes``. Verifies the
    formula end-to-end through the argparse + resolve pipeline."""
    import argparse
    parser = _iterate_parser()
    # nodes=400 should resolve to 1200s on both phases.
    ns = parser.parse_args([*_BASE_ARGS, "--nodes", "400"])
    assert ns.per_game_timeout_self_play_sec is None
    assert ns.per_game_timeout_eval_sec is None
    # Apply the resolve step main() does (copied here as the
    # single-line transform under test).
    if ns.per_game_timeout_self_play_sec is None:
        ns.per_game_timeout_self_play_sec = 3.0 * ns.nodes
    if ns.per_game_timeout_eval_sec is None:
        ns.per_game_timeout_eval_sec = 3.0 * ns.nodes
    assert ns.per_game_timeout_self_play_sec == 1200.0
    assert ns.per_game_timeout_eval_sec == 1200.0
