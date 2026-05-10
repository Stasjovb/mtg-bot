"""Single source of truth for the eval-gate acceptance threshold.

The eval gate compares a freshly-trained network's win-rate (vs the
current best, in head-to-head play) against ``EVAL_GATE_THRESHOLD``.
At-or-above promotes; below keeps the current best. The constant is
imported by every consumer so updating this file updates the gate
everywhere — that is the point of this module.

Consumers:

- ``mtg_bot.cli.iterate`` uses it as the default for
  ``--acceptance-threshold``.
- ``scripts/eval_early_stop_watcher.py`` uses it as the default for
  ``--threshold``.
- ``mtg_bot.training_ui.app`` injects it into the index template so
  the UI's gate-band overlay tracks the constant. The JS-side
  ``EVAL_GATE_THRESHOLD`` is rendered from this value via Jinja.

The Python <-> JS sync seam: the JS unit-test fixtures under
``tests-js/fixtures/gate.js`` mirror this constant. Python and JS
can't share a literal across the language boundary; the cross-
language sync is the cost of having an HTML+JS UI fed by a Python
backend. Keep ``tests-js/fixtures/gate.js`` aligned when changing
the value here.

Why 0.51 (and not 0.52 or 0.55):

AlphaGo Zero-style gating — promote on any statistically significant
improvement. The early-stop watcher's Wilson 95% CI lower bound is
what gates promotion in practice (paired with the 2000-game eval
default), so the literal threshold mostly sets where "significant"
starts. 0.51 is close enough to 50/50 that any real improvement
clears it; the watcher's CI does the heavy lifting on noise.
"""

EVAL_GATE_THRESHOLD = 0.51
"""Win-rate threshold the new NN must beat (vs current best) to be
promoted. Single source of truth — see this module's docstring."""
