# `tests_rust/` — TDD harness for the Rust engine port

Purpose: drive the Rust engine port (`mtg_bot_engine` PyO3 extension)
test-first. Every Rust feature lands as a red→green→commit cycle:

1. Pick a behavior currently exercised by some test in `tests/` (or a
   small primitive needed for one).
2. Port the test into `tests_rust/`, target the Rust API instead of
   `mtg_bot.*` Python API. Watch it fail (RED).
3. Implement the underlying Rust functionality in `rust/src/state.rs`
   (or wherever it belongs). Re-run. Watch it pass (GREEN).
4. Commit on a feature branch. Move to the next test.

This directory is skipped wholesale if `mtg_bot_engine` isn't built
(see `conftest.py`). Run `maturin develop --release -m rust/Cargo.toml`
once and these tests run as part of the default `pytest` invocation.

## Layout

`tests_rust/` mirrors `tests/`. When porting a test from
`tests/test_clone.py`, the new file goes at `tests_rust/test_clone.py`
with the same test names where reasonable. Side-by-side filenames
make `git diff tests/test_X.py tests_rust/test_X.py` a useful
parity check.

## Conventions

- **Use the `engine` / `synthetic_state` / `empty_registry` fixtures**
  from `conftest.py` rather than re-importing in every test.
- **Don't re-test what `tests/test_rust_card_bridge.py` and
  `tests/test_rust_engine_smoke.py` already cover.** Those live in
  `tests/` because they predate the TDD harness; new feature tests
  go in `tests_rust/`.
- **One behavior per test.** TDD discipline — small enough that a
  failing test points at exactly one missing piece of Rust.
- **Document the port in the file's module docstring.** Reference
  the Python test it's based on (e.g. "Ported from `tests/test_clone.py`,
  shrunk to the engine-level subset").

## Out of scope

The Python test suite has 391 files (~7860 tests). Many are not
relevant to the Rust engine port and won't be ported:

- **NN / training / data-gen** (`tests/training/*`, `tests/test_nn_*`,
  most of `tests/search/*`) — Rust crate explicitly excludes these.
- **UI / Flask / vitest** (`tests/training_ui/*`, `tests/test_app*`,
  `tests-js/*`) — pure web layer.
- **CLI / runs DB / orchestration** (`tests/cli/*`,
  `tests/test_*_orchestration*`) — operator-facing, runs in Python.
- **Distributed / SSH / shard plumbing** — same.

The ports target engine-only files: `tests/test_clone.py`,
`tests/test_combat.py`, `tests/test_actions.py`, `tests/test_legal.py`,
`tests/test_counters.py`, the per-card behavior tests
(`tests/test_<card_name>.py`), etc. A precise inventory is built
incrementally as ports happen — don't try to predict the whole
boundary up front.

## Porting status

Tracked in this README so a glance at the file shows where the
port is. Append a row when you start a port; flip to `green` when
the test lands in a commit.

| ported test                       | source                  | status | branch / commit            |
|-----------------------------------|-------------------------|--------|----------------------------|
| tests_rust/test_tap.py            | tests/test_combat.py + game.py  | green  | feature/rust-tdd-tap       |
| tests_rust/test_zones.py          | tests/test_actions.py + game.py | green  | feature/rust-tdd-zones     |
| tests_rust/test_life.py           | tests/test_combat.py + game.py  | green  | feature/rust-tdd-life      |
| tests_rust/test_mana.py           | tests/test_mana.py + game.py                | green  | feature/rust-tdd-mana      |
| tests_rust/test_counters.py       | tests/test_counters.py + game.py            | green  | feature/rust-tdd-counters  |
| tests_rust/test_steps.py          | tests/test_beginning_of_upkeep.py + turn.py | green  | feature/rust-tdd-steps     |
| rust(bridge-ext): P/T + mana_produced | tests/test_rust_card_bridge.py + tests/test_rust_bridge_parity.py | green  | feature/rust-bridge-pt-mana |
| tests_rust/test_damage.py         | tests/test_combat.py + game.py              | green  | feature/rust-tdd-damage    |
| tests_rust/test_winloss.py        | tests/test_game.py + game.py                | green  | feature/rust-tdd-winloss   |
| tests_rust/test_cast.py           | tests/test_actions.py + game.py             | green  | feature/rust-tdd-cast      |
| tests_rust/test_library.py        | tests/test_actions.py + game.py             | green  | feature/rust-tdd-library   |
| tests_rust/test_priority.py       | tests/test_game.py + turn.py                | green  | feature/rust-tdd-priority  |
| tests_rust/test_combat.py         | tests/test_combat.py + combat.py            | green  | feature/rust-tdd-combat    |
| tests_rust/test_stack.py          | tests/test_game.py + game.py                | green  | feature/rust-tdd-stack     |
| tests_rust/test_sba.py            | tests/test_state_based_actions.py + game.py | green  | feature/rust-tdd-sba       |
| rust(cast-rewire): card_types-based detector | tests_rust/test_cast.py rewire              | green  | feature/rust-tdd-cast-rewire |
| tests_rust/test_cleanup.py        | tests/test_actions.py + turn.py             | green  | feature/rust-tdd-cleanup   |
| tests_rust/test_resolve.py        | tests/test_combat.py + game.py              | green  | feature/rust-tdd-resolve   |
| rust(combat-vigilance): keyword skip-tap | tests_rust/test_combat.py extend             | green  | feature/rust-tdd-vigilance |
| tests_rust/test_counterspell.py   | tests/test_counter_cancellation.py + game.py | green  | feature/rust-tdd-counterspell |
| rust(resolve-postmove): card_types-driven destination | tests_rust/test_resolve.py extend            | green  | feature/rust-tdd-postresolve |
| rust(combat-keywords): deathtouch+lifelink | tests_rust/test_combat.py extend            | green  | feature/rust-tdd-deathtouch-lifelink |
| rust(resolve-effects): DrawCards+GainLife dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-resolve-effects |
| rust(cleanup-compose): hand-size+damage-clear | tests_rust/test_cleanup.py extend           | green  | feature/rust-tdd-cleanup-compose |
| rust(combat-keywords): trample+first-strike | tests_rust/test_combat.py extend            | green  | feature/rust-tdd-trample-firststrike |
| rust(etb-triggers): on-resolve dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-etb |
| rust(priority-round-complete): pop+priority-reset | tests_rust/test_priority.py extend          | green  | feature/rust-tdd-priority-pass-resolve |
| rust(combat-keyword): haste | tests_rust/test_combat.py extend           | green  | feature/rust-tdd-haste |
| rust(resolve-effects-r10): ReturnToHand+Mill dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-resolve-bounce-mill |
| tests_rust/test_deck.py           | tests/_test_decks.py + game.py              | green  | feature/rust-tdd-deck |
| rust(combat-keywords): flying+reach | tests_rust/test_combat.py extend           | green  | feature/rust-tdd-flying-reach |
| rust(resolve-effects-r11): ExileTarget dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-exile |
| tests_rust/test_mulligan.py       | tests/test_actions.py + game.py             | green  | feature/rust-tdd-mulligan |
| rust(combat-keywords): menace+defender | tests_rust/test_combat.py extend           | green  | feature/rust-tdd-menace-defender |
| rust(resolve-effects-r12): TapTarget dispatch | tests_rust/test_resolve.py extend           | green  | feature/rust-tdd-tap-target |
| rust(sba-zero-toughness): CR 704.5f | tests_rust/test_sba.py extend           | green  | feature/rust-tdd-sba-zero-toughness |
| rust(resolve-effects-r13): UntapTarget dispatch | tests_rust/test_resolve.py extend | green | feature/rust-tdd-untap-target |

## Build invocation reminder

```
VIRTUAL_ENV="C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313" \
  "C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313/Scripts/maturin.exe" \
  develop --release -m rust/Cargo.toml
```

Run only the Rust harness:
```
PYTHONPATH=src "C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313/Scripts/python.exe" \
  -m pytest tests_rust/ -v --no-cov
```

Full gate (must stay green before commit):
```
PYTHONPATH=src "C:/Users/Gregg Keithley/Documents/Claude/Projects/mtg-bot/.venv-py313/Scripts/python.exe" \
  -m pytest -n 8 --no-cov
```
