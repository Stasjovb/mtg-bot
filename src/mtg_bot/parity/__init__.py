"""Parity tooling: cross-engine state-comparison helpers.

This package hosts utilities that drive Python AND Rust engine states
side-by-side and report divergences. The Rust port is purpose-built to
be a drop-in replacement for the Python engine in the search loop; this
package is the closing-the-loop apparatus that *measures* parity rather
than promising it.

Public surface today (round-27 r5 cross-engine smoke slice):

- :mod:`mtg_bot.parity.cross_engine` — build matched Python+Rust states
  from a tiny synthetic registry, drive them through N decisions, and
  report the first divergence with field-level granularity.

The shape mirrors the round-25 ``scripts/parity_smoke.py`` modes
(initial-state / trajectory / multi-seed / field-diff). The CLI
surface in ``parity_smoke.py`` is a thin wrapper around the helpers
here so the smoke-test-the-smoke pattern works (inject a fake
divergence, verify the harness flags it correctly).
"""
