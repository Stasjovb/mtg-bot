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
- **From a worktree, always set `PYTHONPATH=src` when invoking python**, otherwise the editable install in the shared venv resolves `mtg_bot` to the main checkout's source and your worktree changes won't be exercised. Example:
  `PYTHONPATH=src ../../mtg-bot/.venv/Scripts/python.exe -m pytest`
  (Or, on Windows cmd: `set PYTHONPATH=src && ...`.)
- Run tests: `PYTHONPATH=src ../../mtg-bot/.venv/Scripts/python.exe -m pytest` from inside a worktree, or `.venv/Scripts/python.exe -m pytest` from the main checkout.
  (Python 3.13 + coverage.py can intermittently segfault deep in the simulation
  sweep tests. The crash is not reproducible in isolation and no local code
  change fixes it. If pytest exits with an access violation, run
  `scripts/run_tests.py` instead — it retries on segfault.)
- Run browser-driven E2E tests (opt-in, skipped by default):
  `MTG_BOT_E2E=1 .venv/Scripts/python.exe -m pytest tests/test_e2e.py`
  First time only: `.venv/Scripts/python.exe -m pip install playwright`
  then `.venv/Scripts/python.exe -m playwright install chromium`.
- Run JS unit tests for the static UI bundle (Vitest + jsdom):
  `npm test`
  First time only: `npm install` (requires Node 18+).
  Tests live under `tests-js/`. They load `src/mtg_bot/static/app.js`
  into a jsdom fixture and call its globals; see `tests-js/setup.js`.
- Run a game: `.venv/Scripts/python.exe -m mtg_bot`
- Run the UI (localhost): `.venv/Scripts/python.exe -m mtg_bot.ui`
- Run the UI over Tailscale (reachable from phone/laptop on the tailnet):
  `powershell -ExecutionPolicy Bypass -File scripts\serve.ps1`
  First-time firewall rule setup needs an elevated PowerShell.
- Warm the card-image cache (optional, for nicer first-load):
  `.venv/Scripts/python.exe scripts/fetch_card_images.py`
- Ad-hoc screenshot the live UI:
  `.venv/Scripts/python.exe scripts/screenshot_ui.py --url http://127.0.0.1:5002 --out ui.png`

## Scope reminders

- Card pool target: **Edge of Eternities** (Scryfall set code `eoe`). Raw data is cached at `data/edge_of_eternities.json`; regenerate via `scripts/fetch_eoe.py`.
- Real EoE cards come online as mechanics are implemented. Until then, Stage-1 uses synthetic vanilla creatures defined in `src/mtg_bot/cards.py`.
- Architectural decisions that are locked in: full stack-and-priority simulation (not resolve-immediately); Scryfall JSON as the card data source.
