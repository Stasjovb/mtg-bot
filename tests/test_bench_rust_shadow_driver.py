"""Focused test for the C4 re-sweep ``--driver rust_shadow`` bench
path (SOT_FLIP_CUTOVER_PLAN Step-0 evidence harness).

Covers:
* ``rust_shadow.drive_shadow_game_to_terminal`` runs the EXACT test
  idiom (seeded ``random.Random`` over ``legal_decisions()`` applied
  via ``apply`` until terminal) and returns a ``ShadowGameOutcome``
  with a valid bench status;
* the tiny synthetic deck (the smoke deck) runs divergence-CLEAN to
  the natural terminal through the role-swapped bake-in (the same
  property ``test_rust_shadow_bakein`` asserts, here through the
  scaled-driver entry point — proving the driver IS the same gate);
* a ``ShadowDivergenceError`` is the honest FAIL_DIVERGENCE signal
  (negative control — the driver records the tripwire, NEVER silently
  falls back: feedback_no_fallback_hybrids);
* the bench ``drive_one_game_rust_shadow`` wrapper produces a
  ``GameResult`` foldable into the existing aggregate/render machinery
  and the ``--driver`` flag is wired (default ``step_both``,
  byte-unchanged);
* ``--driver step_both`` remains the default and the existing
  ``drive_one_game`` is untouched (the new driver is opt-in).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


def _bench():
    """Import the scripts/ bench module (same idiom as
    tests/test_trajectory.py's R74-3 repro)."""
    _repo = pathlib.Path(__file__).resolve().parent.parent
    _scripts = _repo / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import bench_trajectory_parity as bench  # noqa: E402

    return bench


# ---------------------------------------------------------------------------
# drive_shadow_game_to_terminal — the headless full-game driver
# ---------------------------------------------------------------------------


def test_shadow_driver_runs_tiny_deck_clean_to_terminal():
    """The tiny synthetic deck (the smoke deck) must run
    divergence-CLEAN to the natural terminal through the scaled
    rust_shadow driver — the SAME property the in-test bake-in pins
    assert, here through the scaled-sweep entry point. This proves the
    C4 driver IS the same role-swapped gate, just driven headlessly."""
    from mtg_bot.parity.cross_engine import tiny_synthetic_deckspec
    from mtg_bot.search.rust_shadow import drive_shadow_game_to_terminal

    outcome = drive_shadow_game_to_terminal(
        tiny_synthetic_deckspec(), seed=2026, max_steps=4000,
    )
    assert outcome.status == "PASS", (
        f"the tiny synthetic deck must run divergence-clean to "
        f"terminal through the rust_shadow scaled driver (the "
        f"G4/G5/G6-closed bake-in property); got "
        f"{outcome.status} at step {outcome.steps} "
        f"(kind={outcome.divergence_kind} "
        f"detail={outcome.divergence_detail})"
    )
    assert outcome.terminal is True
    assert outcome.steps > 0
    assert outcome.divergence_kind is None


def test_shadow_driver_is_per_seed_deterministic():
    """Two runs of the same (spec, seed) must take the identical
    decision path → identical outcome (per-seed determinism, the
    STATE_EQ fingerprint-stability sibling property)."""
    from mtg_bot.parity.cross_engine import tiny_synthetic_deckspec
    from mtg_bot.search.rust_shadow import drive_shadow_game_to_terminal

    a = drive_shadow_game_to_terminal(
        tiny_synthetic_deckspec(), seed=7, max_steps=4000,
    )
    b = drive_shadow_game_to_terminal(
        tiny_synthetic_deckspec(), seed=7, max_steps=4000,
    )
    assert a == b


def test_shadow_driver_records_divergence_not_silent_fallback():
    """Negative control: a ShadowDivergenceError must surface as a
    FAIL_DIVERGENCE outcome carrying the tripwire name + detail — the
    driver NEVER silently falls back to step_both or skips
    (feedback_no_fallback_hybrids / feedback_silent_noop_pipelines)."""
    from mtg_bot.parity.cross_engine import tiny_synthetic_deckspec
    from mtg_bot.search import rust_shadow as rs

    real_build = rs.build_shadow_checked_adapter

    class _PoisonedApply:
        """Wrap a real adapter; make the FIRST apply raise a
        ShadowDivergenceError (the genuine bake-in fail signal)."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def apply(self, decision):
            raise rs.ShadowDivergenceError(
                "STATE_EQ", "injected divergence (negative control)"
            )

    def _poisoned_build(spec):
        return _PoisonedApply(real_build(spec))

    rs.build_shadow_checked_adapter = _poisoned_build
    try:
        outcome = rs.drive_shadow_game_to_terminal(
            tiny_synthetic_deckspec(), seed=1, max_steps=50,
        )
    finally:
        rs.build_shadow_checked_adapter = real_build

    assert outcome.status == "FAIL_DIVERGENCE"
    assert outcome.divergence_kind == "STATE_EQ"
    assert "injected divergence" in (outcome.divergence_detail or "")


# ---------------------------------------------------------------------------
# bench wrapper + CLI wiring
# ---------------------------------------------------------------------------


def test_bench_driver_flag_defaults_to_step_both():
    """The --driver flag must default to step_both so every existing
    invocation is byte-for-byte unchanged (the new driver is opt-in)."""
    bench = _bench()
    args = bench.build_parser().parse_args([])
    assert args.driver == "step_both"
    args2 = bench.build_parser().parse_args(["--driver", "rust_shadow"])
    assert args2.driver == "rust_shadow"
    assert args2.shadow_max_steps == 4000


def test_bench_drive_one_game_rust_shadow_returns_gameresult():
    """drive_one_game_rust_shadow must return a GameResult foldable
    into the existing aggregate()/render_summary() machinery — a real
    production-deck game driven through the bake-in. Status is one of
    the bench status strings; the result aggregates without error."""
    bench = _bench()
    from mtg_bot.parity import trajectory

    try:
        trajectory.load_production_deck(archetype=0)
    except (FileNotFoundError, IndexError):
        pytest.skip("17lands deck pool unavailable")

    r = bench.drive_one_game_rust_shadow(
        archetype=0, seed=0, max_steps=4000,
    )
    assert r.status in {
        "PASS", "FAIL_DIVERGENCE", "FAIL_TIMEOUT",
        "ARCHETYPE_FILTERED", "FAIL_EXCEPTION",
    }
    # The result must aggregate + render without error (report-shape
    # consistency with the round-76 step_both sweep).
    summary = bench.aggregate([r])
    assert summary.total_games == 1
    text = bench.render_summary(summary)
    assert "trajectory-parity bench summary" in text
    # If it diverged, the tripwire name is the divergence kind and the
    # shape histogram bucketed it (the honest C4 signal, not silent).
    if r.status == "FAIL_DIVERGENCE":
        assert r.divergence_kind in {
            "LEGAL_SET_EQ", "CHOSEN_EQ", "STATE_EQ", "NO_RAISE",
        }
        assert summary.fail_divergence == 1
        assert summary.divergence_shape_histogram


def test_bench_step_both_driver_untouched():
    """The step_both driver (drive_one_game) must still exist with its
    original signature — the new driver is purely additive."""
    bench = _bench()
    import inspect

    sig = inspect.signature(bench.drive_one_game)
    # The original step_both driver parameters are unchanged.
    for p in ("archetype", "seed", "max_turns", "combat_strategy",
              "mulligans", "require_creatures"):
        assert p in sig.parameters
