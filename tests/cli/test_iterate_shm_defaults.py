"""Tests for the platform-conditional defaults on ``mtg_bot iterate``'s
``--use-shm-self-play`` and ``--use-shm-eval`` flags.

The SharedTensorNNEvalServer (PR #40, deadlock fix in PR #43) is the
fast path for both self-play and eval NN traffic. The substrate works
on Linux fork + Windows spawn (verified 2026-05-12 via scripts/
scout_shm_pool.py + the SHM server test suite running on Windows);
macOS isn't wired into MPS routing yet. So the defaults flip per
platform:

* Linux → both flags default ON (use the SHM server).
* Windows → both flags default ON (substrate runs over spawn).
* Mac → both flags default OFF (fall back to the legacy per-worker
  NNEvaluator path so MPS workers keep their existing fast path).

Argparse's ``BooleanOptionalAction`` gives us ``--no-use-shm-self-play``
/ ``--no-use-shm-eval`` for free, so a user who hits a regression can
opt out without a code change. These tests pin both halves of that
contract: the platform-conditional default, and the ability to flip
each flag independently with its ``--no-*`` counterpart.
"""

from __future__ import annotations

import argparse
import importlib
import io
import sys
from contextlib import redirect_stderr, redirect_stdout


def _spy_parser(invoke):
    """Run ``invoke()`` (which builds and uses an argparse parser) and
    return the first ``ArgumentParser`` instance it constructed.

    Mirrors the helper in ``tests/training/test_gate.py``; duplicated
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


def test_use_shm_self_play_default_is_platform_conditional():
    """No flag passed → default tracks ``sys.platform in ('linux',
    'win32')``."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        "--bootstrap-version", "v4",
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
    ])
    assert ns.use_shm_self_play is (sys.platform in ("linux", "win32"))


def test_use_shm_eval_default_is_platform_conditional():
    """Same contract for the eval-side flag."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        "--bootstrap-version", "v4",
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
    ])
    assert ns.use_shm_eval is (sys.platform in ("linux", "win32"))


def test_no_use_shm_self_play_forces_off():
    """``--no-use-shm-self-play`` must opt out even on Linux/Windows."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        "--bootstrap-version", "v4",
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
        "--no-use-shm-self-play",
    ])
    assert ns.use_shm_self_play is False


def test_no_use_shm_eval_forces_off():
    """``--no-use-shm-eval`` must opt out even on Linux/Windows."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        "--bootstrap-version", "v4",
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
        "--no-use-shm-eval",
    ])
    assert ns.use_shm_eval is False


def test_use_shm_self_play_explicit_on_works_everywhere():
    """The positive form still works (no-op on Linux/Windows, opt-in
    on Mac — though the shard runner will silently no-op there since
    the SHM activation is platform-gated downstream)."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        "--bootstrap-version", "v4",
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
        "--use-shm-self-play",
    ])
    assert ns.use_shm_self_play is True


def test_split_flags_are_independent():
    """``--no-use-shm-eval`` must not affect ``use_shm_self_play``."""
    parser = _iterate_parser()
    ns = parser.parse_args([
        "--bootstrap-version", "v4",
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
        "--no-use-shm-eval",
    ])
    assert ns.use_shm_self_play is (sys.platform in ("linux", "win32"))
    assert ns.use_shm_eval is False
