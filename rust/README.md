# `mtg_bot_engine` — Rust hot-path crate

Skeleton for the Rust rewrite of the engine + search hot path. Built
as a PyO3 extension and imported from Python as `import mtg_bot_engine`.

## Scope

**This crate owns:**

- `GameState`, `GameObject`, `Player` data shapes
- Clone (today)
- Future: legal-action enumeration, step / resolve / combat, MCTS

**Python keeps:**

- The oracle-text card parser (`src/mtg_bot/cards/parser/`)
- Effect / trigger / static grammar definitions
- The NN evaluator + AlphaZero training pipeline
- The Flask UI and distributed self-play orchestration
- The closed-vocabulary effect enum surfaces to Rust through the
  card-data bridge (TBD next branch)

## Build

From the worktree root, into the project's `.venv-py313`:

```bash
../../mtg-bot/.venv-py313/Scripts/maturin.exe develop \
    --release -m rust/pyproject.toml
```

That compiles and installs `mtg_bot_engine.pyd` into the venv's
`site-packages`. After that any Python in the venv can `import
mtg_bot_engine`.

If `maturin` isn't on PATH, run via the venv's python:

```bash
../../mtg-bot/.venv-py313/Scripts/python.exe -m maturin develop \
    --release -m rust/pyproject.toml
```

## What's here today (skeleton only)

- `make_synthetic_state(num_battlefield, num_hand, num_library) -> GameState`
- `GameState.clone_once() -> GameState`
- `GameState.clone_n_times_micros(n) -> float` — micro-bench helper
- A handful of read-only getters (`turn_number`, `battlefield_sizes`,
  `hand_sizes`, `library_sizes`, `life_totals`)

There is no game logic yet. The first slice exists to:

1. Prove the maturin / PyO3 / MSVC toolchain works on Win11 + 3.13.
2. Get a head-to-head clone perf number against `GameState.clone()`
   in `src/mtg_bot/game.py` so future card-vocabulary growth has a
   baseline.

The Python smoke test at `tests/test_rust_engine_smoke.py` skips
gracefully when the extension isn't installed, so the existing
test suite still runs cleanly on a fresh checkout.

The bench at `scripts/bench_rust_clone.py` runs the Python
`bench_clone.py` shape alongside the Rust `clone_n_times_micros`
on a state with matching dimensions and prints the speedup.

## Why a separate `pyproject.toml`?

The project's main `pyproject.toml` uses setuptools and ships the
pure-Python `mtg_bot` package. Mixing setuptools and maturin in a
single project file is awkward; a sibling `rust/pyproject.toml`
keeps the Rust extension a separately-installable wheel that can be
developed and rebuilt without touching the main Python build.
