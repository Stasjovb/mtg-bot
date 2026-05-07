# Project rules for Claude

## Development workflow

- **All work happens in a git worktree, not in the main checkout.** The main checkout at `mtg-bot/` stays on `main` and is treated as read-only context for cross-branch comparison. Create a worktree per feature with:
  `git worktree add ../mtg-bot-worktrees/<branch-name> -b feature/<branch-name> main`
  Worktrees live in the sibling directory `mtg-bot-worktrees/`. Remove them after merge with `git worktree remove ../mtg-bot-worktrees/<branch-name>`.
- **Every new feature must be developed on its own branch off `main`.** Do not commit feature work directly to `main`.
- Branch naming: `feature/<short-name>` (e.g. `feature/flying-keyword`, `feature/etb-triggers`).
- **Commit as you go.** Each unit of work is its own commit on the feature branch. Do not batch everything into one monster commit.
- **Tests must pass before every commit.** Run the full test suite; if anything fails, fix it before committing.
- **Do not merge to `main` yourself.** Push the branch for review and wait for the user to approve. Only after explicit approval, merge into `main`.

## Perf monitoring (informational)

- One-time per clone: `git config core.hooksPath hooks`. This points
  git at the version-controlled `hooks/` directory.
- After every commit on `main`, `hooks/post-commit` runs `scripts/bench_clone.py`
  and appends the per-call clone time to `.perf_history.log` (gitignored). It
  also prints the new measurement and the % delta vs the previous logged commit.
- Feature-branch commits are silently skipped (no bench, no log entry).
- Never blocks: if the bench fails or the venv is missing, the hook prints
  to stderr and exits 0 so the commit still succeeds.
- Read the log with `tail .perf_history.log` to see the last several commits'
  perf numbers in context.

## Testing

- Use `pytest`. Tests live under `tests/`.
- **Target coverage: high 90s (≥95%).** Run `pytest --cov=mtg_bot` to check. Before declaring a feature complete, verify coverage has not regressed.
- Every new module needs its own `test_<module>.py`. Cover the happy path, meaningful edge cases, and error paths (invalid inputs, exceptional states).

## Running things

- Virtual env is at `.venv/` in the **main checkout** (`mtg-bot/.venv/`). Worktrees share it. Use `mtg-bot/.venv/Scripts/python.exe` on Windows / `mtg-bot/.venv/bin/python` on macOS-Linux.
- **Recommended interpreter for tests is Python 3.13** (or any 3.12+).
  The shared 3.11 venv hits an intermittent Windows access-violation
  segfault inside coverage.py's C-trace backend during the simulation
  sweep tests. Python 3.12+ has PEP 669 `sys.monitoring`; coverage.py
  auto-uses the `sysmon` backend (already pinned in `pyproject.toml`),
  and the crash does not reproduce. See `docs/segfault-fix.md` for the
  full diagnosis.
  Easiest path: create a parallel 3.13 venv per worktree:
  `py -3.13 -m venv .venv-py313 && .venv-py313/Scripts/python.exe -m pip install -e ".[dev]"`
  then run `PYTHONPATH=src .venv-py313/Scripts/python.exe -m pytest`.
  `.venv-*/` is gitignored.
- **From a worktree, always set `PYTHONPATH=src` when invoking python**, otherwise the editable install in the shared venv resolves `mtg_bot` to the main checkout's source and your worktree changes won't be exercised. Example:
  `PYTHONPATH=src ../../mtg-bot/.venv/Scripts/python.exe -m pytest`
  (Or, on Windows cmd: `set PYTHONPATH=src && ...`.)
- Run tests: `PYTHONPATH=src ../../mtg-bot/.venv/Scripts/python.exe -m pytest` from inside a worktree, or `.venv/Scripts/python.exe -m pytest` from the main checkout.
  (If you're on the 3.11 venv and pytest exits with an access violation,
  switch to the 3.13 venv per the previous bullet — that's the fix.
  See `docs/segfault-fix.md`.)
- **Inner-loop dev iteration: `pytest -n 8 --no-cov`** — ~60s for the
  full suite vs ~270s with the default sequential+coverage (~4.3×
  speedup, 7280 pass / 9 skip / 0 flake observed 2026-05-05 on
  Win11+3.13). Use this while iterating; the default
  with-coverage run remains the gate before commit (coverage must
  stay ≥95%). xdist + sysmon are already dev deps; no setup
  needed. The two contributions are roughly multiplicative:
  `-n 8` parallelizes across 8 worker processes (~3× alone),
  `--no-cov` skips sysmon instrumentation (~3× alone).
- Tests marked `@pytest.mark.isolated` (currently `tests/test_perf_clone.py`)
  are skipped by the default `pytest` invocation — they're sensitive to
  accumulated interpreter state from preceding tests and only run reliably
  alone. Run them with `scripts/run_isolated_tests.py` (own subprocess, no
  coverage), or directly: `pytest -m isolated --override-ini=addopts= --no-cov`.
- Run browser-driven E2E tests (opt-in, skipped by default):
  `MTG_BOT_E2E=1 .venv/Scripts/python.exe -m pytest tests/test_e2e.py`
  First time only: `.venv/Scripts/python.exe -m pip install playwright`
  then `.venv/Scripts/python.exe -m playwright install chromium`.
- Run JS unit tests for the static UI bundle (Vitest + jsdom):
  `npm test`
  First time only: `npm install` (requires Node 18+).
  Tests live under `tests-js/`. They load `src/mtg_bot/static/app.js`
  into a jsdom fixture and call its globals; see `tests-js/setup.js`.
- **GPU available** — `.venv-py313/` has `torch 2.11.0+cu128` (CUDA 12.8 build) installed against an RTX 5090. `torch.cuda.is_available()` returns True; `auto_device()` in `src/mtg_bot/training/trainer.py` picks `cuda` automatically when training. Reinstall the CUDA build with:
  `.venv-py313/Scripts/python.exe -m pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu128`
  Smoke check:
  `.venv-py313/Scripts/python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"`
  Network scale (1024-1024-512 trunk, ~10M params, dual-head AlphaZero — v13 / v15 / v16) is now large enough that GPU inference dominates CPU on every host that has a GPU. As of `feature/eval-gpu-auto-device`: (1) `auto_device()` falls back to `mps` when CUDA isn't available (Apple Silicon remote), and (2) the four NNPimcConfig construction sites in `src/mtg_bot/training/distributed.py` (run_shard_local self-play, run_shard_pull self-play, run_shard_eval_pull new+old) explicitly pass `device=auto_device()`. Each call resolves locally on the host where the shard runs — master picks CUDA, Mac picks MPS, Win10 picks CUDA. `NNPimcConfig.device` default stays `None` (which maps to NNEvaluator's CPU default) so direct test construction `NNPimcConfig(...)` continues to use CPU — needed because tests spawn multiprocessing pools and per-worker CUDA-context init on Windows-spawn semantics deadlocks. The earlier "workers stay CPU-only / Python↔CUDA round-trip overhead beats tiny matmuls" guidance was correct for the v2/v3 25k-65k-param scale and is now stale for production paths.
- Run a game: `.venv/Scripts/python.exe -m mtg_bot`
- Run the UI (localhost): `.venv/Scripts/python.exe -m mtg_bot.ui`
- Run the UI over Tailscale (reachable from phone/laptop on the tailnet):
  `powershell -ExecutionPolicy Bypass -File scripts\serve.ps1`
  First-time firewall rule setup needs an elevated PowerShell.
- Warm the card-image cache (optional, for nicer first-load):
  `.venv/Scripts/python.exe scripts/fetch_card_images.py`
- Ad-hoc screenshot the live UI:
  `.venv/Scripts/python.exe scripts/screenshot_ui.py --url http://127.0.0.1:5002 --out ui.png`

## Distributed flow (master + remotes)

The cluster is one master (Win11 desktop) + N remotes (Mac, Win10).
For day-to-day operations — running iterations, running remote
benches that surface in the training UI, monitoring, aborting — see
**[`docs/RUNNING_DISTRIBUTED.md`](docs/RUNNING_DISTRIBUTED.md)**.

For one-time per-machine bootstrap (Python, repo clone, SSH keys,
Tailscale enrollment), see
[`docs/SETUP_DISTRIBUTED.md`](docs/SETUP_DISTRIBUTED.md).

## Scope reminders

- Card pool target: **Edge of Eternities** (Scryfall set code `eoe`). Raw data is cached at `data/edge_of_eternities.json`; regenerate via `scripts/fetch_eoe.py`.
- Self-play / eval data-gen and the iterate-AlphaZero loop run on the real 17lands deck pool at `data/17lands/eoe_decks.json.gz` (5000 EoE archetypes). `iterate_alphazero.py` requires `--deck-pool` and `data_gen` / `self_play` raise on missing pool — there is no synthetic mono-color fallback any more.
- Architectural decisions that are locked in: full stack-and-priority simulation (not resolve-immediately); Scryfall JSON as the card data source.
- **Eval depth must match self-play depth.** The metric we care about is "did v_{N+1} beat v_N at the deployment configuration", and the deployment configuration is whatever depth self-play used. Eval at a different depth measures something else — a network trained at depth=200 may not generalize linearly to depth=400, so a deeper eval doesn't extrapolate cleanly. `iterate_alphazero.py` already uses `args.nodes` for both self-play and eval (one knob). Standalone eval scripts in `scripts/eval_*` should hard-code `nodes` to whatever the most recent iteration's self-play used, and have a comment pointing here. A pre-iter_005-era script that says `nodes = 400` was templated when iter_004 ran self-play at 400; do NOT propagate that without checking.

## Documenting deliberate divergences

Any shortcut, heuristic, search optimization, or incorrect / outdated implementation of real MTG comprehensive rules **must be documented in `docs/SEARCH_LIMITATIONS.md`** at the time it lands.

This applies to (non-exhaustive):

- Engine code that intentionally diverges from current CR (e.g., outdated combat damage assignment, simplified mana ability rules, unmodeled state-based actions, missing layers).
- Search-side optimizations that approximate or skip legal decisions (e.g., capability-based priority short-circuits, factored decompositions of joint decisions, heuristic move pruning).
- Workarounds that "land" via filter rather than fix (e.g., the data_gen writer-side root-legal visit filter).
- Known-incorrect interactions between specific card mechanics that we accept rather than fix.

For each entry, the doc requires: location (file:line), what the shortcut is, why it's OK or which scenarios make it not-OK, failure mode, fix-scope estimate, and impact estimate (perf gain or strength cost).

If you ship a feature that takes any deliberate shortcut without updating `SEARCH_LIMITATIONS.md`, you're shipping technical debt that nobody else will know about. Pause and add the entry first.
