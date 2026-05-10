"""Tests for the eval-gate single source of truth.

The gate threshold lives at ``mtg_bot.training.gate.EVAL_GATE_THRESHOLD``
and every consumer (iterate's ``--acceptance-threshold`` default, the
early-stop watcher's ``--threshold`` default, the training UI's gate
overlay) reads it. These tests pin each consumer to the constant so a
future regression that hardcodes a literal in one of those places
fails loudly here, well before it confuses a live training run.
"""

from __future__ import annotations

import argparse
import importlib
import io
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from mtg_bot.training.gate import EVAL_GATE_THRESHOLD


def test_threshold_is_a_proportion_in_open_unit_interval():
    """A threshold below 0 or above 1 makes no statistical sense.
    Pin the open interval so a zero or one slip doesn't silently
    promote-everything / promote-nothing."""
    assert 0.0 < EVAL_GATE_THRESHOLD < 1.0


def test_iterate_acceptance_threshold_default_tracks_constant():
    """``mtg_bot iterate``'s ``--acceptance-threshold`` default must
    read the SoT — never hardcode a literal at the parser site."""
    iterate = importlib.import_module("mtg_bot.cli.iterate")
    parser = _spy_parser(lambda: iterate.main(["--help"]))
    ns = parser.parse_args([
        "--bootstrap-version", "v4",
        "--deck-pool", "data/17lands/eoe_decks.json.gz",
    ])
    assert ns.acceptance_threshold == pytest.approx(EVAL_GATE_THRESHOLD)


def test_watcher_threshold_default_tracks_constant():
    """``scripts/eval_early_stop_watcher.py``'s ``--threshold``
    default must read the SoT."""
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "eval_early_stop_watcher" in sys.modules:
        del sys.modules["eval_early_stop_watcher"]
    watcher = importlib.import_module("eval_early_stop_watcher")
    parser = _spy_parser(lambda: watcher.main(["--help"]))
    ns = parser.parse_args([])
    assert ns.threshold == pytest.approx(EVAL_GATE_THRESHOLD)


def test_training_ui_index_renders_threshold_into_template_context():
    """The Flask index route must inject ``eval_gate_threshold`` into
    the rendered HTML so the inline JS picks it up."""
    from mtg_bot.training_ui.app import create_app
    with tempfile.TemporaryDirectory() as tmp:
        progress_dir = Path(tmp) / "training_progress"
        progress_dir.mkdir()
        app = create_app(progress_dir)
        app.config["TESTING"] = True
        client = app.test_client()
        res = client.get("/")
        assert res.status_code == 200
        body = res.get_data(as_text=True)
        # The inline JS line ``const EVAL_GATE_THRESHOLD = X.XX;``
        # must carry the SoT value, not a hardcoded literal.
        expected = f"const EVAL_GATE_THRESHOLD = {EVAL_GATE_THRESHOLD};"
        assert expected in body, (
            f"expected {expected!r} in rendered index, got body of "
            f"length {len(body)}"
        )
        # The user-visible gate label must also reflect the SoT.
        expected_label_pct = int(EVAL_GATE_THRESHOLD * 100)
        assert f"gate {expected_label_pct}%" in body


# ---- helpers -------------------------------------------------------------


def _spy_parser(invoke):
    """Run ``invoke()`` (which builds and uses an argparse parser) and
    return the first ``ArgumentParser`` instance it constructed.

    Used to grab a parser whose builder is buried in a ``main()`` body
    that's marked ``pragma: no cover`` — invoking the function with
    ``--help`` fires the parser's exit but only after construction is
    complete, so the spy on ``__init__`` captures it before SystemExit
    unwinds.
    """
    captured: dict[str, argparse.ArgumentParser] = {}
    real_init = argparse.ArgumentParser.__init__

    def spy_init(self, *a, **kw):
        real_init(self, *a, **kw)
        captured.setdefault("parser", self)

    argparse.ArgumentParser.__init__ = spy_init
    try:
        # ``--help`` writes the usage banner to stdout/stderr; the
        # parser is what we care about, not the banner. Swallow both
        # streams so test output stays clean.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                invoke()
            except SystemExit:
                pass
    finally:
        argparse.ArgumentParser.__init__ = real_init
    assert "parser" in captured, "expected invoke() to construct a parser"
    return captured["parser"]
