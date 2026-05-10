// JS-side mirror of the Python single-source-of-truth gate constant
// at ``src/mtg_bot/training/gate.py``.
//
// Why a mirror exists: Python and JS can't share a literal across the
// language boundary, and these unit tests load the inline UI script
// directly from the Jinja template — they don't go through the Flask
// renderer, so they don't see the value Jinja would inject. The mirror
// lets the tests pin assertions to the gate value and document what
// they're testing.
//
// Keep this in sync with ``EVAL_GATE_THRESHOLD`` in
// ``src/mtg_bot/training/gate.py``. The Python tests under
// ``tests/training_ui/`` cover the live render path (Jinja injecting
// the Python value) — this file just lets the JS tests exercise the
// UI logic at the same gate value the user will see.
export const EVAL_GATE_THRESHOLD = 0.51;
